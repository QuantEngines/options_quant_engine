"""
Calibrated probabilistic direction head.

This module estimates P(up | X) from regime, flow, and execution-quality
features, then optionally applies a calibration map. It also produces an
uncertainty score used by runtime decision logic.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Any

from config.direction_probability_policy import (
    DIRECTION_PROBABILITY_DIRECTIONAL_BIAS,
    DIRECTION_PROBABILITY_LOGIT,
    DIRECTION_PROBABILITY_MICROSTRUCTURE_FRICTION,
    DIRECTION_PROBABILITY_UNCERTAINTY,
)
from config.policy_resolver import resolve_mapping
from strategy.score_calibration import ScoreCalibrator


logger = logging.getLogger(__name__)

_DEFAULT_CALIBRATOR_PATH = Path("models_store") / "direction_probability_calibrator.json"
_DEFAULT_METRICS_LOG_EVERY_N = 250
_CALIBRATOR_CACHE: dict[str, tuple[float, ScoreCalibrator]] = {}
_SEGMENTED_CALIBRATOR_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CALIBRATION_SEGMENT_METRICS: dict[str, int] = {
    "total": 0,
    "segment_hits": 0,
    "fallback_hits": 0,
}
_CALIBRATION_SEGMENT_METRICS_LOCK = threading.Lock()
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _directional_bias_policy() -> dict[str, Any]:
    return resolve_mapping(
        "signal_engine.direction_probability_head.directional_bias",
        DIRECTION_PROBABILITY_DIRECTIONAL_BIAS,
    )


def _microstructure_friction_policy() -> dict[str, Any]:
    return resolve_mapping(
        "signal_engine.direction_probability_head.microstructure_friction",
        DIRECTION_PROBABILITY_MICROSTRUCTURE_FRICTION,
    )


def _logit_policy() -> dict[str, Any]:
    return resolve_mapping(
        "signal_engine.direction_probability_head.logit",
        DIRECTION_PROBABILITY_LOGIT,
    )


def _uncertainty_policy() -> dict[str, Any]:
    return resolve_mapping(
        "signal_engine.direction_probability_head.uncertainty",
        DIRECTION_PROBABILITY_UNCERTAINTY,
    )


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except Exception:
        return default


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _as_upper(value: Any) -> str:
    return str(value or "").upper().strip()


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _binary_entropy(probability: float) -> float:
    p = _clip(float(probability), 1e-6, 1.0 - 1e-6)
    return (-(p * math.log(p) + (1.0 - p) * math.log(1.0 - p))) / math.log(2.0)


def _provider_status_score(status: str) -> float:
    policy = _microstructure_friction_policy()
    mapping = {
        "GOOD": float(policy.get("provider_good_score", 0.0)),
        "CAUTION": float(policy.get("provider_caution_score", 0.5)),
        "WEAK": float(policy.get("provider_weak_score", 1.0)),
    }
    return mapping.get(
        _as_upper(status),
        float(policy.get("provider_unknown_score", 0.5)),
    )


def _normalize_rr_points(rr_value: Any, rr_unit: Any = None) -> float | None:
    rr = _safe_float(rr_value, None)
    if rr is None:
        return None
    unit = _as_upper(rr_unit)
    if unit == "DECIMAL":
        return rr * 100.0
    return rr


def _directional_signal_bias(
    *,
    final_flow_signal: Any,
    spot_vs_flip: Any,
    hedging_bias: Any,
    gamma_event: Any,
    gamma_regime: Any,
    oi_velocity_score: Any,
    rr_value: Any,
    rr_unit: Any,
    rr_momentum: Any,
    volume_pcr_atm: Any,
    gamma_flip_drift: Any,
) -> float:
    policy = _directional_bias_policy()
    score = 0.0

    flow = _as_upper(final_flow_signal)
    if flow == "BULLISH_FLOW":
        score += float(policy.get("flow_bullish_score", 1.30))
    elif flow == "BEARISH_FLOW":
        score += float(policy.get("flow_bearish_score", -1.30))

    flip = _as_upper(spot_vs_flip)
    if flip == "ABOVE_FLIP":
        score += float(policy.get("above_flip_score", 0.85))
    elif flip == "BELOW_FLIP":
        score += float(policy.get("below_flip_score", -0.85))

    hedge = _as_upper(hedging_bias)
    if hedge == "UPSIDE_ACCELERATION":
        score += float(policy.get("upside_acceleration_score", 1.00))
    elif hedge == "DOWNSIDE_ACCELERATION":
        score += float(policy.get("downside_acceleration_score", -1.00))

    if _as_upper(gamma_event) == "GAMMA_SQUEEZE":
        if flip == "ABOVE_FLIP":
            score += float(policy.get("gamma_squeeze_flip_score", 0.35))
        elif flip == "BELOW_FLIP":
            score -= float(policy.get("gamma_squeeze_flip_score", 0.35))

    regime = _as_upper(gamma_regime)
    if regime in {"NEGATIVE_GAMMA", "SHORT_GAMMA_ZONE"}:
        negative_gamma_flip_score = float(policy.get("negative_gamma_flip_score", 0.15))
        score += (
            negative_gamma_flip_score
            if flip == "ABOVE_FLIP"
            else -negative_gamma_flip_score
            if flip == "BELOW_FLIP"
            else 0.0
        )

    oi_velocity = _safe_float(oi_velocity_score, None)
    if oi_velocity is not None:
        oi_clip = abs(float(policy.get("oi_velocity_clip", 0.70)))
        score += _clip(oi_velocity, -oi_clip, oi_clip) * float(
            policy.get("oi_velocity_weight", 0.55)
        )

    rr_points = _normalize_rr_points(rr_value, rr_unit)
    if rr_points is not None:
        # Positive RR implies put skew dominance (bearish), negative RR bullish.
        rr_scale = max(abs(float(policy.get("rr_scale_points", 2.0))), 1e-9)
        rr_clip = abs(float(policy.get("rr_clip", 1.0)))
        rr_scaled = _clip(-(rr_points / rr_scale), -rr_clip, rr_clip)
        score += float(policy.get("rr_weight", 0.60)) * rr_scaled

    rr_m = _as_upper(rr_momentum)
    if rr_m == "RISING_PUT_SKEW":
        score += float(policy.get("rr_rising_put_skew_score", -0.20))
    elif rr_m == "FALLING_PUT_SKEW":
        score += float(policy.get("rr_falling_put_skew_score", 0.20))

    pcr = _safe_float(volume_pcr_atm, None)
    if pcr is not None:
        pcr_scale = max(abs(float(policy.get("pcr_scale", 0.60))), 1e-9)
        pcr_clip = abs(float(policy.get("pcr_clip", 0.35)))
        pcr_neutral = float(policy.get("pcr_neutral", 1.0))
        score += _clip((pcr_neutral - pcr) / pcr_scale, -pcr_clip, pcr_clip)

    flip_drift = None
    if isinstance(gamma_flip_drift, dict):
        flip_drift = _safe_float(gamma_flip_drift.get("drift"), None)
    if flip_drift is not None:
        drift_scale = max(abs(float(policy.get("flip_drift_scale_points", 250.0))), 1e-9)
        drift_clip = abs(float(policy.get("flip_drift_clip", 0.35)))
        score += _clip(flip_drift / drift_scale, -drift_clip, drift_clip)

    return float(score)


def _microstructure_friction(
    *,
    provider_health_summary: Any,
    provider_health_blocking_status: Any,
    core_effective_priced_ratio: Any,
    core_one_sided_quote_ratio: Any,
    core_quote_integrity_health: Any,
) -> float:
    policy = _microstructure_friction_policy()
    provider_component = _provider_status_score(_as_upper(provider_health_summary))
    blocking_component = (
        float(policy.get("blocking_component_score", 1.0))
        if _as_upper(provider_health_blocking_status) == "BLOCK"
        else 0.0
    )

    quote_integrity = _as_upper(core_quote_integrity_health)
    quote_component = (
        float(policy.get("quote_weak_score", 1.0))
        if quote_integrity == "WEAK"
        else float(policy.get("quote_caution_score", 0.5))
        if quote_integrity == "CAUTION"
        else float(policy.get("quote_good_score", 0.0))
    )

    priced_ratio = _safe_float(core_effective_priced_ratio, None)
    priced_component = 0.5
    if priced_ratio is not None:
        priced_reference = max(
            abs(float(policy.get("priced_ratio_reference", 0.60))),
            1e-9,
        )
        priced_component = _clip(
            (priced_reference - priced_ratio) / priced_reference,
            0.0,
            1.0,
        )

    one_sided_ratio = _safe_float(core_one_sided_quote_ratio, None)
    one_sided_reference = max(
        abs(float(policy.get("one_sided_ratio_reference", 0.55))),
        1e-9,
    )
    one_sided_component = (
        0.0
        if one_sided_ratio is None
        else _clip(one_sided_ratio / one_sided_reference, 0.0, 1.0)
    )

    friction = (
        float(policy.get("provider_weight", 0.30)) * provider_component
        + float(policy.get("blocking_weight", 0.30)) * blocking_component
        + float(policy.get("quote_weight", 0.20)) * quote_component
        + float(policy.get("priced_ratio_weight", 0.10)) * priced_component
        + float(policy.get("one_sided_weight", 0.10)) * one_sided_component
    )
    return _clip(friction, 0.0, 1.0)


def _load_calibrator(calibrator_path: str | None) -> ScoreCalibrator | None:
    path = Path(calibrator_path or _DEFAULT_CALIBRATOR_PATH)
    if not path.is_absolute():
        # Resolve relative to repository root (stable across launch contexts),
        # not process CWD which depends on how the app was started.
        path = _REPO_ROOT / path
    if not path.exists():
        return None

    key = str(path.resolve())
    mtime = float(path.stat().st_mtime)
    cached = _CALIBRATOR_CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        calibrator = ScoreCalibrator.load_from_file(str(path))
    except Exception:
        return None

    _CALIBRATOR_CACHE[key] = (mtime, calibrator)
    return calibrator


def _resolve_segmented_calibrator_path(calibrator_path: str | None, segmented_calibrator_path: str | None) -> Path | None:
    if segmented_calibrator_path:
        path = Path(segmented_calibrator_path)
        if not path.is_absolute():
            path = _REPO_ROOT / path
        return path if path.exists() else None

    base = Path(calibrator_path or _DEFAULT_CALIBRATOR_PATH)
    if not base.is_absolute():
        base = _REPO_ROOT / base
    if not base.exists():
        return None

    parent = base.parent
    stem = base.stem
    candidates = sorted(parent.glob(f"{stem}_*_segments.json"))
    if not candidates:
        return None

    # Deterministic preference so the default runtime behavior is predictable.
    priority = ["gamma_regime", "macro_regime", "volatility_regime"]
    for key in priority:
        for candidate in candidates:
            if f"_{key}_segments.json" in candidate.name:
                return candidate
    return candidates[0]


def _load_segmented_calibrator_bundle(calibrator_path: str | None, segmented_calibrator_path: str | None) -> dict[str, Any] | None:
    resolved = _resolve_segmented_calibrator_path(calibrator_path, segmented_calibrator_path)
    if resolved is None:
        return None

    key = str(resolved.resolve())
    mtime = float(resolved.stat().st_mtime)
    cached = _SEGMENTED_CALIBRATOR_CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        return None

    meta = payload.get("meta") if isinstance(payload, dict) else None
    groups = payload.get("groups") if isinstance(payload, dict) else None
    if not isinstance(meta, dict) or not isinstance(groups, dict):
        return None

    segment_calibrators: dict[str, ScoreCalibrator] = {}
    for group_name, state in groups.items():
        if not isinstance(state, dict):
            continue
        try:
            segment_calibrators[str(group_name)] = ScoreCalibrator.from_state(state)
        except Exception:
            continue

    if not segment_calibrators:
        return None

    bundle = {
        "path": str(resolved),
        "regime_column": str(meta.get("regime_column") or "").strip(),
        "segments": segment_calibrators,
    }
    _SEGMENTED_CALIBRATOR_CACHE[key] = (mtime, bundle)
    return bundle


def _record_calibration_segment_metric(*, segment_selected: bool) -> None:
    with _CALIBRATION_SEGMENT_METRICS_LOCK:
        _CALIBRATION_SEGMENT_METRICS["total"] = int(_CALIBRATION_SEGMENT_METRICS.get("total", 0)) + 1
        key = "segment_hits" if segment_selected else "fallback_hits"
        _CALIBRATION_SEGMENT_METRICS[key] = int(_CALIBRATION_SEGMENT_METRICS.get(key, 0)) + 1


def reset_direction_head_calibration_metrics() -> None:
    with _CALIBRATION_SEGMENT_METRICS_LOCK:
        _CALIBRATION_SEGMENT_METRICS["total"] = 0
        _CALIBRATION_SEGMENT_METRICS["segment_hits"] = 0
        _CALIBRATION_SEGMENT_METRICS["fallback_hits"] = 0


def get_direction_head_calibration_metrics() -> dict[str, float]:
    with _CALIBRATION_SEGMENT_METRICS_LOCK:
        total = int(_CALIBRATION_SEGMENT_METRICS.get("total", 0))
        segment_hits = int(_CALIBRATION_SEGMENT_METRICS.get("segment_hits", 0))
        fallback_hits = int(_CALIBRATION_SEGMENT_METRICS.get("fallback_hits", 0))
    segment_hit_rate = (segment_hits / total) if total > 0 else 0.0
    fallback_rate = (fallback_hits / total) if total > 0 else 0.0
    return {
        "total": total,
        "segment_hits": segment_hits,
        "fallback_hits": fallback_hits,
        "segment_hit_rate": round(float(segment_hit_rate), 6),
        "fallback_rate": round(float(fallback_rate), 6),
    }


def _maybe_log_calibration_segment_metrics(log_every_n: int) -> None:
    if log_every_n <= 0:
        return
    metrics = get_direction_head_calibration_metrics()
    total = int(metrics.get("total", 0))
    if total <= 0 or (total % log_every_n) != 0:
        return
    logger.info(
        "Direction head calibration routing: total=%d segment_hits=%d fallback_hits=%d segment_hit_rate=%.3f fallback_rate=%.3f",
        total,
        int(metrics.get("segment_hits", 0)),
        int(metrics.get("fallback_hits", 0)),
        float(metrics.get("segment_hit_rate", 0.0)),
        float(metrics.get("fallback_rate", 0.0)),
    )


def _select_segment_key(
    regime_column: str,
    *,
    gamma_regime: Any,
    macro_regime: Any,
    volatility_regime: Any,
) -> str | None:
    col = str(regime_column or "").strip().lower()
    if not col:
        return None
    if col == "gamma_regime":
        candidate = _as_upper(gamma_regime)
        return candidate or None
    if col == "macro_regime":
        candidate = _as_upper(macro_regime)
        return candidate or None
    if col in {"volatility_regime", "vol_regime"}:
        candidate = _as_upper(volatility_regime)
        return candidate or None
    return None


def compute_direction_probability_head(
    *,
    final_flow_signal: Any,
    spot_vs_flip: Any,
    hedging_bias: Any,
    gamma_event: Any,
    gamma_regime: Any,
    macro_regime: Any = None,
    volatility_regime: Any = None,
    oi_velocity_score: Any = None,
    rr_value: Any = None,
    rr_unit: Any = "VOL_POINTS",
    rr_momentum: Any = None,
    volume_pcr_atm: Any = None,
    gamma_flip_drift: Any = None,
    hybrid_move_probability: Any = None,
    vote_bull_probability: Any = 0.5,
    provider_health_summary: Any = None,
    provider_health_blocking_status: Any = None,
    core_effective_priced_ratio: Any = None,
    core_one_sided_quote_ratio: Any = None,
    core_quote_integrity_health: Any = None,
    calibrator_path: str | None = None,
    segmented_calibrator_path: str | None = None,
    calibration_metrics_log_every_n: Any = None,
    apply_calibration: bool = True,
) -> dict[str, Any]:
    directional_bias = _directional_signal_bias(
        final_flow_signal=final_flow_signal,
        spot_vs_flip=spot_vs_flip,
        hedging_bias=hedging_bias,
        gamma_event=gamma_event,
        gamma_regime=gamma_regime,
        oi_velocity_score=oi_velocity_score,
        rr_value=rr_value,
        rr_unit=rr_unit,
        rr_momentum=rr_momentum,
        volume_pcr_atm=volume_pcr_atm,
        gamma_flip_drift=gamma_flip_drift,
    )
    friction = _microstructure_friction(
        provider_health_summary=provider_health_summary,
        provider_health_blocking_status=provider_health_blocking_status,
        core_effective_priced_ratio=core_effective_priced_ratio,
        core_one_sided_quote_ratio=core_one_sided_quote_ratio,
        core_quote_integrity_health=core_quote_integrity_health,
    )

    move_probability = _safe_float(hybrid_move_probability, 0.5)
    vote_up = _clip(_safe_float(vote_bull_probability, 0.5) or 0.5, 0.0, 1.0)
    logit_policy = _logit_policy()
    neutral_probability = float(logit_policy.get("neutral_probability", 0.50))

    logit = (
        float(logit_policy.get("intercept", -0.05))
        + float(logit_policy.get("directional_bias_weight", 0.90)) * directional_bias
        + float(logit_policy.get("vote_probability_weight", 0.80))
        * (vote_up - neutral_probability)
        + float(logit_policy.get("move_probability_weight", 0.55))
        * ((move_probability or neutral_probability) - neutral_probability)
    )
    # Microstructure friction attenuates effective directional edge.
    logit *= (
        1.0
        - float(logit_policy.get("friction_attenuation", 0.60)) * friction
    )

    probability_up_raw = _sigmoid(logit)
    probability_up = probability_up_raw
    calibration_applied = False
    calibrator_loaded = False

    calibrator = _load_calibrator(calibrator_path)
    selected_segment = None
    segmented_bundle = _load_segmented_calibrator_bundle(calibrator_path, segmented_calibrator_path)
    if apply_calibration and segmented_bundle is not None:
        regime_column = str(segmented_bundle.get("regime_column") or "")
        selected_key = _select_segment_key(
            regime_column,
            gamma_regime=gamma_regime,
            macro_regime=macro_regime,
            volatility_regime=volatility_regime,
        )
        segment_calibrator = None
        if selected_key:
            segment_calibrator = segmented_bundle.get("segments", {}).get(selected_key)
        if segment_calibrator is not None:
            calibrator = segment_calibrator
            selected_segment = selected_key

    if apply_calibration and calibrator is not None:
        calibrator_loaded = True
        _record_calibration_segment_metric(segment_selected=selected_segment is not None)
        log_every_n = int(
            max(
                0,
                _safe_float(
                    calibration_metrics_log_every_n,
                    float(_DEFAULT_METRICS_LOG_EVERY_N),
                )
                or 0.0,
            )
        )
        _maybe_log_calibration_segment_metrics(log_every_n)
        try:
            calibrated_score = calibrator.calibrate(float(probability_up_raw * 100.0))
            probability_up = _clip(float(calibrated_score) / 100.0, 0.0, 1.0)
            calibration_applied = True
        except Exception:
            probability_up = probability_up_raw

    disagreement = abs(probability_up - vote_up)
    entropy = _binary_entropy(probability_up)
    # Weights are normalised to sum exactly to 1.0:
    #   entropy      → 0.4783  (≈ 55/115)
    #   disagreement → 0.2609  (≈ 30/115)
    #   friction     → 0.2609  (≈ 30/115)
    # This prevents the composite from saturating at 1.0 and masking
    # individual component contributions in the output diagnostics.
    uncertainty_policy = _uncertainty_policy()
    uncertainty = _clip(
        float(uncertainty_policy.get("entropy_weight", 0.4783)) * entropy
        + float(uncertainty_policy.get("disagreement_weight", 0.2609)) * disagreement
        + float(uncertainty_policy.get("friction_weight", 0.2609)) * friction,
        0.0,
        1.0,
    )

    return {
        "probability_up_raw": round(float(probability_up_raw), 6),
        "probability_up": round(float(probability_up), 6),
        "probability_down": round(float(1.0 - probability_up), 6),
        "logit": round(float(logit), 6),
        "directional_bias_score": round(float(directional_bias), 6),
        "microstructure_friction_score": round(float(friction), 6),
        "disagreement_with_vote": round(float(disagreement), 6),
        "uncertainty": round(float(uncertainty), 6),
        "confidence": round(float(1.0 - uncertainty), 6),
        "calibrator_loaded": bool(calibrator_loaded),
        "calibration_applied": bool(calibration_applied),
        "calibration_segment": selected_segment,
        "calibration_segment_metrics": get_direction_head_calibration_metrics(),
    }

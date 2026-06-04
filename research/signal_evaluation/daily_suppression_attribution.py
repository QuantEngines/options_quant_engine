"""Daily directional-suppression attribution.

This research-only diagnostic explains why directional rows did not become
trade-qualified rows. It does not change runtime thresholds, parameter packs,
data-source routing, or execution behavior.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.signal_evaluation_scoring import SIGNAL_EVALUATION_SELECTION_POLICY
from config.signal_policy import get_trade_runtime_thresholds
from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH
from research.signal_evaluation.signal_quality_model_audit import (
    _atomic_write_csv,
    _atomic_write_text,
    _round_or_none,
    _sanitize_value,
)
from utils.timestamp_helpers import coerce_timestamp_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DAILY_SUPPRESSION_ATTRIBUTION_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "daily_suppression_attribution"
)

LATEST_JSON_FILENAME = "latest_daily_suppression_attribution.json"
LATEST_MARKDOWN_FILENAME = "latest_daily_suppression_attribution.md"
LATEST_SUPPRESSED_ROWS_FILENAME = "latest_daily_suppression_attribution_suppressed_rows.csv"

BLOCKER_LABELS = {
    "runtime_composite_below_threshold": "Runtime composite below threshold",
    "move_probability_below_floor": "Move probability below floor",
    "trade_strength_below_threshold": "Trade strength below threshold",
    "provider_execution_blocked": "Provider execution blocked",
    "provider_direction_blocked": "Provider direction blocked",
    "provider_health_not_good": "Provider health not GOOD",
    "data_quality_not_strong": "Data quality not STRONG",
    "weak_signal_quality": "Weak signal quality",
    "at_gamma_flip": "At gamma flip / pinning zone",
    "risk_off_macro": "Macro regime RISK_OFF",
    "risk_off_global": "Global risk RISK_OFF",
    "low_ta_entry_timing": "Low TA entry-timing score",
}

PRIMARY_BLOCKER_ORDER = (
    "provider_execution_blocked",
    "provider_direction_blocked",
    "runtime_composite_below_threshold",
    "move_probability_below_floor",
    "trade_strength_below_threshold",
    "weak_signal_quality",
    "data_quality_not_strong",
    "provider_health_not_good",
    "at_gamma_flip",
    "risk_off_macro",
    "risk_off_global",
    "low_ta_entry_timing",
)

COMPONENT_LABELS = {
    "trade_strength": "Trade strength",
    "move_probability": "Move probability",
    "confirmation": "Confirmation",
    "data_quality": "Data quality",
    "gamma_stability": "Gamma stability",
}

CONFIRMATION_SCORE_MAP = {
    "STRONG_CONFIRMATION": 100.0,
    "CONFIRMED": 85.0,
    "MIXED": 55.0,
    "CONFLICT": 25.0,
    "NO_DIRECTION": 10.0,
}

DATA_QUALITY_SCORE_MAP = {
    "STRONG": 100.0,
    "GOOD": 85.0,
    "CAUTION": 60.0,
    "WEAK": 35.0,
}


def _load_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset_path = Path(path)
    if not dataset_path.exists():
        return pd.DataFrame()
    return pd.read_csv(dataset_path, low_memory=False)


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _text_series(frame: pd.DataFrame, column: str, default: str = "UNKNOWN") -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="object")
    return (
        frame[column]
        .astype("object")
        .where(frame[column].notna(), default)
        .astype(str)
        .str.strip()
        .replace({"": default, "nan": default, "NaN": default, "None": default})
    )


def _num_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    raw = frame[column]
    if raw.dtype == bool:
        return raw.fillna(False)
    normalized = raw.astype("object").where(raw.notna(), "").astype(str).str.strip().str.lower()
    return normalized.isin({"true", "1", "yes", "y", "block", "blocked"})


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalised_runtime_weights() -> dict[str, float]:
    thresholds = get_trade_runtime_thresholds()
    raw = {
        "trade_strength": float(thresholds.get("composite_weight_trade_strength", 0.50) or 0.0),
        "move_probability": float(thresholds.get("composite_weight_move_probability", 0.20) or 0.0),
        "confirmation": float(thresholds.get("composite_weight_confirmation", 0.15) or 0.0),
        "data_quality": float(thresholds.get("composite_weight_data_quality", 0.10) or 0.0),
        "gamma_stability": float(thresholds.get("composite_weight_gamma_stability", 0.05) or 0.0),
    }
    raw = {key: max(0.0, value) for key, value in raw.items()}
    total = sum(raw.values())
    if total <= 0:
        raw = {
            "trade_strength": 0.50,
            "move_probability": 0.20,
            "confirmation": 0.15,
            "data_quality": 0.10,
            "gamma_stability": 0.05,
        }
        total = 1.0
    return {key: value / total for key, value in raw.items()}


def _normalize_gamma_vol(raw_score: pd.Series) -> pd.Series:
    thresholds = get_trade_runtime_thresholds()
    scale = max(float(thresholds.get("gamma_vol_normalization_scale", 100.0) or 100.0), 1.0)
    lower = _clip(float(thresholds.get("gamma_vol_winsor_lower", 12.0) or 12.0), 0.0, 95.0)
    upper = _clip(float(thresholds.get("gamma_vol_winsor_upper", 88.0) or 88.0), lower + 1.0, 100.0)
    scaled = (pd.to_numeric(raw_score, errors="coerce").fillna(0.0) / scale * 100.0).clip(0.0, 100.0)
    winsorized = scaled.clip(lower, upper)
    normalized = ((winsorized - lower) / max(upper - lower, 1.0) * 100.0).round().clip(0.0, 100.0)
    return normalized.astype("float64")


def _parse_component_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        payload = value
    elif isinstance(value, str) and value.strip() and value.strip() not in {"{}", "nan", "None"}:
        try:
            payload = json.loads(value)
        except Exception:
            return None
    else:
        return None
    components = payload.get("components")
    if not isinstance(components, dict):
        return None
    return payload


def _runtime_component_frame(suppressed: pd.DataFrame, probability_floor: float) -> tuple[pd.DataFrame, str]:
    """Return per-row component scores/contributions for suppressed rows.

    Older rows do not have exact runtime component JSON, so this falls back to
    a point-in-time-field reconstruction using the current runtime policy. New
    rows should use captured JSON when available.
    """
    weights = _normalised_runtime_weights()
    thresholds = get_trade_runtime_thresholds()
    move_cap = float(thresholds.get("move_probability_score_cap", 75.0) or 75.0)
    rows: list[dict[str, Any]] = []
    exact_count = 0

    component_payloads = (
        suppressed.get("runtime_composite_components", pd.Series(index=suppressed.index, dtype=object))
        if "runtime_composite_components" in suppressed.columns
        else pd.Series(index=suppressed.index, dtype=object)
    )
    trade_strength = _num_series(suppressed, "trade_strength")
    probability = _num_series(suppressed, "hybrid_move_probability").fillna(_num_series(suppressed, "move_probability"))
    confirmation = _text_series(suppressed, "confirmation_status", default="")
    data_quality = _text_series(suppressed, "data_quality_status", default="")
    gamma_accel = _num_series(suppressed, "gamma_vol_acceleration_score")
    gamma_stability = 100.0 - _normalize_gamma_vol(gamma_accel)

    for idx in suppressed.index:
        parsed = _parse_component_payload(component_payloads.get(idx))
        row: dict[str, Any] = {"_index": idx}
        if parsed is not None:
            exact_count += 1
            for component in COMPONENT_LABELS:
                component_payload = parsed.get("components", {}).get(component, {})
                score = pd.to_numeric(component_payload.get("score"), errors="coerce")
                weight = pd.to_numeric(component_payload.get("weight"), errors="coerce")
                weighted = pd.to_numeric(component_payload.get("weighted_contribution"), errors="coerce")
                deficit = pd.to_numeric(component_payload.get("weighted_deficit_to_100"), errors="coerce")
                row[f"{component}_score"] = float(score) if pd.notna(score) else None
                row[f"{component}_weight"] = float(weight) if pd.notna(weight) else weights[component]
                row[f"{component}_weighted_contribution"] = float(weighted) if pd.notna(weighted) else None
                row[f"{component}_weighted_deficit_to_100"] = float(deficit) if pd.notna(deficit) else None
            row["estimated_pre_adjust_score"] = parsed.get("pre_adjust_score")
            for adjustment_key in (
                "feature_reliability_composite_penalty",
                "after_feature_reliability_score",
                "regime_composite_adjustment_delta",
                "after_regime_adjustment_score",
                "score_calibration_input_score",
                "score_calibration_output_score",
                "score_calibration_applied",
                "score_calibration_segment_key",
                "time_decay_factor",
                "after_time_decay_score",
                "supplement_candidate_triggered",
                "supplement_apply_to_score",
                "supplement_candidate_adjustment",
                "supplement_score_adjustment",
                "final_score",
            ):
                row[adjustment_key] = parsed.get(adjustment_key)
            row["runtime_composite_supplement_candidate_adjustment"] = parsed.get(
                "supplement_candidate_adjustment",
                parsed.get("runtime_composite_supplement_candidate_adjustment"),
            )
            row["runtime_component_source"] = "captured_json"
        else:
            component_scores = {
                "trade_strength": _clip(float(trade_strength.get(idx)) if pd.notna(trade_strength.get(idx)) else 0.0, 0.0, 100.0),
                "move_probability": _clip(
                    (float(probability.get(idx)) if pd.notna(probability.get(idx)) else 0.0) * 100.0,
                    0.0,
                    move_cap,
                ),
                "confirmation": CONFIRMATION_SCORE_MAP.get(str(confirmation.get(idx)).upper(), 45.0),
                "data_quality": DATA_QUALITY_SCORE_MAP.get(str(data_quality.get(idx)).upper(), 50.0),
                "gamma_stability": _clip(float(gamma_stability.get(idx)) if pd.notna(gamma_stability.get(idx)) else 100.0, 0.0, 100.0),
            }
            weighted_total = 0.0
            for component, score in component_scores.items():
                weight = weights[component]
                weighted = float(score) * weight
                deficit = (100.0 - float(score)) * weight
                row[f"{component}_score"] = float(score)
                row[f"{component}_weight"] = weight
                row[f"{component}_weighted_contribution"] = weighted
                row[f"{component}_weighted_deficit_to_100"] = deficit
                weighted_total += weighted
            row["estimated_pre_adjust_score"] = int(_clip(round(weighted_total), 0, 100))
            row["runtime_component_source"] = "estimated_from_dataset_fields"
        rows.append(row)

    component_frame = pd.DataFrame(rows).set_index("_index") if rows else pd.DataFrame(index=suppressed.index)
    if component_frame.empty:
        return component_frame, "none"
    if exact_count == len(component_frame):
        source = "captured_json"
    elif exact_count > 0:
        source = "mixed_captured_and_estimated"
    else:
        source = "estimated_from_dataset_fields"

    deficit_columns = [f"{component}_weighted_deficit_to_100" for component in COMPONENT_LABELS]
    available_deficits = component_frame[deficit_columns].apply(pd.to_numeric, errors="coerce")
    if not available_deficits.empty:
        component_frame["primary_component_drag"] = (
            available_deficits.idxmax(axis=1).astype(str).str.replace("_weighted_deficit_to_100", "", regex=False)
        )
    else:
        component_frame["primary_component_drag"] = "UNKNOWN"
    component_frame["estimated_composite_residual"] = (
        _num_series(suppressed, "runtime_composite_score") - pd.to_numeric(component_frame.get("estimated_pre_adjust_score"), errors="coerce")
    )
    component_frame["move_probability_below_floor_component"] = probability.notna() & (probability < probability_floor)
    return component_frame, source


def attach_runtime_component_attribution(
    frame: pd.DataFrame,
    *,
    probability_floor: float | None = None,
) -> tuple[pd.DataFrame, str]:
    """Attach runtime-component attribution columns to a signal frame.

    This helper is research-only. It uses captured component JSON when present
    and otherwise reconstructs component scores from point-in-time fields.
    """
    if frame is None or frame.empty:
        return pd.DataFrame(), "none"
    floor = (
        float(probability_floor)
        if probability_floor is not None
        else float(SIGNAL_EVALUATION_SELECTION_POLICY.get("move_probability_floor", 0.60))
    )
    working = frame.copy()
    component_frame, source = _runtime_component_frame(working, floor)
    if component_frame.empty:
        return working, source
    for column in component_frame.columns:
        working[column] = component_frame[column]
    return working, source


def _component_summary(
    suppressed: pd.DataFrame,
    component_frame: pd.DataFrame,
    probability_floor: float,
) -> list[dict[str, Any]]:
    if component_frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    primary = _text_series(component_frame, "primary_component_drag", default="UNKNOWN").value_counts()
    effective_strength_threshold = _num_series(suppressed, "effective_min_trade_strength_threshold")
    probability = _num_series(suppressed, "hybrid_move_probability").fillna(_num_series(suppressed, "move_probability"))
    low_masks = {
        "trade_strength": _num_series(suppressed, "trade_strength") < effective_strength_threshold,
        "move_probability": probability < probability_floor,
        "confirmation": _text_series(suppressed, "confirmation_status", default="").str.upper().isin({"MIXED", "CONFLICT", "NO_DIRECTION", ""}),
        "data_quality": _text_series(suppressed, "data_quality_status", default="").str.upper().isin({"CAUTION", "WEAK", ""}),
        "gamma_stability": _num_series(component_frame, "gamma_stability_score") < 60.0,
    }
    for component, label in COMPONENT_LABELS.items():
        score = _num_series(component_frame, f"{component}_score")
        weighted = _num_series(component_frame, f"{component}_weighted_contribution")
        deficit = _num_series(component_frame, f"{component}_weighted_deficit_to_100")
        low_mask = low_masks.get(component, pd.Series(False, index=suppressed.index)).fillna(False)
        rows.append(
            {
                "component": component,
                "label": label,
                "avg_component_score": _round_or_none(float(score.dropna().mean()), 4) if score.notna().any() else None,
                "avg_weighted_contribution": _round_or_none(float(weighted.dropna().mean()), 4) if weighted.notna().any() else None,
                "avg_weighted_deficit_to_100": _round_or_none(float(deficit.dropna().mean()), 4) if deficit.notna().any() else None,
                "low_component_count": int(low_mask.sum()),
                "low_component_share": _round_or_none(float(low_mask.sum()) / max(len(suppressed), 1), 4),
                "primary_drag_count": int(primary.get(component, 0)),
                "primary_drag_share": _round_or_none(float(primary.get(component, 0)) / max(len(suppressed), 1), 4),
            }
        )
    return sorted(rows, key=lambda item: (-int(item["primary_drag_count"]), -float(item["avg_weighted_deficit_to_100"] or 0.0)))


def _runtime_adjustment_summary(component_frame: pd.DataFrame, suppressed: pd.DataFrame) -> dict[str, Any]:
    if component_frame.empty:
        return {"status": "NO_COMPONENT_ROWS"}
    source_counts = _value_counts(component_frame, "runtime_component_source")
    estimated_pre_adjust = pd.to_numeric(component_frame.get("estimated_pre_adjust_score"), errors="coerce")
    observed_final = _num_series(suppressed, "runtime_composite_score")
    observed_base = _num_series(suppressed, "runtime_composite_base_score")
    summary: dict[str, Any] = {
        "component_source_counts": source_counts,
        "estimated_pre_adjust_score": _summary_stats(estimated_pre_adjust),
        "observed_runtime_composite_score": _summary_stats(observed_final),
        "observed_runtime_composite_base_score": _summary_stats(observed_base),
        "final_minus_estimated_pre_adjust": _summary_stats(observed_final - estimated_pre_adjust),
        "base_minus_estimated_pre_adjust": _summary_stats(observed_base - estimated_pre_adjust),
    }
    for column in (
        "feature_reliability_composite_penalty",
        "regime_composite_adjustment_delta",
        "score_calibration_input_score",
        "score_calibration_output_score",
        "time_decay_factor",
        "runtime_composite_supplement_candidate_adjustment",
        "supplement_score_adjustment",
        "final_score",
    ):
        source = component_frame[column] if column in component_frame.columns else suppressed.get(column, pd.Series(dtype=float))
        if pd.to_numeric(source, errors="coerce").notna().any():
            summary[column] = _summary_stats(source)
        else:
            summary[column] = {"status": "not_captured"}
    for column in (
        "score_calibration_applied",
        "supplement_candidate_triggered",
        "supplement_apply_to_score",
    ):
        if column in component_frame.columns and component_frame[column].notna().any():
            summary[column] = _value_counts(component_frame, column)
        else:
            summary[column] = [{"value": "not_captured", "count": int(len(component_frame)), "share": 1.0}]
    return summary


def _session_frame(frame: pd.DataFrame, report_date: str | None) -> tuple[pd.DataFrame, str | None]:
    if frame.empty or "signal_timestamp" not in frame.columns:
        return frame.iloc[0:0].copy(), report_date
    working = frame.copy()
    timestamps = coerce_timestamp_series(working["signal_timestamp"], utc=True)
    working["_signal_ts"] = timestamps
    local_dates = timestamps.dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
    working["_signal_date"] = local_dates
    selected_date = str(report_date) if report_date else None
    if not selected_date:
        valid_dates = local_dates.dropna()
        selected_date = str(valid_dates.max()) if not valid_dates.empty else None
    if not selected_date:
        return working.iloc[0:0].copy(), selected_date
    return working.loc[working["_signal_date"] == selected_date].copy(), selected_date


def _directional_mask(frame: pd.DataFrame) -> pd.Series:
    direction = _text_series(frame, "direction", default="")
    return direction.str.upper().isin({"CALL", "PUT"})


def _summary_stats(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "count": int(len(values)),
        "mean": _round_or_none(float(values.mean()), 4),
        "median": _round_or_none(float(values.median()), 4),
        "min": _round_or_none(float(values.min()), 4),
        "max": _round_or_none(float(values.max()), 4),
    }


def _value_counts(frame: pd.DataFrame, column: str, limit: int = 20) -> list[dict[str, Any]]:
    values = _text_series(frame, column)
    counts = values.value_counts(dropna=False).head(limit)
    total = max(int(len(frame)), 1)
    return [
        {"value": str(key), "count": int(value), "share": _round_or_none(float(value) / total, 4)}
        for key, value in counts.items()
    ]


def _table(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def _blocker_counts(suppressed: pd.DataFrame, blocker_columns: tuple[str, ...]) -> list[dict[str, Any]]:
    total = max(int(len(suppressed)), 1)
    rows = []
    priority = {blocker: index for index, blocker in enumerate(PRIMARY_BLOCKER_ORDER)}
    for blocker in blocker_columns:
        count = int(suppressed[blocker].fillna(False).sum()) if blocker in suppressed.columns else 0
        rows.append(
            {
                "blocker": blocker,
                "label": BLOCKER_LABELS.get(blocker, blocker),
                "count": count,
                "share_of_suppressed": _round_or_none(count / total, 4),
            }
        )
    return sorted(
        rows,
        key=lambda item: (-int(item["count"]), priority.get(str(item["blocker"]), 999), str(item["blocker"])),
    )


def _primary_blocker(row: pd.Series) -> str:
    for blocker in PRIMARY_BLOCKER_ORDER:
        try:
            if bool(row.get(blocker)):
                return blocker
        except Exception:
            continue
    return "unclassified"


def _recommendations(report: dict[str, Any]) -> list[str]:
    suppressed = int(report.get("suppressed_directional_count") or 0)
    if suppressed <= 0:
        return ["No suppressed directional rows for this session."]
    blockers = {row["blocker"]: row for row in report.get("blocker_counts", [])}
    recs: list[str] = []
    composite_share = float((blockers.get("runtime_composite_below_threshold") or {}).get("share_of_suppressed") or 0.0)
    probability_share = float((blockers.get("move_probability_below_floor") or {}).get("share_of_suppressed") or 0.0)
    risk_share = float((blockers.get("risk_off_macro") or {}).get("share_of_suppressed") or 0.0)
    provider_share = float((blockers.get("provider_execution_blocked") or {}).get("share_of_suppressed") or 0.0)
    hit_rate = report.get("suppressed_outcome", {}).get("hit_rate_60m")
    avg_return = report.get("suppressed_outcome", {}).get("avg_signed_return_60m_bps")

    if composite_share >= 0.8:
        recs.append(
            "Runtime composite is the dominant blocker; compare runtime component contributions against ex-post composite quality before changing any threshold."
        )
    if probability_share >= 0.5:
        recs.append(
            "Move probability is frequently below the diagnostic floor; review probability calibration by regime/direction before using probability as a hard activation gate."
        )
    if risk_share >= 0.8:
        recs.append(
            "All or most suppressed rows sit in RISK_OFF; evaluate risk-off aligned direction separately from risk-off contrarian direction."
        )
    if provider_share > 0:
        recs.append(
            "Provider execution/data blocks are present; keep analytics-vs-execution trust separated in compact output and reports."
        )
    if hit_rate is not None and float(hit_rate) >= 0.6 and avg_return is not None and float(avg_return) <= 0:
        recs.append(
            "Directional hit rate was high but signed return was weak; prioritize entry/exit timing over broad threshold relaxation."
        )
    if not recs:
        recs.append("No single blocker dominates; review top blocker combinations and regime slices before changing policy.")
    return recs


def build_daily_suppression_attribution_report(
    frame: pd.DataFrame,
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    report_date: str | None = None,
    probability_floor: float | None = None,
) -> dict[str, Any]:
    """Build a daily research-only suppression attribution report."""
    session, selected_date = _session_frame(frame if frame is not None else pd.DataFrame(), report_date)
    probability_floor = (
        float(probability_floor)
        if probability_floor is not None
        else float(SIGNAL_EVALUATION_SELECTION_POLICY.get("move_probability_floor", 0.60))
    )
    directional = session.loc[_directional_mask(session)].copy()
    trade_status = _text_series(directional, "trade_status", default="UNKNOWN").str.upper()
    suppressed = directional.loc[trade_status != "TRADE"].copy()

    composite = _num_series(suppressed, "runtime_composite_score")
    composite_threshold = _num_series(suppressed, "effective_min_composite_score_threshold")
    trade_strength = _num_series(suppressed, "trade_strength")
    trade_strength_threshold = _num_series(suppressed, "effective_min_trade_strength_threshold")
    probability = _num_series(suppressed, "hybrid_move_probability").fillna(_num_series(suppressed, "move_probability"))

    suppressed["runtime_composite_gap"] = composite - composite_threshold
    suppressed["trade_strength_gap"] = trade_strength - trade_strength_threshold
    suppressed["probability_gap"] = probability - probability_floor
    suppressed["runtime_composite_below_threshold"] = composite.notna() & composite_threshold.notna() & (composite < composite_threshold)
    suppressed["trade_strength_below_threshold"] = (
        trade_strength.notna() & trade_strength_threshold.notna() & (trade_strength < trade_strength_threshold)
    )
    suppressed["move_probability_below_floor"] = probability.notna() & (probability < probability_floor)
    suppressed["risk_off_macro"] = _text_series(suppressed, "macro_regime", default="").str.upper().str.contains("RISK_OFF")
    suppressed["risk_off_global"] = _text_series(suppressed, "global_risk_state", default="").str.upper().str.contains("RISK_OFF")
    suppressed["at_gamma_flip"] = _text_series(suppressed, "spot_vs_flip", default="").str.upper().eq("AT_FLIP")
    suppressed["provider_execution_blocked"] = (
        _bool_series(suppressed, "provider_quality_blocks_execution")
        | _text_series(suppressed, "provider_quality_mode", default="").str.upper().str.contains("BLOCKED")
        | ~_text_series(suppressed, "market_data_trade_blocking_status", default="PASS").str.upper().eq("PASS")
    )
    suppressed["provider_direction_blocked"] = _bool_series(suppressed, "provider_quality_blocks_direction")
    suppressed["provider_health_not_good"] = ~_text_series(suppressed, "provider_health_status", default="GOOD").str.upper().eq("GOOD")
    suppressed["data_quality_not_strong"] = ~_text_series(suppressed, "data_quality_status", default="STRONG").str.upper().eq("STRONG")
    suppressed["weak_signal_quality"] = _text_series(suppressed, "signal_quality", default="").str.upper().isin({"WEAK", "VERY_WEAK"})
    ta_score = _num_series(suppressed, "ta_entry_timing_score")
    suppressed["low_ta_entry_timing"] = ta_score.notna() & (ta_score < 50.0)

    blocker_columns = tuple(BLOCKER_LABELS.keys())
    if not suppressed.empty:
        suppressed["primary_blocker"] = suppressed.apply(_primary_blocker, axis=1)
        suppressed["blocker_combo"] = suppressed.apply(
            lambda row: "+".join(blocker for blocker in blocker_columns if bool(row.get(blocker))) or "unclassified",
            axis=1,
        )
    else:
        suppressed["primary_blocker"] = pd.Series(dtype="object")
        suppressed["blocker_combo"] = pd.Series(dtype="object")

    component_frame, component_source = _runtime_component_frame(suppressed, probability_floor)
    component_summary = _component_summary(suppressed, component_frame, probability_floor)
    component_primary_counts = (
        _value_counts(component_frame, "primary_component_drag") if not component_frame.empty else []
    )

    label = _num_series(suppressed, "correct_60m")
    signed_return = _num_series(suppressed, "signed_return_60m_bps")
    valid_label = label.notna()
    suppressed_outcome = {
        "label_count_60m": int(valid_label.sum()),
        "hit_rate_60m": _round_or_none(float(label.loc[valid_label].mean()), 4) if valid_label.any() else None,
        "avg_signed_return_60m_bps": _round_or_none(float(signed_return.dropna().mean()), 4)
        if signed_return.notna().any()
        else None,
    }

    combo_counts = suppressed["blocker_combo"].value_counts().head(15) if not suppressed.empty else pd.Series(dtype=int)
    primary_counts = suppressed["primary_blocker"].value_counts().head(15) if not suppressed.empty else pd.Series(dtype=int)
    total_suppressed = max(int(len(suppressed)), 1)
    near_miss = suppressed.loc[
        (suppressed["runtime_composite_gap"] >= -5.0)
        & (suppressed["trade_strength_gap"] >= 0.0)
        & (suppressed["probability_gap"] >= 0.0)
    ]

    report = {
        "report_type": "daily_suppression_attribution",
        "generated_at": _now_utc(),
        "research_only": True,
        "runtime_config_changed": False,
        "parameter_pack_file_changed": False,
        "execution_behavior_changed": False,
        "dataset_path": str(dataset_path),
        "report_date": selected_date,
        "probability_floor": float(probability_floor),
        "total_snapshot_count": int(len(session)),
        "directional_count": int(len(directional)),
        "trade_qualified_count": int((trade_status == "TRADE").sum()) if not directional.empty else 0,
        "suppressed_directional_count": int(len(suppressed)),
        "suppression_rate": _round_or_none(float(len(suppressed)) / max(int(len(directional)), 1), 4),
        "direction_counts": _value_counts(directional, "direction"),
        "trade_status_counts": _value_counts(directional, "trade_status"),
        "blocker_counts": _blocker_counts(suppressed, blocker_columns),
        "primary_blocker_counts": [
            {
                "primary_blocker": str(key),
                "label": BLOCKER_LABELS.get(str(key), str(key)),
                "count": int(value),
                "share_of_suppressed": _round_or_none(float(value) / total_suppressed, 4),
            }
            for key, value in primary_counts.items()
        ],
        "top_blocker_combinations": [
            {"combo": str(key), "count": int(value), "share_of_suppressed": _round_or_none(float(value) / total_suppressed, 4)}
            for key, value in combo_counts.items()
        ],
        "runtime_composite_gap_summary": _summary_stats(suppressed.get("runtime_composite_gap", pd.Series(dtype=float))),
        "trade_strength_gap_summary": _summary_stats(suppressed.get("trade_strength_gap", pd.Series(dtype=float))),
        "probability_gap_summary": _summary_stats(suppressed.get("probability_gap", pd.Series(dtype=float))),
        "runtime_component_attribution": {
            "method": component_source,
            "research_only": True,
            "component_summary": component_summary,
            "primary_component_drag_counts": component_primary_counts,
            "adjustment_summary": _runtime_adjustment_summary(component_frame, suppressed),
            "caveat": (
                "Rows without runtime_composite_components use reconstructed component estimates from captured live-time fields."
            ),
        },
        "suppressed_outcome": suppressed_outcome,
        "near_miss_count": int(len(near_miss)),
        "near_miss_share": _round_or_none(float(len(near_miss)) / total_suppressed, 4),
        "provider_quality_mode_counts": _value_counts(suppressed, "provider_quality_mode"),
        "spot_vs_flip_counts": _value_counts(suppressed, "spot_vs_flip"),
        "signal_quality_counts": _value_counts(suppressed, "signal_quality"),
        "macro_regime_counts": _value_counts(suppressed, "macro_regime"),
        "global_risk_state_counts": _value_counts(suppressed, "global_risk_state"),
    }
    report["recommended_next_actions"] = _recommendations(report)
    return _sanitize_value(report)


def render_daily_suppression_attribution_markdown(report: dict[str, Any]) -> str:
    """Render daily suppression attribution as Markdown."""
    lines = [
        "# Daily Suppression Attribution",
        "",
        "> Author: Pramit Dutta | Organization: Quant Engines",
        "",
        f"- Generated at: {report.get('generated_at')}",
        f"- Date: `{report.get('report_date')}`",
        f"- Dataset: `{report.get('dataset_path')}`",
        f"- Research only: `{report.get('research_only')}`",
        f"- Runtime config changed: `{report.get('runtime_config_changed')}`",
        "",
        "## Summary",
        "",
        f"- Total snapshots: `{report.get('total_snapshot_count')}`",
        f"- Directional rows: `{report.get('directional_count')}`",
        f"- Trade-qualified rows: `{report.get('trade_qualified_count')}`",
        f"- Suppressed directional rows: `{report.get('suppressed_directional_count')}`",
        f"- Suppression rate: `{report.get('suppression_rate')}`",
        f"- Diagnostic probability floor: `{report.get('probability_floor')}`",
        "",
    ]
    lines.extend(
        _table(
            report.get("blocker_counts", []),
            ("label", "count", "share_of_suppressed"),
        )
    )
    lines.extend(["", "## Primary Blocker", ""])
    lines.extend(
        _table(
            report.get("primary_blocker_counts", []),
            ("label", "count", "share_of_suppressed"),
        )
    )
    lines.extend(["", "## Top Blocker Combinations", ""])
    lines.extend(
        _table(
            report.get("top_blocker_combinations", []),
            ("combo", "count", "share_of_suppressed"),
        )
    )
    lines.extend(
        [
            "",
            "## Threshold Gaps",
            "",
            f"- Runtime composite gap: `{report.get('runtime_composite_gap_summary')}`",
            f"- Trade-strength gap: `{report.get('trade_strength_gap_summary')}`",
            f"- Probability gap: `{report.get('probability_gap_summary')}`",
            f"- Near-miss rows: `{report.get('near_miss_count')}` (`{report.get('near_miss_share')}` of suppressed)",
            "",
            "## Runtime Component Attribution",
            "",
            f"- Method: `{(report.get('runtime_component_attribution') or {}).get('method')}`",
            f"- Caveat: {(report.get('runtime_component_attribution') or {}).get('caveat')}",
            "",
            "### Component Summary",
        ]
    )
    component_attribution = report.get("runtime_component_attribution") or {}
    lines.extend(
        _table(
            component_attribution.get("component_summary", []),
            (
                "label",
                "avg_component_score",
                "avg_weighted_contribution",
                "avg_weighted_deficit_to_100",
                "low_component_count",
                "primary_drag_count",
            ),
        )
    )
    lines.extend(["", "### Primary Component Drag"])
    lines.extend(
        _table(
            component_attribution.get("primary_component_drag_counts", []),
            ("value", "count", "share"),
        )
    )
    adjustment_summary = component_attribution.get("adjustment_summary") or {}
    lines.extend(
        [
            "",
            "### Runtime Adjustment Summary",
            "",
            f"- Estimated pre-adjust score: `{adjustment_summary.get('estimated_pre_adjust_score')}`",
            f"- Observed runtime composite score: `{adjustment_summary.get('observed_runtime_composite_score')}`",
            f"- Observed runtime composite base score: `{adjustment_summary.get('observed_runtime_composite_base_score')}`",
            f"- Final-minus-estimated pre-adjust: `{adjustment_summary.get('final_minus_estimated_pre_adjust')}`",
            f"- Base-minus-estimated pre-adjust: `{adjustment_summary.get('base_minus_estimated_pre_adjust')}`",
            f"- Feature reliability penalty: `{adjustment_summary.get('feature_reliability_composite_penalty')}`",
            f"- Regime adjustment delta: `{adjustment_summary.get('regime_composite_adjustment_delta')}`",
            f"- Time decay factor: `{adjustment_summary.get('time_decay_factor')}`",
            f"- Supplement candidate adjustment: `{adjustment_summary.get('runtime_composite_supplement_candidate_adjustment')}`",
            f"- Supplement adjustment: `{adjustment_summary.get('supplement_score_adjustment')}`",
            "",
            "## Suppressed Outcome",
            "",
            f"- 60m labels: `{(report.get('suppressed_outcome') or {}).get('label_count_60m')}`",
            f"- 60m hit rate: `{(report.get('suppressed_outcome') or {}).get('hit_rate_60m')}`",
            f"- Avg signed 60m return bps: `{(report.get('suppressed_outcome') or {}).get('avg_signed_return_60m_bps')}`",
            "",
            "## Context Counts",
            "",
            "### Provider Quality Mode",
        ]
    )
    lines.extend(_table(report.get("provider_quality_mode_counts", []), ("value", "count", "share")))
    lines.extend(["", "### Spot Vs Flip"])
    lines.extend(_table(report.get("spot_vs_flip_counts", []), ("value", "count", "share")))
    lines.extend(["", "### Signal Quality"])
    lines.extend(_table(report.get("signal_quality_counts", []), ("value", "count", "share")))
    lines.extend(["", "## Recommended Next Actions", ""])
    for action in report.get("recommended_next_actions", []) or []:
        lines.append(f"- {action}")
    lines.extend(["", "*Research-only diagnostic. It does not change runtime decisions or execution behavior.*", ""])
    return "\n".join(lines)


def write_daily_suppression_attribution_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_DAILY_SUPPRESSION_ATTRIBUTION_DIR,
    report_date: str | None = None,
    probability_floor: float | None = None,
) -> dict[str, Any]:
    """Build and write daily suppression attribution artifacts."""
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = _load_dataset(dataset)
    report = build_daily_suppression_attribution_report(
        frame,
        dataset_path=dataset,
        report_date=report_date,
        probability_floor=probability_floor,
    )
    stem_date = str(report.get("report_date") or "latest").replace("-", "")
    stem = f"daily_suppression_attribution_{stem_date}"
    json_path = output / f"{stem}.json"
    markdown_path = output / f"{stem}.md"
    suppressed_rows_path = output / f"{stem}_suppressed_rows.csv"
    latest_json_path = output / LATEST_JSON_FILENAME
    latest_markdown_path = output / LATEST_MARKDOWN_FILENAME
    latest_suppressed_rows_path = output / LATEST_SUPPRESSED_ROWS_FILENAME

    markdown = render_daily_suppression_attribution_markdown(report)
    _atomic_write_text(json_path, json.dumps(report, indent=2, sort_keys=True, default=str))
    _atomic_write_text(markdown_path, markdown)
    _atomic_write_text(latest_json_path, json.dumps(report, indent=2, sort_keys=True, default=str))
    _atomic_write_text(latest_markdown_path, markdown)

    session, _ = _session_frame(frame, report.get("report_date"))
    directional = session.loc[_directional_mask(session)].copy()
    trade_status = _text_series(directional, "trade_status", default="UNKNOWN").str.upper()
    suppressed = directional.loc[trade_status != "TRADE"].copy()
    export_columns = [
        column
        for column in (
            "signal_id",
            "signal_timestamp",
            "direction",
            "trade_status",
            "runtime_composite_score",
            "effective_min_composite_score_threshold",
            "trade_strength",
            "effective_min_trade_strength_threshold",
            "hybrid_move_probability",
            "move_probability",
            "macro_regime",
            "global_risk_state",
            "spot_vs_flip",
            "provider_quality_mode",
            "provider_health_status",
            "data_quality_status",
            "signal_quality",
            "correct_60m",
            "signed_return_60m_bps",
        )
        if column in suppressed.columns
    ]
    _atomic_write_csv(suppressed.loc[:, export_columns] if export_columns else suppressed, suppressed_rows_path)
    _atomic_write_csv(
        suppressed.loc[:, export_columns] if export_columns else suppressed,
        latest_suppressed_rows_path,
    )

    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "suppressed_rows_path": str(suppressed_rows_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
        "latest_suppressed_rows_path": str(latest_suppressed_rows_path),
    }

"""Research-only diagnostics for signal invalidation rules.

This module asks a narrow question: once a directional setup appears, what
live-time evidence says the setup is no longer valid?  It measures those
events against realized outcomes without changing live engine decisions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH
from research.signal_evaluation.report_manifest import write_report_reproducibility_manifest
from utils.timestamp_helpers import coerce_timestamp_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SIGNAL_INVALIDATION_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "signal_invalidation"
)

DEFAULT_INVALIDATION_THRESHOLD = 50
DEFAULT_MAX_EPISODE_GAP_MINUTES = 15
DEFAULT_SCORE_DECAY_DROP_POINTS = 10.0

INVALIDATION_PRIORITY = {
    "INVALIDATED_LEVEL_REJECTION": 0,
    "INVALIDATED_CANDLE_REJECTION": 1,
    "INVALIDATED_GAMMA_FLIP_CROSS": 2,
    "INVALIDATED_SCORE_DECAY": 3,
    "INVALIDATED_CONFIRMATION_LOSS": 4,
    "INVALIDATED_PROVIDER_WEAKNESS": 5,
    "INVALIDATED_DIRECTION_FLIP": 6,
}

_RUNTIME_COLUMNS = {
    "signal_timestamp",
    "symbol",
    "source",
    "mode",
    "option_source",
    "direction",
    "runtime_composite_score",
    "trade_strength",
    "trade_status",
    "label_quality_status",
    "outcome_status",
    "spot_at_signal",
    "confirmation_status",
    "final_flow_signal",
    "gamma_regime",
    "volatility_regime",
    "global_risk_state",
    "macro_regime",
    "spot_vs_flip",
    "historical_wall_state",
    "historical_wall_interpretation",
    "provider_health_status",
    "data_quality_status",
    "market_data_trade_blocking_status",
    "analytics_usable",
    "execution_suggestion_usable",
    "signed_return_15m_bps",
    "signed_return_30m_bps",
    "signed_return_60m_bps",
    "signed_return_120m_bps",
    "correct_15m",
    "correct_30m",
    "correct_60m",
    "correct_120m",
    "mfe_60m_bps",
    "mae_60m_bps",
    "mfe_120m_bps",
    "mae_120m_bps",
    "option_premium_return_15m_bps",
    "option_premium_return_30m_bps",
    "option_premium_return_60m_bps",
    "option_premium_return_120m_bps",
    "option_premium_pnl_per_lot_60m",
    "ta_candle_direction",
    "ta_candle_state",
    "ta_candle_late_chase",
    "ta_candle_rejection",
    "ta_entry_timing_state",
    "ta_entry_timing_score",
    "ta_entry_timing_reasons",
}


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if pd.isna(number) or not np.isfinite(number):
        return default
    return number


def _round(value: Any, digits: int = 2) -> float | None:
    number = _safe_float(value, None)
    return round(number, digits) if number is not None else None


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _normalize_text(series: pd.Series, default: str = "UNKNOWN") -> pd.Series:
    return (
        series.fillna(default)
        .astype(str)
        .str.strip()
        .replace({"": default, "nan": default, "NaN": default, "None": default})
    )


def _mean(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.mean())


def _pct_mean(series: pd.Series) -> float | None:
    value = _mean(series)
    return value * 100.0 if value is not None else None


def _share(series: pd.Series, value: str) -> float | None:
    if series.empty:
        return None
    return float((series.astype(str) == value).mean())


def _positive_share(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float((numeric > 0.0).mean())


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().upper() in {"1", "TRUE", "YES", "Y", "ON"}


def _confirmation_ready(value: Any) -> bool:
    return str(value or "").strip().upper() in {"CONFIRMED", "STRONG_CONFIRMATION"}


def _direction_sign(direction: Any) -> float | None:
    token = str(direction or "").strip().upper()
    if token == "CALL":
        return 1.0
    if token == "PUT":
        return -1.0
    return None


def _numeric_columns(frame: pd.DataFrame) -> pd.DataFrame:
    working = frame.copy()
    for column in working.columns:
        if (
            column.startswith("signed_return_")
            or column.startswith("correct_")
            or column.startswith("mfe_")
            or column.startswith("mae_")
            or column.startswith("option_premium_return_")
            or column.startswith("option_premium_pnl_per_lot_")
            or column
            in {
                "runtime_composite_score",
                "trade_strength",
                "spot_at_signal",
                "ta_entry_timing_score",
            }
        ):
            working[column] = pd.to_numeric(working[column], errors="coerce")
    return working


def _candle_adverse(row: pd.Series) -> bool:
    state_blob = " ".join(
        str(row.get(column) or "").strip().upper()
        for column in ("ta_entry_timing_state", "ta_candle_state", "ta_entry_timing_reasons")
    )
    return (
        _truthy(row.get("ta_candle_late_chase"))
        or _truthy(row.get("ta_candle_rejection"))
        or "LATE_CHASE" in state_blob
        or "REJECTION" in state_blob
        or "INVALIDATED" in state_blob
    )


def _adverse_wall_for_direction(row: pd.Series, direction: str) -> bool:
    wall_state = str(row.get("historical_wall_state") or "").strip().upper()
    if direction == "CALL":
        return wall_state == "NEAR_RESISTANCE_WALL"
    if direction == "PUT":
        return wall_state == "NEAR_SUPPORT_WALL"
    return False


def _gamma_flip_against_direction(row: pd.Series, direction: str) -> bool:
    spot_vs_flip = str(row.get("spot_vs_flip") or "").strip().upper()
    if direction == "CALL":
        return spot_vs_flip == "BELOW_FLIP"
    if direction == "PUT":
        return spot_vs_flip == "ABOVE_FLIP"
    return False


def _provider_weak(row: pd.Series) -> bool:
    provider = str(row.get("provider_health_status") or "").strip().upper()
    quality = str(row.get("data_quality_status") or "").strip().upper()
    trade_block = str(row.get("market_data_trade_blocking_status") or "").strip().upper()
    return provider in {"WEAK", "FRAGILE"} or quality == "WEAK" or trade_block in {"BLOCK", "BLOCKED"}


def _minutes_between(later: Any, earlier: Any) -> float | None:
    if pd.isna(later) or pd.isna(earlier):
        return None
    return float((later - earlier).total_seconds() / 60.0)


def load_signal_invalidation_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Signal dataset not found: {dataset_path}")
    return pd.read_csv(
        dataset_path,
        usecols=lambda column: column in _RUNTIME_COLUMNS,
        low_memory=False,
    )


def prepare_signal_invalidation_frame(frame: pd.DataFrame) -> pd.DataFrame:
    working = _numeric_columns(frame)
    if "signal_timestamp" not in working.columns:
        working["signal_timestamp"] = pd.NA
    working["signal_ts"] = coerce_timestamp_series(working["signal_timestamp"], utc=True)
    working["signal_date"] = working["signal_ts"].dt.tz_convert("Asia/Kolkata").dt.date.astype(str)
    for column, default in (
        ("symbol", "UNKNOWN"),
        ("direction", "NO_DIRECTION"),
        ("confirmation_status", "UNKNOWN"),
        ("trade_status", "UNKNOWN"),
        ("outcome_status", "UNKNOWN"),
        ("label_quality_status", "UNKNOWN"),
        ("gamma_regime", "UNKNOWN"),
        ("volatility_regime", "UNKNOWN"),
        ("global_risk_state", "UNKNOWN"),
        ("macro_regime", "UNKNOWN"),
        ("spot_vs_flip", "UNKNOWN"),
        ("historical_wall_state", "UNKNOWN"),
        ("provider_health_status", "UNKNOWN"),
        ("data_quality_status", "UNKNOWN"),
        ("market_data_trade_blocking_status", "UNKNOWN"),
        ("ta_entry_timing_state", "UNAVAILABLE"),
        ("ta_candle_state", "UNAVAILABLE"),
        ("ta_candle_direction", "UNKNOWN"),
    ):
        working[column] = _normalize_text(working.get(column, pd.Series(index=working.index)), default=default)
    working["direction_sign"] = working["direction"].map({"CALL": 1.0, "PUT": -1.0})
    working["runtime_composite_score"] = pd.to_numeric(
        working.get("runtime_composite_score", pd.Series(index=working.index)),
        errors="coerce",
    )
    return working


def _episode_frames(prepared: pd.DataFrame, *, max_episode_gap_minutes: int) -> list[tuple[pd.DataFrame, dict[str, Any]]]:
    directional = prepared[
        prepared["signal_ts"].notna()
        & prepared["direction"].isin(["CALL", "PUT"])
        & prepared["runtime_composite_score"].notna()
    ].copy()
    if directional.empty:
        return []

    episodes: list[tuple[pd.DataFrame, dict[str, Any]]] = []
    max_gap = pd.Timedelta(minutes=int(max_episode_gap_minutes))
    sort_cols = ["signal_date", "symbol", "signal_ts"]
    for (_signal_date, _symbol), day_group in directional.sort_values(sort_cols, kind="mergesort").groupby(
        ["signal_date", "symbol"],
        dropna=False,
        observed=True,
    ):
        active: list[pd.Series] = []
        close_info: dict[str, Any] = {}

        def close_active(info: dict[str, Any]) -> None:
            nonlocal active
            if active:
                episodes.append((pd.DataFrame(active), dict(info)))
                active = []

        for _idx, row in day_group.iterrows():
            if not active:
                active = [row]
                close_info = {}
                continue

            previous = active[-1]
            gap = row["signal_ts"] - previous["signal_ts"]
            direction_changed = str(row["direction"]) != str(previous["direction"])
            gap_expired = gap > max_gap
            if direction_changed or gap_expired:
                if direction_changed:
                    close_info = {
                        "terminal_event_type": "INVALIDATED_DIRECTION_FLIP",
                        "terminal_event_timestamp": row["signal_ts"],
                        "terminal_event_row": row,
                        "terminal_event_reason": f"direction_flip_to_{row['direction']}",
                    }
                else:
                    close_info = {"terminal_event_reason": "gap_expired"}
                close_active(close_info)
                active = [row]
                close_info = {}
                continue

            active.append(row)

        close_active(close_info)
    return episodes


def _event_payload(event_type: str, row: pd.Series, reason: str) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "event_timestamp": row.get("signal_ts"),
        "event_row": row,
        "event_reason": reason,
        "priority": INVALIDATION_PRIORITY.get(event_type, 99),
    }


def _first_matching_event(
    group: pd.DataFrame,
    mask: pd.Series,
    *,
    event_type: str,
    reason: str,
) -> dict[str, Any] | None:
    candidates = group.loc[mask.fillna(False)]
    if candidates.empty:
        return None
    return _event_payload(event_type, candidates.iloc[0], reason)


def _provider_transition_event(group: pd.DataFrame) -> dict[str, Any] | None:
    seen_clean = False
    for _idx, row in group.iterrows():
        weak = _provider_weak(row)
        if not weak:
            seen_clean = True
            continue
        if seen_clean:
            return _event_payload(
                "INVALIDATED_PROVIDER_WEAKNESS",
                row,
                "provider_or_data_quality_transitioned_from_clean_to_weak",
            )
    return None


def _gamma_flip_transition_event(group: pd.DataFrame, direction: str) -> dict[str, Any] | None:
    seen_not_against = False
    for _idx, row in group.iterrows():
        against = _gamma_flip_against_direction(row, direction)
        if not against:
            seen_not_against = True
            continue
        if seen_not_against:
            return _event_payload(
                "INVALIDATED_GAMMA_FLIP_CROSS",
                row,
                "spot_vs_gamma_flip_transitioned_against_signal_direction",
            )
    return None


def _detect_invalidation_events(
    group: pd.DataFrame,
    close_info: dict[str, Any],
    *,
    threshold: int,
    score_decay_drop_points: float,
) -> list[dict[str, Any]]:
    ordered = group.sort_values("signal_ts", kind="mergesort").reset_index(drop=True)
    if ordered.empty:
        return []
    direction = str(ordered.iloc[0].get("direction") or "").strip().upper()
    score = pd.to_numeric(ordered["runtime_composite_score"], errors="coerce")
    threshold_mask = score >= float(threshold)
    after_threshold = ordered.loc[threshold_mask.idxmax() :] if threshold_mask.any() else ordered.iloc[0:0]
    events: list[dict[str, Any]] = []

    if threshold_mask.any():
        peak_pos = int(score.idxmax())
        peak_score = _safe_float(ordered.iloc[peak_pos].get("runtime_composite_score"), None)
        if peak_score is not None and peak_score >= float(threshold):
            after_peak = ordered.iloc[peak_pos + 1 :].copy()
            if not after_peak.empty:
                after_score = pd.to_numeric(after_peak["runtime_composite_score"], errors="coerce")
                score_decay_mask = after_score.lt(float(threshold)) | after_score.le(
                    peak_score - float(score_decay_drop_points)
                )
                event = _first_matching_event(
                    after_peak,
                    score_decay_mask,
                    event_type="INVALIDATED_SCORE_DECAY",
                    reason="runtime_score_fell_below_threshold_or_peak_decay",
                )
                if event is not None:
                    events.append(event)

    confirmation_mask = ordered["confirmation_status"].map(_confirmation_ready)
    if confirmation_mask.any():
        first_confirmation_pos = int(confirmation_mask.idxmax())
        after_confirmation = ordered.iloc[first_confirmation_pos + 1 :].copy()
        if not after_confirmation.empty:
            event = _first_matching_event(
                after_confirmation,
                ~after_confirmation["confirmation_status"].map(_confirmation_ready),
                event_type="INVALIDATED_CONFIRMATION_LOSS",
                reason="confirmation_disappeared_after_ready_state",
            )
            if event is not None:
                events.append(event)

    candle_event = _first_matching_event(
        ordered,
        ordered.apply(_candle_adverse, axis=1),
        event_type="INVALIDATED_CANDLE_REJECTION",
        reason="candle_rejection_or_late_chase_state",
    )
    if candle_event is not None:
        events.append(candle_event)

    level_event = _first_matching_event(
        ordered,
        ordered.apply(lambda row: _adverse_wall_for_direction(row, direction) and _candle_adverse(row), axis=1),
        event_type="INVALIDATED_LEVEL_REJECTION",
        reason="adverse_wall_context_with_candle_rejection",
    )
    if level_event is not None:
        events.append(level_event)

    gamma_source = after_threshold if not after_threshold.empty else ordered
    gamma_event = _gamma_flip_transition_event(gamma_source, direction)
    if gamma_event is not None:
        events.append(gamma_event)

    provider_source = after_threshold if not after_threshold.empty else ordered
    provider_event = _provider_transition_event(provider_source)
    if provider_event is not None:
        events.append(provider_event)

    if close_info.get("terminal_event_type") == "INVALIDATED_DIRECTION_FLIP":
        events.append(
            {
                "event_type": "INVALIDATED_DIRECTION_FLIP",
                "event_timestamp": close_info.get("terminal_event_timestamp"),
                "event_row": close_info.get("terminal_event_row"),
                "event_reason": close_info.get("terminal_event_reason"),
                "priority": INVALIDATION_PRIORITY["INVALIDATED_DIRECTION_FLIP"],
            }
        )

    return [event for event in events if event.get("event_timestamp") is not None]


def _return_for_episode_direction(row: pd.Series, episode_direction: str, horizon: int) -> float | None:
    value = _safe_float(row.get(f"signed_return_{horizon}m_bps"), None)
    if value is None:
        return None
    row_sign = _direction_sign(row.get("direction"))
    episode_sign = _direction_sign(episode_direction)
    if row_sign is None or episode_sign is None:
        return value
    return value * episode_sign / row_sign


def _row_metric_payload(row: pd.Series, episode_direction: str, prefix: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        f"{prefix}_timestamp": row.get("signal_ts").isoformat() if not pd.isna(row.get("signal_ts")) else None,
        f"{prefix}_score": _safe_float(row.get("runtime_composite_score"), None),
        f"{prefix}_confirmation_status": str(row.get("confirmation_status") or "UNKNOWN"),
        f"{prefix}_provider_health_status": str(row.get("provider_health_status") or "UNKNOWN"),
        f"{prefix}_data_quality_status": str(row.get("data_quality_status") or "UNKNOWN"),
        f"{prefix}_spot_vs_flip": str(row.get("spot_vs_flip") or "UNKNOWN"),
        f"{prefix}_historical_wall_state": str(row.get("historical_wall_state") or "UNKNOWN"),
        f"{prefix}_ta_entry_timing_state": str(row.get("ta_entry_timing_state") or "UNAVAILABLE"),
        f"{prefix}_ta_candle_state": str(row.get("ta_candle_state") or "UNAVAILABLE"),
    }
    for horizon in (15, 30, 60, 120):
        ret = _return_for_episode_direction(row, episode_direction, horizon)
        payload[f"{prefix}_return_{horizon}m_bps"] = ret
        payload[f"{prefix}_correct_{horizon}m"] = None if ret is None else int(ret > 0.0)
        payload[f"{prefix}_option_premium_return_{horizon}m_bps"] = _safe_float(
            row.get(f"option_premium_return_{horizon}m_bps"),
            None,
        )
    same_direction = str(row.get("direction") or "").strip().upper() == episode_direction
    for horizon in (60, 120):
        payload[f"{prefix}_mfe_{horizon}m_bps"] = (
            _safe_float(row.get(f"mfe_{horizon}m_bps"), None) if same_direction else None
        )
        payload[f"{prefix}_mae_{horizon}m_bps"] = (
            _safe_float(row.get(f"mae_{horizon}m_bps"), None) if same_direction else None
        )
    payload[f"{prefix}_option_pnl_per_lot_60m"] = _safe_float(row.get("option_premium_pnl_per_lot_60m"), None)
    return payload


def _episode_payload(
    episode_id: str,
    group: pd.DataFrame,
    close_info: dict[str, Any],
    *,
    threshold: int,
    score_decay_drop_points: float,
) -> dict[str, Any]:
    ordered = group.sort_values("signal_ts", kind="mergesort").reset_index(drop=True)
    first = ordered.iloc[0]
    direction = str(first.get("direction") or "").strip().upper()
    events = _detect_invalidation_events(
        ordered,
        close_info,
        threshold=threshold,
        score_decay_drop_points=score_decay_drop_points,
    )
    events.sort(key=lambda event: (event["event_timestamp"], event.get("priority", 99)))
    first_event = events[0] if events else None
    first_event_row = first_event.get("event_row") if first_event else None
    first_ts = first.get("signal_ts")

    payload: dict[str, Any] = {
        "episode_id": episode_id,
        "signal_date": str(first.get("signal_date")),
        "symbol": str(first.get("symbol") or ""),
        "direction": direction,
        "row_count": int(len(ordered)),
        "start_timestamp": first_ts.isoformat() if not pd.isna(first_ts) else None,
        "end_timestamp": ordered.iloc[-1].get("signal_ts").isoformat()
        if not pd.isna(ordered.iloc[-1].get("signal_ts"))
        else None,
        "threshold": int(threshold),
        "has_invalidation": bool(first_event is not None),
        "terminal_validity_state": str(first_event.get("event_type")) if first_event else "ACTIVE_OR_UNRESOLVED",
        "first_invalidation_type": str(first_event.get("event_type")) if first_event else "NO_INVALIDATION",
        "first_invalidation_reason": str(first_event.get("event_reason")) if first_event else None,
        "first_invalidation_timestamp": first_event.get("event_timestamp").isoformat() if first_event else None,
        "first_invalidation_delay_minutes": _round(_minutes_between(first_event.get("event_timestamp"), first_ts))
        if first_event
        else None,
        "all_invalidation_types": "|".join(dict.fromkeys(str(event["event_type"]) for event in events)),
        "invalidation_event_count": int(len(events)),
        "gamma_regime": str(first.get("gamma_regime") or "UNKNOWN"),
        "volatility_regime": str(first.get("volatility_regime") or "UNKNOWN"),
        "global_risk_state": str(first.get("global_risk_state") or "UNKNOWN"),
        "macro_regime": str(first.get("macro_regime") or "UNKNOWN"),
    }
    payload.update(_row_metric_payload(first, direction, "first_seen"))
    if first_event_row is not None:
        payload.update(_row_metric_payload(first_event_row, direction, "invalidation"))
        first_return = payload.get("first_seen_return_60m_bps")
        invalidation_return = payload.get("invalidation_return_60m_bps")
        payload["invalidation_minus_first_return_60m_bps"] = _round(
            invalidation_return - first_return
            if invalidation_return is not None and first_return is not None
            else None
        )
        first_premium = payload.get("first_seen_option_premium_return_60m_bps")
        invalidation_premium = payload.get("invalidation_option_premium_return_60m_bps")
        payload["invalidation_minus_first_option_premium_60m_bps"] = _round(
            invalidation_premium - first_premium
            if invalidation_premium is not None and first_premium is not None
            else None
        )
    else:
        for key in (
            "invalidation_return_60m_bps",
            "invalidation_correct_60m",
            "invalidation_mfe_60m_bps",
            "invalidation_mae_60m_bps",
            "invalidation_option_premium_return_60m_bps",
            "invalidation_minus_first_return_60m_bps",
            "invalidation_minus_first_option_premium_60m_bps",
        ):
            payload[key] = None
    return payload


def build_signal_invalidation_episodes(
    frame: pd.DataFrame,
    *,
    threshold: int = DEFAULT_INVALIDATION_THRESHOLD,
    max_episode_gap_minutes: int = DEFAULT_MAX_EPISODE_GAP_MINUTES,
    score_decay_drop_points: float = DEFAULT_SCORE_DECAY_DROP_POINTS,
) -> pd.DataFrame:
    prepared = prepare_signal_invalidation_frame(frame)
    frames = _episode_frames(prepared, max_episode_gap_minutes=max_episode_gap_minutes)
    rows = [
        _episode_payload(
            f"{group.iloc[0]['signal_date']}:{group.iloc[0]['symbol']}:{group.iloc[0]['direction']}:{idx + 1}",
            group,
            close_info,
            threshold=threshold,
            score_decay_drop_points=score_decay_drop_points,
        )
        for idx, (group, close_info) in enumerate(frames)
    ]
    return pd.DataFrame(rows)


def _summarize_groups(episodes: pd.DataFrame, group_cols: list[str], *, min_rows: int = 1) -> list[dict[str, Any]]:
    if episodes.empty:
        return []
    missing = [column for column in group_cols if column not in episodes.columns]
    if missing:
        return []
    rows: list[dict[str, Any]] = []
    baseline_correct = pd.to_numeric(episodes.get("first_seen_correct_60m", pd.Series(dtype=float)), errors="coerce")
    baseline_hit_ids = set(episodes.loc[baseline_correct.eq(1.0), "episode_id"].astype(str))
    baseline_non_hit_ids = set(episodes.loc[baseline_correct.eq(0.0), "episode_id"].astype(str))
    for keys, group in episodes.groupby(group_cols, dropna=False, observed=True):
        if len(group) < min_rows:
            continue
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {column: str(value) for column, value in zip(group_cols, keys)}
        invalidated = group.loc[group.get("has_invalidation", pd.Series(False, index=group.index)).fillna(False)]
        caught_ids = set(invalidated["episode_id"].astype(str))
        row.update(
            {
                "episode_count": int(len(group)),
                "invalidated_count": int(len(invalidated)),
                "invalidation_share": _round(len(invalidated) / len(group) * 100.0 if len(group) else None),
                "avg_first_score": _round(_mean(group.get("first_seen_score", pd.Series(dtype=float)))),
                "avg_invalidation_score": _round(_mean(group.get("invalidation_score", pd.Series(dtype=float)))),
                "avg_invalidation_delay_minutes": _round(
                    _mean(group.get("first_invalidation_delay_minutes", pd.Series(dtype=float)))
                ),
                "avg_first_return_60m_bps": _round(_mean(group.get("first_seen_return_60m_bps", pd.Series(dtype=float)))),
                "first_hit_rate_60m": _round(_pct_mean(group.get("first_seen_correct_60m", pd.Series(dtype=float)))),
                "avg_invalidation_return_60m_bps": _round(
                    _mean(group.get("invalidation_return_60m_bps", pd.Series(dtype=float)))
                ),
                "invalidation_hit_rate_60m": _round(
                    _pct_mean(group.get("invalidation_correct_60m", pd.Series(dtype=float)))
                ),
                "avg_invalidation_minus_first_return_60m_bps": _round(
                    _mean(group.get("invalidation_minus_first_return_60m_bps", pd.Series(dtype=float)))
                ),
                "invalidation_helped_60m_share": _round(
                    (_positive_share(group.get("invalidation_minus_first_return_60m_bps", pd.Series(dtype=float))) or 0.0)
                    * 100.0
                )
                if group.get("invalidation_minus_first_return_60m_bps", pd.Series(dtype=float)).notna().any()
                else None,
                "avg_invalidation_mfe_60m_bps": _round(
                    _mean(group.get("invalidation_mfe_60m_bps", pd.Series(dtype=float)))
                ),
                "avg_invalidation_mae_60m_bps": _round(
                    _mean(group.get("invalidation_mae_60m_bps", pd.Series(dtype=float)))
                ),
                "avg_invalidation_option_premium_return_60m_bps": _round(
                    _mean(group.get("invalidation_option_premium_return_60m_bps", pd.Series(dtype=float)))
                ),
                "false_positive_removal_60m": _round(
                    len(caught_ids & baseline_non_hit_ids) / len(baseline_non_hit_ids) * 100.0
                    if baseline_non_hit_ids
                    else None
                ),
                "true_positive_loss_60m": _round(
                    len(caught_ids & baseline_hit_ids) / len(baseline_hit_ids) * 100.0 if baseline_hit_ids else None
                ),
            }
        )
        rows.append(row)
    return rows


def _diagnostic_read(report: dict[str, Any]) -> dict[str, Any]:
    by_type = {row.get("first_invalidation_type"): row for row in report.get("first_invalidation_type_summary") or []}
    event_rows = [
        row
        for row in report.get("first_invalidation_type_summary") or []
        if row.get("first_invalidation_type") not in {"None", "nan", "NO_INVALIDATION"}
    ]
    best = None
    if event_rows:
        best = max(
            event_rows,
            key=lambda row: (
                _safe_float(row.get("false_positive_removal_60m"), -1.0) or -1.0,
                _safe_float(row.get("avg_invalidation_minus_first_return_60m_bps"), -1e9) or -1e9,
            ),
        )
    return {
        "episode_sample_is_small": bool((report.get("coverage") or {}).get("episode_count", 0) < 100),
        "invalidation_coverage_pct": (report.get("coverage") or {}).get("invalidation_coverage_pct"),
        "best_observed_invalidation_type": best.get("first_invalidation_type") if best else None,
        "score_decay_observed": "INVALIDATED_SCORE_DECAY" in by_type,
        "candle_rejection_observed": "INVALIDATED_CANDLE_REJECTION" in by_type
        or "INVALIDATED_LEVEL_REJECTION" in by_type,
        "direction_flip_observed": "INVALIDATED_DIRECTION_FLIP" in by_type,
    }


def build_signal_invalidation_report(
    frame: pd.DataFrame,
    *,
    threshold: int = DEFAULT_INVALIDATION_THRESHOLD,
    max_episode_gap_minutes: int = DEFAULT_MAX_EPISODE_GAP_MINUTES,
    score_decay_drop_points: float = DEFAULT_SCORE_DECAY_DROP_POINTS,
) -> dict[str, Any]:
    prepared = prepare_signal_invalidation_frame(frame)
    usable = prepared[
        prepared["signal_ts"].notna()
        & prepared["direction"].isin(["CALL", "PUT"])
        & prepared["runtime_composite_score"].notna()
    ].copy()
    episodes = build_signal_invalidation_episodes(
        frame,
        threshold=threshold,
        max_episode_gap_minutes=max_episode_gap_minutes,
        score_decay_drop_points=score_decay_drop_points,
    )
    ts = usable["signal_ts"].dropna()
    invalidated_count = int(episodes.get("has_invalidation", pd.Series(dtype=bool)).fillna(False).sum()) if not episodes.empty else 0
    report = {
        "report_type": "signal_invalidation_diagnostics",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "threshold": int(threshold),
            "max_episode_gap_minutes": int(max_episode_gap_minutes),
            "score_decay_drop_points": float(score_decay_drop_points),
            "invalidation_rules": {
                "INVALIDATED_DIRECTION_FLIP": "next directional episode flips CALL/PUT",
                "INVALIDATED_SCORE_DECAY": "score falls below threshold or drops by score_decay_drop_points from episode peak",
                "INVALIDATED_CONFIRMATION_LOSS": "confirmation disappears after CONFIRMED/STRONG_CONFIRMATION",
                "INVALIDATED_CANDLE_REJECTION": "candle layer shows rejection, late chase, or invalidation",
                "INVALIDATED_LEVEL_REJECTION": "adverse wall context and candle rejection agree",
                "INVALIDATED_GAMMA_FLIP_CROSS": "spot_vs_flip is against the signal direction",
                "INVALIDATED_PROVIDER_WEAKNESS": "provider/data quality weakens enough to block or degrade execution confidence",
            },
            "guardrail": "research_only_no_live_gate",
        },
        "coverage": {
            "input_rows": int(len(frame)),
            "usable_directional_rows": int(len(usable)),
            "episode_count": int(len(episodes)),
            "invalidated_episode_count": invalidated_count,
            "invalidation_coverage_pct": _round(invalidated_count / len(episodes) * 100.0 if len(episodes) else None),
            "start_timestamp": ts.min().isoformat() if not ts.empty else None,
            "end_timestamp": ts.max().isoformat() if not ts.empty else None,
            "trading_days": int(ts.dt.normalize().nunique()) if not ts.empty else 0,
        },
        "terminal_validity_state_summary": _summarize_groups(episodes, ["terminal_validity_state"]),
        "first_invalidation_type_summary": _summarize_groups(episodes, ["first_invalidation_type"]),
        "regime_invalidation_summary": _summarize_groups(
            episodes,
            ["gamma_regime", "volatility_regime", "global_risk_state"],
            min_rows=2,
        ),
        "provider_invalidation_summary": _summarize_groups(
            episodes,
            ["invalidation_provider_health_status", "invalidation_data_quality_status"],
            min_rows=2,
        ),
        "top_invalidation_examples": _json_ready(episodes.head(25).to_dict(orient="records")) if not episodes.empty else [],
    }
    report["diagnostic_read"] = _diagnostic_read(report)
    return _json_ready(report)


def _markdown_table(rows: list[dict[str, Any]], columns: list[str], *, max_rows: int | None = None) -> list[str]:
    selected = rows[:max_rows] if max_rows is not None else rows
    if not selected:
        return ["No rows available."]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in selected:
        values = []
        for column in columns:
            value = row.get(column)
            values.append("-" if value is None else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def render_signal_invalidation_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    methodology = report.get("methodology") or {}
    lines: list[str] = [
        "# Signal Invalidation Diagnostic Report",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only report detects the first live-time invalidation event inside each directional episode. "
        "It is a diagnostic artifact, not a live execution gate.",
        "",
        f"- Runtime threshold: `{methodology.get('threshold')}`",
        f"- Max episode gap: `{methodology.get('max_episode_gap_minutes')}` minutes",
        f"- Score decay drop: `{methodology.get('score_decay_drop_points')}` points",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Usable directional rows: `{coverage.get('usable_directional_rows')}`",
        f"- Episodes: `{coverage.get('episode_count')}`",
        f"- Invalidated episodes: `{coverage.get('invalidated_episode_count')}`",
        f"- Invalidation coverage: `{coverage.get('invalidation_coverage_pct')}`%",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Episode sample is small: `{read.get('episode_sample_is_small')}`",
        f"- Best observed invalidation type: `{read.get('best_observed_invalidation_type')}`",
        f"- Score decay observed: `{read.get('score_decay_observed')}`",
        f"- Candle/level rejection observed: `{read.get('candle_rejection_observed')}`",
        f"- Direction flip observed: `{read.get('direction_flip_observed')}`",
        "",
        "## First Invalidation Type Summary",
        "",
        "`false_positive_removal_60m` is the share of first-seen 60m misses that had this invalidation. "
        "`true_positive_loss_60m` is the share of first-seen 60m winners that also had this invalidation.",
        "",
    ]
    common_columns = [
        "first_invalidation_type",
        "episode_count",
        "avg_invalidation_delay_minutes",
        "avg_first_score",
        "avg_invalidation_score",
        "avg_first_return_60m_bps",
        "first_hit_rate_60m",
        "avg_invalidation_return_60m_bps",
        "invalidation_hit_rate_60m",
        "avg_invalidation_minus_first_return_60m_bps",
        "invalidation_helped_60m_share",
        "false_positive_removal_60m",
        "true_positive_loss_60m",
    ]
    lines.extend(_markdown_table(report.get("first_invalidation_type_summary") or [], common_columns))
    lines.extend(["", "## Terminal Validity State Summary", ""])
    lines.extend(
        _markdown_table(
            report.get("terminal_validity_state_summary") or [],
            [
                "terminal_validity_state",
                "episode_count",
                "avg_invalidation_delay_minutes",
                "avg_first_return_60m_bps",
                "first_hit_rate_60m",
                "avg_invalidation_return_60m_bps",
                "invalidation_hit_rate_60m",
                "false_positive_removal_60m",
                "true_positive_loss_60m",
            ],
        )
    )
    lines.extend(["", "## Regime Invalidation Summary", ""])
    lines.extend(
        _markdown_table(
            report.get("regime_invalidation_summary") or [],
            [
                "gamma_regime",
                "volatility_regime",
                "global_risk_state",
                "episode_count",
                "invalidation_share",
                "avg_first_return_60m_bps",
                "first_hit_rate_60m",
                "avg_invalidation_return_60m_bps",
                "invalidation_hit_rate_60m",
            ],
            max_rows=20,
        )
    )
    lines.extend(["", "## Provider/Data Quality At Invalidation", ""])
    lines.extend(
        _markdown_table(
            report.get("provider_invalidation_summary") or [],
            [
                "invalidation_provider_health_status",
                "invalidation_data_quality_status",
                "episode_count",
                "avg_invalidation_return_60m_bps",
                "invalidation_hit_rate_60m",
                "false_positive_removal_60m",
                "true_positive_loss_60m",
            ],
            max_rows=20,
        )
    )
    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "",
            "- This report measures invalidation candidates only; it does not prove a live hard block should be added.",
            "- Direction-flip outcomes use returns transformed back into the original episode direction; MFE/MAE is omitted when the event row belongs to the opposite direction.",
            "- Level rejection is deliberately conservative: adverse wall context must coincide with candle rejection.",
            "- Review false-positive removal and true-positive loss together before promoting any rule.",
            "",
        ]
    )
    return "\n".join(lines)


def write_signal_invalidation_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_SIGNAL_INVALIDATION_REPORT_DIR,
    threshold: int = DEFAULT_INVALIDATION_THRESHOLD,
    max_episode_gap_minutes: int = DEFAULT_MAX_EPISODE_GAP_MINUTES,
    score_decay_drop_points: float = DEFAULT_SCORE_DECAY_DROP_POINTS,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    frame = load_signal_invalidation_dataset(dataset)
    report = build_signal_invalidation_report(
        frame,
        threshold=threshold,
        max_episode_gap_minutes=max_episode_gap_minutes,
        score_decay_drop_points=score_decay_drop_points,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output / f"signal_invalidation_diagnostics_{timestamp}.json"
    markdown_path = output / f"signal_invalidation_diagnostics_{timestamp}.md"
    latest_json_path = output / "latest_signal_invalidation_diagnostics.json"
    latest_markdown_path = output / "latest_signal_invalidation_diagnostics.md"

    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_signal_invalidation_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")
    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="signal_invalidation_diagnostics",
        mode="research",
        run_evaluation=False,
        narrative=False,
    )

    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
        "manifest_path": str(manifest_path),
    }

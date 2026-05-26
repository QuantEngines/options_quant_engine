"""Research-only diagnostics for signal lifecycle episodes.

The live engine emits snapshot rows.  This module groups those rows into
directional episodes so we can compare first signal, first threshold crossing,
first confirmation, candle confirmation, and mature signal behavior without
changing live trade decisions.
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
DEFAULT_SIGNAL_LIFECYCLE_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "signal_lifecycle"
)

DEFAULT_LIFECYCLE_THRESHOLD = 50
DEFAULT_MAX_EPISODE_GAP_MINUTES = 15
DEFAULT_MATURE_SNAPSHOT_COUNT = 2
DEFAULT_DECAY_DROP_POINTS = 10.0

MILESTONE_ORDER = (
    "first_seen",
    "first_threshold",
    "first_confirmation",
    "first_candle_confirmation",
    "mature",
)

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
    "ta_candle_confidence",
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


def _score_bucket(score: pd.Series) -> pd.Series:
    return pd.cut(
        pd.to_numeric(score, errors="coerce"),
        bins=[-np.inf, 49.999, 54.999, 59.999, 64.999, 69.999, np.inf],
        labels=["<50", "50-54", "55-59", "60-64", "65-69", "70+"],
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


def _abs_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").abs()


def _mfe_mae_ratio(mfe: pd.Series, mae: pd.Series) -> float | None:
    avg_mfe = _mean(mfe)
    avg_abs_mae = _mean(_abs_numeric(mae))
    if avg_mfe is None or avg_abs_mae is None or avg_abs_mae <= 0:
        return None
    return avg_mfe / avg_abs_mae


def _adverse_path_share(mfe: pd.Series, mae: pd.Series) -> float | None:
    mfe_num = pd.to_numeric(mfe, errors="coerce")
    mae_abs = _abs_numeric(mae)
    valid = pd.DataFrame({"mfe": mfe_num, "mae_abs": mae_abs}).dropna()
    if valid.empty:
        return None
    return float((valid["mae_abs"] > valid["mfe"]).mean())


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
                "ta_candle_confidence",
                "ta_entry_timing_score",
            }
        ):
            working[column] = pd.to_numeric(working[column], errors="coerce")
    return working


def _confirmation_ready(value: Any) -> bool:
    return str(value or "").strip().upper() in {"CONFIRMED", "STRONG_CONFIRMATION"}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().upper() in {"1", "TRUE", "YES", "Y", "ON"}


def _candle_confirms_direction(row: pd.Series) -> bool:
    direction = str(row.get("direction") or "").strip().upper()
    if direction not in {"CALL", "PUT"}:
        return False
    expected_state = f"CANDLE_CONFIRMED_{direction}"
    entry_state = str(row.get("ta_entry_timing_state") or "").strip().upper()
    candle_state = str(row.get("ta_candle_state") or "").strip().upper()
    candle_direction = str(row.get("ta_candle_direction") or "").strip().upper()
    if entry_state == expected_state or candle_state == expected_state:
        return True
    return candle_direction == direction and "CONFIRMED" in entry_state


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


def _minutes_between(later: Any, earlier: Any) -> float | None:
    if pd.isna(later) or pd.isna(earlier):
        return None
    return float((later - earlier).total_seconds() / 60.0)


def load_signal_lifecycle_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Signal dataset not found: {dataset_path}")
    return pd.read_csv(
        dataset_path,
        usecols=lambda column: column in _RUNTIME_COLUMNS,
        low_memory=False,
    )


def prepare_signal_lifecycle_frame(frame: pd.DataFrame) -> pd.DataFrame:
    working = _numeric_columns(frame)
    if "signal_timestamp" not in working.columns:
        working["signal_timestamp"] = pd.NA
    working["signal_ts"] = coerce_timestamp_series(working["signal_timestamp"], utc=True)
    working["signal_date"] = working["signal_ts"].dt.tz_convert("Asia/Kolkata").dt.date.astype(str)
    working["symbol"] = _normalize_text(working.get("symbol", pd.Series(index=working.index)), default="UNKNOWN")
    working["direction"] = _normalize_text(working.get("direction", pd.Series(index=working.index)), default="NO_DIRECTION")
    working["direction_sign"] = working["direction"].map({"CALL": 1.0, "PUT": -1.0})
    working["runtime_composite_score"] = pd.to_numeric(
        working.get("runtime_composite_score", pd.Series(index=working.index)),
        errors="coerce",
    )
    working["score_bucket"] = _score_bucket(working["runtime_composite_score"])
    for column, default in (
        ("confirmation_status", "UNKNOWN"),
        ("trade_status", "UNKNOWN"),
        ("outcome_status", "UNKNOWN"),
        ("label_quality_status", "UNKNOWN"),
        ("gamma_regime", "UNKNOWN"),
        ("volatility_regime", "UNKNOWN"),
        ("global_risk_state", "UNKNOWN"),
        ("macro_regime", "UNKNOWN"),
        ("ta_entry_timing_state", "UNAVAILABLE"),
        ("ta_candle_state", "UNAVAILABLE"),
        ("ta_candle_direction", "UNKNOWN"),
    ):
        working[column] = _normalize_text(working.get(column, pd.Series(index=working.index)), default=default)
    return working


def _row_metrics(row: pd.Series, prefix: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        f"{prefix}_timestamp": row.get("signal_ts").isoformat() if not pd.isna(row.get("signal_ts")) else None,
        f"{prefix}_score": _safe_float(row.get("runtime_composite_score"), None),
        f"{prefix}_trade_strength": _safe_float(row.get("trade_strength"), None),
        f"{prefix}_confirmation_status": str(row.get("confirmation_status") or "UNKNOWN"),
        f"{prefix}_ta_entry_timing_state": str(row.get("ta_entry_timing_state") or "UNAVAILABLE"),
        f"{prefix}_ta_candle_state": str(row.get("ta_candle_state") or "UNAVAILABLE"),
        f"{prefix}_candle_adverse": bool(_candle_adverse(row)),
    }
    for horizon in (15, 30, 60, 120):
        metrics[f"{prefix}_return_{horizon}m_bps"] = _safe_float(row.get(f"signed_return_{horizon}m_bps"), None)
        metrics[f"{prefix}_correct_{horizon}m"] = _safe_float(row.get(f"correct_{horizon}m"), None)
        metrics[f"{prefix}_option_premium_return_{horizon}m_bps"] = _safe_float(
            row.get(f"option_premium_return_{horizon}m_bps"),
            None,
        )
    for horizon in (60, 120):
        metrics[f"{prefix}_mfe_{horizon}m_bps"] = _safe_float(row.get(f"mfe_{horizon}m_bps"), None)
        metrics[f"{prefix}_mae_{horizon}m_bps"] = _safe_float(row.get(f"mae_{horizon}m_bps"), None)
    metrics[f"{prefix}_option_pnl_per_lot_60m"] = _safe_float(row.get("option_premium_pnl_per_lot_60m"), None)
    return metrics


def _first_row_matching(group: pd.DataFrame, mask: pd.Series) -> pd.Series | None:
    candidates = group.loc[mask.fillna(False)]
    if candidates.empty:
        return None
    return candidates.iloc[0]


def _episode_rows(prepared: pd.DataFrame, *, max_episode_gap_minutes: int) -> list[tuple[pd.DataFrame, dict[str, Any]]]:
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
        close_info: dict[str, Any] = {"invalidation_timestamp": None, "invalidation_reason": None}

        def close_active(info: dict[str, Any]) -> None:
            nonlocal active
            if not active:
                return
            episodes.append((pd.DataFrame(active), dict(info)))
            active = []

        for _idx, row in day_group.iterrows():
            if not active:
                active = [row]
                close_info = {"invalidation_timestamp": None, "invalidation_reason": None}
                continue

            previous = active[-1]
            gap = row["signal_ts"] - previous["signal_ts"]
            direction_changed = str(row["direction"]) != str(previous["direction"])
            gap_expired = gap > max_gap
            if direction_changed or gap_expired:
                if direction_changed:
                    close_info = {
                        "invalidation_timestamp": row["signal_ts"].isoformat(),
                        "invalidation_reason": f"DIRECTION_FLIP_TO_{row['direction']}",
                    }
                else:
                    close_info = {
                        "invalidation_timestamp": None,
                        "invalidation_reason": "GAP_EXPIRED",
                    }
                close_active(close_info)
                active = [row]
                close_info = {"invalidation_timestamp": None, "invalidation_reason": None}
                continue

            active.append(row)

        close_active(close_info)
    return episodes


def _episode_payload(
    episode_id: str,
    group: pd.DataFrame,
    close_info: dict[str, Any],
    *,
    threshold: int,
    mature_snapshot_count: int,
    decay_drop_points: float,
) -> dict[str, Any]:
    ordered = group.sort_values("signal_ts", kind="mergesort").reset_index(drop=True)
    first = ordered.iloc[0]
    last = ordered.iloc[-1]
    score = pd.to_numeric(ordered["runtime_composite_score"], errors="coerce")
    threshold_row = _first_row_matching(ordered, score >= float(threshold))
    confirmation_row = _first_row_matching(ordered, ordered["confirmation_status"].map(_confirmation_ready))
    candle_row = _first_row_matching(ordered, ordered.apply(_candle_confirms_direction, axis=1))
    mature_candidates = ordered.loc[score >= float(threshold)]
    mature_row = mature_candidates.iloc[int(mature_snapshot_count) - 1] if len(mature_candidates) >= mature_snapshot_count else None

    peak_pos = int(score.idxmax()) if score.notna().any() else 0
    peak_row = ordered.iloc[peak_pos]
    after_peak = ordered.iloc[peak_pos + 1 :].copy()
    decay_row = None
    peak_score = _safe_float(peak_row.get("runtime_composite_score"), None)
    if peak_score is not None and not after_peak.empty:
        after_score = pd.to_numeric(after_peak["runtime_composite_score"], errors="coerce")
        decay_mask = after_score.le(peak_score - float(decay_drop_points)) | after_score.lt(float(threshold))
        decay_row = _first_row_matching(after_peak, decay_mask)

    first_ts = first.get("signal_ts")
    end_ts = last.get("signal_ts")
    final_score = _safe_float(last.get("runtime_composite_score"), None)
    highest_stage = "FORMING"
    if threshold_row is not None or confirmation_row is not None:
        highest_stage = "CONFIRMED"
    if mature_row is not None:
        highest_stage = "MATURE"
    if decay_row is not None:
        highest_stage = "DECAYING"

    lifecycle_state = highest_stage
    invalidation_reason = str(close_info.get("invalidation_reason") or "")
    if invalidation_reason.startswith("DIRECTION_FLIP"):
        lifecycle_state = "INVALIDATED"
    elif highest_stage == "DECAYING" and final_score is not None and peak_score is not None and final_score <= peak_score - float(decay_drop_points):
        lifecycle_state = "DECAYING"

    payload: dict[str, Any] = {
        "episode_id": episode_id,
        "signal_date": str(first.get("signal_date")),
        "symbol": str(first.get("symbol") or ""),
        "direction": str(first.get("direction") or ""),
        "row_count": int(len(ordered)),
        "start_timestamp": first_ts.isoformat() if not pd.isna(first_ts) else None,
        "end_timestamp": end_ts.isoformat() if not pd.isna(end_ts) else None,
        "duration_minutes": _round(_minutes_between(end_ts, first_ts)),
        "lifecycle_state": lifecycle_state,
        "highest_lifecycle_stage": highest_stage,
        "first_score_bucket": str(first.get("score_bucket")),
        "peak_score": _round(peak_score),
        "final_score": _round(final_score),
        "score_delta_final_vs_first": _round(final_score - _safe_float(first.get("runtime_composite_score"), 0.0))
        if final_score is not None
        else None,
        "gamma_regime": str(first.get("gamma_regime") or "UNKNOWN"),
        "volatility_regime": str(first.get("volatility_regime") or "UNKNOWN"),
        "global_risk_state": str(first.get("global_risk_state") or "UNKNOWN"),
        "macro_regime": str(first.get("macro_regime") or "UNKNOWN"),
        "threshold": int(threshold),
        "mature_snapshot_count": int(mature_snapshot_count),
        "invalidation_timestamp": close_info.get("invalidation_timestamp"),
        "invalidation_reason": close_info.get("invalidation_reason"),
    }
    payload.update(_row_metrics(first, "first_seen"))
    payload["first_seen_delay_minutes"] = 0.0
    payload["first_seen_minus_first_return_60m_bps"] = 0.0
    payload["first_seen_minus_first_option_premium_60m_bps"] = 0.0
    milestone_rows = {
        "first_threshold": threshold_row,
        "first_confirmation": confirmation_row,
        "first_candle_confirmation": candle_row,
        "mature": mature_row,
        "decay": decay_row,
    }
    for prefix, row in milestone_rows.items():
        if row is None:
            payload[f"{prefix}_timestamp"] = None
            payload[f"{prefix}_delay_minutes"] = None
            continue
        payload.update(_row_metrics(row, prefix))
        payload[f"{prefix}_delay_minutes"] = _round(_minutes_between(row.get("signal_ts"), first_ts))
        first_return = _safe_float(first.get("signed_return_60m_bps"), None)
        milestone_return = _safe_float(row.get("signed_return_60m_bps"), None)
        payload[f"{prefix}_minus_first_return_60m_bps"] = _round(
            milestone_return - first_return if first_return is not None and milestone_return is not None else None
        )
        first_premium = _safe_float(first.get("option_premium_return_60m_bps"), None)
        milestone_premium = _safe_float(row.get("option_premium_return_60m_bps"), None)
        payload[f"{prefix}_minus_first_option_premium_60m_bps"] = _round(
            milestone_premium - first_premium if first_premium is not None and milestone_premium is not None else None
        )
    return payload


def build_signal_lifecycle_episodes(
    frame: pd.DataFrame,
    *,
    threshold: int = DEFAULT_LIFECYCLE_THRESHOLD,
    max_episode_gap_minutes: int = DEFAULT_MAX_EPISODE_GAP_MINUTES,
    mature_snapshot_count: int = DEFAULT_MATURE_SNAPSHOT_COUNT,
    decay_drop_points: float = DEFAULT_DECAY_DROP_POINTS,
) -> pd.DataFrame:
    prepared = prepare_signal_lifecycle_frame(frame)
    rows = _episode_rows(prepared, max_episode_gap_minutes=max_episode_gap_minutes)
    payloads = [
        _episode_payload(
            f"{group.iloc[0]['signal_date']}:{group.iloc[0]['symbol']}:{group.iloc[0]['direction']}:{idx + 1}",
            group,
            close_info,
            threshold=threshold,
            mature_snapshot_count=mature_snapshot_count,
            decay_drop_points=decay_drop_points,
        )
        for idx, (group, close_info) in enumerate(rows)
    ]
    return pd.DataFrame(payloads)


def _summarize_episode_groups(episodes: pd.DataFrame, group_cols: list[str], *, min_rows: int = 1) -> list[dict[str, Any]]:
    if episodes.empty:
        return []
    missing = [column for column in group_cols if column not in episodes.columns]
    if missing:
        return []
    rows: list[dict[str, Any]] = []
    for keys, group in episodes.groupby(group_cols, dropna=False, observed=True):
        if len(group) < min_rows:
            continue
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {column: str(value) for column, value in zip(group_cols, keys)}
        row.update(
            {
                "episode_count": int(len(group)),
                "avg_row_count": _round(_mean(group.get("row_count", pd.Series(dtype=float)))),
                "avg_duration_minutes": _round(_mean(group.get("duration_minutes", pd.Series(dtype=float)))),
                "avg_first_score": _round(_mean(group.get("first_seen_score", pd.Series(dtype=float)))),
                "avg_peak_score": _round(_mean(group.get("peak_score", pd.Series(dtype=float)))),
                "avg_first_return_60m_bps": _round(_mean(group.get("first_seen_return_60m_bps", pd.Series(dtype=float)))),
                "first_hit_rate_60m": _round(_pct_mean(group.get("first_seen_correct_60m", pd.Series(dtype=float)))),
                "avg_confirmation_return_60m_bps": _round(
                    _mean(group.get("first_confirmation_return_60m_bps", pd.Series(dtype=float)))
                ),
                "confirmation_hit_rate_60m": _round(
                    _pct_mean(group.get("first_confirmation_correct_60m", pd.Series(dtype=float)))
                ),
                "avg_mature_return_60m_bps": _round(_mean(group.get("mature_return_60m_bps", pd.Series(dtype=float)))),
                "mature_hit_rate_60m": _round(_pct_mean(group.get("mature_correct_60m", pd.Series(dtype=float)))),
                "avg_first_mfe_60m_bps": _round(_mean(group.get("first_seen_mfe_60m_bps", pd.Series(dtype=float)))),
                "avg_first_mae_60m_bps": _round(_mean(group.get("first_seen_mae_60m_bps", pd.Series(dtype=float)))),
                "confirmation_share": _round(group.get("first_confirmation_timestamp", pd.Series(dtype=object)).notna().mean() * 100.0),
                "candle_confirmation_share": _round(
                    group.get("first_candle_confirmation_timestamp", pd.Series(dtype=object)).notna().mean() * 100.0
                ),
                "mature_share": _round(group.get("mature_timestamp", pd.Series(dtype=object)).notna().mean() * 100.0),
                "invalidation_share": _round(_share(group.get("lifecycle_state", pd.Series(dtype=object)), "INVALIDATED") * 100.0),
                "decay_share": _round(group.get("decay_timestamp", pd.Series(dtype=object)).notna().mean() * 100.0),
            }
        )
        rows.append(row)
    return rows


def _milestone_comparison(episodes: pd.DataFrame) -> list[dict[str, Any]]:
    if episodes.empty:
        return []
    baseline_ids = set(episodes["episode_id"].astype(str))
    baseline_correct = pd.to_numeric(episodes.get("first_seen_correct_60m", pd.Series(dtype=float)), errors="coerce")
    baseline_hit_ids = set(episodes.loc[baseline_correct.eq(1.0), "episode_id"].astype(str))
    baseline_non_hit_ids = set(episodes.loc[baseline_correct.eq(0.0), "episode_id"].astype(str))

    rows: list[dict[str, Any]] = []
    for milestone in MILESTONE_ORDER:
        timestamp_col = f"{milestone}_timestamp"
        if milestone == "first_seen":
            selected = episodes.copy()
        elif timestamp_col in episodes.columns:
            selected = episodes.loc[episodes[timestamp_col].notna()].copy()
        else:
            selected = episodes.iloc[0:0].copy()
        selected_ids = set(selected["episode_id"].astype(str)) if not selected.empty else set()
        suppressed_ids = baseline_ids - selected_ids
        return_delta = pd.to_numeric(
            selected.get(f"{milestone}_minus_first_return_60m_bps", pd.Series(0.0, index=selected.index)),
            errors="coerce",
        )
        if milestone == "first_seen":
            return_delta = pd.Series(0.0, index=selected.index, dtype="float64")
        premium_delta = pd.to_numeric(
            selected.get(f"{milestone}_minus_first_option_premium_60m_bps", pd.Series(dtype=float)),
            errors="coerce",
        )
        row = {
            "milestone": milestone,
            "eligible_episode_count": int(len(episodes)),
            "selected_episode_count": int(len(selected)),
            "retention_rate": _round(len(selected) / len(episodes) * 100.0 if len(episodes) else None),
            "avg_delay_minutes": _round(_mean(selected.get(f"{milestone}_delay_minutes", pd.Series(dtype=float)))),
            "avg_score": _round(_mean(selected.get(f"{milestone}_score", pd.Series(dtype=float)))),
            "avg_return_15m_bps": _round(_mean(selected.get(f"{milestone}_return_15m_bps", pd.Series(dtype=float)))),
            "avg_return_30m_bps": _round(_mean(selected.get(f"{milestone}_return_30m_bps", pd.Series(dtype=float)))),
            "avg_return_60m_bps": _round(_mean(selected.get(f"{milestone}_return_60m_bps", pd.Series(dtype=float)))),
            "avg_return_120m_bps": _round(_mean(selected.get(f"{milestone}_return_120m_bps", pd.Series(dtype=float)))),
            "hit_rate_60m": _round(_pct_mean(selected.get(f"{milestone}_correct_60m", pd.Series(dtype=float)))),
            "avg_mfe_60m_bps": _round(_mean(selected.get(f"{milestone}_mfe_60m_bps", pd.Series(dtype=float)))),
            "avg_mae_60m_bps": _round(_mean(selected.get(f"{milestone}_mae_60m_bps", pd.Series(dtype=float)))),
            "mfe_mae_ratio_60m": _round(
                _mfe_mae_ratio(
                    selected.get(f"{milestone}_mfe_60m_bps", pd.Series(dtype=float)),
                    selected.get(f"{milestone}_mae_60m_bps", pd.Series(dtype=float)),
                ),
                3,
            ),
            "adverse_path_share_60m": _round(
                (_adverse_path_share(
                    selected.get(f"{milestone}_mfe_60m_bps", pd.Series(dtype=float)),
                    selected.get(f"{milestone}_mae_60m_bps", pd.Series(dtype=float)),
                ) or 0.0)
                * 100.0,
            )
            if selected.get(f"{milestone}_mfe_60m_bps", pd.Series(dtype=float)).notna().any()
            else None,
            "avg_option_premium_return_60m_bps": _round(
                _mean(selected.get(f"{milestone}_option_premium_return_60m_bps", pd.Series(dtype=float)))
            ),
            "option_premium_hit_rate_60m": _round(
                (_positive_share(selected.get(f"{milestone}_option_premium_return_60m_bps", pd.Series(dtype=float))) or 0.0)
                * 100.0
            )
            if selected.get(f"{milestone}_option_premium_return_60m_bps", pd.Series(dtype=float)).notna().any()
            else None,
            "selected_minus_first_return_60m_bps": _round(_mean(return_delta)),
            "milestone_helped_60m_share": _round((_positive_share(return_delta) or 0.0) * 100.0)
            if return_delta.notna().any()
            else None,
            "selected_minus_first_option_premium_60m_bps": _round(_mean(premium_delta)),
            "premium_milestone_helped_60m_share": _round((_positive_share(premium_delta) or 0.0) * 100.0)
            if premium_delta.notna().any()
            else None,
            "selected_minus_first_mfe_60m_bps": None,
            "mae_improvement_vs_first_60m_bps": None,
            "path_quality_delta_vs_first_60m": None,
            "path_quality_helped_60m_share": None,
            "false_positive_removal_60m": _round(
                len(suppressed_ids & baseline_non_hit_ids) / len(baseline_non_hit_ids) * 100.0
                if baseline_non_hit_ids
                else None
            ),
            "true_positive_loss_60m": _round(
                len(suppressed_ids & baseline_hit_ids) / len(baseline_hit_ids) * 100.0 if baseline_hit_ids else None
            ),
        }
        selected_mfe = pd.to_numeric(selected.get(f"{milestone}_mfe_60m_bps", pd.Series(dtype=float)), errors="coerce")
        first_mfe = pd.to_numeric(selected.get("first_seen_mfe_60m_bps", pd.Series(dtype=float)), errors="coerce")
        selected_mae_abs = _abs_numeric(selected.get(f"{milestone}_mae_60m_bps", pd.Series(dtype=float)))
        first_mae_abs = _abs_numeric(selected.get("first_seen_mae_60m_bps", pd.Series(dtype=float)))
        if milestone == "first_seen":
            mfe_delta = pd.Series(0.0, index=selected.index, dtype="float64")
            mae_improvement = pd.Series(0.0, index=selected.index, dtype="float64")
        else:
            mfe_delta = selected_mfe - first_mfe
            mae_improvement = first_mae_abs - selected_mae_abs
        path_delta = mfe_delta + mae_improvement
        row["selected_minus_first_mfe_60m_bps"] = _round(_mean(mfe_delta))
        row["mae_improvement_vs_first_60m_bps"] = _round(_mean(mae_improvement))
        row["path_quality_delta_vs_first_60m"] = _round(_mean(path_delta))
        row["path_quality_helped_60m_share"] = (
            _round((_positive_share(path_delta) or 0.0) * 100.0) if path_delta.notna().any() else None
        )
        rows.append(row)
    return rows


def _diagnostic_read(report: dict[str, Any]) -> dict[str, Any]:
    milestones = {row.get("milestone"): row for row in report.get("milestone_comparison") or []}
    first = milestones.get("first_seen") or {}
    confirmation = milestones.get("first_confirmation") or {}
    mature = milestones.get("mature") or {}
    comparable = [
        row
        for row in (report.get("milestone_comparison") or [])
        if _safe_float(row.get("mfe_mae_ratio_60m"), None) is not None
        and int(row.get("selected_episode_count") or 0) > 0
    ]
    best_path = max(comparable, key=lambda row: _safe_float(row.get("mfe_mae_ratio_60m"), -np.inf), default={})
    return {
        "episode_sample_is_small": bool((report.get("coverage") or {}).get("episode_count", 0) < 100),
        "confirmation_improves_60m_return": bool(
            _safe_float(confirmation.get("selected_minus_first_return_60m_bps"), 0.0) > 0.0
        )
        if confirmation
        else None,
        "maturity_improves_60m_return": bool(_safe_float(mature.get("selected_minus_first_return_60m_bps"), 0.0) > 0.0)
        if mature
        else None,
        "first_seen_hit_rate_60m": first.get("hit_rate_60m"),
        "first_confirmation_hit_rate_60m": confirmation.get("hit_rate_60m"),
        "mature_hit_rate_60m": mature.get("hit_rate_60m"),
        "first_seen_mfe_mae_ratio_60m": first.get("mfe_mae_ratio_60m"),
        "first_seen_adverse_path_share_60m": first.get("adverse_path_share_60m"),
        "confirmation_improves_path_quality_60m": bool(
            _safe_float(confirmation.get("path_quality_delta_vs_first_60m"), 0.0) > 0.0
        )
        if confirmation
        else None,
        "maturity_improves_path_quality_60m": bool(
            _safe_float(mature.get("path_quality_delta_vs_first_60m"), 0.0) > 0.0
        )
        if mature
        else None,
        "best_path_quality_milestone": best_path.get("milestone"),
        "best_path_quality_mfe_mae_ratio_60m": best_path.get("mfe_mae_ratio_60m"),
    }


def build_signal_lifecycle_report(
    frame: pd.DataFrame,
    *,
    threshold: int = DEFAULT_LIFECYCLE_THRESHOLD,
    max_episode_gap_minutes: int = DEFAULT_MAX_EPISODE_GAP_MINUTES,
    mature_snapshot_count: int = DEFAULT_MATURE_SNAPSHOT_COUNT,
    decay_drop_points: float = DEFAULT_DECAY_DROP_POINTS,
) -> dict[str, Any]:
    prepared = prepare_signal_lifecycle_frame(frame)
    usable = prepared[
        prepared["signal_ts"].notna()
        & prepared["direction"].isin(["CALL", "PUT"])
        & prepared["runtime_composite_score"].notna()
    ].copy()
    episodes = build_signal_lifecycle_episodes(
        frame,
        threshold=threshold,
        max_episode_gap_minutes=max_episode_gap_minutes,
        mature_snapshot_count=mature_snapshot_count,
        decay_drop_points=decay_drop_points,
    )
    ts = usable["signal_ts"].dropna()
    report = {
        "report_type": "signal_lifecycle_diagnostics",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "threshold": int(threshold),
            "max_episode_gap_minutes": int(max_episode_gap_minutes),
            "mature_snapshot_count": int(mature_snapshot_count),
            "decay_drop_points": float(decay_drop_points),
            "episode_split_rules": [
                "new episode starts on first directional CALL/PUT row",
                "episode closes when direction flips or time gap exceeds max_episode_gap_minutes",
                "direction flip marks the prior episode INVALIDATED",
            ],
            "milestones": {
                "first_seen": "first directional row in the episode",
                "first_threshold": "first row with runtime_composite_score >= threshold",
                "first_confirmation": "first row with confirmation_status CONFIRMED or STRONG_CONFIRMATION",
                "first_candle_confirmation": "first row where candle timing confirms the episode direction",
                "mature": "nth row above threshold, where n = mature_snapshot_count",
            },
        },
        "coverage": {
            "input_rows": int(len(frame)),
            "usable_directional_rows": int(len(usable)),
            "episode_count": int(len(episodes)),
            "start_timestamp": ts.min().isoformat() if not ts.empty else None,
            "end_timestamp": ts.max().isoformat() if not ts.empty else None,
            "trading_days": int(ts.dt.normalize().nunique()) if not ts.empty else 0,
            "episodes_with_threshold": int(episodes.get("first_threshold_timestamp", pd.Series(dtype=object)).notna().sum())
            if not episodes.empty
            else 0,
            "episodes_with_confirmation": int(
                episodes.get("first_confirmation_timestamp", pd.Series(dtype=object)).notna().sum()
            )
            if not episodes.empty
            else 0,
            "episodes_with_candle_confirmation": int(
                episodes.get("first_candle_confirmation_timestamp", pd.Series(dtype=object)).notna().sum()
            )
            if not episodes.empty
            else 0,
            "episodes_with_maturity": int(episodes.get("mature_timestamp", pd.Series(dtype=object)).notna().sum())
            if not episodes.empty
            else 0,
        },
        "lifecycle_state_summary": _summarize_episode_groups(episodes, ["lifecycle_state"]),
        "highest_stage_summary": _summarize_episode_groups(episodes, ["highest_lifecycle_stage"]),
        "first_score_bucket_summary": _summarize_episode_groups(episodes, ["first_score_bucket"]),
        "regime_summary": _summarize_episode_groups(
            episodes,
            ["gamma_regime", "volatility_regime", "global_risk_state"],
            min_rows=2,
        ),
        "milestone_comparison": _milestone_comparison(episodes),
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


def render_signal_lifecycle_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    methodology = report.get("methodology") or {}
    lines: list[str] = [
        "# Signal Lifecycle Diagnostic Report",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only report groups live signal snapshots into directional episodes. "
        "It does not alter live decisions.",
        "",
        f"- Runtime threshold: `{methodology.get('threshold')}`",
        f"- Max episode gap: `{methodology.get('max_episode_gap_minutes')}` minutes",
        f"- Mature snapshot count: `{methodology.get('mature_snapshot_count')}`",
        f"- Decay drop: `{methodology.get('decay_drop_points')}` score points from episode peak",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Usable directional rows: `{coverage.get('usable_directional_rows')}`",
        f"- Episodes: `{coverage.get('episode_count')}`",
        f"- Episodes with threshold crossing: `{coverage.get('episodes_with_threshold')}`",
        f"- Episodes with confirmation: `{coverage.get('episodes_with_confirmation')}`",
        f"- Episodes with candle confirmation: `{coverage.get('episodes_with_candle_confirmation')}`",
        f"- Episodes with maturity: `{coverage.get('episodes_with_maturity')}`",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Episode sample is small: `{read.get('episode_sample_is_small')}`",
        f"- Confirmation improves 60m return: `{read.get('confirmation_improves_60m_return')}`",
        f"- Maturity improves 60m return: `{read.get('maturity_improves_60m_return')}`",
        f"- First-seen 60m hit rate: `{read.get('first_seen_hit_rate_60m')}`",
        f"- First-confirmation 60m hit rate: `{read.get('first_confirmation_hit_rate_60m')}`",
        f"- Mature 60m hit rate: `{read.get('mature_hit_rate_60m')}`",
        f"- First-seen MFE/MAE ratio 60m: `{read.get('first_seen_mfe_mae_ratio_60m')}`",
        f"- First-seen adverse path share 60m: `{read.get('first_seen_adverse_path_share_60m')}`",
        f"- Confirmation improves path quality 60m: `{read.get('confirmation_improves_path_quality_60m')}`",
        f"- Maturity improves path quality 60m: `{read.get('maturity_improves_path_quality_60m')}`",
        f"- Best path-quality milestone: `{read.get('best_path_quality_milestone')}` "
        f"(MFE/MAE `{read.get('best_path_quality_mfe_mae_ratio_60m')}`)",
        "",
        "## Milestone Comparison",
        "",
        "Retention shows how many episodes survive to each milestone. "
        "`false_positive_removal_60m` is the share of first-seen 60m misses excluded by waiting; "
        "`true_positive_loss_60m` is the share of first-seen 60m winners excluded by waiting.",
        " `mfe_mae_ratio_60m` above 1 means favorable excursion exceeded adverse excursion on average.",
        "",
    ]
    lines.extend(
        _markdown_table(
            report.get("milestone_comparison") or [],
            [
                "milestone",
                "eligible_episode_count",
                "selected_episode_count",
                "retention_rate",
                "avg_delay_minutes",
                "avg_score",
                "avg_return_60m_bps",
                "hit_rate_60m",
                "avg_mfe_60m_bps",
                "avg_mae_60m_bps",
                "mfe_mae_ratio_60m",
                "adverse_path_share_60m",
                "selected_minus_first_return_60m_bps",
                "selected_minus_first_mfe_60m_bps",
                "mae_improvement_vs_first_60m_bps",
                "path_quality_delta_vs_first_60m",
                "path_quality_helped_60m_share",
                "milestone_helped_60m_share",
                "false_positive_removal_60m",
                "true_positive_loss_60m",
                "avg_option_premium_return_60m_bps",
                "selected_minus_first_option_premium_60m_bps",
            ],
        )
    )
    lines.extend(["", "## Lifecycle State Summary", ""])
    lines.extend(
        _markdown_table(
            report.get("lifecycle_state_summary") or [],
            [
                "lifecycle_state",
                "episode_count",
                "avg_row_count",
                "avg_duration_minutes",
                "avg_first_score",
                "avg_peak_score",
                "avg_first_return_60m_bps",
                "first_hit_rate_60m",
                "avg_confirmation_return_60m_bps",
                "confirmation_hit_rate_60m",
                "confirmation_share",
                "mature_share",
                "invalidation_share",
                "decay_share",
            ],
        )
    )
    lines.extend(["", "## Highest Stage Summary", ""])
    lines.extend(
        _markdown_table(
            report.get("highest_stage_summary") or [],
            [
                "highest_lifecycle_stage",
                "episode_count",
                "avg_first_score",
                "avg_peak_score",
                "avg_first_return_60m_bps",
                "first_hit_rate_60m",
                "avg_mature_return_60m_bps",
                "mature_hit_rate_60m",
                "candle_confirmation_share",
                "decay_share",
            ],
        )
    )
    lines.extend(["", "## First Score Bucket Summary", ""])
    lines.extend(
        _markdown_table(
            report.get("first_score_bucket_summary") or [],
            [
                "first_score_bucket",
                "episode_count",
                "avg_first_score",
                "avg_peak_score",
                "avg_first_return_60m_bps",
                "first_hit_rate_60m",
                "confirmation_share",
                "mature_share",
                "invalidation_share",
            ],
        )
    )
    lines.extend(["", "## Regime Summary", ""])
    lines.extend(
        _markdown_table(
            report.get("regime_summary") or [],
            [
                "gamma_regime",
                "volatility_regime",
                "global_risk_state",
                "episode_count",
                "avg_first_return_60m_bps",
                "first_hit_rate_60m",
                "avg_confirmation_return_60m_bps",
                "confirmation_hit_rate_60m",
                "mature_share",
                "invalidation_share",
            ],
            max_rows=20,
        )
    )
    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "",
            "- This is research-only and must not be used as a hidden live gate.",
            "- Direction flips mark terminal invalidation, but they do not prove a trade should have exited at that exact moment.",
            "- Milestone retention can remove false positives and true positives; both must be reviewed together.",
            "- Candle milestones require post-restart live capture or post-close candle backfill.",
            "",
        ]
    )
    return "\n".join(lines)


def write_signal_lifecycle_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_SIGNAL_LIFECYCLE_REPORT_DIR,
    threshold: int = DEFAULT_LIFECYCLE_THRESHOLD,
    max_episode_gap_minutes: int = DEFAULT_MAX_EPISODE_GAP_MINUTES,
    mature_snapshot_count: int = DEFAULT_MATURE_SNAPSHOT_COUNT,
    decay_drop_points: float = DEFAULT_DECAY_DROP_POINTS,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    frame = load_signal_lifecycle_dataset(dataset)
    report = build_signal_lifecycle_report(
        frame,
        threshold=threshold,
        max_episode_gap_minutes=max_episode_gap_minutes,
        mature_snapshot_count=mature_snapshot_count,
        decay_drop_points=decay_drop_points,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output / f"signal_lifecycle_diagnostics_{timestamp}.json"
    markdown_path = output / f"signal_lifecycle_diagnostics_{timestamp}.md"
    latest_json_path = output / "latest_signal_lifecycle_diagnostics.json"
    latest_markdown_path = output / "latest_signal_lifecycle_diagnostics.md"

    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_signal_lifecycle_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")
    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="signal_lifecycle_diagnostics",
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

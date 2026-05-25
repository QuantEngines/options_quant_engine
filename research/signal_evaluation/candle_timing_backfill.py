"""Backfill intraday candle timing features into signal-evaluation datasets."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from data.spot_history import load_spot_history
from features.ta_indicators import build_intraday_candle_features
from research.signal_evaluation.dataset import (
    CUMULATIVE_DATASET_PATH,
    load_signals_dataset,
    write_signals_dataset,
)


CANDLE_TIMING_COLUMNS = [
    "ta_candle_status",
    "ta_candle_interval_minutes",
    "ta_candle_observation_count",
    "ta_candle_count",
    "ta_candle_timestamp",
    "ta_candle_open",
    "ta_candle_high",
    "ta_candle_low",
    "ta_candle_close",
    "ta_candle_body_bps",
    "ta_candle_range_bps",
    "ta_candle_close_location",
    "ta_candle_upper_wick_share",
    "ta_candle_lower_wick_share",
    "ta_candle_range_expansion_ratio",
    "ta_candle_momentum_3_bps",
    "ta_candle_momentum_5_bps",
    "ta_candle_prior_move_15m_bps",
    "ta_candle_prior_move_30m_bps",
    "ta_candle_direction",
    "ta_candle_state",
    "ta_candle_confidence",
    "ta_candle_late_chase",
    "ta_candle_rejection",
    "ta_candle_range_expanded",
    "ta_candle_warning",
    "ta_entry_timing_state",
    "ta_entry_timing_score",
    "ta_entry_timing_reasons",
]


def _as_ist_timestamp(value: Any) -> pd.Timestamp | None:
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("Asia/Kolkata")
    return ts.tz_convert("Asia/Kolkata")


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not pd.notna(parsed):
        return None
    return parsed


def _day_bounds(ts: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = ts.normalize()
    return start, start + pd.Timedelta(days=1)


def enrich_candle_timing_features(
    frame: pd.DataFrame,
    *,
    limit: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Populate candle timing fields from local spot history.

    The calculation uses only rows at or before each signal timestamp, so it is
    suitable for post-session replay/backfill without outcome leakage.
    """
    if frame is None or frame.empty:
        return frame.copy() if frame is not None else pd.DataFrame(), {
            "rows_seen": 0,
            "rows_enriched": 0,
            "status_counts": {},
        }

    updated = frame.copy()
    for column in CANDLE_TIMING_COLUMNS:
        if column not in updated.columns:
            updated[column] = pd.NA

    rows_seen = 0
    rows_enriched = 0
    skipped_missing_timestamp = 0
    skipped_missing_spot = 0
    status_counts: Counter[str] = Counter()
    history_cache: dict[tuple[str, str], pd.DataFrame] = {}

    iterable = updated.iterrows()
    for idx, row in iterable:
        if limit is not None and rows_seen >= int(limit):
            break
        rows_seen += 1

        ts = _as_ist_timestamp(row.get("signal_timestamp"))
        if ts is None:
            skipped_missing_timestamp += 1
            continue

        spot = _safe_float(row.get("spot_at_signal"))
        if spot is None:
            skipped_missing_spot += 1
            continue

        symbol = str(row.get("symbol") or "NIFTY").upper().strip() or "NIFTY"
        cache_key = (symbol, ts.strftime("%Y-%m-%d"))
        if cache_key not in history_cache:
            start, end = _day_bounds(ts)
            history_cache[cache_key] = load_spot_history(symbol, start_ts=start, end_ts=end, dedupe=False)

        features = build_intraday_candle_features(
            symbol,
            spot,
            intraday_history_df=history_cache[cache_key],
            as_of=ts,
            allow_live_history=False,
        )
        for column in CANDLE_TIMING_COLUMNS:
            updated.at[idx, column] = features.get(column)

        status = str(features.get("ta_candle_status") or "UNKNOWN")
        status_counts[status] += 1
        if status == "OK":
            rows_enriched += 1

    summary = {
        "rows_seen": int(rows_seen),
        "rows_enriched": int(rows_enriched),
        "skipped_missing_timestamp": int(skipped_missing_timestamp),
        "skipped_missing_spot": int(skipped_missing_spot),
        "status_counts": dict(status_counts),
    }
    return updated, summary


def run_candle_timing_backfill(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    write: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    path = Path(dataset_path)
    frame = load_signals_dataset(path)
    updated, summary = enrich_candle_timing_features(frame, limit=limit)
    if write:
        write_signals_dataset(updated, path)
    return {
        **summary,
        "dataset_path": str(path),
        "write": bool(write),
    }

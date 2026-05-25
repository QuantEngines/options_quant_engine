"""Backfill raw level-capture fields from stored historical context JSON."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH, load_signals_dataset, write_signals_dataset


LEVEL_BACKFILL_COLUMNS = [
    "support_wall",
    "support_wall_distance_pts",
    "support_wall_distance_pct",
    "resistance_wall",
    "resistance_wall_distance_pts",
    "resistance_wall_distance_pct",
    "gamma_flip",
    "max_pain",
    "max_pain_dist",
    "max_pain_zone",
    "max_pain_distance_pct",
]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(number):
        return None
    return number


def _coerce_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        loaded = json.loads(value)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _signed_distance(level: Any, spot: Any) -> tuple[float | None, float | None]:
    level_value = _safe_float(level)
    spot_value = _safe_float(spot)
    if level_value is None or spot_value in (None, 0.0):
        return None, None
    distance = level_value - spot_value
    return round(distance, 4), round(distance / spot_value * 100.0, 6)


def _gamma_flip_from_distance(row: pd.Series) -> float | None:
    spot = _safe_float(row.get("spot_at_signal"))
    distance_pct = _safe_float(row.get("gamma_flip_distance_pct"))
    if spot in (None, 0.0) or distance_pct is None:
        return None
    side = str(row.get("spot_vs_flip") or "").strip().upper()
    distance_points = spot * distance_pct / 100.0
    if side == "ABOVE_FLIP":
        return round(spot - distance_points, 4)
    if side == "BELOW_FLIP":
        return round(spot + distance_points, 4)
    if side == "AT_FLIP":
        return round(spot, 4)
    return None


def enrich_level_capture_fields(frame: pd.DataFrame, *, limit: int | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    working = frame.copy()
    for column in LEVEL_BACKFILL_COLUMNS:
        if column not in working.columns:
            working[column] = pd.NA

    rows_seen = 0
    rows_enriched = 0
    field_updates = {column: 0 for column in LEVEL_BACKFILL_COLUMNS}
    iterable = working.iterrows()
    for idx, row in iterable:
        if limit is not None and rows_seen >= int(limit):
            break
        rows_seen += 1
        context = _coerce_json(row.get("historical_context_json"))
        wall = context.get("wall_context") if isinstance(context.get("wall_context"), dict) else {}
        max_pain = context.get("max_pain_context") if isinstance(context.get("max_pain_context"), dict) else {}
        updates: dict[str, Any] = {}

        support = wall.get("support_wall")
        support_dist, support_pct = _signed_distance(support, row.get("spot_at_signal"))
        resistance = wall.get("resistance_wall")
        resistance_dist, resistance_pct = _signed_distance(resistance, row.get("spot_at_signal"))
        max_pain_dist = max_pain.get("distance_points")
        spot = _safe_float(row.get("spot_at_signal"))
        max_pain_level = None
        if spot is not None and _safe_float(max_pain_dist) is not None:
            max_pain_level = round(spot + float(max_pain_dist), 4)
        gamma_flip = _gamma_flip_from_distance(row)

        candidate_updates = {
            "support_wall": support,
            "support_wall_distance_pts": support_dist,
            "support_wall_distance_pct": support_pct,
            "resistance_wall": resistance,
            "resistance_wall_distance_pts": resistance_dist,
            "resistance_wall_distance_pct": resistance_pct,
            "gamma_flip": gamma_flip,
            "max_pain": max_pain_level,
            "max_pain_dist": max_pain_dist,
            "max_pain_zone": max_pain.get("state"),
            "max_pain_distance_pct": max_pain.get("distance_pct"),
        }
        for column, value in candidate_updates.items():
            if value is not None and _is_blank(working.at[idx, column]):
                updates[column] = value

        if not updates:
            continue
        for column, value in updates.items():
            working.at[idx, column] = value
            field_updates[column] += 1
        rows_enriched += 1

    summary = {
        "rows_seen": int(rows_seen),
        "rows_enriched": int(rows_enriched),
        "field_updates": field_updates,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    return working, summary


def backfill_level_capture_fields(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    write: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    frame = load_signals_dataset(dataset)
    updated, summary = enrich_level_capture_fields(frame, limit=limit)
    if write:
        write_signals_dataset(updated, dataset)
    summary.update(
        {
            "dataset_path": str(dataset),
            "write": bool(write),
        }
    )
    return summary

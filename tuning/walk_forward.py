"""
Deterministic walk-forward split engine for time-based validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tuning.models import WalkForwardSplit


DEFAULT_WALK_FORWARD_CONFIG = {
    "split_type": "anchored",
    "train_window_days": 60,
    "validation_window_days": 20,
    "step_size_days": 20,
    "minimum_train_rows": 20,
    "minimum_validation_rows": 10,
}


@dataclass(frozen=True)
class SplitFrames:
    train: pd.DataFrame
    validation: pd.DataFrame


def _prepare_frame(frame: pd.DataFrame, timestamp_col: str = "signal_timestamp") -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=[timestamp_col])

    ordered = frame.copy()
    ordered[timestamp_col] = pd.to_datetime(ordered[timestamp_col], errors="coerce")
    ordered = ordered.dropna(subset=[timestamp_col])
    return ordered.sort_values(timestamp_col, kind="stable").reset_index(drop=True)


def build_walk_forward_splits(
    frame: pd.DataFrame,
    *,
    split_type: str = "anchored",
    train_window_days: int = 60,
    validation_window_days: int = 20,
    step_size_days: int | None = None,
    minimum_train_rows: int = 20,
    minimum_validation_rows: int = 10,
    timestamp_col: str = "signal_timestamp",
) -> list[WalkForwardSplit]:
    ordered = _prepare_frame(frame, timestamp_col=timestamp_col)
    if ordered.empty:
        return []

    split_type = str(split_type or "anchored").lower().strip()
    if split_type not in {"anchored", "rolling"}:
        raise ValueError("split_type must be 'anchored' or 'rolling'")

    train_window = pd.Timedelta(days=max(int(train_window_days), 1))
    validation_window = pd.Timedelta(days=max(int(validation_window_days), 1))
    step_size = pd.Timedelta(days=max(int(step_size_days or validation_window_days), 1))

    min_ts = ordered[timestamp_col].min()
    max_ts = ordered[timestamp_col].max()
    cursor = min_ts
    split_index = 0
    splits: list[WalkForwardSplit] = []

    while True:
        train_start = min_ts if split_type == "anchored" else cursor
        train_end = train_start + train_window
        validation_start = train_end
        validation_end = validation_start + validation_window

        if validation_start > max_ts:
            break

        train_mask = (ordered[timestamp_col] >= train_start) & (ordered[timestamp_col] < train_end)
        validation_mask = (ordered[timestamp_col] >= validation_start) & (ordered[timestamp_col] < validation_end)
        train_frame = ordered.loc[train_mask]
        validation_frame = ordered.loc[validation_mask]

        if len(train_frame) >= minimum_train_rows and len(validation_frame) >= minimum_validation_rows:
            splits.append(
                WalkForwardSplit(
                    split_id=f"{split_type}_{split_index:03d}",
                    split_type=split_type,
                    train_start=train_frame[timestamp_col].min().isoformat() if not train_frame.empty else None,
                    train_end=train_frame[timestamp_col].max().isoformat() if not train_frame.empty else None,
                    validation_start=validation_frame[timestamp_col].min().isoformat() if not validation_frame.empty else None,
                    validation_end=validation_frame[timestamp_col].max().isoformat() if not validation_frame.empty else None,
                    train_count=int(len(train_frame)),
                    validation_count=int(len(validation_frame)),
                )
            )
            split_index += 1

        cursor = cursor + step_size
        if cursor > max_ts:
            break

    return splits


def apply_walk_forward_split(
    frame: pd.DataFrame,
    split: WalkForwardSplit | dict[str, Any],
    *,
    timestamp_col: str = "signal_timestamp",
) -> SplitFrames:
    ordered = _prepare_frame(frame, timestamp_col=timestamp_col)
    split_payload = split.to_dict() if hasattr(split, "to_dict") else dict(split or {})
    if ordered.empty:
        return SplitFrames(train=ordered.copy(), validation=ordered.copy())

    train_start = pd.to_datetime(split_payload.get("train_start"), errors="coerce")
    train_end = pd.to_datetime(split_payload.get("train_end"), errors="coerce")
    validation_start = pd.to_datetime(split_payload.get("validation_start"), errors="coerce")
    validation_end = pd.to_datetime(split_payload.get("validation_end"), errors="coerce")

    train_mask = pd.Series(True, index=ordered.index)
    validation_mask = pd.Series(True, index=ordered.index)

    if pd.notna(train_start):
        train_mask &= ordered[timestamp_col] >= train_start
    if pd.notna(train_end):
        train_mask &= ordered[timestamp_col] <= train_end
    if pd.notna(validation_start):
        validation_mask &= ordered[timestamp_col] >= validation_start
    if pd.notna(validation_end):
        validation_mask &= ordered[timestamp_col] <= validation_end

    return SplitFrames(
        train=ordered.loc[train_mask].copy().reset_index(drop=True),
        validation=ordered.loc[validation_mask].copy().reset_index(drop=True),
    )

#!/usr/bin/env python3
"""Train and persist runtime score calibrator from signal_cumul dataset."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH, load_signals_dataset
from strategy.score_calibration import ScoreCalibrator


def _pick_return_column(columns):
    cols = [str(c) for c in columns]
    preferred = [
        "return_60m_bps",
        "pnl_60m_bps",
        "realized_return_60m_bps",
        "return_60m_pct",
        "pnl_60m_pct",
    ]
    for c in preferred:
        if c in cols:
            return c
    for c in cols:
        lc = c.lower()
        if "60m" in lc and ("return" in lc or "pnl" in lc):
            return c
    return None


def main() -> int:
    df = load_signals_dataset(CUMULATIVE_DATASET_PATH)
    if df.empty:
        raise RuntimeError("Cumulative dataset is empty")

    req_cols = ["composite_signal_score", "correct_60m"]
    for col in req_cols:
        if col not in df.columns:
            raise KeyError(f"Missing required column: {col}")

    raw_scores = pd.to_numeric(df["composite_signal_score"], errors="coerce").fillna(50.0).astype(float).tolist()
    hit_flags = (pd.to_numeric(df["correct_60m"], errors="coerce").fillna(0.0) > 0).astype(float)

    # Utility-aware target: blend directional correctness with realized return quality
    # when return columns are available in the cumulative dataset.
    target_source = "correct_60m"
    return_col = _pick_return_column(df.columns)
    if return_col is not None:
        r = pd.to_numeric(df[return_col], errors="coerce").fillna(0.0).astype(float)
        scale = float(max(r.abs().quantile(0.75), 1e-6))
        utility = 1.0 / (1.0 + np.exp(-(r / scale)))
        calibration_target = (0.5 * hit_flags) + (0.5 * utility)
        target_source = f"blend(correct_60m,{return_col})"
    else:
        calibration_target = hit_flags

    hit_flags = calibration_target.tolist()

    calibrator = ScoreCalibrator(method="isotonic", n_bins=10)
    report = calibrator.fit(raw_scores, hit_flags)
    report["target_source"] = target_source

    out_model = PROJECT_ROOT / "models_store" / "runtime_score_calibrator.json"
    out_model.parent.mkdir(parents=True, exist_ok=True)
    calibrator.save_to_file(str(out_model))

    out_report = PROJECT_ROOT / "documentation" / "improvement_reports" / f"runtime_score_calibrator_train_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    out_report.parent.mkdir(parents=True, exist_ok=True)
    def _json_safe(v):
        if isinstance(v, (np.generic,)):
            return v.item()
        raise TypeError(f"Object of type {type(v).__name__} is not JSON serializable")

    with out_report.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=_json_safe)

    print(f"Saved calibrator: {out_model}")
    print(f"Saved report: {out_report}")
    print(f"Calibration gap: {report.get('overall_calibration_gap')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

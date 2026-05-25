#!/usr/bin/env python3
"""Generate the runtime-composite entry-timing diagnostic report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.entry_timing_diagnostics import (  # noqa: E402
    DEFAULT_CANDLE_CONFIRMATION_WINDOW_MINUTES,
    DEFAULT_CONFIRMATION_WINDOW_MINUTES,
    DEFAULT_ENTRY_TIMING_REPORT_DIR,
    DEFAULT_FUTURE_EDGE_BPS,
    DEFAULT_PULLBACK_BPS,
    DEFAULT_PULLBACK_WINDOW_MINUTES,
    DEFAULT_PRIOR_STRETCH_BPS,
    write_entry_timing_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ENTRY_TIMING_REPORT_DIR)
    parser.add_argument("--prior-stretch-bps", type=float, default=DEFAULT_PRIOR_STRETCH_BPS)
    parser.add_argument("--future-edge-bps", type=float, default=DEFAULT_FUTURE_EDGE_BPS)
    parser.add_argument("--classification-horizon-minutes", type=int, default=60)
    parser.add_argument("--confirmation-window-minutes", type=int, default=DEFAULT_CONFIRMATION_WINDOW_MINUTES)
    parser.add_argument("--pullback-window-minutes", type=int, default=DEFAULT_PULLBACK_WINDOW_MINUTES)
    parser.add_argument("--candle-confirmation-window-minutes", type=int, default=DEFAULT_CANDLE_CONFIRMATION_WINDOW_MINUTES)
    parser.add_argument("--pullback-bps", type=float, default=DEFAULT_PULLBACK_BPS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_entry_timing_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        prior_stretch_bps=args.prior_stretch_bps,
        future_edge_bps=args.future_edge_bps,
        classification_horizon_minutes=args.classification_horizon_minutes,
        confirmation_window_minutes=args.confirmation_window_minutes,
        pullback_window_minutes=args.pullback_window_minutes,
        candle_confirmation_window_minutes=args.candle_confirmation_window_minutes,
        pullback_bps=args.pullback_bps,
    )
    report = result["report"]
    payload = {
        "report_type": report.get("report_type"),
        "runtime_rows": (report.get("coverage") or {}).get("runtime_rows"),
        "mature_60m_rows": (report.get("coverage") or {}).get("mature_60m_rows"),
        "max_runtime_composite_score": (report.get("coverage") or {}).get("max_runtime_composite_score"),
        "late_chase_thesis_supported": (report.get("diagnostic_read") or {}).get("late_chase_thesis_supported"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

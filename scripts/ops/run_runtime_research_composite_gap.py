#!/usr/bin/env python3
"""Generate runtime-vs-research composite gap diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.runtime_research_composite_gap import (  # noqa: E402
    DEFAULT_RESEARCH_HIGH_THRESHOLD,
    DEFAULT_RESEARCH_LOW_THRESHOLD,
    DEFAULT_RUNTIME_HIGH_THRESHOLD,
    DEFAULT_RUNTIME_LOW_THRESHOLD,
    DEFAULT_RUNTIME_RESEARCH_COMPOSITE_GAP_REPORT_DIR,
    write_runtime_research_composite_gap_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUNTIME_RESEARCH_COMPOSITE_GAP_REPORT_DIR)
    parser.add_argument("--date", default=None, help="Optional YYYY-MM-DD date filter in Asia/Kolkata session date.")
    parser.add_argument("--research-high-threshold", type=float, default=DEFAULT_RESEARCH_HIGH_THRESHOLD)
    parser.add_argument("--runtime-low-threshold", type=float, default=DEFAULT_RUNTIME_LOW_THRESHOLD)
    parser.add_argument("--runtime-high-threshold", type=float, default=DEFAULT_RUNTIME_HIGH_THRESHOLD)
    parser.add_argument("--research-low-threshold", type=float, default=DEFAULT_RESEARCH_LOW_THRESHOLD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_runtime_research_composite_gap_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        report_date=args.date,
        research_high_threshold=args.research_high_threshold,
        runtime_low_threshold=args.runtime_low_threshold,
        runtime_high_threshold=args.runtime_high_threshold,
        research_low_threshold=args.research_low_threshold,
    )
    report = result["report"]
    read = report.get("diagnostic_read") or {}
    alignment = report.get("score_alignment") or {}
    payload = {
        "report_type": report.get("report_type"),
        "comparable_rows": (report.get("coverage") or {}).get("comparable_rows"),
        "spearman_correlation": alignment.get("spearman_correlation"),
        "avg_score_gap": alignment.get("avg_score_gap"),
        "blindspot_rows": read.get("blindspot_rows"),
        "false_confidence_rows": read.get("false_confidence_rows"),
        "primary_read": read.get("primary_read"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

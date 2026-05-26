#!/usr/bin/env python3
"""Generate runtime bucket forensic diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.runtime_bucket_forensics import (  # noqa: E402
    DEFAULT_RUNTIME_BUCKET_FORENSICS_REPORT_DIR,
    write_runtime_bucket_forensics_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUNTIME_BUCKET_FORENSICS_REPORT_DIR)
    parser.add_argument("--date", default=None, help="Optional YYYY-MM-DD date filter in Asia/Kolkata session date.")
    parser.add_argument("--target-bucket", default="50-60")
    parser.add_argument("--min-slice-rows", type=int, default=5)
    parser.add_argument("--min-intersection-rows", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_runtime_bucket_forensics_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        report_date=args.date,
        target_bucket=args.target_bucket,
        min_slice_rows=args.min_slice_rows,
        min_intersection_rows=args.min_intersection_rows,
    )
    report = result["report"]
    read = report.get("diagnostic_read") or {}
    payload = {
        "report_type": report.get("report_type"),
        "primary_read": read.get("primary_read"),
        "target_bucket": read.get("target_bucket"),
        "target_rows": read.get("target_rows"),
        "target_hit_rate_60m": read.get("target_hit_rate_60m"),
        "target_avg_return_60m_bps": read.get("target_avg_return_60m_bps"),
        "target_best_horizon": read.get("target_best_horizon"),
        "best_target_intersection": read.get("best_target_intersection"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "latest_bucket_csv_path": result.get("latest_bucket_csv_path"),
        "latest_slice_csv_path": result.get("latest_slice_csv_path"),
        "latest_intersection_csv_path": result.get("latest_intersection_csv_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

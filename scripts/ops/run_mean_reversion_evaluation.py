#!/usr/bin/env python3
"""Generate the research-only mean-reversion evaluation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.mean_reversion_evaluation import (  # noqa: E402
    DEFAULT_MEAN_REVERSION_REPORT_DIR,
    write_mean_reversion_evaluation_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_MEAN_REVERSION_REPORT_DIR)
    parser.add_argument("--date", default=None, help="Optional exact YYYY-MM-DD Asia/Kolkata session date.")
    parser.add_argument("--start-date", default=None, help="Optional inclusive YYYY-MM-DD session-date lower bound.")
    parser.add_argument("--end-date", default=None, help="Optional inclusive YYYY-MM-DD session-date upper bound.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_mean_reversion_evaluation_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        report_date=args.date,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    report = result["report"]
    read = report.get("diagnostic_read") or {}
    coverage = report.get("coverage") or {}
    payload = {
        "report_type": report.get("report_type"),
        "prepared_rows": coverage.get("prepared_rows"),
        "feature_rows": coverage.get("feature_rows"),
        "sessions": coverage.get("sessions"),
        "primary_read": read.get("primary_read"),
        "observations": read.get("observations"),
        "mean_reversion_60m_labels": read.get("mean_reversion_60m_labels"),
        "mean_reversion_60m_hit_rate": read.get("mean_reversion_60m_hit_rate"),
        "mean_reversion_60m_return_bps": read.get("mean_reversion_60m_return_bps"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

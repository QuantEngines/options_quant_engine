#!/usr/bin/env python3
"""Audit whether signal datasets contain raw level fields for ET-08 replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.level_capture_audit import (  # noqa: E402
    DEFAULT_LEVEL_CAPTURE_AUDIT_DIR,
    write_level_capture_audit,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_LEVEL_CAPTURE_AUDIT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_level_capture_audit(dataset_path=args.dataset, output_dir=args.output_dir)
    report = result["report"]
    payload = {
        "report_type": report.get("report_type"),
        "row_count": report.get("row_count"),
        "readiness": report.get("readiness"),
        "missing_raw_level_columns": report.get("missing_raw_level_columns"),
        "low_coverage_core_columns": report.get("low_coverage_core_columns"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

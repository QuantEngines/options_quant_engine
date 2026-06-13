#!/usr/bin/env python3
"""Generate the research-only feature lineage report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.feature_lineage_report import (  # noqa: E402
    DEFAULT_FEATURE_LINEAGE_REPORT_DIR,
    write_feature_lineage_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_FEATURE_LINEAGE_REPORT_DIR)
    parser.add_argument("--date", default=None, help="Optional YYYY-MM-DD session-date filter.")
    parser.add_argument("--start-date", default=None, help="Optional inclusive YYYY-MM-DD lower bound.")
    parser.add_argument("--end-date", default=None, help="Optional inclusive YYYY-MM-DD upper bound.")
    parser.add_argument("--state-min-rows", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_feature_lineage_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        report_date=args.date,
        start_date=args.start_date,
        end_date=args.end_date,
        state_min_rows=args.state_min_rows,
    )
    report = result.get("report") or {}
    read = report.get("diagnostic_read") or {}
    coverage = report.get("coverage") or {}
    payload = {
        "report_type": report.get("report_type"),
        "primary_read": read.get("primary_read"),
        "observations": read.get("observations"),
        "prepared_directional_rows": coverage.get("prepared_directional_rows"),
        "quality_label_count_60m": coverage.get("quality_label_count_60m"),
        "feature_count": coverage.get("feature_count"),
        "best_score_feature": read.get("best_score_feature"),
        "best_score_spearman_return_60m": read.get("best_score_spearman_return_60m"),
        "best_runtime_component": read.get("best_runtime_component"),
        "best_runtime_component_spearman_return_60m": read.get("best_runtime_component_spearman_return_60m"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "latest_feature_csv_path": result.get("latest_feature_csv_path"),
        "latest_factor_csv_path": result.get("latest_factor_csv_path"),
        "latest_state_csv_path": result.get("latest_state_csv_path"),
        "latest_component_csv_path": result.get("latest_component_csv_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

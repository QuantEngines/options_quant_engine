#!/usr/bin/env python3
"""Generate the research-only decision quality convergence diagnostic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.decision_quality_convergence import (  # noqa: E402
    DEFAULT_DECISION_QUALITY_CONVERGENCE_REPORT_DIR,
    write_decision_quality_convergence_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DECISION_QUALITY_CONVERGENCE_REPORT_DIR)
    parser.add_argument("--date", default=None, help="Optional YYYY-MM-DD session-date filter.")
    parser.add_argument("--start-date", default=None, help="Optional inclusive YYYY-MM-DD lower bound.")
    parser.add_argument("--end-date", default=None, help="Optional inclusive YYYY-MM-DD upper bound.")
    parser.add_argument("--grid-min-rows", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_decision_quality_convergence_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        report_date=args.date,
        start_date=args.start_date,
        end_date=args.end_date,
        grid_min_rows=args.grid_min_rows,
    )
    report = result["report"]
    read = report.get("diagnostic_read") or {}
    coverage = report.get("coverage") or {}
    payload = {
        "report_type": report.get("report_type"),
        "primary_read": read.get("primary_read"),
        "observations": read.get("observations"),
        "prepared_directional_rows": coverage.get("prepared_directional_rows"),
        "quality_approved_60m_labels": coverage.get("quality_approved_60m_labels"),
        "trade_strength_spearman_return_60m": read.get("trade_strength_spearman_return_60m"),
        "runtime_composite_spearman_return_60m": read.get("runtime_composite_spearman_return_60m"),
        "guarded_blend_spearman_return_60m": read.get("guarded_blend_spearman_return_60m"),
        "trade_pass_runtime_fail_label_count_60m": read.get("trade_pass_runtime_fail_label_count_60m"),
        "trade_pass_runtime_fail_avg_return_60m_bps": read.get("trade_pass_runtime_fail_avg_return_60m_bps"),
        "both_fail_avg_return_60m_bps": read.get("both_fail_avg_return_60m_bps"),
        "best_top_quantile_metric_by_return_lift": read.get("best_top_quantile_metric_by_return_lift"),
        "best_top_quantile_return_lift_60m_bps": read.get("best_top_quantile_return_lift_60m_bps"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "latest_metric_csv_path": result.get("latest_metric_csv_path"),
        "latest_bucket_csv_path": result.get("latest_bucket_csv_path"),
        "latest_gate_csv_path": result.get("latest_gate_csv_path"),
        "latest_grid_csv_path": result.get("latest_grid_csv_path"),
        "latest_residual_csv_path": result.get("latest_residual_csv_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

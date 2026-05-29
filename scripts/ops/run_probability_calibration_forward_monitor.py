#!/usr/bin/env python3
"""Generate the research-only probability calibration forward monitor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.probability_calibration_forward_monitor import (  # noqa: E402
    DEFAULT_ALERT_ABS_GAP,
    DEFAULT_GROUP_FIELDS,
    DEFAULT_MIN_LABELED_ROWS,
    DEFAULT_MIN_SESSION_COUNT,
    DEFAULT_MIN_SLICE_LABELS,
    DEFAULT_PROBABILITY_CALIBRATION_FORWARD_MONITOR_DIR,
    DEFAULT_SEVERE_ABS_GAP,
    write_probability_calibration_forward_monitor_report,
)
from research.signal_evaluation.signal_quality_model_audit import DEFAULT_PROBABILITY_FIELD  # noqa: E402


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PROBABILITY_CALIBRATION_FORWARD_MONITOR_DIR)
    parser.add_argument("--probability-field", default=DEFAULT_PROBABILITY_FIELD)
    parser.add_argument("--date", default=None, help="Optional exact YYYY-MM-DD Asia/Kolkata session date.")
    parser.add_argument("--start-date", default=None, help="Optional inclusive YYYY-MM-DD session-date lower bound.")
    parser.add_argument("--end-date", default=None, help="Optional inclusive YYYY-MM-DD session-date upper bound.")
    parser.add_argument("--group-fields", default=",".join(DEFAULT_GROUP_FIELDS))
    parser.add_argument("--min-labeled-rows", type=int, default=DEFAULT_MIN_LABELED_ROWS)
    parser.add_argument("--min-session-count", type=int, default=DEFAULT_MIN_SESSION_COUNT)
    parser.add_argument("--min-slice-labels", type=int, default=DEFAULT_MIN_SLICE_LABELS)
    parser.add_argument("--alert-abs-gap", type=float, default=DEFAULT_ALERT_ABS_GAP)
    parser.add_argument("--severe-abs-gap", type=float, default=DEFAULT_SEVERE_ABS_GAP)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_probability_calibration_forward_monitor_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        probability_field=args.probability_field,
        report_date=args.date,
        start_date=args.start_date,
        end_date=args.end_date,
        group_fields=_csv_tuple(args.group_fields),
        min_labeled_rows=args.min_labeled_rows,
        min_session_count=args.min_session_count,
        min_slice_labels=args.min_slice_labels,
        alert_abs_gap=args.alert_abs_gap,
        severe_abs_gap=args.severe_abs_gap,
    )
    report = result.get("report", {}) or {}
    read = report.get("diagnostic_read", {}) or {}
    payload = {
        "report_type": report.get("report_type"),
        "monitor_status": report.get("monitor_status"),
        "eligible_labeled_rows": (report.get("coverage") or {}).get("eligible_labeled_rows"),
        "labeled_session_count": (report.get("coverage") or {}).get("labeled_session_count"),
        "mean_predicted_probability": read.get("mean_predicted_probability"),
        "actual_hit_rate": read.get("actual_hit_rate"),
        "calibration_gap": read.get("calibration_gap"),
        "brier_score": read.get("brier_score"),
        "bucket_ece": read.get("bucket_ece"),
        "underconfidence_slice_count": read.get("underconfidence_slice_count"),
        "overconfidence_slice_count": read.get("overconfidence_slice_count"),
        "flagged_slice_count": read.get("flagged_slice_count"),
        "bucket_pattern": report.get("bucket_pattern"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "latest_summary_csv_path": result.get("latest_summary_csv_path"),
        "latest_buckets_csv_path": result.get("latest_buckets_csv_path"),
        "latest_sessions_csv_path": result.get("latest_sessions_csv_path"),
        "latest_slices_csv_path": result.get("latest_slices_csv_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

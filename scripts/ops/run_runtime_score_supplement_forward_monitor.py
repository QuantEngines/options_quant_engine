#!/usr/bin/env python3
"""Generate research-only runtime-score supplement forward monitor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.runtime_research_composite_gap import DEFAULT_RUNTIME_LOW_THRESHOLD  # noqa: E402
from research.signal_evaluation.runtime_score_supplement_forward_monitor import (  # noqa: E402
    DEFAULT_CANDIDATES,
    DEFAULT_MIN_LABELED_ROWS,
    DEFAULT_MIN_SESSION_COUNT,
    DEFAULT_RUNTIME_SCORE_SUPPLEMENT_FORWARD_MONITOR_DIR,
    DEFAULT_WEAK_SLICE_MIN_LABELS,
    write_runtime_score_supplement_forward_monitor_report,
)


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUNTIME_SCORE_SUPPLEMENT_FORWARD_MONITOR_DIR)
    parser.add_argument("--date", default=None, help="Optional exact YYYY-MM-DD Asia/Kolkata session date.")
    parser.add_argument("--start-date", default=None, help="Optional inclusive YYYY-MM-DD session-date lower bound.")
    parser.add_argument("--end-date", default=None, help="Optional inclusive YYYY-MM-DD session-date upper bound.")
    parser.add_argument("--candidates", default=",".join(DEFAULT_CANDIDATES))
    parser.add_argument("--baseline-threshold", type=float, default=DEFAULT_RUNTIME_LOW_THRESHOLD)
    parser.add_argument("--min-labeled-rows", type=int, default=DEFAULT_MIN_LABELED_ROWS)
    parser.add_argument("--min-session-count", type=int, default=DEFAULT_MIN_SESSION_COUNT)
    parser.add_argument("--weak-slice-min-labels", type=int, default=DEFAULT_WEAK_SLICE_MIN_LABELS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_runtime_score_supplement_forward_monitor_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        report_date=args.date,
        start_date=args.start_date,
        end_date=args.end_date,
        candidate_names=_csv_tuple(args.candidates),
        baseline_threshold=args.baseline_threshold,
        min_labeled_rows=args.min_labeled_rows,
        min_session_count=args.min_session_count,
        weak_slice_min_labels=args.weak_slice_min_labels,
    )
    report = result["report"]
    read = report.get("diagnostic_read") or {}
    payload = {
        "report_type": report.get("report_type"),
        "monitor_status": report.get("monitor_status"),
        "eligible_rows": (report.get("coverage") or {}).get("eligible_rows"),
        "baseline_selected_rows": (report.get("coverage") or {}).get("baseline_selected_rows"),
        "candidate_count": read.get("candidate_count"),
        "top_candidate": read.get("top_candidate"),
        "top_candidate_status": read.get("top_candidate_status"),
        "top_candidate_promoted_rows": read.get("top_candidate_promoted_rows"),
        "top_candidate_promoted_label_count": read.get("top_candidate_promoted_label_count"),
        "top_candidate_labeled_session_count": read.get("top_candidate_labeled_session_count"),
        "top_candidate_hit_rate_60m": read.get("top_candidate_hit_rate_60m"),
        "top_candidate_avg_return_60m_bps": read.get("top_candidate_avg_return_60m_bps"),
        "top_candidate_mfe_mae_ratio_60m": read.get("top_candidate_mfe_mae_ratio_60m"),
        "top_candidate_weak_slice_count": read.get("top_candidate_weak_slice_count"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "latest_summary_csv_path": result.get("latest_summary_csv_path"),
        "latest_sessions_csv_path": result.get("latest_sessions_csv_path"),
        "latest_slices_csv_path": result.get("latest_slices_csv_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

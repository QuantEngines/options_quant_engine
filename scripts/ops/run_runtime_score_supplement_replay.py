#!/usr/bin/env python3
"""Generate research-only runtime-score supplement replay diagnostics."""

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
    DEFAULT_RUNTIME_LOW_THRESHOLD,
)
from research.signal_evaluation.runtime_score_supplement_replay import (  # noqa: E402
    DEFAULT_MIN_PROMOTED_LABELS,
    DEFAULT_RUNTIME_SCORE_SUPPLEMENT_REPLAY_REPORT_DIR,
    write_runtime_score_supplement_replay_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUNTIME_SCORE_SUPPLEMENT_REPLAY_REPORT_DIR)
    parser.add_argument("--date", default=None, help="Optional YYYY-MM-DD date filter in Asia/Kolkata session date.")
    parser.add_argument("--baseline-threshold", type=float, default=DEFAULT_RUNTIME_LOW_THRESHOLD)
    parser.add_argument("--research-high-threshold", type=float, default=DEFAULT_RESEARCH_HIGH_THRESHOLD)
    parser.add_argument("--min-promoted-labels", type=int, default=DEFAULT_MIN_PROMOTED_LABELS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_runtime_score_supplement_replay_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        report_date=args.date,
        baseline_threshold=args.baseline_threshold,
        research_high_threshold=args.research_high_threshold,
        min_promoted_labels=args.min_promoted_labels,
    )
    report = result["report"]
    read = report.get("diagnostic_read") or {}
    payload = {
        "report_type": report.get("report_type"),
        "comparable_rows": (report.get("coverage") or {}).get("comparable_rows"),
        "baseline_selected_rows": (report.get("coverage") or {}).get("baseline_selected_rows"),
        "candidate_count": read.get("candidate_count"),
        "supportive_candidate_count": read.get("supportive_candidate_count"),
        "top_candidate": read.get("top_candidate"),
        "top_candidate_assessment": read.get("top_candidate_assessment"),
        "top_candidate_promoted_rows": read.get("top_candidate_promoted_rows"),
        "top_candidate_recovered_blindspots": read.get("top_candidate_recovered_blindspots"),
        "top_candidate_promoted_hit_rate_60m": read.get("top_candidate_promoted_hit_rate_60m"),
        "top_candidate_promoted_avg_return_60m_bps": read.get("top_candidate_promoted_avg_return_60m_bps"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate exact-forward readiness for runtime-gate candidate monitoring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.signal_evaluation_scoring import SIGNAL_EVALUATION_SELECTION_POLICY  # noqa: E402
from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.runtime_gate_candidate_readiness import (  # noqa: E402
    DEFAULT_RUNTIME_GATE_CANDIDATE_READINESS_DIR,
    write_runtime_gate_candidate_readiness_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUNTIME_GATE_CANDIDATE_READINESS_DIR)
    parser.add_argument("--start-date", default=None, help="Optional YYYY-MM-DD lower bound in Asia/Kolkata.")
    parser.add_argument("--end-date", default=None, help="Optional YYYY-MM-DD upper bound in Asia/Kolkata.")
    parser.add_argument(
        "--component-capture-start",
        default=None,
        help="Optional ISO timestamp for the runtime_composite_components capture start.",
    )
    parser.add_argument(
        "--probability-floor",
        type=float,
        default=float(SIGNAL_EVALUATION_SELECTION_POLICY.get("move_probability_floor", 0.60)),
    )
    parser.add_argument("--min-preserve-matches", type=int, default=3)
    parser.add_argument("--min-exact-candidate-rows", type=int, default=100)
    parser.add_argument("--min-exact-guardrail-rows", type=int, default=100)
    parser.add_argument("--min-exact-sessions", type=int, default=3)
    parser.add_argument("--min-candidate-hit-rate-60m", type=float, default=0.58)
    parser.add_argument("--min-candidate-return-60m-bps", type=float, default=0.0)
    parser.add_argument("--min-candidate-mfe-mae-ratio-60m", type=float, default=1.20)
    parser.add_argument(
        "--include-missing-runtime-composite",
        action="store_true",
        help="Include older suppressed rows without an observed runtime_composite_score.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_runtime_gate_candidate_readiness_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        component_capture_start=args.component_capture_start,
        probability_floor=args.probability_floor,
        min_preserve_matches=args.min_preserve_matches,
        min_exact_candidate_rows=args.min_exact_candidate_rows,
        min_exact_guardrail_rows=args.min_exact_guardrail_rows,
        min_exact_sessions=args.min_exact_sessions,
        min_candidate_hit_rate_60m=args.min_candidate_hit_rate_60m,
        min_candidate_return_60m_bps=args.min_candidate_return_60m_bps,
        min_candidate_mfe_mae_ratio_60m=args.min_candidate_mfe_mae_ratio_60m,
        require_runtime_composite=not args.include_missing_runtime_composite,
    )
    report = result.get("report", {}) or {}
    payload = {
        "report_type": report.get("report_type"),
        "readiness_status": report.get("readiness_status"),
        "manual_review_ready": report.get("manual_review_ready"),
        "promotion_ready": report.get("promotion_ready"),
        "readiness_reasons": report.get("readiness_reasons"),
        "exact_forward_summary": report.get("exact_forward_summary"),
        "candidate_exact_metrics": report.get("candidate_exact_metrics"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

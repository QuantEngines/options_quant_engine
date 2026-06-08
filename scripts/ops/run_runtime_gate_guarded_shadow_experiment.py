#!/usr/bin/env python3
"""Generate research-only guarded runtime-gate shadow experiment diagnostics."""

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
from research.signal_evaluation.runtime_gate_guarded_shadow_experiment import (  # noqa: E402
    DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_DIR,
    write_runtime_gate_guarded_shadow_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_DIR)
    parser.add_argument("--start-date", default=None, help="Optional YYYY-MM-DD lower bound in Asia/Kolkata.")
    parser.add_argument("--end-date", default=None, help="Optional YYYY-MM-DD upper bound in Asia/Kolkata.")
    parser.add_argument(
        "--component-capture-start",
        default=None,
        help="Optional ISO timestamp for exact-forward component capture start.",
    )
    parser.add_argument(
        "--probability-floor",
        type=float,
        default=float(SIGNAL_EVALUATION_SELECTION_POLICY.get("move_probability_floor", 0.60)),
    )
    parser.add_argument("--min-preserve-matches", type=int, default=3)
    parser.add_argument("--preferred-preserve-matches", type=int, default=4)
    parser.add_argument("--min-preferred-exact-rows", type=int, default=50)
    parser.add_argument("--min-exact-sessions", type=int, default=3)
    parser.add_argument("--min-segment-rows", type=int, default=30)
    parser.add_argument(
        "--include-missing-runtime-composite",
        action="store_true",
        help="Include older suppressed rows without an observed runtime_composite_score.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_runtime_gate_guarded_shadow_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        component_capture_start=args.component_capture_start,
        probability_floor=args.probability_floor,
        min_preserve_matches=args.min_preserve_matches,
        preferred_preserve_matches=args.preferred_preserve_matches,
        min_preferred_exact_rows=args.min_preferred_exact_rows,
        min_exact_sessions=args.min_exact_sessions,
        min_segment_rows=args.min_segment_rows,
        require_runtime_composite=not args.include_missing_runtime_composite,
    )
    report = result.get("report", {}) or {}
    payload = {
        "report_type": report.get("report_type"),
        "shadow_read": report.get("shadow_read"),
        "research_only": report.get("research_only"),
        "live_promotion_ready": report.get("live_promotion_ready"),
        "runtime_config_changed": report.get("runtime_config_changed"),
        "execution_behavior_changed": report.get("execution_behavior_changed"),
        "suppressed_directional_rows": report.get("suppressed_directional_rows"),
        "exact_forward_summary": report.get("exact_forward_summary"),
        "exact_action_metrics": report.get("exact_action_metrics"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "latest_segments_path": result.get("latest_segments_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


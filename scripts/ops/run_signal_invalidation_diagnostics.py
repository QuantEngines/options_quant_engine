#!/usr/bin/env python3
"""Generate the research-only signal invalidation diagnostic report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.signal_invalidation_diagnostics import (  # noqa: E402
    DEFAULT_INVALIDATION_THRESHOLD,
    DEFAULT_MAX_EPISODE_GAP_MINUTES,
    DEFAULT_SCORE_DECAY_DROP_POINTS,
    DEFAULT_SIGNAL_INVALIDATION_REPORT_DIR,
    write_signal_invalidation_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_SIGNAL_INVALIDATION_REPORT_DIR)
    parser.add_argument("--threshold", type=int, default=DEFAULT_INVALIDATION_THRESHOLD)
    parser.add_argument("--max-episode-gap-minutes", type=int, default=DEFAULT_MAX_EPISODE_GAP_MINUTES)
    parser.add_argument("--score-decay-drop-points", type=float, default=DEFAULT_SCORE_DECAY_DROP_POINTS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_signal_invalidation_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        threshold=args.threshold,
        max_episode_gap_minutes=args.max_episode_gap_minutes,
        score_decay_drop_points=args.score_decay_drop_points,
    )
    report = result["report"]
    payload = {
        "report_type": report.get("report_type"),
        "episode_count": (report.get("coverage") or {}).get("episode_count"),
        "invalidated_episode_count": (report.get("coverage") or {}).get("invalidated_episode_count"),
        "invalidation_coverage_pct": (report.get("coverage") or {}).get("invalidation_coverage_pct"),
        "best_observed_invalidation_type": (report.get("diagnostic_read") or {}).get(
            "best_observed_invalidation_type"
        ),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

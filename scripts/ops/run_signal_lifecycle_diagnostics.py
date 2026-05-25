#!/usr/bin/env python3
"""Generate the research-only signal lifecycle diagnostic report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.signal_lifecycle_diagnostics import (  # noqa: E402
    DEFAULT_DECAY_DROP_POINTS,
    DEFAULT_LIFECYCLE_THRESHOLD,
    DEFAULT_MAX_EPISODE_GAP_MINUTES,
    DEFAULT_MATURE_SNAPSHOT_COUNT,
    DEFAULT_SIGNAL_LIFECYCLE_REPORT_DIR,
    write_signal_lifecycle_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_SIGNAL_LIFECYCLE_REPORT_DIR)
    parser.add_argument("--threshold", type=int, default=DEFAULT_LIFECYCLE_THRESHOLD)
    parser.add_argument("--max-episode-gap-minutes", type=int, default=DEFAULT_MAX_EPISODE_GAP_MINUTES)
    parser.add_argument("--mature-snapshot-count", type=int, default=DEFAULT_MATURE_SNAPSHOT_COUNT)
    parser.add_argument("--decay-drop-points", type=float, default=DEFAULT_DECAY_DROP_POINTS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_signal_lifecycle_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        threshold=args.threshold,
        max_episode_gap_minutes=args.max_episode_gap_minutes,
        mature_snapshot_count=args.mature_snapshot_count,
        decay_drop_points=args.decay_drop_points,
    )
    report = result["report"]
    payload = {
        "report_type": report.get("report_type"),
        "episode_count": (report.get("coverage") or {}).get("episode_count"),
        "usable_directional_rows": (report.get("coverage") or {}).get("usable_directional_rows"),
        "episodes_with_confirmation": (report.get("coverage") or {}).get("episodes_with_confirmation"),
        "episodes_with_candle_confirmation": (report.get("coverage") or {}).get("episodes_with_candle_confirmation"),
        "confirmation_improves_60m_return": (report.get("diagnostic_read") or {}).get(
            "confirmation_improves_60m_return"
        ),
        "maturity_improves_60m_return": (report.get("diagnostic_read") or {}).get(
            "maturity_improves_60m_return"
        ),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "manifest_path": result.get("manifest_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

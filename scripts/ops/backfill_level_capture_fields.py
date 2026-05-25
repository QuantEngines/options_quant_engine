#!/usr/bin/env python3
"""Backfill raw level fields from stored historical context JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402
from research.signal_evaluation.level_capture_backfill import backfill_level_capture_fields  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--write", action="store_true", help="Persist enriched level fields back to the dataset.")
    parser.add_argument("--limit", type=int, default=None, help="Only inspect this many rows.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = backfill_level_capture_fields(
        dataset_path=args.dataset,
        write=args.write,
        limit=args.limit,
    )
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

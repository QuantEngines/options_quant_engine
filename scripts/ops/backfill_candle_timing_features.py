#!/usr/bin/env python3
"""Backfill intraday candle timing features into a signal dataset."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.candle_timing_backfill import run_candle_timing_backfill  # noqa: E402
from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=str(CUMULATIVE_DATASET_PATH),
        help="Signal dataset path to enrich. Defaults to cumulative dataset.",
    )
    parser.add_argument("--write", action="store_true", help="Persist enriched candle timing fields.")
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for diagnostics/tests.")
    args = parser.parse_args()

    summary = run_candle_timing_backfill(
        dataset_path=args.dataset,
        write=args.write,
        limit=args.limit,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

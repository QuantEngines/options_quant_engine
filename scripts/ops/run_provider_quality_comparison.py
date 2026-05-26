#!/usr/bin/env python3
"""Run the offline ICICI-vs-Zerodha provider quality comparison report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.provider_quality_comparison import (  # noqa: E402
    DEFAULT_OPTION_SNAPSHOT_DIR,
    DEFAULT_SPOT_SNAPSHOT_DIR,
    build_provider_quality_comparison,
    write_provider_quality_comparison_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--date", dest="session_date", default=None, help="Session date in YYYY-MM-DD format.")
    parser.add_argument("--left-source", default="ICICI")
    parser.add_argument("--right-source", default="ZERODHA")
    parser.add_argument("--option-snapshot-dir", default=str(DEFAULT_OPTION_SNAPSHOT_DIR))
    parser.add_argument("--spot-snapshot-dir", default=str(DEFAULT_SPOT_SNAPSHOT_DIR))
    parser.add_argument("--max-pair-seconds", type=int, default=180)
    parser.add_argument("--spot-tolerance-seconds", type=int, default=600)
    parser.add_argument("--max-snapshots-per-source", type=int, default=None)
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_provider_quality_comparison(
        symbol=args.symbol,
        sources=(args.left_source, args.right_source),
        session_date=args.session_date,
        option_snapshot_dir=Path(args.option_snapshot_dir),
        spot_snapshot_dir=Path(args.spot_snapshot_dir),
        max_pair_seconds=args.max_pair_seconds,
        spot_tolerance_seconds=args.spot_tolerance_seconds,
        max_snapshots_per_source=args.max_snapshots_per_source,
    )
    paths = write_provider_quality_comparison_report(
        report,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    print(f"provider_quality_comparison: profiles={len(report['snapshot_profiles'])} pairs={len(report['paired_comparisons'])}")
    print(f"markdown: {paths['latest_markdown']}")
    print(f"json: {paths['latest_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

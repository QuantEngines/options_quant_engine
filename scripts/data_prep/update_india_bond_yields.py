#!/usr/bin/env python3
"""Upsert one EOD India G-Sec yield row into the local macro store."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.india_bond_yield_snapshot import (  # noqa: E402
    DEFAULT_BOND_YIELD_PATH,
    upsert_india_bond_yield_row,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Yield observation date in YYYY-MM-DD format.")
    parser.add_argument("--india-10y-yield", type=float, required=True, help="India 10Y G-Sec yield in percent.")
    parser.add_argument("--india-10y-change-bp", type=float, default=None)
    parser.add_argument("--india-2y-yield", type=float, default=None)
    parser.add_argument("--india-5y-yield", type=float, default=None)
    parser.add_argument("--india-30y-yield", type=float, default=None)
    parser.add_argument("--india-2y10y-spread-bp", type=float, default=None)
    parser.add_argument("--india-5y10y-spread-bp", type=float, default=None)
    parser.add_argument("--source", default="MANUAL_EOD_BOND_CONTEXT")
    parser.add_argument(
        "--source-timestamp",
        default=None,
        help="Publication/source timestamp. Defaults to current timestamp.",
    )
    parser.add_argument("--output", default=str(DEFAULT_BOND_YIELD_PATH))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_timestamp = args.source_timestamp or pd.Timestamp.now(tz="Asia/Kolkata").isoformat()
    row = {
        "date": args.date,
        "india_2y_yield": args.india_2y_yield,
        "india_5y_yield": args.india_5y_yield,
        "india_10y_yield": args.india_10y_yield,
        "india_30y_yield": args.india_30y_yield,
        "india_10y_change_bp": args.india_10y_change_bp,
        "india_2y10y_spread_bp": args.india_2y10y_spread_bp,
        "india_5y10y_spread_bp": args.india_5y10y_spread_bp,
        "source": args.source,
        "source_timestamp": source_timestamp,
    }
    output_path = upsert_india_bond_yield_row(row, path=args.output)
    print("india_bond_yield_update:")
    print(f"  date: {args.date}")
    print(f"  india_10y_yield: {args.india_10y_yield}")
    print(f"  india_10y_change_bp: {args.india_10y_change_bp}")
    print(f"  source: {args.source}")
    print(f"  source_timestamp: {source_timestamp}")
    print(f"  wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

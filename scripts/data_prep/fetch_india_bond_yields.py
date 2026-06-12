#!/usr/bin/env python3
"""Fetch CCIL EOD India G-Sec tenor yields into the local macro store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.india_bond_yield_fetcher import fetch_india_bond_yields  # noqa: E402
from data.india_bond_yield_snapshot import (  # noqa: E402
    DEFAULT_BOND_YIELD_PATH,
    upsert_india_bond_yield_row,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(DEFAULT_BOND_YIELD_PATH),
        help="Output CSV path consumed by data.india_bond_yield_snapshot.",
    )
    parser.add_argument(
        "--source-timestamp",
        default=None,
        help="Override publication/source timestamp. Defaults to current IST time.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print, but do not update the CSV.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = fetch_india_bond_yields(
        timeout=args.timeout,
        source_timestamp=args.source_timestamp,
        previous_path=args.output,
    )
    selected = result.get("selected_row")
    print("india_bond_yield_fetch:")
    for source, payload in result.get("results", {}).items():
        status = "OK" if payload.get("row") else "FAILED"
        issues = payload.get("issues") or []
        warnings = payload.get("warnings") or []
        detail = f" issues={issues}" if issues else ""
        if warnings:
            detail += f" warnings={warnings}"
        print(f"  {source}: {status}{detail}")

    if not selected:
        print("  selected: NONE")
        return 1

    print(f"  selected: {result.get('selected_source')}")
    print(f"  date: {selected.get('date')}")
    print(f"  india_2y_yield: {selected.get('india_2y_yield')}")
    print(f"  india_5y_yield: {selected.get('india_5y_yield')}")
    print(f"  india_10y_yield: {selected.get('india_10y_yield')}")
    print(f"  india_30y_yield: {selected.get('india_30y_yield')}")
    print(f"  india_10y_change_bp: {selected.get('india_10y_change_bp')}")
    print(f"  india_2y10y_spread_bp: {selected.get('india_2y10y_spread_bp')}")
    print(f"  india_5y10y_spread_bp: {selected.get('india_5y10y_spread_bp')}")
    print(f"  source_timestamp: {selected.get('source_timestamp')}")

    if args.dry_run:
        print("  dry_run: true")
        print(json.dumps(selected, indent=2, default=str))
        return 0

    output_path = upsert_india_bond_yield_row(selected, path=args.output)
    print(f"  wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

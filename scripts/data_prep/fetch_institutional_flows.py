#!/usr/bin/env python3
"""Fetch official NSE/BSE EOD FII/DII cash flows into the local research store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.institutional_flow_fetcher import (  # noqa: E402
    DEFAULT_FLOW_PATH,
    fetch_institutional_flows,
    upsert_institutional_flow_row,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        default="NSE,BSE",
        help="Comma-separated official sources to try, in preference order. Default: NSE,BSE.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_FLOW_PATH),
        help="Output CSV path consumed by data.institutional_flow_snapshot.",
    )
    parser.add_argument(
        "--source-timestamp",
        default=None,
        help="Override publication/source timestamp. Defaults to current IST time.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--agreement-tolerance-cr", type=float, default=2.0)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print, but do not update the CSV.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = [item.strip().upper() for item in args.sources.split(",") if item.strip()]
    result = fetch_institutional_flows(
        sources=sources,
        timeout=args.timeout,
        source_timestamp=args.source_timestamp,
        agreement_tolerance_cr=args.agreement_tolerance_cr,
    )
    selected = result.get("selected_row")
    print("institutional_flow_fetch:")
    print(f"  requested_sources: {','.join(sources) or 'NSE,BSE'}")
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
    print(f"  fii_cash_net: {selected.get('fii_cash_net')} {selected.get('unit')}")
    print(f"  dii_cash_net: {selected.get('dii_cash_net')} {selected.get('unit')}")
    print(f"  crosscheck_status: {selected.get('crosscheck_status')}")
    print(f"  source_timestamp: {selected.get('source_timestamp')}")

    if args.dry_run:
        print("  dry_run: true")
        print(json.dumps(selected, indent=2, default=str))
        return 0

    output_path = upsert_institutional_flow_row(selected, path=args.output)
    print(f"  wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

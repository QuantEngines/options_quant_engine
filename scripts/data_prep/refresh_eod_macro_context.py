#!/usr/bin/env python3
"""Refresh EOD macro context stores used by the signal engine.

This utility updates lagged research/display context only. It does not run from
the intraday signal loop and does not change live signal logic.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.india_bond_yield_fetcher import fetch_india_bond_yields  # noqa: E402
from data.india_bond_yield_snapshot import (  # noqa: E402
    DEFAULT_BOND_YIELD_PATH,
    upsert_india_bond_yield_row,
)
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
        help="Comma-separated FII/DII sources to try. Default: NSE,BSE.",
    )
    parser.add_argument("--flow-output", default=str(DEFAULT_FLOW_PATH))
    parser.add_argument("--bond-output", default=str(DEFAULT_BOND_YIELD_PATH))
    parser.add_argument(
        "--source-timestamp",
        default=None,
        help="Override publication/source timestamp for both updates. Defaults to current IST time.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--agreement-tolerance-cr", type=float, default=2.0)
    parser.add_argument("--skip-flows", action="store_true", help="Skip FII/DII refresh.")
    parser.add_argument("--skip-bonds", action="store_true", help="Skip India bond-yield refresh.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print, but do not update local CSVs.")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Exit 0 when at least one attempted macro refresh succeeds.",
    )
    return parser.parse_args()


def _source_list(raw_sources: str | None) -> list[str]:
    return [item.strip().upper() for item in str(raw_sources or "").split(",") if item.strip()] or ["NSE", "BSE"]


def _provider_status(result: dict[str, Any]) -> dict[str, Any]:
    status = {}
    for source, payload in (result.get("results") or {}).items():
        status[source] = {
            "ok": bool(payload.get("row")) and not payload.get("issues"),
            "warnings": list(payload.get("warnings") or []),
            "issues": list(payload.get("issues") or []),
            "raw_url": payload.get("raw_url"),
        }
    return status


def _flow_step_summary(result: dict[str, Any], *, wrote: Path | None) -> dict[str, Any]:
    row = result.get("selected_row") or {}
    return {
        "status": "OK" if row else "FAILED",
        "selected_source": result.get("selected_source"),
        "date": row.get("date"),
        "fii_cash_net": row.get("fii_cash_net"),
        "dii_cash_net": row.get("dii_cash_net"),
        "crosscheck_status": row.get("crosscheck_status"),
        "source_timestamp": row.get("source_timestamp"),
        "wrote": str(wrote) if wrote else None,
        "providers": _provider_status(result),
    }


def _bond_step_summary(result: dict[str, Any], *, wrote: Path | None) -> dict[str, Any]:
    row = result.get("selected_row") or {}
    return {
        "status": "OK" if row else "FAILED",
        "selected_source": result.get("selected_source"),
        "date": row.get("date"),
        "india_2y_yield": row.get("india_2y_yield"),
        "india_5y_yield": row.get("india_5y_yield"),
        "india_10y_yield": row.get("india_10y_yield"),
        "india_30y_yield": row.get("india_30y_yield"),
        "india_10y_change_bp": row.get("india_10y_change_bp"),
        "india_10y_change_basis": row.get("india_10y_change_basis"),
        "india_2y10y_spread_bp": row.get("india_2y10y_spread_bp"),
        "india_5y10y_spread_bp": row.get("india_5y10y_spread_bp"),
        "source_timestamp": row.get("source_timestamp"),
        "wrote": str(wrote) if wrote else None,
        "providers": _provider_status(result),
    }


def refresh_eod_macro_context(
    *,
    sources: list[str] | None = None,
    flow_output: str | Path = DEFAULT_FLOW_PATH,
    bond_output: str | Path = DEFAULT_BOND_YIELD_PATH,
    source_timestamp=None,
    timeout: float = 15.0,
    agreement_tolerance_cr: float = 2.0,
    skip_flows: bool = False,
    skip_bonds: bool = False,
    dry_run: bool = False,
    fetch_flows_func: Callable[..., dict[str, Any]] = fetch_institutional_flows,
    fetch_bonds_func: Callable[..., dict[str, Any]] = fetch_india_bond_yields,
    upsert_flow_func: Callable[..., Path] = upsert_institutional_flow_row,
    upsert_bond_func: Callable[..., Path] = upsert_india_bond_yield_row,
) -> dict[str, Any]:
    """Run both EOD macro refreshes and return a compact status payload."""
    if skip_flows and skip_bonds:
        return {
            "status": "SKIPPED",
            "dry_run": dry_run,
            "steps": {},
            "issues": ["all_macro_refresh_steps_skipped"],
        }

    steps: dict[str, Any] = {}
    successes: list[str] = []
    failures: list[str] = []

    if not skip_flows:
        flow_result = fetch_flows_func(
            sources=sources or ["NSE", "BSE"],
            timeout=timeout,
            source_timestamp=source_timestamp,
            agreement_tolerance_cr=agreement_tolerance_cr,
        )
        flow_wrote = None
        selected_flow = flow_result.get("selected_row")
        if selected_flow:
            successes.append("institutional_flows")
            if not dry_run:
                flow_wrote = upsert_flow_func(selected_flow, path=flow_output)
        else:
            failures.append("institutional_flows")
        steps["institutional_flows"] = _flow_step_summary(flow_result, wrote=flow_wrote)

    if not skip_bonds:
        bond_result = fetch_bonds_func(
            timeout=timeout,
            source_timestamp=source_timestamp,
            previous_path=bond_output,
        )
        bond_wrote = None
        selected_bond = bond_result.get("selected_row")
        if selected_bond:
            successes.append("india_bond_yields")
            if not dry_run:
                bond_wrote = upsert_bond_func(selected_bond, path=bond_output)
        else:
            failures.append("india_bond_yields")
        steps["india_bond_yields"] = _bond_step_summary(bond_result, wrote=bond_wrote)

    if failures and successes:
        status = "PARTIAL"
    elif failures:
        status = "FAILED"
    else:
        status = "OK"

    return {
        "status": status,
        "dry_run": dry_run,
        "steps": steps,
        "successes": successes,
        "failures": failures,
    }


def _print_step(name: str, step: dict[str, Any]) -> None:
    print(f"  {name}: {step.get('status')}")
    for key, value in step.items():
        if key in {"status", "providers"} or value is None:
            continue
        print(f"    {key}: {value}")
    for provider, provider_status in (step.get("providers") or {}).items():
        detail = ""
        if provider_status.get("issues"):
            detail += f" issues={provider_status.get('issues')}"
        if provider_status.get("warnings"):
            detail += f" warnings={provider_status.get('warnings')}"
        print(f"    provider {provider}: {'OK' if provider_status.get('ok') else 'FAILED'}{detail}")


def main() -> int:
    args = parse_args()
    result = refresh_eod_macro_context(
        sources=_source_list(args.sources),
        flow_output=args.flow_output,
        bond_output=args.bond_output,
        source_timestamp=args.source_timestamp,
        timeout=args.timeout,
        agreement_tolerance_cr=args.agreement_tolerance_cr,
        skip_flows=args.skip_flows,
        skip_bonds=args.skip_bonds,
        dry_run=args.dry_run,
    )

    print("eod_macro_context_refresh:")
    print(f"  status: {result.get('status')}")
    print(f"  dry_run: {str(bool(result.get('dry_run'))).lower()}")
    for name, step in (result.get("steps") or {}).items():
        _print_step(name, step)
    if result.get("issues"):
        print(f"  issues: {result.get('issues')}")
    print("  json:")
    print(json.dumps(result, indent=2, default=str))

    status = result.get("status")
    if status == "OK":
        return 0
    if status == "PARTIAL" and args.allow_partial:
        return 0
    if status == "SKIPPED":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

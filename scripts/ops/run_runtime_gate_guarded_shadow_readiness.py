#!/usr/bin/env python3
"""Generate research-only readiness gate for guarded runtime-gate shadow experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.runtime_gate_guarded_shadow_readiness import (  # noqa: E402
    DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_READINESS_DIR,
    DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_REPORT_PATH,
    write_runtime_gate_guarded_shadow_readiness_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shadow-report", type=Path, default=DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_REPORT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_READINESS_DIR)
    parser.add_argument("--min-exact-sessions", type=int, default=5)
    parser.add_argument("--min-preferred-exact-rows", type=int, default=300)
    parser.add_argument("--max-tail-damage-bps", type=float, default=0.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_runtime_gate_guarded_shadow_readiness_report(
        shadow_report_path=args.shadow_report,
        output_dir=args.output_dir,
        min_exact_sessions=args.min_exact_sessions,
        min_preferred_exact_rows=args.min_preferred_exact_rows,
        max_tail_damage_bps=args.max_tail_damage_bps,
    )
    report = result.get("report", {}) or {}
    payload = {
        "report_type": report.get("report_type"),
        "readiness_status": report.get("readiness_status"),
        "promotion_status": report.get("promotion_status"),
        "promotion_ready": report.get("promotion_ready"),
        "runtime_config_changed": report.get("runtime_config_changed"),
        "parameter_pack_file_changed": report.get("parameter_pack_file_changed"),
        "execution_behavior_changed": report.get("execution_behavior_changed"),
        "shadow_read": report.get("shadow_read"),
        "exact_forward_summary": report.get("exact_forward_summary"),
        "deltas": report.get("deltas"),
        "readiness_reasons": report.get("readiness_reasons"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

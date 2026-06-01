#!/usr/bin/env python3
"""Run the EOD guarded segmented-probability refresh loop.

This research-only helper exists because the ordinary soak command is deliberately
not allowed to mutate candidate bundles.  It first runs the normal soak to
refresh outcomes and diagnose whether the guarded bundle is stale.  When the
bundle is stale, it rebuilds the research artifacts and runs a final soak against
the refreshed bundle.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts" / "ops"

SOAK_STALE_STATUSES = {
    "SOAK_CANDIDATE_STALENESS_BLOCKED",
    "SOAK_GUARDED_BUNDLE_STALENESS_BLOCKED",
}

REFRESH_COMMANDS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("segmented_probability_calibration_experiment", ("run_segmented_probability_calibration_experiment.py",), True),
    ("segmented_probability_ev_shadow_evaluation", ("run_segmented_probability_ev_shadow_evaluation.py",), True),
    ("segmented_probability_ev_rejection_attribution", ("run_segmented_probability_ev_rejection_attribution.py",), False),
    ("segmented_probability_guarded_ev_experiment", ("run_segmented_probability_guarded_ev_experiment.py",), True),
    (
        "segmented_probability_guarded_candidate_bundle",
        ("run_segmented_probability_guarded_candidate_bundle.py", "--allow-watch"),
        False,
    ),
    ("segmented_probability_guarded_shadow_validation", ("run_segmented_probability_guarded_shadow_validation.py",), True),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only EOD helper: soak, refresh stale segmented-probability guarded artifacts, "
            "then run a final soak. It never changes runtime config, parameter packs, data sources, "
            "or execution behavior."
        )
    )
    parser.add_argument("--dataset", type=Path, default=None, help="Optional signal dataset CSV path.")
    parser.add_argument(
        "--outcome-refresh-source",
        choices=("local_spot_history", "default_provider", "skip"),
        default="local_spot_history",
        help="Outcome refresh source for the initial soak.",
    )
    parser.add_argument(
        "--final-outcome-refresh-source",
        choices=("local_spot_history", "default_provider", "skip"),
        default="skip",
        help="Outcome refresh source for the final soak after artifact refresh.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Refresh guarded research artifacts even if the initial soak is not stale-blocked.",
    )
    parser.add_argument(
        "--skip-initial-soak",
        action="store_true",
        help="Skip the initial soak and refresh artifacts immediately.",
    )
    parser.add_argument(
        "--allow-holdout-replay-guarded-validation",
        action="store_true",
        help="Pass the research-only holdout replay allowance to soak commands.",
    )
    parser.add_argument(
        "--fail-on-refresh-error",
        action="store_true",
        help="Exit non-zero when any refresh step fails. By default failures are reported in JSON.",
    )
    return parser


def _json_loads(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"raw_stdout": text}
    return payload if isinstance(payload, dict) else {"payload": payload}


def _command(script_name: str, args: list[str], *, dataset: Path | None) -> list[str]:
    command = [sys.executable, str(SCRIPTS_DIR / script_name), *args]
    if dataset is not None:
        command.extend(["--dataset", str(dataset)])
    return command


def _run_step(name: str, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "name": name,
        "returncode": completed.returncode,
        "command": command,
        "stdout": _json_loads(completed.stdout),
        "stderr": completed.stderr.strip() or None,
    }


def _soak_args(outcome_refresh_source: str, *, allow_holdout_replay: bool) -> list[str]:
    args = ["--outcome-refresh-source", outcome_refresh_source]
    if allow_holdout_replay:
        args.append("--allow-holdout-replay-guarded-validation")
    return args


def _needs_refresh(initial_soak: dict[str, Any], *, force_refresh: bool, skipped: bool) -> bool:
    if force_refresh or skipped:
        return True
    payload = initial_soak.get("stdout") or {}
    status = payload.get("soak_status")
    guarded_staleness = payload.get("guarded_staleness_status")
    staleness = payload.get("staleness_status")
    return (
        status in SOAK_STALE_STATUSES
        or guarded_staleness == "GUARDED_BLOCKED"
        or staleness in {"STALE_WATCH", "EXPIRED", "SUPERSEDED"}
    )


def main() -> int:
    args = build_parser().parse_args()
    steps: list[dict[str, Any]] = []

    initial_soak: dict[str, Any] | None = None
    if not args.skip_initial_soak:
        initial_soak = _run_step(
            "initial_shadow_soak",
            _command(
                "run_segmented_probability_shadow_soak.py",
                _soak_args(
                    args.outcome_refresh_source,
                    allow_holdout_replay=args.allow_holdout_replay_guarded_validation,
                ),
                dataset=args.dataset,
            ),
        )
        steps.append(initial_soak)

    refresh_needed = _needs_refresh(
        initial_soak or {},
        force_refresh=args.force_refresh,
        skipped=args.skip_initial_soak,
    )
    refresh_steps: list[dict[str, Any]] = []
    refresh_failed = False

    if refresh_needed:
        for name, command_parts, accepts_dataset in REFRESH_COMMANDS:
            command = _command(
                command_parts[0],
                list(command_parts[1:]),
                dataset=args.dataset if accepts_dataset else None,
            )
            step = _run_step(name, command)
            refresh_steps.append(step)
            steps.append(step)
            if step["returncode"] != 0:
                refresh_failed = True
                break

    final_soak: dict[str, Any] | None = None
    if refresh_needed and not refresh_failed:
        final_soak = _run_step(
            "final_shadow_soak",
            _command(
                "run_segmented_probability_shadow_soak.py",
                _soak_args(
                    args.final_outcome_refresh_source,
                    allow_holdout_replay=args.allow_holdout_replay_guarded_validation,
                ),
                dataset=args.dataset,
            ),
        )
        steps.append(final_soak)

    payload = {
        "workflow": "daily_guarded_refresh",
        "runtime_config_changed": False,
        "parameter_pack_file_changed": False,
        "execution_behavior_changed": False,
        "initial_soak_status": (initial_soak or {}).get("stdout", {}).get("soak_status"),
        "refresh_needed": refresh_needed,
        "refresh_failed": refresh_failed,
        "final_soak_status": (final_soak or {}).get("stdout", {}).get("soak_status"),
        "final_readiness_status": (final_soak or {}).get("stdout", {}).get("readiness_status"),
        "final_guarded_staleness_status": (final_soak or {}).get("stdout", {}).get("guarded_staleness_status"),
        "steps": steps,
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))

    failed_returncodes = [step["returncode"] for step in steps if step["returncode"] != 0]
    if failed_returncodes and args.fail_on_refresh_error:
        return int(failed_returncodes[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

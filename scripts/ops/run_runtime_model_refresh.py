#!/usr/bin/env python3
"""
Runtime Model Refresh Orchestrator
=================================

Purpose:
    Run runtime decay and score-calibration retraining in one command, then
    evaluate simple promotion gates and persist an auditable decision artifact.

Outputs:
    - documentation/improvement_reports/runtime_model_refresh_<timestamp>.json
    - documentation/improvement_reports/runtime_model_refresh_history.csv

This script never deletes prior artifacts. It records every run.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
IMPROVEMENT_REPORTS_DIR = ROOT / "documentation" / "improvement_reports"
DECAY_SCRIPT = ROOT / "scripts" / "retrain_time_decay_from_signal_cumul.py"
CALIBRATOR_SCRIPT = ROOT / "scripts" / "train_runtime_score_calibrator.py"


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class RefreshInputs:
    decay_report_json: Path
    calibrator_model_path: Path
    calibrator_report_json: Path


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _run_python_script(script_path: Path) -> CommandResult:
    cmd = [sys.executable, str(script_path)]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    return CommandResult(
        command=cmd,
        returncode=int(proc.returncode),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def _extract_saved_path(stdout_text: str, prefix: str) -> Path | None:
    for line in stdout_text.splitlines():
        if line.strip().startswith(prefix):
            candidate = line.split(prefix, 1)[1].strip()
            if candidate:
                path = Path(candidate)
                if not path.is_absolute():
                    path = ROOT / path
                return path
    return None


def _latest_matching(pattern: str) -> Path:
    matches = sorted(IMPROVEMENT_REPORTS_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No report found matching pattern: {pattern}")
    return matches[-1]


def _resolve_refresh_inputs(decay_result: CommandResult, calibrator_result: CommandResult) -> RefreshInputs:
    decay_report_json = _extract_saved_path(decay_result.stdout, "Saved JSON:")
    calibrator_model_path = _extract_saved_path(calibrator_result.stdout, "Saved calibrator:")
    calibrator_report_json = _extract_saved_path(calibrator_result.stdout, "Saved report:")

    if decay_report_json is None or not decay_report_json.exists():
        decay_report_json = _latest_matching("time_decay_retrain_signal_cumul_*.json")

    if calibrator_model_path is None:
        calibrator_model_path = ROOT / "models_store" / "runtime_score_calibrator.json"
    if not calibrator_model_path.is_absolute():
        calibrator_model_path = ROOT / calibrator_model_path

    if calibrator_report_json is None or not calibrator_report_json.exists():
        calibrator_report_json = _latest_matching("runtime_score_calibrator_train_*.json")

    return RefreshInputs(
        decay_report_json=decay_report_json,
        calibrator_model_path=calibrator_model_path,
        calibrator_report_json=calibrator_report_json,
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _evaluate_gates(
    *,
    decay_payload: dict[str, Any],
    calibrator_payload: dict[str, Any],
    calibrator_model_path: Path,
    max_decay_fit_mse: float,
    max_abs_calibration_gap: float,
) -> dict[str, Any]:
    regime_fits = list(decay_payload.get("regime_fits") or [])
    fit_mses = [float(row.get("fit_mse", 1e9) or 1e9) for row in regime_fits]
    max_fit_mse_seen = max(fit_mses) if fit_mses else 1e9

    calibration_gap = float(calibrator_payload.get("overall_calibration_gap", 1e9) or 1e9)
    abs_calibration_gap = abs(calibration_gap)

    checks = {
        "decay_report_has_regimes": bool(len(regime_fits) >= 3),
        "calibrator_model_exists": bool(calibrator_model_path.exists()),
        "decay_fit_mse_ok": bool(max_fit_mse_seen <= float(max_decay_fit_mse)),
        "calibration_gap_ok": bool(abs_calibration_gap <= float(max_abs_calibration_gap)),
    }

    all_passed = bool(all(checks.values()))
    reason = "refresh_gate_passed" if all_passed else "refresh_gate_blocked"

    return {
        "gate_passed": all_passed,
        "reason": reason,
        "thresholds": {
            "max_decay_fit_mse": float(max_decay_fit_mse),
            "max_abs_calibration_gap": float(max_abs_calibration_gap),
        },
        "metrics": {
            "max_decay_fit_mse_seen": round(max_fit_mse_seen, 8),
            "calibration_gap": round(calibration_gap, 8),
            "abs_calibration_gap": round(abs_calibration_gap, 8),
        },
        "checks": checks,
    }


def _write_json_report(payload: dict[str, Any]) -> Path:
    IMPROVEMENT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = IMPROVEMENT_REPORTS_DIR / f"runtime_model_refresh_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _append_history_row(row: dict[str, Any]) -> Path:
    IMPROVEMENT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    history_path = IMPROVEMENT_REPORTS_DIR / "runtime_model_refresh_history.csv"
    fieldnames = [
        "generated_at",
        "gate_passed",
        "reason",
        "max_decay_fit_mse_seen",
        "calibration_gap",
        "abs_calibration_gap",
        "decay_report_json",
        "calibrator_report_json",
        "calibrator_model_path",
        "refresh_report_json",
    ]

    write_header = not history_path.exists()
    with history_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    return history_path


def _send_failure_webhook(*, webhook_url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(float(timeout_s), 1.0)) as response:
            status = int(getattr(response, "status", 200))
        return {"attempted": True, "sent": True, "status_code": status, "error": None}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        return {"attempted": True, "sent": False, "status_code": None, "error": str(exc)}


def _run_failure_command(*, command: str, context: dict[str, Any]) -> dict[str, Any]:
    env = os.environ.copy()
    env.update({
        "RUNTIME_REFRESH_REASON": str(context.get("reason", "")),
        "RUNTIME_REFRESH_REPORT": str(context.get("refresh_report_json", "")),
        "RUNTIME_REFRESH_GATE_PASSED": str(int(bool(context.get("gate_passed", False)))),
    })
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        shell=True,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return {
        "attempted": True,
        "returncode": int(proc.returncode),
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def _maybe_emit_failure_alert(*, args: argparse.Namespace, context: dict[str, Any]) -> dict[str, Any]:
    alerts: dict[str, Any] = {
        "webhook": {"attempted": False, "sent": False, "status_code": None, "error": None},
        "notify_command": {"attempted": False, "returncode": None, "stdout": "", "stderr": ""},
    }
    if bool(context.get("gate_passed", False)):
        return alerts

    webhook_url = str(
        args.failure_webhook_url
        or os.getenv("RUNTIME_MODEL_REFRESH_FAILURE_WEBHOOK_URL")
        or ""
    ).strip()
    if webhook_url:
        alerts["webhook"] = _send_failure_webhook(
            webhook_url=webhook_url,
            payload=context,
            timeout_s=args.failure_webhook_timeout_s,
        )

    notify_command = str(args.failure_notify_command or "").strip()
    if notify_command:
        alerts["notify_command"] = _run_failure_command(
            command=notify_command,
            context=context,
        )

    return alerts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run runtime model refresh (decay + calibrator) and evaluate promotion gate."
    )
    parser.add_argument(
        "--max-decay-fit-mse",
        type=float,
        default=0.45,
        help="Maximum acceptable fit MSE across regime half-life fits.",
    )
    parser.add_argument(
        "--max-abs-calibration-gap",
        type=float,
        default=0.10,
        help="Maximum acceptable absolute calibration gap.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 2 when gate fails.",
    )
    parser.add_argument(
        "--failure-webhook-url",
        default="",
        help=(
            "Optional webhook URL for failure alerts. "
            "Can also be set with RUNTIME_MODEL_REFRESH_FAILURE_WEBHOOK_URL."
        ),
    )
    parser.add_argument(
        "--failure-webhook-timeout-s",
        type=float,
        default=8.0,
        help="HTTP timeout in seconds for failure webhook delivery.",
    )
    parser.add_argument(
        "--failure-notify-command",
        default="",
        help=(
            "Optional shell command executed on gate failure. "
            "Environment includes RUNTIME_REFRESH_REASON and RUNTIME_REFRESH_REPORT."
        ),
    )
    return parser


def _run_main(args: argparse.Namespace) -> int:

    if not DECAY_SCRIPT.exists():
        raise FileNotFoundError(f"Missing decay retrain script: {DECAY_SCRIPT}")
    if not CALIBRATOR_SCRIPT.exists():
        raise FileNotFoundError(f"Missing calibrator retrain script: {CALIBRATOR_SCRIPT}")

    decay_result = _run_python_script(DECAY_SCRIPT)
    calibrator_result = _run_python_script(CALIBRATOR_SCRIPT)

    if decay_result.returncode != 0:
        raise RuntimeError(
            "Decay retraining script failed\n"
            f"command={' '.join(decay_result.command)}\n"
            f"stdout:\n{decay_result.stdout}\n"
            f"stderr:\n{decay_result.stderr}"
        )

    if calibrator_result.returncode != 0:
        raise RuntimeError(
            "Calibrator training script failed\n"
            f"command={' '.join(calibrator_result.command)}\n"
            f"stdout:\n{calibrator_result.stdout}\n"
            f"stderr:\n{calibrator_result.stderr}"
        )

    resolved = _resolve_refresh_inputs(decay_result, calibrator_result)
    decay_payload = _load_json(resolved.decay_report_json)
    calibrator_payload = _load_json(resolved.calibrator_report_json)

    gate = _evaluate_gates(
        decay_payload=decay_payload,
        calibrator_payload=calibrator_payload,
        calibrator_model_path=resolved.calibrator_model_path,
        max_decay_fit_mse=args.max_decay_fit_mse,
        max_abs_calibration_gap=args.max_abs_calibration_gap,
    )

    report_payload = {
        "generated_at": _utc_now(),
        "root": str(ROOT),
        "runs": {
            "decay": {
                "command": decay_result.command,
                "returncode": decay_result.returncode,
                "report_json": str(resolved.decay_report_json),
            },
            "calibrator": {
                "command": calibrator_result.command,
                "returncode": calibrator_result.returncode,
                "model_path": str(resolved.calibrator_model_path),
                "report_json": str(resolved.calibrator_report_json),
            },
        },
        "gate": gate,
    }

    refresh_report_json = _write_json_report(report_payload)

    history_row = {
        "generated_at": report_payload["generated_at"],
        "gate_passed": int(bool(gate["gate_passed"])),
        "reason": gate["reason"],
        "max_decay_fit_mse_seen": gate["metrics"]["max_decay_fit_mse_seen"],
        "calibration_gap": gate["metrics"]["calibration_gap"],
        "abs_calibration_gap": gate["metrics"]["abs_calibration_gap"],
        "decay_report_json": str(resolved.decay_report_json),
        "calibrator_report_json": str(resolved.calibrator_report_json),
        "calibrator_model_path": str(resolved.calibrator_model_path),
        "refresh_report_json": str(refresh_report_json),
    }
    history_csv = _append_history_row(history_row)

    output = {
        "refresh_report_json": str(refresh_report_json),
        "history_csv": str(history_csv),
        "gate_passed": bool(gate["gate_passed"]),
        "reason": gate["reason"],
        "metrics": gate["metrics"],
    }

    alert_context = {
        "generated_at": report_payload["generated_at"],
        "gate_passed": bool(gate["gate_passed"]),
        "reason": gate["reason"],
        "metrics": gate["metrics"],
        "refresh_report_json": str(refresh_report_json),
        "history_csv": str(history_csv),
    }
    alerts = _maybe_emit_failure_alert(args=args, context=alert_context)
    output["alerts"] = alerts

    report_payload["alerts"] = alerts
    refresh_report_json.write_text(json.dumps(report_payload, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(output, indent=2, sort_keys=True))

    if args.strict and not gate["gate_passed"]:
        return 2
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return _run_main(args)
    except Exception as exc:
        fail_context = {
            "generated_at": _utc_now(),
            "gate_passed": False,
            "reason": "refresh_runtime_exception",
            "metrics": {},
            "error": str(exc),
            "refresh_report_json": "",
            "history_csv": "",
        }
        alerts = _maybe_emit_failure_alert(args=args, context=fail_context)
        print(
            json.dumps(
                {
                    "gate_passed": False,
                    "reason": "refresh_runtime_exception",
                    "error": str(exc),
                    "alerts": alerts,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

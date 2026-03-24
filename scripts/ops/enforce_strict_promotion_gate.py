#!/usr/bin/env python3
"""
Strict Promotion Gate
=====================

Purpose:
    Enforce a strict approval gate for candidate packs. Approval is granted only
    when BOTH conditions are true:
    1) objective_score_delta > 0
    2) replay robustness_edge_flag is True

Behavior:
    - Writes a decision artifact under research/parameter_tuning/promotion_gate_decisions/
    - Optionally records manual approval/rejection in promotion state
    - Exits non-zero on gate failure to block automation pipelines
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tuning.promotion import PROMOTION_STATE_PATH, record_manual_approval


DECISIONS_ROOT = ROOT / "research" / "parameter_tuning" / "promotion_gate_decisions"


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _slug(text: str) -> str:
    return str(text).strip().replace("/", "_").replace(" ", "_")


def _load_recommendation_objective_delta(report_json_path: Path) -> float:
    report = json.loads(report_json_path.read_text(encoding="utf-8"))
    expected = dict(report.get("expected_improvement_summary") or {})
    return float(expected.get("objective_score_delta", 0.0) or 0.0)


def _load_replay_robustness_edge_flag(replay_summary_csv_path: Path, candidate_pack_name: str) -> bool:
    frame = pd.read_csv(replay_summary_csv_path)
    if frame.empty:
        return False
    selected = frame.loc[frame["candidate_pack"].astype(str) == str(candidate_pack_name)]
    if selected.empty:
        return False
    value = selected.iloc[0].get("robustness_edge_flag", False)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def evaluate_gate(
    *,
    candidate_pack_name: str,
    report_json_path: Path,
    replay_summary_csv_path: Path,
) -> dict[str, Any]:
    objective_delta = _load_recommendation_objective_delta(report_json_path)
    robustness_edge_flag = _load_replay_robustness_edge_flag(replay_summary_csv_path, candidate_pack_name)

    objective_positive = bool(objective_delta > 0.0)
    replay_edge_positive = bool(robustness_edge_flag)
    gate_passed = bool(objective_positive and replay_edge_positive)

    return {
        "generated_at": _utc_now(),
        "candidate_pack_name": candidate_pack_name,
        "report_json_path": str(report_json_path),
        "replay_summary_csv_path": str(replay_summary_csv_path),
        "objective_score_delta": round(objective_delta, 6),
        "objective_positive": objective_positive,
        "replay_robustness_edge_flag": replay_edge_positive,
        "gate_passed": gate_passed,
        "gate_rule": "objective_score_delta > 0 AND replay_robustness_edge_flag == true",
        "reason": (
            "strict_gate_passed"
            if gate_passed
            else "strict_gate_blocked: requires positive objective delta and positive replay robustness edge"
        ),
    }


def _write_decision_artifact(decision: dict[str, Any]) -> Path:
    DECISIONS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = DECISIONS_ROOT / f"strict_gate_{stamp}_{_slug(decision.get('candidate_pack_name', 'candidate'))}.json"
    path.write_text(json.dumps(decision, indent=2, sort_keys=True), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Block candidate approval unless objective delta and replay robustness edge are both positive."
    )
    parser.add_argument("--candidate-pack", required=True)
    parser.add_argument(
        "--report-json",
        default=None,
        help="Path to recommendation_report.json (defaults to reports/<candidate>/recommendation_report.json)",
    )
    parser.add_argument(
        "--replay-summary-csv",
        required=True,
        help="Path to candidate_robustness_edge_summary.csv",
    )
    parser.add_argument("--reviewer", default="strict_gate")
    parser.add_argument("--notes", default=None)
    parser.add_argument(
        "--record-manual-approval",
        action="store_true",
        help="Record approval/rejection in promotion state.",
    )
    parser.add_argument(
        "--state-path",
        default=str(PROMOTION_STATE_PATH),
        help="Promotion state file path used when recording manual approval.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    candidate_pack_name = str(args.candidate_pack).strip()
    report_json_path = Path(args.report_json) if args.report_json else (
        ROOT / "research" / "parameter_tuning" / "reports" / candidate_pack_name / "recommendation_report.json"
    )
    replay_summary_csv_path = Path(args.replay_summary_csv)

    if not report_json_path.is_absolute():
        report_json_path = ROOT / report_json_path
    if not replay_summary_csv_path.is_absolute():
        replay_summary_csv_path = ROOT / replay_summary_csv_path

    if not report_json_path.exists():
        raise FileNotFoundError(f"Recommendation report not found: {report_json_path}")
    if not replay_summary_csv_path.exists():
        raise FileNotFoundError(f"Replay robustness summary not found: {replay_summary_csv_path}")

    decision = evaluate_gate(
        candidate_pack_name=candidate_pack_name,
        report_json_path=report_json_path,
        replay_summary_csv_path=replay_summary_csv_path,
    )

    if args.record_manual_approval:
        state = record_manual_approval(
            pack_name=candidate_pack_name,
            approved=bool(decision["gate_passed"]),
            reviewer=str(args.reviewer),
            notes=args.notes or decision["reason"],
            approval_type="PROMOTION_STRICT_GATE",
            required=True,
            path=args.state_path,
        )
        decision["manual_approval_recorded"] = True
        decision["manual_approval"] = dict((state.get("manual_approvals") or {}).get(candidate_pack_name, {}))
    else:
        decision["manual_approval_recorded"] = False

    decision_path = _write_decision_artifact(decision)
    decision["decision_artifact_path"] = str(decision_path)

    print(json.dumps(decision, indent=2, sort_keys=True))

    if not decision["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

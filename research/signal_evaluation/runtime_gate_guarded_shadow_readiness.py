"""Readiness gate for guarded runtime-gate shadow experiments.

This research-only gate converts the guarded shadow experiment output into a
promotion-readiness checklist. It never changes runtime scoring, thresholds,
parameter packs, data-source routing, or execution behavior.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research.signal_evaluation.runtime_gate_guarded_shadow_experiment import (
    ACTION_DEFER_HOLDOUT,
    ACTION_KEEP_BLOCKED,
    ACTION_PRESERVE_PREFERRED,
    ACTION_PRESERVE_REVIEW,
    DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_DIR,
    LATEST_JSON_FILENAME as SHADOW_LATEST_JSON_FILENAME,
)
from research.signal_evaluation.signal_quality_model_audit import _atomic_write_text, _sanitize_value


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_READINESS_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_gate_guarded_shadow_readiness"
)
DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_REPORT_PATH = DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_DIR / SHADOW_LATEST_JSON_FILENAME

LATEST_JSON_FILENAME = "latest_runtime_gate_guarded_shadow_readiness.json"
LATEST_MARKDOWN_FILENAME = "latest_runtime_gate_guarded_shadow_readiness.md"

STATUS_ACCUMULATING = "ACCUMULATING"
STATUS_REVIEW_READY = "REVIEW_READY"
STATUS_BLOCKED = "BLOCKED"
PROMOTION_READY_FALSE = "PROMOTION_READY_FALSE"


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _load_shadow_report(path: str | Path) -> dict[str, Any]:
    shadow_path = Path(path)
    if not shadow_path.exists():
        return {}
    try:
        payload = json.loads(shadow_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _action_row(report: dict[str, Any], action: str) -> dict[str, Any] | None:
    rows = report.get("exact_action_metrics") or []
    if not isinstance(rows, list):
        return None
    return next((row for row in rows if isinstance(row, dict) and row.get("shadow_action") == action), None)


def _float_value(row: dict[str, Any] | None, key: str) -> float | None:
    if not row:
        return None
    value = row.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(row: dict[str, Any] | None, key: str) -> int:
    value = _float_value(row, key)
    return int(value) if value is not None else 0


def _delta(left: dict[str, Any] | None, right: dict[str, Any] | None, key: str) -> float | None:
    left_value = _float_value(left, key)
    right_value = _float_value(right, key)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


def _check(
    *,
    name: str,
    passed: bool | None,
    observed: Any,
    threshold: Any,
    reason: str,
    pending_if_sample_pending: bool = False,
    sample_pending: bool = False,
) -> dict[str, Any]:
    if pending_if_sample_pending and sample_pending:
        status = "PENDING"
    elif passed is True:
        status = "OK"
    elif passed is None:
        status = "UNKNOWN"
    else:
        status = "FAIL"
    return {
        "name": name,
        "status": status,
        "observed": observed,
        "threshold": threshold,
        "reason": reason,
    }


def build_runtime_gate_guarded_shadow_readiness_report(
    shadow_report: dict[str, Any],
    *,
    shadow_report_path: str | Path | None = None,
    min_exact_sessions: int = 5,
    min_preferred_exact_rows: int = 300,
    max_tail_damage_bps: float = 0.0,
) -> dict[str, Any]:
    """Build a research-only readiness report from a guarded shadow artifact."""
    shadow = shadow_report if isinstance(shadow_report, dict) else {}
    preferred = _action_row(shadow, ACTION_PRESERVE_PREFERRED)
    review = _action_row(shadow, ACTION_PRESERVE_REVIEW)
    guardrail = _action_row(shadow, ACTION_KEEP_BLOCKED)
    holdout = _action_row(shadow, ACTION_DEFER_HOLDOUT)
    exact_summary = shadow.get("exact_forward_summary") or {}
    exact_sessions = int(exact_summary.get("exact_forward_session_count") or 0)
    preferred_rows = _int_value(preferred, "row_count")

    sample_reasons: list[str] = []
    if exact_sessions < int(min_exact_sessions):
        sample_reasons.append(f"exact_sessions {exact_sessions}/{int(min_exact_sessions)}")
    if preferred_rows < int(min_preferred_exact_rows):
        sample_reasons.append(f"preferred_exact_rows {preferred_rows}/{int(min_preferred_exact_rows)}")
    sample_pending = bool(sample_reasons)

    preferred_vs_guardrail_60m = _delta(preferred, guardrail, "avg_signed_return_60m_bps")
    preferred_vs_holdout_60m = _delta(preferred, holdout, "avg_signed_return_60m_bps")
    preferred_vs_guardrail_ratio = _delta(preferred, guardrail, "mfe_mae_ratio_60m")
    preferred_vs_holdout_ratio = _delta(preferred, holdout, "mfe_mae_ratio_60m")
    preferred_vs_guardrail_30m = _delta(preferred, guardrail, "avg_signed_return_30m_bps")
    preferred_vs_guardrail_120m = _delta(preferred, guardrail, "avg_signed_return_120m_bps")
    preferred_vs_guardrail_close = _delta(preferred, guardrail, "avg_signed_return_session_close_bps")
    preferred_vs_review_60m = _delta(preferred, review, "avg_signed_return_60m_bps")
    preferred_vs_review_ratio = _delta(preferred, review, "mfe_mae_ratio_60m")

    checks = [
        _check(
            name="minimum_exact_sessions",
            passed=exact_sessions >= int(min_exact_sessions),
            observed=exact_sessions,
            threshold=int(min_exact_sessions),
            reason="Needs enough exact-forward sessions before promotion review.",
        ),
        _check(
            name="minimum_preferred_exact_rows",
            passed=preferred_rows >= int(min_preferred_exact_rows),
            observed=preferred_rows,
            threshold=int(min_preferred_exact_rows),
            reason="Needs enough preferred-preserve rows before promotion review.",
        ),
        _check(
            name="preferred_beats_guardrail_60m_return",
            passed=preferred_vs_guardrail_60m is not None and preferred_vs_guardrail_60m > 0.0,
            observed=preferred_vs_guardrail_60m,
            threshold="> 0 bps",
            reason="Preferred preserve rows must beat guardrails on 60m signed return.",
            pending_if_sample_pending=True,
            sample_pending=sample_pending,
        ),
        _check(
            name="preferred_beats_holdout_60m_return",
            passed=preferred_vs_holdout_60m is not None and preferred_vs_holdout_60m > 0.0,
            observed=preferred_vs_holdout_60m,
            threshold="> 0 bps",
            reason="Preferred preserve rows must beat deferred holdout rows on 60m signed return.",
            pending_if_sample_pending=True,
            sample_pending=sample_pending,
        ),
        _check(
            name="preferred_beats_guardrail_60m_mfe_mae",
            passed=preferred_vs_guardrail_ratio is not None and preferred_vs_guardrail_ratio > 0.0,
            observed=preferred_vs_guardrail_ratio,
            threshold="> 0",
            reason="Preferred preserve rows must beat guardrails on 60m path quality.",
            pending_if_sample_pending=True,
            sample_pending=sample_pending,
        ),
        _check(
            name="preferred_beats_holdout_60m_mfe_mae",
            passed=preferred_vs_holdout_ratio is not None and preferred_vs_holdout_ratio > 0.0,
            observed=preferred_vs_holdout_ratio,
            threshold="> 0",
            reason="Preferred preserve rows must beat holdout on 60m path quality.",
            pending_if_sample_pending=True,
            sample_pending=sample_pending,
        ),
        _check(
            name="no_30m_degradation_vs_guardrail",
            passed=preferred_vs_guardrail_30m is not None and preferred_vs_guardrail_30m >= 0.0,
            observed=preferred_vs_guardrail_30m,
            threshold=">= 0 bps",
            reason="Preferred preserve rows must not degrade 30m signed return versus guardrails.",
            pending_if_sample_pending=True,
            sample_pending=sample_pending,
        ),
        _check(
            name="no_120m_tail_damage_vs_guardrail",
            passed=preferred_vs_guardrail_120m is not None and preferred_vs_guardrail_120m >= -float(max_tail_damage_bps),
            observed=preferred_vs_guardrail_120m,
            threshold=f">= -{float(max_tail_damage_bps)} bps",
            reason="Preferred preserve rows must not create materially worse 120m tail versus guardrails.",
            pending_if_sample_pending=True,
            sample_pending=sample_pending,
        ),
        _check(
            name="no_session_close_tail_damage_vs_guardrail",
            passed=(
                preferred_vs_guardrail_close is not None
                and preferred_vs_guardrail_close >= -float(max_tail_damage_bps)
            ),
            observed=preferred_vs_guardrail_close,
            threshold=f">= -{float(max_tail_damage_bps)} bps",
            reason="Preferred preserve rows must not create materially worse session-close tail versus guardrails.",
            pending_if_sample_pending=True,
            sample_pending=sample_pending,
        ),
        _check(
            name="preferred_stronger_than_review_60m_return",
            passed=preferred_vs_review_60m is not None and preferred_vs_review_60m > 0.0,
            observed=preferred_vs_review_60m,
            threshold="> 0 bps",
            reason="Preserve-count 4+ must remain stronger than preserve-count 3 on 60m return.",
            pending_if_sample_pending=True,
            sample_pending=sample_pending,
        ),
        _check(
            name="preferred_stronger_than_review_60m_mfe_mae",
            passed=preferred_vs_review_ratio is not None and preferred_vs_review_ratio > 0.0,
            observed=preferred_vs_review_ratio,
            threshold="> 0",
            reason="Preserve-count 4+ must remain stronger than preserve-count 3 on path quality.",
            pending_if_sample_pending=True,
            sample_pending=sample_pending,
        ),
    ]

    mandatory_failures = [check for check in checks if check["status"] in {"FAIL", "UNKNOWN"}]
    if sample_pending:
        readiness_status = STATUS_ACCUMULATING
        readiness_reasons = sample_reasons
    elif mandatory_failures:
        readiness_status = STATUS_BLOCKED
        readiness_reasons = [f"{check['name']}: {check['reason']}" for check in mandatory_failures]
    else:
        readiness_status = STATUS_REVIEW_READY
        readiness_reasons = ["guarded shadow evidence meets formal review thresholds"]

    report = {
        "report_type": "runtime_gate_guarded_shadow_readiness",
        "generated_at": _now_utc(),
        "research_only": True,
        "runtime_config_changed": False,
        "parameter_pack_file_changed": False,
        "execution_behavior_changed": False,
        "readiness_status": readiness_status,
        "promotion_status": PROMOTION_READY_FALSE,
        "promotion_ready": False,
        "shadow_report_path": str(shadow_report_path) if shadow_report_path is not None else None,
        "shadow_report_generated_at": shadow.get("generated_at"),
        "shadow_read": shadow.get("shadow_read"),
        "thresholds": {
            "min_exact_sessions": int(min_exact_sessions),
            "min_preferred_exact_rows": int(min_preferred_exact_rows),
            "max_tail_damage_bps": float(max_tail_damage_bps),
        },
        "exact_forward_summary": exact_summary,
        "action_metrics": {
            "preferred": preferred or {},
            "review": review or {},
            "guardrail": guardrail or {},
            "holdout": holdout or {},
        },
        "deltas": {
            "preferred_minus_guardrail_60m_return_bps": preferred_vs_guardrail_60m,
            "preferred_minus_holdout_60m_return_bps": preferred_vs_holdout_60m,
            "preferred_minus_guardrail_60m_mfe_mae": preferred_vs_guardrail_ratio,
            "preferred_minus_holdout_60m_mfe_mae": preferred_vs_holdout_ratio,
            "preferred_minus_guardrail_30m_return_bps": preferred_vs_guardrail_30m,
            "preferred_minus_guardrail_120m_return_bps": preferred_vs_guardrail_120m,
            "preferred_minus_guardrail_session_close_return_bps": preferred_vs_guardrail_close,
            "preferred_minus_review_60m_return_bps": preferred_vs_review_60m,
            "preferred_minus_review_60m_mfe_mae": preferred_vs_review_ratio,
        },
        "checks": checks,
        "readiness_reasons": readiness_reasons,
        "recommended_next_actions": [
            "Keep this readiness gate research-only; do not alter runtime thresholds or trade decisions.",
            "Rerun after each data-rich session and after the guarded shadow experiment refreshes.",
            "Only consider live promotion after REVIEW_READY and a separate human approval step.",
        ],
    }
    return _sanitize_value(report)


def render_runtime_gate_guarded_shadow_readiness_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Runtime Gate Guarded Shadow Readiness",
        "",
        "> Author: Pramit Dutta | Organization: Quant Engines",
        "",
        f"- Generated at: {report.get('generated_at')}",
        f"- Research only: `{report.get('research_only')}`",
        f"- Readiness status: `{report.get('readiness_status')}`",
        f"- Promotion status: `{report.get('promotion_status')}`",
        f"- Promotion ready: `{report.get('promotion_ready')}`",
        f"- Runtime config changed: `{report.get('runtime_config_changed')}`",
        f"- Execution behavior changed: `{report.get('execution_behavior_changed')}`",
        f"- Shadow read: `{report.get('shadow_read')}`",
        f"- Shadow report: `{report.get('shadow_report_path')}`",
        "",
        "## Thresholds",
        "",
    ]
    for key, value in (report.get("thresholds") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Exact Forward Summary", ""])
    for key, value in (report.get("exact_forward_summary") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Readiness Reasons", ""])
    for reason in report.get("readiness_reasons", []) or []:
        lines.append(f"- {reason}")
    lines.extend(["", "## Deltas", ""])
    for key, value in (report.get("deltas") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Checks", ""])
    checks = report.get("checks") or []
    if checks:
        lines.extend(
            [
                "| check | status | observed | threshold | reason |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for check in checks:
            lines.append(
                "| "
                + " | ".join(
                    str(check.get(key, ""))
                    for key in ("name", "status", "observed", "threshold", "reason")
                )
                + " |"
            )
    else:
        lines.append("No checks available.")
    lines.extend(["", "## Recommended Next Actions", ""])
    for action in report.get("recommended_next_actions", []) or []:
        lines.append(f"- {action}")
    lines.extend(["", "*Research-only readiness gate. It does not alter live signal behavior.*", ""])
    return "\n".join(lines)


def write_runtime_gate_guarded_shadow_readiness_report(
    *,
    shadow_report_path: str | Path = DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_REPORT_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_READINESS_DIR,
    min_exact_sessions: int = 5,
    min_preferred_exact_rows: int = 300,
    max_tail_damage_bps: float = 0.0,
) -> dict[str, Any]:
    shadow_path = Path(shadow_report_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    shadow = _load_shadow_report(shadow_path)
    report = build_runtime_gate_guarded_shadow_readiness_report(
        shadow,
        shadow_report_path=shadow_path,
        min_exact_sessions=min_exact_sessions,
        min_preferred_exact_rows=min_preferred_exact_rows,
        max_tail_damage_bps=max_tail_damage_bps,
    )
    stem = "runtime_gate_guarded_shadow_readiness"
    json_path = output / f"{stem}.json"
    markdown_path = output / f"{stem}.md"
    latest_json_path = output / LATEST_JSON_FILENAME
    latest_markdown_path = output / LATEST_MARKDOWN_FILENAME
    markdown = render_runtime_gate_guarded_shadow_readiness_markdown(report)
    _atomic_write_text(json_path, json.dumps(report, indent=2, sort_keys=True, default=str))
    _atomic_write_text(markdown_path, markdown)
    _atomic_write_text(latest_json_path, json.dumps(report, indent=2, sort_keys=True, default=str))
    _atomic_write_text(latest_markdown_path, markdown)
    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
    }


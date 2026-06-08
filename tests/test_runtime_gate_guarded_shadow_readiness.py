from __future__ import annotations

from research.signal_evaluation.runtime_gate_guarded_shadow_experiment import (
    ACTION_DEFER_HOLDOUT,
    ACTION_KEEP_BLOCKED,
    ACTION_PRESERVE_PREFERRED,
    ACTION_PRESERVE_REVIEW,
)
from research.signal_evaluation.runtime_gate_guarded_shadow_readiness import (
    PROMOTION_READY_FALSE,
    STATUS_ACCUMULATING,
    STATUS_BLOCKED,
    STATUS_REVIEW_READY,
    build_runtime_gate_guarded_shadow_readiness_report,
)


def _action(
    action: str,
    *,
    rows: int,
    ret30: float,
    ret60: float,
    ret120: float,
    ret_close: float,
    ratio: float,
) -> dict:
    return {
        "shadow_action": action,
        "row_count": rows,
        "label_count_60m": rows,
        "hit_rate_30m": 0.6,
        "avg_signed_return_30m_bps": ret30,
        "hit_rate_60m": 0.65,
        "avg_signed_return_60m_bps": ret60,
        "hit_rate_120m": 0.6,
        "avg_signed_return_120m_bps": ret120,
        "hit_rate_session_close": 0.55,
        "avg_signed_return_session_close_bps": ret_close,
        "mfe_mae_ratio_60m": ratio,
    }


def _shadow_report(*, preferred_rows: int = 320, sessions: int = 5, preferred_ret60: float = 10.0) -> dict:
    return {
        "generated_at": "2026-06-08T11:05:00+00:00",
        "shadow_read": "GUARDED_SHADOW_ACTIVE_RESEARCH_ONLY",
        "research_only": True,
        "runtime_config_changed": False,
        "execution_behavior_changed": False,
        "exact_forward_summary": {
            "exact_forward_session_count": sessions,
            "exact_forward_rows": 2000,
        },
        "exact_action_metrics": [
            _action(
                ACTION_PRESERVE_PREFERRED,
                rows=preferred_rows,
                ret30=5.0,
                ret60=preferred_ret60,
                ret120=8.0,
                ret_close=4.0,
                ratio=2.0,
            ),
            _action(
                ACTION_PRESERVE_REVIEW,
                rows=400,
                ret30=3.0,
                ret60=6.0,
                ret120=5.0,
                ret_close=2.0,
                ratio=1.4,
            ),
            _action(
                ACTION_KEEP_BLOCKED,
                rows=1200,
                ret30=1.0,
                ret60=2.0,
                ret120=3.0,
                ret_close=1.0,
                ratio=0.8,
            ),
            _action(
                ACTION_DEFER_HOLDOUT,
                rows=250,
                ret30=-1.0,
                ret60=-2.0,
                ret120=-3.0,
                ret_close=-4.0,
                ratio=0.5,
            ),
        ],
    }


def test_guarded_shadow_readiness_accumulates_until_sessions_and_rows_mature():
    report = build_runtime_gate_guarded_shadow_readiness_report(
        _shadow_report(preferred_rows=56, sessions=3),
        min_exact_sessions=5,
        min_preferred_exact_rows=300,
    )

    assert report["readiness_status"] == STATUS_ACCUMULATING
    assert report["promotion_status"] == PROMOTION_READY_FALSE
    assert report["promotion_ready"] is False
    assert any("exact_sessions 3/5" in reason for reason in report["readiness_reasons"])
    assert any("preferred_exact_rows 56/300" in reason for reason in report["readiness_reasons"])
    pending = {check["name"]: check["status"] for check in report["checks"]}
    assert pending["preferred_beats_guardrail_60m_return"] == "PENDING"


def test_guarded_shadow_readiness_review_ready_after_all_checks_pass():
    report = build_runtime_gate_guarded_shadow_readiness_report(
        _shadow_report(),
        min_exact_sessions=5,
        min_preferred_exact_rows=300,
    )

    assert report["readiness_status"] == STATUS_REVIEW_READY
    assert report["promotion_status"] == PROMOTION_READY_FALSE
    assert report["promotion_ready"] is False
    assert all(check["status"] == "OK" for check in report["checks"])


def test_guarded_shadow_readiness_blocks_when_mature_metrics_fail():
    report = build_runtime_gate_guarded_shadow_readiness_report(
        _shadow_report(preferred_rows=320, sessions=5, preferred_ret60=1.0),
        min_exact_sessions=5,
        min_preferred_exact_rows=300,
    )

    assert report["readiness_status"] == STATUS_BLOCKED
    failures = {check["name"]: check["status"] for check in report["checks"]}
    assert failures["preferred_beats_guardrail_60m_return"] == "FAIL"
    assert any("preferred_beats_guardrail_60m_return" in reason for reason in report["readiness_reasons"])


from __future__ import annotations

import json

import pandas as pd

from research.signal_evaluation.runtime_gate_candidate_readiness import (
    RUNTIME_GATE_CANDIDATE_ACCUMULATING,
    RUNTIME_GATE_CANDIDATE_BLOCKED,
    RUNTIME_GATE_CANDIDATE_REVIEW_READY,
    build_runtime_gate_candidate_readiness_report,
)


def _component_payload(pre_adjust_score: int) -> str:
    components = {}
    for component in ("trade_strength", "move_probability", "confirmation", "data_quality", "gamma_stability"):
        components[component] = {
            "score": pre_adjust_score,
            "weight": 0.2,
            "weighted_contribution": pre_adjust_score * 0.2,
            "weighted_deficit_to_100": (100 - pre_adjust_score) * 0.2,
        }
    return json.dumps({"pre_adjust_score": pre_adjust_score, "components": components, "final_score": 46})


def _candidate_row(timestamp: str, *, signed_return: float = 12.0) -> dict:
    return {
        "signal_timestamp": timestamp,
        "direction": "PUT",
        "trade_status": "WATCHLIST",
        "runtime_composite_score": 46,
        "runtime_composite_components": _component_payload(75),
        "trade_strength": 65,
        "hybrid_move_probability": 0.58,
        "macro_regime": "RISK_OFF",
        "global_risk_state": "RISK_OFF",
        "spot_vs_flip": "BELOW_FLIP",
        "gamma_regime": "POSITIVE_GAMMA",
        "volatility_regime": "NORMAL_VOL",
        "correct_60m": 1 if signed_return > 0 else 0,
        "signed_return_60m_bps": signed_return,
        "mfe_60m_bps": 20.0 if signed_return > 0 else 4.0,
        "mae_60m_bps": -8.0 if signed_return > 0 else -12.0,
    }


def _guardrail_row(timestamp: str) -> dict:
    return {
        "signal_timestamp": timestamp,
        "direction": "PUT",
        "trade_status": "WATCHLIST",
        "runtime_composite_score": 42,
        "runtime_composite_components": _component_payload(85),
        "trade_strength": 85,
        "hybrid_move_probability": 0.62,
        "macro_regime": "MACRO_NEUTRAL",
        "global_risk_state": "GLOBAL_NEUTRAL",
        "spot_vs_flip": "AT_FLIP",
        "gamma_regime": "NEGATIVE_GAMMA",
        "volatility_regime": "LOW_VOL",
        "correct_60m": 0,
        "signed_return_60m_bps": -12.0,
        "mfe_60m_bps": 5.0,
        "mae_60m_bps": -16.0,
    }


def _holdout_row(timestamp: str) -> dict:
    return {
        "signal_timestamp": timestamp,
        "direction": "CALL",
        "trade_status": "WATCHLIST",
        "runtime_composite_score": 52,
        "runtime_composite_components": _component_payload(55),
        "trade_strength": 52,
        "hybrid_move_probability": 0.45,
        "macro_regime": "MACRO_NEUTRAL",
        "global_risk_state": "GLOBAL_NEUTRAL",
        "spot_vs_flip": "BELOW_FLIP",
        "gamma_regime": "POSITIVE_GAMMA",
        "volatility_regime": "NORMAL_VOL",
        "correct_60m": 1,
        "signed_return_60m_bps": 1.0,
        "mfe_60m_bps": 3.0,
        "mae_60m_bps": -4.0,
    }


def test_runtime_gate_candidate_readiness_accumulates_without_exact_components():
    frame = pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-06-03T09:20:00+05:30",
                "direction": "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 46,
                "trade_strength": 65,
                "hybrid_move_probability": 0.58,
                "macro_regime": "RISK_OFF",
                "global_risk_state": "RISK_OFF",
                "spot_vs_flip": "BELOW_FLIP",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "correct_60m": 1,
                "signed_return_60m_bps": 8.0,
            }
        ]
    )

    report = build_runtime_gate_candidate_readiness_report(
        frame,
        dataset_path="unit.csv",
        min_exact_candidate_rows=1,
        min_exact_guardrail_rows=1,
        min_exact_sessions=1,
    )

    assert report["readiness_status"] == RUNTIME_GATE_CANDIDATE_ACCUMULATING
    assert report["manual_review_ready"] is False
    assert report["promotion_ready"] is False
    assert report["exact_forward_summary"]["exact_component_rows"] == 0


def test_runtime_gate_candidate_readiness_review_ready_with_exact_forward_rows():
    frame = pd.DataFrame(
        [
            _candidate_row("2026-06-03T09:20:00+05:30", signed_return=12.0),
            _candidate_row("2026-06-04T09:20:00+05:30", signed_return=10.0),
            _guardrail_row("2026-06-03T09:25:00+05:30"),
            _holdout_row("2026-06-04T09:30:00+05:30"),
        ]
    )

    report = build_runtime_gate_candidate_readiness_report(
        frame,
        dataset_path="unit.csv",
        min_exact_candidate_rows=2,
        min_exact_guardrail_rows=1,
        min_exact_sessions=2,
    )

    assert report["readiness_status"] == RUNTIME_GATE_CANDIDATE_REVIEW_READY
    assert report["manual_review_ready"] is True
    assert report["promotion_ready"] is False
    assert report["exact_forward_summary"]["exact_forward_candidate_rows"] == 2
    assert report["candidate_vs_guardrail_and_holdout"]["candidate_minus_guardrail_return_60m_bps"] > 0


def test_runtime_gate_candidate_readiness_blocks_weak_exact_candidate():
    frame = pd.DataFrame(
        [
            _candidate_row("2026-06-03T09:20:00+05:30", signed_return=-6.0),
            _guardrail_row("2026-06-03T09:25:00+05:30"),
            _holdout_row("2026-06-03T09:30:00+05:30"),
        ]
    )

    report = build_runtime_gate_candidate_readiness_report(
        frame,
        dataset_path="unit.csv",
        min_exact_candidate_rows=1,
        min_exact_guardrail_rows=1,
        min_exact_sessions=1,
    )

    assert report["readiness_status"] == RUNTIME_GATE_CANDIDATE_BLOCKED
    assert report["manual_review_ready"] is False
    assert any("candidate_return_60m_bps" in reason for reason in report["readiness_reasons"])

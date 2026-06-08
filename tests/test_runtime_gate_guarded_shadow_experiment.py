from __future__ import annotations

import json

import pandas as pd

from research.signal_evaluation.runtime_gate_guarded_shadow_experiment import (
    ACTION_DEFER_HOLDOUT,
    ACTION_KEEP_BLOCKED,
    ACTION_PRESERVE_PREFERRED,
    ACTION_PRESERVE_REVIEW,
    build_runtime_gate_guarded_shadow_report,
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
    return json.dumps({"pre_adjust_score": pre_adjust_score, "components": components, "final_score": 45})


def _row(
    *,
    timestamp: str,
    direction: str = "PUT",
    runtime: int,
    pre_adjust: int,
    trade_strength: int,
    macro: str,
    global_risk: str,
    flip: str,
    gamma: str,
    vol: str = "NORMAL_VOL",
    correct_60m: int,
    return_60m: float,
    mfe: float,
    mae: float,
) -> dict:
    return {
        "signal_timestamp": timestamp,
        "direction": direction,
        "trade_status": "WATCHLIST",
        "runtime_composite_score": runtime,
        "runtime_composite_components": _component_payload(pre_adjust),
        "trade_strength": trade_strength,
        "hybrid_move_probability": 0.52,
        "macro_regime": macro,
        "global_risk_state": global_risk,
        "spot_vs_flip": flip,
        "gamma_regime": gamma,
        "volatility_regime": vol,
        "correct_30m": correct_60m,
        "signed_return_30m_bps": return_60m / 2.0,
        "correct_60m": correct_60m,
        "signed_return_60m_bps": return_60m,
        "correct_120m": correct_60m,
        "signed_return_120m_bps": return_60m * 1.5,
        "mfe_60m_bps": mfe,
        "mae_60m_bps": mae,
    }


def test_runtime_gate_guarded_shadow_experiment_splits_preferred_review_guardrail_and_holdout():
    frame = pd.DataFrame(
        [
            _row(
                timestamp="2026-06-04T09:20:00+05:30",
                runtime=45,
                pre_adjust=75,
                trade_strength=65,
                macro="RISK_OFF",
                global_risk="RISK_OFF",
                flip="BELOW_FLIP",
                gamma="POSITIVE_GAMMA",
                correct_60m=1,
                return_60m=16.0,
                mfe=24.0,
                mae=-8.0,
            ),
            _row(
                timestamp="2026-06-04T09:25:00+05:30",
                runtime=45,
                pre_adjust=75,
                trade_strength=52,
                macro="MACRO_NEUTRAL",
                global_risk="GLOBAL_NEUTRAL",
                flip="BELOW_FLIP",
                gamma="POSITIVE_GAMMA",
                correct_60m=1,
                return_60m=4.0,
                mfe=8.0,
                mae=-7.0,
            ),
            _row(
                timestamp="2026-06-04T09:30:00+05:30",
                runtime=45,
                pre_adjust=85,
                trade_strength=85,
                macro="MACRO_NEUTRAL",
                global_risk="GLOBAL_NEUTRAL",
                flip="AT_FLIP",
                gamma="NEGATIVE_GAMMA",
                vol="LOW_VOL",
                correct_60m=0,
                return_60m=-10.0,
                mfe=4.0,
                mae=-15.0,
            ),
            _row(
                timestamp="2026-06-04T09:35:00+05:30",
                runtime=52,
                pre_adjust=60,
                trade_strength=50,
                macro="MACRO_NEUTRAL",
                global_risk="GLOBAL_NEUTRAL",
                flip="BELOW_FLIP",
                gamma="POSITIVE_GAMMA",
                correct_60m=0,
                return_60m=-2.0,
                mfe=3.0,
                mae=-4.0,
            ),
        ]
    )

    report = build_runtime_gate_guarded_shadow_report(
        frame,
        dataset_path="unit.csv",
        start_date="2026-06-04",
        end_date="2026-06-04",
        min_preferred_exact_rows=1,
        min_exact_sessions=1,
        min_segment_rows=1,
    )

    assert report["research_only"] is True
    assert report["runtime_config_changed"] is False
    assert report["execution_behavior_changed"] is False
    assert report["live_promotion_ready"] is False
    assert report["shadow_read"] == "GUARDED_SHADOW_ACTIVE_RESEARCH_ONLY"
    assert report["exact_forward_summary"]["exact_forward_session_count"] == 1

    actions = {row["shadow_action"]: row for row in report["action_metrics"]}
    assert actions[ACTION_PRESERVE_PREFERRED]["row_count"] == 1
    assert actions[ACTION_PRESERVE_PREFERRED]["avg_signed_return_60m_bps"] == 16.0
    assert actions[ACTION_PRESERVE_REVIEW]["row_count"] == 1
    assert actions[ACTION_KEEP_BLOCKED]["row_count"] == 1
    assert actions[ACTION_DEFER_HOLDOUT]["row_count"] == 1

    comparison = report["exact_action_comparison"]
    assert comparison["preferred_minus_guardrail_return_60m_bps"] == 26.0
    assert comparison["preferred_minus_review_return_60m_bps"] == 12.0

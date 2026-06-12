from __future__ import annotations

from research.signal_evaluation.decision_quality_bridge import compute_decision_quality_bridge


def test_decision_quality_bridge_scores_clean_setup_above_blocked_setup():
    clean = {
        "trade_strength": 74,
        "runtime_composite_score": 58,
        "hybrid_move_probability": 0.64,
        "ta_entry_timing_state": "CANDLE_CONFIRMED_PUT",
        "ta_entry_timing_score": 76,
        "option_efficiency_score": 72,
        "target_reachability_score": 70,
        "price_level_confluence_score": 68,
        "price_structure_acceptance_state": "BREAKOUT_ACCEPTED",
        "provider_health_status": "GOOD",
        "provider_analytics_status": "USABLE",
        "provider_execution_status": "USABLE",
        "data_quality_status": "STRONG",
        "gamma_regime": "POSITIVE_GAMMA",
        "spot_vs_flip": "BELOW_FLIP",
        "macro_regime": "MACRO_NEUTRAL",
        "global_risk_state": "GLOBAL_NEUTRAL",
    }
    blocked = {
        **clean,
        "trade_strength": 42,
        "runtime_composite_score": 39,
        "hybrid_move_probability": 0.34,
        "ta_entry_timing_state": "CANDLE_LATE_CHASE_PUT",
        "ta_candle_late_chase": True,
        "option_efficiency_score": 38,
        "provider_quality_blocks_direction": True,
        "provider_health_status": "WEAK",
        "data_quality_status": "WEAK",
        "spot_vs_flip": "AT_FLIP",
        "macro_regime": "RISK_OFF",
        "global_risk_state": "RISK_OFF",
    }

    clean_score = compute_decision_quality_bridge(clean)
    blocked_score = compute_decision_quality_bridge(blocked)

    assert clean_score["score"] > blocked_score["score"]
    assert clean_score["live_safe"] is True
    assert clean_score["research_only"] is True
    assert "provider_direction_block" in blocked_score["penalties"]


def test_decision_quality_bridge_reports_missing_components_without_failing():
    payload = compute_decision_quality_bridge({"trade_strength": 55})

    assert payload["score"] == 55
    assert payload["available_components"] == ["signal_intensity"]
    assert "timing" in payload["missing_components"]

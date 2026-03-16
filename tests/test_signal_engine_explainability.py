from __future__ import annotations

from engine.signal_engine import _build_decision_explainability


def test_directionless_two_sided_setup_is_explicitly_ambiguous_watchlist():
    payload = {
        "direction": None,
        "flow_signal": "BEARISH_FLOW",
        "smart_money_flow": "NEUTRAL_FLOW",
        "confirmation_status": "NO_DIRECTION",
        "signal_quality": "VERY_WEAK",
        "directional_convexity_state": "TWO_SIDED_VOLATILITY_RISK",
        "dealer_flow_state": "PINNING_DOMINANT",
        "dealer_hedging_bias": "DOWNSIDE_PINNING",
        "trade_strength": 24,
        "support_wall": 23000,
        "resistance_wall": 23250,
        "gamma_flip": 23120,
        "spot": 23110,
        "macro_adjustment_reasons": ["macro_news_neutral_fallback"],
        "global_risk_diagnostics": {"fallback": True},
        "expected_move_points": None,
    }

    explainability = _build_decision_explainability(
        payload,
        trade_status="NO_SIGNAL",
        min_trade_strength=45,
    )

    assert explainability["decision_classification"] == "DIRECTIONALLY_AMBIGUOUS"
    assert explainability["setup_state"] == "DIRECTION_PENDING"
    assert explainability["watchlist_flag"] is True
    assert explainability["no_trade_reason_code"] == "TWO_SIDED_VOLATILITY_WITHOUT_EDGE"
    assert "missing_directional_consensus" in explainability["missing_signal_requirements"]
    assert "insufficient_trade_strength" in explainability["missing_signal_requirements"]


def test_data_invalid_maps_to_data_blocked_taxonomy():
    payload = {
        "direction": None,
        "signal_quality": "VERY_WEAK",
        "trade_strength": 0,
        "spot": 0,
    }

    explainability = _build_decision_explainability(
        payload,
        trade_status="DATA_INVALID",
        min_trade_strength=45,
    )

    assert explainability["decision_classification"] == "DATA_BLOCKED"
    assert explainability["setup_state"] == "DATA_BLOCKED"
    assert explainability["no_trade_reason_code"] == "DATA_QUALITY_INSUFFICIENT"
    assert "data_quality" in explainability["blocked_by"]


def test_trade_ready_case_keeps_no_trade_fields_empty():
    payload = {
        "direction": "CALL",
        "flow_signal": "BULLISH_FLOW",
        "smart_money_flow": "BULLISH_FLOW",
        "confirmation_status": "CONFIRMED",
        "signal_quality": "STRONG",
        "trade_strength": 78,
        "spot": 23000,
    }

    explainability = _build_decision_explainability(
        payload,
        trade_status="TRADE",
        min_trade_strength=45,
    )

    assert explainability["decision_classification"] == "TRADE_READY"
    assert explainability["setup_state"] == "NONE"
    assert explainability["watchlist_flag"] is False
    assert explainability["no_trade_reason"] is None


def test_directionless_low_activation_setup_is_classified_as_inactive():
    payload = {
        "direction": None,
        "flow_signal": "NEUTRAL_FLOW",
        "smart_money_flow": "NEUTRAL_FLOW",
        "confirmation_status": "NO_DIRECTION",
        "signal_quality": "VERY_WEAK",
        "directional_convexity_state": "NO_CONVEXITY_EDGE",
        "dealer_flow_state": "HEDGING_NEUTRAL",
        "trade_strength": 7,
        "spot": 23100,
        "hybrid_move_probability": 0.42,
        "expected_move_points": None,
    }

    explainability = _build_decision_explainability(
        payload,
        trade_status="NO_SIGNAL",
        min_trade_strength=45,
    )

    assert explainability["decision_classification"] == "DEAD_INACTIVE"
    assert explainability["watchlist_flag"] is False
    assert explainability["setup_activation_score"] < 35
    assert explainability["explainability_confidence"] in {"LOW", "MEDIUM", "HIGH"}

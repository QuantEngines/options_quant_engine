from contextlib import redirect_stdout
from io import StringIO

from app.terminal_output import (
    _resolve_fibonacci_retracement_levels,
    _resolve_price_structure_levels,
    render_snapshot,
)


def test_resolve_fibonacci_retracement_levels_uses_intraday_range() -> None:
    rows = _resolve_fibonacci_retracement_levels(
        spot=23940.0,
        day_high=24000.0,
        day_low=23800.0,
        top_n=3,
    )
    rounded_rows = [(kind, rank, round(level, 1), ratio) for kind, rank, level, ratio in rows]

    assert rounded_rows[:2] == [
        ("resistance", 1, 23952.8, "23.6%"),
        ("resistance", 2, 24000.0, "0.0%"),
    ]
    assert rounded_rows[2:] == [
        ("support", 1, 23923.6, "38.2%"),
        ("support", 2, 23900.0, "50.0%"),
        ("support", 3, 23876.4, "61.8%"),
    ]


def test_resolve_price_structure_levels_uses_existing_session_anchors() -> None:
    rows = _resolve_price_structure_levels(
        spot=23940.0,
        day_open=23850.0,
        day_high=24000.0,
        day_low=23800.0,
        prev_close=23123.0,
        top_n=3,
    )
    rounded_rows = [(kind, rank, round(level, 1), anchor) for kind, rank, level, anchor in rows]

    assert rounded_rows[:1] == [
        ("resistance", 1, 24000.0, "day_high"),
    ]
    assert rounded_rows[1:] == [
        ("support", 1, 23900.0, "range_mid"),
        ("support", 2, 23850.0, "day_open"),
        ("support", 3, 23800.0, "day_low"),
    ]


def _base_payloads():
    trade = {
        "symbol": "NIFTY",
        "trade_status": "WATCHLIST",
        "direction": None,
        "confirmation_status": "NO_DIRECTION",
        "trade_strength": 0,
        "hybrid_move_probability": 0.60,
        "data_quality_status": "CAUTION",
        "provider_health_summary": "WEAK",
        "provider_health_score": 46.0,
        "provider_health_tier": "FRAGILE",
        "data_readiness_score": 46.0,
        "data_confidence_tier": "FRAGILE",
        "score_calibration_segment_key": "direction=CALL|gamma_regime=POSITIVE_GAMMA|vol_regime=VOL_EXPANSION",
        "regime_segment_guard": {"verdict": "CAUTION", "reason": "segment fragile", "sample_size": 14},
        "regime_segment_key": "direction=CALL|gamma_regime=POSITIVE_GAMMA|vol_regime=VOL_EXPANSION",
        "regime_segment_samples": 14,
        "regime_segment_hit_rate_60m": 0.43,
        "regime_segment_avg_60m_bps": 12.0,
        "regime_segment_avg_close_bps": -9.0,
        "regime_segment_avg_tradeability_score": 49.0,
        "historical_outcome_samples": 18,
        "historical_best_horizon": "15m",
        "historical_exit_bias": "TAKE_PROFIT_EARLY",
        "historical_outcome_guard": {"verdict": "CAUTION", "reason": "early alpha decay", "best_horizon": "15m"},
        "portfolio_book_heat_score": 74,
        "portfolio_book_heat_label": "HOT",
        "portfolio_priority_score": 63.0,
        "portfolio_priority_bucket": "MEDIUM_PRIORITY",
        "portfolio_allocation_tier": "TACTICAL",
        "portfolio_capital_fraction_max": 0.15,
        "portfolio_concentration_guard": {
            "verdict": "REDUCE",
            "same_direction_count": 4,
            "recent_signal_count": 5,
            "same_direction_share": 0.8,
            "heat_score": 74,
            "heat_label": "HOT",
        },
        "final_flow_signal": "BULLISH_FLOW",
        "macro_regime": "RISK_OFF",
        "global_risk_state": "RISK_OFF",
        "analytics_usable": True,
        "execution_suggestion_usable": False,
        "tradable_data": {
            "status": "ANALYTICS_ONLY",
            "score": 0.44,
            "reasons": ["crossed_quotes_high"],
        },
        "feature_reliability_weights": {"gamma": 0.92, "surface": 0.38},
        "feature_reliability_status": "CAUTION",
        "feature_reliability_score": 72.5,
        "provider_health": {
            "summary_status": "CAUTION",
            "atm_iv_health": "CAUTION",
            "atm_iv_midpoint": 0.185,
            "atm_iv_vs_vix_consistent": False,
            "iv_parity_health": "GOOD",
            "iv_parity_breach_ratio": 0.05,
            "iv_staleness_health": "GOOD",
            "iv_stale_ratio": 0.08,
            "market_data_readiness_score": 46.0,
            "market_data_readiness_tier": "FRAGILE",
            "market_data_weak_components": ["core_iv", "atm_iv"],
        },
        "scoring_breakdown": {
            "feature_reliability_penalty": -3,
            "chain_confirmation_reliability_weight": 0.62,
            "chain_confirmation_reliability_delta": -2,
            "gamma_vol_reliability_weight": 0.55,
            "gamma_vol_reliability_delta": -3,
            "dealer_pressure_reliability_weight": 0.58,
            "dealer_pressure_reliability_delta": -2,
            "option_efficiency_reliability_weight": 0.60,
            "option_efficiency_reliability_delta": -1,
        },
        "iv_surface_residual_status": "DEGRADED",
        "iv_surface_residual_penalty_score": 7,
        "option_efficiency_status": "UNAVAILABLE_NEUTRALIZED",
        "option_efficiency_reason": "option_efficiency_features_missing",
        "market_data_provenance_status": "CAUTION",
        "market_data_trade_blocking_status": "PASS",
        "requested_option_source": "ZERODHA",
        "option_source": "ZERODHA",
        "spot_source": "YFINANCE_INTRADAY",
        "market_data_source_consistency": "MIXED_SPOT_OPTION_SOURCE",
        "market_data_timestamp_status": "ALIGNED",
        "market_data_provenance_warnings": ["mixed_spot_option_source"],
    }

    market_data_provenance = {
        "status": "CAUTION",
        "trade_blocking_status": "PASS",
        "requested_option_source": "ZERODHA",
        "option_source": "ZERODHA",
        "spot_source": "YFINANCE_INTRADAY",
        "source_consistency": "MIXED_SPOT_OPTION_SOURCE",
        "timestamp_status": "ALIGNED",
        "warnings": ["mixed_spot_option_source"],
        "issues": [],
    }

    result = {
        "symbol": "NIFTY",
        "mode": "LIVE",
        "source": "ZERODHA",
        "market_data_provenance": market_data_provenance,
        "option_chain_rows": 0,
        "option_chain_frame": None,
        "previous_chain_frame": None,
        "premium_baseline_chain_frames": None,
        "premium_baseline_labels": None,
        "premium_baseline_chain_frame": None,
        "zerodha_oi_baseline_chain_frame": None,
    }

    spot_summary = {
        "spot": 23940.0,
        "day_open": 23850.0,
        "day_high": 24000.0,
        "day_low": 23800.0,
        "prev_close": 23123.0,
        "timestamp": "2026-04-08T12:47:40+05:30",
        "lookback_avg_range_pct": 1.7,
        "price_structure_state": {
            "price_structure_vwap": 23925.0,
            "price_structure_vwap_source": "SPOT_SUMMARY_VWAP",
            "spot_vs_vwap_state": "ABOVE_VWAP",
            "spot_vs_vwap_distance_pts": -15.0,
            "spot_vs_vwap_distance_pct": -0.0627,
            "price_structure_twap_proxy": 23910.0,
            "price_structure_twap_proxy_source": "SPOT_HISTORY_TWAP_PROXY",
            "spot_vs_twap_proxy_state": "ABOVE_TWAP_PROXY",
            "spot_vs_twap_proxy_distance_pts": -30.0,
            "spot_vs_twap_proxy_distance_pct": -0.1253,
            "price_structure_range_position_pct": 70.0,
            "nearest_price_structure_anchor_label": "range_mid",
            "nearest_price_structure_anchor_level": 23900.0,
            "nearest_price_structure_anchor_distance_pts": -40.0,
            "nearest_price_structure_anchor_distance_pct": -0.1671,
            "prior_session_ohlc_available": True,
            "prior_session_high": 24100.0,
            "prior_session_low": 23800.0,
            "prior_session_close": 23850.0,
            "prior_session_date": "2026-04-07",
            "prior_session_ohlc_source": "SPOT_SUMMARY_PRIOR_SESSION_OHLC",
            "classic_pivot_available": True,
            "classic_pivot": 23916.6667,
            "cpr_bc": 23950.0,
            "cpr_tc": 23883.3333,
            "cpr_lower": 23883.3333,
            "cpr_upper": 23950.0,
            "cpr_width_pts": 66.6667,
            "cpr_width_pct": 0.2785,
            "pivot_r1": 24033.3333,
            "pivot_s1": 23733.3333,
            "pivot_r2": 24216.6667,
            "pivot_s2": 23616.6667,
            "spot_vs_pivot_state": "ABOVE_PIVOT",
            "spot_vs_pivot_distance_pts": -23.3333,
            "spot_vs_pivot_distance_pct": -0.0975,
            "spot_vs_cpr_state": "INSIDE_CPR",
            "spot_vs_cpr_lower_distance_pts": -56.6667,
            "spot_vs_cpr_lower_distance_pct": -0.2367,
            "spot_vs_cpr_upper_distance_pts": 10.0,
            "spot_vs_cpr_upper_distance_pct": 0.0418,
            "opening_range_5m_status": "COMPLETE",
            "opening_range_5m_row_count": 1,
            "opening_range_5m_sample_quality": "LOW_SAMPLE",
            "opening_range_5m_low": 23875.0,
            "opening_range_5m_high": 23875.0,
            "opening_range_5m_width_pts": 0.0,
            "opening_range_5m_state": "ABOVE_OPENING_RANGE",
            "opening_range_15m_status": "COMPLETE",
            "opening_range_15m_row_count": 4,
            "opening_range_15m_sample_quality": "OK",
            "opening_range_15m_low": 23800.0,
            "opening_range_15m_high": 23920.0,
            "opening_range_15m_width_pts": 120.0,
            "opening_range_15m_state": "ABOVE_OPENING_RANGE",
            "opening_range_30m_status": "COMPLETE",
            "opening_range_30m_row_count": 8,
            "opening_range_30m_sample_quality": "OK",
            "opening_range_30m_low": 23800.0,
            "opening_range_30m_high": 23950.0,
            "opening_range_30m_width_pts": 150.0,
            "opening_range_30m_state": "INSIDE_OPENING_RANGE",
        },
    }

    spot_validation = {
        "validation_mode": "LIVE",
        "is_valid": True,
        "live_trading_valid": True,
        "replay_analysis_valid": True,
        "is_stale": False,
        "age_minutes": 0,
        "issues": [],
        "warnings": [],
        "market_data_provenance": market_data_provenance,
    }
    option_chain_validation = {
        "validation_mode": "LIVE",
        "is_valid": True,
        "live_trading_valid": True,
        "replay_analysis_valid": True,
        "is_stale": False,
        "age_minutes": 0,
        "issues": [],
        "warnings": [],
    }
    macro_event_state = {
        "macro_event_risk_score": 0,
        "event_window_status": "NONE",
        "event_lockdown_flag": False,
        "minutes_to_next_event": None,
        "next_event_name": None,
    }
    macro_news_state = {
        "macro_regime": "RISK_OFF",
        "macro_sentiment_score": -0.2,
        "volatility_shock_score": 0.1,
        "news_confidence_score": 0.7,
        "macro_regime_reasons": ["test"],
        "headline_velocity": 0.0,
        "headline_count": 0,
        "classified_headline_count": 0,
        "next_event_name": None,
        "neutral_fallback": False,
    }
    global_risk_state = {
        "global_risk_state": "RISK_OFF",
        "global_risk_score": 16,
        "global_risk_adjustment_score": -8,
        "overnight_hold_allowed": False,
        "overnight_gap_risk_score": 72,
        "volatility_expansion_risk_score": 61,
        "overnight_hold_reason": "risk_off",
        "overnight_risk_penalty": -5,
        "global_risk_reasons": ["test"],
    }
    global_market_snapshot = {
        "provider": "TEST",
        "data_available": True,
        "stale": False,
        "warnings": [],
        "market_inputs": {
            "oil_change_24h": 0.0,
            "vix_change_24h": 0.0,
            "india_vix_level": 0.0,
            "india_vix_change_24h": 0.0,
            "dxy_change_24h": 0.1,
            "gift_nifty_change_24h": -0.2,
            "sp500_change_24h": 0.0,
            "us10y_change_bp": 0.0,
            "usdinr_change_24h": 0.0,
            "fii_cash_net": -1200.5,
            "dii_cash_net": 980.25,
            "fii_index_futures_net": -315.0,
            "fii_index_options_net": 144.0,
            "institutional_flow_date": "2026-04-07",
            "institutional_flow_source": "TEST",
            "institutional_flow_source_timestamp": "2026-04-07T18:15:00+05:30",
            "institutional_flow_staleness_days": 9,
            "institutional_flow_data_available": False,
            "india_10y_yield": 6.28,
            "india_10y_change_bp": -2.5,
            "india_bond_yield_date": "2026-04-05",
            "india_bond_yield_source": "TEST_BOND",
            "india_bond_yield_source_timestamp": "2026-04-05T18:15:00+05:30",
            "india_bond_yield_staleness_days": 11,
            "india_bond_yield_data_available": False,
        },
        "institutional_flow_snapshot": {
            "data_available": False,
            "stale": True,
            "warnings": ["institutional_flow_stale:9d"],
        },
        "india_bond_yield_snapshot": {
            "data_available": False,
            "stale": True,
            "warnings": ["india_bond_yield_stale:11d"],
        },
    }
    headline_state = {
        "provider_name": "TEST",
        "data_available": True,
        "is_stale": False,
        "warnings": [],
        "issues": [],
        "provider_metadata": {},
    }

    return {
        "trade": trade,
        "result": result,
        "spot_summary": spot_summary,
        "spot_validation": spot_validation,
        "option_chain_validation": option_chain_validation,
        "macro_event_state": macro_event_state,
        "macro_news_state": macro_news_state,
        "global_risk_state": global_risk_state,
        "global_market_snapshot": global_market_snapshot,
        "headline_state": headline_state,
    }


def test_standard_mode_renders_confidence_note_and_consistency_check() -> None:
    payload = _base_payloads()
    with StringIO() as buffer, redirect_stdout(buffer):
        render_snapshot(
            "STANDARD",
            result=payload["result"],
            spot_summary=payload["spot_summary"],
            spot_validation=payload["spot_validation"],
            option_chain_validation=payload["option_chain_validation"],
            macro_event_state=payload["macro_event_state"],
            macro_news_state=payload["macro_news_state"],
            global_risk_state=payload["global_risk_state"],
            global_market_snapshot=payload["global_market_snapshot"],
            headline_state=payload["headline_state"],
            trade=payload["trade"],
            execution_trade=None,
        )
        output = buffer.getvalue()

    assert "SIGNAL CONFIDENCE" in output
    assert "DATA USABILITY" in output
    assert "RELIABILITY DAMPING" in output
    assert "chain_confirm_delta" in output
    assert "atm_iv_health" in output
    assert "iv_parity_health" in output
    assert "execution_suggestion_usable" in output
    assert "data_readiness_score" in output
    assert "data_confidence_tier" in output
    assert "historical_outcome_samples" in output
    assert "historical_outcome_guard" in output
    assert "regime_segment_guard" in output
    assert "regime_segment_key" in output
    assert "MARKET DATA PROVENANCE" in output
    assert "requested_option_source" in output
    assert "MIXED_SPOT_OPTION_SOURCE" in output
    assert "portfolio_book_heat" in output
    assert "portfolio_priority" in output
    assert "confidence_note" in output
    assert "CONSISTENCY CHECK" in output
    assert "FLOW_MACRO_REGIME_CONTRADICTION" not in output
    assert "bullish flow signal (BULLISH_FLOW) conflicts with RISK_OFF macro/global regime" in output
    assert "GLOBAL MACRO SNAPSHOT" in output
    assert "fii_cash_net" in output


def test_full_debug_mode_renders_confidence_note_and_consistency_check() -> None:
    payload = _base_payloads()
    with StringIO() as buffer, redirect_stdout(buffer):
        render_snapshot(
            "FULL_DEBUG",
            result=payload["result"],
            spot_summary=payload["spot_summary"],
            spot_validation=payload["spot_validation"],
            option_chain_validation=payload["option_chain_validation"],
            macro_event_state=payload["macro_event_state"],
            macro_news_state=payload["macro_news_state"],
            global_risk_state=payload["global_risk_state"],
            global_market_snapshot=payload["global_market_snapshot"],
            headline_state=payload["headline_state"],
            trade=payload["trade"],
            execution_trade=None,
        )
        output = buffer.getvalue()

    assert "SIGNAL CONFIDENCE" in output
    assert "DATA USABILITY" in output
    assert "data_readiness_score" in output
    assert "historical_outcome_guard" in output
    assert "regime_segment_guard" in output
    assert "MARKET DATA PROVENANCE" in output
    assert "requested_option_source" in output
    assert "MIXED_SPOT_OPTION_SOURCE" in output
    assert "portfolio_book_heat" in output
    assert "portfolio_priority" in output
    assert "RELIABILITY DAMPING" in output
    assert "gamma_vol_delta" in output
    assert "atm_iv_health" in output
    assert "iv_staleness_health" in output
    assert "iv_surface_residual_penalty_score" in output
    assert "confidence_note" in output
    assert "CONSISTENCY CHECK" in output
    assert "bullish flow signal (BULLISH_FLOW) conflicts with RISK_OFF macro/global regime" in output
    assert "institutional_flow_date" in output


def test_compact_mode_uses_bias_and_execution_suggestion_wording() -> None:
    payload = _base_payloads()
    payload["trade"].update(
        {
            "decision_classification": "BLOCKED_SETUP",
            "trade_status": "BLOCKED_SETUP",
            "direction": "PUT",
            "direction_source": "FLOW+MICROSTRUCTURE_FRICTION",
            "confirmation_status": "NO_DIRECTION",
            "no_trade_reason": "Provider health is blocking execution",
            "blocked_by": ["provider_health"],
            "iv_hv_regime": "IV_RICH",
        }
    )

    with StringIO() as buffer, redirect_stdout(buffer):
        render_snapshot(
            "COMPACT",
            result=payload["result"],
            spot_summary=payload["spot_summary"],
            spot_validation=payload["spot_validation"],
            option_chain_validation=payload["option_chain_validation"],
            macro_event_state=payload["macro_event_state"],
            macro_news_state=payload["macro_news_state"],
            global_risk_state=payload["global_risk_state"],
            global_market_snapshot=payload["global_market_snapshot"],
            headline_state=payload["headline_state"],
            trade=payload["trade"],
            execution_trade=None,
        )
        output = buffer.getvalue()

    assert "direction_bias" in output
    assert "requested_option_source" in output
    assert "source_consistency" in output
    assert "execution_suggestion_usable" in output
    assert "iv_hv_regime" in output
    assert "GLOBAL MACRO SNAPSHOT" in output
    assert "crude_24h" in output
    assert "FIBONACCI RETRACEMENT" in output
    assert "23.6%" in output
    assert "38.2%" in output
    assert "PRICE STRUCTURE LEVELS" in output
    assert "range_mid" in output
    assert "day_open" in output
    assert "PRICE STRUCTURE CONTEXT" in output
    assert "ABOVE_VWAP" in output
    assert "classic_pivot" in output
    assert "cpr_band" in output
    assert "pivot_levels" in output
    assert "opening_range_5m" in output
    assert "LOW_SAMPLE n=1" in output
    assert "level_confluence" in output
    assert "acceptance_proxy" in output
    assert "day_type_proxy" in output
    assert "STALE 2026-04-05 via TEST_BOND (11d lag; research only)" in output
    assert "6.28% (-2.5bp) [STALE]" in output
    assert "STALE 2026-04-07 via TEST (9d lag; research only)" in output
    assert "-1,200.50 [STALE]" in output
    assert "MICROSTRUCTURE_FRICTION" not in output

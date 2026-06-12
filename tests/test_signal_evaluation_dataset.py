from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import tempfile
import unittest
import warnings
from pathlib import Path

import pandas as pd

from research.signal_evaluation.dataset import ensure_signals_dataset_exists, load_signals_dataset
from research.signal_evaluation.dataset import upsert_signal_rows
from research.signal_evaluation.dataset import write_signals_dataset
from research.signal_evaluation.evaluator import (
    apply_label_quality_fields,
    build_signal_evaluation_row,
    build_regime_fingerprint,
    evaluate_signal_outcomes,
    save_signal_evaluation,
    update_signal_dataset_outcomes,
)
from research.signal_evaluation.market_data import _stitch_saved_spot_snapshots
from research.signal_evaluation.policy import (
    CAPTURE_POLICY_ACTIONABLE,
    CAPTURE_POLICY_ALL,
    CAPTURE_POLICY_TRADE_ONLY,
    normalize_capture_policy,
    should_capture_signal,
)
from tuning.runtime import temporary_parameter_pack


class SignalEvaluationDatasetTests(unittest.TestCase):
    def _sample_result(self):
        return {
            "source": "NSE",
            "mode": "LIVE",
            "symbol": "NIFTY",
            "spot_summary": {
                "spot": 22000.0,
                "day_open": 21940.0,
                "day_high": 22050.0,
                "day_low": 21910.0,
                "prev_close": 21900.0,
                "timestamp": "2026-03-14T10:00:00+05:30",
                "lookback_avg_range_pct": 0.92,
                "ticker": "^NSEI",
                "price_structure_state": {
                    "price_structure_vwap": 21980.0,
                    "price_structure_vwap_source": "SPOT_SUMMARY_VWAP",
                    "price_structure_twap_proxy": 21970.0,
                    "price_structure_twap_proxy_source": "SPOT_HISTORY_TWAP_PROXY",
                    "spot_vs_vwap_state": "ABOVE_VWAP",
                    "spot_vs_vwap_distance_pts": -20.0,
                    "spot_vs_vwap_distance_pct": -0.0909,
                    "spot_vs_twap_proxy_state": "ABOVE_TWAP_PROXY",
                    "spot_vs_twap_proxy_distance_pts": -30.0,
                    "spot_vs_twap_proxy_distance_pct": -0.1364,
                    "price_structure_range_position_pct": 64.2857,
                    "nearest_price_structure_anchor_label": "range_mid",
                    "nearest_price_structure_anchor_side": "support",
                    "nearest_price_structure_anchor_level": 21980.0,
                    "nearest_price_structure_anchor_distance_pts": -20.0,
                    "nearest_price_structure_anchor_distance_pct": -0.0909,
                    "prior_session_ohlc_available": True,
                    "prior_session_high": 22100.0,
                    "prior_session_low": 21800.0,
                    "prior_session_close": 21850.0,
                    "prior_session_date": "2026-03-13",
                    "prior_session_ohlc_source": "SPOT_SUMMARY_PRIOR_SESSION_OHLC",
                    "classic_pivot_available": True,
                    "classic_pivot": 21916.6667,
                    "cpr_bc": 21950.0,
                    "cpr_tc": 21883.3333,
                    "cpr_lower": 21883.3333,
                    "cpr_upper": 21950.0,
                    "cpr_width_pts": 66.6667,
                    "cpr_width_pct": 0.303,
                    "pivot_r1": 22033.3333,
                    "pivot_s1": 21733.3333,
                    "pivot_r2": 22216.6667,
                    "pivot_s2": 21616.6667,
                    "spot_vs_pivot_state": "ABOVE_PIVOT",
                    "spot_vs_pivot_distance_pts": -83.3333,
                    "spot_vs_pivot_distance_pct": -0.3788,
                    "spot_vs_cpr_state": "ABOVE_CPR",
                    "spot_vs_cpr_lower_distance_pts": -116.6667,
                    "spot_vs_cpr_lower_distance_pct": -0.5303,
                    "spot_vs_cpr_upper_distance_pts": -50.0,
                    "spot_vs_cpr_upper_distance_pct": -0.2273,
                    "opening_range_5m_status": "COMPLETE",
                    "opening_range_5m_row_count": 1,
                    "opening_range_5m_sample_quality": "LOW_SAMPLE",
                    "opening_range_5m_high": 21990.0,
                    "opening_range_5m_low": 21935.0,
                    "opening_range_5m_width_pts": 55.0,
                    "opening_range_5m_state": "ABOVE_OPENING_RANGE",
                    "opening_range_15m_status": "COMPLETE",
                    "opening_range_15m_row_count": 4,
                    "opening_range_15m_sample_quality": "OK",
                    "opening_range_15m_high": 22010.0,
                    "opening_range_15m_low": 21930.0,
                    "opening_range_15m_width_pts": 80.0,
                    "opening_range_15m_state": "INSIDE_OPENING_RANGE",
                    "opening_range_30m_status": "COMPLETE",
                    "opening_range_30m_row_count": 8,
                    "opening_range_30m_sample_quality": "OK",
                    "opening_range_30m_high": 22025.0,
                    "opening_range_30m_low": 21920.0,
                    "opening_range_30m_width_pts": 105.0,
                    "opening_range_30m_state": "INSIDE_OPENING_RANGE",
                },
            },
            "saved_paths": {
                "spot": "debug_samples/spot.json",
                "chain": "debug_samples/chain.csv",
            },
            "option_chain_validation": {
                "is_valid": True,
                "is_stale": False,
                "analytics_usable": True,
                "execution_suggestion_usable": False,
                "warnings": ["market_data_provenance:mixed_spot_option_source"],
                "issues": [],
                "tradable_data": {
                    "status": "ANALYTICS_ONLY",
                    "score": 0.44,
                    "reasons": ["wide_spread"],
                },
                "market_data_provenance": {
                    "status": "CAUTION",
                    "trade_blocking_status": "PASS",
                    "requested_option_source": "ICICI",
                    "option_source": "ICICI",
                    "spot_source": "YFINANCE_INTRADAY",
                    "source_consistency": "MIXED_SPOT_OPTION_SOURCE",
                    "timestamp_status": "ALIGNED",
                    "timestamp_delta_seconds": 30.0,
                    "warnings": ["mixed_spot_option_source"],
                    "issues": [],
                    "reasons": ["mixed_spot_option_source"],
                },
                "provider_health": {
                    "summary_status": "GOOD",
                    "row_health": "GOOD",
                    "pricing_health": "GOOD",
                    "pairing_health": "GOOD",
                    "iv_health": "CAUTION",
                    "duplicate_health": "GOOD",
                }
            },
            "trade": {
                "selected_expiry": "2026-03-26",
                "direction": "CALL",
                "option_type": "CE",
                "strike": 22000,
                "entry_price": 110.5,
                "selected_option_last_price": 110.5,
                "selected_option_bid_price": 110.0,
                "selected_option_ask_price": 111.0,
                "selected_option_mid_price": 110.5,
                "selected_option_volume": 138212815,
                "selected_option_open_interest": 8704150,
                "selected_option_iv": 55.79,
                "selected_option_iv_is_proxy": False,
                "selected_option_delta": 0.4735,
                "selected_option_delta_is_proxy": False,
                "selected_option_gamma": 0.0124,
                "selected_option_theta": -0.084,
                "selected_option_vega": 0.221,
                "selected_option_vanna": 0.013,
                "selected_option_charm": -0.009,
                "heston_research_enabled": True,
                "heston_calibration_status": "CALIBRATED",
                "heston_calibration_reason": "ok",
                "heston_calibration_sample_size": 48,
                "heston_kappa": 1.72,
                "heston_theta": 0.052,
                "heston_vol_of_vol": 0.61,
                "heston_rho": -0.43,
                "heston_v0": 0.048,
                "heston_calibration_error": 0.071,
                "heston_surface_quality": "GOOD",
                "heston_quality_flags": "",
                "heston_bound_hit_count": 0,
                "heston_tte_days": 5.25,
                "heston_tte_bucket": "FRONT_WEEK",
                "heston_expiry_context": "NON_EXPIRY",
                "heston_short_tte_guard": "NONE",
                "heston_selected_iv_quality": "OK",
                "heston_skew_state": "NEGATIVE_SKEW",
                "heston_forward_variance_proxy": 0.0486,
                "heston_model_price": 112.4,
                "heston_model_delta": 0.481,
                "heston_model_gamma": 0.0121,
                "heston_model_iv_proxy": 0.301,
                "bs_model_price_for_heston": 110.2,
                "bs_vs_heston_price_gap": 2.2,
                "heston_price_gap_rel_pct": 1.9964,
                "bs_vs_heston_greek_gap": 0.0075,
                "greek_model_divergence_score": 14,
                "heston_diagnostics_json": '{"surface_quality": "GOOD"}',
                "selected_option_capital_per_lot": 13685.75,
                "selected_option_ba_spread_ratio": 0.012,
                "selected_option_ba_spread_pct": 1.2,
                "selected_option_score": 27.81,
                "target": 143.65,
                "stop_loss": 93.93,
                "underlying_profit_booking_level": 22072.0,
                "underlying_profit_booking_lower": 22060.0,
                "underlying_profit_booking_upper": 22086.0,
                "underlying_stop_loss_level": 21965.0,
                "underlying_stop_loss_lower": 21952.0,
                "underlying_stop_loss_upper": 21978.0,
                "underlying_exit_plan_confidence": "HIGH",
                "underlying_exit_plan_basis": "DELTA_PROJECTED_OPTION_EXIT+MARKET_STRUCTURE+EXPECTED_MOVE_CAPPED",
                "underlying_exit_plan_reasons": ["profit_zone_blended_with_nearby_market_structure"],
                "underlying_exit_plan": {
                    "direction": "CALL",
                    "spot": 22000.0,
                    "profit_booking": {"level": 22072.0, "lower": 22060.0, "upper": 22086.0},
                    "stop_loss": {"level": 21965.0, "lower": 21952.0, "upper": 21978.0},
                    "confidence": "HIGH",
                },
                "trade_strength": 81,
                "runtime_composite_score": 86,
                "runtime_composite_components": {
                    "method": "runtime_composite_v1",
                    "pre_adjust_score": 88,
                    "components": {
                        "trade_strength": {"score": 81, "weight": 0.55, "weighted_contribution": 44.55},
                        "move_probability": {"score": 72, "weight": 0.15, "weighted_contribution": 10.8},
                    },
                    "final_score": 86,
                },
                "runtime_composite_observation_tier": "OVERRIDE_85_PLUS",
                "runtime_composite_observation_threshold": 80,
                "runtime_composite_soft_override_threshold": 85,
                "runtime_composite_soft_override_applied": True,
                "runtime_composite_soft_override_mode": "HIGH_RUNTIME_COMPOSITE_SOFT_BLOCK",
                "runtime_composite_soft_override_blockers": ["GLOBAL_RISK_WATCHLIST"],
                "runtime_composite_soft_override_reason": "GLOBAL_RISK_WATCHLIST:runtime_composite_score 86 >= 85",
                "runtime_composite_soft_override_constraints": ["size_cap:0.65", "max_hold_minutes:35", "no_overnight"],
                "runtime_composite_soft_override_original_status": "WATCHLIST",
                "runtime_composite_soft_override_original_reason_code": "GLOBAL_RISK_WATCHLIST",
                "runtime_composite_soft_override_original_message": "Trade downgraded to watchlist due to global risk reduction",
                "runtime_composite_soft_override_diagnostics": {
                    "GLOBAL_RISK_WATCHLIST": {"eligible": True, "runtime_composite_score": 86}
                },
                "effective_min_trade_strength_threshold": 62,
                "effective_min_composite_score_threshold": 58,
                "signal_quality": "STRONG",
                "signal_regime": "EXPANSION_BIAS",
                "execution_regime": "ACTIVE",
                "provider_quality_mode": "ANALYTICS_ONLY_EXECUTION_BLOCKED",
                "provider_analytics_status": "USABLE",
                "provider_execution_status": "BLOCKED",
                "provider_direction_trust": "TRUST_PROVIDER_ANALYTICS",
                "provider_execution_trust": "DO_NOT_TRADE_EXECUTION_QUOTES",
                "provider_quality_action": "OBSERVE_SIGNAL_DO_NOT_EXECUTE",
                "provider_quality_note": "Direction analytics are usable, but execution quotes/tradable data are not reliable enough to trade.",
                "provider_quality_blocks_direction": False,
                "provider_quality_blocks_execution": True,
                "provider_quality_reasons": ["wide_spread"],
                "trade_status": "TRADE",
                "direction_source": "FLOW+HEDGING_BIAS",
                "final_flow_signal": "BULLISH_FLOW",
                "gamma_regime": "SHORT_GAMMA_ZONE",
                "spot_vs_flip": "ABOVE_FLIP",
                "gamma_flip": 21980.0,
                "gamma_flip_drift": {"drift": 18.0, "direction": "RISING"},
                "support_wall": 21950.0,
                "resistance_wall": 22100.0,
                "max_pain": 22050.0,
                "max_pain_dist": 50.0,
                "max_pain_zone": "NEAR_MAX_PAIN",
                "liquidity_levels": [21950.0, 22050.0, 22100.0],
                "gamma_clusters": [21980.0, 22120.0],
                "dealer_liquidity_map": {"next_support": 21950.0, "next_resistance": 22100.0},
                "macro_regime": "MACRO_NEUTRAL",
                "global_risk_state": "GLOBAL_NEUTRAL",
                "global_risk_score": 24,
                "global_risk_state_score": 16,
                "global_risk_overlay_score": 24,
                "global_risk_diagnostics": {
                    "dominant_risk_driver": "risk_off_pressure",
                    "regime_score": 0.28,
                    "risk_off_pressure": 0.31,
                    "risk_on_support": 0.03,
                    "component_contributions": {
                        "risk_off_pressure": 16.12,
                        "macro_regime_risk_off_bonus": 0.0,
                        "volatility_expansion_risk": 4.2,
                    },
                },
                "gamma_vol_acceleration_score": 68,
                "squeeze_risk_state": "HIGH_ACCELERATION_RISK",
                "directional_convexity_state": "UPSIDE_SQUEEZE_RISK",
                "upside_squeeze_risk": 0.74,
                "downside_airpocket_risk": 0.41,
                "overnight_convexity_risk": 0.52,
                "gamma_vol_adjustment_score": 4,
                "dealer_hedging_pressure_score": 66,
                "dealer_flow_state": "UPSIDE_HEDGING_ACCELERATION",
                "upside_hedging_pressure": 0.81,
                "downside_hedging_pressure": 0.32,
                "pinning_pressure_score": 0.18,
                "dealer_pressure_adjustment_score": 3,
                "expected_move_points": 165.4,
                "expected_move_pct": 0.7518,
                "open_interest_pcr": 1.42,
                "volume_pcr": 1.18,
                "volume_pcr_atm": 1.25,
                "volume_pcr_regime": "PUT_DOMINANT",
                "target_reachability_score": 78,
                "premium_efficiency_score": 74,
                "strike_efficiency_score": 78,
                "option_efficiency_score": 77,
                "option_efficiency_adjustment_score": 4,
                "consistency_check_status": "PASS",
                "consistency_check_issue_count": 0,
                "consistency_check_critical_issue_count": 0,
                "consistency_check_escalated": False,
                "consistency_check_findings": [],
                "oil_shock_score": 0.7,
                "commodity_risk_score": 0.53,
                "market_volatility_shock_score": 0.7,
                "volatility_explosion_probability": 0.45,
                "dealer_position": "Short Gamma",
                "dealer_hedging_bias": "UPSIDE_ACCELERATION",
                "dealer_hedging_flow": 0.63,
                "delta_exposure": 142500.0,
                "gamma_exposure_greeks": -8420.0,
                "theta_exposure": -315.0,
                "vega_exposure": 2240.0,
                "vanna_exposure": 190.0,
                "charm_exposure": -44.0,
                "volatility_regime": "VOL_EXPANSION",
                "liquidity_vacuum_state": "BREAKOUT_ZONE",
                "confirmation_status": "CONFIRMED",
                "macro_event_risk_score": 12,
                "data_quality_score": 88,
                "data_quality_status": "STRONG",
                "rule_move_probability": 0.61,
                "hybrid_move_probability": 0.72,
                "ml_move_probability": 0.68,
                "large_move_probability": 0.72,
                "historical_context": {
                    "version": "historical_context_v1",
                    "decision_mode": "LIVE_APPLIED",
                    "prior_artifact_version": "historical_prior_artifact_v1",
                    "prior_artifact_source_run_id": "20260518_113042",
                    "apply_to_live_decision": True,
                    "volatility_context": {
                        "bucket": "HIGH",
                        "expected_range_bps": 262.25,
                        "expected_abs_move_bps": 156.72,
                        "range_multiplier": 1.826,
                    },
                    "global_directional_prior": {
                        "prior_direction": "PUT",
                        "prior_score": -2.75,
                        "evidence": [
                            {"feature": "sp500_change_24h", "direction": "PUT"},
                            {"feature": "us_vix_change_24h", "direction": "PUT"},
                        ],
                    },
                    "pcr_context": {
                        "state": "HIGH_PCR",
                        "value": 1.42,
                        "basis": "OPEN_INTEREST",
                        "interpretation": "support_or_pinning_context_not_automatic_bearish_signal",
                    },
                    "interaction_context": {
                        "matched_count": 2,
                        "bucket_state": {
                            "expiry_bucket": "2-3d",
                            "pcr_oi_bucket": "high",
                            "pcr_basis": "OPEN_INTEREST",
                            "india_vix_bucket": "high",
                            "trend_20d_bucket": "selloff",
                            "weekday": "Monday",
                        },
                        "score_adjustment": 3,
                        "probability_adjustment": 0.02,
                        "reasons": ["expiry_x_pcr_aligned_call", "high_range_weekday_vix_interaction"],
                    },
                    "max_pain_context": {
                        "state": "NEAR_MAX_PAIN",
                        "interpretation": "pinning_or_friction_context_only",
                    },
                    "wall_context": {
                        "state": "NEAR_RESISTANCE_WALL",
                        "interpretation": "walls_are_friction_and_breakout_context_not_hard_reversal_levels",
                    },
                    "live_modifiers": {
                        "applied": True,
                        "score_adjustment": -6,
                        "probability_adjustment": -0.025,
                        "trade_strength_threshold_adjustment": 4,
                        "composite_threshold_adjustment": 2,
                        "size_multiplier": 0.75,
                        "direction_override": None,
                        "reasons": ["historical_global_prior_conflict"],
                    },
                    "score_adjustment_preview": -8,
                    "probability_adjustment_preview": -0.0413,
                    "score_adjustment": -6,
                    "probability_adjustment": -0.025,
                    "trade_strength_threshold_adjustment": 4,
                    "composite_threshold_adjustment": 2,
                    "size_multiplier": 0.75,
                    "direction_override": None,
                    "primary_notes": ["vol_bucket=HIGH", "global_prior=PUT:-2.75"],
                },
                "signal_confidence_score": 68.5,
                "signal_confidence_level": "MODERATE",
                "signal_confidence_calibration_status": "CAUTION",
                "signal_confidence_calibration_sample_size": 18,
                "signal_confidence_calibration_regime_match": "PARTIAL",
                "signal_confidence_calibration_guardrail": {
                    "status": "CAUTION",
                    "sample_size": 18,
                    "regime_match": "PARTIAL",
                },
                "signal_confidence_recalibration_guards": ["thin_calibration_history"],
                "oil_change_24h": -0.8,
                "us_vix_change_24h": 1.4,
                "us10y_yield": 4.32,
                "us10y_change_bp": 2.5,
                "india_2y_yield": 6.15,
                "india_5y_yield": 6.42,
                "india_10y_yield": 6.78,
                "india_30y_yield": 7.05,
                "india_10y_change_bp": -3.2,
                "india_2y10y_spread_bp": 63.0,
                "india_5y10y_spread_bp": 36.0,
                "india_us_10y_spread_bp": 246.0,
                "india_bond_yield_date": "2026-05-28",
                "india_bond_yield_source": "TEST_BOND",
                "india_bond_yield_source_timestamp": "2026-05-28T18:10:00+05:30",
                "india_bond_yield_staleness_days": 1,
                "india_bond_yield_data_available": True,
                "india_bond_yield_warnings": [],
                "dxy_change_24h": 0.2,
                "usdinr_change_24h": 0.1,
                "gift_nifty_change_24h": -0.35,
                "fii_cash_net": -1200.5,
                "dii_cash_net": 980.25,
                "fii_index_futures_net": -315.0,
                "fii_index_options_net": 144.0,
                "institutional_flow_date": "2026-05-28",
                "institutional_flow_source": "TEST",
                "institutional_flow_source_timestamp": "2026-05-28T18:15:00+05:30",
                "institutional_flow_staleness_days": 1,
                "institutional_flow_data_available": True,
                "institutional_flow_warnings": [],
                "mean_reversion_features": {
                    "mean_reversion_signal": "MEAN_REVERSION",
                    "mean_reversion_zscore": 1.92,
                    "mean_reversion_strength": 24.0,
                    "mean_reversion_distance_pct": 1.17,
                    "mean_reversion_reason": "spot_stretched_vs_recent_history",
                },
            },
        }

    def test_build_row_has_stable_primary_key_and_context(self):
        row_a = build_signal_evaluation_row(self._sample_result())
        row_b = build_signal_evaluation_row(self._sample_result())

        self.assertEqual(row_a["signal_id"], row_b["signal_id"])
        self.assertEqual(row_a["symbol"], "NIFTY")
        self.assertEqual(row_a["selected_option_last_price"], 110.5)
        self.assertEqual(row_a["selected_option_bid_price"], 110.0)
        self.assertEqual(row_a["selected_option_ask_price"], 111.0)
        self.assertEqual(row_a["gamma_flip"], 21980.0)
        self.assertEqual(row_a["support_wall"], 21950.0)
        self.assertEqual(row_a["support_wall_distance_pts"], -50.0)
        self.assertEqual(row_a["resistance_wall"], 22100.0)
        self.assertEqual(row_a["resistance_wall_distance_pts"], 100.0)
        self.assertEqual(row_a["max_pain"], 22050.0)
        self.assertEqual(row_a["max_pain_distance_pct"], 0.227273)
        self.assertIn("22100.0", row_a["liquidity_levels_json"])
        self.assertIn("next_resistance", row_a["dealer_liquidity_map_json"])
        self.assertEqual(row_a["selected_option_mid_price"], 110.5)
        self.assertEqual(row_a["option_entry_premium"], 110.5)
        self.assertEqual(row_a["option_target_premium"], 143.65)
        self.assertEqual(row_a["option_stop_loss_premium"], 93.93)
        self.assertEqual(row_a["underlying_profit_booking_level"], 22072.0)
        self.assertEqual(row_a["underlying_profit_booking_lower"], 22060.0)
        self.assertEqual(row_a["underlying_profit_booking_upper"], 22086.0)
        self.assertEqual(row_a["underlying_stop_loss_level"], 21965.0)
        self.assertEqual(row_a["underlying_exit_plan_confidence"], "HIGH")
        self.assertEqual(row_a["underlying_exit_plan_reasons"], "profit_zone_blended_with_nearby_market_structure")
        self.assertIn('"profit_booking"', row_a["underlying_exit_plan_json"])
        self.assertAlmostEqual(row_a["option_premium_pct_of_spot"], 0.5023, places=4)
        self.assertEqual(row_a["selected_option_delta"], 0.4735)
        self.assertEqual(row_a["selected_option_gamma"], 0.0124)
        self.assertEqual(row_a["selected_option_charm"], -0.009)
        self.assertEqual(row_a["heston_calibration_status"], "CALIBRATED")
        self.assertEqual(row_a["heston_surface_quality"], "GOOD")
        self.assertEqual(row_a["heston_quality_flags"], "")
        self.assertEqual(row_a["heston_bound_hit_count"], 0)
        self.assertEqual(row_a["heston_tte_bucket"], "FRONT_WEEK")
        self.assertEqual(row_a["heston_selected_iv_quality"], "OK")
        self.assertEqual(row_a["heston_skew_state"], "NEGATIVE_SKEW")
        self.assertAlmostEqual(row_a["heston_calibration_error"], 0.071)
        self.assertAlmostEqual(row_a["heston_price_gap_rel_pct"], 1.9964)
        self.assertEqual(row_a["greek_model_divergence_score"], 14)
        self.assertEqual(row_a["market_gamma_exposure"], -8420.0)
        self.assertEqual(row_a["market_charm_exposure"], -44.0)
        self.assertAlmostEqual(row_a["target_premium_return_pct"], 30.0, places=4)
        self.assertAlmostEqual(row_a["stop_loss_premium_return_pct"], -14.9955, places=4)
        self.assertEqual(row_a["provider_health_status"], "GOOD")
        self.assertEqual(row_a["requested_option_source"], "ICICI")
        self.assertIn('"pre_adjust_score": 88', row_a["runtime_composite_components"])
        self.assertEqual(row_a["option_source"], "ICICI")
        self.assertEqual(row_a["spot_source"], "YFINANCE_INTRADAY")
        self.assertEqual(row_a["market_data_source_consistency"], "MIXED_SPOT_OPTION_SOURCE")
        self.assertEqual(row_a["market_data_provenance_status"], "CAUTION")
        self.assertEqual(row_a["market_data_timestamp_status"], "ALIGNED")
        self.assertEqual(row_a["market_data_provenance_reasons"], "mixed_spot_option_source")
        self.assertEqual(row_a["option_chain_validation_status"], "GOOD")
        self.assertEqual(row_a["option_chain_is_valid"], True)
        self.assertEqual(row_a["option_chain_warning_count"], 1)
        self.assertEqual(row_a["runtime_composite_score"], 86)
        self.assertEqual(row_a["runtime_composite_observation_tier"], "OVERRIDE_85_PLUS")
        self.assertEqual(row_a["runtime_composite_soft_override_applied"], True)
        self.assertEqual(row_a["runtime_composite_soft_override_mode"], "HIGH_RUNTIME_COMPOSITE_SOFT_BLOCK")
        self.assertEqual(row_a["runtime_composite_soft_override_blockers"], "GLOBAL_RISK_WATCHLIST")
        self.assertEqual(row_a["runtime_composite_soft_override_constraints"], "size_cap:0.65|max_hold_minutes:35|no_overnight")
        self.assertEqual(row_a["runtime_composite_soft_override_original_status"], "WATCHLIST")
        self.assertIn('"runtime_composite_score": 86', row_a["runtime_composite_soft_override_diagnostics"])
        self.assertEqual(row_a["effective_min_composite_score_threshold"], 58)
        self.assertEqual(row_a["analytics_usable"], True)
        self.assertEqual(row_a["execution_suggestion_usable"], False)
        self.assertEqual(row_a["provider_quality_mode"], "ANALYTICS_ONLY_EXECUTION_BLOCKED")
        self.assertEqual(row_a["provider_direction_trust"], "TRUST_PROVIDER_ANALYTICS")
        self.assertEqual(row_a["provider_execution_trust"], "DO_NOT_TRADE_EXECUTION_QUOTES")
        self.assertEqual(row_a["provider_quality_action"], "OBSERVE_SIGNAL_DO_NOT_EXECUTE")
        self.assertEqual(row_a["provider_quality_blocks_direction"], False)
        self.assertEqual(row_a["provider_quality_blocks_execution"], True)
        self.assertEqual(row_a["provider_quality_reasons"], "wide_spread")
        self.assertEqual(row_a["tradable_data_status"], "ANALYTICS_ONLY")
        self.assertEqual(row_a["signal_confidence_score"], 68.5)
        self.assertEqual(row_a["signal_confidence_level"], "MODERATE")
        self.assertEqual(row_a["signal_confidence_calibration_status"], "CAUTION")
        self.assertEqual(row_a["signal_confidence_calibration_guardrail_status"], "CAUTION")
        self.assertEqual(row_a["signal_confidence_recalibration_guards"], "thin_calibration_history")
        self.assertAlmostEqual(row_a["price_structure_vwap"], 21980.0)
        self.assertEqual(row_a["price_structure_vwap_source"], "SPOT_SUMMARY_VWAP")
        self.assertAlmostEqual(row_a["price_structure_twap_proxy"], 21970.0)
        self.assertEqual(row_a["spot_vs_vwap_state"], "ABOVE_VWAP")
        self.assertEqual(row_a["spot_vs_twap_proxy_state"], "ABOVE_TWAP_PROXY")
        self.assertAlmostEqual(row_a["price_structure_range_position_pct"], 64.2857)
        self.assertEqual(row_a["nearest_price_structure_anchor_label"], "range_mid")
        self.assertAlmostEqual(row_a["nearest_price_structure_anchor_level"], 21980.0)
        self.assertEqual(row_a["prior_session_ohlc_available"], True)
        self.assertAlmostEqual(row_a["prior_session_high"], 22100.0)
        self.assertEqual(row_a["prior_session_ohlc_source"], "SPOT_SUMMARY_PRIOR_SESSION_OHLC")
        self.assertAlmostEqual(row_a["classic_pivot"], 21916.6667)
        self.assertAlmostEqual(row_a["cpr_lower"], 21883.3333)
        self.assertAlmostEqual(row_a["cpr_upper"], 21950.0)
        self.assertEqual(row_a["spot_vs_pivot_state"], "ABOVE_PIVOT")
        self.assertEqual(row_a["spot_vs_cpr_state"], "ABOVE_CPR")
        self.assertEqual(row_a["opening_range_5m_status"], "COMPLETE")
        self.assertEqual(row_a["opening_range_5m_row_count"], 1)
        self.assertEqual(row_a["opening_range_5m_sample_quality"], "LOW_SAMPLE")
        self.assertEqual(row_a["opening_range_5m_state"], "ABOVE_OPENING_RANGE")
        self.assertEqual(row_a["opening_range_15m_sample_quality"], "OK")
        self.assertAlmostEqual(row_a["opening_range_15m_width_pts"], 80.0)
        self.assertEqual(row_a["opening_range_30m_row_count"], 8)
        self.assertEqual(row_a["opening_range_30m_state"], "INSIDE_OPENING_RANGE")
        self.assertIn(row_a["price_level_confluence_state"], {"HIGH_CONFLUENCE", "VERY_HIGH_CONFLUENCE"})
        self.assertGreaterEqual(row_a["price_level_confluence_source_count"], 4)
        self.assertIn("dealer_gamma", row_a["nearest_confluence_sources"])
        self.assertIn("vwap", row_a["nearest_confluence_sources"])
        self.assertEqual(row_a["price_structure_acceptance_state"], "BALANCED_ROTATION_CANDIDATE")
        self.assertEqual(row_a["price_structure_day_type_proxy"], "RANGE_DAY_CANDIDATE")
        self.assertAlmostEqual(row_a["oil_change_24h"], -0.8)
        self.assertAlmostEqual(row_a["us_vix_change_24h"], 1.4)
        self.assertAlmostEqual(row_a["us10y_yield"], 4.32)
        self.assertAlmostEqual(row_a["us10y_change_bp"], 2.5)
        self.assertAlmostEqual(row_a["india_2y_yield"], 6.15)
        self.assertAlmostEqual(row_a["india_5y_yield"], 6.42)
        self.assertAlmostEqual(row_a["india_10y_yield"], 6.78)
        self.assertAlmostEqual(row_a["india_30y_yield"], 7.05)
        self.assertAlmostEqual(row_a["india_10y_change_bp"], -3.2)
        self.assertAlmostEqual(row_a["india_2y10y_spread_bp"], 63.0)
        self.assertAlmostEqual(row_a["india_5y10y_spread_bp"], 36.0)
        self.assertAlmostEqual(row_a["india_us_10y_spread_bp"], 246.0)
        self.assertEqual(row_a["india_bond_yield_date"], "2026-05-28")
        self.assertEqual(row_a["india_bond_yield_source"], "TEST_BOND")
        self.assertEqual(row_a["india_bond_yield_source_timestamp"], "2026-05-28T18:10:00+05:30")
        self.assertAlmostEqual(row_a["india_bond_yield_staleness_days"], 1)
        self.assertEqual(row_a["india_bond_yield_data_available"], True)
        self.assertAlmostEqual(row_a["dxy_change_24h"], 0.2)
        self.assertAlmostEqual(row_a["usdinr_change_24h"], 0.1)
        self.assertAlmostEqual(row_a["gift_nifty_change_24h"], -0.35)
        self.assertAlmostEqual(row_a["fii_cash_net"], -1200.5)
        self.assertAlmostEqual(row_a["dii_cash_net"], 980.25)
        self.assertAlmostEqual(row_a["fii_index_futures_net"], -315.0)
        self.assertAlmostEqual(row_a["fii_index_options_net"], 144.0)
        self.assertEqual(row_a["institutional_flow_date"], "2026-05-28")
        self.assertEqual(row_a["institutional_flow_source"], "TEST")
        self.assertEqual(row_a["institutional_flow_source_timestamp"], "2026-05-28T18:15:00+05:30")
        self.assertAlmostEqual(row_a["institutional_flow_staleness_days"], 1)
        self.assertEqual(row_a["institutional_flow_data_available"], True)
        self.assertEqual(row_a["mean_reversion_signal"], "MEAN_REVERSION")
        self.assertAlmostEqual(row_a["mean_reversion_zscore"], 1.92)
        self.assertAlmostEqual(row_a["mean_reversion_strength"], 24.0)
        self.assertAlmostEqual(row_a["mean_reversion_distance_pct"], 1.17)
        self.assertEqual(row_a["mean_reversion_reason"], "spot_stretched_vs_recent_history")
        self.assertEqual(row_a["hybrid_move_probability"], 0.72)
        self.assertEqual(row_a["rule_move_probability"], 0.61)
        self.assertEqual(row_a["label_quality_status"], "PENDING")
        self.assertFalse(row_a["calibration_label_available"])
        self.assertEqual(row_a["calibration_label_horizon"], "60m")
        self.assertEqual(row_a["primary_outcome_horizon"], "60m")
        self.assertIn("outcome_pending", row_a["label_quality_reasons"])
        self.assertEqual(row_a["global_risk_state"], "GLOBAL_NEUTRAL")
        self.assertEqual(row_a["global_risk_score"], 24)
        self.assertEqual(row_a["global_risk_state_score"], 16)
        self.assertEqual(row_a["global_risk_overlay_score"], 24)
        self.assertEqual(row_a["global_risk_dominant_driver"], "risk_off_pressure")
        self.assertAlmostEqual(row_a["global_risk_regime_score"], 0.28)
        self.assertAlmostEqual(row_a["global_risk_risk_off_pressure"], 0.31)
        self.assertAlmostEqual(row_a["global_risk_risk_on_support"], 0.03)
        global_risk_components = json.loads(row_a["global_risk_component_contributions"])
        self.assertAlmostEqual(global_risk_components["risk_off_pressure"], 16.12)
        self.assertIn("macro_regime_risk_off_bonus", global_risk_components)
        self.assertEqual(row_a["gamma_vol_acceleration_score"], 68)
        self.assertEqual(row_a["squeeze_risk_state"], "HIGH_ACCELERATION_RISK")
        self.assertEqual(row_a["directional_convexity_state"], "UPSIDE_SQUEEZE_RISK")
        self.assertEqual(row_a["upside_squeeze_risk"], 0.74)
        self.assertEqual(row_a["downside_airpocket_risk"], 0.41)
        self.assertEqual(row_a["overnight_convexity_risk"], 0.52)
        self.assertEqual(row_a["gamma_vol_adjustment_score"], 4)
        self.assertEqual(row_a["dealer_hedging_pressure_score"], 66)
        self.assertEqual(row_a["dealer_flow_state"], "UPSIDE_HEDGING_ACCELERATION")
        self.assertEqual(row_a["upside_hedging_pressure"], 0.81)
        self.assertEqual(row_a["downside_hedging_pressure"], 0.32)
        self.assertEqual(row_a["pinning_pressure_score"], 0.18)
        self.assertEqual(row_a["dealer_pressure_adjustment_score"], 3)
        self.assertEqual(row_a["expected_move_points"], 165.4)
        self.assertEqual(row_a["expected_move_pct"], 0.7518)
        self.assertEqual(row_a["open_interest_pcr"], 1.42)
        self.assertEqual(row_a["volume_pcr"], 1.18)
        self.assertEqual(row_a["volume_pcr_atm"], 1.25)
        self.assertEqual(row_a["volume_pcr_regime"], "PUT_DOMINANT")
        self.assertEqual(row_a["pcr_value"], 1.42)
        self.assertEqual(row_a["pcr_basis"], "OPEN_INTEREST")
        self.assertEqual(row_a["pcr_bucket"], "HIGH_PCR")
        self.assertEqual(row_a["pcr_data_source"], "LIVE_PAYLOAD")
        self.assertIsNone(row_a["pcr_snapshot_age_seconds"])
        self.assertEqual(row_a["target_reachability_score"], 78)
        self.assertEqual(row_a["premium_efficiency_score"], 74)
        self.assertEqual(row_a["strike_efficiency_score"], 78)
        self.assertEqual(row_a["option_efficiency_score"], 77)
        self.assertEqual(row_a["option_efficiency_adjustment_score"], 4)
        self.assertEqual(row_a["consistency_check_status"], "PASS")
        self.assertEqual(row_a["consistency_check_issue_count"], 0)
        self.assertEqual(row_a["consistency_check_critical_issue_count"], 0)
        self.assertEqual(row_a["consistency_check_escalated"], False)
        self.assertEqual(row_a["oil_shock_score"], 0.7)
        self.assertEqual(row_a["commodity_risk_score"], 0.53)
        self.assertEqual(row_a["volatility_shock_score"], 0.7)
        self.assertEqual(row_a["volatility_explosion_probability"], 0.45)
        self.assertEqual(row_a["historical_context_version"], "historical_context_v1")
        self.assertEqual(row_a["historical_context_mode"], "LIVE_APPLIED")
        self.assertEqual(row_a["historical_prior_artifact_version"], "historical_prior_artifact_v1")
        self.assertEqual(row_a["historical_prior_artifact_source_run_id"], "20260518_113042")
        self.assertEqual(row_a["historical_context_applied"], True)
        self.assertEqual(row_a["historical_volatility_bucket"], "HIGH")
        self.assertEqual(row_a["historical_expected_range_bps"], 262.25)
        self.assertEqual(row_a["historical_global_prior_direction"], "PUT")
        self.assertEqual(row_a["historical_global_prior_score"], -2.75)
        self.assertEqual(row_a["historical_global_prior_evidence"], "sp500_change_24h:PUT|us_vix_change_24h:PUT")
        self.assertEqual(row_a["historical_pcr_state"], "HIGH_PCR")
        self.assertEqual(row_a["historical_context_score_adjustment_preview"], -8)
        self.assertEqual(row_a["historical_context_score_adjustment"], -6)
        self.assertEqual(row_a["historical_context_probability_adjustment"], -0.025)
        self.assertEqual(row_a["historical_context_trade_strength_threshold_adjustment"], 4)
        self.assertEqual(row_a["historical_context_size_multiplier"], 0.75)
        self.assertEqual(row_a["historical_context_reasons"], "historical_global_prior_conflict")
        self.assertEqual(row_a["historical_interaction_count"], 2)
        self.assertEqual(row_a["historical_interaction_score_adjustment"], 3)
        self.assertEqual(row_a["historical_interaction_probability_adjustment"], 0.02)
        self.assertEqual(
            row_a["historical_interaction_reasons"],
            "expiry_x_pcr_aligned_call|high_range_weekday_vix_interaction",
        )
        self.assertIn('"pcr_basis": "OPEN_INTEREST"', row_a["historical_interaction_bucket_state"])
        self.assertTrue(str(row_a["regime_fingerprint"]).startswith("signal_regime="))
        self.assertEqual(len(str(row_a["regime_fingerprint_id"])), 16)
        self.assertEqual(row_a["signal_calibration_bucket"], "80_100")

    def test_build_row_disambiguates_parameter_pack_traceability(self):
        baseline_result = self._sample_result()
        candidate_result = self._sample_result()
        baseline_result["trade"] = dict(baseline_result["trade"])
        candidate_result["trade"] = dict(candidate_result["trade"])
        baseline_result["trade"]["parameter_pack_name"] = "baseline_v1"
        candidate_result["trade"]["parameter_pack_name"] = "candidate_v1"

        baseline_row = build_signal_evaluation_row(baseline_result)
        candidate_row = build_signal_evaluation_row(candidate_result)

        self.assertNotEqual(baseline_row["signal_id"], candidate_row["signal_id"])
        self.assertEqual(baseline_row["parameter_pack_name"], "baseline_v1")
        self.assertEqual(candidate_row["parameter_pack_name"], "candidate_v1")

        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "signals_dataset.csv"
            save_signal_evaluation(baseline_result, dataset_path=dataset_path)
            save_signal_evaluation(candidate_result, dataset_path=dataset_path)

            frame = load_signals_dataset(dataset_path)
            self.assertEqual(len(frame), 2)
            self.assertSetEqual(set(frame["parameter_pack_name"]), {"baseline_v1", "candidate_v1"})

    def test_regime_fingerprint_is_deterministic(self):
        trade = self._sample_result()["trade"]
        provider_health = self._sample_result()["option_chain_validation"]["provider_health"]
        fp_a, fp_id_a = build_regime_fingerprint(trade, provider_health)
        fp_b, fp_id_b = build_regime_fingerprint(trade, provider_health)

        self.assertEqual(fp_a, fp_b)
        self.assertEqual(fp_id_a, fp_id_b)

    def test_dataset_file_is_created_with_headers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "signals_dataset.csv"
            ensure_signals_dataset_exists(dataset_path)

            self.assertTrue(dataset_path.exists())
            frame = load_signals_dataset(dataset_path)
            self.assertIn("signal_id", frame.columns)
            self.assertIn("move_probability", frame.columns)
            self.assertIn("global_risk_state", frame.columns)
            self.assertIn("gamma_vol_acceleration_score", frame.columns)
            self.assertIn("squeeze_risk_state", frame.columns)
            self.assertIn("directional_convexity_state", frame.columns)
            self.assertIn("upside_squeeze_risk", frame.columns)
            self.assertIn("downside_airpocket_risk", frame.columns)
            self.assertIn("overnight_convexity_risk", frame.columns)
            self.assertIn("gamma_vol_adjustment_score", frame.columns)
            self.assertIn("dealer_hedging_pressure_score", frame.columns)
            self.assertIn("dealer_flow_state", frame.columns)
            self.assertIn("upside_hedging_pressure", frame.columns)
            self.assertIn("downside_hedging_pressure", frame.columns)
            self.assertIn("pinning_pressure_score", frame.columns)
            self.assertIn("dealer_pressure_adjustment_score", frame.columns)
            self.assertIn("expected_move_points", frame.columns)
            self.assertIn("expected_move_pct", frame.columns)
            self.assertIn("open_interest_pcr", frame.columns)
            self.assertIn("volume_pcr", frame.columns)
            self.assertIn("volume_pcr_atm", frame.columns)
            self.assertIn("volume_pcr_regime", frame.columns)
            self.assertIn("pcr_value", frame.columns)
            self.assertIn("pcr_basis", frame.columns)
            self.assertIn("pcr_bucket", frame.columns)
            self.assertIn("pcr_data_source", frame.columns)
            self.assertIn("pcr_snapshot_age_seconds", frame.columns)
            self.assertIn("target_reachability_score", frame.columns)
            self.assertIn("premium_efficiency_score", frame.columns)
            self.assertIn("option_entry_premium", frame.columns)
            self.assertIn("option_target_premium", frame.columns)
            self.assertIn("option_stop_loss_premium", frame.columns)
            self.assertIn("option_premium_pct_of_spot", frame.columns)
            self.assertIn("selected_option_bid_price", frame.columns)
            self.assertIn("selected_option_ask_price", frame.columns)
            self.assertIn("selected_option_mid_price", frame.columns)
            self.assertIn("option_premium_path_status", frame.columns)
            self.assertIn("option_premium_60m", frame.columns)
            self.assertIn("option_premium_return_60m_bps", frame.columns)
            self.assertIn("option_premium_pnl_per_lot_60m", frame.columns)
            self.assertIn("selected_option_delta", frame.columns)
            self.assertIn("selected_option_iv", frame.columns)
            self.assertIn("heston_calibration_status", frame.columns)
            self.assertIn("heston_surface_quality", frame.columns)
            self.assertIn("heston_quality_flags", frame.columns)
            self.assertIn("heston_tte_bucket", frame.columns)
            self.assertIn("heston_selected_iv_quality", frame.columns)
            self.assertIn("heston_price_gap_rel_pct", frame.columns)
            self.assertIn("greek_model_divergence_score", frame.columns)
            self.assertIn("market_gamma_exposure", frame.columns)
            self.assertIn("market_charm_exposure", frame.columns)
            self.assertIn("strike_efficiency_score", frame.columns)
            self.assertIn("option_efficiency_score", frame.columns)
            self.assertIn("option_efficiency_adjustment_score", frame.columns)
            self.assertIn("consistency_check_status", frame.columns)
            self.assertIn("consistency_check_issue_count", frame.columns)
            self.assertIn("consistency_check_critical_issue_count", frame.columns)
            self.assertIn("consistency_check_escalated", frame.columns)
            self.assertIn("consistency_check_findings", frame.columns)
            self.assertIn("oil_shock_score", frame.columns)
            self.assertIn("commodity_risk_score", frame.columns)
            self.assertIn("volatility_shock_score", frame.columns)
            self.assertIn("volatility_explosion_probability", frame.columns)
            self.assertIn("historical_context_version", frame.columns)
            self.assertIn("historical_prior_artifact_version", frame.columns)
            self.assertIn("historical_prior_artifact_source_run_id", frame.columns)
            self.assertIn("historical_volatility_bucket", frame.columns)
            self.assertIn("historical_global_prior_direction", frame.columns)
            self.assertIn("historical_context_score_adjustment_preview", frame.columns)
            self.assertIn("historical_context_score_adjustment", frame.columns)
            self.assertIn("historical_context_probability_adjustment", frame.columns)
            self.assertIn("historical_context_size_multiplier", frame.columns)
            self.assertIn("historical_interaction_count", frame.columns)
            self.assertIn("historical_interaction_score_adjustment", frame.columns)
            self.assertIn("historical_interaction_probability_adjustment", frame.columns)
            self.assertIn("historical_interaction_bucket_state", frame.columns)
            self.assertIn("market_data_provenance_status", frame.columns)
            self.assertIn("option_chain_validation_status", frame.columns)
            self.assertIn("signal_confidence_calibration_status", frame.columns)
            self.assertIn("label_quality_status", frame.columns)
            self.assertIn("label_quality_score", frame.columns)
            self.assertIn("label_quality_reasons", frame.columns)
            self.assertIn("calibration_label", frame.columns)
            self.assertIn("calibration_label_available", frame.columns)
            self.assertIn("primary_outcome_return_bps", frame.columns)
            self.assertEqual(len(frame), 0)

    def test_dataset_writes_sqlite_sidecar_for_durable_storage(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "signals_dataset.csv"
            save_signal_evaluation(self._sample_result(), dataset_path=dataset_path)

            sqlite_path = dataset_path.with_suffix(".sqlite")
            self.assertTrue(sqlite_path.exists())

            frame = load_signals_dataset(dataset_path)
            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.iloc[0]["signal_id"], build_signal_evaluation_row(self._sample_result())["signal_id"])

    def test_append_sqlite_rows_auto_migrates_missing_columns(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "signals_dataset.csv"
            sqlite_path = dataset_path.with_suffix(".sqlite")

            # Simulate an older schema that predates recently added columns.
            with sqlite3.connect(sqlite_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE signals (
                        signal_id TEXT,
                        signal_timestamp TEXT,
                        source TEXT,
                        mode TEXT,
                        symbol TEXT
                    )
                    """
                )

            save_signal_evaluation(self._sample_result(), dataset_path=dataset_path)

            with sqlite3.connect(sqlite_path) as connection:
                columns = {
                    row[1]
                    for row in connection.execute('PRAGMA table_info("signals")').fetchall()
                }

            self.assertIn("event_intelligence_enabled", columns)

            frame = load_signals_dataset(dataset_path)
            self.assertEqual(len(frame), 1)

    def test_save_signal_evaluation_uses_signal_timestamp_as_default_capture_time(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "signals_dataset.csv"
            save_signal_evaluation(self._sample_result(), dataset_path=dataset_path)

            frame = load_signals_dataset(dataset_path)
            self.assertEqual(frame.iloc[0]["created_at"], "2026-03-14T10:00:00+05:30")
            self.assertEqual(frame.iloc[0]["updated_at"], "2026-03-14T10:00:00+05:30")

    def test_sparse_frame_normalization_does_not_emit_fragmentation_warning(self):
        sparse_frame = pd.DataFrame(
            [
                {
                    "signal_id": "sig-1",
                    "signal_timestamp": "2026-03-14T10:00:00+05:30",
                    "symbol": "NIFTY",
                    "trade_status": "TRADE",
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "signals_dataset.csv"
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                write_signals_dataset(sparse_frame, dataset_path)

            performance_warnings = [
                warning
                for warning in caught
                if issubclass(warning.category, pd.errors.PerformanceWarning)
            ]

            self.assertEqual(performance_warnings, [])

    def test_evaluate_signal_outcomes_enriches_row_without_duplication(self):
        row = build_signal_evaluation_row(self._sample_result())
        realized_path = pd.DataFrame(
            {
                "timestamp": [
                    "2026-03-14T10:05:00+05:30",
                    "2026-03-14T10:15:00+05:30",
                    "2026-03-14T10:30:00+05:30",
                    "2026-03-14T11:00:00+05:30",
                    "2026-03-14T15:25:00+05:30",
                    "2026-03-15T09:20:00+05:30",
                    "2026-03-15T15:25:00+05:30",
                ],
                "spot": [22020, 22035, 22050, 22010, 22080, 22110, 22140],
            }
        )

        enriched = evaluate_signal_outcomes(row, realized_path, as_of="2026-03-15T15:25:00+05:30")

        self.assertEqual(enriched["outcome_status"], "COMPLETE")
        self.assertEqual(enriched["spot_5m"], 22020)
        self.assertEqual(enriched["spot_close_same_day"], 22080)
        self.assertEqual(enriched["spot_next_open"], 22110)
        self.assertEqual(enriched["spot_next_close"], 22140)
        selfGreater = self.assertGreater
        selfGreater(enriched["realized_return_5m"], 0)
        self.assertGreater(enriched["signed_return_60m_bps"], 0)
        self.assertGreater(enriched["mfe_points"], 0)
        self.assertGreater(enriched["direction_score"], 0)
        self.assertGreater(enriched["magnitude_score"], 0)
        self.assertGreater(enriched["timing_score"], 0)
        self.assertGreater(enriched["tradeability_score"], 0)
        self.assertGreater(enriched["composite_signal_score"], 0)
        self.assertEqual(enriched["correct_session_close"], 1)
        self.assertEqual(enriched["label_quality_status"], "CLEAN")
        self.assertEqual(enriched["label_quality_reasons"], "")
        self.assertTrue(enriched["calibration_label_available"])
        self.assertEqual(enriched["calibration_label"], enriched["correct_60m"])
        self.assertEqual(enriched["calibration_label_horizon"], "60m")
        self.assertEqual(enriched["primary_outcome_return_bps"], enriched["signed_return_60m_bps"])

    def test_label_quality_policy_caps_resolve_from_parameter_pack(self):
        row = {
            "direction": "",
            "spot_at_signal": 22000.0,
            "outcome_status": "COMPLETE",
            "correct_60m": 1,
            "signed_return_60m_bps": 14.5,
        }

        with temporary_parameter_pack(
            overrides={"evaluation_thresholds.label_quality.direction_unresolved_score_cap": 22.0},
        ):
            enriched = apply_label_quality_fields(row)

        self.assertEqual(enriched["label_quality_status"], "UNUSABLE")
        self.assertEqual(enriched["label_quality_score"], 22.0)
        self.assertEqual(enriched["calibration_label_available"], False)
        self.assertIn("direction_unresolved", enriched["label_quality_reasons"])

    def test_label_quality_primary_horizon_resolves_from_parameter_pack(self):
        row = {
            "direction": "CALL",
            "spot_at_signal": 22000.0,
            "outcome_status": "COMPLETE",
            "observed_minutes": 30,
            "correct_30m": 1,
            "signed_return_30m_bps": 9.25,
            "correct_60m": 0,
            "signed_return_60m_bps": -6.0,
        }

        with temporary_parameter_pack(
            overrides={"evaluation_thresholds.label_quality.primary_label_horizon_minutes": 30},
        ):
            enriched = apply_label_quality_fields(row)

        self.assertEqual(enriched["label_quality_status"], "CLEAN")
        self.assertEqual(enriched["calibration_label"], 1)
        self.assertEqual(enriched["calibration_label_horizon"], "30m")
        self.assertEqual(enriched["primary_outcome_horizon"], "30m")
        self.assertEqual(enriched["primary_outcome_return_bps"], 9.25)

    def test_evaluate_signal_outcomes_labels_early_alpha_decay_and_exit_pressure(self):
        row = build_signal_evaluation_row(self._sample_result())
        realized_path = pd.DataFrame(
            {
                "timestamp": [
                    "2026-03-14T10:05:00+05:30",
                    "2026-03-14T10:15:00+05:30",
                    "2026-03-14T10:30:00+05:30",
                    "2026-03-14T11:00:00+05:30",
                    "2026-03-14T15:25:00+05:30",
                ],
                "spot": [22040, 22110, 22070, 22015, 21980],
            }
        )

        enriched = evaluate_signal_outcomes(row, realized_path, as_of="2026-03-14T15:25:00+05:30")

        self.assertEqual(enriched["best_outcome_horizon"], "15m")
        self.assertEqual(enriched["horizon_edge_label"], "EARLY_ALPHA_DECAY")
        self.assertEqual(enriched["exit_quality_label"], "EARLY_EXIT")
        self.assertLess(float(enriched["peak_to_close_decay_bps"]), 0)
        self.assertIn(enriched["tradeability_tier"], {"HIGH", "USABLE", "FRAGILE"})

    def test_evaluate_signal_outcomes_respects_as_of_without_future_leakage(self):
        row = build_signal_evaluation_row(self._sample_result())
        realized_path = pd.DataFrame(
            {
                "timestamp": [
                    "2026-03-14T10:05:00+05:30",
                    "2026-03-14T10:10:00+05:30",
                    "2026-03-14T11:05:00+05:30",
                ],
                "spot": [22010, 22020, 22100],
            }
        )

        enriched = evaluate_signal_outcomes(
            row,
            realized_path,
            as_of="2026-03-14T10:10:00+05:30",
        )

        self.assertTrue(pd.isna(enriched.get("spot_60m")))
        self.assertTrue(pd.isna(enriched.get("signed_return_60m_bps")))
        self.assertIn(enriched["outcome_status"], {"PENDING", "PARTIAL"})
        self.assertFalse(enriched["calibration_label_available"])
        self.assertIn(enriched["label_quality_status"], {"PENDING", "PARTIAL"})
        self.assertIn("primary_horizon_unavailable", enriched["label_quality_reasons"])

    def test_saved_spot_snapshot_stitcher_reads_standard_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_dir = root / "spot_snapshots"
            snapshot_dir.mkdir(parents=True)
            path = snapshot_dir / "NIFTY_spot_snapshot_2026-05-15T12-20-00+05-30.json"
            path.write_text(
                '{"timestamp":"2026-05-15T12:20:00+05:30","spot":23727.8}',
                encoding="utf-8",
            )

            frame = _stitch_saved_spot_snapshots(
                "NIFTY",
                start_ts=pd.Timestamp("2026-05-15T11:00:00+05:30"),
                end_ts=pd.Timestamp("2026-05-15T13:00:00+05:30"),
                snapshot_dir=root,
            )

        self.assertEqual(len(frame), 1)
        self.assertEqual(float(frame.iloc[0]["spot"]), 23727.8)

    def test_save_signal_evaluation_upserts_by_signal_id(self):
        result = self._sample_result()
        realized_path = pd.DataFrame(
            {
                "timestamp": [
                    "2026-03-14T10:15:00+05:30",
                    "2026-03-14T10:30:00+05:30",
                ],
                "spot": [22040, 22060],
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "signals_dataset.csv"
            save_signal_evaluation(result, dataset_path=dataset_path)
            save_signal_evaluation(result, dataset_path=dataset_path, realized_spot_path=realized_path)

            frame = load_signals_dataset(dataset_path)
            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.iloc[0]["signal_id"], build_signal_evaluation_row(result)["signal_id"])
            self.assertEqual(frame.iloc[0]["outcome_status"], "PARTIAL")
            self.assertIn(str(frame.iloc[0]["calibration_label_available"]).lower(), {"false", "0", "0.0"})

    def test_save_signal_evaluation_supports_append_only_live_capture(self):
        result_a = self._sample_result()
        result_b = self._sample_result()
        result_b["spot_summary"] = dict(result_b["spot_summary"])
        result_b["spot_summary"]["timestamp"] = "2026-03-14T10:30:00+05:30"

        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "signals_dataset.csv"
            returned = save_signal_evaluation(result_a, dataset_path=dataset_path, return_frame=False)
            self.assertIsNone(returned)

            returned = save_signal_evaluation(result_b, dataset_path=dataset_path, return_frame=False)
            self.assertIsNone(returned)

            frame = load_signals_dataset(dataset_path)
            self.assertEqual(len(frame), 2)
            self.assertEqual(frame["signal_id"].nunique(), 2)

    def test_concurrent_upserts_keep_csv_and_sqlite_consistent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "signals_dataset.csv"

            def write_row(index: int) -> None:
                upsert_signal_rows(
                    [
                        {
                            "signal_id": f"sig_{index:03d}",
                            "signal_timestamp": f"2026-03-14T10:{index % 60:02d}:00+05:30",
                            "updated_at": f"2026-03-14T10:{index % 60:02d}:00+05:30",
                            "symbol": "NIFTY",
                            "trade_status": "TRADE",
                        }
                    ],
                    path=dataset_path,
                    return_frame=False,
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(write_row, range(24)))

            frame = load_signals_dataset(dataset_path)
            csv_frame = pd.read_csv(dataset_path)
            sqlite_path = dataset_path.with_suffix(".sqlite")
            with sqlite3.connect(sqlite_path) as connection:
                sqlite_count = connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

            self.assertEqual(len(frame), 24)
            self.assertEqual(len(csv_frame), 24)
            self.assertEqual(sqlite_count, 24)
            self.assertSetEqual(set(frame["signal_id"]), {f"sig_{index:03d}" for index in range(24)})
            self.assertSetEqual(set(csv_frame["signal_id"]), set(frame["signal_id"]))

    def test_no_direction_signal_does_not_force_directional_scoring(self):
        result = self._sample_result()
        result["trade"] = dict(result["trade"])
        result["trade"]["direction"] = None
        result["trade"]["option_type"] = None
        result["trade"]["strike"] = None
        result["trade"]["entry_price"] = None
        result["trade"]["target"] = None
        result["trade"]["stop_loss"] = None
        result["trade"]["trade_status"] = "NO_SIGNAL"

        row = build_signal_evaluation_row(result)
        realized_path = pd.DataFrame(
            {
                "timestamp": [
                    "2026-03-14T10:05:00+05:30",
                    "2026-03-14T10:15:00+05:30",
                    "2026-03-14T15:25:00+05:30",
                ],
                "spot": [22020, 22035, 22080],
            }
        )

        enriched = evaluate_signal_outcomes(row, realized_path, as_of="2026-03-14T15:25:00+05:30")

        self.assertEqual(enriched["outcome_status"], "PARTIAL")
        self.assertEqual(enriched["spot_5m"], 22020)
        self.assertGreater(enriched["realized_return_5m"], 0)
        self.assertTrue(pd.isna(enriched["signed_return_5m_bps"]))
        self.assertTrue(pd.isna(enriched["correct_5m"]))
        self.assertTrue(pd.isna(enriched["signed_return_session_close_bps"]))
        self.assertTrue(pd.isna(enriched["directional_consistency_score"]))
        self.assertTrue(pd.isna(enriched["direction_score"]))
        self.assertTrue(pd.isna(enriched["magnitude_score"]))
        self.assertTrue(pd.isna(enriched["timing_score"]))
        self.assertTrue(pd.isna(enriched["tradeability_score"]))
        self.assertEqual(enriched["label_quality_status"], "UNUSABLE")
        self.assertFalse(enriched["calibration_label_available"])
        self.assertIn("direction_unresolved", enriched["label_quality_reasons"])

    def test_row_builder_infers_missing_contract_keys_from_ranked_strikes(self):
        result = self._sample_result()
        result["trade"] = dict(result["trade"])
        result["trade"]["selected_expiry"] = None
        result["trade"]["option_type"] = None
        result["trade"]["strike"] = None
        result["option_chain_validation"] = dict(result["option_chain_validation"])
        result["option_chain_validation"]["selected_expiry"] = "2026-03-26"
        result["ranked_strikes"] = [
            {
                "strike": 22100,
                "option_type": "PE",
                "selected_expiry": "2026-03-26",
                "score": 25.0,
            },
            {
                "strike": 22000,
                "option_type": "CE",
                "selected_expiry": "2026-03-26",
                "score": 27.81,
            },
        ]

        row = build_signal_evaluation_row(result)

        self.assertEqual(row["selected_expiry"], "2026-03-26")
        self.assertEqual(row["option_type"], "CE")
        self.assertEqual(row["strike"], 22000)

    def test_update_dataset_outcomes_merges_updated_rows(self):
        result = self._sample_result()

        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "signals_dataset.csv"
            save_signal_evaluation(result, dataset_path=dataset_path)

            def fake_fetch(symbol, signal_timestamp, as_of=None):
                return pd.DataFrame(
                    {
                        "timestamp": [
                            "2026-03-14T10:05:00+05:30",
                            "2026-03-14T10:15:00+05:30",
                            "2026-03-14T10:30:00+05:30",
                            "2026-03-14T11:00:00+05:30",
                            "2026-03-14T15:25:00+05:30",
                            "2026-03-15T09:20:00+05:30",
                            "2026-03-15T15:25:00+05:30",
                        ],
                        "spot": [22005, 22030, 22020, 22070, 22090, 22110, 22130],
                    }
                )

            frame = update_signal_dataset_outcomes(
                dataset_path=dataset_path,
                as_of="2026-03-15T15:25:00+05:30",
                fetch_spot_path_fn=fake_fetch,
            )

            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.iloc[0]["outcome_status"], "COMPLETE")
            self.assertFalse(pd.isna(frame.iloc[0]["spot_next_open"]))
            self.assertFalse(pd.isna(frame.iloc[0]["spot_next_close"]))
            self.assertGreater(float(frame.iloc[0]["directional_consistency_score"]), 0)

    def test_capture_policy_switch(self):
        trade = self._sample_result()["trade"]

        self.assertTrue(should_capture_signal(trade, CAPTURE_POLICY_ALL))
        self.assertTrue(should_capture_signal(trade, CAPTURE_POLICY_ACTIONABLE))
        self.assertTrue(should_capture_signal(trade, CAPTURE_POLICY_TRADE_ONLY))

        watchlist_trade = dict(trade)
        watchlist_trade["trade_status"] = "WATCHLIST"
        self.assertTrue(should_capture_signal(watchlist_trade, CAPTURE_POLICY_ALL))
        self.assertTrue(should_capture_signal(watchlist_trade, CAPTURE_POLICY_ACTIONABLE))
        self.assertFalse(should_capture_signal(watchlist_trade, CAPTURE_POLICY_TRADE_ONLY))

        no_signal_trade = dict(trade)
        no_signal_trade["trade_status"] = "NO_SIGNAL"
        self.assertTrue(should_capture_signal(no_signal_trade, CAPTURE_POLICY_ALL))
        self.assertFalse(should_capture_signal(no_signal_trade, CAPTURE_POLICY_ACTIONABLE))
        self.assertFalse(should_capture_signal(no_signal_trade, CAPTURE_POLICY_TRADE_ONLY))

        self.assertEqual(normalize_capture_policy("trade_only"), CAPTURE_POLICY_TRADE_ONLY)
        self.assertEqual(normalize_capture_policy("unknown"), CAPTURE_POLICY_ALL)


class CumulativeDatasetArchivalTests(unittest.TestCase):
    """Tests for the cumulative dataset syncing and archival mechanism."""

    def _make_rows(self, signal_ids, date="2026-03-18"):
        return [
            {
                "signal_id": sid,
                "signal_date": date,
                "updated_at": f"{date}T10:00:00+05:30",
                "symbol": "NIFTY",
            }
            for sid in signal_ids
        ]

    def test_sync_to_cumulative_appends_new_rows(self):
        from research.signal_evaluation.dataset import (
            _sync_to_cumulative,
            CUMULATIVE_DATASET_PATH,
            _dataset_store_path,
        )
        import research.signal_evaluation.dataset as ds_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            cumul_csv = Path(tmp_dir) / "signals_dataset_cumul.csv"
            cumul_sqlite = Path(tmp_dir) / "signals_dataset_cumul.sqlite"

            # Temporarily override the module-level paths
            orig_cumul = ds_mod.CUMULATIVE_DATASET_PATH
            ds_mod.CUMULATIVE_DATASET_PATH = cumul_csv

            try:
                # First sync — creates cumulative from scratch
                df1 = pd.DataFrame(self._make_rows(["sig_a", "sig_b"]))
                _sync_to_cumulative(df1)
                cumul = pd.read_csv(cumul_csv)
                self.assertEqual(len(cumul), 2)

                # Second sync — only new rows appended
                df2 = pd.DataFrame(self._make_rows(["sig_b", "sig_c"]))
                _sync_to_cumulative(df2)
                cumul = pd.read_csv(cumul_csv)
                self.assertEqual(len(cumul), 3)
                self.assertSetEqual(set(cumul["signal_id"]), {"sig_a", "sig_b", "sig_c"})
            finally:
                ds_mod.CUMULATIVE_DATASET_PATH = orig_cumul

    def test_sync_to_cumulative_skips_empty_frame(self):
        from research.signal_evaluation.dataset import _sync_to_cumulative
        import research.signal_evaluation.dataset as ds_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            cumul_csv = Path(tmp_dir) / "signals_dataset_cumul.csv"
            orig_cumul = ds_mod.CUMULATIVE_DATASET_PATH
            ds_mod.CUMULATIVE_DATASET_PATH = cumul_csv

            try:
                _sync_to_cumulative(pd.DataFrame())
                self.assertFalse(cumul_csv.exists())
            finally:
                ds_mod.CUMULATIVE_DATASET_PATH = orig_cumul

    def test_sync_live_to_cumulative_returns_new_count(self):
        from research.signal_evaluation.dataset import (
            sync_live_to_cumulative,
            write_signals_dataset,
        )
        import research.signal_evaluation.dataset as ds_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            live_csv = Path(tmp_dir) / "signals_dataset.csv"
            cumul_csv = Path(tmp_dir) / "signals_dataset_cumul.csv"

            orig_live = ds_mod.SIGNAL_DATASET_PATH
            orig_cumul = ds_mod.CUMULATIVE_DATASET_PATH
            ds_mod.SIGNAL_DATASET_PATH = live_csv
            ds_mod.CUMULATIVE_DATASET_PATH = cumul_csv

            try:
                # Write live dataset with 3 rows
                live_df = pd.DataFrame(self._make_rows(["sig_1", "sig_2", "sig_3"]))
                write_signals_dataset(live_df, live_csv)

                # First sync — all 3 should be new
                synced = sync_live_to_cumulative()
                self.assertEqual(synced, 3)

                # Second sync — idempotent, no new rows
                synced = sync_live_to_cumulative()
                self.assertEqual(synced, 0)
            finally:
                ds_mod.SIGNAL_DATASET_PATH = orig_live
                ds_mod.CUMULATIVE_DATASET_PATH = orig_cumul

    def test_upsert_auto_syncs_to_cumulative(self):
        from research.signal_evaluation.dataset import upsert_signal_rows
        import research.signal_evaluation.dataset as ds_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            live_csv = Path(tmp_dir) / "signals_dataset.csv"
            cumul_csv = Path(tmp_dir) / "signals_dataset_cumul.csv"

            orig_live = ds_mod.SIGNAL_DATASET_PATH
            orig_cumul = ds_mod.CUMULATIVE_DATASET_PATH
            ds_mod.SIGNAL_DATASET_PATH = live_csv
            ds_mod.CUMULATIVE_DATASET_PATH = cumul_csv

            try:
                # Upsert to the live path — should auto-sync to cumulative
                upsert_signal_rows(
                    self._make_rows(["sig_x", "sig_y"]),
                    path=live_csv,
                    return_frame=False,
                )
                self.assertTrue(cumul_csv.exists())
                cumul = pd.read_csv(cumul_csv)
                self.assertEqual(len(cumul), 2)
                self.assertSetEqual(set(cumul["signal_id"]), {"sig_x", "sig_y"})
            finally:
                ds_mod.SIGNAL_DATASET_PATH = orig_live
                ds_mod.CUMULATIVE_DATASET_PATH = orig_cumul

    def test_concurrent_live_upserts_sync_cumulative_consistently(self):
        import research.signal_evaluation.dataset as ds_mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            live_csv = Path(tmp_dir) / "signals_dataset.csv"
            cumul_csv = Path(tmp_dir) / "signals_dataset_cumul.csv"

            orig_live = ds_mod.SIGNAL_DATASET_PATH
            orig_cumul = ds_mod.CUMULATIVE_DATASET_PATH
            ds_mod.SIGNAL_DATASET_PATH = live_csv
            ds_mod.CUMULATIVE_DATASET_PATH = cumul_csv

            try:
                def write_row(index: int) -> None:
                    upsert_signal_rows(
                        self._make_rows([f"sig_live_{index:03d}"]),
                        path=live_csv,
                        return_frame=False,
                    )

                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(write_row, range(20)))

                live = load_signals_dataset(live_csv)
                cumul = load_signals_dataset(cumul_csv)
                cumul_csv_frame = pd.read_csv(cumul_csv)
                with sqlite3.connect(cumul_csv.with_suffix(".sqlite")) as connection:
                    cumul_sqlite_count = connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

                self.assertEqual(len(live), 20)
                self.assertEqual(len(cumul), 20)
                self.assertEqual(len(cumul_csv_frame), 20)
                self.assertEqual(cumul_sqlite_count, 20)
                self.assertSetEqual(set(live["signal_id"]), set(cumul["signal_id"]))
            finally:
                ds_mod.SIGNAL_DATASET_PATH = orig_live
                ds_mod.CUMULATIVE_DATASET_PATH = orig_cumul


if __name__ == "__main__":
    unittest.main()

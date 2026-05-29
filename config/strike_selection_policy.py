"""
Module: strike_selection_policy.py

Purpose:
    Define the thresholds, weights, and policy getters used by strike selection.

Role in the System:
    Part of the configuration layer that centralizes policy defaults, thresholds, and governance controls.

Key Outputs:
    Configuration objects and threshold bundles consumed by runtime and research workflows.

Downstream Usage:
    Consumed by analytics, signal generation, strategy, risk overlays, tuning, and backtests.
"""

from __future__ import annotations


STRIKE_SELECTION_SCORE_CONFIG = {
    "strike_scoring_mode": "continuous",
    "atm_distance_pct": 0.20,
    "near_distance_pct": 0.40,
    "mid_distance_pct": 0.70,
    "far_distance_pct": 1.20,
    "moneyness_atm_score": 10,
    "moneyness_near_score": 8,
    "moneyness_mid_score": 5,
    "moneyness_far_score": 2,
    "moneyness_deep_penalty": -2,
    "call_above_spot_score": 2,
    "call_below_spot_score": 1,
    "put_below_spot_score": 2,
    "put_above_spot_score": 1,
    "premium_optimal_min": 80.0,
    "premium_optimal_max": 250.0,
    "premium_secondary_min": 40.0,
    "premium_secondary_max": 400.0,
    "premium_lower_tail_min": 20.0,
    "premium_optimal_score": 8,
    "premium_secondary_score": 6,
    "premium_upper_mid_score": 4,
    "premium_lower_tail_score": 3,
    "premium_default_score": 1,
    "premium_invalid_penalty": -10,
    "premium_over_budget_penalty": -5,
    "premium_near_budget_penalty": -2,
    "premium_near_budget_ratio": 0.85,
    "volume_high_threshold": 5000.0,
    "volume_medium_threshold": 2000.0,
    "volume_low_threshold": 500.0,
    "volume_high_score": 6,
    "volume_medium_score": 4,
    "volume_low_score": 2,
    "oi_high_threshold": 100000.0,
    "oi_medium_threshold": 50000.0,
    "oi_low_threshold": 10000.0,
    "oi_high_score": 6,
    "oi_medium_score": 4,
    "oi_low_score": 2,
    "wall_near_distance_points": 50.0,
    "wall_medium_distance_points": 100.0,
    "wall_near_penalty": -4,
    "wall_medium_penalty": -2,
    "gamma_cluster_near_distance_points": 50.0,
    "gamma_cluster_medium_distance_points": 100.0,
    "gamma_cluster_near_penalty": -2,
    "gamma_cluster_medium_penalty": -1,
    "gamma_cluster_far_bonus": 1,
    "iv_low_min": 10.0,
    "iv_low_max": 22.0,
    "iv_mid_max": 30.0,
    "iv_high_threshold": 40.0,
    "iv_low_score": 3,
    "iv_mid_score": 1,
    "iv_high_penalty": -2,
    "strike_window_steps": 8,
    # Bid-ask spread quality: penalise wide spreads relative to mid-price.
    # spread_ratio = (ask - bid) / mid.  Above the threshold, apply the penalty.
    "ba_spread_ratio_threshold": 0.04,
    "ba_spread_ratio_wide": 0.10,
    "ba_spread_narrow_bonus": 1,
    "ba_spread_wide_penalty": -3,
    # Enhanced strike scoring weights. These preserve the previous
    # strategy.enhanced_strike_scoring defaults while making them governable.
    "enhanced_weight_liquidity": 0.30,
    "enhanced_weight_gamma_magnetism": 0.25,
    "enhanced_weight_dealer_pressure": 0.20,
    "enhanced_weight_volatility_convexity": 0.15,
    "enhanced_weight_premium_efficiency": 0.10,
    "enhanced_liquidity_weight_volume": 0.40,
    "enhanced_liquidity_weight_open_interest": 0.40,
    "enhanced_liquidity_weight_oi_change": 0.20,
    "dealer_gamma_regime_score_short_gamma_zone": 0.90,
    "dealer_gamma_regime_score_negative_gamma": 0.85,
    "dealer_gamma_regime_score_neutral_gamma": 0.50,
    "dealer_gamma_regime_score_long_gamma_zone": 0.20,
    "dealer_gamma_regime_score_positive_gamma": 0.15,
    "dealer_hedging_bias_score_downside_acceleration": 0.90,
    "dealer_hedging_bias_score_upside_acceleration": 0.85,
    "dealer_hedging_bias_score_two_sided_instability": 0.80,
    "dealer_hedging_bias_score_pinning_dominant": 0.30,
    "dealer_hedging_bias_score_downside_pinning": 0.35,
    "dealer_hedging_bias_score_upside_pinning": 0.35,
    "dealer_hedging_bias_score_neutral": 0.50,
    "dealer_flip_context_score_at_flip": 1.00,
    "dealer_flip_context_score_above_flip": 0.65,
    "dealer_flip_context_score_below_flip": 0.65,
    "dealer_flip_context_score_default": 0.50,
    "dealer_flip_proximity_default_pct": 5.00,
    "dealer_flip_proximity_cap_pct": 10.00,
    "dealer_gex_log_scale": 12.00,
    "dealer_pressure_weight_regime": 0.30,
    "dealer_pressure_weight_flip_proximity": 0.25,
    "dealer_pressure_weight_bias": 0.25,
    "dealer_pressure_weight_flip_context": 0.10,
    "dealer_pressure_weight_gex": 0.10,
    "expected_move_default_iv": 0.15,
    "expected_move_default_dte": 1.00,
    "expected_move_min_dte": 0.10,
    "premium_efficiency_min_premium": 0.01,
    "payoff_weight_premium_efficiency": 0.35,
    "payoff_weight_delta_alignment": 0.25,
    "payoff_weight_liquidity_score": 0.20,
    "payoff_weight_distance_to_target": 0.10,
    "payoff_weight_iv_efficiency": 0.10,
    "payoff_delta_ideal": 0.45,
    "payoff_delta_normalization": 0.45,
    "payoff_liquidity_weight_volume": 0.50,
    "payoff_liquidity_weight_open_interest": 0.50,
    "tradeability_min_intraday_volume": 500.0,
    "tradeability_min_overnight_volume": 2000.0,
    "tradeability_min_liquidity_oi": 10000.0,
    "tradeability_max_premium_ratio": 5.0,
    "tradeability_min_premium_cap": 1.0,
}


def get_strike_selection_score_config():
    """
    Purpose:
        Return the configuration bundle for strike selection score.
    
    Context:
        Public function within the configuration layer. It exposes a reusable step in this module's workflow.
    
    Inputs:
        None: This helper does not require caller-supplied inputs.
    
    Returns:
        Any: Result returned by the helper.
    
    Notes:
        Centralizing this contract keeps runtime, replay, and research workflows aligned on the same configuration semantics.
    """
    from config.policy_resolver import resolve_mapping

    return resolve_mapping("strike_selection.core", STRIKE_SELECTION_SCORE_CONFIG)

"""
Module: option_efficiency_policy.py

Purpose:
    Define the thresholds, weights, and policy getters used by option efficiency.

Role in the System:
    Part of the configuration layer that centralizes policy defaults, thresholds, and governance controls.

Key Outputs:
    Configuration objects and threshold bundles consumed by runtime and research workflows.

Downstream Usage:
    Consumed by analytics, signal generation, strategy, risk overlays, tuning, and backtests.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionEfficiencyPolicyConfig:
    """
    Purpose:
        Dataclass representing OptionEfficiencyPolicyConfig within the repository.
    
    Context:
        Used within the configuration layer that centralizes policy defaults and thresholds. The class keeps configuration or structured state explicit for downstream consumers.
    
    Attributes:
        neutral_score (int): Score value for neutral.
        high_efficiency_threshold (int): Threshold used to classify or trigger high efficiency.
        good_efficiency_threshold (int): Threshold used to classify or trigger good efficiency.
        weak_efficiency_threshold (int): Threshold used to classify or trigger weak efficiency.
        poor_efficiency_threshold (int): Threshold used to classify or trigger poor efficiency.
        overnight_block_threshold (int): Threshold used to classify or trigger overnight block.
        overnight_watch_threshold (int): Threshold used to classify or trigger overnight watch.
        iv_percent_unit_threshold (float): Threshold used to classify or trigger IV percent unit.
        minimum_time_to_expiry_years (float): Value supplied for minimum time to expiry years.
        min_effective_delta (float): Value supplied for min effective delta.
        max_effective_delta (float): Value supplied for max effective delta.
        fallback_delta (float): Value supplied for fallback delta.
        target_delta_floor (float): Floor value used for target delta.
        target_intrinsic_hurdle_multiplier (float): Multiplier applied to target intrinsic hurdle.
        strike_moneyness_atm_distance_pct (float): Value supplied for strike moneyness ATM distance percentage.
        payoff_far_otm_distance_ratio (float): Ratio used for payoff far otm distance.
        payoff_deep_itm_premium_ratio (float): Ratio used for payoff deep itm premium.
        trade_probability_floor (float): Floor value used for trade probability.
        trade_probability_ceiling (float): Value supplied for trade probability ceiling.
        convexity_base (float): Value supplied for convexity base.
        convexity_gamma_vol_weight (float): Weight applied to convexity gamma vol.
        convexity_dealer_pressure_weight (float): Weight applied to convexity dealer pressure.
        convexity_liquidity_vacuum_bonus (float): Bonus applied when convexity liquidity vacuum is active.
        option_move_probability_base (float): Value supplied for option move probability base.
        option_move_probability_weight (float): Weight applied to option move probability.
        target_reachability_center (float): Smooth-score center for target reachability coverage.
        target_reachability_steepness (float): Smooth-score steepness for target reachability coverage.
        target_reachability_score_floor (float): Lower score bound for target reachability.
        target_reachability_score_ceiling (float): Upper score bound for target reachability.
        premium_efficiency_center (float): Smooth-score center for premium coverage.
        premium_efficiency_steepness (float): Smooth-score steepness for premium coverage.
        premium_efficiency_score_floor (float): Lower score bound for premium efficiency.
        premium_efficiency_score_ceiling (float): Upper score bound for premium efficiency.
        strike_efficiency_center (float): Smooth-score center for strike-distance quality.
        strike_efficiency_steepness (float): Smooth-score steepness for strike-distance quality.
        strike_efficiency_score_floor (float): Lower score bound for strike efficiency.
        strike_efficiency_score_ceiling (float): Upper score bound for strike efficiency.
        strike_efficiency_atm_bonus (int): Score bonus applied to ATM strikes.
        strike_efficiency_itm_penalty (int): Score penalty applied to ITM strikes.
        strike_efficiency_itm_premium_poor_threshold (float): Premium coverage threshold for expensive ITM penalty.
        strike_efficiency_itm_premium_poor_penalty (int): ITM penalty when premium coverage is poor.
        strike_efficiency_itm_premium_weak_threshold (float): Premium coverage threshold for weaker ITM penalty.
        strike_efficiency_itm_premium_weak_penalty (int): ITM penalty when premium coverage is weak.
        option_efficiency_premium_weight (float): Composite option-efficiency premium component weight.
        option_efficiency_target_weight (float): Composite option-efficiency target-reachability weight.
        option_efficiency_strike_weight (float): Composite option-efficiency strike component weight.
        target_reachability_boost (int): Value supplied for target reachability boost.
        target_reachability_moderate_boost (int): Value supplied for target reachability moderate boost.
        premium_penalty (int): Penalty applied when premium is active.
        strike_penalty (int): Penalty applied when strike is active.
        poor_efficiency_penalty (int): Penalty applied when poor efficiency is active.
        overnight_option_efficiency_poor_threshold (int): Overnight penalty threshold for poor option efficiency.
        overnight_option_efficiency_poor_penalty (int): Overnight penalty for poor option efficiency.
        overnight_option_efficiency_weak_threshold (int): Overnight penalty threshold for weak option efficiency.
        overnight_option_efficiency_weak_penalty (int): Overnight penalty for weak option efficiency.
        overnight_target_reachability_weak_threshold (int): Overnight penalty threshold for target reachability.
        overnight_target_reachability_weak_penalty (int): Overnight penalty for weak target reachability.
        overnight_premium_efficiency_poor_threshold (int): Overnight penalty threshold for poor premium efficiency.
        overnight_premium_efficiency_poor_penalty (int): Overnight penalty for poor premium efficiency.
        overnight_premium_efficiency_weak_threshold (int): Overnight penalty threshold for weak premium efficiency.
        overnight_premium_efficiency_weak_penalty (int): Overnight penalty for weak premium efficiency.
        overnight_strike_efficiency_poor_threshold (int): Overnight penalty threshold for poor strike efficiency.
        overnight_strike_efficiency_poor_penalty (int): Overnight penalty for poor strike efficiency.
        overnight_strike_efficiency_weak_threshold (int): Overnight penalty threshold for weak strike efficiency.
        overnight_strike_efficiency_weak_penalty (int): Overnight penalty for weak strike efficiency.
        overnight_premium_coverage_min_ratio (float): Overnight penalty threshold for insufficient premium coverage.
        overnight_premium_coverage_penalty (int): Overnight penalty for insufficient premium coverage.
        overnight_strike_distance_max_ratio (float): Overnight penalty threshold for excessive strike distance.
        overnight_strike_distance_penalty (int): Overnight penalty for excessive strike distance.
        overnight_penalty_cap (int): Maximum overnight option-efficiency penalty.
        candidate_high_efficiency_adjustment (int): Candidate strike score bump for high option efficiency.
        candidate_good_efficiency_adjustment (int): Candidate strike score bump for good option efficiency.
    
    Notes:
        Explicit field-level documentation makes policy tuning safer because threshold and weighting semantics stay visible at the point of definition.
    """
    neutral_score: int = 50
    high_efficiency_threshold: int = 75
    good_efficiency_threshold: int = 62
    weak_efficiency_threshold: int = 40
    poor_efficiency_threshold: int = 28
    overnight_block_threshold: int = 5
    overnight_watch_threshold: int = 3
    iv_percent_unit_threshold: float = 1.5
    minimum_time_to_expiry_years: float = 0.000114155
    min_effective_delta: float = 0.25
    max_effective_delta: float = 0.85
    fallback_delta: float = 0.35
    target_delta_floor: float = 0.25
    target_intrinsic_hurdle_multiplier: float = 0.75
    strike_moneyness_atm_distance_pct: float = 0.20
    payoff_far_otm_distance_ratio: float = 1.0
    payoff_deep_itm_premium_ratio: float = 0.65
    trade_probability_floor: float = 0.05
    trade_probability_ceiling: float = 0.95
    convexity_base: float = 1.0
    convexity_gamma_vol_weight: float = 0.22
    convexity_dealer_pressure_weight: float = 0.16
    convexity_liquidity_vacuum_bonus: float = 0.08
    option_move_probability_base: float = 0.75
    option_move_probability_weight: float = 0.50
    target_reachability_center: float = 0.90
    target_reachability_steepness: float = 4.0
    target_reachability_score_floor: float = 12.0
    target_reachability_score_ceiling: float = 92.0
    premium_efficiency_center: float = 1.00
    premium_efficiency_steepness: float = 3.6
    premium_efficiency_score_floor: float = 14.0
    premium_efficiency_score_ceiling: float = 90.0
    strike_efficiency_center: float = 0.20
    strike_efficiency_steepness: float = 4.2
    strike_efficiency_score_floor: float = 18.0
    strike_efficiency_score_ceiling: float = 82.0
    strike_efficiency_atm_bonus: int = 8
    strike_efficiency_itm_penalty: int = -6
    strike_efficiency_itm_premium_poor_threshold: float = 0.65
    strike_efficiency_itm_premium_poor_penalty: int = -8
    strike_efficiency_itm_premium_weak_threshold: float = 0.85
    strike_efficiency_itm_premium_weak_penalty: int = -3
    option_efficiency_premium_weight: float = 0.38
    option_efficiency_target_weight: float = 0.34
    option_efficiency_strike_weight: float = 0.28
    target_reachability_boost: int = 3
    target_reachability_moderate_boost: int = 1
    premium_penalty: int = -3
    strike_penalty: int = -2
    poor_efficiency_penalty: int = -4
    overnight_option_efficiency_poor_threshold: int = 32
    overnight_option_efficiency_poor_penalty: int = 4
    overnight_option_efficiency_weak_threshold: int = 45
    overnight_option_efficiency_weak_penalty: int = 2
    overnight_target_reachability_weak_threshold: int = 32
    overnight_target_reachability_weak_penalty: int = 3
    overnight_premium_efficiency_poor_threshold: int = 28
    overnight_premium_efficiency_poor_penalty: int = 2
    overnight_premium_efficiency_weak_threshold: int = 34
    overnight_premium_efficiency_weak_penalty: int = 1
    overnight_strike_efficiency_poor_threshold: int = 20
    overnight_strike_efficiency_poor_penalty: int = 3
    overnight_strike_efficiency_weak_threshold: int = 35
    overnight_strike_efficiency_weak_penalty: int = 1
    overnight_premium_coverage_min_ratio: float = 0.65
    overnight_premium_coverage_penalty: int = 2
    overnight_strike_distance_max_ratio: float = 1.15
    overnight_strike_distance_penalty: int = 2
    overnight_penalty_cap: int = 10
    candidate_high_efficiency_adjustment: int = 3
    candidate_good_efficiency_adjustment: int = 1


OPTION_EFFICIENCY_POLICY_CONFIG = OptionEfficiencyPolicyConfig()


def get_option_efficiency_policy_config() -> OptionEfficiencyPolicyConfig:
    """
    Purpose:
        Return the option-efficiency policy bundle used by contract scoring.
    
    Context:
        Public function in the configuration layer. It exposes a stable policy bundle for runtime, research, or governance code.
    
    Inputs:
        None: This helper does not require caller-supplied inputs.
    
    Returns:
        OptionEfficiencyPolicyConfig: Configuration object used by downstream runtime, research, or governance code.
    
    Notes:
        Centralizing policy access behind getters keeps live, replay, research, and tuning workflows aligned on the same defaults.
    """
    from config.policy_resolver import resolve_dataclass_config

    return resolve_dataclass_config("option_efficiency.core", OptionEfficiencyPolicyConfig())

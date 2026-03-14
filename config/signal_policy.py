"""
Signal policy calibration for live engine scoring and direction selection.
"""

from __future__ import annotations

DIRECTION_VOTE_WEIGHTS = {
    "FLOW": 1.2,
    "HEDGING_BIAS": 1.1,
    "GAMMA_SQUEEZE": 0.9,
    "GAMMA_FLIP": 0.85,
    "DEALER_VOL": 0.8,
    "VANNA": 0.45,
    "CHARM": 0.45,
    "BACKTEST_FALLBACK": 0.6,
}

DIRECTION_MIN_SCORE = 1.75
DIRECTION_MIN_MARGIN = 0.7

TRADE_STRENGTH_WEIGHTS = {
    "flow_call_bullish": 20,
    "flow_call_bearish": -10,
    "flow_put_bearish": 20,
    "flow_put_bullish": -10,
    "smart_call_bullish": 15,
    "smart_call_bearish": -8,
    "smart_put_bearish": 15,
    "smart_put_bullish": -8,
    "hedging_acceleration_support": 10,
    "hedging_acceleration_conflict": -6,
    "gamma_regime_negative": 10,
    "gamma_regime_positive": 2,
    "gamma_regime_neutral": 5,
    "spot_flip_primary": 8,
    "spot_flip_secondary": 2,
    "wall_support_bonus": 5,
    "wall_resistance_penalty": -3,
    "liquidity_map_path_bonus": 4,
    "gamma_event_bonus": 10,
    "dealer_short_gamma_bonus": 10,
    "dealer_long_gamma_bonus": 5,
    "vol_expansion_bonus": 10,
    "normal_vol_bonus": 5,
    "liquidity_void_near_bonus": 10,
    "liquidity_void_far_bonus": 4,
    "vacuum_breakout_bonus": 10,
    "vacuum_watch_bonus": 4,
    "intraday_vol_expansion_bonus": 5,
    "intraday_gamma_decrease_bonus": 3,
}

CONSENSUS_SCORE_CONFIG = {
    "strong_alignment_bonus": 8,
    "moderate_alignment_bonus": 4,
    "conflict_penalty": -6,
}

TRADE_RUNTIME_THRESHOLDS = {
    "min_trade_strength": 45,
    "strong_signal_threshold": 75,
    "medium_signal_threshold": 60,
    "weak_signal_threshold": 40,
    "expansion_bias_threshold": 75,
    "directional_bias_threshold": 55,
}

CONFIRMATION_FILTER_CONFIG = {
    "strong_confirmation_threshold": 6,
    "confirmed_threshold": 2,
    "mixed_threshold": -3,
    "open_alignment_support": 2,
    "open_alignment_conflict": -2,
    "prev_close_alignment_support": 1,
    "prev_close_alignment_conflict": -1,
    "range_expansion_strong_score": 3,
    "range_expansion_moderate_score": 2,
    "range_expansion_low_score": 1,
    "range_expansion_cold_score": -1,
    "flow_support": 3,
    "flow_conflict": -4,
    "hedging_support": 3,
    "hedging_conflict": -4,
    "gamma_event_support": 2,
    "move_probability_high_threshold": 0.65,
    "move_probability_high_score": 3,
    "move_probability_moderate_threshold": 0.50,
    "move_probability_moderate_score": 2,
    "move_probability_low_support_threshold": 0.40,
    "move_probability_low_support_score": 1,
    "move_probability_conflict_threshold": 0.30,
    "move_probability_conflict_score": -2,
    "flip_alignment_support": 2,
    "flip_alignment_conflict": -1,
    "veto_hard_conflicts": 3,
    "veto_move_probability_ceiling": 0.55,
}


def get_direction_vote_weights():
    from tuning.runtime import resolve_mapping

    return resolve_mapping("trade_strength.direction_vote", DIRECTION_VOTE_WEIGHTS)


def get_direction_thresholds():
    from tuning.runtime import get_parameter_value

    return {
        "min_score": float(get_parameter_value("trade_strength.direction_thresholds.min_score")),
        "min_margin": float(get_parameter_value("trade_strength.direction_thresholds.min_margin")),
    }


def get_trade_strength_weights():
    from tuning.runtime import resolve_mapping

    return resolve_mapping("trade_strength.scoring", TRADE_STRENGTH_WEIGHTS)


def get_consensus_score_config():
    from tuning.runtime import resolve_mapping

    return resolve_mapping("trade_strength.consensus", CONSENSUS_SCORE_CONFIG)


def get_trade_runtime_thresholds():
    from tuning.runtime import resolve_mapping

    return resolve_mapping("trade_strength.runtime_thresholds", TRADE_RUNTIME_THRESHOLDS)


def get_confirmation_filter_config():
    from tuning.runtime import resolve_mapping

    return resolve_mapping("confirmation_filter.core", CONFIRMATION_FILTER_CONFIG)

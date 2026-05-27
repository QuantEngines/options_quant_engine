"""
Policy defaults for the probabilistic direction head.

The direction head estimates P(up | X) from structural signal inputs. These
defaults preserve the current live behavior while making the coefficients
visible to parameter governance and future research.
"""

from __future__ import annotations


DIRECTION_PROBABILITY_DIRECTIONAL_BIAS = {
    "flow_bullish_score": 1.30,
    "flow_bearish_score": -1.30,
    "above_flip_score": 0.85,
    "below_flip_score": -0.85,
    "upside_acceleration_score": 1.00,
    "downside_acceleration_score": -1.00,
    "gamma_squeeze_flip_score": 0.35,
    "negative_gamma_flip_score": 0.15,
    "oi_velocity_clip": 0.70,
    "oi_velocity_weight": 0.55,
    "rr_scale_points": 2.0,
    "rr_clip": 1.0,
    "rr_weight": 0.60,
    "rr_rising_put_skew_score": -0.20,
    "rr_falling_put_skew_score": 0.20,
    "pcr_neutral": 1.0,
    "pcr_scale": 0.60,
    "pcr_clip": 0.35,
    "flip_drift_scale_points": 250.0,
    "flip_drift_clip": 0.35,
}


DIRECTION_PROBABILITY_MICROSTRUCTURE_FRICTION = {
    "provider_good_score": 0.0,
    "provider_caution_score": 0.5,
    "provider_weak_score": 1.0,
    "provider_unknown_score": 0.5,
    "blocking_component_score": 1.0,
    "quote_weak_score": 1.0,
    "quote_caution_score": 0.5,
    "quote_good_score": 0.0,
    "priced_ratio_reference": 0.60,
    "one_sided_ratio_reference": 0.55,
    "provider_weight": 0.30,
    "blocking_weight": 0.30,
    "quote_weight": 0.20,
    "priced_ratio_weight": 0.10,
    "one_sided_weight": 0.10,
}


DIRECTION_PROBABILITY_LOGIT = {
    "intercept": -0.05,
    "directional_bias_weight": 0.90,
    "vote_probability_weight": 0.80,
    "move_probability_weight": 0.55,
    "neutral_probability": 0.50,
    "friction_attenuation": 0.60,
}


DIRECTION_PROBABILITY_UNCERTAINTY = {
    "entropy_weight": 0.4783,
    "disagreement_weight": 0.2609,
    "friction_weight": 0.2609,
}

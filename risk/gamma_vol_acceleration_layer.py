"""
Backward-compatible facade for the gamma-vol acceleration overlay.
"""

from __future__ import annotations

from risk.gamma_vol_acceleration_features import build_gamma_vol_acceleration_features
from risk.gamma_vol_acceleration_regime import classify_gamma_vol_acceleration_state


def build_gamma_vol_acceleration_state(
    *,
    gamma_regime=None,
    spot_vs_flip=None,
    gamma_flip_distance_pct=None,
    dealer_hedging_bias=None,
    liquidity_vacuum_state=None,
    intraday_range_pct=None,
    volatility_compression_score=None,
    volatility_shock_score=None,
    macro_event_risk_score=None,
    global_risk_state=None,
    volatility_explosion_probability=None,
    holding_profile="AUTO",
    support_wall=None,
    resistance_wall=None,
):
    features = build_gamma_vol_acceleration_features(
        gamma_regime=gamma_regime,
        spot_vs_flip=spot_vs_flip,
        gamma_flip_distance_pct=gamma_flip_distance_pct,
        dealer_hedging_bias=dealer_hedging_bias,
        liquidity_vacuum_state=liquidity_vacuum_state,
        intraday_range_pct=intraday_range_pct,
        volatility_compression_score=volatility_compression_score,
        volatility_shock_score=volatility_shock_score,
        macro_event_risk_score=macro_event_risk_score,
        global_risk_state=global_risk_state,
        volatility_explosion_probability=volatility_explosion_probability,
        holding_profile=holding_profile,
        support_wall=support_wall,
        resistance_wall=resistance_wall,
    )
    return classify_gamma_vol_acceleration_state(features).to_dict()

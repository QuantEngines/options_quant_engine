"""
Backward-compatible facade for the dealer hedging pressure overlay.
"""

from __future__ import annotations

from risk.dealer_hedging_pressure_features import build_dealer_hedging_pressure_features
from risk.dealer_hedging_pressure_regime import classify_dealer_hedging_pressure_state


def build_dealer_hedging_pressure_state(
    *,
    spot=None,
    gamma_regime=None,
    spot_vs_flip=None,
    gamma_flip_distance_pct=None,
    dealer_position=None,
    dealer_hedging_bias=None,
    dealer_hedging_flow=None,
    market_gamma=None,
    gamma_clusters=None,
    liquidity_levels=None,
    support_wall=None,
    resistance_wall=None,
    liquidity_vacuum_state=None,
    intraday_gamma_state=None,
    intraday_range_pct=None,
    flow_signal=None,
    smart_money_flow=None,
    macro_event_risk_score=None,
    global_risk_state=None,
    volatility_explosion_probability=None,
    gamma_vol_acceleration_score=None,
    holding_profile="AUTO",
):
    features = build_dealer_hedging_pressure_features(
        spot=spot,
        gamma_regime=gamma_regime,
        spot_vs_flip=spot_vs_flip,
        gamma_flip_distance_pct=gamma_flip_distance_pct,
        dealer_position=dealer_position,
        dealer_hedging_bias=dealer_hedging_bias,
        dealer_hedging_flow=dealer_hedging_flow,
        market_gamma=market_gamma,
        gamma_clusters=gamma_clusters,
        liquidity_levels=liquidity_levels,
        support_wall=support_wall,
        resistance_wall=resistance_wall,
        liquidity_vacuum_state=liquidity_vacuum_state,
        intraday_gamma_state=intraday_gamma_state,
        intraday_range_pct=intraday_range_pct,
        flow_signal=flow_signal,
        smart_money_flow=smart_money_flow,
        macro_event_risk_score=macro_event_risk_score,
        global_risk_state=global_risk_state,
        volatility_explosion_probability=volatility_explosion_probability,
        gamma_vol_acceleration_score=gamma_vol_acceleration_score,
        holding_profile=holding_profile,
    )
    return classify_dealer_hedging_pressure_state(features).to_dict()

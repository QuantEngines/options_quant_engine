"""
Deterministic raw feature model for dealer hedging pressure.
"""

from __future__ import annotations


def _clip(value, lo, hi):
    return max(lo, min(hi, value))


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def _holding_context(global_risk_state, holding_profile):
    global_risk_state = global_risk_state if isinstance(global_risk_state, dict) else {}
    holding_context = global_risk_state.get("holding_context", {})
    holding_context = holding_context if isinstance(holding_context, dict) else {}
    profile = str(holding_profile or holding_context.get("holding_profile") or "AUTO").upper().strip() or "AUTO"
    return {
        "holding_profile": profile,
        "overnight_relevant": bool(
            holding_context.get("overnight_relevant", False)
            or profile in {"OVERNIGHT", "SWING"}
        ),
        "market_session": holding_context.get("market_session", "UNKNOWN"),
        "minutes_to_close": holding_context.get("minutes_to_close"),
    }


def _gamma_base_scores(gamma_regime, dealer_position):
    gamma_regime = str(gamma_regime or "").upper().strip()
    dealer_position = str(dealer_position or "").upper().strip()

    acceleration = 0.0
    pinning = 0.0

    if gamma_regime in {"SHORT_GAMMA_ZONE", "NEGATIVE_GAMMA"}:
        acceleration += 0.7
    elif gamma_regime in {"LONG_GAMMA_ZONE", "POSITIVE_GAMMA"}:
        pinning += 0.65

    if dealer_position == "SHORT GAMMA":
        acceleration += 0.25
    elif dealer_position == "LONG GAMMA":
        pinning += 0.25

    return round(_clip(acceleration, 0.0, 1.0), 4), round(_clip(pinning, 0.0, 1.0), 4)


def _flip_proximity_score(gamma_flip_distance_pct, spot_vs_flip):
    spot_vs_flip = str(spot_vs_flip or "").upper().strip()
    distance = _safe_float(gamma_flip_distance_pct, None)

    if spot_vs_flip == "AT_FLIP":
        return 1.0
    if distance is None:
        if spot_vs_flip in {"ABOVE_FLIP", "BELOW_FLIP"}:
            return 0.22
        return 0.0
    if distance <= 0.10:
        return 1.0
    if distance <= 0.25:
        return 0.82
    if distance <= 0.50:
        return 0.60
    if distance <= 0.90:
        return 0.36
    return 0.10


def _bias_scores(dealer_hedging_bias):
    bias = str(dealer_hedging_bias or "").upper().strip()
    upside = 0.0
    downside = 0.0
    pinning = 0.0

    if bias == "UPSIDE_ACCELERATION":
        upside = 0.95
    elif bias == "DOWNSIDE_ACCELERATION":
        downside = 0.95
    elif bias in {"UPSIDE_PINNING", "DOWNSIDE_PINNING"}:
        pinning = 0.65
    elif bias == "PINNING":
        pinning = 0.85

    return upside, downside, pinning


def _hedging_flow_scores(dealer_hedging_flow):
    flow = str(dealer_hedging_flow or "").upper().strip()
    if flow == "BUY_FUTURES":
        return 0.55, 0.0
    if flow == "SELL_FUTURES":
        return 0.0, 0.55
    return 0.0, 0.0


def _intraday_gamma_scores(intraday_gamma_state):
    state = str(intraday_gamma_state or "").upper().strip()
    if state == "VOL_EXPANSION":
        return 0.7, 0.0
    if state == "GAMMA_DECREASE":
        return 0.55, 0.0
    if state in {"VOL_SUPPRESSION", "GAMMA_INCREASE"}:
        return 0.0, 0.5
    return 0.0, 0.0


def _flow_confirmation_scores(flow_signal, smart_money_flow):
    bullish = 0.0
    bearish = 0.0

    flow_signal = str(flow_signal or "").upper().strip()
    smart_money_flow = str(smart_money_flow or "").upper().strip()

    if flow_signal == "BULLISH_FLOW":
        bullish += 0.18
    elif flow_signal == "BEARISH_FLOW":
        bearish += 0.18

    if smart_money_flow == "BULLISH_FLOW":
        bullish += 0.18
    elif smart_money_flow == "BEARISH_FLOW":
        bearish += 0.18

    return round(_clip(bullish, 0.0, 0.4), 4), round(_clip(bearish, 0.0, 0.4), 4)


def _nearest_level_distance_pct(spot, levels):
    spot_value = _safe_float(spot, None)
    if spot_value in (None, 0):
        return None

    nearest = None
    for level in levels:
        value = _safe_float(level, None)
        if value is None:
            continue
        distance_pct = abs(value - spot_value) / spot_value * 100.0
        if nearest is None or distance_pct < nearest:
            nearest = distance_pct
    return nearest


def _structure_scores(spot, support_wall, resistance_wall, gamma_clusters, liquidity_levels, liquidity_vacuum_state):
    levels = []
    for level in [support_wall, resistance_wall]:
        if level is not None:
            levels.append(level)
    for bucket in [gamma_clusters or [], liquidity_levels or []]:
        levels.extend(bucket)

    nearest_level_distance_pct = _nearest_level_distance_pct(spot, levels)
    concentration_score = 0.0
    if nearest_level_distance_pct is not None:
        if nearest_level_distance_pct <= 0.12:
            concentration_score = 0.9
        elif nearest_level_distance_pct <= 0.25:
            concentration_score = 0.72
        elif nearest_level_distance_pct <= 0.50:
            concentration_score = 0.45
        else:
            concentration_score = 0.15

    vacuum_state = str(liquidity_vacuum_state or "").upper().strip()
    vacuum_score = {
        "BREAKOUT_ZONE": 0.9,
        "NEAR_VACUUM": 0.7,
        "VACUUM_WATCH": 0.45,
    }.get(vacuum_state, 0.0)

    acceleration_structure = _clip(vacuum_score * (1.0 - (concentration_score * 0.55)), 0.0, 1.0)
    pinning_structure = _clip((0.65 * concentration_score) + (0.15 if len(levels) >= 4 else 0.0), 0.0, 1.0)
    return round(acceleration_structure, 4), round(pinning_structure, 4), nearest_level_distance_pct


def _macro_global_boost(macro_event_risk_score, global_risk_state, volatility_explosion_probability, gamma_vol_acceleration_score):
    macro_norm = _clip(_safe_float(macro_event_risk_score, 0.0) / 100.0, 0.0, 1.0)
    state = (
        global_risk_state.get("global_risk_state")
        if isinstance(global_risk_state, dict)
        else global_risk_state
    )
    state = str(state or "").upper().strip()
    global_boost = {
        "VOL_SHOCK": 1.0,
        "EVENT_LOCKDOWN": 0.9,
        "RISK_OFF": 0.55,
        "GLOBAL_NEUTRAL": 0.12,
        "RISK_ON": 0.0,
    }.get(state, 0.08)
    volatility_boost = _clip(_safe_float(volatility_explosion_probability, 0.0), 0.0, 1.0)
    gamma_vol_boost = _clip(_safe_float(gamma_vol_acceleration_score, 0.0) / 100.0, 0.0, 1.0)
    return round(_clip(
        (0.40 * macro_norm)
        + (0.25 * global_boost)
        + (0.20 * volatility_boost)
        + (0.15 * gamma_vol_boost),
        0.0,
        1.0,
    ), 4)


def build_dealer_hedging_pressure_features(
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
    holding_context = _holding_context(global_risk_state, holding_profile)

    feature_inputs = {
        "gamma_regime": gamma_regime,
        "spot_vs_flip": spot_vs_flip,
        "gamma_flip_distance_pct": gamma_flip_distance_pct,
        "dealer_position": dealer_position,
        "dealer_hedging_bias": dealer_hedging_bias,
        "dealer_hedging_flow": dealer_hedging_flow,
        "liquidity_vacuum_state": liquidity_vacuum_state,
        "intraday_gamma_state": intraday_gamma_state,
        "flow_signal": flow_signal,
        "smart_money_flow": smart_money_flow,
        "macro_event_risk_score": macro_event_risk_score,
        "global_risk_state": (
            global_risk_state.get("global_risk_state")
            if isinstance(global_risk_state, dict)
            else global_risk_state
        ),
    }
    input_availability = {
        key: value not in (None, "", "UNKNOWN")
        for key, value in feature_inputs.items()
    }
    coverage_ratio = round(sum(1 for value in input_availability.values() if value) / max(len(input_availability), 1), 4)
    feature_confidence = _clip(coverage_ratio, 0.0, 1.0)

    gamma_acceleration_base, gamma_pinning_base = _gamma_base_scores(gamma_regime, dealer_position)
    flip_proximity_score = _flip_proximity_score(gamma_flip_distance_pct, spot_vs_flip)
    bias_up, bias_down, bias_pinning = _bias_scores(dealer_hedging_bias)
    flow_up, flow_down = _hedging_flow_scores(dealer_hedging_flow)
    intraday_instability_score, intraday_pinning_score = _intraday_gamma_scores(intraday_gamma_state)
    bullish_flow_confirmation, bearish_flow_confirmation = _flow_confirmation_scores(flow_signal, smart_money_flow)
    acceleration_structure_score, pinning_structure_score, nearest_level_distance_pct = _structure_scores(
        spot,
        support_wall,
        resistance_wall,
        gamma_clusters,
        liquidity_levels,
        liquidity_vacuum_state,
    )
    far_level_dampener = 0.0
    if nearest_level_distance_pct is not None:
        if nearest_level_distance_pct > 0.60:
            far_level_dampener = 0.35
        elif nearest_level_distance_pct > 0.35:
            far_level_dampener = 0.18
    macro_global_boost = _macro_global_boost(
        macro_event_risk_score,
        global_risk_state,
        volatility_explosion_probability,
        gamma_vol_acceleration_score,
    )
    intraday_range_score = _clip(_safe_float(intraday_range_pct, 0.0) / 1.2, 0.0, 1.0)
    gamma_vol_overlay = _clip(_safe_float(gamma_vol_acceleration_score, 0.0) / 100.0, 0.0, 1.0)

    acceleration_base = _clip(
        (0.42 * gamma_acceleration_base)
        + (0.24 * flip_proximity_score)
        + (0.18 * acceleration_structure_score)
        + (0.10 * intraday_instability_score)
        + (0.06 * intraday_range_score),
        0.0,
        1.0,
    )
    pinning_base = _clip(
        (0.48 * gamma_pinning_base)
        + (0.22 * bias_pinning)
        + (0.22 * pinning_structure_score)
        + (0.08 * intraday_pinning_score),
        0.0,
        1.0,
    )

    upside_hedging_pressure = round(_clip(
        (0.38 * acceleration_base)
        + (0.20 * bias_up)
        + (0.10 * flow_up)
        + (0.10 * bullish_flow_confirmation)
        + (0.08 * macro_global_boost)
        + (0.08 * gamma_vol_overlay)
        + (0.06 * intraday_instability_score)
        - (0.24 * pinning_base),
        0.0,
        1.0,
    ) * feature_confidence, 4)
    downside_hedging_pressure = round(_clip(
        (0.38 * acceleration_base)
        + (0.20 * bias_down)
        + (0.10 * flow_down)
        + (0.10 * bearish_flow_confirmation)
        + (0.08 * macro_global_boost)
        + (0.08 * gamma_vol_overlay)
        + (0.06 * intraday_instability_score)
        - (0.24 * pinning_base),
        0.0,
        1.0,
    ) * feature_confidence, 4)
    pinning_pressure_score = round(_clip(
        (0.52 * pinning_base)
        + (0.12 * bias_pinning)
        + (0.12 * pinning_structure_score)
        + (0.10 * max(0.0, 1.0 - flip_proximity_score))
        + (0.08 * max(0.0, 1.0 - gamma_vol_overlay))
        + (0.06 * intraday_pinning_score)
        - (0.24 * acceleration_base)
        - (0.25 * far_level_dampener),
        0.0,
        1.0,
    ) * feature_confidence, 4)
    two_sided_instability = round(min(upside_hedging_pressure, downside_hedging_pressure), 4)
    normalized_pressure = round(_clip(
        (0.48 * max(upside_hedging_pressure, downside_hedging_pressure))
        + (0.20 * two_sided_instability)
        + (0.14 * pinning_pressure_score)
        + (0.18 * acceleration_base),
        0.0,
        1.0,
    ), 4)
    overnight_hedging_risk = round(_clip(
        (0.34 * max(upside_hedging_pressure, downside_hedging_pressure))
        + (0.20 * two_sided_instability)
        + (0.16 * macro_global_boost)
        + (0.15 * gamma_vol_overlay)
        + (0.10 * _clip(_safe_float(macro_event_risk_score, 0.0) / 100.0, 0.0, 1.0))
        + (0.05 * (1.0 if holding_context["overnight_relevant"] else 0.0)),
        0.0,
        1.0,
    ), 4)

    warnings = []
    if feature_confidence < 0.55:
        warnings.append("dealer_pressure_partial_input_coverage")
    if gamma_regime is None:
        warnings.append("gamma_regime_missing")
    if dealer_hedging_bias is None:
        warnings.append("dealer_hedging_bias_missing")

    return {
        "spot": _safe_float(spot, None),
        "gamma_regime": gamma_regime,
        "spot_vs_flip": spot_vs_flip,
        "gamma_flip_distance_pct": _safe_float(gamma_flip_distance_pct, None),
        "dealer_position": dealer_position,
        "dealer_hedging_bias": dealer_hedging_bias,
        "dealer_hedging_flow": dealer_hedging_flow,
        "market_gamma": market_gamma,
        "gamma_clusters": list(gamma_clusters or []),
        "liquidity_levels": list(liquidity_levels or []),
        "support_wall": support_wall,
        "resistance_wall": resistance_wall,
        "liquidity_vacuum_state": liquidity_vacuum_state,
        "intraday_gamma_state": intraday_gamma_state,
        "intraday_range_pct": _safe_float(intraday_range_pct, None),
        "flow_signal": flow_signal,
        "smart_money_flow": smart_money_flow,
        "macro_event_risk_score": _safe_int(macro_event_risk_score, 0),
        "global_risk_state": (
            str(global_risk_state.get("global_risk_state"))
            if isinstance(global_risk_state, dict)
            else str(global_risk_state or "GLOBAL_NEUTRAL")
        ).upper().strip() or "GLOBAL_NEUTRAL",
        "volatility_explosion_probability": round(_clip(_safe_float(volatility_explosion_probability, 0.0), 0.0, 1.0), 4),
        "gamma_vol_acceleration_score": _safe_int(gamma_vol_acceleration_score, 0),
        "holding_context": holding_context,
        "input_availability": input_availability,
        "feature_confidence": round(feature_confidence, 4),
        "gamma_acceleration_base": gamma_acceleration_base,
        "gamma_pinning_base": gamma_pinning_base,
        "flip_proximity_score": round(flip_proximity_score, 4),
        "bias_up_score": round(bias_up, 4),
        "bias_down_score": round(bias_down, 4),
        "bias_pinning_score": round(bias_pinning, 4),
        "flow_up_score": round(flow_up, 4),
        "flow_down_score": round(flow_down, 4),
        "bullish_flow_confirmation": bullish_flow_confirmation,
        "bearish_flow_confirmation": bearish_flow_confirmation,
        "intraday_instability_score": round(intraday_instability_score, 4),
        "intraday_pinning_score": round(intraday_pinning_score, 4),
        "acceleration_structure_score": acceleration_structure_score,
        "pinning_structure_score": pinning_structure_score,
        "nearest_level_distance_pct": nearest_level_distance_pct,
        "far_level_dampener": round(far_level_dampener, 4),
        "macro_global_boost": macro_global_boost,
        "acceleration_base": round(acceleration_base, 4),
        "pinning_base": round(pinning_base, 4),
        "upside_hedging_pressure": upside_hedging_pressure,
        "downside_hedging_pressure": downside_hedging_pressure,
        "pinning_pressure_score": pinning_pressure_score,
        "normalized_pressure": normalized_pressure,
        "overnight_hedging_risk": overnight_hedging_risk,
        "neutral_fallback": feature_confidence == 0.0,
        "warnings": warnings,
    }

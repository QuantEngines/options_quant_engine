"""
Deterministic raw feature model for the gamma-vol acceleration overlay.
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


def _gamma_regime_score(gamma_regime):
    gamma_regime = str(gamma_regime or "").upper().strip()
    if gamma_regime in {"SHORT_GAMMA_ZONE", "NEGATIVE_GAMMA"}:
        return 0.85
    if gamma_regime in {"LONG_GAMMA_ZONE", "POSITIVE_GAMMA"}:
        return -0.55
    return 0.0


def _flip_proximity_score(gamma_flip_distance_pct, spot_vs_flip):
    spot_vs_flip = str(spot_vs_flip or "").upper().strip()
    distance = _safe_float(gamma_flip_distance_pct, None)

    if spot_vs_flip == "AT_FLIP":
        return 1.0

    if distance is None:
        if spot_vs_flip in {"ABOVE_FLIP", "BELOW_FLIP"}:
            return 0.25
        return 0.0

    if distance <= 0.10:
        return 1.0
    if distance <= 0.25:
        return 0.82
    if distance <= 0.50:
        return 0.62
    if distance <= 0.90:
        return 0.38
    return 0.12


def _volatility_transition_score(volatility_compression_score, volatility_shock_score, volatility_explosion_probability):
    compression = _clip(_safe_float(volatility_compression_score, 0.0), 0.0, 1.0)
    shock = _clip(_safe_float(volatility_shock_score, 0.0), 0.0, 1.0)
    explosion = _clip(_safe_float(volatility_explosion_probability, 0.0), 0.0, 1.0)
    return round(_clip((0.45 * compression) + (0.30 * shock) + (0.25 * explosion), 0.0, 1.0), 4)


def _liquidity_vacuum_score(liquidity_vacuum_state):
    mapping = {
        "BREAKOUT_ZONE": 0.9,
        "NEAR_VACUUM": 0.7,
        "VACUUM_WATCH": 0.45,
        "VACUUM_CONTAINED": 0.2,
        "NO_VACUUM": 0.0,
    }
    return mapping.get(str(liquidity_vacuum_state or "").upper().strip(), 0.0)


def _hedging_bias_score(dealer_hedging_bias):
    bias = str(dealer_hedging_bias or "").upper().strip()
    if bias == "UPSIDE_ACCELERATION":
        return 0.9
    if bias == "DOWNSIDE_ACCELERATION":
        return -0.9
    if bias == "UPSIDE_PINNING":
        return 0.15
    if bias == "DOWNSIDE_PINNING":
        return -0.15
    if bias == "PINNING":
        return 0.0
    return 0.0


def _pinning_dampener(dealer_hedging_bias):
    bias = str(dealer_hedging_bias or "").upper().strip()
    if bias == "PINNING":
        return 0.45
    if bias in {"UPSIDE_PINNING", "DOWNSIDE_PINNING"}:
        return 0.25
    return 0.0


def _intraday_extension_score(intraday_range_pct):
    value = _safe_float(intraday_range_pct, None)
    if value is None:
        return 0.0
    if value <= 0.35:
        return 0.0
    if value <= 0.70:
        return 0.25
    if value <= 1.00:
        return 0.45
    return 0.65


def _macro_global_boost(macro_event_risk_score, global_risk_state, volatility_explosion_probability):
    event_norm = _clip(_safe_float(macro_event_risk_score, 0.0) / 100.0, 0.0, 1.0)
    state = str(global_risk_state or "").upper().strip()
    global_state_boost = {
        "VOL_SHOCK": 1.0,
        "EVENT_LOCKDOWN": 0.95,
        "RISK_OFF": 0.60,
        "GLOBAL_NEUTRAL": 0.15,
        "RISK_ON": 0.0,
    }.get(state, 0.10)
    explosion = _clip(_safe_float(volatility_explosion_probability, 0.0), 0.0, 1.0)
    return round(_clip((0.45 * event_norm) + (0.30 * global_state_boost) + (0.25 * explosion), 0.0, 1.0), 4)


def build_gamma_vol_acceleration_features(
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
    holding_context = _holding_context(global_risk_state, holding_profile)
    global_state_label = (
        global_risk_state.get("global_risk_state")
        if isinstance(global_risk_state, dict)
        else global_risk_state
    )

    feature_inputs = {
        "gamma_regime": gamma_regime,
        "spot_vs_flip": spot_vs_flip,
        "gamma_flip_distance_pct": gamma_flip_distance_pct,
        "dealer_hedging_bias": dealer_hedging_bias,
        "liquidity_vacuum_state": liquidity_vacuum_state,
        "intraday_range_pct": intraday_range_pct,
        "volatility_compression_score": volatility_compression_score,
        "volatility_shock_score": volatility_shock_score,
        "macro_event_risk_score": macro_event_risk_score,
        "global_risk_state": global_state_label,
        "volatility_explosion_probability": volatility_explosion_probability,
    }
    input_availability = {
        key: value not in (None, "", "UNKNOWN")
        for key, value in feature_inputs.items()
    }
    coverage_ratio = round(sum(1 for value in input_availability.values() if value) / max(len(input_availability), 1), 4)
    feature_confidence = _clip(coverage_ratio, 0.0, 1.0)

    gamma_regime_score = _gamma_regime_score(gamma_regime)
    flip_proximity_score = _flip_proximity_score(gamma_flip_distance_pct, spot_vs_flip)
    volatility_transition_score = _volatility_transition_score(
        volatility_compression_score,
        volatility_shock_score,
        volatility_explosion_probability,
    )
    liquidity_vacuum_score = _liquidity_vacuum_score(liquidity_vacuum_state)
    hedging_bias_score = _hedging_bias_score(dealer_hedging_bias)
    pinning_dampener = _pinning_dampener(dealer_hedging_bias)
    intraday_extension_score = _intraday_extension_score(intraday_range_pct)
    macro_global_boost = _macro_global_boost(
        macro_event_risk_score,
        global_state_label,
        volatility_explosion_probability,
    )

    positive_gamma_pressure = max(gamma_regime_score, 0.0)
    gamma_dampener = max(-gamma_regime_score, 0.0)
    acceleration_core = _clip(
        (0.34 * positive_gamma_pressure)
        + (0.18 * flip_proximity_score)
        + (0.16 * volatility_transition_score)
        + (0.12 * liquidity_vacuum_score)
        + (0.10 * abs(hedging_bias_score))
        + (0.05 * intraday_extension_score)
        + (0.05 * macro_global_boost),
        0.0,
        1.0,
    )
    dampening_core = _clip(
        (0.60 * gamma_dampener)
        + (0.40 * pinning_dampener),
        0.0,
        1.0,
    )
    normalized_acceleration = _clip((acceleration_core - (0.50 * dampening_core)) * feature_confidence, 0.0, 1.0)

    spot_vs_flip_label = str(spot_vs_flip or "").upper().strip()
    upside_alignment = 0.0
    downside_alignment = 0.0
    if spot_vs_flip_label == "ABOVE_FLIP":
        upside_alignment += 0.18
    elif spot_vs_flip_label == "BELOW_FLIP":
        downside_alignment += 0.18
    elif spot_vs_flip_label == "AT_FLIP":
        upside_alignment += 0.08
        downside_alignment += 0.08

    if hedging_bias_score > 0:
        upside_alignment += min(0.24, hedging_bias_score * 0.24)
    elif hedging_bias_score < 0:
        downside_alignment += min(0.24, abs(hedging_bias_score) * 0.24)

    upside_squeeze_risk = round(_clip(
        (0.40 * positive_gamma_pressure)
        + (0.18 * flip_proximity_score)
        + (0.16 * volatility_transition_score)
        + (0.10 * liquidity_vacuum_score)
        + (0.06 * intraday_extension_score)
        + (0.10 * macro_global_boost)
        + upside_alignment
        - (0.28 * dampening_core),
        0.0,
        1.0,
    ) * feature_confidence, 4)
    downside_airpocket_risk = round(_clip(
        (0.40 * positive_gamma_pressure)
        + (0.18 * flip_proximity_score)
        + (0.16 * volatility_transition_score)
        + (0.10 * liquidity_vacuum_score)
        + (0.06 * intraday_extension_score)
        + (0.10 * macro_global_boost)
        + downside_alignment
        - (0.28 * dampening_core),
        0.0,
        1.0,
    ) * feature_confidence, 4)
    overnight_convexity_risk = round(_clip(
        (0.28 * normalized_acceleration)
        + (0.20 * _clip(_safe_float(volatility_explosion_probability, 0.0), 0.0, 1.0))
        + (0.18 * _clip(_safe_float(macro_event_risk_score, 0.0) / 100.0, 0.0, 1.0))
        + (0.14 * max(upside_squeeze_risk, downside_airpocket_risk))
        + (0.10 * macro_global_boost)
        + (0.10 * (1.0 if holding_context["overnight_relevant"] else 0.0))
        - (0.22 * dampening_core),
        0.0,
        1.0,
    ), 4)

    warnings = []
    if feature_confidence < 0.55:
        warnings.append("gamma_vol_partial_input_coverage")
    if gamma_regime is None:
        warnings.append("gamma_regime_missing")
    if gamma_flip_distance_pct is None and spot_vs_flip not in {"AT_FLIP", "ABOVE_FLIP", "BELOW_FLIP"}:
        warnings.append("flip_context_missing")

    return {
        "gamma_regime": gamma_regime,
        "spot_vs_flip": spot_vs_flip,
        "gamma_flip_distance_pct": _safe_float(gamma_flip_distance_pct, None),
        "dealer_hedging_bias": dealer_hedging_bias,
        "liquidity_vacuum_state": liquidity_vacuum_state,
        "intraday_range_pct": _safe_float(intraday_range_pct, None),
        "volatility_compression_score": round(_clip(_safe_float(volatility_compression_score, 0.0), 0.0, 1.0), 4),
        "volatility_shock_score": round(_clip(_safe_float(volatility_shock_score, 0.0), 0.0, 1.0), 4),
        "macro_event_risk_score": _safe_int(macro_event_risk_score, 0),
        "global_risk_state": str(global_state_label or "GLOBAL_NEUTRAL").upper().strip() or "GLOBAL_NEUTRAL",
        "volatility_explosion_probability": round(_clip(_safe_float(volatility_explosion_probability, 0.0), 0.0, 1.0), 4),
        "support_wall_available": support_wall is not None,
        "resistance_wall_available": resistance_wall is not None,
        "holding_context": holding_context,
        "input_availability": input_availability,
        "feature_confidence": round(feature_confidence, 4),
        "gamma_regime_score": round(gamma_regime_score, 4),
        "flip_proximity_score": round(flip_proximity_score, 4),
        "volatility_transition_score": round(volatility_transition_score, 4),
        "liquidity_vacuum_score": round(liquidity_vacuum_score, 4),
        "hedging_bias_score": round(hedging_bias_score, 4),
        "pinning_dampener": round(pinning_dampener, 4),
        "intraday_extension_score": round(intraday_extension_score, 4),
        "macro_global_boost": round(macro_global_boost, 4),
        "acceleration_core": round(acceleration_core, 4),
        "dampening_core": round(dampening_core, 4),
        "normalized_acceleration": round(normalized_acceleration, 4),
        "upside_squeeze_risk": upside_squeeze_risk,
        "downside_airpocket_risk": downside_airpocket_risk,
        "overnight_convexity_risk": overnight_convexity_risk,
        "neutral_fallback": feature_confidence == 0.0,
        "warnings": warnings,
    }

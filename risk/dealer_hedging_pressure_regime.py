"""
Interpretable regime classifier for dealer hedging pressure.
"""

from __future__ import annotations

from config.dealer_hedging_pressure_policy import get_dealer_hedging_pressure_policy_config
from risk.dealer_hedging_pressure_models import DealerHedgingPressureState


def _clip(value, lo, hi):
    return max(lo, min(hi, value))


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _state(upside_hedging_pressure, downside_hedging_pressure, pinning_pressure_score):
    cfg = get_dealer_hedging_pressure_policy_config()
    upside = _clip(_safe_float(upside_hedging_pressure, 0.0), 0.0, 1.0)
    downside = _clip(_safe_float(downside_hedging_pressure, 0.0), 0.0, 1.0)
    pinning = _clip(_safe_float(pinning_pressure_score, 0.0), 0.0, 1.0)

    if pinning >= cfg.pinning_pressure_threshold and pinning > max(upside, downside) + 0.08:
        return "PINNING_DOMINANT"
    if upside >= cfg.upside_pressure_threshold and upside > downside + cfg.state_balance_tolerance:
        return "UPSIDE_HEDGING_ACCELERATION"
    if downside >= cfg.downside_pressure_threshold and downside > upside + cfg.state_balance_tolerance:
        return "DOWNSIDE_HEDGING_ACCELERATION"
    if upside >= cfg.two_sided_threshold and downside >= cfg.two_sided_threshold:
        return "TWO_SIDED_INSTABILITY"
    if (
        max(upside, downside) >= 0.38
        and min(upside, downside) >= 0.35
        and abs(upside - downside) <= (cfg.state_balance_tolerance + 0.02)
        and pinning < cfg.pinning_pressure_threshold
    ):
        return "TWO_SIDED_INSTABILITY"
    return "HEDGING_NEUTRAL"


def _adjustment_score(dealer_flow_state, dealer_hedging_pressure_score):
    cfg = get_dealer_hedging_pressure_policy_config()

    if dealer_flow_state == "PINNING_DOMINANT":
        return cfg.pinning_adjustment
    if dealer_flow_state == "TWO_SIDED_INSTABILITY":
        return cfg.two_sided_adjustment
    if dealer_flow_state in {"UPSIDE_HEDGING_ACCELERATION", "DOWNSIDE_HEDGING_ACCELERATION"}:
        if dealer_hedging_pressure_score >= cfg.extreme_pressure_threshold:
            return cfg.acceleration_adjustment_extreme
        if dealer_hedging_pressure_score >= cfg.high_pressure_threshold:
            return cfg.acceleration_adjustment_high
    return 0


def _overnight_evaluation(
    *,
    dealer_flow_state,
    overnight_hedging_risk,
    global_risk_state,
    macro_event_risk_score,
    overnight_relevant,
):
    cfg = get_dealer_hedging_pressure_policy_config()

    if not overnight_relevant:
        return True, "overnight_hedging_contained", 0, 0

    penalty = 0
    boost = 0
    reasons = []
    overnight_hedging_risk = _clip(_safe_float(overnight_hedging_risk, 0.0), 0.0, 1.0)
    global_state = str(global_risk_state or "").upper().strip()
    macro_event_risk_score = _safe_float(macro_event_risk_score, 0.0)

    if dealer_flow_state == "TWO_SIDED_INSTABILITY":
        penalty += 3
        reasons.append("two_sided_hedging_instability")
    elif dealer_flow_state in {"UPSIDE_HEDGING_ACCELERATION", "DOWNSIDE_HEDGING_ACCELERATION"} and overnight_hedging_risk >= 0.7:
        penalty += 2
        reasons.append("accelerating_hedging_pressure")
    elif dealer_flow_state == "PINNING_DOMINANT":
        boost = 1
        reasons.append("pinning_overnight_containment")

    if overnight_hedging_risk >= 0.78:
        penalty += 4
        reasons.append("overnight_hedging_risk_high")
    elif overnight_hedging_risk >= 0.58:
        penalty += 2
        reasons.append("overnight_hedging_risk_elevated")

    if global_state in {"VOL_SHOCK", "EVENT_LOCKDOWN"}:
        penalty += 3
        reasons.append("unstable_global_risk_regime")
    elif global_state == "RISK_OFF":
        penalty += 2
        reasons.append("risk_off_global_regime")

    if macro_event_risk_score >= 70.0:
        penalty += 2
        reasons.append("macro_event_risk_high")
    elif macro_event_risk_score >= 45.0:
        penalty += 1
        reasons.append("macro_event_risk_elevated")

    penalty = int(_clip(penalty, 0, 10))
    if penalty >= cfg.overnight_block_threshold:
        return False, reasons[0] if reasons else "overnight_hedging_block", penalty, boost
    if penalty >= cfg.overnight_watch_threshold:
        return True, reasons[0] if reasons else "overnight_hedging_watch", penalty, boost
    if boost > 0:
        return True, reasons[0], penalty, boost
    return True, "overnight_hedging_contained", 0, 0


def classify_dealer_hedging_pressure_state(features: dict | None) -> DealerHedgingPressureState:
    features = features if isinstance(features, dict) else {}

    dealer_hedging_pressure_score = int(round(_clip(_safe_float(features.get("normalized_pressure"), 0.0) * 100.0, 0.0, 100.0)))
    upside_hedging_pressure = round(_clip(_safe_float(features.get("upside_hedging_pressure"), 0.0), 0.0, 1.0), 4)
    downside_hedging_pressure = round(_clip(_safe_float(features.get("downside_hedging_pressure"), 0.0), 0.0, 1.0), 4)
    pinning_pressure_score = round(_clip(_safe_float(features.get("pinning_pressure_score"), 0.0), 0.0, 1.0), 4)
    overnight_hedging_risk = round(_clip(_safe_float(features.get("overnight_hedging_risk"), 0.0), 0.0, 1.0), 4)

    dealer_flow_state = _state(
        upside_hedging_pressure,
        downside_hedging_pressure,
        pinning_pressure_score,
    )
    dealer_pressure_adjustment_score = _adjustment_score(
        dealer_flow_state,
        dealer_hedging_pressure_score,
    )

    holding_context = features.get("holding_context", {})
    holding_context = holding_context if isinstance(holding_context, dict) else {}
    overnight_hold_allowed, overnight_hold_reason, overnight_penalty, overnight_boost = _overnight_evaluation(
        dealer_flow_state=dealer_flow_state,
        overnight_hedging_risk=overnight_hedging_risk,
        global_risk_state=features.get("global_risk_state"),
        macro_event_risk_score=features.get("macro_event_risk_score"),
        overnight_relevant=bool(holding_context.get("overnight_relevant", False)),
    )

    reasons = []
    if features.get("neutral_fallback"):
        reasons.append("dealer_pressure_neutral_fallback")
    if dealer_flow_state != "HEDGING_NEUTRAL":
        reasons.append(dealer_flow_state.lower())
    if not reasons:
        reasons.append("dealer_pressure_contained")

    diagnostics = {
        "feature_confidence": round(_safe_float(features.get("feature_confidence"), 0.0), 4),
        "input_availability": dict(features.get("input_availability", {})),
        "gamma_acceleration_base": round(_safe_float(features.get("gamma_acceleration_base"), 0.0), 4),
        "gamma_pinning_base": round(_safe_float(features.get("gamma_pinning_base"), 0.0), 4),
        "flip_proximity_score": round(_safe_float(features.get("flip_proximity_score"), 0.0), 4),
        "acceleration_structure_score": round(_safe_float(features.get("acceleration_structure_score"), 0.0), 4),
        "pinning_structure_score": round(_safe_float(features.get("pinning_structure_score"), 0.0), 4),
        "nearest_level_distance_pct": features.get("nearest_level_distance_pct"),
        "far_level_dampener": round(_safe_float(features.get("far_level_dampener"), 0.0), 4),
        "macro_global_boost": round(_safe_float(features.get("macro_global_boost"), 0.0), 4),
        "warnings": list(features.get("warnings", [])),
    }

    return DealerHedgingPressureState(
        dealer_hedging_pressure_score=dealer_hedging_pressure_score,
        dealer_flow_state=dealer_flow_state,
        upside_hedging_pressure=upside_hedging_pressure,
        downside_hedging_pressure=downside_hedging_pressure,
        pinning_pressure_score=pinning_pressure_score,
        overnight_hedging_risk=overnight_hedging_risk,
        overnight_hold_allowed=overnight_hold_allowed,
        overnight_hold_reason=overnight_hold_reason,
        overnight_dealer_pressure_penalty=overnight_penalty,
        overnight_dealer_pressure_boost=overnight_boost,
        dealer_pressure_adjustment_score=dealer_pressure_adjustment_score,
        neutral_fallback=bool(features.get("neutral_fallback", False)),
        dealer_pressure_reasons=reasons,
        dealer_pressure_features=features,
        dealer_pressure_diagnostics=diagnostics,
    )

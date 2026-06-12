"""Live-safe research bridge between runtime and ex-post composite quality.

This module intentionally stays in the research layer.  It uses only fields
that are available at signal-capture time and produces diagnostics that can be
compared with the matured ex-post `composite_signal_score` later.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


DECISION_QUALITY_BRIDGE_VERSION = "decision_quality_bridge_v1"

COMPONENT_WEIGHTS = {
    "signal_intensity": 0.65,
    "runtime_quality": 0.25,
    "tradeability": 0.10,
    # Captured as diagnostics, but held at zero weight until forward evidence
    # shows stable incremental value over trade strength + runtime composite.
    "probability": 0.0,
    "timing": 0.0,
    "price_structure": 0.0,
    "provider_data": 0.0,
    "regime_context": 0.0,
}

PENALTY_MULTIPLIER = 0.25


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _clip(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _text(value: Any, default: str = "UNKNOWN") -> str:
    token = str(value if value not in (None, "") else default).strip().upper()
    return token or default


def _truthy(value: Any) -> bool:
    return str(value if value is not None else "").strip().upper() in {"1", "1.0", "TRUE", "T", "YES", "Y"}


def _mean_available(*values: Any) -> float | None:
    numbers = [_safe_float(value, None) for value in values]
    numbers = [number for number in numbers if number is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _probability_0_100(row: Mapping[str, Any]) -> float | None:
    for field in ("hybrid_move_probability", "move_probability", "rule_move_probability", "ml_move_probability"):
        value = _safe_float(row.get(field), None)
        if value is None:
            continue
        if value <= 1.5:
            value *= 100.0
        return _clip(value)
    return None


def _timing_score(row: Mapping[str, Any]) -> float | None:
    score = _safe_float(row.get("ta_entry_timing_score"), None)
    state = _text(row.get("ta_entry_timing_state"))
    candle_state = _text(row.get("ta_candle_state"))
    if score is None:
        if "LATE_CHASE" in state or _truthy(row.get("ta_candle_late_chase")):
            score = 32.0
        elif "CONFIRMED" in state:
            score = 72.0
        elif "REJECTION" in state:
            score = 64.0
        elif "FORMING" in state:
            score = 48.0
        elif state not in {"UNKNOWN", "CANDLE_UNAVAILABLE"}:
            score = 50.0
    if score is None and candle_state not in {"UNKNOWN", "NONE"}:
        if "LATE_CHASE" in candle_state:
            score = 32.0
        elif "CONFIRMED" in candle_state:
            score = 70.0
        elif "REJECTION" in candle_state:
            score = 62.0
    if score is None:
        return None
    if "LATE_CHASE" in state or _truthy(row.get("ta_candle_late_chase")):
        score = min(score, 38.0)
    return _clip(score)


def _price_structure_score(row: Mapping[str, Any]) -> float | None:
    confluence = _safe_float(row.get("price_level_confluence_score"), None)
    trend = _safe_float(row.get("price_structure_trend_day_proxy_score"), None)
    acceptance = _text(row.get("price_structure_acceptance_state"))
    anchor_distance = abs(_safe_float(row.get("nearest_price_structure_anchor_distance_pct"), 999.0) or 999.0)

    acceptance_score = None
    if "ACCEPT" in acceptance or "RECLAIM" in acceptance or "BREAKOUT" in acceptance:
        acceptance_score = 68.0
    elif "REJECT" in acceptance or "FAIL" in acceptance:
        acceptance_score = 60.0
    elif "BALANCED" in acceptance or "ROTATION" in acceptance:
        acceptance_score = 48.0

    anchor_score = None
    if anchor_distance != 999.0:
        if anchor_distance <= 0.10:
            anchor_score = 64.0
        elif anchor_distance <= 0.30:
            anchor_score = 58.0
        else:
            anchor_score = 50.0

    return _mean_available(confluence, trend, acceptance_score, anchor_score)


def _tradeability_score(row: Mapping[str, Any]) -> float | None:
    return _mean_available(
        row.get("option_efficiency_score"),
        row.get("target_reachability_score"),
        row.get("premium_efficiency_score"),
        row.get("strike_efficiency_score"),
    )


def _provider_data_score(row: Mapping[str, Any]) -> float | None:
    status_scores = {
        "STRONG": 100.0,
        "GOOD": 88.0,
        "PASS": 88.0,
        "OK": 84.0,
        "CAUTION": 62.0,
        "FRAGILE": 48.0,
        "WEAK": 36.0,
        "BLOCK": 24.0,
        "BLOCKED": 24.0,
        "FAIL": 20.0,
    }
    values = []
    for field in ("data_quality_status", "provider_health_status", "provider_analytics_status", "provider_execution_status"):
        token = _text(row.get(field))
        if token in status_scores:
            values.append(status_scores[token])
        elif "USABLE" in token:
            values.append(82.0)
        elif "BLOCK" in token:
            values.append(24.0)
    if _truthy(row.get("execution_suggestion_usable")):
        values.append(84.0)
    if _truthy(row.get("provider_quality_blocks_direction")):
        values.append(20.0)
    if not values:
        return None
    return _clip(sum(values) / len(values))


def _regime_context_score(row: Mapping[str, Any]) -> float | None:
    regime_fields = ("gamma_regime", "spot_vs_flip", "macro_regime", "global_risk_state", "volatility_regime")
    if all(row.get(field) in (None, "") for field in regime_fields):
        return None

    score = 54.0
    gamma = _text(row.get("gamma_regime"))
    spot_flip = _text(row.get("spot_vs_flip"))
    macro = _text(row.get("macro_regime"))
    global_risk = _text(row.get("global_risk_state"))
    vol = _text(row.get("volatility_regime"))

    if gamma == "POSITIVE_GAMMA":
        score += 3.0
    elif gamma == "NEGATIVE_GAMMA":
        score -= 2.0
    elif gamma == "NEUTRAL_GAMMA":
        score -= 1.0

    if spot_flip == "AT_FLIP":
        score -= 7.0
    elif spot_flip in {"ABOVE_FLIP", "BELOW_FLIP"}:
        score += 2.0

    if "RISK_OFF" in macro:
        score -= 4.0
    if "RISK_OFF" in global_risk:
        score -= 4.0
    if "LOW_VOL" in vol:
        score -= 2.0
    if "HIGH" in vol or "EXPANSION" in vol:
        score += 2.0
    return _clip(score)


def _penalties(row: Mapping[str, Any]) -> dict[str, float]:
    penalties: dict[str, float] = {}
    if _truthy(row.get("provider_quality_blocks_direction")):
        penalties["provider_direction_block"] = 15.0
    if _truthy(row.get("provider_quality_blocks_execution")):
        penalties["provider_execution_block"] = 4.0
    if _text(row.get("spot_vs_flip")) == "AT_FLIP":
        penalties["at_flip_chop"] = 4.0
    if "RISK_OFF" in _text(row.get("macro_regime")):
        penalties["macro_risk_off"] = 3.0
    if "RISK_OFF" in _text(row.get("global_risk_state")):
        penalties["global_risk_off"] = 3.0
    if _truthy(row.get("ta_candle_late_chase")) or "LATE_CHASE" in _text(row.get("ta_entry_timing_state")):
        penalties["late_chase"] = 8.0
    for field in ("data_quality_status", "provider_health_status"):
        token = _text(row.get(field))
        if token in {"WEAK", "BLOCK", "BLOCKED", "FAIL"}:
            penalties[f"{field.lower()}_weak"] = 5.0
    return penalties


def compute_decision_quality_bridge(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a research-only live-safe decision-quality score payload."""
    components = {
        "signal_intensity": _safe_float(row.get("trade_strength"), None),
        "runtime_quality": _safe_float(row.get("runtime_composite_score"), None),
        "probability": _probability_0_100(row),
        "timing": _timing_score(row),
        "tradeability": _tradeability_score(row),
        "price_structure": _price_structure_score(row),
        "provider_data": _provider_data_score(row),
        "regime_context": _regime_context_score(row),
    }
    usable = {name: _clip(float(value)) for name, value in components.items() if value is not None}
    weight_sum = sum(COMPONENT_WEIGHTS[name] for name in usable)
    if weight_sum <= 0:
        return {
            "version": DECISION_QUALITY_BRIDGE_VERSION,
            "research_only": True,
            "live_safe": True,
            "score": None,
            "raw_score": None,
            "available_components": [],
            "missing_components": sorted(set(COMPONENT_WEIGHTS) - set(usable)),
            "components": {},
            "contributions": {},
            "penalties": {},
            "penalty_total": 0.0,
            "primary_drivers": [],
        }

    contributions = {
        name: {
            "score": round(value, 4),
            "weight": round(COMPONENT_WEIGHTS[name] / weight_sum, 6),
            "weighted_contribution": round(value * COMPONENT_WEIGHTS[name] / weight_sum, 4),
        }
        for name, value in usable.items()
    }
    raw_score = sum(item["weighted_contribution"] for item in contributions.values())
    penalties = _penalties(row)
    raw_penalty_total = min(35.0, sum(penalties.values()))
    penalty_total = raw_penalty_total * PENALTY_MULTIPLIER
    final_score = _clip(raw_score - penalty_total)
    primary_drivers = [
        name
        for name in sorted(
            contributions,
            key=lambda key: contributions[key]["weighted_contribution"],
            reverse=True,
        )
        if contributions[name]["weighted_contribution"] > 0
    ][:3]

    return {
        "version": DECISION_QUALITY_BRIDGE_VERSION,
        "research_only": True,
        "live_safe": True,
        "score": int(round(final_score)),
        "raw_score": round(raw_score, 4),
        "available_components": sorted(usable),
        "missing_components": sorted(set(COMPONENT_WEIGHTS) - set(usable)),
        "components": {name: round(value, 4) for name, value in usable.items()},
        "contributions": contributions,
        "penalties": {name: round(value, 4) for name, value in penalties.items()},
        "penalty_multiplier": PENALTY_MULTIPLIER,
        "raw_penalty_total": round(raw_penalty_total, 4),
        "penalty_total": round(penalty_total, 4),
        "primary_drivers": primary_drivers,
    }

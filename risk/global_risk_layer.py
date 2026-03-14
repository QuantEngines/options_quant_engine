"""
Backward-compatible facade for the global risk layer.
"""

from __future__ import annotations

from risk.global_risk_features import build_global_risk_features
from risk.global_risk_regime import classify_global_risk_state


def _clip(value, lo, hi):
    return max(lo, min(hi, value))


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _event_name(active_event_name=None, next_event_name=None):
    return active_event_name or next_event_name or "scheduled macro event"


def build_global_risk_state(
    *,
    macro_event_state=None,
    macro_news_state=None,
    global_market_snapshot=None,
    holding_profile: str = "AUTO",
    as_of=None,
):
    features = build_global_risk_features(
        macro_event_state=macro_event_state,
        macro_news_state=macro_news_state,
        global_market_snapshot=global_market_snapshot,
        holding_profile=holding_profile,
        as_of=as_of,
    )
    return classify_global_risk_state(features).to_dict()


def _fallback_global_risk_state(
    *,
    event_window_status,
    macro_event_risk_score,
    event_lockdown_flag,
    next_event_name=None,
    active_event_name=None,
    holding_profile="AUTO",
):
    state = "EVENT_LOCKDOWN" if event_lockdown_flag else "GLOBAL_NEUTRAL"
    score = 100 if event_lockdown_flag else int(_clip(_safe_float(macro_event_risk_score, 0.0) * 0.5, 0.0, 100.0))
    reasons = ["event_lockdown"] if event_lockdown_flag else ["global_risk_neutral_fallback"]

    return {
        "global_risk_state": state,
        "global_risk_score": score,
        "overnight_gap_risk_score": score if event_window_status in {"PRE_EVENT_WATCH", "PRE_EVENT_LOCKDOWN", "LIVE_EVENT"} else 0,
        "volatility_expansion_risk_score": 0,
        "overnight_hold_allowed": not event_lockdown_flag,
        "overnight_hold_reason": "event_lockdown_block" if event_lockdown_flag else "overnight_risk_contained",
        "overnight_risk_penalty": 10 if event_lockdown_flag else 0,
        "global_risk_adjustment_score": -6 if event_lockdown_flag else 0,
        "global_risk_veto": bool(event_lockdown_flag),
        "global_risk_position_size_multiplier": 0.0 if event_lockdown_flag else 1.0,
        "neutral_fallback": True,
        "holding_context": {
            "holding_profile": str(holding_profile or "AUTO").upper().strip() or "AUTO",
            "overnight_relevant": False,
            "market_session": "UNKNOWN",
            "minutes_to_close": None,
        },
        "global_risk_reasons": reasons,
        "global_risk_features": {
            "event_window_status": event_window_status,
            "macro_event_risk_score": int(_safe_float(macro_event_risk_score, 0.0)),
            "event_lockdown_flag": bool(event_lockdown_flag),
            "next_event_name": next_event_name,
            "active_event_name": active_event_name,
            "oil_shock_score": 0.0,
            "gold_risk_score": 0.0,
            "copper_growth_signal": 0.0,
            "commodity_risk_score": 0.0,
            "volatility_shock_score": 0.0,
            "us_equity_risk_score": 0.0,
            "rates_shock_score": 0.0,
            "currency_shock_score": 0.0,
            "risk_off_intensity": 0.0,
            "volatility_compression_score": 0.0,
            "volatility_explosion_probability": 0.0,
        },
        "global_risk_diagnostics": {
            "event_window_status": event_window_status,
            "fallback": True,
        },
    }


def _result(*, state, score, level, action, size_cap, reasons, trade_status=None, message=None):
    state = state if isinstance(state, dict) else {}
    return {
        "global_risk_state": state.get("global_risk_state", "GLOBAL_NEUTRAL"),
        "global_risk_score": int(_clip(score, 0, 100)),
        "overnight_gap_risk_score": int(_clip(_safe_float(state.get("overnight_gap_risk_score"), 0.0), 0, 100)),
        "volatility_expansion_risk_score": int(_clip(_safe_float(state.get("volatility_expansion_risk_score"), 0.0), 0, 100)),
        "overnight_hold_allowed": bool(state.get("overnight_hold_allowed", True)),
        "overnight_hold_reason": str(state.get("overnight_hold_reason", "overnight_risk_contained")),
        "overnight_risk_penalty": int(_clip(_safe_float(state.get("overnight_risk_penalty"), 0.0), 0, 10)),
        "global_risk_adjustment_score": int(_safe_float(state.get("global_risk_adjustment_score"), 0.0)),
        "global_risk_level": level,
        "global_risk_action": action,
        "global_risk_size_cap": round(_clip(size_cap, 0.0, 1.0), 2),
        "global_risk_reasons": reasons,
        "global_risk_features": state.get("global_risk_features", {}),
        "global_risk_diagnostics": state.get("global_risk_diagnostics", {}),
        "risk_trade_status": trade_status,
        "risk_message": message,
    }


def evaluate_global_risk_layer(
    *,
    data_quality,
    confirmation,
    adjusted_trade_strength,
    min_trade_strength,
    event_window_status,
    macro_event_risk_score,
    event_lockdown_flag,
    next_event_name=None,
    active_event_name=None,
    macro_news_adjustments=None,
    global_risk_state=None,
    holding_profile="AUTO",
):
    data_quality = data_quality if isinstance(data_quality, dict) else {}
    confirmation = confirmation if isinstance(confirmation, dict) else {}
    macro_news_adjustments = macro_news_adjustments if isinstance(macro_news_adjustments, dict) else {}
    global_risk_state = global_risk_state if isinstance(global_risk_state, dict) else None

    if global_risk_state is None:
        global_risk_state = _fallback_global_risk_state(
            event_window_status=event_window_status,
            macro_event_risk_score=macro_event_risk_score,
            event_lockdown_flag=event_lockdown_flag,
            next_event_name=next_event_name,
            active_event_name=active_event_name,
            holding_profile=holding_profile,
        )

    reasons = []
    size_cap = min(
        _clip(_safe_float(macro_news_adjustments.get("macro_position_size_multiplier"), 1.0), 0.0, 1.0),
        _clip(_safe_float(global_risk_state.get("global_risk_position_size_multiplier"), 1.0), 0.0, 1.0),
    )
    score = int(round((100 - _safe_float(data_quality.get("score"), 100.0)) * 0.35))
    score += int(round(_safe_float(macro_event_risk_score, 0.0) * 0.20))
    score += int(round(_safe_float(global_risk_state.get("global_risk_score"), 0.0) * 0.45))
    score += int(round((1.0 - size_cap) * 20.0))

    if data_quality.get("fatal"):
        return _result(
            state=global_risk_state,
            score=100,
            level="BLOCKED",
            action="BLOCK",
            size_cap=0.0,
            reasons=["invalid_market_data"],
            trade_status="DATA_INVALID",
            message="Trade blocked due to invalid market data",
        )

    if event_lockdown_flag or macro_news_adjustments.get("event_lockdown_flag", False):
        return _result(
            state=global_risk_state,
            score=100,
            level="BLOCKED",
            action="BLOCK",
            size_cap=0.0,
            reasons=["event_lockdown"],
            trade_status="EVENT_LOCKDOWN",
            message=f"Trade blocked due to scheduled macro event lockdown: {_event_name(active_event_name, next_event_name)}",
        )

    if global_risk_state.get("global_risk_veto"):
        reasons.extend(global_risk_state.get("global_risk_reasons", []))
        return _result(
            state=global_risk_state,
            score=max(score, 82),
            level="HIGH",
            action="BLOCK",
            size_cap=0.0,
            reasons=reasons,
            trade_status="GLOBAL_RISK_BLOCKED",
            message="Trade blocked due to elevated global risk conditions",
        )

    holding_context = global_risk_state.get("holding_context", {})
    overnight_relevant = bool(holding_context.get("overnight_relevant", False))
    if overnight_relevant and not global_risk_state.get("overnight_hold_allowed", True):
        reasons.extend(global_risk_state.get("global_risk_reasons", []))
        overnight_hold_reason = global_risk_state.get("overnight_hold_reason")
        if overnight_hold_reason:
            reasons.append(str(overnight_hold_reason))
        return _result(
            state=global_risk_state,
            score=max(score, 70),
            level="HIGH",
            action="WATCHLIST",
            size_cap=min(size_cap, 0.5),
            reasons=reasons or ["overnight_hold_not_allowed"],
            trade_status="WATCHLIST",
            message=f"Trade downgraded due to elevated overnight risk: {global_risk_state.get('overnight_hold_reason', 'overnight_hold_not_allowed')}",
        )

    if confirmation.get("veto"):
        reasons.append("confirmation_veto")
        return _result(
            state=global_risk_state,
            score=max(score, 72),
            level="HIGH",
            action="WATCHLIST",
            size_cap=size_cap,
            reasons=reasons,
            trade_status="WATCHLIST",
            message="Trade downgraded to watchlist due to confirmation conflict",
        )

    if adjusted_trade_strength < min_trade_strength:
        reasons.append("insufficient_trade_strength")
        return _result(
            state=global_risk_state,
            score=max(score, 58),
            level="MEDIUM",
            action="WATCHLIST",
            size_cap=size_cap,
            reasons=reasons,
            trade_status="WATCHLIST",
            message="Trade filtered out due to low strength",
        )

    if _safe_float(data_quality.get("score"), 0.0) < 55:
        reasons.append("weak_data_quality")
        return _result(
            state=global_risk_state,
            score=max(score, 66),
            level="HIGH",
            action="WATCHLIST",
            size_cap=min(size_cap, 0.5),
            reasons=reasons,
            trade_status="WATCHLIST",
            message="Trade downgraded to watchlist due to weak data quality",
        )

    if data_quality.get("status") == "CAUTION" and adjusted_trade_strength < (min_trade_strength + 8):
        reasons.append("cautionary_data_quality")
        return _result(
            state=global_risk_state,
            score=max(score, 54),
            level="MEDIUM",
            action="WATCHLIST",
            size_cap=min(size_cap, 0.75),
            reasons=reasons,
            trade_status="WATCHLIST",
            message="Trade downgraded to watchlist due to cautionary data quality",
        )

    if confirmation.get("status") == "CONFLICT" and adjusted_trade_strength < (min_trade_strength + 10):
        reasons.append("live_confirmation_conflict")
        return _result(
            state=global_risk_state,
            score=max(score, 57),
            level="MEDIUM",
            action="WATCHLIST",
            size_cap=min(size_cap, 0.75),
            reasons=reasons,
            trade_status="WATCHLIST",
            message="Trade downgraded to watchlist due to weak live confirmation",
        )

    if size_cap < 0.75 and adjusted_trade_strength < (min_trade_strength + 12):
        reasons.append("global_macro_size_reduction")
        return _result(
            state=global_risk_state,
            score=max(score, 60),
            level="MEDIUM",
            action="WATCHLIST",
            size_cap=size_cap,
            reasons=reasons,
            trade_status="WATCHLIST",
            message="Trade downgraded to watchlist due to global risk reduction",
        )

    reasons.extend(global_risk_state.get("global_risk_reasons", []))
    if size_cap < 1.0:
        reasons.append("size_reduced")

    if not reasons:
        reasons.append("risk_checks_passed")

    level = "LOW"
    if score >= 60:
        level = "HIGH"
    elif score >= 35:
        level = "MEDIUM"

    return _result(
        state=global_risk_state,
        score=score,
        level=level,
        action="REDUCE" if size_cap < 1.0 else "ALLOW",
        size_cap=size_cap,
        reasons=reasons,
    )

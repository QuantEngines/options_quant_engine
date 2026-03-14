"""
Deterministic regime labeling for validation and robustness analysis.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


REGIME_COLUMNS = [
    "vol_regime_bucket",
    "gamma_regime_bucket",
    "macro_regime_bucket",
    "global_risk_bucket",
    "overnight_bucket",
    "squeeze_risk_bucket",
    "event_risk_bucket",
]


def _normalize(value: Any) -> str:
    return str(value or "").upper().strip()


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _vol_bucket(row: pd.Series) -> str:
    state = _normalize(row.get("volatility_regime"))
    global_state = _normalize(row.get("global_risk_state"))
    if global_state == "VOL_SHOCK":
        return "HIGH_VOL"
    if state in {"VOL_EXPANSION", "HIGH_VOL", "VOL_SHOCK"}:
        return "HIGH_VOL"
    if state in {"VOL_SUPPRESSION", "LOW_VOL"}:
        return "LOW_VOL"
    if state in {"NORMAL_VOL", "BALANCED_VOL"}:
        return "NORMAL_VOL"
    return "UNKNOWN_VOL"


def _gamma_bucket(row: pd.Series) -> str:
    state = _normalize(row.get("gamma_regime"))
    if state in {"NEGATIVE_GAMMA", "SHORT_GAMMA_ZONE"}:
        return "SHORT_GAMMA"
    if state in {"POSITIVE_GAMMA", "LONG_GAMMA_ZONE"}:
        return "LONG_GAMMA"
    if state in {"NEUTRAL_GAMMA"}:
        return "NEUTRAL_GAMMA"
    return "UNKNOWN_GAMMA"


def _macro_bucket(row: pd.Series) -> str:
    state = _normalize(row.get("macro_regime"))
    if state in {"EVENT_LOCKDOWN"}:
        return "EVENT_LOCKDOWN"
    if state in {"RISK_OFF"}:
        return "RISK_OFF"
    if state in {"RISK_ON"}:
        return "RISK_ON"
    if state in {"MACRO_NEUTRAL"}:
        return "MACRO_NEUTRAL"
    return "MACRO_UNKNOWN"


def _global_risk_bucket(row: pd.Series) -> str:
    state = _normalize(row.get("global_risk_state"))
    if state in {"VOL_SHOCK", "EVENT_LOCKDOWN", "RISK_OFF", "RISK_ON", "GLOBAL_NEUTRAL"}:
        return state
    return "GLOBAL_RISK_UNKNOWN"


def _overnight_bucket(row: pd.Series) -> str:
    value = row.get("overnight_hold_allowed")
    raw = str(value).strip().lower() if value is not None and str(value) != "<NA>" else ""
    if raw in {"true", "1"}:
        return "OVERNIGHT_ALLOWED"
    if raw in {"false", "0"}:
        return "OVERNIGHT_BLOCKED"
    return "OVERNIGHT_UNKNOWN"


def _squeeze_bucket(row: pd.Series) -> str:
    state = _normalize(row.get("squeeze_risk_state"))
    if state in {
        "LOW_ACCELERATION_RISK",
        "MODERATE_ACCELERATION_RISK",
        "HIGH_ACCELERATION_RISK",
        "EXTREME_ACCELERATION_RISK",
    }:
        return state

    dealer_state = _normalize(row.get("dealer_flow_state"))
    if dealer_state in {"PINNING_DOMINANT"}:
        return "PINNING_REGIME"
    if dealer_state in {"UPSIDE_HEDGING_ACCELERATION", "DOWNSIDE_HEDGING_ACCELERATION", "TWO_SIDED_INSTABILITY"}:
        return "CONVEXITY_ACTIVE"
    return "SQUEEZE_UNKNOWN"


def _event_risk_bucket(row: pd.Series) -> str:
    event_score = _safe_float(row.get("macro_event_risk_score"), None)
    if event_score is None:
        return "EVENT_RISK_UNKNOWN"
    if event_score >= 70.0:
        return "HIGH_EVENT_RISK"
    if event_score >= 45.0:
        return "ELEVATED_EVENT_RISK"
    return "LOW_EVENT_RISK"


def label_validation_regimes(frame: pd.DataFrame) -> pd.DataFrame:
    labeled = frame.copy() if frame is not None else pd.DataFrame()
    if labeled.empty:
        for column in REGIME_COLUMNS:
            labeled[column] = pd.Series(dtype="object")
        return labeled

    labeled["vol_regime_bucket"] = labeled.apply(_vol_bucket, axis=1)
    labeled["gamma_regime_bucket"] = labeled.apply(_gamma_bucket, axis=1)
    labeled["macro_regime_bucket"] = labeled.apply(_macro_bucket, axis=1)
    labeled["global_risk_bucket"] = labeled.apply(_global_risk_bucket, axis=1)
    labeled["overnight_bucket"] = labeled.apply(_overnight_bucket, axis=1)
    labeled["squeeze_risk_bucket"] = labeled.apply(_squeeze_bucket, axis=1)
    labeled["event_risk_bucket"] = labeled.apply(_event_risk_bucket, axis=1)
    return labeled

"""
Centralized configuration for the stage-1 global risk layer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlobalRiskPolicyConfig:
    caution_threshold: int = 35
    risk_off_threshold: int = 55
    extreme_threshold: int = 75
    event_risk_state_threshold: int = 60
    extreme_veto_threshold: int = 85
    overnight_gap_block_threshold: int = 68
    overnight_gap_veto_threshold: int = 82
    volatility_expansion_high_threshold: float = 65.0
    volatility_expansion_medium_threshold: float = 45.0
    global_bias_risk_full_scale: float = 0.85
    news_confidence_floor: float = 20.0
    headline_velocity_full_scale: float = 1.0
    risk_adjustment_caution: int = -2
    risk_adjustment_risk_off: int = -4
    risk_adjustment_extreme: int = -6
    size_cap_caution: float = 0.85
    size_cap_risk_off: float = 0.65
    size_cap_extreme: float = 0.35
    near_close_overnight_minutes: int = 45
    market_open_hour: int = 9
    market_open_minute: int = 15
    market_close_hour: int = 15
    market_close_minute: int = 30


GLOBAL_RISK_POLICY_CONFIG = GlobalRiskPolicyConfig()


def get_global_risk_policy_config() -> GlobalRiskPolicyConfig:
    from tuning.runtime import resolve_dataclass_config

    return resolve_dataclass_config("global_risk.core", GlobalRiskPolicyConfig())

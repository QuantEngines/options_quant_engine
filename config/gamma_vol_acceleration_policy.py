"""
Centralized configuration for the gamma-vol acceleration overlay.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GammaVolAccelerationPolicyConfig:
    low_risk_threshold: int = 25
    moderate_risk_threshold: int = 40
    high_risk_threshold: int = 60
    extreme_risk_threshold: int = 78
    directional_edge_threshold: float = 0.58
    two_sided_edge_threshold: float = 0.48
    two_sided_balance_tolerance: float = 0.12
    overnight_block_threshold: int = 7
    overnight_watch_threshold: int = 4
    score_boost_extreme: int = 4
    score_boost_high: int = 2
    score_boost_moderate: int = 1
    score_dampen_long_gamma: int = -3
    score_direction_mismatch_penalty: int = -2
    score_two_sided_bonus: int = 1


GAMMA_VOL_ACCELERATION_POLICY_CONFIG = GammaVolAccelerationPolicyConfig()


def get_gamma_vol_acceleration_policy_config() -> GammaVolAccelerationPolicyConfig:
    from tuning.runtime import resolve_dataclass_config

    return resolve_dataclass_config("gamma_vol_acceleration.core", GammaVolAccelerationPolicyConfig())

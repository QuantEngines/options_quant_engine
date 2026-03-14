"""
Centralized configuration for the expected move / option efficiency overlay.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionEfficiencyPolicyConfig:
    neutral_score: int = 50
    high_efficiency_threshold: int = 75
    good_efficiency_threshold: int = 62
    weak_efficiency_threshold: int = 40
    poor_efficiency_threshold: int = 28
    overnight_block_threshold: int = 5
    overnight_watch_threshold: int = 3
    min_effective_delta: float = 0.25
    fallback_delta: float = 0.35
    target_reachability_boost: int = 3
    target_reachability_moderate_boost: int = 1
    premium_penalty: int = -3
    strike_penalty: int = -2
    poor_efficiency_penalty: int = -4


OPTION_EFFICIENCY_POLICY_CONFIG = OptionEfficiencyPolicyConfig()


def get_option_efficiency_policy_config() -> OptionEfficiencyPolicyConfig:
    from tuning.runtime import resolve_dataclass_config

    return resolve_dataclass_config("option_efficiency.core", OptionEfficiencyPolicyConfig())

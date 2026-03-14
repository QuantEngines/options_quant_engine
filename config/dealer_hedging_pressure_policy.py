"""
Centralized configuration for the dealer hedging pressure overlay.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DealerHedgingPressurePolicyConfig:
    upside_pressure_threshold: float = 0.60
    downside_pressure_threshold: float = 0.60
    pinning_pressure_threshold: float = 0.62
    two_sided_threshold: float = 0.48
    state_balance_tolerance: float = 0.12
    moderate_pressure_threshold: int = 38
    high_pressure_threshold: int = 60
    extreme_pressure_threshold: int = 78
    overnight_block_threshold: int = 7
    overnight_watch_threshold: int = 4
    acceleration_adjustment_high: int = 2
    acceleration_adjustment_extreme: int = 3
    pinning_adjustment: int = -3
    two_sided_adjustment: int = -1


DEALER_HEDGING_PRESSURE_POLICY_CONFIG = DealerHedgingPressurePolicyConfig()


def get_dealer_hedging_pressure_policy_config() -> DealerHedgingPressurePolicyConfig:
    from tuning.runtime import resolve_dataclass_config

    return resolve_dataclass_config("dealer_pressure.core", DealerHedgingPressurePolicyConfig())

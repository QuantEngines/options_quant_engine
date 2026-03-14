"""
Typed containers for the dealer hedging pressure overlay.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DealerHedgingPressureState:
    dealer_hedging_pressure_score: int
    dealer_flow_state: str
    upside_hedging_pressure: float
    downside_hedging_pressure: float
    pinning_pressure_score: float
    overnight_hedging_risk: float
    overnight_hold_allowed: bool
    overnight_hold_reason: str
    overnight_dealer_pressure_penalty: int
    overnight_dealer_pressure_boost: int
    dealer_pressure_adjustment_score: int
    neutral_fallback: bool
    dealer_pressure_reasons: list[str] = field(default_factory=list)
    dealer_pressure_features: dict[str, Any] = field(default_factory=dict)
    dealer_pressure_diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

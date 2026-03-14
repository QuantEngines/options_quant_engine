"""
Typed containers for the stage-1 global risk layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class HoldingContext:
    holding_profile: str = "AUTO"
    overnight_relevant: bool = False
    market_session: str = "UNKNOWN"
    minutes_to_close: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GlobalRiskState:
    global_risk_state: str
    global_risk_score: int
    overnight_gap_risk_score: int
    volatility_expansion_risk_score: int
    overnight_hold_allowed: bool
    overnight_hold_reason: str
    overnight_risk_penalty: int
    global_risk_adjustment_score: int
    global_risk_veto: bool
    global_risk_position_size_multiplier: float
    neutral_fallback: bool
    holding_context: dict[str, Any] = field(default_factory=dict)
    global_risk_reasons: list[str] = field(default_factory=list)
    global_risk_features: dict[str, Any] = field(default_factory=dict)
    global_risk_diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

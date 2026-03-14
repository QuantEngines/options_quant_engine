"""
Typed containers for the gamma-vol acceleration overlay.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class GammaVolAccelerationState:
    gamma_vol_acceleration_score: int
    squeeze_risk_state: str
    directional_convexity_state: str
    upside_squeeze_risk: float
    downside_airpocket_risk: float
    overnight_convexity_risk: float
    overnight_hold_allowed: bool
    overnight_hold_reason: str
    overnight_convexity_penalty: int
    overnight_convexity_boost: int
    gamma_vol_adjustment_score: int
    neutral_fallback: bool
    gamma_vol_reasons: list[str] = field(default_factory=list)
    gamma_vol_features: dict[str, Any] = field(default_factory=dict)
    gamma_vol_diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

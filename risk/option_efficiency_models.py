"""
Typed containers for the expected move / option efficiency overlay.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class OptionEfficiencyState:
    expected_move_points: float | None
    expected_move_pct: float | None
    expected_move_quality: str
    target_distance_points: float | None
    target_distance_pct: float | None
    expected_move_coverage_ratio: float | None
    target_reachability_score: int
    premium_efficiency_score: int
    strike_efficiency_score: int
    option_efficiency_score: int
    option_efficiency_adjustment_score: int
    overnight_hold_allowed: bool
    overnight_hold_reason: str
    overnight_option_efficiency_penalty: int
    strike_moneyness_bucket: str
    strike_distance_from_spot: float | None
    payoff_efficiency_hint: str
    neutral_fallback: bool
    option_efficiency_reasons: list[str] = field(default_factory=list)
    option_efficiency_features: dict[str, Any] = field(default_factory=dict)
    option_efficiency_diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

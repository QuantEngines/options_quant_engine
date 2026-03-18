"""
MovePredictor Protocol and PredictionResult dataclass.

Every predictor must implement the MovePredictor Protocol so the engine can
call it uniformly regardless of the underlying method.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class PredictionResult:
    """Standardised output from any predictor."""

    rule_move_probability: float | None = None
    ml_move_probability: float | None = None
    hybrid_move_probability: float | None = None
    model_features: np.ndarray | None = None
    components: dict[str, Any] = field(default_factory=dict)
    predictor_name: str = "unknown"


@runtime_checkable
class MovePredictor(Protocol):
    """
    Protocol that all predictors must satisfy.

    Implementors must provide:
      - name : str property identifying the predictor
      - predict(market_ctx) -> PredictionResult
    """

    @property
    def name(self) -> str: ...

    def predict(self, market_ctx: dict[str, Any]) -> PredictionResult:
        """
        Compute move-probability estimates from a market context dict.

        Parameters
        ----------
        market_ctx : dict
            Keys expected (all optional — implementors degrade gracefully):
              df, spot, symbol, market_state, day_high, day_low, day_open,
              prev_close, lookback_avg_range_pct, global_context

        Returns
        -------
        PredictionResult with at least hybrid_move_probability populated.
        """
        ...

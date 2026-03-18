"""
DefaultBlendedPredictor — wraps the existing production pipeline.

This is a thin adapter around the current rule + ML + logistic-recalibration
blend.  All existing logic is delegated to probability.py helpers so there
is zero behavioural change when running in ``blended`` mode.
"""
from __future__ import annotations

from typing import Any

from engine.predictors.protocol import MovePredictor, PredictionResult


class DefaultBlendedPredictor:
    """Current production predictor: weighted blend of rule + ML legs."""

    @property
    def name(self) -> str:
        return "blended"

    def predict(self, market_ctx: dict[str, Any]) -> PredictionResult:
        # Late import to avoid circular dependency at module-load time.
        from engine.trading_support.probability import (
            _compute_probability_state_impl,
        )

        raw = _compute_probability_state_impl(**market_ctx)
        return PredictionResult(
            rule_move_probability=raw.get("rule_move_probability"),
            ml_move_probability=raw.get("ml_move_probability"),
            hybrid_move_probability=raw.get("hybrid_move_probability"),
            model_features=raw.get("model_features"),
            components=raw.get("components", {}),
            predictor_name=self.name,
        )


class PureRulePredictor:
    """Rule-based leg only — ML leg is suppressed."""

    @property
    def name(self) -> str:
        return "pure_rule"

    def predict(self, market_ctx: dict[str, Any]) -> PredictionResult:
        from engine.trading_support.probability import (
            _compute_probability_state_impl,
        )

        raw = _compute_probability_state_impl(**market_ctx, _force_rule_only=True)
        return PredictionResult(
            rule_move_probability=raw.get("rule_move_probability"),
            ml_move_probability=None,
            hybrid_move_probability=raw.get("rule_move_probability"),
            model_features=raw.get("model_features"),
            components=raw.get("components", {}),
            predictor_name=self.name,
        )


class PureMLPredictor:
    """ML leg only — rule leg is suppressed.  Blend weight = 100% ML."""

    @property
    def name(self) -> str:
        return "pure_ml"

    def predict(self, market_ctx: dict[str, Any]) -> PredictionResult:
        from engine.trading_support.probability import (
            _compute_probability_state_impl,
        )

        raw = _compute_probability_state_impl(**market_ctx, _force_ml_only=True)
        ml_prob = raw.get("ml_move_probability")
        return PredictionResult(
            rule_move_probability=None,
            ml_move_probability=ml_prob,
            hybrid_move_probability=ml_prob if ml_prob is not None else raw.get("rule_move_probability"),
            model_features=raw.get("model_features"),
            components=raw.get("components", {}),
            predictor_name=self.name,
        )

"""
Pluggable predictor architecture for the options quant engine.

This package provides a Protocol-based abstraction that allows the engine
to swap between different prediction methods via configuration, with no
code changes required.

Available predictors:
  - blended (default)           : Production blend (rule + ML leg + calibration)
  - pure_ml                     : ML-only probability, rule leg disabled
  - pure_rule                   : Rule-only probability, ML leg disabled
  - research_dual_model         : Research dual-model (rank + confidence overlay)
  - research_decision_policy    : Dual-model + decision-policy gate
  - ev_sizing                   : Dual-model + expected-value sizing overlay
  - research_rank_gate          : Dual-model + rank threshold block
  - research_uncertainty_adjusted : Dual-model + uncertainty discount

Usage:
    from engine.predictors import get_predictor
    predictor = get_predictor()            # reads PREDICTION_METHOD from settings
    result = predictor.predict(market_ctx) # returns PredictionResult
"""
from engine.predictors.protocol import MovePredictor, PredictionResult
from engine.predictors.factory import get_predictor, reset_predictor, prediction_method_override

__all__ = [
    "MovePredictor",
    "PredictionResult",
    "get_predictor",
    "reset_predictor",
    "prediction_method_override",
]

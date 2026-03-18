"""
Pluggable predictor architecture for the options quant engine.

This package provides a Protocol-based abstraction that allows the engine
to swap between different prediction methods via configuration, with no
code changes required.

Available predictors:
  - blended (default)       : Current production pipeline (rule + ML blend)
  - pure_ml                 : ML-only probability, rule leg disabled
  - pure_rule               : Rule-only probability, ML leg disabled
  - research_dual_model     : Research dual-model (GBT ranking + LogReg calibration)

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

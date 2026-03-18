"""
ML Research Models — Dual-model inference layer for research evaluation.

This package provides a RESEARCH-ONLY ML inference layer that runs two
complementary models in shadow mode alongside the production signal engine:

  1. GBT_shallow_v1  → ml_rank_score   (ranking model, higher AUC / quintile spread)
  2. LogReg_ElasticNet_v1 → ml_confidence_score (calibration model, well-calibrated probabilities)

CRITICAL: These models do NOT influence production trading decisions.
All outputs are strictly for research logging, evaluation, and reporting.
"""

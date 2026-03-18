"""
ML Research Configuration
==========================
Centralized configuration for the dual-model ML research layer.

Toggle ML research ON/OFF without touching any other code.
All model paths, bucket definitions, and sizing parameters live here.
"""
from __future__ import annotations

import os
from pathlib import Path

from config.settings import BASE_DIR


# ── Master toggle ────────────────────────────────────────────────────
# Set OQE_ML_RESEARCH_ENABLED=1 in .env or environment to activate.
# When disabled, all ML research functions return None gracefully.
ML_RESEARCH_ENABLED: bool = os.getenv("OQE_ML_RESEARCH_ENABLED", "1").strip() == "1"

# ── Model registry paths ────────────────────────────────────────────
_REGISTRY_DIR = Path(BASE_DIR) / "models_store" / "registry"

GBT_MODEL_NAME = "GBT_shallow_v1"
LOGREG_MODEL_NAME = "LogReg_ElasticNet_v1"

GBT_MODEL_PATH = _REGISTRY_DIR / GBT_MODEL_NAME / "model.joblib"
GBT_META_PATH = _REGISTRY_DIR / GBT_MODEL_NAME / "meta.json"

LOGREG_MODEL_PATH = _REGISTRY_DIR / LOGREG_MODEL_NAME / "model.joblib"
LOGREG_META_PATH = _REGISTRY_DIR / LOGREG_MODEL_NAME / "meta.json"

# ── Quintile bucket definitions ─────────────────────────────────────
# Used for ml_rank_bucket and ml_confidence_bucket (quintile boundaries).
RANK_QUINTILE_THRESHOLDS = [0.20, 0.40, 0.60, 0.80]
CONFIDENCE_QUINTILE_THRESHOLDS = [0.20, 0.40, 0.60, 0.80]

RANK_BUCKET_LABELS = ["Q1_lowest", "Q2_low", "Q3_mid", "Q4_high", "Q5_highest"]
CONFIDENCE_BUCKET_LABELS = ["Q1_lowest", "Q2_low", "Q3_mid", "Q4_high", "Q5_highest"]

# ── Position sizing simulation buckets ──────────────────────────────
# Maps ml_confidence_score ranges to hypothetical size multipliers.
# This is for simulation ONLY — never used in live trading.
SIZING_BUCKETS = [
    (0.00, 0.55, 0.50),   # low confidence → half size
    (0.55, 0.65, 0.75),   # moderate → three-quarter size
    (0.65, 0.75, 1.00),   # good → full size
    (0.75, 1.01, 1.25),   # high confidence → 1.25x size
]

# ── Filter simulation thresholds ────────────────────────────────────
FILTER_PERCENTILES = [20, 30]   # bottom N% of ml_rank_score to simulate removing

# ── Output paths ────────────────────────────────────────────────────
ML_EVALUATION_DIR = Path(BASE_DIR) / "research" / "ml_evaluation"
ML_EXTENDED_DATASET_PATH = ML_EVALUATION_DIR / "ml_extended_signals.csv"

# ── Dataset extension columns ───────────────────────────────────────
ML_DATASET_COLUMNS = [
    "ml_rank_score",
    "ml_confidence_score",
    "ml_rank_bucket",
    "ml_confidence_bucket",
    "ml_agreement_with_engine",
]

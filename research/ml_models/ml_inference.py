"""
Unified ML Inference Pipeline
===============================
Combines GBT (ranking) and LogReg (calibration) model outputs into a
single research inference result for each signal.

For every signal:
  1. Extract 33-feature vector via expanded_feature_builder
  2. Run GBT → ml_rank_score
  3. Run LogReg → ml_confidence_score
  4. Compute ml_agreement_with_engine
  5. Assign quintile buckets

CRITICAL: This module is STRICTLY OBSERVATIONAL.
It does NOT modify, trigger, or block any production trading decisions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

from models.expanded_feature_builder import extract_features, N_FEATURES
from research.ml_models.ml_config import (
    ML_RESEARCH_ENABLED,
    RANK_QUINTILE_THRESHOLDS,
    CONFIDENCE_QUINTILE_THRESHOLDS,
    RANK_BUCKET_LABELS,
    CONFIDENCE_BUCKET_LABELS,
    SIZING_BUCKETS,
)
from research.ml_models.gbt_model import (
    predict_rank_score,
    predict_rank_scores_batch,
)
from research.ml_models.logreg_model import (
    predict_confidence_score,
    predict_confidence_scores_batch,
)

logger = logging.getLogger(__name__)


@dataclass
class MLInferenceResult:
    """Container for dual-model inference output on a single signal."""
    ml_rank_score: Optional[float] = None
    ml_confidence_score: Optional[float] = None
    ml_rank_bucket: Optional[str] = None
    ml_confidence_bucket: Optional[str] = None
    ml_agreement_with_engine: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _assign_quintile_bucket(
    score: Optional[float],
    thresholds: list[float],
    labels: list[str],
) -> Optional[str]:
    """Assign a score to a quintile bucket based on thresholds."""
    if score is None:
        return None
    for i, threshold in enumerate(thresholds):
        if score < threshold:
            return labels[i]
    return labels[-1]


def _compute_agreement(
    ml_rank_score: Optional[float],
    ml_confidence_score: Optional[float],
    trade_status: Optional[str],
    direction: Optional[str],
) -> str:
    """
    Determine whether the ML models agree with the engine's trade decision.

    Returns:
      - "YES" if ML scores suggest tradeable AND engine issued a TRADE
      - "NO" if ML and engine disagree on tradeability
      - "NO_ENGINE_SIGNAL" if the engine did not issue a TRADE/WATCHLIST
    """
    engine_active = str(trade_status or "").upper().strip() in {"TRADE", "WATCHLIST"}
    has_direction = str(direction or "").upper().strip() in {"CALL", "PUT"}

    if not engine_active or not has_direction:
        return "NO_ENGINE_SIGNAL"

    if ml_rank_score is None or ml_confidence_score is None:
        return "NO_ENGINE_SIGNAL"

    # ML considers signal tradeable if both scores are above median (0.5)
    ml_favorable = ml_rank_score >= 0.5 and ml_confidence_score >= 0.5
    return "YES" if ml_favorable else "NO"


def infer_single(row: dict) -> MLInferenceResult:
    """
    Run dual-model inference on a single signal evaluation row.

    Parameters
    ----------
    row : dict
        A signal evaluation row (from dataset or engine payload).

    Returns
    -------
    MLInferenceResult with all ML research fields populated.
    Returns empty result (all None) if ML research is disabled or models fail.
    """
    if not ML_RESEARCH_ENABLED:
        return MLInferenceResult()

    try:
        features = extract_features(row)
    except Exception:
        logger.debug("Feature extraction failed for signal", exc_info=True)
        return MLInferenceResult()

    rank_score = predict_rank_score(features)
    confidence_score = predict_confidence_score(features)

    rank_bucket = _assign_quintile_bucket(
        rank_score, RANK_QUINTILE_THRESHOLDS, RANK_BUCKET_LABELS,
    )
    confidence_bucket = _assign_quintile_bucket(
        confidence_score, CONFIDENCE_QUINTILE_THRESHOLDS, CONFIDENCE_BUCKET_LABELS,
    )

    agreement = _compute_agreement(
        rank_score,
        confidence_score,
        row.get("trade_status"),
        row.get("direction"),
    )

    return MLInferenceResult(
        ml_rank_score=rank_score,
        ml_confidence_score=confidence_score,
        ml_rank_bucket=rank_bucket,
        ml_confidence_bucket=confidence_bucket,
        ml_agreement_with_engine=agreement,
    )


def infer_batch(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run dual-model inference on a DataFrame of signal evaluation rows.

    Returns a new DataFrame with the 5 ML columns appended.
    Original columns are preserved — no mutations to the input DataFrame.
    """
    if not ML_RESEARCH_ENABLED or df.empty:
        for col in ["ml_rank_score", "ml_confidence_score",
                     "ml_rank_bucket", "ml_confidence_bucket",
                     "ml_agreement_with_engine"]:
            df[col] = None
        return df

    # Extract feature matrix for all rows
    feature_matrix = np.zeros((len(df), N_FEATURES), dtype=np.float64)
    valid_mask = np.ones(len(df), dtype=bool)

    for i, (_, row) in enumerate(df.iterrows()):
        try:
            feature_matrix[i] = extract_features(row.to_dict())
        except Exception:
            valid_mask[i] = False

    # Batch inference
    rank_scores = np.full(len(df), np.nan)
    confidence_scores = np.full(len(df), np.nan)

    if valid_mask.any():
        valid_features = feature_matrix[valid_mask]

        gbt_results = predict_rank_scores_batch(valid_features)
        if gbt_results is not None:
            rank_scores[valid_mask] = gbt_results

        logreg_results = predict_confidence_scores_batch(valid_features)
        if logreg_results is not None:
            confidence_scores[valid_mask] = logreg_results

    # Build output DataFrame (copy to avoid mutating input)
    result = df.copy()
    result["ml_rank_score"] = rank_scores
    result["ml_confidence_score"] = confidence_scores

    # Assign quintile buckets
    result["ml_rank_bucket"] = [
        _assign_quintile_bucket(s if not np.isnan(s) else None,
                                RANK_QUINTILE_THRESHOLDS, RANK_BUCKET_LABELS)
        for s in rank_scores
    ]
    result["ml_confidence_bucket"] = [
        _assign_quintile_bucket(s if not np.isnan(s) else None,
                                CONFIDENCE_QUINTILE_THRESHOLDS, CONFIDENCE_BUCKET_LABELS)
        for s in confidence_scores
    ]

    # Compute agreement
    result["ml_agreement_with_engine"] = [
        _compute_agreement(
            r if not np.isnan(r) else None,
            c if not np.isnan(c) else None,
            row.get("trade_status"),
            row.get("direction"),
        )
        for (_, row), r, c in zip(df.iterrows(), rank_scores, confidence_scores)
    ]

    return result


def compute_size_multiplier(ml_confidence_score: Optional[float]) -> float:
    """
    Compute hypothetical position size multiplier from ml_confidence_score.

    This is for SIMULATION purposes only — never used in live sizing.
    """
    if ml_confidence_score is None:
        return 1.0
    for low, high, multiplier in SIZING_BUCKETS:
        if low <= ml_confidence_score < high:
            return multiplier
    return 1.0

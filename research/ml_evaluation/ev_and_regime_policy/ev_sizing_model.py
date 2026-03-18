"""
EV-Based Sizing Model
======================
Estimates per-signal Expected Value (EV) using conditional return tables
and maps EV into research-only size multipliers.

Formula
-------
    EV = p_win × E[gain | win] − (1 − p_win) × |E[loss | loss]|

Where:
  *  p_win comes from the calibrated logistic model (ml_confidence_score)
  *  E[gain | win] and E[loss | loss] come from the conditional return table,
     bucketed by (rank_bucket, confidence_bucket, regime).

EV normalization uses the global interquartile range to produce an
ev_normalized score in [0, 1], capped at reasonable bounds.

Author: Pramit Dutta
Organization: Quant Engines

RESEARCH ONLY — never imported by production engine paths.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from research.ml_evaluation.ev_and_regime_policy.conditional_return_tables import (
    BucketStats,
    ConditionalReturnTable,
    build_conditional_return_table,
    lookup,
)

logger = logging.getLogger(__name__)

# ── EV sizing configuration ─────────────────────────────────────────

DEFAULT_EV_SIZING_MAP: list[tuple[float, float, float]] = [
    # (ev_norm_lower, ev_norm_upper, size_multiplier)
    (-999.0,   0.00,  0.00),     # negative EV → no position
    (  0.00,   0.15,  0.25),     # marginal EV → quarter size
    (  0.15,   0.35,  0.50),     # low EV
    (  0.35,   0.55,  1.00),     # medium EV  → full
    (  0.55,   0.75,  1.50),     # high EV    → oversize
    (  0.75, 999.00,  2.00),     # very high EV → cap at 2×
]

EV_BUCKET_LABELS: list[tuple[float, float, str]] = [
    (-999.0,   0.00,  "negative"),
    (  0.00,   0.15,  "marginal"),
    (  0.15,   0.35,  "low"),
    (  0.35,   0.55,  "medium"),
    (  0.55,   0.75,  "high"),
    (  0.75, 999.00,  "very_high"),
]

# Minimum sample count before EV reliability is full.
EV_RELIABILITY_HIGH_THRESHOLD: int = 30
EV_RELIABILITY_MED_THRESHOLD: int = 10


# ── Data structures ──────────────────────────────────────────────────

@dataclass(frozen=True)
class EVResult:
    """Per-signal EV computation output."""
    ev_raw: float
    ev_normalized: float
    ev_bucket: str
    ev_size_multiplier: float
    sample_support: int
    ev_reliability_score: float
    p_win: float
    expected_gain: float
    expected_loss: float
    backed_off: bool


# ── Core EV computation ─────────────────────────────────────────────

def compute_ev(
    p_win: float,
    cell: BucketStats,
) -> tuple[float, float, float]:
    """
    Compute raw EV using the conditional return table cell.

    Returns (ev_raw, expected_gain, expected_loss).
    """
    expected_gain = cell.avg_positive_return_bps
    expected_loss = abs(cell.avg_negative_return_bps)   # make positive for the formula

    ev = p_win * expected_gain - (1.0 - p_win) * expected_loss
    return ev, expected_gain, expected_loss


def compute_ev_reliability(cell: BucketStats) -> float:
    """
    Score in [0.0, 1.0] reflecting how trustworthy the EV estimate is.

    Based on sample support and smoothing status.
    """
    n = cell.n
    if n >= EV_RELIABILITY_HIGH_THRESHOLD:
        base = 1.0
    elif n >= EV_RELIABILITY_MED_THRESHOLD:
        base = 0.5 + 0.5 * (n - EV_RELIABILITY_MED_THRESHOLD) / max(EV_RELIABILITY_HIGH_THRESHOLD - EV_RELIABILITY_MED_THRESHOLD, 1)
    elif n >= 3:
        base = 0.25
    else:
        base = 0.10

    # Penalize backed-off cells
    if cell.backed_off:
        base *= 0.6

    return round(min(base, 1.0), 4)


def classify_ev_bucket(ev_norm: float) -> str:
    """Map a normalized EV to a human-readable bucket label."""
    for lo, hi, label in EV_BUCKET_LABELS:
        if lo <= ev_norm < hi:
            return label
    return "unknown"


def ev_to_size_multiplier(
    ev_norm: float,
    sizing_map: list[tuple[float, float, float]] | None = None,
) -> float:
    """Map normalized EV → size multiplier using the configured tiers."""
    tiers = sizing_map or DEFAULT_EV_SIZING_MAP
    for lo, hi, mult in tiers:
        if lo <= ev_norm < hi:
            return mult
    return 1.0


# ── Normalization ────────────────────────────────────────────────────

def build_ev_normalizer(
    ev_values: np.ndarray,
) -> tuple[float, float]:
    """
    Compute percentile-based normalization bounds from a distribution
    of raw EV values.

    Returns (ev_low, ev_high) such that:
      norm = (ev_raw - ev_low) / (ev_high - ev_low)  clipped to [0, 1]
    """
    finite = ev_values[np.isfinite(ev_values)]
    if len(finite) < 5:
        return 0.0, 1.0
    ev_low = float(np.percentile(finite, 10))
    ev_high = float(np.percentile(finite, 90))
    if ev_high - ev_low < 1e-6:
        ev_high = ev_low + 1.0
    return ev_low, ev_high


def normalize_ev(ev_raw: float, ev_low: float, ev_high: float) -> float:
    """Normalize raw EV to [0, 1] using percentile-based bounds."""
    span = ev_high - ev_low
    if span < 1e-9:
        return 0.5
    return float(np.clip((ev_raw - ev_low) / span, 0.0, 1.0))


# ── Batch scoring ────────────────────────────────────────────────────

def score_signals(
    df: pd.DataFrame,
    table: ConditionalReturnTable,
    *,
    confidence_col: str = "ml_confidence_score",
    rank_bucket_col: str = "ml_rank_bucket",
    confidence_bucket_col: str = "ml_confidence_bucket",
    regime_col: str = "gamma_regime",
    sizing_map: list[tuple[float, float, float]] | None = None,
) -> pd.DataFrame:
    """
    Score every signal in *df* with EV metrics and return a copy with
    new columns appended.

    New columns added:
      ev_raw, ev_normalized, ev_bucket, ev_size_multiplier,
      ev_reliability_score, sample_support_for_ev, ev_p_win,
      ev_expected_gain, ev_expected_loss
    """
    df = df.copy()

    # First pass: compute raw EV for every row
    ev_raws: list[float] = []
    gains: list[float] = []
    losses: list[float] = []
    supports: list[int] = []
    reliabilities: list[float] = []
    p_wins: list[float] = []
    backed: list[bool] = []

    for _, row in df.iterrows():
        rank_b = str(row.get(rank_bucket_col, "Q3_mid"))
        conf_b = str(row.get(confidence_bucket_col, "Q3_mid"))
        regime = str(row.get(regime_col, "UNKNOWN"))
        p_w = float(row.get(confidence_col, 0.5))
        if np.isnan(p_w):
            p_w = 0.5

        cell = lookup(table, rank_b, conf_b, regime)
        ev, eg, el = compute_ev(p_w, cell)

        ev_raws.append(ev)
        gains.append(eg)
        losses.append(el)
        supports.append(cell.n)
        reliabilities.append(compute_ev_reliability(cell))
        p_wins.append(p_w)
        backed.append(cell.backed_off)

    # Build normalizer from the raw EV distribution
    ev_arr = np.array(ev_raws)
    ev_low, ev_high = build_ev_normalizer(ev_arr)

    # Second pass: normalize and classify
    ev_norms = [normalize_ev(e, ev_low, ev_high) for e in ev_raws]
    ev_bkts = [classify_ev_bucket(n) for n in ev_norms]
    ev_sizes = [ev_to_size_multiplier(n, sizing_map) for n in ev_norms]

    df["ev_raw"] = ev_raws
    df["ev_normalized"] = [round(n, 4) for n in ev_norms]
    df["ev_bucket"] = ev_bkts
    df["ev_size_multiplier"] = ev_sizes
    df["ev_reliability_score"] = reliabilities
    df["sample_support_for_ev"] = supports
    df["ev_p_win"] = p_wins
    df["ev_expected_gain"] = [round(g, 2) for g in gains]
    df["ev_expected_loss"] = [round(l, 2) for l in losses]

    logger.info(
        "EV scoring complete: %d signals, ev_raw mean=%.2f, ev_norm mean=%.3f",
        len(df), float(ev_arr.mean()), float(np.mean(ev_norms)),
    )

    return df


# ── Confidence-only sizing (for comparison baseline) ─────────────────

DEFAULT_CONFIDENCE_SIZING_MAP: list[tuple[float, float, float]] = [
    (0.00, 0.40, 0.25),
    (0.40, 0.55, 0.50),
    (0.55, 0.65, 0.75),
    (0.65, 0.75, 1.00),
    (0.75, 1.01, 1.25),
]


def assign_confidence_size(conf: float | None) -> float:
    """Map confidence to a size multiplier (existing methodology baseline)."""
    if conf is None or (isinstance(conf, float) and np.isnan(conf)):
        return 1.0
    for lo, hi, mult in DEFAULT_CONFIDENCE_SIZING_MAP:
        if lo <= conf < hi:
            return mult
    return 1.0

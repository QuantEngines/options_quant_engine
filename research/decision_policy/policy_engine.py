"""
Decision Policy Engine
=======================
Applies all registered policies to the backtest signal dataset and
produces an annotated DataFrame with per-signal decisions, reasons,
and hypothetical size multipliers.

Entry points
------------
``apply_policies(df)``
    Takes an ML-extended dataset (must contain ``ml_rank_score``,
    ``ml_confidence_score``, and ``hybrid_move_probability``).
    Returns the same DataFrame with new columns per policy:
      • ``{policy_name}_decision``   — ALLOW / BLOCK / DOWNGRADE
      • ``{policy_name}_reason``     — human-readable explanation
      • ``{policy_name}_size_mult``  — hypothetical size multiplier

``apply_single_policy(row, policy_fn)``
    Evaluate a single signal row through one policy.

Author: Pramit Dutta
Organization: Quant Engines

RESEARCH ONLY — never imported by production engine paths.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from research.decision_policy.policy_config import (
    DECISION_POLICY_ENABLED,
    RANK_FILTER_PERCENTILES,
)
from research.decision_policy.policy_definitions import (
    PolicyDecision,
    PolicyFn,
    get_all_policies,
    make_rank_filter_policy,
)

logger = logging.getLogger(__name__)


def apply_policies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply every registered policy to *df* and return an annotated copy.

    For each policy ``p``, three columns are added:
      - ``p_decision``  (str)   — ALLOW / BLOCK / DOWNGRADE
      - ``p_reason``    (str)   — human-readable explanation
      - ``p_size_mult`` (float) — hypothetical sizing multiplier

    The incoming DataFrame must already contain ML columns
    (``ml_rank_score``, ``ml_confidence_score``) and engine columns
    (``hybrid_move_probability``).
    """
    if not DECISION_POLICY_ENABLED:
        logger.warning("Decision policy layer disabled — returning input unchanged")
        return df

    df = df.copy()

    # Build rank-filter thresholds from dataset percentiles.
    rank_thresholds = _compute_rank_thresholds(df)

    # Assemble all policies.
    policies = get_all_policies(rank_thresholds=rank_thresholds)

    logger.info("Applying %d decision policies to %d signals …", len(policies), len(df))

    for policy_name, policy_fn in policies.items():
        decisions: list[str] = []
        reasons: list[str] = []
        mults: list[float] = []

        for _, row in df.iterrows():
            dec = _safe_apply(policy_fn, row.to_dict(), policy_name)
            decisions.append(dec.decision)
            reasons.append(dec.reason)
            mults.append(dec.size_multiplier)

        col_prefix = policy_name
        df[f"{col_prefix}_decision"] = decisions
        df[f"{col_prefix}_reason"] = reasons
        df[f"{col_prefix}_size_mult"] = mults

    logger.info("Policy annotations complete — %d new columns added", len(policies) * 3)
    return df


def apply_single_policy(
    row: dict[str, Any],
    policy_fn: PolicyFn,
) -> PolicyDecision:
    """Evaluate a single signal through one policy (convenience wrapper)."""
    return policy_fn(row)


# ── Internals ────────────────────────────────────────────────────────

def _compute_rank_thresholds(df: pd.DataFrame) -> dict[str, float]:
    """Derive rank-filter thresholds from the dataset percentiles."""
    thresholds: dict[str, float] = {}
    rank_scores = df["ml_rank_score"].dropna()
    if rank_scores.empty:
        return thresholds
    for pct in RANK_FILTER_PERCENTILES:
        val = float(np.percentile(rank_scores, pct))
        thresholds[f"bottom_{pct}pct"] = val
    return thresholds


def _safe_apply(
    policy_fn: PolicyFn,
    row: dict[str, Any],
    policy_name: str,
) -> PolicyDecision:
    """Call *policy_fn* and return a safe default on unexpected failure."""
    try:
        return policy_fn(row)
    except Exception:
        logger.debug("Policy %s raised on row — defaulting to ALLOW", policy_name, exc_info=True)
        return PolicyDecision(
            decision="ALLOW",
            policy_name=policy_name,
            reason="Policy evaluation error — default ALLOW",
        )

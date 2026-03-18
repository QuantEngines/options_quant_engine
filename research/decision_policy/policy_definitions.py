"""
Decision Policy Definitions
=============================
Four pluggable policies that evaluate a signal row and return a decision
dataclass with ALLOW / BLOCK / DOWNGRADE status and a human-readable reason.

Policies
--------
1. **Agreement Only** — blocks signals where ML and engine disagree.
2. **Rank Filter**    — blocks the bottom N % by GBT rank score (two variants: 20 %, 30 %).
3. **Dual Threshold** — requires *both* a minimum rank AND confidence score.
4. **Sizing Simulation** — always ALLOWs but assigns a confidence-tier size
   multiplier for hypothetical P&L simulation.

Each policy is a callable that accepts a single-row dict (or pd.Series) and
returns a ``PolicyDecision``.

Author: Pramit Dutta
Organization: Quant Engines

RESEARCH ONLY — never imported by production engine paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from research.decision_policy.policy_config import (
    AGREEMENT_ENGINE_MIN_PROB,
    AGREEMENT_ML_MIN_CONFIDENCE,
    DECISION_ALLOW,
    DECISION_BLOCK,
    DECISION_DOWNGRADE,
    DUAL_DOWNGRADE_ENABLED,
    DUAL_MIN_CONFIDENCE,
    DUAL_MIN_RANK_SCORE,
    POLICY_AGREEMENT_ONLY,
    POLICY_DUAL_THRESHOLD,
    POLICY_RANK_FILTER,
    POLICY_SIZING_SIMULATION,
    SIZING_TIERS,
)


# ── Data structures ─────────────────────────────────────────────────

@dataclass(frozen=True)
class PolicyDecision:
    """Immutable decision output from any policy."""
    decision: str           # ALLOW | BLOCK | DOWNGRADE
    policy_name: str        # identifier of the policy that produced this
    reason: str             # human-readable explanation
    size_multiplier: float = 1.0  # hypothetical position-size scalar


# Type alias for a policy callable.
PolicyFn = Callable[[dict[str, Any]], PolicyDecision]


# ── Helper to safely read numeric values ────────────────────────────

def _num(row: dict[str, Any], key: str, default: float | None = None) -> float | None:
    """Return *key* from *row* as float, or *default* if missing / NaN."""
    val = row.get(key)
    if val is None:
        return default
    try:
        f = float(val)
        return default if (np.isnan(f) or np.isinf(f)) else f
    except (TypeError, ValueError):
        return default


# ═════════════════════════════════════════════════════════════════════
# 1. Agreement-Only Policy
# ═════════════════════════════════════════════════════════════════════

def agreement_only_policy(row: dict[str, Any]) -> PolicyDecision:
    """
    ALLOW only when both the engine *and* the ML model signal confidence
    above their respective minimum thresholds.

    Logic
    -----
    - engine hybrid_move_probability ≥ AGREEMENT_ENGINE_MIN_PROB  AND
      ml_confidence_score ≥ AGREEMENT_ML_MIN_CONFIDENCE            → ALLOW
    - One of the two below threshold                               → DOWNGRADE
    - Both below or missing                                        → BLOCK
    """
    engine_prob = _num(row, "hybrid_move_probability")
    ml_conf = _num(row, "ml_confidence_score")

    engine_ok = engine_prob is not None and engine_prob >= AGREEMENT_ENGINE_MIN_PROB
    ml_ok = ml_conf is not None and ml_conf >= AGREEMENT_ML_MIN_CONFIDENCE

    if engine_ok and ml_ok:
        return PolicyDecision(
            decision=DECISION_ALLOW,
            policy_name=POLICY_AGREEMENT_ONLY,
            reason=f"Engine ({engine_prob:.2f}) and ML ({ml_conf:.2f}) both above thresholds",
        )

    if engine_ok or ml_ok:
        weak = "engine" if not engine_ok else "ML"
        return PolicyDecision(
            decision=DECISION_DOWNGRADE,
            policy_name=POLICY_AGREEMENT_ONLY,
            reason=f"Partial agreement — {weak} below threshold "
                   f"(engine={engine_prob}, ml={ml_conf})",
            size_multiplier=0.5,
        )

    return PolicyDecision(
        decision=DECISION_BLOCK,
        policy_name=POLICY_AGREEMENT_ONLY,
        reason=f"No agreement — engine={engine_prob}, ml={ml_conf}",
    )


# ═════════════════════════════════════════════════════════════════════
# 2. Rank-Filter Policy  (parameterised by a rank-score threshold)
# ═════════════════════════════════════════════════════════════════════

def make_rank_filter_policy(rank_threshold: float, label_suffix: str = "") -> PolicyFn:
    """
    Factory that returns a rank-filter policy for a given *rank_threshold*.

    Signals with ``ml_rank_score < rank_threshold`` are BLOCKed.
    """
    policy_label = f"{POLICY_RANK_FILTER}_{label_suffix}" if label_suffix else POLICY_RANK_FILTER

    def _policy(row: dict[str, Any]) -> PolicyDecision:
        rank = _num(row, "ml_rank_score")
        if rank is None:
            return PolicyDecision(
                decision=DECISION_BLOCK,
                policy_name=policy_label,
                reason="ml_rank_score unavailable",
            )

        if rank >= rank_threshold:
            return PolicyDecision(
                decision=DECISION_ALLOW,
                policy_name=policy_label,
                reason=f"Rank {rank:.4f} ≥ threshold {rank_threshold:.4f}",
            )
        return PolicyDecision(
            decision=DECISION_BLOCK,
            policy_name=policy_label,
            reason=f"Rank {rank:.4f} < threshold {rank_threshold:.4f}",
        )

    return _policy


# ═════════════════════════════════════════════════════════════════════
# 3. Dual-Threshold Policy
# ═════════════════════════════════════════════════════════════════════

def dual_threshold_policy(row: dict[str, Any]) -> PolicyDecision:
    """
    Require both a minimum rank score AND a minimum confidence score.

    - Both pass   → ALLOW
    - One fails   → DOWNGRADE (if enabled) with reduced multiplier
    - Both fail   → BLOCK
    """
    rank = _num(row, "ml_rank_score")
    conf = _num(row, "ml_confidence_score")

    rank_ok = rank is not None and rank >= DUAL_MIN_RANK_SCORE
    conf_ok = conf is not None and conf >= DUAL_MIN_CONFIDENCE

    if rank_ok and conf_ok:
        return PolicyDecision(
            decision=DECISION_ALLOW,
            policy_name=POLICY_DUAL_THRESHOLD,
            reason=f"Both pass — rank={rank:.4f}≥{DUAL_MIN_RANK_SCORE}, "
                   f"conf={conf:.4f}≥{DUAL_MIN_CONFIDENCE}",
        )

    if (rank_ok or conf_ok) and DUAL_DOWNGRADE_ENABLED:
        weak = "rank" if not rank_ok else "confidence"
        return PolicyDecision(
            decision=DECISION_DOWNGRADE,
            policy_name=POLICY_DUAL_THRESHOLD,
            reason=f"Partial — {weak} below minimum (rank={rank}, conf={conf})",
            size_multiplier=0.5,
        )

    return PolicyDecision(
        decision=DECISION_BLOCK,
        policy_name=POLICY_DUAL_THRESHOLD,
        reason=f"Both below — rank={rank}, conf={conf}",
    )


# ═════════════════════════════════════════════════════════════════════
# 4. Sizing-Simulation Policy
# ═════════════════════════════════════════════════════════════════════

def sizing_simulation_policy(row: dict[str, Any]) -> PolicyDecision:
    """
    Always ALLOWs, but assigns a tier-based size multiplier derived from
    ``ml_confidence_score`` for hypothetical P&L simulation.
    """
    conf = _num(row, "ml_confidence_score")

    if conf is None:
        return PolicyDecision(
            decision=DECISION_ALLOW,
            policy_name=POLICY_SIZING_SIMULATION,
            reason="No confidence score — default 1.0× sizing",
            size_multiplier=1.0,
        )

    multiplier = 1.0
    tier_label = "default"
    for low, high, mult in SIZING_TIERS:
        if low <= conf < high:
            multiplier = mult
            tier_label = f"{low:.2f}–{high:.2f}"
            break

    return PolicyDecision(
        decision=DECISION_ALLOW,
        policy_name=POLICY_SIZING_SIMULATION,
        reason=f"Confidence {conf:.4f} → tier {tier_label} → {multiplier}× size",
        size_multiplier=multiplier,
    )


# ═════════════════════════════════════════════════════════════════════
# Registry — convenience lookup for all policies
# ═════════════════════════════════════════════════════════════════════

def get_all_policies(rank_thresholds: dict[str, float] | None = None) -> dict[str, PolicyFn]:
    """
    Return a dict mapping policy name → callable.

    *rank_thresholds* maps a label suffix (e.g. ``"bottom_20pct"``) to
    the rank-score threshold.  When ``None``, no rank-filter variants are
    included (they are added dynamically by the policy engine from the
    dataset percentiles).
    """
    policies: dict[str, PolicyFn] = {
        POLICY_AGREEMENT_ONLY: agreement_only_policy,
        POLICY_DUAL_THRESHOLD: dual_threshold_policy,
        POLICY_SIZING_SIMULATION: sizing_simulation_policy,
    }

    if rank_thresholds:
        for suffix, threshold in rank_thresholds.items():
            name = f"{POLICY_RANK_FILTER}_{suffix}"
            policies[name] = make_rank_filter_policy(threshold, label_suffix=suffix)

    return policies

"""
Regime-Switching Policy Layer
==============================
Selects which decision policy to apply to each signal based on the
prevailing market regime.  Regime identification uses existing columns
in the signal dataset:

  • gamma_regime     (POSITIVE_GAMMA / NEGATIVE_GAMMA / NEUTRAL_GAMMA)
  • volatility_regime (LOW_VOL / NORMAL_VOL / VOL_EXPANSION)
  • macro_regime     (MACRO_NEUTRAL / RISK_ON / RISK_OFF / EVENT_LOCKDOWN)
  • global_risk_state (LOW_RISK / MODERATE_RISK / ELEVATED_RISK / HIGH_RISK / EXTREME_RISK)

A **regime mapping** is a simple dictionary from a regime combination key
to a policy name.  This keeps the layer interpretable and auditable.

Candidate policies:
  • dual_threshold
  • rank_gate_20  (block bottom 20 % by rank)
  • rank_gate_30  (block bottom 30 % by rank)
  • rank_gate_40  (block bottom 40 % by rank)
  • rank_gate_30_ev  (rank gate 30 + EV-based sizing)

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

logger = logging.getLogger(__name__)

# ── Policy identifiers ──────────────────────────────────────────────

POLICY_DUAL_THRESHOLD = "dual_threshold"
POLICY_RANK_GATE_20 = "rank_gate_20"
POLICY_RANK_GATE_30 = "rank_gate_30"
POLICY_RANK_GATE_40 = "rank_gate_40"
POLICY_RANK_GATE_30_EV = "rank_gate_30_ev"

ALL_CANDIDATE_POLICIES = [
    POLICY_DUAL_THRESHOLD,
    POLICY_RANK_GATE_20,
    POLICY_RANK_GATE_30,
    POLICY_RANK_GATE_40,
    POLICY_RANK_GATE_30_EV,
]

# ── Regime column names (from the signal dataset) ────────────────────

GAMMA_COL = "gamma_regime"
VOL_COL = "volatility_regime"
MACRO_COL = "macro_regime"
RISK_COL = "global_risk_state"

# ── Default regime → policy mapping ──────────────────────────────────

DEFAULT_REGIME_MAP: dict[str, str] = {
    # Primary gamma-driven rules
    "NEGATIVE_GAMMA": POLICY_RANK_GATE_40,
    "POSITIVE_GAMMA": POLICY_RANK_GATE_30,
    "NEUTRAL_GAMMA":  POLICY_DUAL_THRESHOLD,

    # Volatility overrides (checked before gamma)
    "VOL_EXPANSION": POLICY_DUAL_THRESHOLD,

    # Macro overrides (highest priority)
    "EVENT_LOCKDOWN": POLICY_RANK_GATE_40,
    "RISK_OFF":       POLICY_RANK_GATE_40,
    "RISK_ON":        POLICY_RANK_GATE_20,

    # Combined keys (matched before single-key)
    "MACRO_NEUTRAL+POSITIVE_GAMMA": POLICY_RANK_GATE_30,
    "MACRO_NEUTRAL+NEGATIVE_GAMMA": POLICY_RANK_GATE_40,
    "RISK_OFF+VOL_EXPANSION":       POLICY_RANK_GATE_40,
    "RISK_ON+POSITIVE_GAMMA":       POLICY_RANK_GATE_20,
}

# Fallback if no key matches
DEFAULT_FALLBACK_POLICY = POLICY_RANK_GATE_30


# ── Data structures ──────────────────────────────────────────────────

@dataclass(frozen=True)
class RegimePolicyDecision:
    """Output of the regime router for a single signal."""
    selected_policy: str
    regime_key_matched: str
    reason: str


# ── Regime key builder ───────────────────────────────────────────────

def _build_regime_keys(row: dict[str, Any]) -> list[str]:
    """
    Build a list of candidate regime keys from a signal row, ordered
    from most specific (combined) to least specific (single dimension).

    The resolver will try them in order and return the first match.
    """
    gamma = str(row.get(GAMMA_COL, "")).strip()
    vol = str(row.get(VOL_COL, "")).strip()
    macro = str(row.get(MACRO_COL, "")).strip()

    keys: list[str] = []

    # 3-way combined
    if macro and gamma and vol:
        keys.append(f"{macro}+{gamma}+{vol}")

    # 2-way combined (macro + gamma, macro + vol, gamma + vol)
    if macro and gamma:
        keys.append(f"{macro}+{gamma}")
    if macro and vol:
        keys.append(f"{macro}+{vol}")
    if gamma and vol:
        keys.append(f"{gamma}+{vol}")

    # Single dimension (priority order: macro → vol → gamma)
    if macro:
        keys.append(macro)
    if vol:
        keys.append(vol)
    if gamma:
        keys.append(gamma)

    return keys


def resolve_policy(
    row: dict[str, Any],
    regime_map: dict[str, str] | None = None,
    fallback: str = DEFAULT_FALLBACK_POLICY,
) -> RegimePolicyDecision:
    """
    Resolve which policy to apply based on the signal's regime state.

    Parameters
    ----------
    row : signal row (dict or pd.Series-like).
    regime_map : regime_key → policy_name mapping.
    fallback : policy to use when no key matches.

    Returns
    -------
    RegimePolicyDecision with the selected policy and matched key.
    """
    mapping = regime_map or DEFAULT_REGIME_MAP
    keys = _build_regime_keys(row)

    for key in keys:
        if key in mapping:
            return RegimePolicyDecision(
                selected_policy=mapping[key],
                regime_key_matched=key,
                reason=f"Regime key '{key}' → {mapping[key]}",
            )

    return RegimePolicyDecision(
        selected_policy=fallback,
        regime_key_matched="FALLBACK",
        reason=f"No regime key matched — using fallback '{fallback}'",
    )


# ── Batch application ────────────────────────────────────────────────

def _resolve_policy_vectorized(
    df: pd.DataFrame,
    regime_map: dict[str, str],
    fallback: str,
) -> tuple[pd.Series, pd.Series]:
    """
    Vectorized regime-key resolution (no row-by-row iteration).

    Returns (selected_policy Series, reason Series).
    """
    gamma = df.get(GAMMA_COL, pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    vol = df.get(VOL_COL, pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    macro = df.get(MACRO_COL, pd.Series("", index=df.index)).fillna("").astype(str).str.strip()

    # Build candidate key columns from most-specific to least-specific
    key_cols: list[tuple[str, pd.Series]] = []
    # 3-way
    k3 = macro + "+" + gamma + "+" + vol
    key_cols.append(("3-way", k3))
    # 2-way combinations
    key_cols.append(("macro+gamma", macro + "+" + gamma))
    key_cols.append(("macro+vol",   macro + "+" + vol))
    key_cols.append(("gamma+vol",   gamma + "+" + vol))
    # Single dimension (priority: macro → vol → gamma)
    key_cols.append(("macro",  macro))
    key_cols.append(("vol",    vol))
    key_cols.append(("gamma",  gamma))

    policy = pd.Series(fallback, index=df.index, dtype=object)
    reason = pd.Series(f"No regime key matched — using fallback '{fallback}'", index=df.index, dtype=object)
    matched = pd.Series(False, index=df.index)

    # Process from MOST specific to LEAST specific.
    # First match wins (skip rows already matched).
    for label, key_series in key_cols:
        hits = key_series.map(regime_map)
        mask = hits.notna() & ~matched
        if mask.any():
            policy = policy.where(~mask, hits)
            reason = reason.where(~mask, "Regime key '" + key_series + "' → " + hits.fillna(""))
            matched = matched | mask

    return policy, reason


def apply_regime_policy(
    df: pd.DataFrame,
    *,
    regime_map: dict[str, str] | None = None,
    fallback: str = DEFAULT_FALLBACK_POLICY,
    rank_col: str = "ml_rank_score",
    confidence_col: str = "ml_confidence_score",
    ev_size_col: str = "ev_size_multiplier",
) -> pd.DataFrame:
    """
    Apply regime-switching policy to every row and add decision columns.

    New columns:
      selected_regime_policy — policy name
      regime_policy_reason   — explanation
      regime_policy_decision — ALLOW / BLOCK
      regime_policy_size_mult — size multiplier

    The actual ALLOW/BLOCK decision is computed by applying the selected
    policy's gating logic inline (vectorized).
    """
    df = df.copy()
    mapping = regime_map or DEFAULT_REGIME_MAP

    # ── 1. Vectorized regime resolution ──────────────────────────────
    policy, reason = _resolve_policy_vectorized(df, mapping, fallback)
    df["selected_regime_policy"] = policy
    df["regime_policy_reason"] = reason

    # ── 2. Precompute rank percentile thresholds ─────────────────────
    rank = pd.to_numeric(df[rank_col], errors="coerce").fillna(0.0)
    conf = pd.to_numeric(df[confidence_col], errors="coerce").fillna(0.5)
    ev_mult = pd.to_numeric(df.get(ev_size_col, pd.Series(1.0, index=df.index)), errors="coerce").fillna(1.0)

    rank_clean = rank.dropna()
    thresholds = {pct: float(np.nanpercentile(rank_clean, pct)) for pct in [20, 30, 40]}

    # ── 3. Vectorized gating per policy ──────────────────────────────
    allowed = pd.Series(True, index=df.index)
    size_mult = pd.Series(1.0, index=df.index)

    m_dt = policy == POLICY_DUAL_THRESHOLD
    allowed = allowed.where(~m_dt, (rank >= 0.40) & (conf >= 0.50))

    m_rg20 = policy == POLICY_RANK_GATE_20
    allowed = allowed.where(~m_rg20, rank >= thresholds.get(20, 0.0))

    m_rg30 = policy == POLICY_RANK_GATE_30
    allowed = allowed.where(~m_rg30, rank >= thresholds.get(30, 0.0))

    m_rg40 = policy == POLICY_RANK_GATE_40
    allowed = allowed.where(~m_rg40, rank >= thresholds.get(40, 0.0))

    m_rg30ev = policy == POLICY_RANK_GATE_30_EV
    allowed = allowed.where(~m_rg30ev, rank >= thresholds.get(30, 0.0))
    size_mult = size_mult.where(~m_rg30ev, ev_mult)

    df["regime_policy_decision"] = np.where(allowed, "ALLOW", "BLOCK")
    df["regime_policy_size_mult"] = size_mult

    n_allow = int(allowed.sum())
    logger.info(
        "Regime policy applied: %d ALLOW, %d BLOCK across %d signals",
        n_allow, len(df) - n_allow, len(df),
    )

    return df


# ── Search space for regime-policy optimization ──────────────────────

def generate_regime_map_variants() -> list[tuple[str, dict[str, str]]]:
    """
    Generate a small, interpretable search space of regime-policy mappings.

    Each variant is a (label, mapping_dict) tuple.
    """
    variants: list[tuple[str, dict[str, str]]] = []

    # Baseline: use single static policy for all regimes
    for static_pol in [POLICY_RANK_GATE_30, POLICY_RANK_GATE_40, POLICY_DUAL_THRESHOLD]:
        label = f"static_{static_pol}"
        mapping = {
            "POSITIVE_GAMMA": static_pol,
            "NEGATIVE_GAMMA": static_pol,
            "NEUTRAL_GAMMA":  static_pol,
            "VOL_EXPANSION":  static_pol,
            "EVENT_LOCKDOWN": static_pol,
            "RISK_OFF":       static_pol,
            "RISK_ON":        static_pol,
            "MACRO_NEUTRAL+POSITIVE_GAMMA": static_pol,
            "MACRO_NEUTRAL+NEGATIVE_GAMMA": static_pol,
        }
        variants.append((label, mapping))

    # Variant 1: default mapping (gamma-driven)
    variants.append(("default_gamma_driven", DEFAULT_REGIME_MAP.copy()))

    # Variant 2: aggressive (risk_on → gate_20, all else → gate_30)
    variants.append(("aggressive_risk_on", {
        "POSITIVE_GAMMA": POLICY_RANK_GATE_20,
        "NEGATIVE_GAMMA": POLICY_RANK_GATE_30,
        "NEUTRAL_GAMMA":  POLICY_RANK_GATE_30,
        "VOL_EXPANSION":  POLICY_RANK_GATE_30,
        "EVENT_LOCKDOWN": POLICY_RANK_GATE_40,
        "RISK_OFF":       POLICY_RANK_GATE_40,
        "RISK_ON":        POLICY_RANK_GATE_20,
        "MACRO_NEUTRAL+POSITIVE_GAMMA": POLICY_RANK_GATE_20,
        "MACRO_NEUTRAL+NEGATIVE_GAMMA": POLICY_RANK_GATE_30,
    }))

    # Variant 3: defensive (everything > gate_30)
    variants.append(("defensive_gamma_vol", {
        "POSITIVE_GAMMA": POLICY_RANK_GATE_30,
        "NEGATIVE_GAMMA": POLICY_RANK_GATE_40,
        "NEUTRAL_GAMMA":  POLICY_RANK_GATE_40,
        "VOL_EXPANSION":  POLICY_RANK_GATE_40,
        "EVENT_LOCKDOWN": POLICY_RANK_GATE_40,
        "RISK_OFF":       POLICY_RANK_GATE_40,
        "RISK_ON":        POLICY_RANK_GATE_30,
        "MACRO_NEUTRAL+POSITIVE_GAMMA": POLICY_RANK_GATE_30,
        "MACRO_NEUTRAL+NEGATIVE_GAMMA": POLICY_RANK_GATE_40,
    }))

    # Variant 4: EV-aware (rank_gate_30_ev in favorable regimes)
    variants.append(("ev_favorable_regime", {
        "POSITIVE_GAMMA":  POLICY_RANK_GATE_30_EV,
        "NEGATIVE_GAMMA":  POLICY_RANK_GATE_40,
        "NEUTRAL_GAMMA":   POLICY_DUAL_THRESHOLD,
        "VOL_EXPANSION":   POLICY_RANK_GATE_40,
        "EVENT_LOCKDOWN":  POLICY_RANK_GATE_40,
        "RISK_OFF":        POLICY_RANK_GATE_40,
        "RISK_ON":         POLICY_RANK_GATE_30_EV,
        "MACRO_NEUTRAL+POSITIVE_GAMMA": POLICY_RANK_GATE_30_EV,
        "MACRO_NEUTRAL+NEGATIVE_GAMMA": POLICY_RANK_GATE_40,
    }))

    # Variant 5: gamma-only switching (simplest conditional)
    variants.append(("gamma_only_switch", {
        "POSITIVE_GAMMA": POLICY_RANK_GATE_20,
        "NEGATIVE_GAMMA": POLICY_RANK_GATE_40,
        "NEUTRAL_GAMMA":  POLICY_RANK_GATE_30,
    }))

    # Variant 6: vol-aware gamma switch
    variants.append(("vol_aware_gamma", {
        "POSITIVE_GAMMA": POLICY_RANK_GATE_30,
        "NEGATIVE_GAMMA": POLICY_RANK_GATE_40,
        "NEUTRAL_GAMMA":  POLICY_RANK_GATE_30,
        "VOL_EXPANSION":  POLICY_RANK_GATE_40,
        "POSITIVE_GAMMA+VOL_EXPANSION": POLICY_RANK_GATE_40,
        "RISK_OFF+VOL_EXPANSION":       POLICY_RANK_GATE_40,
    }))

    return variants

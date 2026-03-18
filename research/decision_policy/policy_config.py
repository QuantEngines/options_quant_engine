"""
Decision Policy Configuration
===============================
Centralized thresholds, buckets, and output-path definitions for the
Decision Policy research layer.

All knobs are declared once here so that evaluation scripts, policy
definitions, and the predictor all share a single source of truth.

Author: Pramit Dutta
Organization: Quant Engines

RESEARCH ONLY — never imported by production engine paths.
"""
from __future__ import annotations

from pathlib import Path

from config.settings import BASE_DIR

# ── Master toggle ────────────────────────────────────────────────────
# Policies will gracefully no-op when disabled.
DECISION_POLICY_ENABLED: bool = True

# ── Policy identifiers ──────────────────────────────────────────────
POLICY_AGREEMENT_ONLY = "agreement_only"
POLICY_RANK_FILTER = "rank_filter"
POLICY_DUAL_THRESHOLD = "dual_threshold"
POLICY_SIZING_SIMULATION = "sizing_simulation"

ALL_POLICIES = [
    POLICY_AGREEMENT_ONLY,
    POLICY_RANK_FILTER,
    POLICY_DUAL_THRESHOLD,
    POLICY_SIZING_SIMULATION,
]

# ── Decision labels ─────────────────────────────────────────────────
DECISION_ALLOW = "ALLOW"
DECISION_BLOCK = "BLOCK"
DECISION_DOWNGRADE = "DOWNGRADE"

# ── Agreement policy thresholds ─────────────────────────────────────
# Requires both ML confidence *and* engine hybrid probability above these
# for agreement to be "true".
AGREEMENT_ENGINE_MIN_PROB: float = 0.50
AGREEMENT_ML_MIN_CONFIDENCE: float = 0.50

# ── Rank-filter policy thresholds ───────────────────────────────────
# Two variants: conservative (block bottom 30 %) and moderate (bottom 20 %).
RANK_FILTER_PERCENTILES: list[int] = [20, 30]

# ── Dual-threshold policy ───────────────────────────────────────────
# Signal must pass BOTH a minimum rank score AND a minimum confidence
# score. Falling short on one dimension → DOWNGRADE; both → BLOCK.
DUAL_MIN_RANK_SCORE: float = 0.40
DUAL_MIN_CONFIDENCE: float = 0.50
# Partial pass: one dimension OK, the other below → DOWNGRADE
DUAL_DOWNGRADE_ENABLED: bool = True

# ── Sizing-simulation policy ────────────────────────────────────────
# Maps confidence ranges to hypothetical size multipliers.
# Structure: (lower_bound_inclusive, upper_bound_exclusive, multiplier)
SIZING_TIERS: list[tuple[float, float, float]] = [
    (0.00, 0.40, 0.25),   # very low  → quarter size
    (0.40, 0.55, 0.50),   # low       → half size
    (0.55, 0.65, 0.75),   # moderate  → three-quarter size
    (0.65, 0.75, 1.00),   # good      → full size
    (0.75, 1.01, 1.25),   # high      → 1.25× size
]

# ── Regime column mappings ──────────────────────────────────────────
# Column names in the backtest dataset used for regime-conditional splits.
REGIME_COLUMNS = {
    "macro": "macro_regime",
    "gamma": "gamma_regime",
    "volatility": "volatility_regime",
    "global_risk": "global_risk_state",
}

# ── Outcome columns ────────────────────────────────────────────────
PRIMARY_HIT_COL = "correct_60m"
PRIMARY_RETURN_COL = "signed_return_60m_bps"
SECONDARY_RETURN_COL = "signed_return_120m_bps"
MFE_COL = "mfe_60m_bps"
MAE_COL = "mae_60m_bps"
SESSION_RETURN_COL = "signed_return_session_close_bps"

# ── Output paths ────────────────────────────────────────────────────
DECISION_POLICY_EVAL_DIR = Path(BASE_DIR) / "research" / "ml_evaluation"
DECISION_POLICY_REPORT_JSON = DECISION_POLICY_EVAL_DIR / "decision_policy_report.json"
DECISION_POLICY_REPORT_MD = DECISION_POLICY_EVAL_DIR / "decision_policy_report.md"
DECISION_POLICY_COMPARISON_JSON = DECISION_POLICY_EVAL_DIR / "decision_policy_comparison.json"
DECISION_POLICY_COMPARISON_MD = DECISION_POLICY_EVAL_DIR / "decision_policy_comparison.md"
DECISION_POLICY_COMPARISON_CSV = DECISION_POLICY_EVAL_DIR / "decision_policy_comparison.csv"

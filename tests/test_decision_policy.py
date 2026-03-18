"""
Tests for the Decision Policy Layer
=============================================
Covers: policy definitions, policy engine, policy config, predictor
registration, and cross-methodology comparison structure.
"""
from __future__ import annotations

import pytest

from research.decision_policy.policy_config import (
    DECISION_ALLOW,
    DECISION_BLOCK,
    DECISION_DOWNGRADE,
    POLICY_AGREEMENT_ONLY,
    POLICY_DUAL_THRESHOLD,
    POLICY_SIZING_SIMULATION,
    SIZING_TIERS,
)
from research.decision_policy.policy_definitions import (
    PolicyDecision,
    agreement_only_policy,
    dual_threshold_policy,
    make_rank_filter_policy,
    sizing_simulation_policy,
    get_all_policies,
)


# ── PolicyDecision dataclass ────────────────────────────────────────

class TestPolicyDecision:
    def test_is_frozen(self):
        dec = PolicyDecision(decision="ALLOW", policy_name="test", reason="ok")
        with pytest.raises(AttributeError):
            dec.decision = "BLOCK"  # type: ignore[misc]

    def test_default_size_multiplier(self):
        dec = PolicyDecision(decision="ALLOW", policy_name="test", reason="ok")
        assert dec.size_multiplier == 1.0


# ── Agreement-only policy ───────────────────────────────────────────

class TestAgreementOnlyPolicy:
    def test_both_above_threshold(self):
        row = {"hybrid_move_probability": 0.60, "ml_confidence_score": 0.60}
        dec = agreement_only_policy(row)
        assert dec.decision == DECISION_ALLOW
        assert dec.policy_name == POLICY_AGREEMENT_ONLY

    def test_engine_below_threshold(self):
        row = {"hybrid_move_probability": 0.30, "ml_confidence_score": 0.70}
        dec = agreement_only_policy(row)
        assert dec.decision == DECISION_DOWNGRADE
        assert dec.size_multiplier == 0.5

    def test_ml_below_threshold(self):
        row = {"hybrid_move_probability": 0.70, "ml_confidence_score": 0.30}
        dec = agreement_only_policy(row)
        assert dec.decision == DECISION_DOWNGRADE

    def test_both_below_threshold(self):
        row = {"hybrid_move_probability": 0.30, "ml_confidence_score": 0.30}
        dec = agreement_only_policy(row)
        assert dec.decision == DECISION_BLOCK

    def test_missing_values(self):
        row = {}
        dec = agreement_only_policy(row)
        assert dec.decision == DECISION_BLOCK


# ── Rank-filter policy ──────────────────────────────────────────────

class TestRankFilterPolicy:
    def test_above_threshold_allows(self):
        policy = make_rank_filter_policy(0.30, "bottom_30pct")
        dec = policy({"ml_rank_score": 0.50})
        assert dec.decision == DECISION_ALLOW

    def test_below_threshold_blocks(self):
        policy = make_rank_filter_policy(0.30, "bottom_30pct")
        dec = policy({"ml_rank_score": 0.10})
        assert dec.decision == DECISION_BLOCK

    def test_missing_rank_blocks(self):
        policy = make_rank_filter_policy(0.30, "bottom_30pct")
        dec = policy({})
        assert dec.decision == DECISION_BLOCK

    def test_exact_threshold_allows(self):
        policy = make_rank_filter_policy(0.50)
        dec = policy({"ml_rank_score": 0.50})
        assert dec.decision == DECISION_ALLOW


# ── Dual-threshold policy ───────────────────────────────────────────

class TestDualThresholdPolicy:
    def test_both_pass(self):
        row = {"ml_rank_score": 0.60, "ml_confidence_score": 0.70}
        dec = dual_threshold_policy(row)
        assert dec.decision == DECISION_ALLOW

    def test_rank_fails_only(self):
        row = {"ml_rank_score": 0.10, "ml_confidence_score": 0.70}
        dec = dual_threshold_policy(row)
        assert dec.decision == DECISION_DOWNGRADE

    def test_both_fail(self):
        row = {"ml_rank_score": 0.10, "ml_confidence_score": 0.20}
        dec = dual_threshold_policy(row)
        assert dec.decision == DECISION_BLOCK

    def test_missing_both(self):
        dec = dual_threshold_policy({})
        assert dec.decision == DECISION_BLOCK


# ── Sizing-simulation policy ────────────────────────────────────────

class TestSizingSimulationPolicy:
    def test_always_allows(self):
        dec = sizing_simulation_policy({"ml_confidence_score": 0.30})
        assert dec.decision == DECISION_ALLOW

    def test_low_confidence_small_size(self):
        dec = sizing_simulation_policy({"ml_confidence_score": 0.30})
        assert dec.size_multiplier < 1.0

    def test_high_confidence_large_size(self):
        dec = sizing_simulation_policy({"ml_confidence_score": 0.80})
        assert dec.size_multiplier > 1.0

    def test_missing_confidence_default(self):
        dec = sizing_simulation_policy({})
        assert dec.size_multiplier == 1.0


# ── get_all_policies ────────────────────────────────────────────────

class TestGetAllPolicies:
    def test_base_policies_registered(self):
        policies = get_all_policies()
        assert POLICY_AGREEMENT_ONLY in policies
        assert POLICY_DUAL_THRESHOLD in policies
        assert POLICY_SIZING_SIMULATION in policies

    def test_rank_filter_variants(self):
        policies = get_all_policies(rank_thresholds={"bottom_20pct": 0.20})
        assert "rank_filter_bottom_20pct" in policies


# ── Predictor registration ──────────────────────────────────────────

class TestDecisionPolicyPredictor:
    def test_registered_in_factory(self):
        from engine.predictors.factory import _ensure_registry
        reg = _ensure_registry()
        assert "research_decision_policy" in reg

    def test_predictor_name(self):
        from engine.predictors.decision_policy_predictor import ResearchDecisionPolicyPredictor
        pred = ResearchDecisionPolicyPredictor()
        assert pred.name == "research_decision_policy"

    def test_satisfies_protocol(self):
        from engine.predictors.protocol import MovePredictor
        from engine.predictors.decision_policy_predictor import ResearchDecisionPolicyPredictor
        assert isinstance(ResearchDecisionPolicyPredictor(), MovePredictor)

from __future__ import annotations

import unittest

from config.policy_resolver import temporary_parameter_pack
from risk.option_efficiency_layer import (
    build_option_efficiency_state,
    classify_option_efficiency_state,
    score_option_efficiency_candidate,
)


class OptionEfficiencyLayerTests(unittest.TestCase):
    def test_direct_expected_move_uses_atm_iv_and_expiry(self):
        state = build_option_efficiency_state(
            spot=22000,
            atm_iv=18.0,
            expiry_value="2026-03-21",
            valuation_time="2026-03-14T10:00:00+05:30",
            direction="CALL",
            strike=22000,
            option_type="CE",
            entry_price=110,
            target=145,
            stop_loss=92,
        )

        self.assertEqual(state["expected_move_quality"], "DIRECT")
        self.assertIsNotNone(state["expected_move_points"])
        self.assertGreater(state["expected_move_points"], 0)
        self.assertGreater(state["target_reachability_score"], 50)

    def test_fallback_iv_path_stays_interpretable(self):
        state = build_option_efficiency_state(
            spot=22000,
            fallback_iv=0.19,
            expiry_value="2026-03-21",
            valuation_time="2026-03-14T10:00:00+05:30",
            direction="CALL",
            strike=22000,
            option_type="CE",
            entry_price=110,
            target=145,
        )

        self.assertEqual(state["expected_move_quality"], "FALLBACK")
        self.assertIn("fallback_iv_used", state["option_efficiency_diagnostics"]["warnings"])

    def test_india_vix_can_anchor_expected_move_when_atm_iv_is_missing(self):
        state = build_option_efficiency_state(
            spot=22000,
            india_vix_level=16.5,
            india_vix_change_24h=5.2,
            expiry_value="2026-03-21",
            valuation_time="2026-03-14T10:00:00+05:30",
            direction="CALL",
            strike=22000,
            option_type="CE",
            entry_price=110,
            target=145,
        )

        self.assertEqual(state["expected_move_quality"], "FALLBACK")
        self.assertEqual(state["option_efficiency_diagnostics"]["iv_source"], "INDIA_VIX")
        self.assertIn("india_vix_used", state["option_efficiency_diagnostics"]["warnings"])
        self.assertIsNotNone(state["expected_move_points"])

    def test_missing_iv_and_expiry_degrades_to_neutral(self):
        state = build_option_efficiency_state(
            spot=22000,
            direction="CALL",
            strike=22000,
            option_type="CE",
            entry_price=110,
            target=145,
        )

        self.assertTrue(state["neutral_fallback"])
        self.assertEqual(state["expected_move_quality"], "UNAVAILABLE")
        self.assertEqual(state["option_efficiency_score"], 50)

    def test_far_otm_strike_scores_as_less_efficient(self):
        state = build_option_efficiency_state(
            spot=22000,
            atm_iv=15.0,
            expiry_value="2026-03-18",
            valuation_time="2026-03-14T10:00:00+05:30",
            direction="CALL",
            strike=22500,
            option_type="CE",
            entry_price=32,
            target=52,
        )

        self.assertEqual(state["strike_moneyness_bucket"], "OTM")
        self.assertLess(state["strike_efficiency_score"], 60)

    def test_overnight_poor_efficiency_can_block_hold(self):
        state = build_option_efficiency_state(
            spot=22000,
            atm_iv=13.0,
            expiry_value="2026-03-17",
            valuation_time="2026-03-14T15:10:00+05:30",
            direction="CALL",
            strike=22300,
            option_type="CE",
            entry_price=145,
            target=210,
            stop_loss=105,
            holding_profile="OVERNIGHT",
            global_risk_state={
                "global_risk_state": "GLOBAL_NEUTRAL",
                "holding_context": {
                    "holding_profile": "OVERNIGHT",
                    "overnight_relevant": True,
                },
            },
        )

        self.assertFalse(state["overnight_hold_allowed"])
        self.assertGreaterEqual(state["overnight_option_efficiency_penalty"], 5)

    def test_target_reachability_scoring_is_smooth_and_monotonic(self):
        common = {
            "spot": 22000,
            "atm_iv": 18.0,
            "expiry_value": "2026-03-21",
            "valuation_time": "2026-03-14T10:00:00+05:30",
            "direction": "CALL",
            "strike": 22000,
            "option_type": "CE",
            "entry_price": 110,
        }

        near_target = build_option_efficiency_state(**common, target=130)
        mid_target = build_option_efficiency_state(**common, target=260)
        far_target = build_option_efficiency_state(**common, target=420)

        self.assertGreaterEqual(near_target["target_reachability_score"], mid_target["target_reachability_score"])
        self.assertGreaterEqual(mid_target["target_reachability_score"], far_target["target_reachability_score"])
        self.assertNotEqual(near_target["target_reachability_score"], mid_target["target_reachability_score"])

    def test_option_efficiency_component_weights_are_parameterized(self):
        features = {
            "expected_move_coverage_ratio": 2.0,
            "premium_coverage_ratio": 0.1,
            "strike_distance_ratio": 0.0,
            "strike_moneyness_bucket": "ATM",
        }

        with temporary_parameter_pack(
            overrides={
                "option_efficiency.core.option_efficiency_premium_weight": 1.0,
                "option_efficiency.core.option_efficiency_target_weight": 0.0,
                "option_efficiency.core.option_efficiency_strike_weight": 0.0,
            },
        ):
            state = classify_option_efficiency_state(features)

        self.assertEqual(state.option_efficiency_score, state.premium_efficiency_score)

    def test_candidate_score_adjustment_is_parameterized(self):
        row = {
            "strikePrice": 22000,
            "OPTION_TYP": "CE",
            "lastPrice": 95,
            "impliedVolatility": 18.0,
            "DELTA": 0.5,
        }

        with temporary_parameter_pack(
            overrides={
                "option_efficiency.core.high_efficiency_threshold": 0,
                "option_efficiency.core.candidate_high_efficiency_adjustment": 7,
            },
        ):
            payload = score_option_efficiency_candidate(
                row,
                spot=22000,
                direction="CALL",
                selected_expiry="2026-03-21",
                valuation_time="2026-03-14T10:00:00+05:30",
            )

        self.assertEqual(payload["score_adjustment"], 7)

    def test_overnight_option_efficiency_penalty_policy_is_parameterized(self):
        features = {
            "expected_move_coverage_ratio": 2.0,
            "premium_coverage_ratio": 2.0,
            "strike_distance_ratio": 0.0,
            "strike_moneyness_bucket": "ATM",
            "holding_context": {"overnight_relevant": True},
        }

        with temporary_parameter_pack(
            overrides={
                "option_efficiency.core.overnight_option_efficiency_weak_threshold": 100,
                "option_efficiency.core.overnight_option_efficiency_weak_penalty": 5,
                "option_efficiency.core.overnight_block_threshold": 5,
            },
        ):
            state = classify_option_efficiency_state(features)

        self.assertFalse(state.overnight_hold_allowed)
        self.assertEqual(state.overnight_hold_reason, "option_efficiency_weak")
        self.assertEqual(state.overnight_option_efficiency_penalty, 5)


if __name__ == "__main__":
    unittest.main()

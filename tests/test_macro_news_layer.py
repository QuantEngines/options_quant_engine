from __future__ import annotations

import json
import unittest
from pathlib import Path

from backtest.macro_news_scenario_runner import run_scenario
from config.settings import BASE_DIR
from macro.macro_news_aggregator import build_macro_news_state
from macro.engine_adjustments import compute_macro_news_adjustments
from macro.scope_utils import headline_mentions_symbol
from news.service import HeadlineIngestionService
from news.classifier import classify_headline
from news.models import HeadlineIngestionState, HeadlineRecord, coerce_headline_timestamp


SCENARIO_FILE = Path(BASE_DIR) / "config/macro_news_scenarios.json"


def _load_scenarios():
    return json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))


class MacroNewsLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = {item["name"]: item for item in _load_scenarios()}

    def test_headline_classification_policy(self):
        record = HeadlineRecord(
            timestamp=coerce_headline_timestamp("2026-03-13T09:05:00+05:30"),
            source="TEST",
            headline="RBI Governor says inflation trajectory remains watchful",
            url_or_identifier="test-rbi-001",
            category="MACRO",
        )
        result = classify_headline(record)
        self.assertEqual(result.primary_category, "policy")
        self.assertGreater(result.volatility_shock_score, 0)
        self.assertGreater(result.headline_impact_score, 0)

    def test_neutral_day_scenario(self):
        result = run_scenario(self.scenarios["neutral_day"])
        state = result["macro_news_state"]
        self.assertEqual(state["macro_regime"], "MACRO_NEUTRAL")
        self.assertTrue(state["neutral_fallback"])
        self.assertEqual(state["headline_count"], 0)

    def test_rbi_event_window_scenario(self):
        result = run_scenario(self.scenarios["rbi_event_window"])
        self.assertEqual(result["event_state"]["event_window_status"], "PRE_EVENT_LOCKDOWN")
        self.assertTrue(result["macro_news_state"]["event_lockdown_flag"])
        self.assertEqual(result["macro_news_state"]["macro_regime"], "EVENT_LOCKDOWN")

    def test_risk_off_geopolitical_burst_scenario(self):
        result = run_scenario(self.scenarios["risk_off_geopolitical_burst"])
        state = result["macro_news_state"]
        self.assertEqual(state["macro_regime"], "RISK_OFF")
        self.assertIn("volatility_shock_high", state["macro_regime_reasons"])
        self.assertGreater(state["volatility_shock_score"], 0)
        self.assertGreater(state["news_confidence_score"], 0)
        self.assertGreaterEqual(state["headline_count"], 3)

    def test_risk_on_soft_landing_scenario(self):
        result = run_scenario(self.scenarios["risk_on_soft_landing"])
        state = result["macro_news_state"]
        self.assertEqual(state["macro_regime"], "RISK_ON")
        self.assertIn("sentiment_risk_on", state["macro_regime_reasons"])

    def test_stale_news_feed_scenario(self):
        result = run_scenario(self.scenarios["stale_news_feed"])
        state = result["macro_news_state"]
        self.assertTrue(state["neutral_fallback"])
        self.assertEqual(state["macro_regime"], "MACRO_NEUTRAL")
        self.assertIn("neutral_fallback", state["macro_regime_reasons"])

    def test_macro_news_state_ignores_future_headlines(self):
        as_of = coerce_headline_timestamp("2026-03-14T10:00:00+05:30")
        headline_state = HeadlineIngestionState(
            records=[
                HeadlineRecord(
                    timestamp=coerce_headline_timestamp("2026-03-14T09:55:00+05:30"),
                    source="TEST",
                    headline="SEBI probe raises uncertainty for Indian markets",
                    url_or_identifier="past-risk",
                ),
                HeadlineRecord(
                    timestamp=coerce_headline_timestamp("2026-03-14T10:45:00+05:30"),
                    source="TEST",
                    headline="Nifty wins broad upgrade as global risk sharply improves",
                    url_or_identifier="future-risk-on",
                ),
            ],
            provider_name="TEST",
            fetched_at=as_of,
            latest_headline_at=as_of,
            is_stale=False,
            data_available=True,
            neutral_fallback=False,
            stale_after_minutes=60,
        )

        state = build_macro_news_state(
            event_state={"event_window_status": "CLEAR", "event_lockdown_flag": False},
            headline_state=headline_state,
            as_of=as_of,
            symbol="NIFTY",
        )

        self.assertEqual(state.headline_count, 1)
        self.assertEqual(state.classified_headline_count, 1)
        self.assertIn("future_headline_records_ignored:1", state.warnings)
        self.assertLessEqual(state.macro_sentiment_score, 0)

    def test_headline_service_neutralizes_all_future_records(self):
        as_of = coerce_headline_timestamp("2026-03-14T10:00:00+05:30")

        class _FutureProvider:
            provider_name = "TEST"

            def fetch_headlines(self, *, symbol=None, limit=None):
                return [
                    HeadlineRecord(
                        timestamp=coerce_headline_timestamp("2026-03-14T10:45:00+05:30"),
                        source="TEST",
                        headline="Future headline should not be visible",
                        url_or_identifier="future-only",
                    )
                ]

            def last_fetch_metadata(self):
                return {}

        state = HeadlineIngestionService(_FutureProvider(), enabled=True).fetch(as_of=as_of)

        self.assertTrue(state.neutral_fallback)
        self.assertFalse(state.data_available)
        self.assertEqual(state.records, [])
        self.assertIn("future_headline_records_ignored:1", state.warnings)

    def test_engine_adjustment_risk_off_conflicting_call(self):
        adjustments = compute_macro_news_adjustments(
            direction="CALL",
            macro_news_state={
                "macro_regime": "RISK_OFF",
                "macro_sentiment_score": -30,
                "volatility_shock_score": 72,
                "news_confidence_score": 65,
                "event_lockdown_flag": False,
                "neutral_fallback": False,
            },
        )
        self.assertLess(adjustments["macro_adjustment_score"], 0)
        self.assertLess(adjustments["macro_confirmation_adjustment"], 0)
        self.assertLess(adjustments["macro_position_size_multiplier"], 1.0)

    def test_engine_adjustment_event_lockdown(self):
        adjustments = compute_macro_news_adjustments(
            direction="PUT",
            macro_news_state={
                "macro_regime": "EVENT_LOCKDOWN",
                "macro_sentiment_score": 0,
                "volatility_shock_score": 80,
                "news_confidence_score": 55,
                "event_lockdown_flag": True,
                "neutral_fallback": False,
            },
        )
        self.assertTrue(adjustments["event_lockdown_flag"])
        self.assertEqual(adjustments["macro_position_size_multiplier"], 0.0)

    def test_engine_graceful_degradation_when_news_missing(self):
        adjustments = compute_macro_news_adjustments(
            direction="CALL",
            macro_news_state=None,
        )
        self.assertEqual(adjustments["macro_regime"], "MACRO_NEUTRAL")
        self.assertEqual(adjustments["macro_adjustment_score"], 0)
        self.assertEqual(adjustments["macro_position_size_multiplier"], 1.0)

    def test_symbol_relevance_helper(self):
        self.assertTrue(headline_mentions_symbol("NIFTY", "Nifty gains as bond yields cool"))
        self.assertTrue(headline_mentions_symbol("NIFTY", "Indian markets rise as Sensex and broader equities extend gains"))
        self.assertTrue(headline_mentions_symbol("BANKNIFTY", "Financials rally lifts Bank Nifty sentiment"))
        self.assertTrue(headline_mentions_symbol("BANKNIFTY", "Indian banking stocks rebound as private lenders lead market gains"))
        self.assertTrue(headline_mentions_symbol("FINNIFTY", "Indian financial services stocks gain after softer yields"))
        self.assertTrue(headline_mentions_symbol("RELIANCE", "Reliance board approves capex update"))
        self.assertFalse(headline_mentions_symbol("NIFTY", "US stocks rally as Treasury yields cool after Fed remarks"))
        self.assertFalse(headline_mentions_symbol("RELIANCE", "Infosys board discusses buyback plan"))


if __name__ == "__main__":
    unittest.main()

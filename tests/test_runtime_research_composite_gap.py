from __future__ import annotations

import pandas as pd

from research.signal_evaluation.runtime_research_composite_gap import (
    build_runtime_research_composite_gap_report,
    prepare_runtime_research_composite_frame,
)


def _gap_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-05-25T10:00:00+05:30",
                "direction": "CALL",
                "runtime_composite_score": 48,
                "composite_signal_score": 86,
                "trade_strength": 52,
                "move_probability": 0.42,
                "provider_health_status": "WEAK",
                "data_quality_status": "GOOD",
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "RISK_OFF",
                "spot_vs_flip": "ABOVE_FLIP",
                "historical_wall_state": "NEAR_RESISTANCE_WALL",
                "support_wall_distance_pct": -0.35,
                "resistance_wall_distance_pct": 0.08,
                "max_pain_zone": "NEAR_MAX_PAIN",
                "execution_suggestion_usable": False,
                "analytics_usable": True,
                "ta_entry_timing_state": "CANDLE_CONFIRMED_CALL",
                "ta_candle_state": "CANDLE_CONFIRMED_CALL",
                "signed_return_60m_bps": 20,
                "correct_60m": 1,
                "mfe_60m_bps": 24,
                "mae_60m_bps": -4,
                "direction_score": 100,
                "magnitude_score": 80,
                "timing_score": 75,
                "tradeability_score": 95,
            },
            {
                "signal_timestamp": "2026-05-25T10:05:00+05:30",
                "direction": "CALL",
                "runtime_composite_score": 58,
                "composite_signal_score": 82,
                "trade_strength": 55,
                "move_probability": 0.47,
                "provider_health_status": "WEAK",
                "data_quality_status": "GOOD",
                "confirmation_status": "CONFIRMED",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "RISK_OFF",
                "spot_vs_flip": "ABOVE_FLIP",
                "historical_wall_state": "NEAR_RESISTANCE_WALL",
                "support_wall_distance_pct": -0.28,
                "resistance_wall_distance_pct": 0.18,
                "max_pain_zone": "NEAR_MAX_PAIN",
                "execution_suggestion_usable": False,
                "analytics_usable": True,
                "ta_entry_timing_state": "CANDLE_FORMING",
                "ta_candle_state": "CANDLE_FORMING",
                "signed_return_60m_bps": 8,
                "correct_60m": 1,
                "mfe_60m_bps": 12,
                "mae_60m_bps": -6,
                "direction_score": 90,
                "magnitude_score": 70,
                "timing_score": 65,
                "tradeability_score": 80,
            },
            {
                "signal_timestamp": "2026-05-25T10:10:00+05:30",
                "direction": "PUT",
                "runtime_composite_score": 72,
                "composite_signal_score": 42,
                "trade_strength": 78,
                "move_probability": 0.68,
                "provider_health_status": "GOOD",
                "data_quality_status": "GOOD",
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "VOL_EXPANSION",
                "global_risk_state": "RISK_ON",
                "spot_vs_flip": "BELOW_FLIP",
                "historical_wall_state": "NO_NEAR_WALL",
                "support_wall_distance_pct": -0.75,
                "resistance_wall_distance_pct": 0.65,
                "max_pain_zone": "AWAY_FROM_MAX_PAIN",
                "execution_suggestion_usable": True,
                "analytics_usable": True,
                "signed_return_60m_bps": -12,
                "correct_60m": 0,
                "mfe_60m_bps": 3,
                "mae_60m_bps": -18,
                "direction_score": 20,
                "magnitude_score": 25,
                "timing_score": 10,
                "tradeability_score": 15,
            },
            {
                "signal_timestamp": "2026-05-25T10:15:00+05:30",
                "direction": "PUT",
                "runtime_composite_score": 74,
                "composite_signal_score": 88,
                "trade_strength": 82,
                "move_probability": 0.72,
                "provider_health_status": "GOOD",
                "data_quality_status": "GOOD",
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "VOL_EXPANSION",
                "global_risk_state": "RISK_ON",
                "spot_vs_flip": "BELOW_FLIP",
                "historical_wall_state": "NO_NEAR_WALL",
                "support_wall_distance_pct": -0.45,
                "resistance_wall_distance_pct": 0.35,
                "max_pain_zone": "AWAY_FROM_MAX_PAIN",
                "execution_suggestion_usable": True,
                "analytics_usable": True,
                "signed_return_60m_bps": 15,
                "correct_60m": 1,
                "mfe_60m_bps": 18,
                "mae_60m_bps": -3,
                "direction_score": 100,
                "magnitude_score": 85,
                "timing_score": 80,
                "tradeability_score": 95,
            },
        ]
    )


def test_prepare_runtime_research_composite_frame_builds_gap_fields():
    prepared = prepare_runtime_research_composite_frame(_gap_rows(), report_date="2026-05-25")

    assert len(prepared) == 4
    assert prepared["has_comparable_scores"].all()
    assert prepared.loc[0, "score_gap_research_minus_runtime"] == 38
    assert str(prepared.loc[0, "runtime_bucket"]) == "<50"
    assert str(prepared.loc[0, "research_bucket"]) == "80+"
    assert prepared.loc[0, "nearest_wall_distance_pct"] == 0.08
    assert prepared.loc[0, "nearest_wall_bucket"] == "AT_WALL"
    assert prepared.loc[0, "wall_context_state"] == "NEAR_RESISTANCE_WALL"


def test_build_runtime_research_composite_gap_report_flags_blindspots():
    report = build_runtime_research_composite_gap_report(_gap_rows(), report_date="2026-05-25")

    assert report["coverage"]["comparable_rows"] == 4
    assert report["diagnostic_read"]["blindspot_rows"] == 2
    assert report["diagnostic_read"]["false_confidence_rows"] == 1
    assert "provider_quality_suppressed_execution_context" in report["diagnostic_read"]["primary_read"]
    assert "confirmation_present_despite_low_runtime_score" in report["diagnostic_read"]["primary_read"]

    blindspot = report["cohorts"]["research_high_runtime_low"]["metrics"]
    assert blindspot["avg_runtime_composite_score"] == 53.0
    assert blindspot["avg_research_composite_score"] == 84.0
    assert blindspot["provider_weak_share"] == 100.0
    assert blindspot["execution_usable_share"] == 0.0

    components = {
        row["component"]: row
        for row in report["cohorts"]["research_high_runtime_low"]["research_component_drivers"]
    }
    assert components["direction_score"]["high_component_share"] == 100.0
    assert components["tradeability_score"]["avg_score"] == 87.5

    subgroups = report["blindspot_subgroups"]
    assert subgroups["runtime_bucket"][0]["runtime_bucket"] == "<50"
    assert subgroups["runtime_bucket"][0]["row_count"] == 1
    assert subgroups["gamma_x_volatility"][0]["subgroup"] == "POSITIVE_GAMMA / NORMAL_VOL"
    assert subgroups["wall_context_state"][0]["wall_context_state"] == "NEAR_RESISTANCE_WALL"
    assert report["diagnostic_read"]["largest_blindspot_runtime_bucket"].startswith("<50")

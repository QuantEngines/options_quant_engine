from __future__ import annotations

import pandas as pd

from research.signal_evaluation.runtime_blindspot_feature_audit import (
    build_runtime_blindspot_feature_audit_report,
    prepare_runtime_blindspot_feature_frame,
)


def _audit_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-05-25T10:00:00+05:30",
                "direction": "CALL",
                "runtime_composite_score": 42,
                "composite_signal_score": 88,
                "trade_strength": 25,
                "move_probability": 0.58,
                "provider_health_status": "WEAK",
                "data_quality_status": "CAUTION",
                "analytics_usable": True,
                "execution_suggestion_usable": False,
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "VOL_EXPANSION",
                "global_risk_state": "RISK_OFF",
                "ta_entry_timing_state": "CANDLE_CONFIRMED_CALL",
                "ta_candle_state": "CANDLE_CONFIRMED_CALL",
                "ta_entry_timing_score": 82,
                "support_wall_distance_pct": -0.35,
                "resistance_wall_distance_pct": 0.08,
                "historical_wall_state": "NEAR_RESISTANCE_WALL",
                "max_pain_zone": "NEAR_MAX_PAIN",
                "correct_60m": 1,
                "signed_return_60m_bps": 18,
                "mfe_60m_bps": 25,
                "mae_60m_bps": -5,
                "outcome_status": "COMPLETE",
            },
            {
                "signal_timestamp": "2026-05-25T10:05:00+05:30",
                "direction": "CALL",
                "runtime_composite_score": 35,
                "composite_signal_score": 84,
                "trade_strength": 20,
                "move_probability": 0.56,
                "provider_health_status": "WEAK",
                "data_quality_status": "CAUTION",
                "analytics_usable": True,
                "execution_suggestion_usable": False,
                "confirmation_status": "CONFIRMED",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "VOL_EXPANSION",
                "global_risk_state": "RISK_OFF",
                "ta_entry_timing_state": "CANDLE_FORMING",
                "ta_candle_state": "CANDLE_FORMING",
                "ta_entry_timing_score": 58,
                "support_wall_distance_pct": -0.25,
                "resistance_wall_distance_pct": 0.12,
                "historical_wall_state": "NEAR_RESISTANCE_WALL",
                "max_pain_zone": "NEAR_MAX_PAIN",
                "correct_60m": 1,
                "signed_return_60m_bps": 12,
                "mfe_60m_bps": 18,
                "mae_60m_bps": -6,
                "outcome_status": "COMPLETE",
            },
            {
                "signal_timestamp": "2026-05-25T10:10:00+05:30",
                "direction": "PUT",
                "runtime_composite_score": 62,
                "composite_signal_score": 55,
                "trade_strength": 72,
                "move_probability": 0.66,
                "provider_health_status": "GOOD",
                "data_quality_status": "GOOD",
                "analytics_usable": True,
                "execution_suggestion_usable": True,
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "GLOBAL_NEUTRAL",
                "ta_entry_timing_state": "CANDLE_REJECTION_BULLISH",
                "ta_candle_state": "CANDLE_REJECTION_BULLISH",
                "ta_entry_timing_score": 20,
                "support_wall_distance_pct": -0.8,
                "resistance_wall_distance_pct": 0.75,
                "historical_wall_state": "AWAY_FROM_NEAREST_WALL",
                "max_pain_zone": "FAR_FROM_MAX_PAIN",
                "correct_60m": 0,
                "signed_return_60m_bps": -10,
                "mfe_60m_bps": 4,
                "mae_60m_bps": -18,
                "outcome_status": "COMPLETE",
            },
            {
                "signal_timestamp": "2026-05-25T10:15:00+05:30",
                "direction": "PUT",
                "runtime_composite_score": 52,
                "composite_signal_score": 62,
                "trade_strength": 50,
                "move_probability": 0.48,
                "provider_health_status": "GOOD",
                "data_quality_status": "GOOD",
                "analytics_usable": True,
                "execution_suggestion_usable": True,
                "confirmation_status": "NO_DIRECTION",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "GLOBAL_NEUTRAL",
                "ta_entry_timing_state": "CANDLE_REJECTION_BULLISH",
                "ta_candle_state": "CANDLE_REJECTION_BULLISH",
                "ta_entry_timing_score": 25,
                "support_wall_distance_pct": -0.7,
                "resistance_wall_distance_pct": 0.7,
                "historical_wall_state": "AWAY_FROM_NEAREST_WALL",
                "max_pain_zone": "FAR_FROM_MAX_PAIN",
                "correct_60m": 0,
                "signed_return_60m_bps": -8,
                "mfe_60m_bps": 3,
                "mae_60m_bps": -12,
                "outcome_status": "COMPLETE",
            },
        ]
    )


def test_prepare_runtime_blindspot_feature_frame_builds_provider_context():
    prepared = prepare_runtime_blindspot_feature_frame(_audit_rows(), report_date="2026-05-25")

    assert len(prepared) == 4
    assert prepared.loc[0, "provider_execution_context"] == "ANALYTICS_ONLY_EXECUTION_BLOCKED"
    assert prepared.loc[0, "nearest_wall_distance_pct"] == 0.08
    assert prepared.loc[0, "nearest_wall_bucket"] == "AT_WALL"
    assert str(prepared.loc[0, "runtime_bucket"]) == "<50"


def test_build_runtime_blindspot_feature_audit_report_ranks_live_features():
    report = build_runtime_blindspot_feature_audit_report(_audit_rows(), report_date="2026-05-25")

    assert report["coverage"]["blindspot_rows"] == 2
    assert report["coverage"]["baseline_rows"] == 2
    assert report["outcome_summary"]["blindspot"]["hit_rate_60m"] == 100.0

    ranked_features = {row["feature"] for row in report["ranked_live_feature_candidates"]}
    assert "provider_execution_context" in ranked_features
    assert "gamma_regime" in ranked_features
    assert "ta_entry_timing_score" in ranked_features

    families = {row["family"] for row in report["family_summary"]}
    assert "provider_quality" in families
    assert "regime_context" in families
    assert report["diagnostic_read"]["top_feature"] is not None

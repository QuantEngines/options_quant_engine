from __future__ import annotations

import pandas as pd

from research.signal_evaluation.runtime_score_supplement_replay import (
    build_runtime_score_supplement_replay_report,
    prepare_runtime_score_supplement_replay_frame,
)


def _replay_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-05-25T10:00:00+05:30",
                "direction": "CALL",
                "runtime_composite_score": 55,
                "composite_signal_score": 88,
                "analytics_usable": True,
                "execution_suggestion_usable": False,
                "provider_health_status": "WEAK",
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "VOL_EXPANSION",
                "ta_candle_state": "CANDLE_CONFIRMED_CALL",
                "ta_entry_timing_state": "CANDLE_CONFIRMED_CALL",
                "ta_candle_direction": "CALL",
                "ta_candle_range_expanded": True,
                "ta_candle_range_expansion_ratio": 1.4,
                "ta_candle_momentum_3_bps": 5,
                "ta_candle_close_location": 0.82,
                "ta_entry_timing_score": 80,
                "historical_wall_state": "AWAY_FROM_NEAREST_WALL",
                "wall_context_state": "AWAY_FROM_NEAREST_WALL",
                "support_wall_distance_pct": -0.65,
                "resistance_wall_distance_pct": 0.70,
                "max_pain_zone": "FAR_FROM_MAX_PAIN",
                "correct_60m": 1,
                "signed_return_60m_bps": 20,
                "mfe_60m_bps": 24,
                "mae_60m_bps": -4,
                "outcome_status": "COMPLETE",
            },
            {
                "signal_timestamp": "2026-05-25T10:05:00+05:30",
                "direction": "PUT",
                "runtime_composite_score": 58,
                "composite_signal_score": 84,
                "analytics_usable": False,
                "execution_suggestion_usable": False,
                "provider_health_status": "WEAK",
                "confirmation_status": "CONFIRMED",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "VOL_EXPANSION",
                "ta_candle_state": "CANDLE_REJECTION_BEARISH",
                "ta_entry_timing_state": "CANDLE_REJECTION_BEARISH",
                "ta_candle_direction": "PUT",
                "ta_candle_range_expanded": True,
                "ta_candle_range_expansion_ratio": 1.3,
                "ta_candle_momentum_3_bps": -4,
                "ta_candle_close_location": 0.25,
                "ta_entry_timing_score": 62,
                "historical_wall_state": "NEAR_SUPPORT_WALL",
                "wall_context_state": "NEAR_SUPPORT_WALL",
                "support_wall_distance_pct": -0.15,
                "resistance_wall_distance_pct": 0.55,
                "max_pain_zone": "NEAR_MAX_PAIN",
                "correct_60m": 1,
                "signed_return_60m_bps": 12,
                "mfe_60m_bps": 16,
                "mae_60m_bps": -5,
                "outcome_status": "COMPLETE",
            },
            {
                "signal_timestamp": "2026-05-25T10:10:00+05:30",
                "direction": "CALL",
                "runtime_composite_score": 62,
                "composite_signal_score": 45,
                "analytics_usable": True,
                "execution_suggestion_usable": True,
                "provider_health_status": "GOOD",
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "ta_candle_state": "CANDLE_REJECTION_BEARISH",
                "ta_entry_timing_state": "CANDLE_REJECTION_BEARISH",
                "ta_candle_direction": "PUT",
                "ta_candle_range_expanded": False,
                "ta_candle_range_expansion_ratio": 0.8,
                "ta_candle_momentum_3_bps": -3,
                "ta_candle_close_location": 0.2,
                "ta_entry_timing_score": 20,
                "historical_wall_state": "AWAY_FROM_NEAREST_WALL",
                "wall_context_state": "AWAY_FROM_NEAREST_WALL",
                "support_wall_distance_pct": -0.75,
                "resistance_wall_distance_pct": 0.80,
                "max_pain_zone": "FAR_FROM_MAX_PAIN",
                "correct_60m": 0,
                "signed_return_60m_bps": -10,
                "mfe_60m_bps": 4,
                "mae_60m_bps": -15,
                "outcome_status": "COMPLETE",
            },
            {
                "signal_timestamp": "2026-05-25T10:15:00+05:30",
                "direction": "CALL",
                "runtime_composite_score": 50,
                "composite_signal_score": 60,
                "analytics_usable": True,
                "execution_suggestion_usable": True,
                "provider_health_status": "GOOD",
                "confirmation_status": "NO_DIRECTION",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "ta_candle_state": "CANDLE_REJECTION_BEARISH",
                "ta_entry_timing_state": "CANDLE_REJECTION_BEARISH",
                "ta_candle_direction": "PUT",
                "ta_candle_range_expanded": False,
                "ta_candle_range_expansion_ratio": 0.9,
                "ta_candle_momentum_3_bps": -2,
                "ta_candle_close_location": 0.2,
                "ta_entry_timing_score": 18,
                "historical_wall_state": "NEAR_RESISTANCE_WALL",
                "wall_context_state": "NEAR_RESISTANCE_WALL",
                "support_wall_distance_pct": -0.55,
                "resistance_wall_distance_pct": 0.15,
                "max_pain_zone": "NEAR_MAX_PAIN",
                "correct_60m": 0,
                "signed_return_60m_bps": -8,
                "mfe_60m_bps": 3,
                "mae_60m_bps": -12,
                "outcome_status": "COMPLETE",
            },
        ]
    )


def test_prepare_runtime_score_supplement_replay_frame_preserves_live_features():
    prepared = prepare_runtime_score_supplement_replay_frame(_replay_rows(), report_date="2026-05-25")

    assert len(prepared) == 4
    assert prepared.loc[0, "provider_execution_context"] == "ANALYTICS_ONLY_EXECUTION_BLOCKED"
    assert prepared.loc[0, "ta_candle_range_expansion_ratio"] == 1.4
    assert prepared.loc[0, "nearest_wall_bucket"] == "AWAY_FROM_WALL"


def test_build_runtime_score_supplement_replay_report_compares_promotions():
    report = build_runtime_score_supplement_replay_report(
        _replay_rows(),
        report_date="2026-05-25",
        min_promoted_labels=1,
    )

    assert report["coverage"]["baseline_selected_rows"] == 1
    candidates = {row["candidate"]: row for row in report["candidate_replay"]}

    candle = candidates["candle_range_plus_8"]
    assert candle["promoted_rows"] == 2
    assert candle["helpful_promoted_rows"] == 2
    assert candle["recovered_research_blindspot_rows"] == 2
    assert candle["assessment"] == "SUPPORTIVE_REPLAY"

    guarded = candidates["guarded_candle_wall_plus_10"]
    assert guarded["promoted_rows"] == 1
    assert guarded["helpful_promoted_rows"] == 1
    assert guarded["recovered_research_blindspot_rows"] == 1

    assert report["diagnostic_read"]["supportive_candidate_count"] >= 1

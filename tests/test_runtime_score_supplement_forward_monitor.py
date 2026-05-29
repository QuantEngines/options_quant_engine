from __future__ import annotations

import pandas as pd

from research.signal_evaluation.runtime_score_supplement_forward_monitor import (
    build_runtime_score_supplement_forward_monitor_report,
    prepare_runtime_score_supplement_forward_monitor_frame,
)


def _monitor_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-05-25T10:00:00+05:30",
                "direction": "PUT",
                "runtime_composite_score": 55,
                "analytics_usable": True,
                "provider_health_status": "GOOD",
                "provider_execution_context": "ANALYTICS_AND_EXECUTION_USABLE",
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "ta_candle_state": "CANDLE_CONFIRMED_PUT",
                "ta_entry_timing_state": "CANDLE_CONFIRMED_PUT",
                "ta_candle_direction": "PUT",
                "ta_candle_momentum_3_bps": -5,
                "ta_candle_close_location": 0.2,
                "ta_entry_timing_score": 80,
                "historical_wall_state": "NEAR_SUPPORT_WALL",
                "wall_context_state": "NEAR_SUPPORT_WALL",
                "support_wall_distance_pct": -0.15,
                "resistance_wall_distance_pct": 0.70,
                "correct_60m": 1,
                "signed_return_60m_bps": 18,
                "mfe_60m_bps": 25,
                "mae_60m_bps": -5,
                "outcome_status": "COMPLETE",
            },
            {
                "signal_timestamp": "2026-05-26T10:00:00+05:30",
                "direction": "PUT",
                "runtime_composite_score": 58,
                "analytics_usable": True,
                "provider_health_status": "GOOD",
                "provider_execution_context": "ANALYTICS_AND_EXECUTION_USABLE",
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "NEUTRAL_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "ta_candle_state": "CANDLE_CONFIRMED_PUT",
                "ta_entry_timing_state": "CANDLE_CONFIRMED_PUT",
                "ta_candle_direction": "PUT",
                "ta_candle_momentum_3_bps": -4,
                "ta_candle_close_location": 0.25,
                "ta_entry_timing_score": 70,
                "historical_wall_state": "NEAR_SUPPORT_WALL",
                "wall_context_state": "NEAR_SUPPORT_WALL",
                "support_wall_distance_pct": -0.12,
                "resistance_wall_distance_pct": 0.80,
                "correct_60m": 0,
                "signed_return_60m_bps": -6,
                "mfe_60m_bps": 3,
                "mae_60m_bps": -9,
                "outcome_status": "COMPLETE",
            },
            {
                "signal_timestamp": "2026-05-26T10:05:00+05:30",
                "direction": "PUT",
                "runtime_composite_score": 62,
                "analytics_usable": True,
                "provider_health_status": "GOOD",
                "provider_execution_context": "ANALYTICS_AND_EXECUTION_USABLE",
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "ta_candle_state": "CANDLE_CONFIRMED_PUT",
                "ta_entry_timing_state": "CANDLE_CONFIRMED_PUT",
                "ta_candle_direction": "PUT",
                "historical_wall_state": "NEAR_SUPPORT_WALL",
                "wall_context_state": "NEAR_SUPPORT_WALL",
                "correct_60m": 1,
                "signed_return_60m_bps": 10,
                "mfe_60m_bps": 14,
                "mae_60m_bps": -4,
                "outcome_status": "COMPLETE",
            },
        ]
    )


def test_prepare_forward_monitor_does_not_require_expost_score():
    prepared = prepare_runtime_score_supplement_forward_monitor_frame(
        _monitor_rows(),
        start_date="2026-05-25",
        end_date="2026-05-26",
    )

    assert len(prepared) == 3
    assert prepared["monitor_eligible"].all()
    assert "composite_signal_score" in prepared.columns


def test_forward_monitor_tracks_promoted_rows_and_weak_slices():
    report = build_runtime_score_supplement_forward_monitor_report(
        _monitor_rows(),
        candidate_names=("candle_wall_plus_10",),
        min_labeled_rows=1,
        min_session_count=1,
        weak_slice_min_labels=1,
    )

    candidate = report["candidate_monitor"][0]
    assert candidate["candidate"] == "candle_wall_plus_10"
    assert candidate["promoted_rows"] == 2
    assert candidate["promoted_label_count"] == 2
    assert candidate["promoted_metrics"]["hit_rate_60m"] == 50.0
    assert candidate["weak_slice_count"] >= 1
    assert any(row["subgroup"].startswith("NEUTRAL_GAMMA") for row in candidate["weak_slices"])


def test_forward_monitor_can_focus_single_forward_session():
    report = build_runtime_score_supplement_forward_monitor_report(
        _monitor_rows(),
        report_date="2026-05-25",
        candidate_names=("candle_wall_plus_10",),
        min_labeled_rows=1,
        min_session_count=1,
        weak_slice_min_labels=1,
    )

    candidate = report["candidate_monitor"][0]
    assert candidate["promoted_rows"] == 1
    assert candidate["candidate_status"] == "FORWARD_MONITOR_SUPPORTIVE"
    assert report["monitor_status"] == "FORWARD_MONITOR_SUPPORTIVE"

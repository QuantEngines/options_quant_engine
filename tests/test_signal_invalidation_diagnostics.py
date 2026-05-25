from __future__ import annotations

import pandas as pd

from research.signal_evaluation.signal_invalidation_diagnostics import (
    build_signal_invalidation_episodes,
    build_signal_invalidation_report,
    prepare_signal_invalidation_frame,
)


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-05-25T09:30:00+05:30",
                "symbol": "NIFTY",
                "direction": "CALL",
                "runtime_composite_score": 48,
                "spot_at_signal": 10000,
                "confirmation_status": "MIXED",
                "provider_health_status": "GOOD",
                "data_quality_status": "GOOD",
                "spot_vs_flip": "ABOVE_FLIP",
                "historical_wall_state": "NO_NEAR_WALL",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "RISK_OFF",
                "signed_return_60m_bps": -10,
                "correct_60m": 0,
                "mfe_60m_bps": 4,
                "mae_60m_bps": -18,
            },
            {
                "signal_timestamp": "2026-05-25T09:35:00+05:30",
                "symbol": "NIFTY",
                "direction": "CALL",
                "runtime_composite_score": 62,
                "spot_at_signal": 10015,
                "confirmation_status": "STRONG_CONFIRMATION",
                "provider_health_status": "GOOD",
                "data_quality_status": "GOOD",
                "spot_vs_flip": "ABOVE_FLIP",
                "historical_wall_state": "NO_NEAR_WALL",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "RISK_OFF",
                "signed_return_60m_bps": 4,
                "correct_60m": 1,
                "mfe_60m_bps": 14,
                "mae_60m_bps": -6,
            },
            {
                "signal_timestamp": "2026-05-25T09:40:00+05:30",
                "symbol": "NIFTY",
                "direction": "CALL",
                "runtime_composite_score": 47,
                "spot_at_signal": 10005,
                "confirmation_status": "MIXED",
                "provider_health_status": "GOOD",
                "data_quality_status": "GOOD",
                "spot_vs_flip": "ABOVE_FLIP",
                "historical_wall_state": "NO_NEAR_WALL",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "RISK_OFF",
                "signed_return_60m_bps": -12,
                "correct_60m": 0,
                "mfe_60m_bps": 3,
                "mae_60m_bps": -20,
            },
            {
                "signal_timestamp": "2026-05-25T09:55:00+05:30",
                "symbol": "NIFTY",
                "direction": "PUT",
                "runtime_composite_score": 54,
                "spot_at_signal": 9980,
                "confirmation_status": "MIXED",
                "provider_health_status": "GOOD",
                "data_quality_status": "GOOD",
                "spot_vs_flip": "BELOW_FLIP",
                "historical_wall_state": "NEAR_SUPPORT_WALL",
                "ta_candle_rejection": True,
                "ta_candle_state": "CANDLE_REJECTION",
                "ta_entry_timing_state": "CANDLE_REJECTION",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "VOL_EXPANSION",
                "global_risk_state": "RISK_OFF",
                "signed_return_60m_bps": -8,
                "correct_60m": 0,
                "mfe_60m_bps": 2,
                "mae_60m_bps": -15,
            },
            {
                "signal_timestamp": "2026-05-25T10:10:00+05:30",
                "symbol": "NIFTY",
                "direction": "CALL",
                "runtime_composite_score": 52,
                "spot_at_signal": 10025,
                "confirmation_status": "MIXED",
                "provider_health_status": "GOOD",
                "data_quality_status": "GOOD",
                "spot_vs_flip": "ABOVE_FLIP",
                "historical_wall_state": "NO_NEAR_WALL",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "RISK_OFF",
                "signed_return_60m_bps": 10,
                "correct_60m": 1,
                "mfe_60m_bps": 16,
                "mae_60m_bps": -3,
            },
            {
                "signal_timestamp": "2026-05-25T10:15:00+05:30",
                "symbol": "NIFTY",
                "direction": "PUT",
                "runtime_composite_score": 55,
                "spot_at_signal": 10000,
                "confirmation_status": "MIXED",
                "provider_health_status": "GOOD",
                "data_quality_status": "GOOD",
                "spot_vs_flip": "BELOW_FLIP",
                "historical_wall_state": "NO_NEAR_WALL",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "RISK_OFF",
                "signed_return_60m_bps": 7,
                "correct_60m": 1,
                "mfe_60m_bps": 11,
                "mae_60m_bps": -4,
            },
        ]
    )


def test_prepare_signal_invalidation_frame_normalizes_inputs():
    prepared = prepare_signal_invalidation_frame(_rows())

    assert prepared["signal_ts"].notna().all()
    assert prepared.loc[0, "direction"] == "CALL"
    assert prepared.loc[3, "historical_wall_state"] == "NEAR_SUPPORT_WALL"
    assert prepared.loc[5, "direction_sign"] == -1.0


def test_build_signal_invalidation_episodes_detects_first_invalidation_rules():
    episodes = build_signal_invalidation_episodes(
        _rows(),
        threshold=50,
        max_episode_gap_minutes=20,
        score_decay_drop_points=10,
    )

    assert len(episodes) == 4
    first_call = episodes.loc[episodes["episode_id"].str.endswith("CALL:1")].iloc[0]
    first_put = episodes.loc[episodes["episode_id"].str.endswith("PUT:2")].iloc[0]
    second_call = episodes.loc[episodes["episode_id"].str.endswith("CALL:3")].iloc[0]

    assert first_call["first_invalidation_type"] == "INVALIDATED_SCORE_DECAY"
    assert first_call["first_invalidation_delay_minutes"] == 10.0
    assert first_call["invalidation_minus_first_return_60m_bps"] == -2.0
    assert "INVALIDATED_CONFIRMATION_LOSS" in first_call["all_invalidation_types"]
    assert first_put["first_invalidation_type"] == "INVALIDATED_LEVEL_REJECTION"
    assert second_call["first_invalidation_type"] == "INVALIDATED_DIRECTION_FLIP"
    assert second_call["invalidation_return_60m_bps"] == -7.0


def test_build_signal_invalidation_report_summarizes_helped_hurt():
    report = build_signal_invalidation_report(
        _rows(),
        threshold=50,
        max_episode_gap_minutes=20,
        score_decay_drop_points=10,
    )
    by_type = {row["first_invalidation_type"]: row for row in report["first_invalidation_type_summary"]}

    assert report["coverage"]["episode_count"] == 4
    assert report["coverage"]["invalidated_episode_count"] == 3
    assert by_type["INVALIDATED_SCORE_DECAY"]["episode_count"] == 1
    assert by_type["INVALIDATED_LEVEL_REJECTION"]["false_positive_removal_60m"] == 50.0
    assert by_type["INVALIDATED_DIRECTION_FLIP"]["true_positive_loss_60m"] == 50.0
    assert report["diagnostic_read"]["score_decay_observed"] is True
    assert report["diagnostic_read"]["candle_rejection_observed"] is True
    assert report["diagnostic_read"]["direction_flip_observed"] is True

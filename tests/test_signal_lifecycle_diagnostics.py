from __future__ import annotations

import pandas as pd

from research.signal_evaluation.signal_lifecycle_diagnostics import (
    build_signal_lifecycle_episodes,
    build_signal_lifecycle_report,
    prepare_signal_lifecycle_frame,
)


def _lifecycle_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-05-25T09:30:00+05:30",
                "symbol": "NIFTY",
                "direction": "CALL",
                "runtime_composite_score": 45,
                "trade_strength": 40,
                "spot_at_signal": 10000,
                "confirmation_status": "NO_DIRECTION",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "RISK_OFF",
                "signed_return_60m_bps": -10,
                "correct_60m": 0,
                "mfe_60m_bps": 3,
                "mae_60m_bps": -18,
                "option_premium_return_60m_bps": -200,
            },
            {
                "signal_timestamp": "2026-05-25T09:35:00+05:30",
                "symbol": "NIFTY",
                "direction": "CALL",
                "runtime_composite_score": 55,
                "trade_strength": 52,
                "spot_at_signal": 10010,
                "confirmation_status": "MIXED",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "RISK_OFF",
                "signed_return_60m_bps": -8,
                "correct_60m": 0,
                "mfe_60m_bps": 5,
                "mae_60m_bps": -14,
                "option_premium_return_60m_bps": -100,
            },
            {
                "signal_timestamp": "2026-05-25T09:40:00+05:30",
                "symbol": "NIFTY",
                "direction": "CALL",
                "runtime_composite_score": 62,
                "trade_strength": 60,
                "spot_at_signal": 10020,
                "confirmation_status": "STRONG_CONFIRMATION",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "RISK_OFF",
                "signed_return_60m_bps": 12,
                "correct_60m": 1,
                "mfe_60m_bps": 20,
                "mae_60m_bps": -6,
                "option_premium_return_60m_bps": 300,
                "ta_entry_timing_state": "CANDLE_CONFIRMED_CALL",
                "ta_candle_state": "CANDLE_CONFIRMED_CALL",
                "ta_candle_direction": "CALL",
            },
            {
                "signal_timestamp": "2026-05-25T10:00:00+05:30",
                "symbol": "NIFTY",
                "direction": "PUT",
                "runtime_composite_score": 52,
                "trade_strength": 50,
                "spot_at_signal": 10005,
                "confirmation_status": "MIXED",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "VOL_EXPANSION",
                "global_risk_state": "RISK_OFF",
                "signed_return_60m_bps": -6,
                "correct_60m": 0,
                "mfe_60m_bps": 2,
                "mae_60m_bps": -11,
                "option_premium_return_60m_bps": -150,
            },
        ]
    )


def test_prepare_signal_lifecycle_frame_normalizes_runtime_fields():
    prepared = prepare_signal_lifecycle_frame(_lifecycle_rows())

    assert prepared["signal_ts"].notna().all()
    assert prepared.loc[0, "direction"] == "CALL"
    assert prepared.loc[3, "direction_sign"] == -1.0
    assert str(prepared.loc[1, "score_bucket"]) == "55-59"


def test_build_signal_lifecycle_episodes_tracks_milestones_and_invalidation():
    episodes = build_signal_lifecycle_episodes(
        _lifecycle_rows(),
        threshold=50,
        max_episode_gap_minutes=25,
        mature_snapshot_count=2,
    )

    assert len(episodes) == 2
    call = episodes.loc[episodes["direction"] == "CALL"].iloc[0]
    put = episodes.loc[episodes["direction"] == "PUT"].iloc[0]

    assert call["lifecycle_state"] == "INVALIDATED"
    assert call["highest_lifecycle_stage"] == "MATURE"
    assert call["first_threshold_delay_minutes"] == 5.0
    assert call["first_confirmation_delay_minutes"] == 10.0
    assert call["first_candle_confirmation_delay_minutes"] == 10.0
    assert call["mature_delay_minutes"] == 10.0
    assert call["first_confirmation_minus_first_return_60m_bps"] == 22.0
    assert call["invalidation_reason"] == "DIRECTION_FLIP_TO_PUT"
    assert put["lifecycle_state"] == "CONFIRMED"


def test_build_signal_lifecycle_report_compares_first_seen_with_milestones():
    report = build_signal_lifecycle_report(
        _lifecycle_rows(),
        threshold=50,
        max_episode_gap_minutes=25,
        mature_snapshot_count=2,
    )
    milestone_rows = {row["milestone"]: row for row in report["milestone_comparison"]}

    assert report["coverage"]["episode_count"] == 2
    assert report["coverage"]["episodes_with_confirmation"] == 1
    assert report["coverage"]["episodes_with_candle_confirmation"] == 1
    assert milestone_rows["first_seen"]["selected_episode_count"] == 2
    assert milestone_rows["first_confirmation"]["selected_episode_count"] == 1
    assert milestone_rows["first_confirmation"]["avg_return_60m_bps"] == 12.0
    assert milestone_rows["first_confirmation"]["selected_minus_first_return_60m_bps"] == 22.0
    assert milestone_rows["first_confirmation"]["false_positive_removal_60m"] == 50.0
    assert milestone_rows["first_confirmation"]["true_positive_loss_60m"] is None
    assert report["diagnostic_read"]["confirmation_improves_60m_return"] is True

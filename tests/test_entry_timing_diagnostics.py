from __future__ import annotations

import pandas as pd

from research.signal_evaluation.entry_timing_diagnostics import (
    build_entry_timing_report,
    classify_timing_quality,
    prepare_entry_timing_frame,
)


def _base_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-05-20T09:30:00+05:30",
                "direction": "CALL",
                "runtime_composite_score": 45,
                "spot_at_signal": 10000,
                "signed_return_60m_bps": 2,
                "correct_60m": 1,
                "trade_status": "WATCHLIST",
                "outcome_status": "COMPLETE",
            },
            {
                "signal_timestamp": "2026-05-20T09:45:00+05:30",
                "direction": "CALL",
                "runtime_composite_score": 56,
                "spot_at_signal": 10020,
                "signed_return_60m_bps": -8,
                "correct_60m": 0,
                "trade_status": "WATCHLIST",
                "outcome_status": "COMPLETE",
            },
            {
                "signal_timestamp": "2026-05-20T10:00:00+05:30",
                "direction": "PUT",
                "runtime_composite_score": 52,
                "spot_at_signal": 9990,
                "signed_return_60m_bps": 9,
                "correct_60m": 1,
                "trade_status": "WATCHLIST",
                "outcome_status": "COMPLETE",
            },
        ]
    )


def test_prepare_entry_timing_frame_computes_directional_prior_moves():
    prepared = prepare_entry_timing_frame(_base_rows())

    call_row = prepared.loc[prepared["runtime_composite_score"] == 56].iloc[0]
    put_row = prepared.loc[prepared["direction"] == "PUT"].iloc[0]

    assert round(float(call_row["prior_15m_signed_bps"]), 2) == 20.0
    assert round(float(put_row["prior_15m_signed_bps"]), 2) == 29.94
    assert call_row["timing_class"] == "LATE_CHASE"
    assert put_row["timing_class"] == "CONFIRMING"


def test_classify_timing_quality_covers_core_buckets():
    assert classify_timing_quality({"prior_favorable_max_bps": 12, "signed_return_60m_bps": 8}) == "CONFIRMING"
    assert classify_timing_quality({"prior_favorable_max_bps": 12, "signed_return_60m_bps": -6}) == "LATE_CHASE"
    assert classify_timing_quality({"prior_favorable_max_bps": 3, "signed_return_60m_bps": 8}) == "EARLY"
    assert classify_timing_quality({"prior_favorable_max_bps": 3, "signed_return_60m_bps": -8}) == "FALSE_START"
    assert classify_timing_quality({"prior_favorable_max_bps": 3, "signed_return_60m_bps": None}) == "PENDING_OUTCOME"


def test_build_entry_timing_report_uses_runtime_score_and_reports_diagnostic_read():
    report = build_entry_timing_report(_base_rows())

    assert report["methodology"]["live_score_field"] == "runtime_composite_score"
    assert report["methodology"]["excluded_hindsight_score_field"] == "composite_signal_score"
    assert report["coverage"]["runtime_rows"] == 3
    assert report["coverage"]["mature_60m_rows"] == 3
    assert any(row["score_bucket"] == "55-59" for row in report["score_bucket_summary_mature_60m"])
    assert any(row["timing_class"] == "LATE_CHASE" for row in report["timing_class_summary"])
    assert "late_chase_thesis_supported" in report["diagnostic_read"]


def test_build_entry_timing_report_filters_session_date():
    frame = pd.concat(
        [
            _base_rows(),
            pd.DataFrame(
                [
                    {
                        "signal_timestamp": "2026-05-21T09:30:00+05:30",
                        "direction": "CALL",
                        "runtime_composite_score": 65,
                        "spot_at_signal": 10100,
                        "signed_return_60m_bps": 15,
                        "correct_60m": 1,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    report = build_entry_timing_report(frame, report_date="2026-05-21")

    assert report["methodology"]["report_date"] == "2026-05-21"
    assert report["coverage"]["input_rows"] == 4
    assert report["coverage"]["rows_after_date_filter"] == 1
    assert report["coverage"]["runtime_rows"] == 1


def test_build_entry_timing_report_compares_entry_strategies_and_candle_states():
    frame = pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-05-25T09:30:00+05:30",
                "symbol": "NIFTY",
                "direction": "CALL",
                "runtime_composite_score": 45,
                "spot_at_signal": 10000,
                "confirmation_status": "NO_DIRECTION",
                "signed_return_60m_bps": 1,
                "correct_60m": 1,
            },
            {
                "signal_timestamp": "2026-05-25T09:35:00+05:30",
                "symbol": "NIFTY",
                "direction": "CALL",
                "runtime_composite_score": 52,
                "spot_at_signal": 10020,
                "confirmation_status": "MIXED",
                "signed_return_60m_bps": -10,
                "correct_60m": 0,
                "mfe_60m_bps": 4,
                "mae_60m_bps": -18,
                "option_premium_return_60m_bps": -200,
                "option_premium_pnl_per_lot_60m": -1000,
                "ta_entry_timing_state": "CANDLE_FORMING",
                "ta_candle_state": "CANDLE_FORMING",
            },
            {
                "signal_timestamp": "2026-05-25T09:40:00+05:30",
                "symbol": "NIFTY",
                "direction": "CALL",
                "runtime_composite_score": 58,
                "spot_at_signal": 10010,
                "confirmation_status": "STRONG_CONFIRMATION",
                "signed_return_60m_bps": 12,
                "correct_60m": 1,
                "mfe_60m_bps": 20,
                "mae_60m_bps": -6,
                "option_premium_return_60m_bps": 350,
                "option_premium_pnl_per_lot_60m": 1750,
                "ta_entry_timing_state": "CANDLE_CONFIRMED_CALL",
                "ta_candle_state": "CANDLE_CONFIRMED_CALL",
                "ta_candle_direction": "CALL",
            },
            {
                "signal_timestamp": "2026-05-25T09:30:00+05:30",
                "symbol": "NIFTY",
                "direction": "PUT",
                "runtime_composite_score": 45,
                "spot_at_signal": 10030,
                "confirmation_status": "NO_DIRECTION",
                "signed_return_60m_bps": 1,
                "correct_60m": 1,
            },
            {
                "signal_timestamp": "2026-05-25T09:35:00+05:30",
                "symbol": "NIFTY",
                "direction": "PUT",
                "runtime_composite_score": 53,
                "spot_at_signal": 10020,
                "confirmation_status": "MIXED",
                "signed_return_60m_bps": -8,
                "correct_60m": 0,
                "mfe_60m_bps": 3,
                "mae_60m_bps": -12,
                "option_premium_return_60m_bps": -120,
                "option_premium_pnl_per_lot_60m": -600,
                "ta_entry_timing_state": "CANDLE_REJECTION",
                "ta_candle_state": "CANDLE_REJECTION",
                "ta_candle_rejection": True,
            },
        ]
    )

    report = build_entry_timing_report(
        frame,
        score_thresholds=(50,),
        pullback_bps=5,
        confirmation_window_minutes=10,
        pullback_window_minutes=10,
        candle_confirmation_window_minutes=10,
    )
    strategy_rows = {
        row["strategy"]: row
        for row in report["entry_strategy_summary"]
        if row["threshold"] == 50
    }

    assert strategy_rows["immediate"]["entry_count"] == 2
    assert strategy_rows["second_confirmation"]["entry_count"] == 1
    assert strategy_rows["pullback_retest"]["entry_count"] == 1
    assert strategy_rows["candle_confirmed"]["entry_count"] == 1
    assert strategy_rows["second_confirmation"]["avg_return_60m_bps"] == 12.0
    assert strategy_rows["second_confirmation"]["selected_minus_immediate_return_60m_bps"] == 22.0
    assert strategy_rows["second_confirmation"]["false_positive_removal_60m"] == 50.0
    assert strategy_rows["second_confirmation"]["true_positive_loss_60m"] is None
    assert strategy_rows["candle_confirmed"]["avg_option_premium_return_60m_bps"] == 350.0
    assert any(
        row["ta_entry_timing_state"] == "CANDLE_CONFIRMED_CALL"
        for row in report["candle_entry_timing_state_summary"]
    )

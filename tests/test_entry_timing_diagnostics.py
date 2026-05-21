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


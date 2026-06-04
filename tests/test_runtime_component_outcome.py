from __future__ import annotations

import pandas as pd

from research.signal_evaluation.runtime_component_outcome import build_runtime_component_outcome_report


def test_runtime_component_outcome_segments_suppressed_directional_rows():
    frame = pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-06-03T09:20:00+05:30",
                "direction": "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 42,
                "runtime_composite_base_score": 42,
                "effective_min_composite_score_threshold": 58,
                "trade_strength": 72,
                "effective_min_trade_strength_threshold": 60,
                "hybrid_move_probability": 0.52,
                "confirmation_status": "STRONG_CONFIRMATION",
                "data_quality_status": "STRONG",
                "gamma_vol_acceleration_score": 20,
                "macro_regime": "RISK_OFF",
                "global_risk_state": "RISK_OFF",
                "spot_vs_flip": "AT_FLIP",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "ta_entry_timing_state": "CANDLE_REJECTION_BEARISH",
                "correct_30m": 1,
                "correct_60m": 1,
                "correct_120m": 0,
                "signed_return_30m_bps": 4.5,
                "signed_return_60m_bps": -2.0,
                "signed_return_120m_bps": -8.0,
                "mfe_60m_bps": 6.0,
                "mae_60m_bps": -12.0,
            },
            {
                "signal_timestamp": "2026-06-03T09:35:00+05:30",
                "direction": "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 43,
                "runtime_composite_base_score": 43,
                "effective_min_composite_score_threshold": 58,
                "trade_strength": 55,
                "effective_min_trade_strength_threshold": 60,
                "hybrid_move_probability": 0.49,
                "confirmation_status": "CONFIRMED",
                "data_quality_status": "STRONG",
                "gamma_vol_acceleration_score": 30,
                "macro_regime": "RISK_OFF",
                "global_risk_state": "RISK_OFF",
                "spot_vs_flip": "AT_FLIP",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "ta_entry_timing_state": "LOW_SCORE_CONTINUATION",
                "correct_30m": 0,
                "correct_60m": 0,
                "correct_120m": 0,
                "signed_return_30m_bps": -3.0,
                "signed_return_60m_bps": -7.0,
                "signed_return_120m_bps": -10.0,
                "mfe_60m_bps": 3.0,
                "mae_60m_bps": -9.0,
            },
            {
                "signal_timestamp": "2026-06-03T09:40:00+05:30",
                "direction": "CALL",
                "trade_status": "TRADE",
                "runtime_composite_score": 70,
                "trade_strength": 80,
                "hybrid_move_probability": 0.70,
                "correct_60m": 1,
            },
            {
                "signal_timestamp": "2026-06-02T09:40:00+05:30",
                "direction": "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 10,
            },
        ]
    )

    report = build_runtime_component_outcome_report(
        frame,
        dataset_path="unit.csv",
        start_date="2026-06-03",
        end_date="2026-06-03",
        min_segment_rows=1,
    )

    assert report["suppressed_directional_rows"] == 2
    assert report["require_runtime_composite"] is True
    assert report["component_source"] == "estimated_from_dataset_fields"
    assert report["overall_metrics"]["label_count_60m"] == 2
    assert report["overall_metrics"]["hit_rate_60m"] == 0.5
    assert report["overall_metrics"]["avg_signed_return_60m_bps"] == -4.5
    segment_keys = {(row["segment"], row["value"]) for row in report["segments"]}
    assert ("primary_component_drag", "trade_strength") in segment_keys
    assert report["runtime_config_changed"] is False
    assert report["execution_behavior_changed"] is False

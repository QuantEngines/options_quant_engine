from __future__ import annotations

import pandas as pd

from research.signal_evaluation.probability_calibration_forward_monitor import (
    build_probability_calibration_forward_monitor_report,
    prepare_probability_calibration_forward_monitor_frame,
    write_probability_calibration_forward_monitor_report,
)


def _calibration_rows() -> pd.DataFrame:
    rows = []
    for idx in range(20):
        rows.append(
            {
                "signal_timestamp": f"2026-05-29T10:{idx:02d}:00+05:30",
                "direction": "PUT",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "macro_regime": "RISK_OFF",
                "trade_status": "WATCHLIST_SETUP",
                "hybrid_move_probability": 25,
                "correct_60m": 1,
                "signed_return_60m_bps": 18,
                "runtime_composite_score": 51,
                "trade_strength": 60,
            }
        )
    for idx in range(20):
        rows.append(
            {
                "signal_timestamp": f"2026-05-29T11:{idx:02d}:00+05:30",
                "direction": "CALL",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "VOL_EXPANSION",
                "macro_regime": "MACRO_NEUTRAL",
                "trade_status": "TRADE_READY",
                "hybrid_move_probability": 72,
                "correct_60m": 0,
                "signed_return_60m_bps": -12,
                "runtime_composite_score": 70,
                "trade_strength": 75,
            }
        )
    return pd.DataFrame(rows)


def test_prepare_probability_calibration_forward_monitor_filters_session_date():
    frame = pd.concat(
        [
            _calibration_rows(),
            pd.DataFrame(
                [
                    {
                        "signal_timestamp": "2026-05-28T10:00:00+05:30",
                        "direction": "PUT",
                        "hybrid_move_probability": 40,
                        "correct_60m": 1,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    prepared = prepare_probability_calibration_forward_monitor_frame(frame, report_date="2026-05-29")

    assert len(prepared) == 40
    assert prepared["monitor_eligible"].all()
    assert set(prepared["signal_date"]) == {"2026-05-29"}


def test_probability_calibration_forward_monitor_flags_non_monotonic_risk():
    report = build_probability_calibration_forward_monitor_report(
        _calibration_rows(),
        report_date="2026-05-29",
        min_labeled_rows=10,
        min_session_count=1,
        min_slice_labels=5,
        alert_abs_gap=0.10,
        severe_abs_gap=0.20,
    )

    assert report["monitor_status"] == "CALIBRATION_FORWARD_ALERT"
    assert report["bucket_pattern"]["non_monotonic_calibration_risk"] is True
    assert report["diagnostic_read"]["underconfidence_slice_count"] > 0
    assert report["diagnostic_read"]["overconfidence_slice_count"] > 0
    statuses = {row["calibration_status"] for row in report["probability_bucket_rows"]}
    assert "SEVERE_UNDERCONFIDENCE" in statuses
    assert "SEVERE_OVERCONFIDENCE" in statuses


def test_write_probability_calibration_forward_monitor_outputs_artifacts(tmp_path):
    dataset = tmp_path / "signals.csv"
    _calibration_rows().to_csv(dataset, index=False)

    result = write_probability_calibration_forward_monitor_report(
        dataset_path=dataset,
        output_dir=tmp_path / "reports",
        report_date="2026-05-29",
        min_labeled_rows=10,
        min_session_count=1,
        min_slice_labels=5,
    )

    assert result["report"]["report_type"] == "probability_calibration_forward_monitor"
    assert result["latest_markdown_path"].endswith("latest_probability_calibration_forward_monitor.md")
    assert pd.read_csv(result["latest_buckets_csv_path"]).shape[0] >= 2

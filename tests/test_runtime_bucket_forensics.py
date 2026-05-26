from __future__ import annotations

import pandas as pd

from research.signal_evaluation.runtime_bucket_forensics import (
    build_runtime_bucket_forensics_report,
    prepare_runtime_bucket_forensics_frame,
    write_runtime_bucket_forensics_report,
)


def _bucket_rows() -> pd.DataFrame:
    base = pd.Timestamp("2026-05-26T09:30:00+05:30")
    rows = []
    for idx in range(48):
        in_target = idx < 24
        runtime = 52 + (idx % 4) if in_target else 44 + (idx % 4)
        is_put = idx % 3 != 0
        rows.append(
            {
                "signal_timestamp": (base + pd.Timedelta(minutes=5 * idx)).isoformat(),
                "direction": "PUT" if is_put else "CALL",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": runtime,
                "composite_signal_score": 68 if in_target else 28,
                "correct_15m": 1 if in_target else 0,
                "correct_30m": 1 if in_target else 0,
                "correct_60m": 1 if in_target or idx % 5 == 0 else 0,
                "correct_120m": 1 if in_target and idx % 2 == 0 else 0,
                "correct_session_close": 0 if in_target else 1,
                "signed_return_15m_bps": 5 if in_target else -3,
                "signed_return_30m_bps": 9 if in_target else -5,
                "signed_return_60m_bps": 14 if in_target else -8,
                "signed_return_120m_bps": 4 if in_target else -2,
                "signed_return_session_close_bps": -10 if in_target else 3,
                "mfe_60m_bps": 20 if in_target else 4,
                "mae_60m_bps": -7 if in_target else -14,
                "volume_pcr_atm": 1.35 if in_target else 0.72,
                "volume_pcr": 1.2 if in_target else 0.65,
                "volume_pcr_regime": "PUT_DOMINANT" if in_target else "CALL_DOMINANT",
                "gamma_regime": "NEGATIVE_GAMMA" if in_target else "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "confirmation_status": "STRONG_CONFIRMATION" if in_target else "MIXED",
                "ta_entry_timing_state": "CANDLE_CONFIRMED_PUT" if in_target else "CANDLE_FORMING",
                "ta_candle_state": "CANDLE_CONFIRMED_PUT" if in_target else "CANDLE_FORMING",
                "wall_context_state": "NEAR_SUPPORT_WALL" if in_target else "NEAR_RESISTANCE_WALL",
                "provider_health_status": "WEAK",
                "analytics_usable": True,
                "execution_suggestion_usable": False,
                "outcome_status": "COMPLETE",
            }
        )
    return pd.DataFrame(rows)


def test_prepare_runtime_bucket_forensics_frame_assigns_target_bucket():
    prepared = prepare_runtime_bucket_forensics_frame(_bucket_rows(), report_date="2026-05-26")

    target = prepared.loc[prepared["runtime_10pt_bucket"].astype(str).eq("50-60")]

    assert len(prepared) == 48
    assert len(target) == 24
    assert target["runtime_composite_score"].between(50, 60).all()


def test_build_runtime_bucket_forensics_report_summarizes_target_edge():
    report = build_runtime_bucket_forensics_report(
        _bucket_rows(),
        report_date="2026-05-26",
        target_bucket="50-60",
        min_slice_rows=3,
        min_intersection_rows=3,
    )

    read = report["diagnostic_read"]
    assert read["primary_read"] == "TARGET_BUCKET_TACTICAL_EDGE"
    assert read["target_rows"] == 24
    assert read["target_hit_rate_60m"] == 100.0
    assert read["target_best_horizon"]["horizon"] == "60m"
    assert report["target_slices"]
    assert any(row["slice_column"] == "volume_pcr_regime" for row in report["target_slices"])
    assert report["target_intersections"]


def test_write_runtime_bucket_forensics_report_writes_artifacts(tmp_path):
    dataset = tmp_path / "signals.csv"
    _bucket_rows().to_csv(dataset, index=False)

    result = write_runtime_bucket_forensics_report(
        dataset_path=dataset,
        output_dir=tmp_path / "reports",
        report_date="2026-05-26",
        target_bucket="50-60",
    )

    for key in (
        "latest_json_path",
        "latest_markdown_path",
        "latest_bucket_csv_path",
        "latest_slice_csv_path",
        "latest_intersection_csv_path",
        "manifest_path",
    ):
        assert result[key]
        assert pd.io.common.file_exists(result[key])

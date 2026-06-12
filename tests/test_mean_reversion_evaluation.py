from __future__ import annotations

from pathlib import Path

import pandas as pd

from research.signal_evaluation.mean_reversion_evaluation import (
    build_mean_reversion_evaluation_report,
    prepare_mean_reversion_frame,
    write_mean_reversion_evaluation_report,
)


def _rows() -> pd.DataFrame:
    rows = []
    for idx in range(80):
        is_mean_reversion = idx < 40
        rows.append(
            {
                "signal_timestamp": f"2026-06-12T09:{idx % 60:02d}:00+05:30",
                "symbol": "NIFTY",
                "direction": "PUT" if idx % 2 else "CALL",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 58 if is_mean_reversion else 48,
                "trade_strength": 66 if is_mean_reversion else 42,
                "composite_signal_score": 72 if is_mean_reversion else 48,
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "global_risk_state": "GLOBAL_NEUTRAL",
                "provider_quality_mode": "ANALYTICS_AND_EXECUTION_USABLE",
                "option_source": "ZERODHA",
                "mean_reversion_signal": "MEAN_REVERSION" if is_mean_reversion else "TREND_CONTINUATION",
                "mean_reversion_zscore": 1.8 if is_mean_reversion else 0.4,
                "mean_reversion_strength": 35.0 if is_mean_reversion else 5.0,
                "mean_reversion_distance_pct": 1.2 if is_mean_reversion else 0.2,
                "mean_reversion_reason": "spot_stretched_vs_recent_history",
                "signed_return_5m_bps": 3 if is_mean_reversion else -1,
                "signed_return_15m_bps": 8 if is_mean_reversion else -2,
                "signed_return_30m_bps": 10 if is_mean_reversion else -4,
                "signed_return_60m_bps": 14 if is_mean_reversion else -6,
                "signed_return_120m_bps": 12 if is_mean_reversion else -8,
                "correct_5m": 1 if is_mean_reversion else 0,
                "correct_15m": 1 if is_mean_reversion else 0,
                "correct_30m": 1 if is_mean_reversion else 0,
                "correct_60m": 1 if is_mean_reversion else 0,
                "correct_120m": 1 if is_mean_reversion else 0,
                "mfe_60m_bps": 20 if is_mean_reversion else 4,
                "mae_60m_bps": -6 if is_mean_reversion else -14,
                "mfe_120m_bps": 22 if is_mean_reversion else 5,
                "mae_120m_bps": -8 if is_mean_reversion else -18,
            }
        )
    return pd.DataFrame(rows)


def test_prepare_mean_reversion_frame_adds_buckets_and_filters_by_date():
    prepared = prepare_mean_reversion_frame(_rows(), report_date="2026-06-12")

    assert len(prepared) == 80
    assert prepared["has_mean_reversion_features"].all()
    assert set(prepared["mean_reversion_signal"]) == {"MEAN_REVERSION", "TREND_CONTINUATION"}
    assert "25-50" in set(prepared["mean_reversion_strength_bucket"].dropna())
    assert "1.5-2.0" in set(prepared["mean_reversion_abs_zscore_bucket"].dropna())


def test_build_mean_reversion_report_detects_helpful_mean_reversion_slice():
    report = build_mean_reversion_evaluation_report(_rows(), report_date="2026-06-12")

    read = report["diagnostic_read"]
    assert report["report_type"] == "mean_reversion_evaluation"
    assert report["coverage"]["prepared_rows"] == 80
    assert read["primary_read"] == "MEAN_REVERSION_OUTPERFORMS_TREND_CONTINUATION_60M"
    assert "MEAN_REVERSION_HIT_RATE_ADVANTAGE_60M" in read["observations"]
    assert any(row["mean_reversion_signal"] == "MEAN_REVERSION" for row in report["signal_summary"])


def test_write_mean_reversion_report_creates_latest_artifacts(tmp_path: Path):
    dataset_path = tmp_path / "signals.csv"
    _rows().to_csv(dataset_path, index=False)

    result = write_mean_reversion_evaluation_report(
        dataset_path=dataset_path,
        output_dir=tmp_path / "reports",
        report_date="2026-06-12",
    )

    assert Path(result["latest_markdown_path"]).exists()
    assert Path(result["latest_json_path"]).exists()
    assert Path(result["latest_signal_csv_path"]).exists()
    assert Path(result["manifest_path"]).exists()

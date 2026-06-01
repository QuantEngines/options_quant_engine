from __future__ import annotations

import pandas as pd

from research.signal_evaluation.decision_quality_convergence import (
    build_decision_quality_convergence_report,
    prepare_decision_quality_convergence_frame,
    write_decision_quality_convergence_report,
)


def _rows() -> pd.DataFrame:
    base = pd.Timestamp("2026-06-01T09:20:00+05:30")
    rows = []
    for idx in range(48):
        strong = idx % 4 in {0, 1}
        runtime_fail = idx % 6 in {0, 1}
        trade_strength = 72 if strong else 46
        runtime_score = 51 if runtime_fail else (66 if strong else 42)
        hit = 1 if strong else 0
        ret = 18.0 if strong else -7.0
        rows.append(
            {
                "signal_timestamp": (base + pd.Timedelta(minutes=5 * idx)).isoformat(),
                "direction": "PUT" if idx % 3 else "CALL",
                "trade_status": "WATCHLIST_SETUP",
                "trade_strength": trade_strength,
                "runtime_composite_score": runtime_score,
                "effective_min_trade_strength_threshold": 60,
                "effective_min_composite_score_threshold": 55,
                "hybrid_move_probability": 0.62 if strong else 0.38,
                "option_efficiency_score": 74 if strong else 41,
                "ta_entry_timing_score": 70 if strong else 20,
                "provider_health_status": "GOOD",
                "provider_quality_blocks_direction": False,
                "provider_quality_blocks_execution": runtime_fail,
                "data_quality_status": "STRONG",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "macro_regime": "MACRO_NEUTRAL",
                "global_risk_state": "GLOBAL_NEUTRAL",
                "spot_vs_flip": "ABOVE_FLIP" if strong else "AT_FLIP",
                "confirmation_status": "STRONG_CONFIRMATION" if strong else "NO_DIRECTION",
                "composite_signal_score": 88 if strong else 35,
                "correct_5m": hit,
                "correct_15m": hit,
                "correct_30m": hit,
                "correct_60m": hit,
                "correct_120m": hit,
                "correct_session_close": hit,
                "signed_return_5m_bps": ret / 3,
                "signed_return_15m_bps": ret / 2,
                "signed_return_30m_bps": ret,
                "signed_return_60m_bps": ret,
                "signed_return_120m_bps": ret * 1.5,
                "signed_return_session_close_bps": ret * 2,
                "mfe_60m_bps": 22 if strong else 8,
                "mae_60m_bps": -5 if strong else -14,
            }
        )
    return pd.DataFrame(rows)


def test_prepare_decision_quality_convergence_frame_builds_live_safe_candidates():
    prepared = prepare_decision_quality_convergence_frame(_rows(), report_date="2026-06-01")

    assert not prepared.empty
    assert prepared["candidate_decision_quality_blend_v0"].notna().all()
    assert prepared["candidate_decision_quality_guarded_v0"].notna().all()
    assert "TRADE_PASS_RUNTIME_FAIL" in set(prepared["effective_gate_state"])
    assert prepared["probability_score_0_100"].max() > 1.5


def test_build_decision_quality_convergence_report_contains_core_diagnostics():
    report = build_decision_quality_convergence_report(_rows(), report_date="2026-06-01")

    assert report["report_type"] == "decision_quality_convergence"
    assert report["coverage"]["prepared_directional_rows"] == 48
    assert report["metric_alignment"]
    assert report["metric_bucket_summary"]
    assert report["effective_gate_state_summary"]
    assert report["trade_strength_runtime_grid"]
    assert report["diagnostic_read"]["primary_read"]


def test_write_decision_quality_convergence_report_writes_artifacts(tmp_path):
    dataset = tmp_path / "signals.csv"
    _rows().to_csv(dataset, index=False)

    result = write_decision_quality_convergence_report(
        dataset_path=dataset,
        output_dir=tmp_path / "reports",
        report_date="2026-06-01",
    )

    for key in (
        "latest_json_path",
        "latest_markdown_path",
        "latest_metric_csv_path",
        "latest_bucket_csv_path",
        "latest_gate_csv_path",
        "latest_grid_csv_path",
        "latest_residual_csv_path",
        "manifest_path",
    ):
        assert result[key]
        assert pd.io.common.file_exists(result[key])

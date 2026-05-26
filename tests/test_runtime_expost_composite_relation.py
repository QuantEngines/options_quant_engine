from __future__ import annotations

import pandas as pd

from research.signal_evaluation.runtime_expost_composite_relation import (
    build_runtime_expost_composite_relation_report,
    prepare_runtime_expost_composite_relation_frame,
    write_runtime_expost_composite_relation_report,
)


def _relation_rows() -> pd.DataFrame:
    rows = []
    base = pd.Timestamp("2026-05-19T09:30:00+05:30")
    for idx in range(24):
        context_good = idx % 3 == 0 or idx in {5, 11, 17}
        runtime = 35 + (idx % 8) * 5
        expost = 86 if context_good and runtime < 60 else 44 + (idx % 4) * 5
        rows.append(
            {
                "signal_timestamp": (base + pd.Timedelta(minutes=5 * idx)).isoformat(),
                "direction": "CALL" if idx % 2 == 0 else "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": runtime,
                "composite_signal_score": expost,
                "trade_strength": runtime + 4,
                "move_probability": 0.62 if context_good else 0.42,
                "premium_efficiency_score": 88 if context_good else 35,
                "volume_pcr": 1.45 if context_good else 0.72,
                "india_vix_level": 18.5 if context_good else 24.0,
                "confirmation_status": "STRONG_CONFIRMATION" if context_good else "MIXED",
                "gamma_regime": "POSITIVE_GAMMA" if idx % 2 == 0 else "NEGATIVE_GAMMA",
                "volatility_regime": "VOL_EXPANSION" if context_good else "NORMAL_VOL",
                "global_risk_state": "GLOBAL_NEUTRAL",
                "macro_regime": "MACRO_NEUTRAL",
                "spot_vs_flip": "ABOVE_FLIP" if context_good else "AT_FLIP",
                "ta_candle_state": "CANDLE_CONFIRMED_CALL" if context_good else "CANDLE_FORMING",
                "ta_entry_timing_state": "CANDLE_CONFIRMED_CALL" if context_good else "CANDLE_FORMING",
                "ta_entry_timing_score": 82 if context_good else 12,
                "analytics_usable": True,
                "execution_suggestion_usable": True,
                "provider_health_status": "GOOD",
                "correct_60m": 1 if context_good else 0,
                "signed_return_60m_bps": 18 if context_good else -6,
                "outcome_status": "COMPLETE",
            }
        )
    return pd.DataFrame(rows)


def test_prepare_runtime_expost_relation_frame_marks_blindspots():
    prepared = prepare_runtime_expost_composite_relation_frame(_relation_rows())

    blindspots = prepared.loc[prepared["runtime_blindspot"]]

    assert not blindspots.empty
    assert (blindspots["runtime_composite_score"] < 60).all()
    assert (blindspots["composite_signal_score"] >= 80).all()


def test_build_runtime_expost_relation_report_compares_runtime_and_context_models():
    report = build_runtime_expost_composite_relation_report(_relation_rows())

    assert report["coverage"]["comparable_rows"] == 24
    assert report["coverage"]["blindspot_rows"] > 0
    assert report["diagnostic_read"]["primary_read"] in {
        "CONTEXT_CONDITIONED_RELATIONSHIP",
        "RUNTIME_SCORE_HAS_DIRECT_SIGNAL",
        "WEAK_DIRECT_RELATIONSHIP",
    }
    assert report["runtime_bucket_summary"]
    assert any(row.get("model") == "tree_depth3_runtime_only" for row in report["model_comparison"])
    assert any(row.get("model") == "random_forest_live_context" for row in report["model_comparison"])
    assert report["feature_importance"]
    assert report["condition_slices"]


def test_write_runtime_expost_relation_report_writes_latest_artifacts(tmp_path):
    dataset = tmp_path / "signals.csv"
    _relation_rows().to_csv(dataset, index=False)

    result = write_runtime_expost_composite_relation_report(dataset_path=dataset, output_dir=tmp_path / "reports")

    for key in (
        "latest_json_path",
        "latest_markdown_path",
        "latest_svg_path",
        "latest_model_csv_path",
        "latest_feature_csv_path",
        "latest_slices_csv_path",
        "manifest_path",
    ):
        assert result[key]
        assert pd.io.common.file_exists(result[key])

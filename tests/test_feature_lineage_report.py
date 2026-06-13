from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research.signal_evaluation.feature_lineage_report import (
    build_feature_lineage_report,
    prepare_feature_lineage_frame,
    write_feature_lineage_report,
)


def _runtime_components(trade_strength: float, probability: float, confirmation: float = 100.0) -> str:
    payload = {
        "pre_adjust_score": trade_strength,
        "final_score": trade_strength,
        "components": {
            "trade_strength": {
                "score": trade_strength,
                "weight": 0.55,
                "weighted_contribution": trade_strength * 0.55,
                "weighted_deficit_to_100": (100.0 - trade_strength) * 0.55,
            },
            "move_probability": {
                "score": probability,
                "weight": 0.15,
                "weighted_contribution": probability * 0.15,
                "weighted_deficit_to_100": (100.0 - probability) * 0.15,
            },
            "confirmation": {
                "score": confirmation,
                "weight": 0.15,
                "weighted_contribution": confirmation * 0.15,
                "weighted_deficit_to_100": (100.0 - confirmation) * 0.15,
            },
            "data_quality": {
                "score": 100.0,
                "weight": 0.10,
                "weighted_contribution": 10.0,
                "weighted_deficit_to_100": 0.0,
            },
            "gamma_stability": {
                "score": 60.0,
                "weight": 0.05,
                "weighted_contribution": 3.0,
                "weighted_deficit_to_100": 2.0,
            },
        },
    }
    return json.dumps(payload)


def _rows() -> pd.DataFrame:
    base = pd.Timestamp("2026-06-12T09:20:00+05:30")
    rows = []
    for idx in range(60):
        strong = idx % 3 != 0
        trade_strength = 76.0 if strong else 38.0
        runtime = 63.0 if strong else 34.0
        probability = 67.0 if strong else 35.0
        rows.append(
            {
                "signal_timestamp": (base + pd.Timedelta(minutes=idx)).isoformat(),
                "direction": "PUT" if idx % 2 else "CALL",
                "trade_status": "WATCHLIST_SETUP",
                "trade_strength": trade_strength,
                "runtime_composite_base_score": runtime,
                "runtime_composite_score": runtime,
                "runtime_composite_components": _runtime_components(trade_strength, probability),
                "runtime_composite_observation_tier": "HIGH" if strong else "LOW",
                "effective_min_composite_score_threshold": 55,
                "decision_quality_score_v1": 72 if strong else 32,
                "decision_quality_score_v1_raw": 75 if strong else 35,
                "hybrid_move_probability": probability / 100.0,
                "move_probability": probability,
                "signal_quality": "MEDIUM" if strong else "VERY_WEAK",
                "confirmation_status": "STRONG_CONFIRMATION" if strong else "NO_DIRECTION",
                "final_flow_signal": "BEARISH_FLOW" if strong else "NEUTRAL_FLOW",
                "provider_quality_mode": "ANALYTICS_AND_EXECUTION_USABLE",
                "provider_health_status": "GOOD",
                "provider_analytics_status": "USABLE",
                "provider_execution_status": "USABLE",
                "provider_quality_blocks_direction": False,
                "provider_quality_blocks_execution": False,
                "data_quality_status": "STRONG",
                "option_source": "ZERODHA",
                "gamma_regime": "POSITIVE_GAMMA",
                "spot_vs_flip": "BELOW_FLIP" if strong else "AT_FLIP",
                "dealer_flow_state": "HEDGING_NEUTRAL",
                "option_efficiency_score": 70 if strong else 40,
                "target_reachability_score": 68 if strong else 30,
                "premium_efficiency_score": 66 if strong else 34,
                "strike_efficiency_score": 72 if strong else 45,
                "ta_entry_timing_state": "CANDLE_CONFIRMED_PUT" if strong else "CANDLE_LATE_CHASE_PUT",
                "ta_entry_timing_score": 78 if strong else 20,
                "ta_candle_state": "CANDLE_CONFIRMED_PUT" if strong else "CANDLE_FORMING",
                "price_level_confluence_state": "NEAR_CONFLUENCE" if strong else "NO_CONFLUENCE",
                "price_level_confluence_score": 74 if strong else 20,
                "price_structure_acceptance_state": "BREAKOUT_ACCEPTED" if strong else "BALANCED_ROTATION_CANDIDATE",
                "macro_regime": "RISK_OFF",
                "global_risk_state": "RISK_OFF",
                "global_risk_state_score": 18 if strong else 8,
                "volatility_regime": "NORMAL_VOL",
                "selected_option_iv": 12.4,
                "heston_surface_quality": "GOOD",
                "mean_reversion_signal": "TREND_CONTINUATION" if strong else "MEAN_REVERSION",
                "mean_reversion_strength": 8 if strong else 35,
                "correct_60m": 1 if strong else 0,
                "signed_return_60m_bps": 14.0 if strong else -8.0,
                "calibration_label_available": True,
                "calibration_label": 1 if strong else 0,
                "primary_outcome_return_bps": 14.0 if strong else -8.0,
                "label_quality_status": "QUALITY_APPROVED",
            }
        )
    return pd.DataFrame(rows)


def test_prepare_feature_lineage_frame_filters_dates_and_preserves_quality_labels():
    prepared = prepare_feature_lineage_frame(_rows(), report_date="2026-06-12")

    assert len(prepared) == 60
    assert prepared["_quality_label_approved"].all()
    assert set(prepared["direction"]) == {"CALL", "PUT"}


def test_build_feature_lineage_report_maps_features_to_factors_and_components():
    report = build_feature_lineage_report(_rows(), report_date="2026-06-12", state_min_rows=5)

    assert report["report_type"] == "feature_lineage_report"
    assert report["coverage"]["prepared_directional_rows"] == 60
    feature_ids = {row["feature_id"] for row in report["feature_lineage"]}
    assert "runtime_composite_gate" in feature_ids
    assert "technical_entry_timing" in feature_ids
    runtime_row = next(row for row in report["feature_lineage"] if row["feature_id"] == "runtime_composite_gate")
    assert runtime_row["avg_runtime_weighted_contribution"] is not None
    assert report["runtime_component_summary"]
    assert report["state_outcome_summary"]
    assert report["diagnostic_read"]["primary_read"]


def test_write_feature_lineage_report_creates_latest_artifacts(tmp_path: Path):
    dataset = tmp_path / "signals.csv"
    _rows().to_csv(dataset, index=False)

    result = write_feature_lineage_report(
        dataset_path=dataset,
        output_dir=tmp_path / "reports",
        report_date="2026-06-12",
        state_min_rows=5,
    )

    for key in (
        "latest_json_path",
        "latest_markdown_path",
        "latest_feature_csv_path",
        "latest_factor_csv_path",
        "latest_state_csv_path",
        "latest_component_csv_path",
        "manifest_path",
    ):
        assert result[key]
        assert Path(result[key]).exists()

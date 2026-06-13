from __future__ import annotations

import json

import pandas as pd

from research.signal_evaluation.daily_suppression_attribution import (
    build_daily_suppression_attribution_report,
)


def test_daily_suppression_attribution_counts_threshold_blockers():
    frame = pd.DataFrame(
        [
            {
                "signal_id": "a",
                "signal_timestamp": "2026-06-03 09:20:00+05:30",
                "direction": "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 50,
                "effective_min_composite_score_threshold": 58,
                "trade_strength": 70,
                "effective_min_trade_strength_threshold": 60,
                "hybrid_move_probability": 0.55,
                "macro_regime": "RISK_OFF",
                "global_risk_state": "RISK_OFF",
                "spot_vs_flip": "AT_FLIP",
                "provider_quality_mode": "ANALYTICS_AND_EXECUTION_USABLE",
                "provider_health_status": "GOOD",
                "market_data_trade_blocking_status": "PASS",
                "data_quality_status": "STRONG",
                "signal_quality": "MEDIUM",
                "correct_60m": 1,
                "signed_return_60m_bps": -4.5,
            },
            {
                "signal_id": "b",
                "signal_timestamp": "2026-06-03T09:35:00.123456+05:30",
                "direction": "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 61,
                "effective_min_composite_score_threshold": 58,
                "trade_strength": 55,
                "effective_min_trade_strength_threshold": 60,
                "hybrid_move_probability": 0.62,
                "macro_regime": "RISK_OFF",
                "global_risk_state": "RISK_OFF",
                "spot_vs_flip": "BELOW_FLIP",
                "provider_quality_mode": "ANALYTICS_AND_EXECUTION_USABLE",
                "provider_health_status": "GOOD",
                "market_data_trade_blocking_status": "PASS",
                "data_quality_status": "STRONG",
                "signal_quality": "WEAK",
                "correct_60m": 0,
                "signed_return_60m_bps": -12.0,
            },
            {
                "signal_id": "c",
                "signal_timestamp": "2026-06-03T09:50:00+05:30",
                "direction": "CALL",
                "trade_status": "TRADE",
                "runtime_composite_score": 70,
                "effective_min_composite_score_threshold": 58,
                "trade_strength": 75,
                "effective_min_trade_strength_threshold": 60,
                "hybrid_move_probability": 0.66,
                "correct_60m": 1,
            },
            {
                "signal_id": "old",
                "signal_timestamp": "2026-06-02T09:50:00+05:30",
                "direction": "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 10,
                "effective_min_composite_score_threshold": 58,
            },
        ]
    )

    report = build_daily_suppression_attribution_report(
        frame,
        dataset_path="unit.csv",
        report_date="2026-06-03",
        probability_floor=0.60,
    )

    assert report["directional_count"] == 3
    assert report["trade_qualified_count"] == 1
    assert report["suppressed_directional_count"] == 2
    blockers = {row["blocker"]: row["count"] for row in report["blocker_counts"]}
    assert blockers["runtime_composite_below_threshold"] == 1
    assert blockers["move_probability_below_floor"] == 1
    assert blockers["trade_strength_below_threshold"] == 1
    assert blockers["risk_off_macro"] == 2
    assert report["suppressed_outcome"]["hit_rate_60m"] == 0.5
    attribution = report["runtime_component_attribution"]
    assert attribution["method"] == "estimated_from_dataset_fields"
    component_rows = {row["component"]: row for row in attribution["component_summary"]}
    assert component_rows["move_probability"]["low_component_count"] == 1
    assert component_rows["trade_strength"]["low_component_count"] == 1
    assert attribution["primary_component_drag_counts"][0]["value"] in {
        "move_probability",
        "trade_strength",
        "gamma_stability",
        "confirmation",
        "data_quality",
    }
    lineage = report["feature_lineage_attribution"]
    assert lineage["method"] == "primary_blocker_plus_runtime_component_drag"
    assert lineage["lineage_factor_summary"]


def test_daily_suppression_attribution_maps_runtime_block_to_lineage_component():
    component_payload = {
        "pre_adjust_score": 55,
        "final_score": 48,
        "components": {
            "trade_strength": {
                "score": 88,
                "weight": 0.55,
                "weighted_contribution": 48.4,
                "weighted_deficit_to_100": 6.6,
            },
            "move_probability": {
                "score": 35,
                "weight": 0.15,
                "weighted_contribution": 5.25,
                "weighted_deficit_to_100": 9.75,
            },
            "confirmation": {
                "score": 100,
                "weight": 0.15,
                "weighted_contribution": 15.0,
                "weighted_deficit_to_100": 0.0,
            },
            "data_quality": {
                "score": 100,
                "weight": 0.10,
                "weighted_contribution": 10.0,
                "weighted_deficit_to_100": 0.0,
            },
            "gamma_stability": {
                "score": 90,
                "weight": 0.05,
                "weighted_contribution": 4.5,
                "weighted_deficit_to_100": 0.5,
            },
        },
    }
    frame = pd.DataFrame(
        [
            {
                "signal_id": "lineage-a",
                "signal_timestamp": "2026-06-12 09:20:00+05:30",
                "direction": "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 48,
                "runtime_composite_components": json.dumps(component_payload),
                "effective_min_composite_score_threshold": 58,
                "trade_strength": 88,
                "effective_min_trade_strength_threshold": 60,
                "hybrid_move_probability": 0.62,
                "macro_regime": "MACRO_NEUTRAL",
                "global_risk_state": "GLOBAL_NEUTRAL",
                "spot_vs_flip": "BELOW_FLIP",
                "provider_quality_mode": "ANALYTICS_AND_EXECUTION_USABLE",
                "provider_health_status": "GOOD",
                "market_data_trade_blocking_status": "PASS",
                "data_quality_status": "STRONG",
                "signal_quality": "MEDIUM",
                "correct_60m": 1,
                "signed_return_60m_bps": 12.0,
            }
        ]
    )

    report = build_daily_suppression_attribution_report(
        frame,
        dataset_path="unit.csv",
        report_date="2026-06-12",
        probability_floor=0.60,
    )

    lineage = report["feature_lineage_attribution"]
    blocker_rows = lineage["lineage_blocker_summary"]
    assert blocker_rows[0]["primary_blocker"] == "runtime_composite_below_threshold"
    assert blocker_rows[0]["primary_component_drag"] == "move_probability"
    assert blocker_rows[0]["lineage_factor_bucket"] == "probability_calibration"
    assert blocker_rows[0]["lineage_feature_id"] == "probability_layer"

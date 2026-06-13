from __future__ import annotations

import json

import pandas as pd

from research.signal_evaluation.runtime_gate_candidate_monitor import build_runtime_gate_candidate_monitor_report


def _component_payload(pre_adjust_score: int) -> str:
    components = {}
    for component in ("trade_strength", "move_probability", "confirmation", "data_quality", "gamma_stability"):
        components[component] = {
            "score": pre_adjust_score,
            "weight": 0.2,
            "weighted_contribution": pre_adjust_score * 0.2,
            "weighted_deficit_to_100": (100 - pre_adjust_score) * 0.2,
        }
    return json.dumps({"pre_adjust_score": pre_adjust_score, "components": components, "final_score": 56})


def test_runtime_gate_candidate_monitor_classifies_candidate_guardrail_and_holdout():
    frame = pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-06-03T09:20:00+05:30",
                "direction": "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 56,
                "runtime_composite_components": _component_payload(75),
                "effective_min_composite_score_threshold": 58,
                "trade_strength": 65,
                "effective_min_trade_strength_threshold": 60,
                "hybrid_move_probability": 0.58,
                "setup_activation_score": 74,
                "setup_maturity_score": 82,
                "macro_regime": "RISK_OFF",
                "global_risk_state": "RISK_OFF",
                "spot_vs_flip": "BELOW_FLIP",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "ta_entry_timing_state": "CANDLE_CONFIRMED_PUT",
                "correct_60m": 1,
                "signed_return_60m_bps": 8.0,
                "mfe_60m_bps": 18.0,
                "mae_60m_bps": -8.0,
            },
            {
                "signal_timestamp": "2026-06-03T09:25:00+05:30",
                "direction": "PUT",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 42,
                "runtime_composite_components": _component_payload(85),
                "effective_min_composite_score_threshold": 58,
                "trade_strength": 85,
                "effective_min_trade_strength_threshold": 60,
                "hybrid_move_probability": 0.62,
                "macro_regime": "MACRO_NEUTRAL",
                "global_risk_state": "GLOBAL_NEUTRAL",
                "spot_vs_flip": "AT_FLIP",
                "gamma_regime": "NEGATIVE_GAMMA",
                "volatility_regime": "LOW_VOL",
                "ta_entry_timing_state": "CANDLE_LATE_CHASE_PUT",
                "correct_60m": 0,
                "signed_return_60m_bps": -12.0,
                "mfe_60m_bps": 5.0,
                "mae_60m_bps": -16.0,
            },
            {
                "signal_timestamp": "2026-06-03T09:30:00+05:30",
                "direction": "CALL",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 48,
                "runtime_composite_components": _component_payload(55),
                "effective_min_composite_score_threshold": 58,
                "trade_strength": 52,
                "effective_min_trade_strength_threshold": 60,
                "hybrid_move_probability": 0.45,
                "macro_regime": "MACRO_NEUTRAL",
                "global_risk_state": "GLOBAL_NEUTRAL",
                "spot_vs_flip": "BELOW_FLIP",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "correct_60m": 1,
                "signed_return_60m_bps": 2.0,
                "mfe_60m_bps": 4.0,
                "mae_60m_bps": -3.0,
            },
        ]
    )

    report = build_runtime_gate_candidate_monitor_report(
        frame,
        dataset_path="unit.csv",
        start_date="2026-06-03",
        end_date="2026-06-03",
        min_preserve_matches=3,
        min_candidate_rows=1,
        min_segment_rows=1,
    )

    assert report["suppressed_directional_rows"] == 3
    assert report["component_source"] == "captured_json"
    assert report["promotion_ready"] is False
    assert report["runtime_config_changed"] is False
    buckets = {row["bucket"]: row for row in report["candidate_bucket_metrics"]}
    assert buckets["CANDIDATE_MONITOR"]["row_count"] == 1
    assert buckets["CANDIDATE_MONITOR"]["avg_signed_return_60m_bps"] == 8.0
    assert buckets["KEEP_BLOCKED_GUARDRAIL"]["row_count"] == 1
    assert buckets["RESEARCH_HOLDOUT"]["row_count"] == 1
    assert report["candidate_read"] == "SEGMENTED_CANDIDATE_PROMISING_RESEARCH_ONLY"
    near = {row["near_threshold_state"]: row for row in report["near_threshold_candidate_metrics"]}
    assert near["NEAR_THRESHOLD_PRESERVE_READY"]["row_count"] == 1
    assert near["NEAR_THRESHOLD_PRESERVE_READY"]["avg_runtime_gap_to_threshold"] == -2.0
    segment_keys = {(row["segment"], row["value"]) for row in report["segments"]}
    assert ("runtime_gate_candidate_bucket", "CANDIDATE_MONITOR") in segment_keys
    assert ("near_threshold_candidate_state", "NEAR_THRESHOLD_PRESERVE_READY") in segment_keys
    assert ("lineage_factor_bucket", "signal_core") in segment_keys
    lineage = report["feature_lineage_attribution"]
    assert lineage["method"] == "runtime_component_drag_to_feature_lineage"
    bucket_lineage = lineage["candidate_bucket_lineage_summary"]
    assert any(
        row["runtime_gate_candidate_bucket"] == "CANDIDATE_MONITOR"
        and row["lineage_factor_bucket"] == "signal_core"
        for row in bucket_lineage
    )


def test_runtime_gate_candidate_near_threshold_waits_for_activation_maturity_capture():
    frame = pd.DataFrame(
        [
            {
                "signal_timestamp": "2026-06-05T10:00:00+05:30",
                "direction": "CALL",
                "trade_status": "WATCHLIST",
                "runtime_composite_score": 47,
                "runtime_composite_components": _component_payload(75),
                "effective_min_composite_score_threshold": 58,
                "trade_strength": 66,
                "effective_min_trade_strength_threshold": 60,
                "hybrid_move_probability": 0.52,
                "macro_regime": "RISK_OFF",
                "global_risk_state": "RISK_OFF",
                "spot_vs_flip": "BELOW_FLIP",
                "gamma_regime": "POSITIVE_GAMMA",
                "volatility_regime": "NORMAL_VOL",
                "correct_60m": 1,
                "signed_return_60m_bps": 10.0,
            }
        ]
    )

    report = build_runtime_gate_candidate_monitor_report(
        frame,
        dataset_path="unit.csv",
        start_date="2026-06-05",
        end_date="2026-06-05",
        min_preserve_matches=3,
        min_candidate_rows=1,
        min_segment_rows=1,
    )

    near = {row["near_threshold_state"]: row for row in report["near_threshold_candidate_metrics"]}
    assert near["NEAR_THRESHOLD_PENDING_ACTIVATION_MATURITY"]["row_count"] == 1
    assert "NEAR_THRESHOLD_PRESERVE_READY" not in near

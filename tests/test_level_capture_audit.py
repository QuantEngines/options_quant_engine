from __future__ import annotations

import pandas as pd

from research.signal_evaluation.level_capture_audit import build_level_capture_audit


def test_level_capture_audit_marks_derived_only_dataset_as_forward_capture_required():
    frame = pd.DataFrame(
        [
            {
                "spot_vs_flip": "ABOVE_FLIP",
                "historical_wall_state": "NEAR_RESISTANCE_WALL",
                "historical_max_pain_state": "NEAR_MAX_PAIN",
            }
        ]
    )

    report = build_level_capture_audit(frame)

    assert report["readiness"] == "FORWARD_CAPTURE_REQUIRED_DERIVED_CONTEXT_ONLY"
    assert "support_wall" in report["missing_raw_level_columns"]
    assert report["derived_context_coverage"][0]["present"] is True


def test_level_capture_audit_marks_raw_level_dataset_as_replay_ready():
    rows = []
    for _idx in range(5):
        rows.append(
            {
                "support_wall": 21950.0,
                "support_wall_distance_pts": -50.0,
                "support_wall_distance_pct": -0.227,
                "resistance_wall": 22100.0,
                "resistance_wall_distance_pts": 100.0,
                "resistance_wall_distance_pct": 0.455,
                "gamma_flip": 21980.0,
                "gamma_flip_distance_pct": 0.091,
                "gamma_flip_drift_points": 18.0,
                "gamma_flip_drift_direction": "RISING",
                "max_pain": 22050.0,
                "max_pain_dist": 50.0,
                "max_pain_zone": "NEAR_MAX_PAIN",
                "max_pain_distance_pct": 0.227,
                "liquidity_levels_json": "[21950.0, 22100.0]",
                "gamma_clusters_json": "[21980.0]",
                "dealer_liquidity_map_json": '{"next_support": 21950.0}',
                "spot_vs_flip": "ABOVE_FLIP",
            }
        )
    frame = pd.DataFrame(rows)

    report = build_level_capture_audit(frame)

    assert report["readiness"] == "REPLAY_READY"
    assert report["missing_raw_level_columns"] == []
    assert report["low_coverage_core_columns"] == []

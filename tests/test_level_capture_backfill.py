from __future__ import annotations

import json

import pandas as pd

from research.signal_evaluation.level_capture_backfill import enrich_level_capture_fields


def test_enrich_level_capture_fields_recovers_levels_from_historical_context_json():
    context = {
        "wall_context": {
            "support_wall": 21950.0,
            "resistance_wall": 22100.0,
            "state": "NEAR_RESISTANCE_WALL",
        },
        "max_pain_context": {
            "state": "NEAR_MAX_PAIN",
            "distance_points": 50.0,
            "distance_pct": 0.2273,
        },
    }
    frame = pd.DataFrame(
        [
            {
                "spot_at_signal": 22000.0,
                "spot_vs_flip": "ABOVE_FLIP",
                "gamma_flip_distance_pct": 0.0909,
                "historical_context_json": json.dumps(context),
            }
        ]
    )

    updated, summary = enrich_level_capture_fields(frame)

    assert summary["rows_seen"] == 1
    assert summary["rows_enriched"] == 1
    row = updated.iloc[0]
    assert row["support_wall"] == 21950.0
    assert row["support_wall_distance_pts"] == -50.0
    assert row["resistance_wall"] == 22100.0
    assert row["resistance_wall_distance_pts"] == 100.0
    assert row["max_pain"] == 22050.0
    assert row["max_pain_dist"] == 50.0
    assert row["max_pain_zone"] == "NEAR_MAX_PAIN"
    assert round(float(row["gamma_flip"]), 2) == 21980.0


def test_enrich_level_capture_fields_does_not_overwrite_existing_values():
    frame = pd.DataFrame(
        [
            {
                "spot_at_signal": 22000.0,
                "support_wall": 21900.0,
                "historical_context_json": json.dumps({"wall_context": {"support_wall": 21950.0}}),
            }
        ]
    )

    updated, summary = enrich_level_capture_fields(frame)

    assert updated.iloc[0]["support_wall"] == 21900.0
    assert summary["field_updates"]["support_wall"] == 0

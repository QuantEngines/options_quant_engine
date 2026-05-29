from __future__ import annotations

import pandas as pd

from data.india_bond_yield_snapshot import build_india_bond_yield_snapshot, upsert_india_bond_yield_row


def test_india_bond_yield_uses_prior_day_when_same_day_has_no_timestamp(tmp_path):
    path = tmp_path / "india_bond_yields.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-05-28",
                "india_2y_yield": 6.15,
                "india_5y_yield": 6.42,
                "india_10y_yield": 6.78,
                "india_10y_change_bp": -3.2,
                "source": "TEST",
            },
            {
                "date": "2026-05-29",
                "india_10y_yield": 7.25,
                "source": "TEST",
            },
        ]
    ).to_csv(path, index=False)

    snapshot = build_india_bond_yield_snapshot(
        as_of="2026-05-29T12:00:00+05:30",
        path=path,
    )

    assert snapshot["bond_date"] == "2026-05-28"
    assert snapshot["yields"]["india_10y_yield"] == 6.78
    assert round(snapshot["yields"]["india_2y10y_spread_bp"], 2) == 63.0
    assert round(snapshot["yields"]["india_5y10y_spread_bp"], 2) == 36.0


def test_india_bond_yield_allows_same_day_when_source_timestamp_is_mature(tmp_path):
    path = tmp_path / "india_bond_yields.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-05-28",
                "india_10y_yield": 6.78,
                "source": "TEST",
            },
            {
                "date": "2026-05-29",
                "india_10y_yield": 6.83,
                "india_10y_change_bp": 5.0,
                "source": "TEST",
                "source_timestamp": "2026-05-29T18:30:00+05:30",
            },
        ]
    ).to_csv(path, index=False)

    before_publish = build_india_bond_yield_snapshot(
        as_of="2026-05-29T15:20:00+05:30",
        path=path,
    )
    after_publish = build_india_bond_yield_snapshot(
        as_of="2026-05-29T19:00:00+05:30",
        path=path,
    )

    assert before_publish["bond_date"] == "2026-05-28"
    assert after_publish["bond_date"] == "2026-05-29"
    assert after_publish["yields"]["india_10y_yield"] == 6.83
    assert after_publish["source_timestamp"] == "2026-05-29T18:30:00+05:30"


def test_india_bond_yield_missing_file_degrades_to_neutral(tmp_path):
    snapshot = build_india_bond_yield_snapshot(
        as_of="2026-05-29T12:00:00+05:30",
        path=tmp_path / "missing.csv",
    )

    assert snapshot["data_available"] is False
    assert snapshot["neutral_fallback"] is True
    assert snapshot["yields"]["india_10y_yield"] is None
    assert snapshot["warnings"]


def test_upsert_india_bond_yield_row_replaces_same_date_source(tmp_path):
    path = tmp_path / "india_bond_yields.csv"
    first = {
        "date": "2026-05-29",
        "india_10y_yield": 6.78,
        "india_10y_change_bp": -3.2,
        "source": "TEST",
        "source_timestamp": "2026-05-29T18:15:00+05:30",
    }
    second = {
        **first,
        "india_10y_yield": 6.81,
        "source_timestamp": "2026-05-29T18:45:00+05:30",
    }

    upsert_india_bond_yield_row(first, path=path)
    upsert_india_bond_yield_row(second, path=path)

    frame = pd.read_csv(path)
    assert len(frame) == 1
    assert frame.iloc[0]["india_10y_yield"] == 6.81
    assert frame.iloc[0]["source_timestamp"] == "2026-05-29T18:45:00+05:30"

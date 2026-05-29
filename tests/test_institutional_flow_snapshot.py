from __future__ import annotations

import pandas as pd

from data.institutional_flow_snapshot import build_institutional_flow_snapshot


def test_institutional_flow_uses_prior_day_when_same_day_has_no_timestamp(tmp_path):
    path = tmp_path / "institutional_flows.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-05-28",
                "fii_cash_net": -1200.5,
                "dii_cash_net": 980.25,
                "fii_index_futures_net": -315.0,
                "fii_index_options_net": 144.0,
                "source": "TEST",
            },
            {
                "date": "2026-05-29",
                "fii_cash_net": 5000.0,
                "dii_cash_net": -1000.0,
                "source": "TEST",
            },
        ]
    ).to_csv(path, index=False)

    snapshot = build_institutional_flow_snapshot(
        as_of="2026-05-29T12:00:00+05:30",
        path=path,
    )

    assert snapshot["flow_date"] == "2026-05-28"
    assert snapshot["flows"]["fii_cash_net"] == -1200.5
    assert snapshot["flows"]["dii_cash_net"] == 980.25


def test_institutional_flow_allows_same_day_when_source_timestamp_is_mature(tmp_path):
    path = tmp_path / "institutional_flows.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-05-28",
                "fii_cash_net": -1200.5,
                "dii_cash_net": 980.25,
                "source": "TEST",
            },
            {
                "date": "2026-05-29",
                "fii_cash_net": 150.0,
                "dii_cash_net": -75.0,
                "source": "TEST",
                "source_timestamp": "2026-05-29T18:30:00+05:30",
            },
        ]
    ).to_csv(path, index=False)

    before_publish = build_institutional_flow_snapshot(
        as_of="2026-05-29T15:20:00+05:30",
        path=path,
    )
    after_publish = build_institutional_flow_snapshot(
        as_of="2026-05-29T19:00:00+05:30",
        path=path,
    )

    assert before_publish["flow_date"] == "2026-05-28"
    assert after_publish["flow_date"] == "2026-05-29"
    assert after_publish["flows"]["fii_cash_net"] == 150.0
    assert after_publish["source_timestamp"] == "2026-05-29T18:30:00+05:30"


def test_institutional_flow_missing_file_degrades_to_neutral(tmp_path):
    snapshot = build_institutional_flow_snapshot(
        as_of="2026-05-29T12:00:00+05:30",
        path=tmp_path / "missing.csv",
    )

    assert snapshot["data_available"] is False
    assert snapshot["neutral_fallback"] is True
    assert snapshot["flows"]["fii_cash_net"] is None
    assert snapshot["warnings"]


def test_institutional_flow_blank_optional_fields_remain_none(tmp_path):
    path = tmp_path / "institutional_flows.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-05-28",
                "fii_cash_net": -1200.5,
                "dii_cash_net": 980.25,
                "fii_index_futures_net": "",
                "fii_index_options_net": "",
                "source": "TEST",
                "source_timestamp": "2026-05-28T18:30:00+05:30",
            },
        ]
    ).to_csv(path, index=False)

    snapshot = build_institutional_flow_snapshot(
        as_of="2026-05-29T12:00:00+05:30",
        path=path,
    )

    assert snapshot["flows"]["fii_index_futures_net"] is None
    assert snapshot["flows"]["fii_index_options_net"] is None

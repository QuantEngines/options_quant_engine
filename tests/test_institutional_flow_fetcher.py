from __future__ import annotations

import pandas as pd

from data.institutional_flow_fetcher import (
    fetch_institutional_flows,
    parse_cash_flow_text,
    parse_cash_flow_frames,
    upsert_institutional_flow_row,
)


def test_parse_bse_categorywise_cash_flow_frame():
    frame = pd.DataFrame(
        [
            {
                "Category": "FII/FPI",
                "Date": "29/05/2026",
                "Buy Value": "12,383.76",
                "Sale Value": "17,351.98",
                "Net Value": "-4,968.22",
            },
            {
                "Category": "DII",
                "Date": "29/05/2026",
                "Buy Value": "24,572.09",
                "Sale Value": "16,110.62",
                "Net Value": "8,461.47",
            },
        ]
    )

    row = parse_cash_flow_frames(
        [frame],
        source="BSE_COMBINED_CASH",
        source_timestamp="2026-05-29T18:30:00+05:30",
    )

    assert row["date"] == "2026-05-29"
    assert row["source"] == "BSE_COMBINED_CASH"
    assert row["unit"] == "INR_CR"
    assert row["fii_cash_net"] == -4968.22
    assert row["dii_cash_net"] == 8461.47
    assert row["fii_cash_buy"] == 12383.76
    assert row["dii_cash_sell"] == 16110.62


def test_parse_nse_camelcase_json_frame():
    frame = pd.DataFrame(
        [
            {
                "category": "FII",
                "tradeDate": "2026-05-29",
                "buyValue": 100.25,
                "sellValue": 125.50,
                "netValue": -25.25,
            },
            {
                "category": "DII",
                "tradeDate": "2026-05-29",
                "buyValue": 200.0,
                "sellValue": 150.0,
                "netValue": 50.0,
            },
        ]
    )

    row = parse_cash_flow_frames(
        [frame],
        source="NSE_FII_DII_CASH",
        source_timestamp="2026-05-29T18:30:00+05:30",
    )

    assert row["date"] == "2026-05-29"
    assert row["fii_cash_net"] == -25.25
    assert row["dii_cash_net"] == 50.0


def test_parse_exchange_rendered_text_fallback():
    text = """
    FII/FPI trading activity on BSE, NSE & MSEI in Capital Market Segment
    Category Date Buy Value Sale Value Net Value
    FII/FPI 14/11/2025 12,383.76 17,351.98 -4,968.22
    DII trading activity on BSE, NSE & MSEI in Capital Market Segment
    Category Date Buy Value Sale Value Net Value
    DII 14/11/2025 24,572.09 16,110.62 8,461.47
    """

    row = parse_cash_flow_text(
        text,
        source="BSE_COMBINED_CASH",
        source_timestamp="2025-11-14T18:30:00+05:30",
    )

    assert row["date"] == "2025-11-14"
    assert row["fii_cash_net"] == -4968.22
    assert row["dii_cash_net"] == 8461.47


def test_fetch_selects_nse_and_crosschecks_bse(monkeypatch):
    from data import institutional_flow_fetcher as fetcher

    nse_row = {
        "date": "2026-05-29",
        "fii_cash_net": -100.0,
        "dii_cash_net": 80.0,
        "source": "NSE_FII_DII_CASH",
        "source_timestamp": "2026-05-29T18:30:00+05:30",
        "unit": "INR_CR",
    }
    bse_row = {
        "date": "2026-05-29",
        "fii_cash_net": -100.5,
        "dii_cash_net": 81.0,
        "source": "BSE_COMBINED_CASH",
        "source_timestamp": "2026-05-29T18:30:00+05:30",
        "unit": "INR_CR",
    }

    monkeypatch.setattr(
        fetcher,
        "fetch_nse_institutional_flow",
        lambda **kwargs: fetcher.InstitutionalFlowFetch(source="NSE", row=nse_row),
    )
    monkeypatch.setattr(
        fetcher,
        "fetch_bse_institutional_flow",
        lambda **kwargs: fetcher.InstitutionalFlowFetch(source="BSE", row=bse_row),
    )

    result = fetch_institutional_flows(sources=("NSE", "BSE"), agreement_tolerance_cr=2.0)

    assert result["selected_source"] == "NSE"
    assert result["selected_row"]["source"] == "NSE_FII_DII_CASH"
    assert result["selected_row"]["crosscheck_status"] == "AGREE"
    assert result["selected_row"]["crosscheck_max_abs_diff"] == 1.0
    assert result["selected_row"]["bse_dii_cash_net"] == 81.0


def test_upsert_institutional_flow_row_replaces_same_date_source(tmp_path):
    path = tmp_path / "institutional_flows.csv"
    first = {
        "date": "2026-05-29",
        "fii_cash_net": -100.0,
        "dii_cash_net": 80.0,
        "source": "NSE_FII_DII_CASH",
        "source_timestamp": "2026-05-29T18:30:00+05:30",
        "unit": "INR_CR",
    }
    second = {
        **first,
        "fii_cash_net": -90.0,
        "source_timestamp": "2026-05-29T18:45:00+05:30",
    }

    upsert_institutional_flow_row(first, path=path)
    upsert_institutional_flow_row(second, path=path)

    frame = pd.read_csv(path)
    assert len(frame) == 1
    assert frame.iloc[0]["fii_cash_net"] == -90.0
    assert frame.iloc[0]["source_timestamp"] == "2026-05-29T18:45:00+05:30"

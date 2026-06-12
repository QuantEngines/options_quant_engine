from __future__ import annotations

import pandas as pd

from data.india_bond_yield_fetcher import (
    add_local_10y_change,
    fetch_india_bond_yields,
    parse_ccil_tenorwise_yields,
)


CCIL_TENOR_HTML = """
<html>
  <body>
    <table>
      <thead>
        <tr><th>Date</th><th>Tenor Bucket</th><th>Security</th><th>YTM (%)</th></tr>
      </thead>
      <tbody>
        <tr><td>10-06-2026</td><td>91D</td><td>91 DTB (10/09/2026)</td><td>5.2998</td></tr>
        <tr><td>10-06-2026</td><td>1Y-2Y</td><td>7.38% GS 2027</td><td>5.9724</td></tr>
        <tr><td>10-06-2026</td><td>4Y-5Y</td><td>6.36% GS 2031</td><td>6.5416</td></tr>
        <tr><td>10-06-2026</td><td>9Y-10Y</td><td>6.48% GS 2035</td><td>6.9134</td></tr>
        <tr><td>10-06-2026</td><td>28Y-30Y</td><td>7.24% GS 2055</td><td>7.5462</td></tr>
        <tr><td>10-06-2026</td><td>10Y</td><td>7.63% GUJARAT SGS 2037</td><td>7.63</td></tr>
      </tbody>
    </table>
  </body>
</html>
"""


def test_parse_ccil_tenorwise_yields_maps_gsec_tenors():
    row = parse_ccil_tenorwise_yields(
        CCIL_TENOR_HTML,
        source_timestamp="2026-06-10T18:30:00+05:30",
    )

    assert row["date"] == "2026-06-10"
    assert row["source"] == "CCIL_TENORWISE_INDICATIVE_YIELDS"
    assert row["india_2y_yield"] == 5.9724
    assert row["india_5y_yield"] == 6.5416
    assert row["india_10y_yield"] == 6.9134
    assert row["india_30y_yield"] == 7.5462
    assert round(row["india_2y10y_spread_bp"], 2) == 94.10
    assert round(row["india_5y10y_spread_bp"], 2) == 37.18


def test_add_local_10y_change_uses_prior_stored_row(tmp_path):
    path = tmp_path / "india_bond_yields.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-06-09",
                "india_10y_yield": 6.88,
                "source": "TEST",
                "source_timestamp": "2026-06-09T18:30:00+05:30",
            }
        ]
    ).to_csv(path, index=False)
    row = parse_ccil_tenorwise_yields(
        CCIL_TENOR_HTML,
        source_timestamp="2026-06-10T18:30:00+05:30",
    )

    enriched = add_local_10y_change(row, path=path)

    assert round(enriched["india_10y_change_bp"], 2) == 3.34
    assert enriched["india_10y_change_basis"] == "LOCAL_PRIOR_ROW"


def test_add_local_10y_change_rejects_stale_prior_row(tmp_path):
    path = tmp_path / "india_bond_yields.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-05-29",
                "india_10y_yield": 6.28,
                "source": "TEST",
                "source_timestamp": "2026-05-29T18:30:00+05:30",
            }
        ]
    ).to_csv(path, index=False)
    row = parse_ccil_tenorwise_yields(
        CCIL_TENOR_HTML,
        source_timestamp="2026-06-10T18:30:00+05:30",
    )

    enriched = add_local_10y_change(row, path=path)

    assert enriched["india_10y_change_bp"] is None
    assert enriched["india_10y_change_basis"] == "UNAVAILABLE_PRIOR_GAP_12D"


def test_fetch_india_bond_yields_returns_selected_row(tmp_path):
    class Response:
        status_code = 200
        text = CCIL_TENOR_HTML

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    path = tmp_path / "india_bond_yields.csv"
    result = fetch_india_bond_yields(
        source_timestamp="2026-06-10T18:30:00+05:30",
        previous_path=path,
        session=Session(),
    )

    assert result["selected_source"] == "CCIL"
    assert result["selected_row"]["date"] == "2026-06-10"
    assert result["selected_row"]["india_10y_yield"] == 6.9134
    assert result["results"]["CCIL"]["issues"] == []

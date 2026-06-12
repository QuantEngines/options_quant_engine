from __future__ import annotations

from pathlib import Path

from scripts.data_prep.refresh_eod_macro_context import refresh_eod_macro_context


def _flow_result(row=None):
    row = row or {
        "date": "2026-06-10",
        "fii_cash_net": -2124.98,
        "dii_cash_net": 3123.95,
        "source_timestamp": "2026-06-11T12:15:00+05:30",
        "crosscheck_status": "SINGLE_SOURCE",
    }
    return {
        "selected_source": "NSE",
        "selected_row": row,
        "results": {
            "NSE": {"row": row, "warnings": [], "issues": [], "raw_url": "https://www.nseindia.com/"}
        },
    }


def _bond_result(row=None):
    row = row or {
        "date": "2026-06-10",
        "india_2y_yield": 5.9724,
        "india_5y_yield": 6.5416,
        "india_10y_yield": 6.9134,
        "india_30y_yield": 7.5462,
        "india_10y_change_bp": None,
        "india_10y_change_basis": "UNAVAILABLE_PRIOR_GAP_12D",
        "source_timestamp": "2026-06-11T12:15:00+05:30",
    }
    return {
        "selected_source": "CCIL",
        "selected_row": row,
        "results": {
            "CCIL": {"row": row, "warnings": [], "issues": [], "raw_url": "https://www.ccilindia.com/"}
        },
    }


def test_refresh_eod_macro_context_updates_both_stores(tmp_path):
    writes = {}
    flow_path = tmp_path / "institutional_flows.csv"
    bond_path = tmp_path / "india_bond_yields.csv"

    def upsert_flow(row, *, path):
        writes["flow"] = (row, Path(path))
        return Path(path)

    def upsert_bond(row, *, path):
        writes["bond"] = (row, Path(path))
        return Path(path)

    result = refresh_eod_macro_context(
        sources=["NSE"],
        flow_output=flow_path,
        bond_output=bond_path,
        fetch_flows_func=lambda **kwargs: _flow_result(),
        fetch_bonds_func=lambda **kwargs: _bond_result(),
        upsert_flow_func=upsert_flow,
        upsert_bond_func=upsert_bond,
    )

    assert result["status"] == "OK"
    assert result["steps"]["institutional_flows"]["wrote"] == str(flow_path)
    assert result["steps"]["india_bond_yields"]["wrote"] == str(bond_path)
    assert writes["flow"][1] == flow_path
    assert writes["bond"][1] == bond_path


def test_refresh_eod_macro_context_reports_partial_failure(tmp_path):
    result = refresh_eod_macro_context(
        flow_output=tmp_path / "institutional_flows.csv",
        bond_output=tmp_path / "india_bond_yields.csv",
        fetch_flows_func=lambda **kwargs: _flow_result(),
        fetch_bonds_func=lambda **kwargs: {
            "selected_source": None,
            "selected_row": None,
            "results": {"CCIL": {"row": None, "warnings": [], "issues": ["network_failed"]}},
        },
        upsert_flow_func=lambda row, *, path: Path(path),
        upsert_bond_func=lambda row, *, path: Path(path),
    )

    assert result["status"] == "PARTIAL"
    assert result["successes"] == ["institutional_flows"]
    assert result["failures"] == ["india_bond_yields"]
    assert result["steps"]["india_bond_yields"]["providers"]["CCIL"]["issues"] == ["network_failed"]


def test_refresh_eod_macro_context_dry_run_does_not_write(tmp_path):
    writes = []

    def _should_not_write(row, *, path):
        writes.append((row, path))
        return Path(path)

    result = refresh_eod_macro_context(
        flow_output=tmp_path / "institutional_flows.csv",
        bond_output=tmp_path / "india_bond_yields.csv",
        dry_run=True,
        fetch_flows_func=lambda **kwargs: _flow_result(),
        fetch_bonds_func=lambda **kwargs: _bond_result(),
        upsert_flow_func=_should_not_write,
        upsert_bond_func=_should_not_write,
    )

    assert result["status"] == "OK"
    assert writes == []
    assert result["steps"]["institutional_flows"]["wrote"] is None
    assert result["steps"]["india_bond_yields"]["wrote"] is None

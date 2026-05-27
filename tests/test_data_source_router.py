from __future__ import annotations

import logging

import pandas as pd

import data.data_source_router as data_source_router
from analytics.greeks_engine import _bs_price_for_iv, _parse_expiry_years


class _WeakLoader:
    def __init__(self, source: str) -> None:
        self.source = source

    def fetch_option_chain(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "strikePrice": 20000,
                    "OPTION_TYP": "CE",
                    "lastPrice": 100.0,
                    "EXPIRY_DT": "2026-05-23",
                },
                {
                    "strikePrice": 20100,
                    "OPTION_TYP": "PE",
                    "lastPrice": 95.0,
                    "EXPIRY_DT": "2026-05-23",
                },
            ]
        )

    def build_option_chain(self, symbol: str) -> pd.DataFrame:
        return self.fetch_option_chain(symbol)


class _UnexpectedFallbackLoader:
    def __init__(self, calls: list[str], source: str) -> None:
        calls.append(source)

    def fetch_option_chain(self, symbol: str) -> pd.DataFrame:
        raise AssertionError("fallback loader should not be used")

    def build_option_chain(self, symbol: str) -> pd.DataFrame:
        raise AssertionError("fallback loader should not be used")


class _ZeroIvPricedLoader:
    def build_option_chain(self, symbol: str) -> pd.DataFrame:
        spot = 24000.0
        expiry = "2027-06-02"
        valuation_time = pd.Timestamp.now(tz="UTC")
        tte = _parse_expiry_years(expiry, valuation_time=valuation_time)
        rows = []
        for strike in range(22500, 25550, 50):
            for option_type in ("CE", "PE"):
                price = _bs_price_for_iv(spot, strike, tte, 0.16, option_type)
                bid = max(price - 0.05, price * 0.99, 0.01)
                ask = max(price + 0.05, bid + 0.01)
                rows.append(
                    {
                        "strikePrice": strike,
                        "OPTION_TYP": option_type,
                        "lastPrice": price,
                        "bidPrice": bid,
                        "askPrice": ask,
                        "EXPIRY_DT": expiry,
                        "impliedVolatility": 0.0,
                        "IV": 0.0,
                    }
                )
        return pd.DataFrame(rows)

    def fetch_option_chain(self, symbol: str) -> pd.DataFrame:
        return self.build_option_chain(symbol)


def test_data_source_router_keeps_selected_source_on_weak_data(monkeypatch, caplog):
    """Weak selected-source data should warn, not switch to another provider."""
    fallback_calls: list[str] = []

    def _fake_loader_factories():
        return {
            "ICICI": lambda: _WeakLoader("ICICI"),
            "NSE": lambda: _UnexpectedFallbackLoader(fallback_calls, "NSE"),
            "ZERODHA": lambda: _UnexpectedFallbackLoader(fallback_calls, "ZERODHA"),
        }

    monkeypatch.setattr(data_source_router, "_build_loader_factories", _fake_loader_factories)

    router = data_source_router.DataSourceRouter("ICICI")
    with caplog.at_level(logging.WARNING, logger=data_source_router.__name__):
        result = router.get_option_chain("NIFTY")

    assert fallback_calls == []
    assert result["source"].unique().tolist() == ["ICICI"]
    assert result["underlying_symbol"].iloc[0] == "NIFTY"
    assert router.last_validation["is_valid"] is False
    assert "Keeping the user-selected source" in caplog.text


def test_data_source_router_secondary_research_warning_is_not_user_selected(monkeypatch, caplog):
    """Secondary multi-source collectors should not claim to be the decision source."""

    def _fake_loader_factories():
        return {
            "ICICI": lambda: _WeakLoader("ICICI"),
            "NSE": lambda: _UnexpectedFallbackLoader([], "NSE"),
            "ZERODHA": lambda: _UnexpectedFallbackLoader([], "ZERODHA"),
        }

    monkeypatch.setattr(data_source_router, "_build_loader_factories", _fake_loader_factories)

    router = data_source_router.DataSourceRouter("ICICI")
    router.selection_role = "SECONDARY_RESEARCH_ONLY"
    with caplog.at_level(logging.WARNING, logger=data_source_router.__name__):
        router.get_option_chain("NIFTY")

    assert "Secondary research data source ICICI returned option-chain quality" in caplog.text
    assert "will not override the primary decision source" in caplog.text
    assert "Keeping the user-selected source" not in caplog.text


def test_data_source_router_derives_missing_iv_before_early_quality_warning(monkeypatch, caplog):
    """Router pre-validation should not treat zero provider-IV fields as weak if prices imply IV."""

    def _fake_loader_factories():
        return {
            "ICICI": lambda: _UnexpectedFallbackLoader([], "ICICI"),
            "NSE": lambda: _UnexpectedFallbackLoader([], "NSE"),
            "ZERODHA": _ZeroIvPricedLoader,
        }

    monkeypatch.setattr(data_source_router, "_build_loader_factories", _fake_loader_factories)

    router = data_source_router.DataSourceRouter("ZERODHA")
    with caplog.at_level(logging.WARNING, logger=data_source_router.__name__):
        result = router.get_option_chain("NIFTY")

    provider_health = router.last_validation["provider_health"]
    assert not result.empty
    assert router.last_validation["iv_validation_source"] == "MODEL_DERIVED_FROM_OPTION_PRICE_PRE_SPOT"
    assert router.last_validation["raw_positive_iv_rows"] == 0
    assert router.last_validation["validation_positive_iv_rows"] > 0
    assert "core_iv_weak" not in provider_health["trade_blocking_reasons"]
    assert "no_positive_iv_rows" not in router.last_validation["warnings"]
    assert "Selected data source ZERODHA returned option-chain quality WEAK" not in caplog.text

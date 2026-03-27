from __future__ import annotations

import pandas as pd
import pytest

import engine.signal_engine as signal_engine
import engine.trading_engine as trading_engine


def test_trading_engine_facade_matches_signal_engine():
    assert trading_engine.generate_trade is signal_engine.generate_trade


def test_generate_trade_passes_days_to_expiry_into_market_state(monkeypatch):
    captured = {"days_to_expiry": None}

    class _StopReview(Exception):
        pass

    def _fake_normalize_option_chain(option_chain, spot=None, valuation_time=None):
        return option_chain

    def _fake_collect_market_state(df, spot, symbol=None, prev_df=None, days_to_expiry=None):
        captured["days_to_expiry"] = days_to_expiry
        raise _StopReview()

    monkeypatch.setattr(signal_engine, "normalize_option_chain", _fake_normalize_option_chain)
    monkeypatch.setattr(signal_engine, "_collect_market_state", _fake_collect_market_state)

    option_chain = pd.DataFrame(
        {
            "strikePrice": [22500],
            "OPTION_TYP": ["CE"],
            "lastPrice": [100.0],
        }
    )

    with pytest.raises(_StopReview):
        signal_engine.generate_trade(
            symbol="NIFTY",
            spot=22500.0,
            option_chain=option_chain,
            option_chain_validation={"selected_expiry": "2026-03-28 10:00:00"},
            valuation_time="2026-03-27 10:00:00",
        )

    assert captured["days_to_expiry"] == 1.0

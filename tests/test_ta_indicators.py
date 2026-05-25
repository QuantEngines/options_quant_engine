from __future__ import annotations

import pandas as pd

from config.policy_resolver import temporary_parameter_pack
from config.analytics_feature_policy import get_technical_analysis_policy_config
from features.ta_indicators import (
    build_intraday_candle_features,
    build_ta_features,
    get_ta_features_for_trade,
)


def test_get_ta_features_for_trade_does_not_fetch_live_history_when_disallowed(monkeypatch):
    import features.ta_indicators as ta

    def _raise_if_called(*args, **kwargs):
        raise AssertionError("live history fetch should not be called")

    monkeypatch.setattr(ta, "get_recent_spot_history", _raise_if_called)

    features = get_ta_features_for_trade(
        "NIFTY",
        100.5,
        allow_live_history=False,
    )

    assert features["ta_direction"] == "NO_SIGNAL"
    assert features["ta_confidence"] == 0.0
    assert features["ta_regime"] == "point_in_time_unavailable"
    assert features["ta_warning"] == "ta_history_not_supplied_for_historical_mode"


def test_get_ta_features_for_trade_filters_supplied_history_as_of(monkeypatch):
    import features.ta_indicators as ta

    def _raise_if_called(*args, **kwargs):
        raise AssertionError("live history fetch should not be called")

    monkeypatch.setattr(ta, "get_recent_spot_history", _raise_if_called)
    history = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-03-01 09:15", periods=60, freq="D", tz="Asia/Kolkata"),
            "close": [100.0 + idx for idx in range(60)],
        }
    )

    features = get_ta_features_for_trade(
        "NIFTY",
        120.0,
        history_df=history,
        as_of="2026-03-31T15:30:00+05:30",
        allow_live_history=False,
    )

    assert features["ta_regime"] != "point_in_time_unavailable"
    assert features["indicators"]


def test_build_ta_features_default_history_covers_slow_window(monkeypatch):
    import features.ta_indicators as ta

    captured = {}

    def _fake_history(symbol, days):
        captured["symbol"] = symbol
        captured["days"] = days
        return pd.DataFrame({"close": [100.0 + idx for idx in range(60)]})

    monkeypatch.setattr(ta, "get_recent_spot_history", _fake_history)

    features = build_ta_features("NIFTY", 160.0)

    expected_days = get_technical_analysis_policy_config().default_history_days
    assert expected_days >= 100
    assert captured == {"symbol": "NIFTY", "days": expected_days}
    assert "sma_50" in features["indicators"]


def test_build_ta_features_computes_partial_indicators_with_minimum_history():
    history = pd.DataFrame({"close": [100.0 + idx for idx in range(14)]})

    features = build_ta_features(
        "NIFTY",
        114.0,
        history_df=history,
        allow_live_history=False,
    )

    assert features["ta_direction"] == "PUT"
    assert features["ta_confidence"] == 0.7
    assert features["ta_regime"] == "overbought"
    assert features["indicators"]["rsi"] == 100.0


def test_ta_feature_windows_are_runtime_policy_driven():
    history = pd.DataFrame({"close": [100.0 + idx for idx in range(20)]})

    with temporary_parameter_pack(
        "ta_window_test",
        overrides={
            "analytics.technical_analysis.sma_fast_window": 10,
            "analytics.technical_analysis.minimum_history_rows": 10,
        },
    ):
        features = build_ta_features(
            "NIFTY",
            120.0,
            history_df=history,
            allow_live_history=False,
        )

    assert "sma_10" in features["indicators"]
    assert "ret_10d_bps" in features["indicators"]
    assert "ret_20d_bps" in features["indicators"]


def test_intraday_candle_features_confirm_call_direction():
    timestamps = pd.date_range("2026-05-25 09:15", periods=20, freq="min", tz="Asia/Kolkata")
    prices = [
        100.0, 100.1, 100.0, 100.1, 100.0,
        100.2, 100.1, 100.0, 100.2, 100.1,
        100.4, 100.3, 100.5, 100.4, 100.6,
        100.8, 101.2, 101.8, 102.4, 103.0,
    ]
    history = pd.DataFrame({"timestamp": timestamps, "spot": prices})

    features = build_intraday_candle_features(
        "NIFTY",
        103.0,
        intraday_history_df=history,
        as_of=timestamps[-1],
        allow_live_history=False,
    )

    assert features["ta_candle_status"] == "OK"
    assert features["ta_candle_direction"] == "CALL"
    assert features["ta_candle_state"] in {"CANDLE_CONFIRMED_CALL", "CANDLE_LATE_CHASE_CALL"}
    assert features["ta_entry_timing_score"] > 0
    assert features["ta_candle_close_location"] >= 0.66


def test_build_ta_features_carries_intraday_candle_fields_with_slow_ta():
    daily_history = pd.DataFrame({"close": [100.0 + idx for idx in range(60)]})
    timestamps = pd.date_range("2026-05-25 09:15", periods=20, freq="min", tz="Asia/Kolkata")
    intraday = pd.DataFrame(
        {
            "timestamp": timestamps,
            "spot": [100.0] * 15 + [100.5, 101.0, 101.5, 102.0, 102.5],
        }
    )

    features = build_ta_features(
        "NIFTY",
        102.5,
        history_df=daily_history,
        intraday_history_df=intraday,
        as_of=timestamps[-1],
        allow_live_history=False,
    )

    assert features["ta_direction"] in {"CALL", "PUT", "NO_SIGNAL"}
    assert features["ta_candle_status"] == "OK"
    assert features["ta_candle_direction"] == "CALL"

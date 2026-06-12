from __future__ import annotations

import pandas as pd

from analytics.price_structure import (
    add_price_structure_research_overlays,
    build_price_structure_state,
    resolve_session_anchor_levels,
)


def test_build_price_structure_state_uses_spot_history_without_lookahead() -> None:
    history = pd.DataFrame(
        [
            {"timestamp": "2026-06-11T09:15:00+05:30", "spot": 100.0},
            {"timestamp": "2026-06-11T09:20:00+05:30", "spot": 110.0},
            {"timestamp": "2026-06-11T09:30:00+05:30", "spot": 90.0},
            {"timestamp": "2026-06-11T09:50:00+05:30", "spot": 140.0},
        ]
    )

    def loader(symbol, *, start_ts=None, end_ts=None, dedupe=True):
        assert symbol == "NIFTY"
        return history

    state = build_price_structure_state(
        "NIFTY",
        {
            "spot": 105.0,
            "day_open": 100.0,
            "day_high": 120.0,
            "day_low": 90.0,
            "prev_close": 98.0,
            "timestamp": "2026-06-11T09:35:00+05:30",
        },
        spot_history_loader=loader,
    )

    assert state["price_structure_history_rows"] == 3
    assert state["price_structure_vwap_source"] == "UNAVAILABLE"
    assert state["price_structure_twap_proxy_source"] == "SPOT_HISTORY_TWAP_PROXY"
    assert state["price_structure_twap_proxy"] == 100.0
    assert state["spot_vs_twap_proxy_state"] == "ABOVE_TWAP_PROXY"
    assert state["opening_range_5m_status"] == "COMPLETE"
    assert state["opening_range_5m_high"] == 110.0
    assert state["opening_range_5m_low"] == 100.0
    assert state["opening_range_5m_row_count"] == 2
    assert state["opening_range_5m_sample_quality"] == "THIN_SAMPLE"
    assert state["opening_range_15m_high"] == 110.0
    assert state["opening_range_15m_low"] == 90.0
    assert state["opening_range_15m_sample_quality"] == "OK"
    assert state["opening_range_30m_state"] == "INSIDE_OPENING_RANGE"
    assert state["opening_range_30m_sample_quality"] == "OK"


def test_build_price_structure_state_prefers_provider_vwap_when_available() -> None:
    state = build_price_structure_state(
        "NIFTY",
        {
            "spot": 105.0,
            "vwap": 102.5,
            "day_high": 110.0,
            "day_low": 100.0,
            "timestamp": "2026-06-11T10:00:00+05:30",
        },
        spot_history_loader=lambda *args, **kwargs: pd.DataFrame(columns=["timestamp", "spot"]),
    )

    assert state["price_structure_vwap"] == 102.5
    assert state["price_structure_vwap_source"] == "SPOT_SUMMARY_VWAP"
    assert state["spot_vs_vwap_state"] == "ABOVE_VWAP"
    assert state["spot_vs_vwap_distance_pts"] == -2.5


def test_build_price_structure_state_calculates_cpr_from_direct_prior_ohlc() -> None:
    state = build_price_structure_state(
        "NIFTY",
        {
            "spot": 112.0,
            "day_high": 118.0,
            "day_low": 108.0,
            "timestamp": "2026-06-11T10:00:00+05:30",
            "prior_session_high": 130.0,
            "prior_session_low": 100.0,
            "prior_session_close": 100.0,
            "prior_session_date": "2026-06-10",
        },
        spot_history_loader=lambda *args, **kwargs: pd.DataFrame(columns=["timestamp", "spot"]),
    )

    assert state["prior_session_ohlc_available"] is True
    assert state["prior_session_ohlc_source"] == "SPOT_SUMMARY_PRIOR_SESSION_OHLC"
    assert state["classic_pivot"] == 110.0
    assert state["cpr_bc"] == 115.0
    assert state["cpr_tc"] == 105.0
    assert state["cpr_lower"] == 105.0
    assert state["cpr_upper"] == 115.0
    assert state["cpr_width_pts"] == 10.0
    assert state["pivot_r1"] == 120.0
    assert state["pivot_s1"] == 90.0
    assert state["pivot_r2"] == 140.0
    assert state["pivot_s2"] == 80.0
    assert state["pivot_r3"] == 150.0
    assert state["pivot_s3"] == 60.0
    assert state["spot_vs_pivot_state"] == "ABOVE_PIVOT"
    assert state["spot_vs_cpr_state"] == "INSIDE_CPR"


def test_build_price_structure_state_derives_cpr_from_prior_spot_history() -> None:
    history = pd.DataFrame(
        [
            {"timestamp": "2026-06-10T09:20:00+05:30", "spot": 130.0},
            {"timestamp": "2026-06-10T10:00:00+05:30", "spot": 100.0},
            {"timestamp": "2026-06-10T15:29:00+05:30", "spot": 100.0},
            {"timestamp": "2026-06-11T09:15:00+05:30", "spot": 111.0},
            {"timestamp": "2026-06-11T09:20:00+05:30", "spot": 112.0},
        ]
    )

    def loader(symbol, *, start_ts=None, end_ts=None, dedupe=True):
        assert symbol == "NIFTY"
        return history

    state = build_price_structure_state(
        "NIFTY",
        {
            "spot": 112.0,
            "day_high": 118.0,
            "day_low": 108.0,
            "timestamp": "2026-06-11T10:00:00+05:30",
        },
        spot_history_loader=loader,
    )

    assert state["price_structure_history_rows"] == 2
    assert state["prior_session_ohlc_available"] is True
    assert state["prior_session_ohlc_source"] == "SPOT_HISTORY_PRIOR_SESSION_PROXY"
    assert state["prior_session_date"] == "2026-06-10"
    assert state["prior_session_high"] == 130.0
    assert state["prior_session_low"] == 100.0
    assert state["prior_session_close"] == 100.0
    assert state["classic_pivot"] == 110.0
    assert state["spot_vs_cpr_state"] == "INSIDE_CPR"


def test_resolve_session_anchor_levels_dedupes_overlapping_anchors() -> None:
    rows = resolve_session_anchor_levels(
        spot=105.0,
        day_open=100.0,
        day_high=110.0,
        day_low=90.0,
        prev_close=100.0,
        top_n=3,
    )

    assert ("support", 1, 100.0, "day_open/prev_close/range_mid") in rows
    assert rows[0] == ("resistance", 1, 110.0, "day_high")


def test_price_structure_research_overlays_capture_confluence_and_acceptance() -> None:
    spot_summary = {
        "spot": 105.0,
        "day_open": 100.0,
        "day_high": 120.0,
        "day_low": 90.0,
        "prev_close": 100.0,
        "timestamp": "2026-06-11T09:35:00+05:30",
    }
    state = {
        "price_structure_twap_proxy": 100.0,
        "spot_vs_twap_proxy_state": "ABOVE_TWAP_PROXY",
        "price_structure_range_position_pct": 50.0,
        "opening_range_30m_high": 110.0,
        "opening_range_30m_low": 90.0,
        "opening_range_30m_state": "INSIDE_OPENING_RANGE",
    }

    enriched = add_price_structure_research_overlays(
        state,
        spot_summary=spot_summary,
        trade={"gamma_flip": 100.0, "support_wall": 100.0, "max_pain": 100.0},
        confluence_window_pts=5.0,
    )

    assert enriched["price_level_confluence_source_count"] >= 4
    assert enriched["price_level_confluence_state"] in {"HIGH_CONFLUENCE", "VERY_HIGH_CONFLUENCE"}
    assert "dealer_gamma" in enriched["nearest_confluence_sources"]
    assert enriched["price_structure_acceptance_state"] == "BALANCED_ROTATION_CANDIDATE"
    assert enriched["price_structure_day_type_proxy"] == "RANGE_DAY_CANDIDATE"

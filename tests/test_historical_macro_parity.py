from __future__ import annotations

from datetime import date

from data import historical_snapshot


# Keep this list aligned with statuses produced by the live scheduled-event path.
LIVE_EVENT_WINDOW_STATUSES = {
    "NO_EVENT_DATA",
    "CLEAR",
    "PRE_EVENT_WATCH",
    "PRE_EVENT_LOCKDOWN",
    "LIVE_EVENT",
    "POST_EVENT_COOLDOWN",
    "EVENT_FILTER_DISABLED",
}


def _event(name: str, ts: str, severity: str = "MAJOR") -> dict:
    return {
        "name": name,
        "timestamp": ts,
        "severity": severity,
        "scope": ["ALL"],
    }


def test_historical_macro_statuses_match_live_enum(monkeypatch):
    trade_day = date(2026, 3, 18)

    scenarios = [
        [],
        [_event("RBI Policy", "2026-03-18T10:00:00+05:30", "CRITICAL")],
        [_event("India CPI", "2026-03-19T08:00:00+05:30", "MAJOR")],
        [_event("US Payrolls", "2026-03-17T20:30:00+05:30", "MEDIUM")],
        [_event("Far Event", "2026-04-15T10:00:00+05:30", "MINOR")],
    ]

    for events in scenarios:
        monkeypatch.setattr(historical_snapshot, "_load_macro_events", lambda: events)
        state = historical_snapshot._build_historical_macro_event_state(trade_day, "NIFTY")
        assert state["event_window_status"] in LIVE_EVENT_WINDOW_STATUSES


def test_historical_macro_risk_score_bounded_0_100(monkeypatch):
    trade_day = date(2026, 3, 18)
    events = [
        _event("RBI Policy", "2026-03-18T10:00:00+05:30", "CRITICAL"),
        _event("Unknown Medium Event", "2026-03-19T10:00:00+05:30", "MEDIUM"),
        _event("Low Trade Event", "2026-03-17T10:00:00+05:30", "MINOR"),
    ]

    monkeypatch.setattr(historical_snapshot, "_load_macro_events", lambda: events)
    state = historical_snapshot._build_historical_macro_event_state(trade_day, "NIFTY")

    score = state.get("macro_event_risk_score")
    assert isinstance(score, int)
    assert 0 <= score <= 100

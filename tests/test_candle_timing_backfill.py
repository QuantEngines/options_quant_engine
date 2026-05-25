from __future__ import annotations

import pandas as pd

from research.signal_evaluation import candle_timing_backfill as ctb


def test_enrich_candle_timing_features_uses_local_spot_history(monkeypatch):
    signal_ts = pd.Timestamp("2026-05-25 09:34", tz="Asia/Kolkata")
    frame = pd.DataFrame(
        [
            {
                "signal_id": "s1",
                "signal_timestamp": signal_ts.isoformat(),
                "symbol": "NIFTY",
                "spot_at_signal": 103.0,
            }
        ]
    )
    timestamps = pd.date_range("2026-05-25 09:15", periods=20, freq="min", tz="Asia/Kolkata")
    history = pd.DataFrame(
        {
            "timestamp": timestamps,
            "spot": [100.0] * 15 + [100.8, 101.2, 101.8, 102.4, 103.0],
        }
    )
    monkeypatch.setattr(ctb, "load_spot_history", lambda *args, **kwargs: history)

    updated, summary = ctb.enrich_candle_timing_features(frame)

    assert summary["rows_seen"] == 1
    assert summary["rows_enriched"] == 1
    assert updated.loc[0, "ta_candle_status"] == "OK"
    assert updated.loc[0, "ta_candle_direction"] == "CALL"
    assert updated.loc[0, "ta_entry_timing_score"] > 0

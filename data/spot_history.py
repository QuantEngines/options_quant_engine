"""
Module: spot_history.py

Purpose:
    Persist and retrieve intraday spot observations as a continuous time-series.

Role in the System:
    Part of the data layer that accumulates a local spot history during live sessions.
    This provides a reliable fallback for outcome enrichment when external providers
    (yfinance) are unavailable or delayed.

Key Outputs:
    Append-only CSV files with (timestamp, spot, symbol) rows, one file per symbol per date.

Downstream Usage:
    Consumed by the signal-evaluation enrichment pipeline as a primary local source
    of realized spot paths, reducing dependence on yfinance backfills.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config.market_data_policy import IST_TIMEZONE

logger = logging.getLogger(__name__)

SPOT_HISTORY_DIR = Path("data_store") / "spot_history"


def _history_path(symbol: str, date: str, *, base_dir: Path = SPOT_HISTORY_DIR) -> Path:
    return base_dir / symbol.upper() / f"{symbol.upper()}_{date}.csv"


def append_spot_observation(
    symbol: str,
    spot: float,
    timestamp,
    *,
    base_dir: Path = SPOT_HISTORY_DIR,
) -> Path:
    """Append a single (timestamp, spot) row to the daily spot history file."""
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize(IST_TIMEZONE)
    else:
        ts = ts.tz_convert(IST_TIMEZONE)

    date_str = ts.strftime("%Y-%m-%d")
    path = _history_path(symbol, date_str, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    ts_iso = ts.isoformat()
    write_header = not path.exists()
    with open(path, "a", encoding="utf-8") as f:
        if write_header:
            f.write("timestamp,spot\n")
        f.write(f"{ts_iso},{round(float(spot), 4)}\n")

    return path


def load_spot_history(
    symbol: str,
    *,
    start_ts=None,
    end_ts=None,
    base_dir: Path = SPOT_HISTORY_DIR,
) -> pd.DataFrame:
    """Load local spot history for a symbol between start_ts and end_ts.

    Scans daily CSV files in the symbol's directory to build a contiguous
    (timestamp, spot) DataFrame.  Returns an empty frame if no local data exists.
    """
    symbol_dir = base_dir / symbol.upper()
    if not symbol_dir.exists():
        return pd.DataFrame(columns=["timestamp", "spot"])

    start = pd.Timestamp(start_ts).tz_convert(IST_TIMEZONE) if start_ts is not None else None
    end = pd.Timestamp(end_ts).tz_convert(IST_TIMEZONE) if end_ts is not None else None

    frames: list[pd.DataFrame] = []
    for csv_file in sorted(symbol_dir.glob("*.csv")):
        try:
            df = pd.read_csv(csv_file, parse_dates=["timestamp"])
        except Exception:
            logger.warning("Skipping corrupt spot history file: %s", csv_file)
            continue

        if df.empty or "timestamp" not in df.columns or "spot" not in df.columns:
            continue

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(IST_TIMEZONE)
        df["spot"] = pd.to_numeric(df["spot"], errors="coerce")
        df = df.dropna(subset=["timestamp", "spot"])

        if start is not None:
            df = df[df["timestamp"] >= start]
        if end is not None:
            df = df[df["timestamp"] <= end]

        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["timestamp", "spot"])

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return combined[["timestamp", "spot"]]

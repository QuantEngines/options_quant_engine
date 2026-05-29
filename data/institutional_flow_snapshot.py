"""
Lagged institutional-flow snapshot ingestion.

This module intentionally uses a file-backed, point-in-time reader.  FII/DII
flows are published after the fact, so they are captured as research context
and must not leak into live intraday signal decisions.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from config.market_data_policy import IST_TIMEZONE
from config.settings import DATA_DIR
from utils.numerics import safe_float as _safe_float


FLOW_FIELDS = (
    "fii_cash_net",
    "dii_cash_net",
    "fii_index_futures_net",
    "fii_index_options_net",
)

DEFAULT_FLOW_PATH = Path(DATA_DIR) / "macro" / "institutional_flows.csv"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except Exception:
        return default


def _coerce_timestamp(value):
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce", dayfirst=True, utc=True)
    if pd.isna(parsed):
        return None
    try:
        return parsed.tz_convert(IST_TIMEZONE)
    except Exception:
        return None


def _coerce_date(value):
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _safe_flow_float(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return _safe_float(value, None)


def _normalize_column_name(value: str) -> str:
    token = str(value or "").strip().lower()
    for char in (" ", "-", "/", ".", "(", ")", "%"):
        token = token.replace(char, "_")
    while "__" in token:
        token = token.replace("__", "_")
    return token.strip("_")


def _rename_columns(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "date": "date",
        "flow_date": "date",
        "report_date": "date",
        "trade_date": "date",
        "source": "source",
        "provider": "source",
        "source_timestamp": "source_timestamp",
        "published_at": "source_timestamp",
        "publication_timestamp": "source_timestamp",
        "timestamp": "source_timestamp",
        "as_of": "source_timestamp",
        "fii_cash_net": "fii_cash_net",
        "fii_net_cash": "fii_cash_net",
        "fii_cash": "fii_cash_net",
        "fpi_cash_net": "fii_cash_net",
        "dii_cash_net": "dii_cash_net",
        "dii_net_cash": "dii_cash_net",
        "dii_cash": "dii_cash_net",
        "fii_index_futures_net": "fii_index_futures_net",
        "fii_idx_futures_net": "fii_index_futures_net",
        "fii_index_future_net": "fii_index_futures_net",
        "fii_index_options_net": "fii_index_options_net",
        "fii_idx_options_net": "fii_index_options_net",
        "fii_index_option_net": "fii_index_options_net",
    }
    rename_map = {}
    for column in frame.columns:
        normalized = _normalize_column_name(column)
        target = aliases.get(normalized)
        if target:
            rename_map[column] = target
    return frame.rename(columns=rename_map)


def _empty_snapshot(*, as_of_ts, path, warnings=None, issues=None):
    return {
        "provider": "FILE",
        "path": str(path),
        "as_of": as_of_ts.isoformat(),
        "data_available": False,
        "neutral_fallback": True,
        "stale": True,
        "flow_date": None,
        "source": None,
        "source_timestamp": None,
        "staleness_days": None,
        "warnings": list(warnings or []),
        "issues": list(issues or []),
        "flows": {field: None for field in FLOW_FIELDS},
    }


def build_institutional_flow_snapshot(*, as_of=None, path=None, max_staleness_days=None) -> dict:
    """
    Load the latest point-in-time eligible FII/DII flow row.

    Expected CSV columns:
        date, fii_cash_net, dii_cash_net, fii_index_futures_net,
        fii_index_options_net, source, source_timestamp

    Same-day rows are only eligible when `source_timestamp <= as_of`.  Rows
    without a source timestamp are treated as end-of-day lagged data and become
    eligible from the next date onward.
    """

    as_of_ts = _coerce_timestamp(as_of) or pd.Timestamp.now(tz=IST_TIMEZONE)
    enabled = _env_bool("INSTITUTIONAL_FLOW_DATA_ENABLED", True)
    flow_path = Path(path or os.getenv("INSTITUTIONAL_FLOW_FILE", str(DEFAULT_FLOW_PATH))).expanduser()
    max_staleness = (
        int(max_staleness_days)
        if max_staleness_days is not None
        else _env_int("INSTITUTIONAL_FLOW_MAX_STALENESS_DAYS", 7)
    )

    if not enabled:
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=flow_path,
            warnings=["institutional_flow_data_disabled"],
        )

    if not flow_path.exists():
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=flow_path,
            warnings=[f"institutional_flow_file_missing:{flow_path}"],
        )

    try:
        frame = pd.read_csv(flow_path)
    except Exception as exc:
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=flow_path,
            issues=[f"institutional_flow_file_read_failed:{exc}"],
        )

    frame = _rename_columns(frame)
    if "date" not in frame.columns:
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=flow_path,
            issues=["institutional_flow_date_column_missing"],
        )

    working = frame.copy()
    working["_flow_date"] = working["date"].apply(_coerce_date)
    working = working[working["_flow_date"].notna()].copy()
    if working.empty:
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=flow_path,
            issues=["institutional_flow_no_valid_dates"],
        )

    if "source_timestamp" in working.columns:
        working["_source_timestamp"] = working["source_timestamp"].apply(_coerce_timestamp)
    else:
        working["_source_timestamp"] = None

    as_of_date = as_of_ts.date()

    def _eligible(row) -> bool:
        source_ts = row.get("_source_timestamp")
        if source_ts is not None and not pd.isna(source_ts):
            return source_ts <= as_of_ts
        return row["_flow_date"] < as_of_date

    eligible = working[working.apply(_eligible, axis=1)].copy()
    if eligible.empty:
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=flow_path,
            warnings=["institutional_flow_no_point_in_time_eligible_row"],
        )

    eligible["_sort_ts"] = eligible["_source_timestamp"].apply(
        lambda value: value.value if value is not None and not pd.isna(value) else -1
    )
    eligible = eligible.sort_values(["_flow_date", "_sort_ts"], ascending=[True, True])
    latest = eligible.iloc[-1]

    flow_date = latest["_flow_date"]
    staleness_days = max((as_of_date - flow_date).days, 0)
    stale = staleness_days > max_staleness
    warnings = []
    if stale:
        warnings.append(f"institutional_flow_stale:{staleness_days}d")

    source_ts = latest.get("_source_timestamp")
    source_ts_text = source_ts.isoformat() if source_ts is not None and not pd.isna(source_ts) else None
    source_value = latest.get("source")
    source_text = None
    if source_value is not None and not pd.isna(source_value) and str(source_value).strip():
        source_text = str(source_value).strip()
    flows = {field: _safe_flow_float(latest.get(field)) for field in FLOW_FIELDS}

    return {
        "provider": "FILE",
        "path": str(flow_path),
        "as_of": as_of_ts.isoformat(),
        "data_available": not stale,
        "neutral_fallback": stale,
        "stale": stale,
        "flow_date": flow_date.isoformat(),
        "source": source_text,
        "source_timestamp": source_ts_text,
        "staleness_days": staleness_days,
        "warnings": warnings,
        "issues": [],
        "flows": flows,
    }

"""
Lagged India bond-market context ingestion.

India G-Sec yields are important macro context for index-options signals, but
they are not cleanly available from the existing intraday provider stack. This
module reads a local EOD file with point-in-time eligibility, mirroring the
institutional-flow approach: research/display first, no live-score influence.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from config.market_data_policy import IST_TIMEZONE
from config.settings import DATA_DIR
from utils.numerics import safe_float as _safe_float


BOND_YIELD_FIELDS = (
    "india_2y_yield",
    "india_5y_yield",
    "india_10y_yield",
    "india_30y_yield",
    "india_10y_change_bp",
    "india_2y10y_spread_bp",
    "india_5y10y_spread_bp",
)

DEFAULT_BOND_YIELD_PATH = Path(DATA_DIR) / "macro" / "india_bond_yields.csv"

STANDARD_COLUMNS = (
    "date",
    "india_2y_yield",
    "india_5y_yield",
    "india_10y_yield",
    "india_30y_yield",
    "india_10y_change_bp",
    "india_2y10y_spread_bp",
    "india_5y10y_spread_bp",
    "source",
    "source_timestamp",
)


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


def _safe_bond_float(value):
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
    token = token.replace("%", "pct")
    for char in (" ", "-", "/", ".", "(", ")"):
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
        "india_2y_yield": "india_2y_yield",
        "india_2_year_yield": "india_2y_yield",
        "india_2y_gsec_yield": "india_2y_yield",
        "india_5y_yield": "india_5y_yield",
        "india_5_year_yield": "india_5y_yield",
        "india_5y_gsec_yield": "india_5y_yield",
        "india_10y_yield": "india_10y_yield",
        "india_10_year_yield": "india_10y_yield",
        "india_10y_gsec_yield": "india_10y_yield",
        "india_10_year_gsec_yield": "india_10y_yield",
        "india_30y_yield": "india_30y_yield",
        "india_30_year_yield": "india_30y_yield",
        "india_30y_gsec_yield": "india_30y_yield",
        "india_10y_change_bp": "india_10y_change_bp",
        "india_10y_change_bps": "india_10y_change_bp",
        "india_10_year_change_bp": "india_10y_change_bp",
        "india_2y10y_spread_bp": "india_2y10y_spread_bp",
        "india_2s10s_spread_bp": "india_2y10y_spread_bp",
        "india_5y10y_spread_bp": "india_5y10y_spread_bp",
        "india_5s10s_spread_bp": "india_5y10y_spread_bp",
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
        "bond_date": None,
        "source": None,
        "source_timestamp": None,
        "staleness_days": None,
        "warnings": list(warnings or []),
        "issues": list(issues or []),
        "yields": {field: None for field in BOND_YIELD_FIELDS},
    }


def _derive_spreads(values: dict[str, float | None]) -> dict[str, float | None]:
    out = dict(values)
    ten = out.get("india_10y_yield")
    two = out.get("india_2y_yield")
    five = out.get("india_5y_yield")
    if out.get("india_2y10y_spread_bp") is None and ten is not None and two is not None:
        out["india_2y10y_spread_bp"] = (ten - two) * 100.0
    if out.get("india_5y10y_spread_bp") is None and ten is not None and five is not None:
        out["india_5y10y_spread_bp"] = (ten - five) * 100.0
    return out


def build_india_bond_yield_snapshot(*, as_of=None, path=None, max_staleness_days=None) -> dict:
    """
    Load the latest point-in-time eligible India G-Sec yield row.

    Expected CSV columns:
        date, india_10y_yield, india_10y_change_bp, source, source_timestamp

    Optional columns:
        india_2y_yield, india_5y_yield, india_30y_yield,
        india_2y10y_spread_bp, india_5y10y_spread_bp

    Same-day rows are only eligible when `source_timestamp <= as_of`. Rows
    without source timestamps are treated as next-day eligible EOD data.
    """

    as_of_ts = _coerce_timestamp(as_of) or pd.Timestamp.now(tz=IST_TIMEZONE)
    enabled = _env_bool("INDIA_BOND_YIELD_DATA_ENABLED", True)
    bond_path = Path(path or os.getenv("INDIA_BOND_YIELD_FILE", str(DEFAULT_BOND_YIELD_PATH))).expanduser()
    max_staleness = (
        int(max_staleness_days)
        if max_staleness_days is not None
        else _env_int("INDIA_BOND_YIELD_MAX_STALENESS_DAYS", 10)
    )

    if not enabled:
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=bond_path,
            warnings=["india_bond_yield_data_disabled"],
        )

    if not bond_path.exists():
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=bond_path,
            warnings=[f"india_bond_yield_file_missing:{bond_path}"],
        )

    try:
        frame = pd.read_csv(bond_path)
    except Exception as exc:
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=bond_path,
            issues=[f"india_bond_yield_file_read_failed:{exc}"],
        )

    frame = _rename_columns(frame)
    if "date" not in frame.columns:
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=bond_path,
            issues=["india_bond_yield_date_column_missing"],
        )

    working = frame.copy()
    working["_bond_date"] = working["date"].apply(_coerce_date)
    working = working[working["_bond_date"].notna()].copy()
    if working.empty:
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=bond_path,
            issues=["india_bond_yield_no_valid_dates"],
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
        return row["_bond_date"] < as_of_date

    eligible = working[working.apply(_eligible, axis=1)].copy()
    if eligible.empty:
        return _empty_snapshot(
            as_of_ts=as_of_ts,
            path=bond_path,
            warnings=["india_bond_yield_no_point_in_time_eligible_row"],
        )

    eligible["_sort_ts"] = eligible["_source_timestamp"].apply(
        lambda value: value.value if value is not None and not pd.isna(value) else -1
    )
    eligible = eligible.sort_values(["_bond_date", "_sort_ts"], ascending=[True, True])
    latest = eligible.iloc[-1]

    bond_date = latest["_bond_date"]
    staleness_days = max((as_of_date - bond_date).days, 0)
    stale = staleness_days > max_staleness
    warnings = []
    if stale:
        warnings.append(f"india_bond_yield_stale:{staleness_days}d")

    source_ts = latest.get("_source_timestamp")
    source_ts_text = source_ts.isoformat() if source_ts is not None and not pd.isna(source_ts) else None
    source_value = latest.get("source")
    source_text = None
    if source_value is not None and not pd.isna(source_value) and str(source_value).strip():
        source_text = str(source_value).strip()
    values = {field: _safe_bond_float(latest.get(field)) for field in BOND_YIELD_FIELDS}
    values = _derive_spreads(values)

    return {
        "provider": "FILE",
        "path": str(bond_path),
        "as_of": as_of_ts.isoformat(),
        "data_available": not stale and values.get("india_10y_yield") is not None,
        "neutral_fallback": stale or values.get("india_10y_yield") is None,
        "stale": stale,
        "bond_date": bond_date.isoformat(),
        "source": source_text,
        "source_timestamp": source_ts_text,
        "staleness_days": staleness_days,
        "warnings": warnings,
        "issues": [],
        "yields": values,
    }


def upsert_india_bond_yield_row(row: dict, *, path: str | Path = DEFAULT_BOND_YIELD_PATH) -> Path:
    """Upsert one India bond-yield row into the local macro CSV store."""
    if not row:
        raise ValueError("row is required")
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing = pd.DataFrame()
    if output_path.exists():
        existing = pd.read_csv(output_path)

    existing_rows = existing.to_dict("records") if not existing.empty else []
    frame = pd.DataFrame.from_records([*existing_rows, row])

    for column in STANDARD_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    frame["_date_sort"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["_source_ts_sort"] = pd.to_datetime(frame.get("source_timestamp"), errors="coerce", utc=True)
    frame = frame.sort_values(["_date_sort", "source", "_source_ts_sort"], na_position="last")
    frame = frame.drop_duplicates(subset=["date", "source"], keep="last")
    frame = frame.drop(columns=["_date_sort", "_source_ts_sort"])

    ordered = [column for column in STANDARD_COLUMNS if column in frame.columns]
    ordered.extend(column for column in frame.columns if column not in ordered)
    frame = frame[ordered]

    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    frame.to_csv(tmp_path, index=False)
    tmp_path.replace(output_path)
    return output_path

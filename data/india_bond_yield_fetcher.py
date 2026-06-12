"""
Official-source fetcher for India G-Sec benchmark tenor yields.

The live engine consumes India bond context only through
`data.india_bond_yield_snapshot`, which applies point-in-time eligibility.
This module is an EOD/research utility that updates the local macro file from
CCIL's tenor-wise indicative yields page; it must not be called from the
intraday signal loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
import re

import pandas as pd
import requests

from config.market_data_policy import IST_TIMEZONE
from data.india_bond_yield_snapshot import DEFAULT_BOND_YIELD_PATH


CCIL_TENORWISE_INDICATIVE_YIELDS_URL = "https://www.ccilindia.com/tenorwise-indicative-yields"
CCIL_SOURCE = "CCIL_TENORWISE_INDICATIVE_YIELDS"
STANDARD_TENORS = {
    "india_2y_yield": ("1Y-2Y", "2Y"),
    "india_5y_yield": ("4Y-5Y", "5Y"),
    "india_10y_yield": ("9Y-10Y", "10Y"),
    "india_30y_yield": ("28Y-30Y", "30Y"),
}


@dataclass
class IndiaBondYieldFetch:
    source: str
    row: dict | None = None
    warnings: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    raw_url: str | None = None

    @property
    def ok(self) -> bool:
        return self.row is not None and not self.issues


def _base_headers() -> dict[str, str]:
    return {
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "referer": "https://www.ccilindia.com/",
    }


def _now_ist() -> pd.Timestamp:
    return pd.Timestamp.now(tz=IST_TIMEZONE)


def _coerce_source_timestamp(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        parsed = _now_ist()
    return parsed.tz_convert(IST_TIMEZONE).isoformat()


def _normalize_column_name(value) -> str:
    token = str(value or "").strip().lower()
    token = re.sub(r"[^a-z0-9]+", "_", token)
    token = re.sub(r"_+", "_", token)
    return token.strip("_")


def _parse_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-", "--"}:
        return None
    text = text.replace(",", "").replace("%", "").strip()
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def _parse_date(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _read_html_tables(html_text: str) -> list[pd.DataFrame]:
    if not html_text:
        return []
    try:
        return list(pd.read_html(StringIO(html_text)))
    except Exception:
        return []


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        flattened = []
        for column in out.columns:
            parts = [
                str(part)
                for part in column
                if str(part).strip() and not str(part).lower().startswith("unnamed")
            ]
            flattened.append("_".join(parts) if parts else "")
        out.columns = flattened
    else:
        out.columns = [str(column) for column in out.columns]
    return out


def _column_by_name(frame: pd.DataFrame, fragments: tuple[str, ...]) -> str | None:
    normalized_fragments = tuple(_normalize_column_name(fragment) for fragment in fragments)
    for column in frame.columns:
        normalized = _normalize_column_name(column)
        if any(fragment in normalized for fragment in normalized_fragments):
            return column
    return None


def _rows_from_frame(frame: pd.DataFrame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    working = _flatten_columns(frame)
    date_col = _column_by_name(working, ("date",))
    tenor_col = _column_by_name(working, ("tenor_bucket", "tenor"))
    security_col = _column_by_name(working, ("security", "instrument"))
    ytm_col = _column_by_name(working, ("ytm", "yield"))
    if not date_col or not tenor_col or not ytm_col:
        return []

    rows = []
    for _, row in working.iterrows():
        date_text = _parse_date(row.get(date_col))
        tenor = str(row.get(tenor_col) or "").strip().upper()
        ytm = _parse_number(row.get(ytm_col))
        if not date_text or not tenor or ytm is None:
            continue
        rows.append(
            {
                "date": date_text,
                "tenor_bucket": tenor,
                "security": str(row.get(security_col) or "").strip() if security_col else "",
                "ytm": ytm,
            }
        )
    return rows


def _rows_from_text(html_text: str) -> list[dict]:
    if not html_text:
        return []
    text = re.sub(r"<script\b.*?</script>", "\n", html_text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", "\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</(?:tr|p|div|li|br)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)

    rows = []
    row_pattern = re.compile(
        r"^\s*(?P<date>\d{1,2}-\d{1,2}-\d{4})\s+"
        r"(?P<tenor>[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?)\s+"
        r"(?P<security>.+?)\s+"
        r"(?P<ytm>[-+]?\d+(?:\.\d+)?)\s*$"
    )
    for line in text.splitlines():
        match = row_pattern.match(line.strip())
        if not match:
            continue
        date_text = _parse_date(match.group("date"))
        ytm = _parse_number(match.group("ytm"))
        if not date_text or ytm is None:
            continue
        rows.append(
            {
                "date": date_text,
                "tenor_bucket": match.group("tenor").strip().upper(),
                "security": match.group("security").strip(),
                "ytm": ytm,
            }
        )
    return rows


def _is_gsec_row(row: dict) -> bool:
    security = str(row.get("security") or "").upper()
    return bool(re.search(r"\bGS\b", security)) and "SGS" not in security


def _latest_gsec_rows(rows: list[dict]) -> list[dict]:
    gsec_rows = [row for row in rows if _is_gsec_row(row) and row.get("date")]
    if not gsec_rows:
        return []
    latest_date = max(row["date"] for row in gsec_rows)
    return [row for row in gsec_rows if row["date"] == latest_date]


def _select_tenor_yield(rows: list[dict], tenor_candidates: tuple[str, ...]) -> float | None:
    candidates = {str(tenor).upper() for tenor in tenor_candidates}
    for row in rows:
        if str(row.get("tenor_bucket") or "").upper() in candidates:
            return _parse_number(row.get("ytm"))
    return None


def _derive_spreads(row: dict) -> dict:
    out = dict(row)
    ten = out.get("india_10y_yield")
    two = out.get("india_2y_yield")
    five = out.get("india_5y_yield")
    if ten is not None and two is not None:
        out["india_2y10y_spread_bp"] = (float(ten) - float(two)) * 100.0
    else:
        out["india_2y10y_spread_bp"] = None
    if ten is not None and five is not None:
        out["india_5y10y_spread_bp"] = (float(ten) - float(five)) * 100.0
    else:
        out["india_5y10y_spread_bp"] = None
    return out


def _previous_10y_yield(*, current_date: str, path: str | Path) -> tuple[str, float] | None:
    bond_path = Path(path).expanduser()
    if not bond_path.exists():
        return None
    try:
        frame = pd.read_csv(bond_path)
    except Exception:
        return None
    if frame.empty or "date" not in frame.columns or "india_10y_yield" not in frame.columns:
        return None
    working = frame.copy()
    working["_date"] = pd.to_datetime(working["date"], errors="coerce")
    current_ts = pd.to_datetime(current_date, errors="coerce")
    if pd.isna(current_ts):
        return None
    working = working[working["_date"].notna() & (working["_date"] < current_ts)].copy()
    working["india_10y_yield"] = pd.to_numeric(working["india_10y_yield"], errors="coerce")
    working = working[working["india_10y_yield"].notna()].copy()
    if working.empty:
        return None
    working = working.sort_values("_date")
    latest = working.iloc[-1]
    return latest["_date"].date().isoformat(), float(latest["india_10y_yield"])


def add_local_10y_change(
    row: dict,
    *,
    path: str | Path = DEFAULT_BOND_YIELD_PATH,
    max_prior_gap_days: int = 5,
) -> dict:
    """Compute 10Y daily change from the local prior row when the source omits it."""
    out = dict(row)
    if out.get("india_10y_change_bp") is not None:
        return out
    current_10y = _parse_number(out.get("india_10y_yield"))
    current_date = out.get("date")
    if current_10y is None or not current_date:
        out["india_10y_change_bp"] = None
        return out
    previous = _previous_10y_yield(current_date=str(current_date), path=path)
    if previous is None:
        out["india_10y_change_bp"] = None
        out["india_10y_change_basis"] = "UNAVAILABLE_NO_PRIOR_ROW"
    else:
        previous_date, previous_10y = previous
        current_ts = pd.to_datetime(current_date, errors="coerce")
        previous_ts = pd.to_datetime(previous_date, errors="coerce")
        gap_days = None
        if not pd.isna(current_ts) and not pd.isna(previous_ts):
            gap_days = int((current_ts.date() - previous_ts.date()).days)
        if gap_days is None or gap_days > max_prior_gap_days:
            out["india_10y_change_bp"] = None
            out["india_10y_change_basis"] = f"UNAVAILABLE_PRIOR_GAP_{gap_days}D"
            return out
        out["india_10y_change_bp"] = (float(current_10y) - float(previous_10y)) * 100.0
        out["india_10y_change_basis"] = "LOCAL_PRIOR_ROW"
    return out


def parse_ccil_tenorwise_yields(html_text: str, *, source_timestamp=None) -> dict:
    """
    Parse CCIL's public tenor-wise indicative yield page into the canonical row.

    The page publishes benchmark buckets such as 4Y-5Y, 9Y-10Y, and 28Y-30Y.
    We map those to 5Y, 10Y, and 30Y G-Sec context for display/research use.
    """
    rows: list[dict] = []
    for frame in _read_html_tables(html_text):
        rows.extend(_rows_from_frame(frame))
    if not rows:
        rows = _rows_from_text(html_text)

    gsec_rows = _latest_gsec_rows(rows)
    if not gsec_rows:
        raise ValueError("no_ccil_gsec_tenor_rows_found")

    latest_date = max(row["date"] for row in gsec_rows)
    output = {
        "date": latest_date,
        "india_10y_change_bp": None,
        "source": CCIL_SOURCE,
        "source_timestamp": _coerce_source_timestamp(source_timestamp),
        "source_url": CCIL_TENORWISE_INDICATIVE_YIELDS_URL,
    }
    for field, tenor_candidates in STANDARD_TENORS.items():
        output[field] = _select_tenor_yield(gsec_rows, tenor_candidates)
    output = _derive_spreads(output)
    if output.get("india_10y_yield") is None:
        raise ValueError("ccil_10y_gsec_yield_missing")
    return output


def fetch_india_bond_yields(
    *,
    timeout: float = 15.0,
    source_timestamp=None,
    previous_path: str | Path = DEFAULT_BOND_YIELD_PATH,
    session=None,
) -> dict:
    """Fetch CCIL tenor-wise G-Sec yields and return a canonical selected row."""
    fetch = IndiaBondYieldFetch(source="CCIL", raw_url=CCIL_TENORWISE_INDICATIVE_YIELDS_URL)
    sess = session or requests.Session()
    try:
        response = sess.get(
            CCIL_TENORWISE_INDICATIVE_YIELDS_URL,
            headers=_base_headers(),
            timeout=timeout,
        )
        status_code = getattr(response, "status_code", 200)
        if int(status_code) >= 400:
            raise RuntimeError(f"http_status_{status_code}")
        row = parse_ccil_tenorwise_yields(response.text, source_timestamp=source_timestamp)
        row = add_local_10y_change(row, path=previous_path)
        fetch.row = row
    except Exception as exc:
        fetch.issues.append(str(exc))

    return {
        "selected_source": "CCIL" if fetch.ok else None,
        "selected_row": fetch.row if fetch.ok else None,
        "results": {
            "CCIL": {
                "row": fetch.row,
                "warnings": list(fetch.warnings),
                "issues": list(fetch.issues),
                "raw_url": fetch.raw_url,
            }
        },
    }

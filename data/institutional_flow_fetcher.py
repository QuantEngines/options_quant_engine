"""
Official exchange fetcher for lagged institutional-flow data.

The live engine consumes institutional flows only through
`data.institutional_flow_snapshot`, which applies point-in-time eligibility.
This module is an EOD/research utility that updates that local file from
official NSE/BSE pages; it must not be called from the intraday signal loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import html
from io import StringIO
from pathlib import Path
import re
from typing import Iterable

import pandas as pd
import requests

from config.market_data_policy import IST_TIMEZONE
from data.institutional_flow_snapshot import DEFAULT_FLOW_PATH, FLOW_FIELDS


NSE_HOME_PAGE = "https://www.nseindia.com/"
NSE_REPORT_PAGE = "https://www.nseindia.com/reports/fii-dii?os=dio"
NSE_FII_DII_API = "https://www.nseindia.com/api/fiidiiTradeReact"
BSE_CATEGORYWISE_TURNOVER_URL = "https://www.bseindia.com/markets/equity/EQReports/categorywise_turnover.aspx"
BSE_CLIENT_CATEGORY_URL = "https://www.bseindia.com/markets/equity/eqreports/stockprchistori.aspx?flag=1"
BSE_ARCHIVE_CATEGORY_URL = "https://www.bseindia.com/stockinfo/categorywise_turnover_default.aspx"

STANDARD_COLUMNS = (
    "date",
    "fii_cash_net",
    "dii_cash_net",
    "fii_index_futures_net",
    "fii_index_options_net",
    "source",
    "source_timestamp",
    "unit",
    "fii_cash_buy",
    "fii_cash_sell",
    "dii_cash_buy",
    "dii_cash_sell",
    "crosscheck_status",
    "crosscheck_max_abs_diff",
    "crosscheck_sources",
    "nse_fii_cash_net",
    "nse_dii_cash_net",
    "bse_fii_cash_net",
    "bse_dii_cash_net",
)


@dataclass
class InstitutionalFlowFetch:
    source: str
    row: dict | None = None
    warnings: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    raw_url: str | None = None

    @property
    def ok(self) -> bool:
        return self.row is not None and not self.issues


def _base_headers(*, referer: str | None = None) -> dict[str, str]:
    return {
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        "accept": "application/json, text/html, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "referer": referer or NSE_HOME_PAGE,
        "connection": "keep-alive",
    }


def _now_ist() -> pd.Timestamp:
    return pd.Timestamp.now(tz=IST_TIMEZONE)


def _normalize_column_name(value) -> str:
    token = str(value or "").strip()
    token = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", token)
    token = token.lower()
    token = re.sub(r"[^a-z0-9]+", "_", token)
    token = re.sub(r"_+", "_", token)
    return token.strip("_")


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        flattened = []
        for col in out.columns:
            parts = [
                str(part)
                for part in col
                if str(part).strip() and not str(part).lower().startswith("unnamed")
            ]
            flattened.append("_".join(parts) if parts else "")
        out.columns = flattened
    else:
        out.columns = [str(col) for col in out.columns]
    return out


def _parse_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-", "--"}:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
    text = (
        text.replace(",", "")
        .replace("₹", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("Cr.", "")
        .replace("Cr", "")
        .replace("crores", "")
        .replace("crore", "")
        .replace("(", "")
        .replace(")", "")
        .strip()
    )
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    value_float = float(match.group(0))
    return -abs(value_float) if negative else value_float


def _parse_date(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    dayfirst = bool(re.match(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$", text))
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=dayfirst)
    if pd.isna(parsed) and not dayfirst:
        parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _column_candidates(frame: pd.DataFrame, fragments: Iterable[str]) -> list[str]:
    fragments = tuple(_normalize_column_name(fragment) for fragment in fragments)
    columns = []
    for col in frame.columns:
        normalized = _normalize_column_name(col)
        if any(fragment in normalized for fragment in fragments):
            columns.append(col)
    return columns


def _first_from_columns(row: pd.Series, columns: Iterable[str]) -> object | None:
    for column in columns:
        if column not in row.index:
            continue
        value = row.get(column)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        text = str(value).strip()
        if text:
            return value
    return None


def _numeric_from_columns(row: pd.Series, columns: Iterable[str]) -> float | None:
    for column in columns:
        value = _parse_number(row.get(column))
        if value is not None:
            return value
    return None


def _numeric_sequence(row: pd.Series) -> list[float]:
    values = []
    for value in row.tolist():
        parsed = _parse_number(value)
        if parsed is not None:
            values.append(parsed)
    return values


def _is_fii_row(text: str) -> bool:
    normalized = text.lower()
    return bool(re.search(r"\bfii\b|\bfpi\b|fii\s*/\s*fpi|foreign institutional", normalized))


def _is_dii_row(text: str) -> bool:
    normalized = text.lower()
    return bool(re.search(r"\bdii\b|domestic institutional", normalized))


def _extract_cash_rows_from_frame(frame: pd.DataFrame) -> tuple[dict | None, dict | None]:
    if frame is None or frame.empty:
        return None, None

    working = _flatten_columns(frame)
    if working.empty:
        return None, None

    date_cols = _column_candidates(working, ("date", "trade_date", "category_date"))
    buy_cols = _column_candidates(working, ("buy_value", "gross_purchase", "purchase", "buyvalue"))
    sell_cols = _column_candidates(working, ("sale_value", "sell_value", "gross_sales", "sales", "sellvalue"))
    net_cols = _column_candidates(working, ("net_value", "net_purchase", "net_sales", "netvalue", "net"))

    fii_row = None
    dii_row = None
    for _, row in working.iterrows():
        row_text = " ".join(str(value) for value in row.tolist() if str(value).strip())
        if not row_text:
            continue
        target = None
        if _is_fii_row(row_text):
            target = "FII"
        elif _is_dii_row(row_text):
            target = "DII"
        if target is None:
            continue

        numerics = _numeric_sequence(row)
        extracted = {
            "date": _parse_date(_first_from_columns(row, date_cols)),
            "buy": _numeric_from_columns(row, buy_cols),
            "sell": _numeric_from_columns(row, sell_cols),
            "net": _numeric_from_columns(row, net_cols),
        }
        if extracted["buy"] is None and len(numerics) >= 3:
            extracted["buy"] = numerics[-3]
        if extracted["sell"] is None and len(numerics) >= 2:
            extracted["sell"] = numerics[-2]
        if extracted["net"] is None and len(numerics) >= 1:
            extracted["net"] = numerics[-1]

        if target == "FII":
            fii_row = extracted
        elif target == "DII":
            dii_row = extracted

    return fii_row, dii_row


def parse_cash_flow_frames(frames: Iterable[pd.DataFrame], *, source: str, source_timestamp=None) -> dict:
    """Parse NSE/BSE-style FII/DII cash-flow tables into the canonical row."""
    source_ts = source_timestamp or _now_ist()
    source_ts_text = _coerce_source_timestamp(source_ts)
    for frame in frames:
        fii_row, dii_row = _extract_cash_rows_from_frame(frame)
        if not fii_row or not dii_row:
            continue
        flow_date = fii_row.get("date") or dii_row.get("date")
        if not flow_date:
            continue
        return {
            "date": flow_date,
            "fii_cash_net": fii_row.get("net"),
            "dii_cash_net": dii_row.get("net"),
            "fii_index_futures_net": None,
            "fii_index_options_net": None,
            "source": source,
            "source_timestamp": source_ts_text,
            "unit": "INR_CR",
            "fii_cash_buy": fii_row.get("buy"),
            "fii_cash_sell": fii_row.get("sell"),
            "dii_cash_buy": dii_row.get("buy"),
            "dii_cash_sell": dii_row.get("sell"),
        }
    raise ValueError("no_fii_dii_cash_table_found")


def _coerce_source_timestamp(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        parsed = _now_ist()
    return parsed.tz_convert(IST_TIMEZONE).isoformat()


def _json_frames(payload) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    if payload is None:
        return frames
    if isinstance(payload, list):
        try:
            frames.append(pd.DataFrame(payload))
        except Exception:
            pass
        for item in payload:
            frames.extend(_json_frames(item))
        return frames
    if isinstance(payload, dict):
        if payload:
            try:
                frames.append(pd.DataFrame([payload]))
            except Exception:
                pass
        for value in payload.values():
            frames.extend(_json_frames(value))
    return frames


def _read_html_tables(html_text: str) -> list[pd.DataFrame]:
    if not html_text:
        return []
    try:
        return list(pd.read_html(StringIO(html_text)))
    except Exception:
        return []


def parse_cash_flow_text(text: str, *, source: str, source_timestamp=None) -> dict:
    """Parse rendered exchange-page text when no HTML tables are available."""
    if not text:
        raise ValueError("empty_cash_flow_text")
    cleaned = html.unescape(str(text))
    cleaned = re.sub(r"<script\b.*?</script>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<style\b.*?</style>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)

    date_pat = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}-[A-Za-z]{3}-\d{2,4})"
    number_pat = r"[-+]?\(?\d[\d,]*(?:\.\d+)?\)?"
    row_pat = re.compile(
        rf"(FII\s*/\s*FPI|FII/FPI|FII|DII)\s+({date_pat})\s+({number_pat})\s+({number_pat})\s+({number_pat})",
        flags=re.IGNORECASE,
    )

    rows = []
    for match in row_pat.finditer(cleaned):
        rows.append(
            {
                "Category": match.group(1).upper().replace(" ", ""),
                "Date": match.group(2),
                "Buy Value": match.group(3),
                "Sale Value": match.group(4),
                "Net Value": match.group(5),
            }
        )
    if not rows:
        raise ValueError("no_fii_dii_cash_text_found")
    return parse_cash_flow_frames([pd.DataFrame(rows)], source=source, source_timestamp=source_timestamp)


def _nse_session(session=None, *, timeout: float = 15.0):
    sess = session or requests.Session()
    sess.headers.update(_base_headers(referer=NSE_HOME_PAGE))
    for url in (NSE_HOME_PAGE, NSE_REPORT_PAGE):
        try:
            sess.get(url, headers=_base_headers(referer=NSE_HOME_PAGE), timeout=timeout)
        except Exception:
            continue
    return sess


def fetch_nse_institutional_flow(*, session=None, timeout: float = 15.0, source_timestamp=None) -> InstitutionalFlowFetch:
    """Fetch the latest NSE FII/DII cash-flow payload."""
    sess = _nse_session(session, timeout=timeout)
    warnings: list[str] = []
    try:
        response = sess.get(
            NSE_FII_DII_API,
            headers=_base_headers(referer=NSE_REPORT_PAGE),
            timeout=timeout,
        )
        if response.status_code == 200:
            frames = _json_frames(response.json())
            row = parse_cash_flow_frames(
                frames,
                source="NSE_FII_DII_CASH",
                source_timestamp=source_timestamp,
            )
            return InstitutionalFlowFetch(source="NSE", row=row, warnings=warnings, raw_url=NSE_FII_DII_API)
        warnings.append(f"nse_api_http_{response.status_code}")
    except Exception as exc:
        warnings.append(f"nse_api_failed:{exc}")

    try:
        response = sess.get(
            NSE_REPORT_PAGE,
            headers=_base_headers(referer=NSE_HOME_PAGE),
            timeout=timeout,
        )
        if response.status_code != 200:
            return InstitutionalFlowFetch(
                source="NSE",
                warnings=warnings,
                issues=[f"nse_report_page_http_{response.status_code}"],
                raw_url=NSE_REPORT_PAGE,
            )
        try:
            row = parse_cash_flow_frames(
                _read_html_tables(response.text),
                source="NSE_FII_DII_CASH",
                source_timestamp=source_timestamp,
            )
        except Exception:
            row = parse_cash_flow_text(
                response.text,
                source="NSE_FII_DII_CASH",
                source_timestamp=source_timestamp,
            )
        return InstitutionalFlowFetch(source="NSE", row=row, warnings=warnings, raw_url=NSE_REPORT_PAGE)
    except Exception as exc:
        return InstitutionalFlowFetch(
            source="NSE",
            warnings=warnings,
            issues=[f"nse_parse_failed:{exc}"],
            raw_url=NSE_REPORT_PAGE,
        )


def fetch_bse_institutional_flow(*, session=None, timeout: float = 15.0, source_timestamp=None) -> InstitutionalFlowFetch:
    """Fetch the latest BSE category-wise institutional cash-flow table."""
    sess = session or requests.Session()
    urls = (BSE_CATEGORYWISE_TURNOVER_URL, BSE_CLIENT_CATEGORY_URL, BSE_ARCHIVE_CATEGORY_URL)
    warnings: list[str] = []
    for url in urls:
        try:
            response = sess.get(
                url,
                headers=_base_headers(referer="https://www.bseindia.com/"),
                timeout=timeout,
            )
            if response.status_code != 200:
                warnings.append(f"{url}:http_{response.status_code}")
                continue
            try:
                row = parse_cash_flow_frames(
                    _read_html_tables(response.text),
                    source="BSE_COMBINED_CASH",
                    source_timestamp=source_timestamp,
                )
            except Exception:
                row = parse_cash_flow_text(
                    response.text,
                    source="BSE_COMBINED_CASH",
                    source_timestamp=source_timestamp,
                )
            return InstitutionalFlowFetch(source="BSE", row=row, warnings=warnings, raw_url=url)
        except Exception as exc:
            warnings.append(f"{url}:parse_failed:{exc}")
            continue
    return InstitutionalFlowFetch(
        source="BSE",
        warnings=warnings,
        issues=["bse_no_parseable_institutional_flow_rows"],
        raw_url=BSE_CATEGORYWISE_TURNOVER_URL,
    )


def fetch_institutional_flows(
    *,
    sources: Iterable[str] = ("NSE", "BSE"),
    timeout: float = 15.0,
    source_timestamp=None,
    agreement_tolerance_cr: float = 2.0,
) -> dict:
    """Fetch all requested sources, select the first successful one, and cross-check the rest."""
    normalized_sources = [str(source).upper().strip() for source in sources if str(source).strip()]
    if not normalized_sources:
        normalized_sources = ["NSE", "BSE"]

    results: dict[str, InstitutionalFlowFetch] = {}
    for source in normalized_sources:
        if source == "NSE":
            results[source] = fetch_nse_institutional_flow(timeout=timeout, source_timestamp=source_timestamp)
        elif source == "BSE":
            results[source] = fetch_bse_institutional_flow(timeout=timeout, source_timestamp=source_timestamp)
        else:
            results[source] = InstitutionalFlowFetch(source=source, issues=[f"unsupported_source:{source}"])

    selected_source = next((source for source in normalized_sources if results[source].row is not None), None)
    selected_row = dict(results[selected_source].row) if selected_source else None
    crosscheck = _build_crosscheck(selected_row, results, agreement_tolerance_cr=agreement_tolerance_cr)
    if selected_row:
        selected_row.update(crosscheck)

    return {
        "selected_source": selected_source,
        "selected_row": selected_row,
        "results": {
            source: {
                "ok": result.ok,
                "row": result.row,
                "warnings": result.warnings,
                "issues": result.issues,
                "raw_url": result.raw_url,
            }
            for source, result in results.items()
        },
    }


def _build_crosscheck(selected_row: dict | None, results: dict[str, InstitutionalFlowFetch], *, agreement_tolerance_cr: float) -> dict:
    rows = {source: result.row for source, result in results.items() if result.row is not None}
    out = {
        "crosscheck_status": "NO_SOURCE",
        "crosscheck_max_abs_diff": None,
        "crosscheck_sources": ",".join(rows.keys()),
        "nse_fii_cash_net": rows.get("NSE", {}).get("fii_cash_net") if rows.get("NSE") else None,
        "nse_dii_cash_net": rows.get("NSE", {}).get("dii_cash_net") if rows.get("NSE") else None,
        "bse_fii_cash_net": rows.get("BSE", {}).get("fii_cash_net") if rows.get("BSE") else None,
        "bse_dii_cash_net": rows.get("BSE", {}).get("dii_cash_net") if rows.get("BSE") else None,
    }
    if not selected_row:
        return out
    if len(rows) < 2:
        out["crosscheck_status"] = "SINGLE_SOURCE"
        return out

    dates = {row.get("date") for row in rows.values()}
    diffs = []
    for field in ("fii_cash_net", "dii_cash_net"):
        values = [row.get(field) for row in rows.values() if row.get(field) is not None]
        if len(values) >= 2:
            diffs.append(max(values) - min(values))
    max_abs_diff = max((abs(value) for value in diffs), default=0.0)
    out["crosscheck_max_abs_diff"] = max_abs_diff
    if len(dates) > 1:
        out["crosscheck_status"] = "DATE_MISMATCH"
    elif max_abs_diff <= float(agreement_tolerance_cr):
        out["crosscheck_status"] = "AGREE"
    else:
        out["crosscheck_status"] = "NET_MISMATCH"
    return out


def upsert_institutional_flow_row(row: dict, *, path: str | Path = DEFAULT_FLOW_PATH) -> Path:
    """Upsert one canonical institutional-flow row into the local CSV store."""
    if not row:
        raise ValueError("row is required")
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing = pd.DataFrame()
    if output_path.exists():
        existing = pd.read_csv(output_path)

    incoming = pd.DataFrame([row])
    frame = pd.concat([existing, incoming], ignore_index=True, sort=False)

    for column in STANDARD_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    for field in FLOW_FIELDS:
        if field not in frame.columns:
            frame[field] = None

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

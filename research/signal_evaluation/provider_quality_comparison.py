"""Compare stored option-chain quality across data providers.

This report is intentionally offline/research-only. It reads already persisted
option-chain snapshots, validates each provider with the normal chain-quality
checks, pairs near-synchronous snapshots, and summarizes whether a provider is
better suited for analytics, execution, or neither.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from config.market_data_policy import IST_TIMEZONE
from data.iv_validation_enrichment import (
    attach_iv_validation_diagnostics,
    build_iv_validation_frame,
)
from data.option_chain_validation import _resolve_column_name, validate_option_chain
from data.replay_loader import load_option_chain_snapshot, load_spot_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPTION_SNAPSHOT_DIR = PROJECT_ROOT / "debug_samples" / "option_chain_snapshots"
DEFAULT_SPOT_SNAPSHOT_DIR = PROJECT_ROOT / "debug_samples" / "spot_snapshots"
REPORT_DIR = PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "provider_quality_comparison"

OPTION_SNAPSHOT_RE = re.compile(
    r"^(?P<symbol>.+?)_(?P<source>[A-Za-z0-9]+)_option_chain_snapshot_(?P<timestamp>.+)\.csv$"
)
SPOT_SNAPSHOT_RE = re.compile(r"^(?P<symbol>.+?)_spot_snapshot_(?P<timestamp>.+)\.json$")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True, default=_json_default))


def _atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        frame.to_csv(tmp_path, index=False)
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _parse_snapshot_timestamp(token: str) -> pd.Timestamp | None:
    text = str(token or "").strip()
    if not text:
        return None
    if "T" in text:
        date_part, time_part = text.split("T", 1)
        time_part = re.sub(r"^(\d{2})-(\d{2})-(\d{2})(.*)$", r"\1:\2:\3\4", time_part)
        time_part = re.sub(r"([+-]\d{2})-(\d{2})$", r"\1:\2", time_part)
        text = f"{date_part}T{time_part}"
    try:
        ts = pd.Timestamp(text)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize(IST_TIMEZONE)
    return ts.tz_convert(IST_TIMEZONE)


def _rel(path: Path | str | None) -> str | None:
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(path)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(number):
        return default
    return number


def _safe_int(value: Any, default: int = 0) -> int:
    number = _safe_float(value)
    if number is None:
        return default
    return int(number)


def _discover_option_snapshots(
    *,
    snapshot_dir: Path,
    symbol: str,
    sources: tuple[str, ...],
    session_date: str | None = None,
) -> list[dict[str, Any]]:
    symbol_clean = str(symbol or "").upper().strip()
    source_set = {str(source).upper().strip() for source in sources}
    records: list[dict[str, Any]] = []
    if not snapshot_dir.exists():
        return records

    for path in sorted(snapshot_dir.glob("*.csv")):
        match = OPTION_SNAPSHOT_RE.match(path.name)
        if not match:
            continue
        file_symbol = match.group("symbol").upper().strip()
        source = match.group("source").upper().strip()
        if file_symbol != symbol_clean or source not in source_set:
            continue
        timestamp = _parse_snapshot_timestamp(match.group("timestamp"))
        if timestamp is None:
            continue
        if session_date and timestamp.date().isoformat() != str(session_date):
            continue
        records.append(
            {
                "symbol": file_symbol,
                "source": source,
                "timestamp": timestamp,
                "path": path,
            }
        )
    return records


def _discover_spot_snapshots(*, spot_dir: Path, symbol: str, session_date: str | None = None) -> list[dict[str, Any]]:
    symbol_clean = str(symbol or "").upper().strip()
    records: list[dict[str, Any]] = []
    if not spot_dir.exists():
        return records

    for path in sorted(spot_dir.glob("*.json")):
        match = SPOT_SNAPSHOT_RE.match(path.name)
        if not match or match.group("symbol").upper().strip() != symbol_clean:
            continue
        timestamp = _parse_snapshot_timestamp(match.group("timestamp"))
        if timestamp is None:
            continue
        if session_date and timestamp.date().isoformat() != str(session_date):
            continue
        records.append({"symbol": symbol_clean, "timestamp": timestamp, "path": path})
    return records


def _find_nearest_spot(
    timestamp: pd.Timestamp,
    spot_records: list[dict[str, Any]],
    *,
    max_seconds: int,
) -> dict[str, Any] | None:
    if not spot_records:
        return None
    best = min(
        spot_records,
        key=lambda record: abs((record["timestamp"] - timestamp).total_seconds()),
    )
    delta = abs((best["timestamp"] - timestamp).total_seconds())
    if delta > max_seconds:
        return None
    return best


def _load_spot_value(record: dict[str, Any] | None) -> float | None:
    if not record:
        return None
    try:
        payload = load_spot_snapshot(str(record["path"]))
    except Exception:
        return None
    return _safe_float(payload.get("spot"))


def _numeric_series(frame: pd.DataFrame, canonical: str) -> pd.Series:
    column = _resolve_column_name(frame, canonical)
    if column is None:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _text_series(frame: pd.DataFrame, canonical: str) -> pd.Series:
    column = _resolve_column_name(frame, canonical)
    if column is None:
        return pd.Series(dtype="object")
    return frame[column].astype(str).str.upper().str.strip()


def _top_oi_by_side(frame: pd.DataFrame, side: str) -> float | None:
    strike = _numeric_series(frame, "strikePrice")
    oi = _numeric_series(frame, "openInterest")
    option_type = _text_series(frame, "OPTION_TYP")
    if strike.empty or oi.empty or option_type.empty:
        return None
    work = pd.DataFrame({"strike": strike, "oi": oi, "option_type": option_type})
    side_rows = work[work["option_type"].eq(side) & work["strike"].notna() & work["oi"].notna()]
    if side_rows.empty:
        return None
    grouped = side_rows.groupby("strike", as_index=False)["oi"].sum()
    grouped = grouped.sort_values(["oi", "strike"], ascending=[False, True], kind="mergesort")
    return _safe_float(grouped.iloc[0]["strike"])


def _profile_snapshot(
    record: dict[str, Any],
    *,
    spot_records: list[dict[str, Any]],
    spot_tolerance_seconds: int,
) -> dict[str, Any]:
    source = str(record.get("source") or "").upper().strip()
    timestamp = record["timestamp"]
    spot_record = _find_nearest_spot(timestamp, spot_records, max_seconds=spot_tolerance_seconds)
    spot = _load_spot_value(spot_record)

    error = None
    try:
        frame = load_option_chain_snapshot(str(record["path"]))
        validation_frame, iv_validation_diagnostics = build_iv_validation_frame(
            frame,
            spot=spot,
            valuation_time=timestamp,
        )
        validation = validate_option_chain(validation_frame, spot=spot, as_of=timestamp)
        validation = attach_iv_validation_diagnostics(validation, iv_validation_diagnostics)
    except Exception as exc:
        frame = pd.DataFrame()
        validation = {}
        error = f"{type(exc).__name__}: {exc}"

    provider_health = validation.get("provider_health") if isinstance(validation.get("provider_health"), dict) else {}
    tradable_data = validation.get("tradable_data") if isinstance(validation.get("tradable_data"), dict) else {}

    return {
        "symbol": record.get("symbol"),
        "source": source,
        "timestamp": timestamp.isoformat(),
        "session_date": timestamp.date().isoformat(),
        "path": _rel(record.get("path")),
        "spot": spot,
        "spot_path": _rel(spot_record.get("path")) if spot_record else None,
        "spot_delta_seconds": (
            round(abs((spot_record["timestamp"] - timestamp).total_seconds()), 3)
            if spot_record
            else None
        ),
        "load_error": error,
        "row_count": _safe_int(validation.get("row_count"), len(frame)),
        "strike_count": _safe_int(validation.get("strike_count")),
        "ce_rows": _safe_int(validation.get("ce_rows")),
        "pe_rows": _safe_int(validation.get("pe_rows")),
        "priced_ratio": _safe_float(validation.get("priced_ratio")),
        "quoted_ratio": _safe_float(validation.get("quoted_ratio")),
        "bid_present_rows": _safe_int(validation.get("bid_present_rows")),
        "ask_present_rows": _safe_int(validation.get("ask_present_rows")),
        "one_sided_quote_rows": _safe_int(validation.get("one_sided_quote_rows")),
        "effective_priced_ratio": _safe_float(validation.get("effective_priced_ratio")),
        "iv_ratio": _safe_float(validation.get("iv_ratio")),
        "iv_validation_source": validation.get("iv_validation_source"),
        "raw_positive_iv_rows": _safe_int(validation.get("raw_positive_iv_rows")),
        "validation_positive_iv_rows": _safe_int(validation.get("validation_positive_iv_rows")),
        "model_derived_iv_applied": bool(validation.get("model_derived_iv_applied")) if validation else False,
        "paired_strike_ratio": _safe_float(validation.get("paired_strike_ratio")),
        "is_valid": bool(validation.get("is_valid")) if validation else False,
        "is_stale": bool(validation.get("is_stale")) if validation else False,
        "analytics_usable": bool(validation.get("analytics_usable")) if validation else False,
        "execution_suggestion_usable": bool(validation.get("execution_suggestion_usable")) if validation else False,
        "warnings": "|".join(str(item) for item in validation.get("warnings", []) or []),
        "issues": "|".join(str(item) for item in validation.get("issues", []) or []),
        "provider_health_summary": provider_health.get("summary_status"),
        "row_health": provider_health.get("row_health"),
        "pricing_health": provider_health.get("pricing_health"),
        "trade_price_health": provider_health.get("trade_price_health"),
        "quote_health": provider_health.get("quote_health"),
        "pairing_health": provider_health.get("pairing_health"),
        "iv_health": provider_health.get("iv_health"),
        "core_marketability_health": provider_health.get("core_marketability_health"),
        "core_pairing_health": provider_health.get("core_pairing_health"),
        "core_iv_health": provider_health.get("core_iv_health"),
        "core_quote_integrity_health": provider_health.get("core_quote_integrity_health"),
        "atm_iv_health": provider_health.get("atm_iv_health"),
        "atm_iv_midpoint": _safe_float(provider_health.get("atm_iv_midpoint")),
        "iv_parity_health": provider_health.get("iv_parity_health"),
        "iv_staleness_health": provider_health.get("iv_staleness_health"),
        "quote_freshness_health": provider_health.get("quote_freshness_health"),
        "quote_spread_health": provider_health.get("quote_spread_health"),
        "liquidity_coverage_health": provider_health.get("liquidity_coverage_health"),
        "readiness_score": _safe_float(provider_health.get("market_data_readiness_score")),
        "readiness_tier": provider_health.get("market_data_readiness_tier"),
        "trade_blocking_status": provider_health.get("trade_blocking_status"),
        "trade_blocking_reasons": "|".join(str(item) for item in provider_health.get("trade_blocking_reasons", []) or []),
        "tradable_data_status": tradable_data.get("status"),
        "tradable_data_score": _safe_float(tradable_data.get("score")),
        "top_call_oi_strike": _top_oi_by_side(frame, "CE"),
        "top_put_oi_strike": _top_oi_by_side(frame, "PE"),
    }


def _score_profile(profile: dict[str, Any], *, purpose: str) -> float:
    score = _safe_float(profile.get("readiness_score"), 0.0) or 0.0
    if profile.get("is_valid"):
        score += 5.0
    if purpose == "analytics":
        if profile.get("analytics_usable"):
            score += 15.0
        if str(profile.get("provider_health_summary") or "").upper() == "WEAK":
            score -= 8.0
        if str(profile.get("core_iv_health") or "").upper() == "WEAK":
            score -= 8.0
        if str(profile.get("pairing_health") or "").upper() == "WEAK":
            score -= 8.0
    else:
        if profile.get("execution_suggestion_usable"):
            score += 20.0
        if str(profile.get("trade_blocking_status") or "").upper() == "BLOCK":
            score -= 25.0
        quote_ratio = _safe_float(profile.get("quoted_ratio"), 0.0) or 0.0
        score += min(quote_ratio * 20.0, 20.0)
        one_sided = _safe_float(profile.get("one_sided_quote_rows"), 0.0) or 0.0
        rows = max(_safe_float(profile.get("row_count"), 1.0) or 1.0, 1.0)
        score -= min((one_sided / rows) * 20.0, 20.0)
    return round(score, 4)


def _pick_preferred(left: dict[str, Any], right: dict[str, Any], *, purpose: str) -> str:
    left_score = _score_profile(left, purpose=purpose)
    right_score = _score_profile(right, purpose=purpose)
    if abs(left_score - right_score) < 3.0:
        return "TIE"
    return str(left.get("source") if left_score > right_score else right.get("source"))


def _pair_profiles(
    profiles: list[dict[str, Any]],
    *,
    sources: tuple[str, str],
    max_pair_seconds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    first_source, second_source = (source.upper().strip() for source in sources)
    first = sorted([p for p in profiles if p.get("source") == first_source], key=lambda p: p["timestamp"])
    second = sorted([p for p in profiles if p.get("source") == second_source], key=lambda p: p["timestamp"])
    unused_second = set(range(len(second)))
    pairs: list[dict[str, Any]] = []
    paired_paths: set[str] = set()

    for left in first:
        left_ts = pd.Timestamp(left["timestamp"])
        best_idx = None
        best_delta = None
        for idx in list(unused_second):
            right_ts = pd.Timestamp(second[idx]["timestamp"])
            delta = abs((right_ts - left_ts).total_seconds())
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_idx = idx
        if best_idx is None or best_delta is None or best_delta > max_pair_seconds:
            continue
        right = second[best_idx]
        left_ts = pd.Timestamp(left["timestamp"])
        right_ts = pd.Timestamp(right["timestamp"])
        right_after_left = max((right_ts - left_ts).total_seconds(), 0.0)
        left_after_right = max((left_ts - right_ts).total_seconds(), 0.0)
        unused_second.remove(best_idx)
        paired_paths.add(str(left.get("path")))
        paired_paths.add(str(right.get("path")))
        call_gap = None
        put_gap = None
        if left.get("top_call_oi_strike") is not None and right.get("top_call_oi_strike") is not None:
            call_gap = round(float(right["top_call_oi_strike"]) - float(left["top_call_oi_strike"]), 4)
        if left.get("top_put_oi_strike") is not None and right.get("top_put_oi_strike") is not None:
            put_gap = round(float(right["top_put_oi_strike"]) - float(left["top_put_oi_strike"]), 4)
        pairs.append(
            {
                "left_source": first_source,
                "right_source": second_source,
                "left_timestamp": left["timestamp"],
                "right_timestamp": right["timestamp"],
                "pair_delta_seconds": round(float(best_delta), 3),
                "right_after_left_seconds": round(float(right_after_left), 3),
                "left_after_right_seconds": round(float(left_after_right), 3),
                "research_only": True,
                "causal_replay_eligible": bool(right_after_left == 0.0),
                "pairing_note": (
                    "offline_near_sync_research_pair"
                    if right_after_left == 0.0
                    else "offline_near_sync_research_pair_right_after_left"
                ),
                "analytics_preferred_source": _pick_preferred(left, right, purpose="analytics"),
                "execution_preferred_source": _pick_preferred(left, right, purpose="execution"),
                "left_readiness_score": left.get("readiness_score"),
                "right_readiness_score": right.get("readiness_score"),
                "readiness_delta_right_minus_left": (
                    round(float(right["readiness_score"]) - float(left["readiness_score"]), 4)
                    if right.get("readiness_score") is not None and left.get("readiness_score") is not None
                    else None
                ),
                "left_analytics_usable": left.get("analytics_usable"),
                "right_analytics_usable": right.get("analytics_usable"),
                "left_execution_usable": left.get("execution_suggestion_usable"),
                "right_execution_usable": right.get("execution_suggestion_usable"),
                "left_quoted_ratio": left.get("quoted_ratio"),
                "right_quoted_ratio": right.get("quoted_ratio"),
                "left_one_sided_quote_rows": left.get("one_sided_quote_rows"),
                "right_one_sided_quote_rows": right.get("one_sided_quote_rows"),
                "left_provider_health_summary": left.get("provider_health_summary"),
                "right_provider_health_summary": right.get("provider_health_summary"),
                "left_trade_blocking_status": left.get("trade_blocking_status"),
                "right_trade_blocking_status": right.get("trade_blocking_status"),
                "top_call_oi_strike_gap_right_minus_left": call_gap,
                "top_put_oi_strike_gap_right_minus_left": put_gap,
            }
        )

    unpaired = [profile for profile in profiles if str(profile.get("path")) not in paired_paths]
    return pairs, unpaired


def _source_summary(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, group in pd.DataFrame(profiles).groupby("source", dropna=False):
        rows.append(
            {
                "source": source,
                "snapshots": int(len(group)),
                "analytics_usable_share": round(float(group["analytics_usable"].mean()), 4) if len(group) else None,
                "execution_usable_share": round(float(group["execution_suggestion_usable"].mean()), 4) if len(group) else None,
                "avg_readiness_score": round(float(pd.to_numeric(group["readiness_score"], errors="coerce").mean()), 4),
                "avg_quoted_ratio": round(float(pd.to_numeric(group["quoted_ratio"], errors="coerce").mean()), 4),
                "avg_effective_priced_ratio": round(float(pd.to_numeric(group["effective_priced_ratio"], errors="coerce").mean()), 4),
                "avg_one_sided_quote_rows": round(float(pd.to_numeric(group["one_sided_quote_rows"], errors="coerce").mean()), 4),
                "provider_health_counts": dict(Counter(group["provider_health_summary"].fillna("UNKNOWN").astype(str))),
                "trade_blocking_counts": dict(Counter(group["trade_blocking_status"].fillna("UNKNOWN").astype(str))),
            }
        )
    return rows


def _render_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["_No rows._"]
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, float):
                value = round(value, 4)
            values.append("" if value is None else str(value))
        out.append("| " + " | ".join(values) + " |")
    return out


def _build_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Provider Quality Comparison",
        "",
        f"Generated: {report['generated_at']}",
        f"Symbol: `{report['symbol']}`",
        f"Session date: `{report.get('session_date') or 'ALL'}`",
        f"Sources: `{', '.join(report['sources'])}`",
        "",
        "## Summary",
        "",
        f"- Snapshot profiles: {len(report['snapshot_profiles'])}",
        f"- Paired comparisons: {len(report['paired_comparisons'])}",
        f"- Unpaired snapshots: {len(report['unpaired_snapshots'])}",
        f"- Scope: `{report.get('comparison_scope', 'OFFLINE_RESEARCH_ONLY')}`",
        "",
        "This report is an offline provider-quality artifact. It does not select or override the live decision provider.",
        "",
    ]
    lines.extend(
        _render_table(
            report["source_summary"],
            [
                "source",
                "snapshots",
                "analytics_usable_share",
                "execution_usable_share",
                "avg_readiness_score",
                "avg_quoted_ratio",
                "avg_one_sided_quote_rows",
            ],
        )
    )
    lines.extend(["", "## Pair Preferences", ""])
    preference_counts = report.get("pair_preference_counts", {})
    lines.append(f"- Analytics preference counts: `{preference_counts.get('analytics', {})}`")
    lines.append(f"- Execution preference counts: `{preference_counts.get('execution', {})}`")
    lines.extend(["", "## Paired Snapshot Detail", ""])
    lines.extend(
        _render_table(
            report["paired_comparisons"][:50],
            [
                "left_timestamp",
                "pair_delta_seconds",
                "causal_replay_eligible",
                "analytics_preferred_source",
                "execution_preferred_source",
                "left_readiness_score",
                "right_readiness_score",
                "left_execution_usable",
                "right_execution_usable",
                "top_call_oi_strike_gap_right_minus_left",
                "top_put_oi_strike_gap_right_minus_left",
            ],
        )
    )
    lines.extend(["", "## Operating Read", ""])
    if not report["paired_comparisons"]:
        lines.append("- No near-synchronous provider pairs found. Tomorrow, run both providers close enough in time to compare them.")
    else:
        lines.append("- Use analytics-preferred source for directional research only if analytics usability is stable and OI/strike alignment is not contradictory.")
        lines.append("- Use execution-preferred source for tradeability only if execution usability and quote coverage are materially better.")
        lines.append("- If one provider is analytics-preferred and the other is execution-preferred, keep that as a split-provider research hypothesis until fresh-forward evidence confirms it.")
    lines.append("")
    return "\n".join(lines)


def build_provider_quality_comparison(
    *,
    symbol: str = "NIFTY",
    sources: tuple[str, str] = ("ICICI", "ZERODHA"),
    session_date: str | None = None,
    option_snapshot_dir: Path = DEFAULT_OPTION_SNAPSHOT_DIR,
    spot_snapshot_dir: Path = DEFAULT_SPOT_SNAPSHOT_DIR,
    max_pair_seconds: int = 180,
    spot_tolerance_seconds: int = 600,
    max_snapshots_per_source: int | None = None,
) -> dict[str, Any]:
    sources = tuple(str(source).upper().strip() for source in sources if str(source or "").strip())
    if len(sources) != 2:
        raise ValueError("Provider comparison requires exactly two sources.")

    option_records = _discover_option_snapshots(
        snapshot_dir=Path(option_snapshot_dir),
        symbol=symbol,
        sources=sources,
        session_date=session_date,
    )
    if max_snapshots_per_source:
        trimmed: list[dict[str, Any]] = []
        for source in sources:
            source_records = [record for record in option_records if record["source"] == source]
            trimmed.extend(source_records[-int(max_snapshots_per_source) :])
        option_records = sorted(trimmed, key=lambda record: record["timestamp"])

    spot_records = _discover_spot_snapshots(
        spot_dir=Path(spot_snapshot_dir),
        symbol=symbol,
        session_date=session_date,
    )
    profiles = [
        _profile_snapshot(
            record,
            spot_records=spot_records,
            spot_tolerance_seconds=spot_tolerance_seconds,
        )
        for record in option_records
    ]
    pairs, unpaired = _pair_profiles(profiles, sources=sources, max_pair_seconds=max_pair_seconds)
    preference_counts = {
        "analytics": dict(Counter(pair["analytics_preferred_source"] for pair in pairs)),
        "execution": dict(Counter(pair["execution_preferred_source"] for pair in pairs)),
    }
    return {
        "generated_at": pd.Timestamp.now(tz=IST_TIMEZONE).isoformat(),
        "symbol": str(symbol).upper().strip(),
        "sources": list(sources),
        "session_date": session_date,
        "comparison_scope": "OFFLINE_RESEARCH_ONLY",
        "live_decision_policy": "primary source remains the only live decision source; secondary sources are research-only evidence",
        "option_snapshot_dir": _rel(option_snapshot_dir),
        "spot_snapshot_dir": _rel(spot_snapshot_dir),
        "max_pair_seconds": max_pair_seconds,
        "spot_tolerance_seconds": spot_tolerance_seconds,
        "snapshot_profiles": profiles,
        "paired_comparisons": pairs,
        "unpaired_snapshots": unpaired,
        "source_summary": _source_summary(profiles) if profiles else [],
        "pair_preference_counts": preference_counts,
    }


def write_provider_quality_comparison_report(
    report: dict[str, Any],
    *,
    output_dir: Path | None = REPORT_DIR,
) -> dict[str, str]:
    output_dir = Path(output_dir or REPORT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = pd.Timestamp.now(tz=IST_TIMEZONE).strftime("%Y%m%d_%H%M%S_%f")
    md_path = output_dir / f"provider_quality_comparison_{run_id}.md"
    json_path = output_dir / f"provider_quality_comparison_{run_id}.json"
    profiles_path = output_dir / f"provider_quality_profiles_{run_id}.csv"
    pairs_path = output_dir / f"provider_quality_pairs_{run_id}.csv"

    _atomic_write_text(md_path, _build_markdown(report))
    _atomic_write_json(json_path, report)
    _atomic_write_csv(profiles_path, pd.DataFrame(report.get("snapshot_profiles") or []))
    _atomic_write_csv(pairs_path, pd.DataFrame(report.get("paired_comparisons") or []))

    latest_md = output_dir / "latest_provider_quality_comparison.md"
    latest_json = output_dir / "latest_provider_quality_comparison.json"
    latest_profiles = output_dir / "latest_provider_quality_profiles.csv"
    latest_pairs = output_dir / "latest_provider_quality_pairs.csv"
    _atomic_write_text(latest_md, _build_markdown(report))
    _atomic_write_json(latest_json, report)
    _atomic_write_csv(latest_profiles, pd.DataFrame(report.get("snapshot_profiles") or []))
    _atomic_write_csv(latest_pairs, pd.DataFrame(report.get("paired_comparisons") or []))

    return {
        "markdown": str(md_path),
        "json": str(json_path),
        "profiles_csv": str(profiles_path),
        "pairs_csv": str(pairs_path),
        "latest_markdown": str(latest_md),
        "latest_json": str(latest_json),
        "latest_profiles_csv": str(latest_profiles),
        "latest_pairs_csv": str(latest_pairs),
    }

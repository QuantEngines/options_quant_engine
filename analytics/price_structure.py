"""
Module: price_structure.py

Purpose:
    Build display and research features for intraday price-structure context.

Role in the System:
    Part of the analytics layer. The helpers in this module are intentionally
    signal-neutral: they expose trader-facing context and point-in-time research
    fields, but they do not change trade decisions.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import pandas as pd

from config.market_data_policy import IST_TIMEZONE
from data.spot_history import load_spot_history


OPENING_RANGE_WINDOWS_MINUTES = (5, 15, 30)
FIBONACCI_RETRACEMENT_RATIOS = (
    (0.000, "fib_0.0"),
    (0.236, "fib_23.6"),
    (0.382, "fib_38.2"),
    (0.500, "fib_50.0"),
    (0.618, "fib_61.8"),
    (0.786, "fib_78.6"),
    (1.000, "fib_100.0"),
)
PRIOR_HIGH_KEYS = (
    "prior_session_high",
    "previous_session_high",
    "prev_session_high",
    "prior_high",
    "previous_high",
    "prev_high",
)
PRIOR_LOW_KEYS = (
    "prior_session_low",
    "previous_session_low",
    "prev_session_low",
    "prior_low",
    "previous_low",
    "prev_low",
)
PRIOR_CLOSE_KEYS = (
    "prior_session_close",
    "previous_session_close",
    "prev_session_close",
    "prior_close",
    "previous_close",
    "prev_close",
)
PRIOR_DATE_KEYS = (
    "prior_session_date",
    "previous_session_date",
    "prev_session_date",
    "prior_date",
    "previous_date",
)


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return None
    return resolved if math.isfinite(resolved) else None


def _coerce_ist_timestamp(value: Any):
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        if ts.tzinfo is None:
            return ts.tz_localize(IST_TIMEZONE)
        return ts.tz_convert(IST_TIMEZONE)
    except Exception:
        return None


def _round_or_none(value: Any, digits: int = 4):
    value_f = _safe_float(value)
    if value_f is None:
        return None
    return round(value_f, digits)


def _signed_distance(level: Any, spot: Any) -> tuple[float | None, float | None]:
    level_f = _safe_float(level)
    spot_f = _safe_float(spot)
    if level_f is None or spot_f in (None, 0.0):
        return None, None
    distance_pts = level_f - spot_f
    return round(distance_pts, 4), round((distance_pts / spot_f) * 100.0, 6)


def _spot_relation_state(*, level: Any, spot: Any, label: str, tolerance_pts: float = 0.5) -> str | None:
    level_f = _safe_float(level)
    spot_f = _safe_float(spot)
    if level_f is None or spot_f is None:
        return None
    if abs(spot_f - level_f) <= tolerance_pts:
        return f"AT_{label}"
    if spot_f > level_f:
        return f"ABOVE_{label}"
    return f"BELOW_{label}"


def _opening_range_state(*, spot: Any, high: Any, low: Any, tolerance_pts: float = 0.5) -> str | None:
    spot_f = _safe_float(spot)
    high_f = _safe_float(high)
    low_f = _safe_float(low)
    if spot_f is None or high_f is None or low_f is None:
        return None
    if spot_f > high_f + tolerance_pts:
        return "ABOVE_OPENING_RANGE"
    if spot_f < low_f - tolerance_pts:
        return "BELOW_OPENING_RANGE"
    if abs(spot_f - high_f) <= tolerance_pts:
        return "AT_OPENING_RANGE_HIGH"
    if abs(spot_f - low_f) <= tolerance_pts:
        return "AT_OPENING_RANGE_LOW"
    return "INSIDE_OPENING_RANGE"


def _opening_range_sample_quality(*, status: str | None, row_count: int | None) -> str:
    status_text = str(status or "").upper().strip()
    if status_text == "UNAVAILABLE":
        return "UNAVAILABLE"
    if row_count is None or row_count <= 0:
        return "UNAVAILABLE"
    if row_count <= 1:
        return "LOW_SAMPLE"
    if row_count < 3:
        return "THIN_SAMPLE"
    return "OK"


def _session_start_for(ts: pd.Timestamp | None):
    if ts is None:
        return None
    return ts.replace(hour=9, minute=15, second=0, microsecond=0)


def _first_float(mapping: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _safe_float(mapping.get(key))
        if value is not None:
            return value
    return None


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _normalise_history_frame(history: pd.DataFrame | None, *, session_start, timestamp) -> pd.DataFrame:
    if history is None or history.empty or "timestamp" not in history.columns or "spot" not in history.columns:
        return pd.DataFrame(columns=["timestamp", "spot"])
    frame = history[["timestamp", "spot"]].copy()
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp"],
        utc=True,
        errors="coerce",
        format="mixed",
    ).dt.tz_convert(IST_TIMEZONE)
    frame["spot"] = pd.to_numeric(frame["spot"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "spot"])
    if session_start is not None:
        frame = frame[frame["timestamp"] >= session_start]
    if timestamp is not None:
        frame = frame[frame["timestamp"] <= timestamp]
    return frame.sort_values("timestamp", kind="mergesort").reset_index(drop=True)


def _prior_session_ohlc_from_spot_summary(spot_summary: dict[str, Any]) -> dict[str, Any]:
    high = _first_float(spot_summary, PRIOR_HIGH_KEYS)
    low = _first_float(spot_summary, PRIOR_LOW_KEYS)
    close = _first_float(spot_summary, PRIOR_CLOSE_KEYS)
    if high is None or low is None or close is None or high < low:
        return {}
    return {
        "prior_session_high": high,
        "prior_session_low": low,
        "prior_session_close": close,
        "prior_session_date": _string_or_none(_first_present(spot_summary, PRIOR_DATE_KEYS)),
        "prior_session_ohlc_source": "SPOT_SUMMARY_PRIOR_SESSION_OHLC",
    }


def _prior_session_ohlc_from_history(
    *,
    symbol: str,
    session_start,
    timestamp,
    loader: Callable[..., pd.DataFrame],
) -> dict[str, Any]:
    if not symbol or session_start is None or timestamp is None:
        return {}
    lookback_start = session_start - pd.Timedelta(days=7)
    prior_end = session_start - pd.Timedelta(seconds=1)
    try:
        raw_history = loader(symbol, start_ts=lookback_start, end_ts=prior_end, dedupe=True)
        history = _normalise_history_frame(raw_history, session_start=None, timestamp=prior_end)
    except Exception:
        return {}
    if history.empty:
        return {}
    history = history[history["timestamp"] < session_start]
    if history.empty:
        return {}
    history["session_date"] = history["timestamp"].dt.date
    current_date = session_start.date()
    prior_dates = sorted(date for date in history["session_date"].dropna().unique() if date < current_date)
    if not prior_dates:
        return {}
    prior_date = prior_dates[-1]
    prior_frame = history[history["session_date"] == prior_date]
    if prior_frame.empty:
        return {}
    high = _safe_float(prior_frame["spot"].max())
    low = _safe_float(prior_frame["spot"].min())
    close = _safe_float(prior_frame.sort_values("timestamp", kind="mergesort")["spot"].iloc[-1])
    if high is None or low is None or close is None or high < low:
        return {}
    return {
        "prior_session_high": high,
        "prior_session_low": low,
        "prior_session_close": close,
        "prior_session_date": str(prior_date),
        "prior_session_ohlc_source": "SPOT_HISTORY_PRIOR_SESSION_PROXY",
    }


def _resolve_prior_session_ohlc(
    *,
    symbol: str,
    spot_summary: dict[str, Any],
    session_start,
    timestamp,
    loader: Callable[..., pd.DataFrame],
) -> dict[str, Any]:
    direct = _prior_session_ohlc_from_spot_summary(spot_summary)
    if direct:
        return direct
    return _prior_session_ohlc_from_history(
        symbol=symbol,
        session_start=session_start,
        timestamp=timestamp,
        loader=loader,
    )


def _cpr_state(*, spot: Any, lower: Any, upper: Any, tolerance_pts: float = 0.5) -> str | None:
    spot_f = _safe_float(spot)
    lower_f = _safe_float(lower)
    upper_f = _safe_float(upper)
    if spot_f is None or lower_f is None or upper_f is None:
        return None
    if lower_f > upper_f:
        lower_f, upper_f = upper_f, lower_f
    if lower_f - tolerance_pts <= spot_f <= upper_f + tolerance_pts:
        return "INSIDE_CPR"
    if spot_f > upper_f:
        return "ABOVE_CPR"
    return "BELOW_CPR"


def _classic_pivot_state(
    *,
    spot: Any,
    high: Any,
    low: Any,
    close: Any,
) -> dict[str, Any]:
    high_f = _safe_float(high)
    low_f = _safe_float(low)
    close_f = _safe_float(close)
    spot_f = _safe_float(spot)
    if high_f is None or low_f is None or close_f is None or high_f < low_f:
        return {
            "prior_session_ohlc_available": False,
            "classic_pivot_available": False,
        }

    pivot = (high_f + low_f + close_f) / 3.0
    cpr_bc = (high_f + low_f) / 2.0
    cpr_tc = (2.0 * pivot) - cpr_bc
    cpr_lower = min(cpr_bc, cpr_tc)
    cpr_upper = max(cpr_bc, cpr_tc)
    day_range = high_f - low_f
    cpr_width = cpr_upper - cpr_lower
    pivot_dist_pts, pivot_dist_pct = _signed_distance(pivot, spot_f)
    cpr_lower_dist_pts, cpr_lower_dist_pct = _signed_distance(cpr_lower, spot_f)
    cpr_upper_dist_pts, cpr_upper_dist_pct = _signed_distance(cpr_upper, spot_f)

    return {
        "prior_session_ohlc_available": True,
        "classic_pivot_available": True,
        "classic_pivot": _round_or_none(pivot),
        "cpr_bc": _round_or_none(cpr_bc),
        "cpr_tc": _round_or_none(cpr_tc),
        "cpr_lower": _round_or_none(cpr_lower),
        "cpr_upper": _round_or_none(cpr_upper),
        "cpr_width_pts": _round_or_none(cpr_width),
        "cpr_width_pct": round((cpr_width / spot_f) * 100.0, 6) if spot_f not in (None, 0.0) else None,
        "pivot_r1": _round_or_none((2.0 * pivot) - low_f),
        "pivot_s1": _round_or_none((2.0 * pivot) - high_f),
        "pivot_r2": _round_or_none(pivot + day_range),
        "pivot_s2": _round_or_none(pivot - day_range),
        "pivot_r3": _round_or_none(high_f + (2.0 * (pivot - low_f))),
        "pivot_s3": _round_or_none(low_f - (2.0 * (high_f - pivot))),
        "spot_vs_pivot_state": _spot_relation_state(level=pivot, spot=spot_f, label="PIVOT"),
        "spot_vs_pivot_distance_pts": pivot_dist_pts,
        "spot_vs_pivot_distance_pct": pivot_dist_pct,
        "spot_vs_cpr_state": _cpr_state(spot=spot_f, lower=cpr_lower, upper=cpr_upper),
        "spot_vs_cpr_lower_distance_pts": cpr_lower_dist_pts,
        "spot_vs_cpr_lower_distance_pct": cpr_lower_dist_pct,
        "spot_vs_cpr_upper_distance_pts": cpr_upper_dist_pts,
        "spot_vs_cpr_upper_distance_pct": cpr_upper_dist_pct,
    }


def resolve_session_anchor_levels(
    *,
    spot,
    day_open=None,
    day_high=None,
    day_low=None,
    prev_close=None,
    top_n=3,
):
    """Resolve nearest display-only session anchors around spot."""
    spot_f = _safe_float(spot)
    if spot_f is None:
        return []

    candidates: list[tuple[str, float, int]] = []

    def _add(label: str, value: Any, priority: int) -> None:
        value_f = _safe_float(value)
        if value_f is None or value_f <= 0:
            return
        candidates.append((label, value_f, priority))

    high_f = _safe_float(day_high)
    low_f = _safe_float(day_low)
    _add("day_high", day_high, 1)
    _add("day_low", day_low, 1)
    _add("day_open", day_open, 2)
    _add("prev_close", prev_close, 3)
    if high_f is not None and low_f is not None and high_f > low_f:
        _add("range_mid", (high_f + low_f) / 2.0, 2)

    by_level: dict[float, dict[str, Any]] = {}
    for label, level, priority in candidates:
        key = round(level, 6)
        if key not in by_level:
            by_level[key] = {"level": level, "labels": [label], "priority": priority}
            continue
        by_level[key]["labels"].append(label)
        by_level[key]["priority"] = min(by_level[key]["priority"], priority)

    levels = list(by_level.values())
    supports = sorted(
        [item for item in levels if item["level"] <= spot_f],
        key=lambda item: (abs(item["level"] - spot_f), item["priority"], item["level"]),
    )[:top_n]
    resistances = sorted(
        [item for item in levels if item["level"] >= spot_f],
        key=lambda item: (abs(item["level"] - spot_f), item["priority"], item["level"]),
    )[:top_n]

    rows = []
    for rank, item in enumerate(resistances, start=1):
        rows.append(("resistance", rank, item["level"], "/".join(item["labels"])))
    for rank, item in enumerate(supports, start=1):
        rows.append(("support", rank, item["level"], "/".join(item["labels"])))
    return rows


def _nearest_anchor(spot: Any, spot_summary: dict[str, Any]) -> dict[str, Any]:
    rows = resolve_session_anchor_levels(
        spot=spot,
        day_open=spot_summary.get("day_open"),
        day_high=spot_summary.get("day_high"),
        day_low=spot_summary.get("day_low"),
        prev_close=spot_summary.get("prev_close"),
        top_n=10,
    )
    if not rows:
        return {}
    spot_f = _safe_float(spot)
    if spot_f is None:
        return {}
    nearest = min(rows, key=lambda row: abs(float(row[2]) - spot_f))
    distance_pts, distance_pct = _signed_distance(nearest[2], spot_f)
    return {
        "nearest_price_structure_anchor_side": nearest[0],
        "nearest_price_structure_anchor_rank": nearest[1],
        "nearest_price_structure_anchor_level": round(float(nearest[2]), 4),
        "nearest_price_structure_anchor_label": nearest[3],
        "nearest_price_structure_anchor_distance_pts": distance_pts,
        "nearest_price_structure_anchor_distance_pct": distance_pct,
    }


def _add_level(levels: list[dict[str, Any]], label: str, level: Any, source: str) -> None:
    value = _safe_float(level)
    if value is None or value <= 0:
        return
    levels.append({"label": label, "level": value, "source": source})


def _fibonacci_level_points(spot_summary: dict[str, Any]) -> list[dict[str, Any]]:
    high = _safe_float(spot_summary.get("day_high"))
    low = _safe_float(spot_summary.get("day_low"))
    if high is None or low is None or high <= low:
        return []
    levels: list[dict[str, Any]] = []
    span = high - low
    for ratio, label in FIBONACCI_RETRACEMENT_RATIOS:
        _add_level(levels, label, high - (span * ratio), "fibonacci")
    return levels


def _price_structure_level_points(
    *,
    spot_summary: dict[str, Any],
    price_structure_state: dict[str, Any],
    trade: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    spot = spot_summary.get("spot")
    for side, _rank, level, label in resolve_session_anchor_levels(
        spot=spot,
        day_open=spot_summary.get("day_open"),
        day_high=spot_summary.get("day_high"),
        day_low=spot_summary.get("day_low"),
        prev_close=spot_summary.get("prev_close"),
        top_n=10,
    ):
        _add_level(levels, f"{label}:{side}", level, "session_anchor")

    _add_level(levels, "vwap", price_structure_state.get("price_structure_vwap"), "vwap")
    _add_level(levels, "twap_proxy", price_structure_state.get("price_structure_twap_proxy"), "twap_proxy")
    for minutes in OPENING_RANGE_WINDOWS_MINUTES:
        prefix = f"opening_range_{minutes}m"
        _add_level(levels, f"{prefix}_high", price_structure_state.get(f"{prefix}_high"), "opening_range")
        _add_level(levels, f"{prefix}_low", price_structure_state.get(f"{prefix}_low"), "opening_range")

    _add_level(levels, "classic_pivot", price_structure_state.get("classic_pivot"), "cpr_pivot")
    _add_level(levels, "cpr_bc", price_structure_state.get("cpr_bc"), "cpr_pivot")
    _add_level(levels, "cpr_tc", price_structure_state.get("cpr_tc"), "cpr_pivot")
    _add_level(levels, "pivot_r1", price_structure_state.get("pivot_r1"), "cpr_pivot")
    _add_level(levels, "pivot_s1", price_structure_state.get("pivot_s1"), "cpr_pivot")
    _add_level(levels, "pivot_r2", price_structure_state.get("pivot_r2"), "cpr_pivot")
    _add_level(levels, "pivot_s2", price_structure_state.get("pivot_s2"), "cpr_pivot")
    _add_level(levels, "pivot_r3", price_structure_state.get("pivot_r3"), "cpr_pivot")
    _add_level(levels, "pivot_s3", price_structure_state.get("pivot_s3"), "cpr_pivot")

    levels.extend(_fibonacci_level_points(spot_summary))

    trade = trade if isinstance(trade, dict) else {}
    _add_level(levels, "support_wall", trade.get("support_wall", trade.get("nearest_support_wall")), "option_wall")
    _add_level(levels, "resistance_wall", trade.get("resistance_wall", trade.get("nearest_resistance_wall")), "option_wall")
    _add_level(levels, "gamma_flip", trade.get("gamma_flip"), "dealer_gamma")
    _add_level(levels, "max_pain", trade.get("max_pain"), "max_pain")
    return levels


def _confluence_quality(source_count: int) -> str:
    if source_count >= 5:
        return "VERY_HIGH_CONFLUENCE"
    if source_count >= 4:
        return "HIGH_CONFLUENCE"
    if source_count >= 3:
        return "MODERATE_CONFLUENCE"
    if source_count >= 2:
        return "LOW_CONFLUENCE"
    return "NO_CONFLUENCE"


def _acceptance_proxy_state(price_structure_state: dict[str, Any]) -> tuple[str, str]:
    or_state = (
        price_structure_state.get("opening_range_30m_state")
        or price_structure_state.get("opening_range_15m_state")
        or price_structure_state.get("opening_range_5m_state")
    )
    vwap_state = price_structure_state.get("spot_vs_vwap_state")
    twap_state = price_structure_state.get("spot_vs_twap_proxy_state")
    range_pos = _safe_float(price_structure_state.get("price_structure_range_position_pct"))
    vwap_or_twap_state = vwap_state or twap_state
    basis_parts = [part for part in (or_state, vwap_or_twap_state) if part]
    if range_pos is not None:
        basis_parts.append(f"range_pos={range_pos:.1f}")

    if str(or_state or "").startswith("ABOVE_") and str(vwap_or_twap_state or "").startswith("ABOVE_"):
        return "UPSIDE_ACCEPTANCE_CANDIDATE", "|".join(basis_parts)
    if str(or_state or "").startswith("BELOW_") and str(vwap_or_twap_state or "").startswith("BELOW_"):
        return "DOWNSIDE_ACCEPTANCE_CANDIDATE", "|".join(basis_parts)
    if or_state == "INSIDE_OPENING_RANGE" and vwap_or_twap_state in {
        "AT_VWAP",
        "AT_TWAP_PROXY",
        "ABOVE_VWAP",
        "BELOW_VWAP",
        "ABOVE_TWAP_PROXY",
        "BELOW_TWAP_PROXY",
    }:
        if range_pos is not None and 35.0 <= range_pos <= 65.0:
            return "BALANCED_ROTATION_CANDIDATE", "|".join(basis_parts)
    if or_state:
        return "MIXED_ACCEPTANCE_CONTEXT", "|".join(basis_parts)
    return "ACCEPTANCE_UNAVAILABLE", "|".join(basis_parts)


def _day_type_proxy_state(price_structure_state: dict[str, Any]) -> tuple[str, float | None]:
    acceptance_state = price_structure_state.get("price_structure_acceptance_state")
    range_pos = _safe_float(price_structure_state.get("price_structure_range_position_pct"))
    if acceptance_state == "UPSIDE_ACCEPTANCE_CANDIDATE":
        base = 70.0
        if range_pos is not None and range_pos >= 75.0:
            base += 10.0
        return "TREND_UP_CANDIDATE", min(base, 95.0)
    if acceptance_state == "DOWNSIDE_ACCEPTANCE_CANDIDATE":
        base = 70.0
        if range_pos is not None and range_pos <= 25.0:
            base += 10.0
        return "TREND_DOWN_CANDIDATE", min(base, 95.0)
    if acceptance_state == "BALANCED_ROTATION_CANDIDATE":
        return "RANGE_DAY_CANDIDATE", 65.0
    if acceptance_state == "MIXED_ACCEPTANCE_CONTEXT":
        return "MIXED_DAY_TYPE", 45.0
    return "DAY_TYPE_UNAVAILABLE", None


def add_price_structure_research_overlays(
    price_structure_state: dict[str, Any],
    *,
    spot_summary: dict[str, Any] | None = None,
    trade: dict[str, Any] | None = None,
    confluence_window_pts: float = 25.0,
) -> dict[str, Any]:
    """Add research-only confluence and acceptance/day-type proxy fields."""
    state = dict(price_structure_state or {})
    spot_summary = spot_summary if isinstance(spot_summary, dict) else {}
    spot = _safe_float(spot_summary.get("spot"))
    levels = _price_structure_level_points(
        spot_summary=spot_summary,
        price_structure_state=state,
        trade=trade,
    )
    window = max(float(confluence_window_pts), 1.0)
    best_cluster = None
    if levels:
        for anchor in levels:
            cluster = [item for item in levels if abs(float(item["level"]) - float(anchor["level"])) <= window]
            sources = sorted({str(item["source"]) for item in cluster})
            labels = sorted({str(item["label"]) for item in cluster})
            center = sum(float(item["level"]) for item in cluster) / len(cluster)
            distance = abs(center - spot) if spot is not None else 0.0
            score_tuple = (len(sources), len(cluster), -distance)
            if best_cluster is None or score_tuple > best_cluster["score_tuple"]:
                best_cluster = {
                    "center": center,
                    "sources": sources,
                    "labels": labels,
                    "level_count": len(cluster),
                    "source_count": len(sources),
                    "score_tuple": score_tuple,
                }

    if best_cluster is not None:
        distance_pts, distance_pct = _signed_distance(best_cluster["center"], spot)
        source_count = int(best_cluster["source_count"])
        level_count = int(best_cluster["level_count"])
        state.update(
            {
                "price_level_confluence_state": _confluence_quality(source_count),
                "price_level_confluence_score": min(100.0, round((source_count * 18.0) + (level_count * 2.0), 2)),
                "price_level_confluence_source_count": source_count,
                "price_level_confluence_level_count": level_count,
                "nearest_confluence_level": _round_or_none(best_cluster["center"]),
                "nearest_confluence_distance_pts": distance_pts,
                "nearest_confluence_distance_pct": distance_pct,
                "nearest_confluence_sources": "|".join(best_cluster["sources"]),
                "nearest_confluence_labels": "|".join(best_cluster["labels"]),
            }
        )
    else:
        state.update(
            {
                "price_level_confluence_state": "NO_CONFLUENCE",
                "price_level_confluence_score": 0.0,
                "price_level_confluence_source_count": 0,
                "price_level_confluence_level_count": 0,
                "nearest_confluence_level": None,
                "nearest_confluence_distance_pts": None,
                "nearest_confluence_distance_pct": None,
                "nearest_confluence_sources": "",
                "nearest_confluence_labels": "",
            }
        )

    acceptance_state, acceptance_basis = _acceptance_proxy_state(state)
    state["price_structure_acceptance_state"] = acceptance_state
    state["price_structure_acceptance_basis"] = acceptance_basis
    day_type_state, day_type_score = _day_type_proxy_state(state)
    state["price_structure_day_type_proxy"] = day_type_state
    state["price_structure_trend_day_proxy_score"] = day_type_score
    return state


def build_price_structure_state(
    symbol: str,
    spot_summary: dict[str, Any] | None,
    *,
    spot_history_loader: Callable[..., pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Build point-in-time VWAP/proxy and opening-range context.

    True VWAP is used only when the upstream spot payload supplies a VWAP field.
    Local spot history contains no traded volume, so the fallback is explicitly
    labeled as a TWAP proxy rather than silently pretending to be VWAP.
    """
    spot_summary = spot_summary if isinstance(spot_summary, dict) else {}
    spot = _safe_float(spot_summary.get("spot"))
    timestamp = _coerce_ist_timestamp(spot_summary.get("timestamp"))
    session_start = _session_start_for(timestamp)
    loader = spot_history_loader or load_spot_history

    history = pd.DataFrame(columns=["timestamp", "spot"])
    if symbol and timestamp is not None and session_start is not None:
        try:
            raw_history = loader(symbol, start_ts=session_start, end_ts=timestamp, dedupe=True)
            history = _normalise_history_frame(raw_history, session_start=session_start, timestamp=timestamp)
        except Exception:
            history = pd.DataFrame(columns=["timestamp", "spot"])

    vwap = None
    vwap_source = "UNAVAILABLE"
    for key in ("vwap", "session_vwap", "intraday_vwap", "vwap_price"):
        value = _safe_float(spot_summary.get(key))
        if value is not None:
            vwap = value
            vwap_source = f"SPOT_SUMMARY_{key.upper()}"
            break

    twap_proxy = None
    twap_source = "UNAVAILABLE"
    if not history.empty:
        twap_proxy = _safe_float(history["spot"].mean())
        if twap_proxy is not None:
            twap_source = "SPOT_HISTORY_TWAP_PROXY"

    state: dict[str, Any] = {
        "price_structure_timestamp": timestamp.isoformat() if timestamp is not None else None,
        "price_structure_history_rows": int(len(history)),
        "price_structure_vwap": _round_or_none(vwap),
        "price_structure_vwap_source": vwap_source,
        "price_structure_vwap_available": vwap is not None,
        "price_structure_twap_proxy": _round_or_none(twap_proxy),
        "price_structure_twap_proxy_source": twap_source,
        "price_structure_twap_proxy_available": twap_proxy is not None,
        "spot_vs_vwap_state": _spot_relation_state(level=vwap, spot=spot, label="VWAP"),
        "spot_vs_twap_proxy_state": _spot_relation_state(level=twap_proxy, spot=spot, label="TWAP_PROXY"),
    }
    vwap_dist_pts, vwap_dist_pct = _signed_distance(vwap, spot)
    twap_dist_pts, twap_dist_pct = _signed_distance(twap_proxy, spot)
    state.update(
        {
            "spot_vs_vwap_distance_pts": vwap_dist_pts,
            "spot_vs_vwap_distance_pct": vwap_dist_pct,
            "spot_vs_twap_proxy_distance_pts": twap_dist_pts,
            "spot_vs_twap_proxy_distance_pct": twap_dist_pct,
        }
    )

    day_high = _safe_float(spot_summary.get("day_high"))
    day_low = _safe_float(spot_summary.get("day_low"))
    if spot is not None and day_high is not None and day_low is not None and day_high > day_low:
        state["price_structure_range_position_pct"] = round(((spot - day_low) / (day_high - day_low)) * 100.0, 4)
    else:
        state["price_structure_range_position_pct"] = None

    state.update(_nearest_anchor(spot, spot_summary))

    prior_ohlc = _resolve_prior_session_ohlc(
        symbol=symbol,
        spot_summary=spot_summary,
        session_start=session_start,
        timestamp=timestamp,
        loader=loader,
    )
    if prior_ohlc:
        prior_high = prior_ohlc.get("prior_session_high")
        prior_low = prior_ohlc.get("prior_session_low")
        prior_close = prior_ohlc.get("prior_session_close")
        state.update(
            {
                "prior_session_high": _round_or_none(prior_high),
                "prior_session_low": _round_or_none(prior_low),
                "prior_session_close": _round_or_none(prior_close),
                "prior_session_date": prior_ohlc.get("prior_session_date"),
                "prior_session_ohlc_source": prior_ohlc.get("prior_session_ohlc_source"),
            }
        )
        state.update(_classic_pivot_state(spot=spot, high=prior_high, low=prior_low, close=prior_close))
    else:
        state.update(
            {
                "prior_session_ohlc_available": False,
                "prior_session_high": None,
                "prior_session_low": None,
                "prior_session_close": None,
                "prior_session_date": None,
                "prior_session_ohlc_source": "UNAVAILABLE",
                "classic_pivot_available": False,
                "classic_pivot": None,
                "cpr_bc": None,
                "cpr_tc": None,
                "cpr_lower": None,
                "cpr_upper": None,
                "cpr_width_pts": None,
                "cpr_width_pct": None,
                "pivot_r1": None,
                "pivot_s1": None,
                "pivot_r2": None,
                "pivot_s2": None,
                "pivot_r3": None,
                "pivot_s3": None,
                "spot_vs_pivot_state": None,
                "spot_vs_pivot_distance_pts": None,
                "spot_vs_pivot_distance_pct": None,
                "spot_vs_cpr_state": None,
                "spot_vs_cpr_lower_distance_pts": None,
                "spot_vs_cpr_lower_distance_pct": None,
                "spot_vs_cpr_upper_distance_pts": None,
                "spot_vs_cpr_upper_distance_pct": None,
            }
        )

    for minutes in OPENING_RANGE_WINDOWS_MINUTES:
        prefix = f"opening_range_{minutes}m"
        high = low = width = None
        status = "UNAVAILABLE"
        relation = None
        row_count = 0
        if session_start is not None and timestamp is not None and not history.empty:
            window_end = session_start + pd.Timedelta(minutes=minutes)
            cutoff = min(timestamp, window_end)
            window = history[(history["timestamp"] >= session_start) & (history["timestamp"] <= cutoff)]
            row_count = int(len(window))
            if row_count > 0:
                high = _safe_float(window["spot"].max())
                low = _safe_float(window["spot"].min())
                status = "FORMING" if timestamp < window_end else "COMPLETE"
                if high is not None and low is not None:
                    width = high - low
                    relation = _opening_range_state(spot=spot, high=high, low=low)

        high_dist_pts, high_dist_pct = _signed_distance(high, spot)
        low_dist_pts, low_dist_pct = _signed_distance(low, spot)
        state.update(
            {
                f"{prefix}_status": status,
                f"{prefix}_row_count": row_count,
                f"{prefix}_sample_quality": _opening_range_sample_quality(status=status, row_count=row_count),
                f"{prefix}_high": _round_or_none(high),
                f"{prefix}_low": _round_or_none(low),
                f"{prefix}_width_pts": _round_or_none(width),
                f"{prefix}_state": relation,
                f"{prefix}_high_distance_pts": high_dist_pts,
                f"{prefix}_high_distance_pct": high_dist_pct,
                f"{prefix}_low_distance_pts": low_dist_pts,
                f"{prefix}_low_distance_pct": low_dist_pct,
            }
        )

    return add_price_structure_research_overlays(state, spot_summary=spot_summary, trade=None)

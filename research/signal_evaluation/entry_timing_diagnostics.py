"""Entry-timing diagnostics for live runtime composite scores."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH
from research.signal_evaluation.report_manifest import write_report_reproducibility_manifest
from utils.timestamp_helpers import coerce_timestamp_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENTRY_TIMING_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "entry_timing"
)

PRIOR_LAGS_MINUTES = (5, 15, 30)
FUTURE_HORIZONS_MINUTES = (5, 15, 30, 60, 120)
DEFAULT_SCORE_THRESHOLDS = (50, 55, 60, 65, 70)
DEFAULT_DELAY_LAGS_MINUTES = (5, 10, 15)
DEFAULT_PRIOR_STRETCH_BPS = 10.0
DEFAULT_FUTURE_EDGE_BPS = 5.0

_RUNTIME_COLUMNS = {
    "signal_timestamp",
    "symbol",
    "source",
    "mode",
    "option_source",
    "direction",
    "runtime_composite_score",
    "trade_strength",
    "trade_status",
    "label_quality_status",
    "outcome_status",
    "spot_at_signal",
    "confirmation_status",
    "final_flow_signal",
    "gamma_regime",
    "volatility_regime",
    "global_risk_state",
    "macro_regime",
    "signed_return_5m_bps",
    "signed_return_15m_bps",
    "signed_return_30m_bps",
    "signed_return_60m_bps",
    "signed_return_120m_bps",
    "correct_5m",
    "correct_15m",
    "correct_30m",
    "correct_60m",
    "correct_120m",
    "mfe_60m_bps",
    "mae_60m_bps",
    "mfe_120m_bps",
    "mae_120m_bps",
}


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if pd.isna(number) or not np.isfinite(number):
        return default
    return number


def _round(value: Any, digits: int = 2) -> float | None:
    number = _safe_float(value, None)
    return round(number, digits) if number is not None else None


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _normalize_text(series: pd.Series, default: str = "UNKNOWN") -> pd.Series:
    return (
        series.fillna(default)
        .astype(str)
        .str.strip()
        .replace({"": default, "nan": default, "NaN": default, "None": default})
    )


def _score_bucket(score: pd.Series) -> pd.Series:
    return pd.cut(
        pd.to_numeric(score, errors="coerce"),
        bins=[-np.inf, 49.999, 54.999, 59.999, 64.999, 69.999, np.inf],
        labels=["<50", "50-54", "55-59", "60-64", "65-69", "70+"],
    )


def _numeric_columns(frame: pd.DataFrame) -> pd.DataFrame:
    working = frame.copy()
    for column in working.columns:
        if (
            column.startswith("signed_return_")
            or column.startswith("correct_")
            or column.startswith("mfe_")
            or column.startswith("mae_")
            or column
            in {
                "runtime_composite_score",
                "trade_strength",
                "spot_at_signal",
            }
        ):
            working[column] = pd.to_numeric(working[column], errors="coerce")
    return working


def load_entry_timing_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Signal dataset not found: {dataset_path}")
    return pd.read_csv(
        dataset_path,
        usecols=lambda column: column in _RUNTIME_COLUMNS,
        low_memory=False,
    )


def add_prior_signed_moves(
    frame: pd.DataFrame,
    *,
    prior_lags_minutes: tuple[int, ...] = PRIOR_LAGS_MINUTES,
    tolerance_ratio: float = 0.60,
    min_tolerance_minutes: float = 2.0,
) -> pd.DataFrame:
    """Attach signed prior spot moves by direction using same-session spot observations."""
    working = frame.copy()
    if working.empty:
        for lag in prior_lags_minutes:
            working[f"prior_{lag}m_signed_bps"] = pd.Series(dtype="float64")
        return working

    working["_row_id"] = working.index
    for lag in prior_lags_minutes:
        column = f"prior_{lag}m_signed_bps"
        prior_values = pd.Series(np.nan, index=working.index, dtype="float64")
        tolerance = pd.Timedelta(minutes=max(float(lag) * tolerance_ratio, min_tolerance_minutes))

        for _date, group in working.groupby("signal_date", dropna=False, sort=False):
            valid = group.dropna(subset=["signal_ts", "spot_at_signal", "direction_sign"])
            if valid.empty:
                continue

            spot_timeline = (
                valid[["signal_ts", "spot_at_signal"]]
                .groupby("signal_ts", as_index=False)["spot_at_signal"]
                .median()
                .sort_values("signal_ts")
                .rename(columns={"signal_ts": "prior_ts", "spot_at_signal": "prior_spot"})
            )
            if spot_timeline.empty:
                continue

            left = valid[["_row_id", "signal_ts", "spot_at_signal", "direction_sign"]].copy()
            left["target_ts"] = left["signal_ts"] - pd.Timedelta(minutes=lag)
            merged = pd.merge_asof(
                left.sort_values("target_ts"),
                spot_timeline,
                left_on="target_ts",
                right_on="prior_ts",
                direction="nearest",
                tolerance=tolerance,
            )
            signed_bps = (
                merged["direction_sign"]
                * (merged["spot_at_signal"] - merged["prior_spot"])
                / merged["prior_spot"]
                * 10000.0
            )
            prior_values.loc[merged["_row_id"].to_numpy()] = signed_bps.to_numpy()

        working[column] = prior_values

    return working.drop(columns=["_row_id"], errors="ignore")


def classify_timing_quality(
    row: pd.Series | dict[str, Any],
    *,
    prior_reference_column: str = "prior_favorable_max_bps",
    future_reference_column: str = "signed_return_60m_bps",
    prior_stretch_bps: float = DEFAULT_PRIOR_STRETCH_BPS,
    future_edge_bps: float = DEFAULT_FUTURE_EDGE_BPS,
) -> str:
    prior = _safe_float(row.get(prior_reference_column), None)
    future = _safe_float(row.get(future_reference_column), None)
    if future is None:
        return "PENDING_OUTCOME"
    if prior is None:
        return "UNKNOWN_PRIOR"

    prior_favorable = prior >= prior_stretch_bps
    future_favorable = future >= future_edge_bps
    future_adverse = future <= -future_edge_bps

    if prior_favorable and future_favorable:
        return "CONFIRMING"
    if prior_favorable and (future_adverse or future <= 0.0):
        return "LATE_CHASE"
    if not prior_favorable and future_favorable:
        return "EARLY"
    if not prior_favorable and future_adverse:
        return "FALSE_START"
    return "NO_EDGE"


def prepare_entry_timing_frame(
    frame: pd.DataFrame,
    *,
    prior_lags_minutes: tuple[int, ...] = PRIOR_LAGS_MINUTES,
    classification_horizon_minutes: int = 60,
    prior_stretch_bps: float = DEFAULT_PRIOR_STRETCH_BPS,
    future_edge_bps: float = DEFAULT_FUTURE_EDGE_BPS,
) -> pd.DataFrame:
    working = _numeric_columns(frame)
    if "signal_timestamp" not in working.columns:
        working["signal_timestamp"] = pd.NA
    working["signal_ts"] = coerce_timestamp_series(working["signal_timestamp"], utc=True)
    working["signal_date"] = working["signal_ts"].dt.tz_convert("Asia/Kolkata").dt.date.astype(str)
    working["direction"] = _normalize_text(working.get("direction", pd.Series(index=working.index)))
    working["direction_sign"] = working["direction"].map({"CALL": 1.0, "PUT": -1.0})
    working["runtime_composite_score"] = pd.to_numeric(
        working.get("runtime_composite_score", pd.Series(index=working.index)),
        errors="coerce",
    )
    working["score_bucket"] = _score_bucket(working["runtime_composite_score"])

    prepared = add_prior_signed_moves(working, prior_lags_minutes=prior_lags_minutes)
    prior_columns = [f"prior_{lag}m_signed_bps" for lag in prior_lags_minutes if f"prior_{lag}m_signed_bps" in prepared.columns]
    if prior_columns:
        prepared["prior_favorable_max_bps"] = prepared[prior_columns].max(axis=1, skipna=True)
    else:
        prepared["prior_favorable_max_bps"] = np.nan

    future_column = f"signed_return_{classification_horizon_minutes}m_bps"
    prepared["timing_class"] = prepared.apply(
        classify_timing_quality,
        axis=1,
        future_reference_column=future_column,
        prior_stretch_bps=prior_stretch_bps,
        future_edge_bps=future_edge_bps,
    )
    return prepared


def _mean(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.mean())


def _share(series: pd.Series, value: str) -> float | None:
    if series.empty:
        return None
    return float((series.astype(str) == value).mean())


def _pct_mean(series: pd.Series) -> float | None:
    value = _mean(series)
    return value * 100.0 if value is not None else None


def _summarize_groups(frame: pd.DataFrame, group_cols: list[str], *, min_rows: int = 1) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    missing = [column for column in group_cols if column not in frame.columns]
    if missing:
        return []
    rows: list[dict[str, Any]] = []
    for keys, group in frame.groupby(group_cols, dropna=False, observed=True):
        if len(group) < min_rows:
            continue
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {column: str(value) for column, value in zip(group_cols, keys)}
        row.update(
            {
                "row_count": int(len(group)),
                "avg_runtime_composite_score": _round(_mean(group["runtime_composite_score"])),
                "avg_prior_15m_bps": _round(_mean(group.get("prior_15m_signed_bps", pd.Series(dtype=float)))),
                "avg_prior_30m_bps": _round(_mean(group.get("prior_30m_signed_bps", pd.Series(dtype=float)))),
                "avg_prior_favorable_max_bps": _round(_mean(group.get("prior_favorable_max_bps", pd.Series(dtype=float)))),
                "avg_return_15m_bps": _round(_mean(group.get("signed_return_15m_bps", pd.Series(dtype=float)))),
                "avg_return_30m_bps": _round(_mean(group.get("signed_return_30m_bps", pd.Series(dtype=float)))),
                "avg_return_60m_bps": _round(_mean(group.get("signed_return_60m_bps", pd.Series(dtype=float)))),
                "avg_return_120m_bps": _round(_mean(group.get("signed_return_120m_bps", pd.Series(dtype=float)))),
                "hit_rate_60m": _round(_pct_mean(group.get("correct_60m", pd.Series(dtype=float)))),
                "avg_mfe_60m_bps": _round(_mean(group.get("mfe_60m_bps", pd.Series(dtype=float)))),
                "avg_mae_60m_bps": _round(_mean(group.get("mae_60m_bps", pd.Series(dtype=float)))),
                "late_chase_share": _round(_share(group["timing_class"], "LATE_CHASE") * 100.0),
                "confirming_share": _round(_share(group["timing_class"], "CONFIRMING") * 100.0),
                "early_share": _round(_share(group["timing_class"], "EARLY") * 100.0),
                "false_start_share": _round(_share(group["timing_class"], "FALSE_START") * 100.0),
                "pending_share": _round(_share(group["timing_class"], "PENDING_OUTCOME") * 100.0),
            }
        )
        rows.append(row)
    return rows


def _threshold_crossings(
    frame: pd.DataFrame,
    *,
    thresholds: tuple[int, ...] = DEFAULT_SCORE_THRESHOLDS,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return rows
    event_keys = ["signal_date", "direction"]
    for threshold in thresholds:
        events = []
        for _keys, group in frame.sort_values("signal_ts").groupby(event_keys, dropna=False, observed=True):
            previous_score = group["runtime_composite_score"].shift(1).fillna(-np.inf)
            crossed = group[(group["runtime_composite_score"] >= threshold) & (previous_score < threshold)]
            if not crossed.empty:
                events.append(crossed.iloc[0])
        if not events:
            rows.append({"threshold": int(threshold), "event_count": 0})
            continue
        event_frame = pd.DataFrame(events)
        rows.append(
            {
                "threshold": int(threshold),
                "event_count": int(len(event_frame)),
                "avg_runtime_composite_score": _round(_mean(event_frame["runtime_composite_score"])),
                "avg_prior_15m_bps": _round(_mean(event_frame.get("prior_15m_signed_bps", pd.Series(dtype=float)))),
                "avg_prior_30m_bps": _round(_mean(event_frame.get("prior_30m_signed_bps", pd.Series(dtype=float)))),
                "avg_return_15m_bps": _round(_mean(event_frame.get("signed_return_15m_bps", pd.Series(dtype=float)))),
                "avg_return_30m_bps": _round(_mean(event_frame.get("signed_return_30m_bps", pd.Series(dtype=float)))),
                "avg_return_60m_bps": _round(_mean(event_frame.get("signed_return_60m_bps", pd.Series(dtype=float)))),
                "hit_rate_60m": _round(_pct_mean(event_frame.get("correct_60m", pd.Series(dtype=float)))),
                "late_chase_share": _round(_share(event_frame["timing_class"], "LATE_CHASE") * 100.0),
                "confirming_share": _round(_share(event_frame["timing_class"], "CONFIRMING") * 100.0),
                "pending_share": _round(_share(event_frame["timing_class"], "PENDING_OUTCOME") * 100.0),
            }
        )
    return rows


def _delayed_entry_summary(
    frame: pd.DataFrame,
    *,
    thresholds: tuple[int, ...] = DEFAULT_SCORE_THRESHOLDS,
    delay_lags_minutes: tuple[int, ...] = DEFAULT_DELAY_LAGS_MINUTES,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return rows

    sort_cols = ["signal_date", "direction", "signal_ts"]
    ordered = frame.sort_values(sort_cols).copy()
    compare_cols = [
        "runtime_composite_score",
        "signed_return_15m_bps",
        "signed_return_30m_bps",
        "signed_return_60m_bps",
        "signed_return_120m_bps",
    ]
    compare_cols = [column for column in compare_cols if column in ordered.columns]

    for threshold in thresholds:
        candidates = ordered[ordered["runtime_composite_score"] >= threshold].copy()
        for delay in delay_lags_minutes:
            comparisons = []
            tolerance = pd.Timedelta(minutes=max(2.0, delay * 0.60))
            for (signal_date, direction), group in ordered.groupby(["signal_date", "direction"], dropna=False, observed=True):
                left = candidates[(candidates["signal_date"] == signal_date) & (candidates["direction"] == direction)]
                if left.empty:
                    continue
                left = left[["signal_ts", *compare_cols]].copy()
                left["target_ts"] = left["signal_ts"] + pd.Timedelta(minutes=delay)
                right = group[["signal_ts", *compare_cols]].copy().rename(
                    columns={column: f"delayed_{column}" for column in compare_cols}
                )
                right = right.rename(columns={"signal_ts": "delayed_signal_ts"})
                merged = pd.merge_asof(
                    left.sort_values("target_ts"),
                    right.sort_values("delayed_signal_ts"),
                    left_on="target_ts",
                    right_on="delayed_signal_ts",
                    direction="nearest",
                    tolerance=tolerance,
                )
                comparisons.append(merged)
            if not comparisons:
                rows.append({"threshold": int(threshold), "delay_minutes": int(delay), "pair_count": 0})
                continue
            joined = pd.concat(comparisons, ignore_index=True)
            joined = joined[joined["delayed_signal_ts"].notna()].copy()
            row: dict[str, Any] = {
                "threshold": int(threshold),
                "delay_minutes": int(delay),
                "pair_count": int(len(joined)),
                "avg_now_score": _round(_mean(joined["runtime_composite_score"])),
                "avg_delayed_score": _round(_mean(joined["delayed_runtime_composite_score"])),
            }
            for horizon in (15, 30, 60, 120):
                now_col = f"signed_return_{horizon}m_bps"
                delayed_col = f"delayed_signed_return_{horizon}m_bps"
                if now_col in joined.columns and delayed_col in joined.columns:
                    delta = pd.to_numeric(joined[delayed_col], errors="coerce") - pd.to_numeric(joined[now_col], errors="coerce")
                    row[f"delayed_minus_now_{horizon}m_bps"] = _round(_mean(delta))
                    valid_delta = delta.dropna()
                    row[f"delayed_better_{horizon}m_share"] = (
                        _round(float((valid_delta > 0).mean()) * 100.0) if not valid_delta.empty else None
                    )
            rows.append(row)
    return rows


def _top_late_chase_regimes(frame: pd.DataFrame, *, min_rows: int = 5) -> list[dict[str, Any]]:
    group_cols = ["gamma_regime", "volatility_regime", "global_risk_state"]
    for column in group_cols:
        if column not in frame.columns:
            frame[column] = "UNKNOWN"
        frame[column] = _normalize_text(frame[column])
    rows = _summarize_groups(frame, group_cols, min_rows=min_rows)
    rows.sort(key=lambda row: (-(row.get("late_chase_share") or 0), -row.get("row_count", 0)))
    return rows[:15]


def build_entry_timing_report(
    frame: pd.DataFrame,
    *,
    prior_lags_minutes: tuple[int, ...] = PRIOR_LAGS_MINUTES,
    score_thresholds: tuple[int, ...] = DEFAULT_SCORE_THRESHOLDS,
    delay_lags_minutes: tuple[int, ...] = DEFAULT_DELAY_LAGS_MINUTES,
    classification_horizon_minutes: int = 60,
    prior_stretch_bps: float = DEFAULT_PRIOR_STRETCH_BPS,
    future_edge_bps: float = DEFAULT_FUTURE_EDGE_BPS,
) -> dict[str, Any]:
    prepared = prepare_entry_timing_frame(
        frame,
        prior_lags_minutes=prior_lags_minutes,
        classification_horizon_minutes=classification_horizon_minutes,
        prior_stretch_bps=prior_stretch_bps,
        future_edge_bps=future_edge_bps,
    )
    runtime = prepared[
        prepared["runtime_composite_score"].notna()
        & prepared["direction_sign"].notna()
        & prepared["signal_ts"].notna()
        & prepared["spot_at_signal"].notna()
    ].copy()

    runtime["trade_status"] = _normalize_text(runtime.get("trade_status", pd.Series(index=runtime.index)))
    runtime["outcome_status"] = _normalize_text(runtime.get("outcome_status", pd.Series(index=runtime.index)))
    runtime["label_quality_status"] = _normalize_text(runtime.get("label_quality_status", pd.Series(index=runtime.index)))

    mature_60m = runtime[runtime.get("signed_return_60m_bps", pd.Series(index=runtime.index)).notna()].copy()
    score_summary = _summarize_groups(runtime, ["score_bucket"])
    score_summary_mature_60m = _summarize_groups(mature_60m, ["score_bucket"])
    timing_summary = _summarize_groups(runtime, ["timing_class"])
    timing_by_score = _summarize_groups(runtime, ["score_bucket", "timing_class"])

    generated_at = datetime.now(UTC).isoformat()
    ts = runtime["signal_ts"].dropna()
    report = {
        "report_type": "entry_timing_diagnostics",
        "schema_version": 1,
        "generated_at": generated_at,
        "methodology": {
            "live_score_field": "runtime_composite_score",
            "excluded_hindsight_score_field": "composite_signal_score",
            "classification_horizon_minutes": int(classification_horizon_minutes),
            "prior_lags_minutes": list(prior_lags_minutes),
            "score_thresholds": list(score_thresholds),
            "delay_lags_minutes": list(delay_lags_minutes),
            "prior_stretch_bps": float(prior_stretch_bps),
            "future_edge_bps": float(future_edge_bps),
            "timing_class_definitions": {
                "EARLY": "prior move not stretched; future signed return >= edge floor",
                "CONFIRMING": "prior favorable move stretched; future signed return still >= edge floor",
                "LATE_CHASE": "prior favorable move stretched; future signed return is weak or adverse",
                "FALSE_START": "prior move not stretched; future signed return <= adverse floor",
                "NO_EDGE": "neither favorable nor adverse enough at the classification horizon",
                "PENDING_OUTCOME": "future classification horizon is not mature yet",
                "UNKNOWN_PRIOR": "future is present but prior spot history was unavailable",
            },
        },
        "coverage": {
            "input_rows": int(len(frame)),
            "runtime_rows": int(len(runtime)),
            "mature_60m_rows": int(len(mature_60m)),
            "pending_outcome_rows": int((runtime["timing_class"] == "PENDING_OUTCOME").sum()),
            "start_timestamp": ts.min().isoformat() if not ts.empty else None,
            "end_timestamp": ts.max().isoformat() if not ts.empty else None,
            "trading_days": int(ts.dt.normalize().nunique()) if not ts.empty else 0,
            "max_runtime_composite_score": _round(runtime["runtime_composite_score"].max(), 0),
            "runtime_score_non_null_rows": int(prepared["runtime_composite_score"].notna().sum()),
            "trade_status_counts": runtime["trade_status"].value_counts(dropna=False).to_dict(),
            "outcome_status_counts": runtime["outcome_status"].value_counts(dropna=False).to_dict(),
            "label_quality_counts": runtime["label_quality_status"].value_counts(dropna=False).to_dict(),
        },
        "score_bucket_summary": score_summary,
        "score_bucket_summary_mature_60m": score_summary_mature_60m,
        "timing_class_summary": timing_summary,
        "timing_by_score_bucket": timing_by_score,
        "threshold_crossings": _threshold_crossings(runtime, thresholds=score_thresholds),
        "delayed_entry_summary": _delayed_entry_summary(
            runtime,
            thresholds=score_thresholds,
            delay_lags_minutes=delay_lags_minutes,
        ),
        "top_late_chase_regime_slices": _top_late_chase_regimes(runtime.copy()),
    }
    report["diagnostic_read"] = _diagnostic_read(report)
    return _json_ready(report)


def _diagnostic_read(report: dict[str, Any]) -> dict[str, Any]:
    mature = report.get("score_bucket_summary_mature_60m") or []
    by_bucket = {row.get("score_bucket"): row for row in mature}
    mid = by_bucket.get("55-59") or {}
    lower = by_bucket.get("50-54") or {}
    late_signal = None
    if mid and lower:
        mid_return = _safe_float(mid.get("avg_return_60m_bps"), None)
        lower_return = _safe_float(lower.get("avg_return_60m_bps"), None)
        mid_late = _safe_float(mid.get("late_chase_share"), 0.0)
        lower_late = _safe_float(lower.get("late_chase_share"), 0.0)
        late_signal = bool(
            mid_return is not None
            and lower_return is not None
            and mid_return < lower_return
            and mid_late >= lower_late
        )

    threshold_50 = next((row for row in report.get("threshold_crossings", []) if row.get("threshold") == 50), {})
    threshold_55 = next((row for row in report.get("threshold_crossings", []) if row.get("threshold") == 55), {})
    return {
        "runtime_sample_is_small": bool((report.get("coverage") or {}).get("runtime_rows", 0) < 500),
        "high_score_evidence_is_immature": bool((report.get("coverage") or {}).get("max_runtime_composite_score", 0) < 80),
        "late_chase_thesis_supported": late_signal,
        "score_55_59_vs_50_54": {
            "avg_return_60m_delta_bps": _round(
                _safe_float(mid.get("avg_return_60m_bps"), 0.0) - _safe_float(lower.get("avg_return_60m_bps"), 0.0)
            )
            if mid and lower
            else None,
            "hit_rate_60m_delta_pct": _round(
                _safe_float(mid.get("hit_rate_60m"), 0.0) - _safe_float(lower.get("hit_rate_60m"), 0.0)
            )
            if mid and lower
            else None,
        },
        "first_crossing_50": threshold_50,
        "first_crossing_55": threshold_55,
    }


def _markdown_table(rows: list[dict[str, Any]], columns: list[str], *, max_rows: int | None = None) -> list[str]:
    selected = rows[:max_rows] if max_rows is not None else rows
    if not selected:
        return ["No rows available."]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in selected:
        values = []
        for column in columns:
            value = row.get(column)
            values.append("-" if value is None else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def render_entry_timing_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    lines: list[str] = [
        "# Entry Timing Diagnostic Report",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This report uses the live-time `runtime_composite_score` only. It intentionally excludes "
        "`composite_signal_score`, because that field is populated from realized outcome quality and would introduce hindsight.",
        "",
        f"Timing classes use prior signed spot movement versus the {report['methodology']['classification_horizon_minutes']}m signed return. "
        f"A prior move is considered stretched above `{report['methodology']['prior_stretch_bps']}` bps; "
        f"a future edge is considered meaningful above `{report['methodology']['future_edge_bps']}` bps.",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Runtime rows with usable score/direction/spot: `{coverage.get('runtime_rows')}`",
        f"- Mature 60m rows: `{coverage.get('mature_60m_rows')}`",
        f"- Pending outcome rows: `{coverage.get('pending_outcome_rows')}`",
        f"- Trading days: `{coverage.get('trading_days')}`",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        f"- Max observed runtime composite score: `{coverage.get('max_runtime_composite_score')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Late-chase thesis supported on current mature sample: `{read.get('late_chase_thesis_supported')}`",
        f"- Runtime sample is small: `{read.get('runtime_sample_is_small')}`",
        f"- High-score evidence is immature: `{read.get('high_score_evidence_is_immature')}`",
        f"- 55-59 vs 50-54 60m return delta: `{(read.get('score_55_59_vs_50_54') or {}).get('avg_return_60m_delta_bps')}` bps",
        f"- 55-59 vs 50-54 60m hit-rate delta: `{(read.get('score_55_59_vs_50_54') or {}).get('hit_rate_60m_delta_pct')}` pct pts",
        "",
        "## Score Buckets: Mature 60m Rows",
        "",
    ]
    lines.extend(
        _markdown_table(
            report.get("score_bucket_summary_mature_60m") or [],
            [
                "score_bucket",
                "row_count",
                "avg_runtime_composite_score",
                "avg_prior_15m_bps",
                "avg_prior_30m_bps",
                "avg_return_15m_bps",
                "avg_return_30m_bps",
                "avg_return_60m_bps",
                "hit_rate_60m",
                "avg_mfe_60m_bps",
                "avg_mae_60m_bps",
                "late_chase_share",
                "confirming_share",
                "early_share",
            ],
        )
    )
    lines.extend(
        [
            "",
            "## Timing Classes",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            report.get("timing_class_summary") or [],
            [
                "timing_class",
                "row_count",
                "avg_runtime_composite_score",
                "avg_prior_15m_bps",
                "avg_prior_30m_bps",
                "avg_return_60m_bps",
                "hit_rate_60m",
                "avg_mfe_60m_bps",
                "avg_mae_60m_bps",
            ],
        )
    )
    lines.extend(
        [
            "",
            "## First Threshold Crossings",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            report.get("threshold_crossings") or [],
            [
                "threshold",
                "event_count",
                "avg_runtime_composite_score",
                "avg_prior_15m_bps",
                "avg_prior_30m_bps",
                "avg_return_15m_bps",
                "avg_return_30m_bps",
                "avg_return_60m_bps",
                "hit_rate_60m",
                "late_chase_share",
                "confirming_share",
                "pending_share",
            ],
        )
    )
    lines.extend(
        [
            "",
            "## Delayed Entry Check",
            "",
            "Positive `delayed_minus_now` means the delayed signal row had better forward return than the original row.",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            report.get("delayed_entry_summary") or [],
            [
                "threshold",
                "delay_minutes",
                "pair_count",
                "avg_now_score",
                "avg_delayed_score",
                "delayed_minus_now_15m_bps",
                "delayed_better_15m_share",
                "delayed_minus_now_30m_bps",
                "delayed_better_30m_share",
                "delayed_minus_now_60m_bps",
                "delayed_better_60m_share",
            ],
        )
    )
    lines.extend(
        [
            "",
            "## Late-Chase Regime Slices",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            report.get("top_late_chase_regime_slices") or [],
            [
                "gamma_regime",
                "volatility_regime",
                "global_risk_state",
                "row_count",
                "late_chase_share",
                "avg_return_60m_bps",
                "hit_rate_60m",
                "avg_prior_15m_bps",
                "avg_prior_30m_bps",
            ],
            max_rows=15,
        )
    )
    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "",
            "- This is research-only and does not alter live decisions.",
            "- Rows with pending outcomes are useful for coverage but not for mature 60m edge conclusions.",
            "- The current high-score runtime sample is still sparse, so promotion-quality rules need more forward data.",
            "",
        ]
    )
    return "\n".join(lines)


def write_entry_timing_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_ENTRY_TIMING_REPORT_DIR,
    prior_stretch_bps: float = DEFAULT_PRIOR_STRETCH_BPS,
    future_edge_bps: float = DEFAULT_FUTURE_EDGE_BPS,
    classification_horizon_minutes: int = 60,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    frame = load_entry_timing_dataset(dataset)
    report = build_entry_timing_report(
        frame,
        prior_stretch_bps=prior_stretch_bps,
        future_edge_bps=future_edge_bps,
        classification_horizon_minutes=classification_horizon_minutes,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output / f"entry_timing_diagnostics_{timestamp}.json"
    markdown_path = output / f"entry_timing_diagnostics_{timestamp}.md"
    latest_json_path = output / "latest_entry_timing_diagnostics.json"
    latest_markdown_path = output / "latest_entry_timing_diagnostics.md"

    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_entry_timing_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")
    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="entry_timing_diagnostics",
        mode="research",
        run_evaluation=False,
        narrative=False,
    )

    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
        "manifest_path": str(manifest_path),
    }

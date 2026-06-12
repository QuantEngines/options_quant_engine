"""Research-only mean-reversion outcome evaluation.

This report evaluates the point-in-time mean-reversion fields already captured
in the signal dataset. It does not change live signal generation, trade gates,
probabilities, parameter packs, or execution behavior.
"""

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
DEFAULT_MEAN_REVERSION_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "mean_reversion"
)

HORIZONS: tuple[tuple[str, str, str], ...] = (
    ("5m", "signed_return_5m_bps", "correct_5m"),
    ("15m", "signed_return_15m_bps", "correct_15m"),
    ("30m", "signed_return_30m_bps", "correct_30m"),
    ("60m", "signed_return_60m_bps", "correct_60m"),
    ("120m", "signed_return_120m_bps", "correct_120m"),
    ("session_close", "signed_return_session_close_bps", "correct_session_close"),
)

USE_COLUMNS = {
    "signal_timestamp",
    "symbol",
    "direction",
    "trade_status",
    "runtime_composite_score",
    "trade_strength",
    "decision_quality_score_v1",
    "composite_signal_score",
    "confirmation_status",
    "gamma_regime",
    "volatility_regime",
    "macro_regime",
    "global_risk_state",
    "provider_quality_mode",
    "option_source",
    "mean_reversion_signal",
    "mean_reversion_zscore",
    "mean_reversion_strength",
    "mean_reversion_distance_pct",
    "mean_reversion_reason",
    "mfe_60m_bps",
    "mae_60m_bps",
    "mfe_120m_bps",
    "mae_120m_bps",
    *[column for _, return_col, hit_col in HORIZONS for column in (return_col, hit_col)],
}

DEFAULT_MIN_LABELS = 30


def _round_or_none(value: Any, digits: int = 3) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(number) or not np.isfinite(number):
        return None
    return round(number, digits)


def _safe_mean(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.mean())


def _normalize_text(series: pd.Series, default: str = "UNKNOWN") -> pd.Series:
    return (
        series.astype("object")
        .where(series.notna(), default)
        .astype(str)
        .str.strip()
        .replace({"": default, "nan": default, "NaN": default, "None": default})
    )


def _hit_series(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="float64")
    normalized = series.astype("object")
    numeric = pd.to_numeric(normalized, errors="coerce")
    text = normalized.astype(str).str.strip().str.upper()
    truthy = text.isin({"TRUE", "T", "YES", "Y"})
    falsy = text.isin({"FALSE", "F", "NO", "N"})
    numeric = numeric.mask(numeric.isna() & truthy, 1.0)
    numeric = numeric.mask(numeric.isna() & falsy, 0.0)
    return numeric.clip(lower=0.0, upper=1.0)


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


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(_json_ready(payload), indent=2, sort_keys=True, default=str))


def _atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def load_mean_reversion_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset = Path(path)
    if not dataset.exists():
        raise FileNotFoundError(f"Signal dataset not found: {dataset}")
    return pd.read_csv(dataset, usecols=lambda column: column in USE_COLUMNS, low_memory=False)


def _filter_signal_date_range(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    working = frame.copy()
    if "signal_timestamp" not in working.columns:
        return working.iloc[0:0].copy() if report_date else working.copy()
    signal_ts = coerce_timestamp_series(working["signal_timestamp"], utc=True)
    local_date = signal_ts.dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
    mask = pd.Series(True, index=working.index, dtype=bool)
    if report_date:
        mask &= local_date == str(report_date)
    if start_date:
        mask &= local_date >= str(start_date)
    if end_date:
        mask &= local_date <= str(end_date)
    return working.loc[mask.fillna(False)].copy()


def _score_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(
        pd.to_numeric(series, errors="coerce"),
        bins=[-np.inf, 34.999, 49.999, 59.999, 69.999, 79.999, np.inf],
        labels=["0-35", "35-50", "50-60", "60-70", "70-80", "80-100"],
    ).astype("string")


def _strength_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(
        pd.to_numeric(series, errors="coerce"),
        bins=[-np.inf, 0.001, 9.999, 24.999, 49.999, np.inf],
        labels=["0", "0-10", "10-25", "25-50", "50+"],
    ).astype("string")


def _abs_zscore_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(
        pd.to_numeric(series, errors="coerce").abs(),
        bins=[-np.inf, 0.5, 1.0, 1.5, 2.0, np.inf],
        labels=["0-0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0", "2.0+"],
    ).astype("string")


def _distance_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(
        pd.to_numeric(series, errors="coerce").abs(),
        bins=[-np.inf, 0.25, 0.75, 1.5, 3.0, np.inf],
        labels=["0-0.25", "0.25-0.75", "0.75-1.5", "1.5-3.0", "3.0+"],
    ).astype("string")


def prepare_mean_reversion_frame(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    working = frame.copy() if frame is not None else pd.DataFrame()
    for column in USE_COLUMNS:
        if column not in working.columns:
            working[column] = pd.NA
    working = _filter_signal_date_range(
        working,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    if working.empty:
        return working

    if "signal_timestamp" in working.columns:
        working["signal_ts"] = coerce_timestamp_series(working["signal_timestamp"], utc=True)
        working["signal_date"] = working["signal_ts"].dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
    else:
        working["signal_ts"] = pd.Series(pd.NaT, index=working.index, dtype="datetime64[ns, UTC]")
        working["signal_date"] = "UNKNOWN"
    working["signal_date"] = working["signal_date"].fillna("UNKNOWN")

    for column in (
        "runtime_composite_score",
        "trade_strength",
        "decision_quality_score_v1",
        "composite_signal_score",
        "mean_reversion_zscore",
        "mean_reversion_strength",
        "mean_reversion_distance_pct",
        "mfe_60m_bps",
        "mae_60m_bps",
        "mfe_120m_bps",
        "mae_120m_bps",
        *[return_col for _, return_col, _ in HORIZONS],
    ):
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    for _, _, hit_col in HORIZONS:
        if hit_col in working.columns:
            working[hit_col] = _hit_series(working[hit_col])

    text_columns = (
        "symbol",
        "direction",
        "trade_status",
        "confirmation_status",
        "gamma_regime",
        "volatility_regime",
        "macro_regime",
        "global_risk_state",
        "provider_quality_mode",
        "option_source",
        "mean_reversion_signal",
        "mean_reversion_reason",
    )
    for column in text_columns:
        working[column] = _normalize_text(working[column])

    working["mean_reversion_signal"] = working["mean_reversion_signal"].str.upper()
    working["has_mean_reversion_features"] = ~working["mean_reversion_signal"].isin(
        {"UNKNOWN", "INSUFFICIENT_DATA", "ERROR", "UNAVAILABLE"}
    )
    working["runtime_composite_bucket"] = _score_bucket(working["runtime_composite_score"])
    working["trade_strength_bucket"] = _score_bucket(working["trade_strength"])
    working["mean_reversion_strength_bucket"] = _strength_bucket(working["mean_reversion_strength"])
    working["mean_reversion_abs_zscore_bucket"] = _abs_zscore_bucket(working["mean_reversion_zscore"])
    working["mean_reversion_distance_bucket"] = _distance_bucket(working["mean_reversion_distance_pct"])
    return working.reset_index(drop=True)


def _mfe_mae_ratio(frame: pd.DataFrame, horizon: str = "60m") -> float | None:
    mfe = _safe_mean(frame.get(f"mfe_{horizon}_bps", pd.Series(index=frame.index)))
    mae = _safe_mean(
        pd.to_numeric(frame.get(f"mae_{horizon}_bps", pd.Series(index=frame.index)), errors="coerce").abs()
    )
    if mfe is None or mae is None or mae <= 0:
        return None
    return mfe / mae


def _metric_bundle(frame: pd.DataFrame) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "row_count": int(len(frame)),
        "feature_row_count": int(frame.get("has_mean_reversion_features", pd.Series(False, index=frame.index)).sum()),
        "avg_mean_reversion_zscore": _round_or_none(_safe_mean(frame.get("mean_reversion_zscore", pd.Series(index=frame.index)))),
        "avg_abs_mean_reversion_zscore": _round_or_none(
            _safe_mean(pd.to_numeric(frame.get("mean_reversion_zscore", pd.Series(index=frame.index)), errors="coerce").abs())
        ),
        "avg_mean_reversion_strength": _round_or_none(
            _safe_mean(frame.get("mean_reversion_strength", pd.Series(index=frame.index)))
        ),
        "avg_mean_reversion_distance_pct": _round_or_none(
            _safe_mean(frame.get("mean_reversion_distance_pct", pd.Series(index=frame.index)))
        ),
        "avg_runtime_composite_score": _round_or_none(
            _safe_mean(frame.get("runtime_composite_score", pd.Series(index=frame.index)))
        ),
        "avg_trade_strength": _round_or_none(_safe_mean(frame.get("trade_strength", pd.Series(index=frame.index)))),
        "avg_expost_composite": _round_or_none(
            _safe_mean(frame.get("composite_signal_score", pd.Series(index=frame.index)))
        ),
        "mfe_mae_ratio_60m": _round_or_none(_mfe_mae_ratio(frame, "60m")),
        "mfe_mae_ratio_120m": _round_or_none(_mfe_mae_ratio(frame, "120m")),
    }
    for horizon, return_col, hit_col in HORIZONS:
        returns = pd.to_numeric(frame.get(return_col, pd.Series(index=frame.index)), errors="coerce")
        hits = pd.to_numeric(frame.get(hit_col, pd.Series(index=frame.index)), errors="coerce")
        label_mask = returns.notna() | hits.notna()
        valid_hits = hits.dropna()
        payload[f"label_count_{horizon}"] = int(label_mask.sum())
        payload[f"hit_rate_{horizon}"] = (
            _round_or_none(float(valid_hits.mean() * 100.0), 2) if not valid_hits.empty else None
        )
        payload[f"avg_signed_return_{horizon}_bps"] = _round_or_none(_safe_mean(returns), 3)
    return payload


def _summarize_groups(frame: pd.DataFrame, group_cols: list[str], *, min_rows: int = 1) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    for column in group_cols:
        if column not in frame.columns:
            frame[column] = "UNKNOWN"
    rows: list[dict[str, Any]] = []
    for keys, group in frame.groupby(group_cols, dropna=False, observed=False, sort=True):
        if len(group) < min_rows:
            continue
        if not isinstance(keys, tuple):
            keys = (keys,)
        prefix = {column: _json_ready(value) for column, value in zip(group_cols, keys)}
        rows.append({**prefix, **_metric_bundle(group)})
    return rows


def _row_by_signal(rows: list[dict[str, Any]], signal: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get("mean_reversion_signal", "")).upper() == signal:
            return row
    return {}


def _diagnostic_read(signal_summary: list[dict[str, Any]], strength_summary: list[dict[str, Any]]) -> dict[str, Any]:
    observations: list[str] = []
    mr = _row_by_signal(signal_summary, "MEAN_REVERSION")
    trend = _row_by_signal(signal_summary, "TREND_CONTINUATION")
    insufficient = _row_by_signal(signal_summary, "INSUFFICIENT_DATA")

    mr_labels = int(mr.get("label_count_60m") or 0)
    trend_labels = int(trend.get("label_count_60m") or 0)
    mr_return = _round_or_none(mr.get("avg_signed_return_60m_bps"))
    trend_return = _round_or_none(trend.get("avg_signed_return_60m_bps"))
    mr_hit = _round_or_none(mr.get("hit_rate_60m"), 2)
    trend_hit = _round_or_none(trend.get("hit_rate_60m"), 2)

    if mr_labels >= DEFAULT_MIN_LABELS and trend_labels >= DEFAULT_MIN_LABELS:
        if mr_return is not None and trend_return is not None:
            if mr_return >= trend_return + 2.0:
                observations.append("MEAN_REVERSION_OUTPERFORMS_TREND_CONTINUATION_60M")
            elif mr_return <= trend_return - 2.0:
                observations.append("MEAN_REVERSION_UNDERPERFORMS_TREND_CONTINUATION_60M")
        if mr_hit is not None and trend_hit is not None:
            if mr_hit >= trend_hit + 5.0:
                observations.append("MEAN_REVERSION_HIT_RATE_ADVANTAGE_60M")
            elif mr_hit <= trend_hit - 5.0:
                observations.append("MEAN_REVERSION_HIT_RATE_DISADVANTAGE_60M")
    elif mr_labels > 0 or trend_labels > 0:
        observations.append("MEAN_REVERSION_SIGNAL_EVIDENCE_ACCUMULATING")

    high_strength_rows = [
        row
        for row in strength_summary
        if str(row.get("mean_reversion_strength_bucket")) in {"25-50", "50+"}
        and int(row.get("label_count_60m") or 0) >= DEFAULT_MIN_LABELS
    ]
    if high_strength_rows:
        best = max(high_strength_rows, key=lambda row: float(row.get("avg_signed_return_60m_bps") or -1e9))
        if (best.get("avg_signed_return_60m_bps") or 0) > 0 and (best.get("mfe_mae_ratio_60m") or 0) > 1:
            observations.append("HIGH_STRENGTH_MEAN_REVERSION_BUCKET_PROMISING")

    if not observations:
        observations.append("NO_STABLE_MEAN_REVERSION_EDGE_YET")

    primary_read = observations[0]
    if int(insufficient.get("row_count") or 0) > max(mr.get("row_count") or 0, trend.get("row_count") or 0, 0):
        observations.append("MEAN_REVERSION_FEATURE_COVERAGE_STILL_LIMITED")

    return {
        "primary_read": primary_read,
        "observations": observations,
        "mean_reversion_60m_labels": mr_labels,
        "mean_reversion_60m_hit_rate": mr_hit,
        "mean_reversion_60m_return_bps": mr_return,
        "trend_continuation_60m_labels": trend_labels,
        "trend_continuation_60m_hit_rate": trend_hit,
        "trend_continuation_60m_return_bps": trend_return,
    }


def build_mean_reversion_evaluation_report(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    prepared = prepare_mean_reversion_frame(
        frame,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    signal_summary = _summarize_groups(prepared, ["mean_reversion_signal"])
    strength_summary = _summarize_groups(prepared, ["mean_reversion_strength_bucket"])
    zscore_summary = _summarize_groups(prepared, ["mean_reversion_abs_zscore_bucket"])
    distance_summary = _summarize_groups(prepared, ["mean_reversion_distance_bucket"])
    direction_signal_summary = _summarize_groups(prepared, ["direction", "mean_reversion_signal"])
    regime_signal_summary = _summarize_groups(
        prepared,
        ["gamma_regime", "volatility_regime", "global_risk_state", "mean_reversion_signal"],
        min_rows=10,
    )
    runtime_signal_summary = _summarize_groups(prepared, ["runtime_composite_bucket", "mean_reversion_signal"])
    diagnostic_read = _diagnostic_read(signal_summary, strength_summary)
    ts = prepared.get("signal_ts", pd.Series(dtype="datetime64[ns, UTC]")).dropna()
    return {
        "report_type": "mean_reversion_evaluation",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "research_only": True,
            "live_behavior_changed": False,
            "report_date": report_date,
            "start_date": start_date,
            "end_date": end_date,
            "feature_fields": [
                "mean_reversion_signal",
                "mean_reversion_zscore",
                "mean_reversion_strength",
                "mean_reversion_distance_pct",
            ],
            "outcome_fields": [return_col for _, return_col, _ in HORIZONS],
            "promotion_guardrail": (
                "Mean-reversion features must remain research-only until point-in-time "
                "evaluation shows stable value by regime, direction, and score bucket."
            ),
        },
        "coverage": {
            "input_rows": int(len(frame)) if frame is not None else 0,
            "prepared_rows": int(len(prepared)),
            "feature_rows": int(prepared.get("has_mean_reversion_features", pd.Series(False)).sum())
            if not prepared.empty
            else 0,
            "sessions": int(prepared["signal_date"].nunique()) if "signal_date" in prepared.columns else 0,
            "time_range": {
                "start": ts.min().isoformat() if not ts.empty else None,
                "end": ts.max().isoformat() if not ts.empty else None,
            },
        },
        "diagnostic_read": diagnostic_read,
        "overall": _metric_bundle(prepared),
        "signal_summary": signal_summary,
        "strength_summary": strength_summary,
        "zscore_summary": zscore_summary,
        "distance_summary": distance_summary,
        "direction_signal_summary": direction_signal_summary,
        "regime_signal_summary": regime_signal_summary[:25],
        "runtime_signal_summary": runtime_signal_summary,
    }


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    if not rows:
        lines.append("| " + " | ".join(["N/A"] * len(columns)) + " |")
        return lines
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def render_mean_reversion_evaluation_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    lines = [
        "# Mean-Reversion Evaluation",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only report evaluates captured mean-reversion diagnostics against matured signal outcomes. It does not change live behavior.",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Prepared rows: `{coverage.get('prepared_rows')}`",
        f"- Feature rows: `{coverage.get('feature_rows')}`",
        f"- Sessions: `{coverage.get('sessions')}`",
        f"- Time range: `{(coverage.get('time_range') or {}).get('start')}` to `{(coverage.get('time_range') or {}).get('end')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Primary read: `{read.get('primary_read')}`",
        f"- Observations: `{', '.join(read.get('observations') or [])}`",
        f"- Mean-reversion 60m labels: `{read.get('mean_reversion_60m_labels')}`",
        f"- Mean-reversion 60m hit/return: `{read.get('mean_reversion_60m_hit_rate')}`% / `{read.get('mean_reversion_60m_return_bps')}` bps",
        f"- Trend-continuation 60m hit/return: `{read.get('trend_continuation_60m_hit_rate')}`% / `{read.get('trend_continuation_60m_return_bps')}` bps",
        "",
        "## By Signal",
        "",
        *_markdown_table(
            report.get("signal_summary") or [],
            [
                "mean_reversion_signal",
                "row_count",
                "label_count_60m",
                "hit_rate_60m",
                "avg_signed_return_60m_bps",
                "mfe_mae_ratio_60m",
                "avg_mean_reversion_strength",
            ],
        ),
        "",
        "## By Strength Bucket",
        "",
        *_markdown_table(
            report.get("strength_summary") or [],
            [
                "mean_reversion_strength_bucket",
                "row_count",
                "label_count_60m",
                "hit_rate_60m",
                "avg_signed_return_60m_bps",
                "mfe_mae_ratio_60m",
            ],
        ),
        "",
        "## By Direction And Signal",
        "",
        *_markdown_table(
            report.get("direction_signal_summary") or [],
            [
                "direction",
                "mean_reversion_signal",
                "row_count",
                "label_count_60m",
                "hit_rate_60m",
                "avg_signed_return_60m_bps",
                "mfe_mae_ratio_60m",
            ],
        ),
        "",
        "## Runtime Bucket x Signal",
        "",
        *_markdown_table(
            report.get("runtime_signal_summary") or [],
            [
                "runtime_composite_bucket",
                "mean_reversion_signal",
                "row_count",
                "label_count_60m",
                "hit_rate_60m",
                "avg_signed_return_60m_bps",
                "mfe_mae_ratio_60m",
            ],
        ),
        "",
        "## Guardrails",
        "",
        "- Mean-reversion evaluation is research-only.",
        "- It uses matured outcomes only in reports, never in live signal generation.",
        "- No mean-reversion feature should affect live scoring until forward evidence is stable by regime and direction.",
    ]
    return "\n".join(lines) + "\n"


def write_mean_reversion_evaluation_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_MEAN_REVERSION_REPORT_DIR,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = load_mean_reversion_dataset(dataset)
    report = build_mean_reversion_evaluation_report(
        frame,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    stem = f"mean_reversion_evaluation_{timestamp}"
    if report_date:
        stem += f"_{report_date.replace('-', '')}"

    json_path = output / f"{stem}.json"
    markdown_path = output / f"{stem}.md"
    signal_csv_path = output / f"{stem}_signal_summary.csv"
    strength_csv_path = output / f"{stem}_strength_summary.csv"
    zscore_csv_path = output / f"{stem}_zscore_summary.csv"
    direction_csv_path = output / f"{stem}_direction_signal_summary.csv"

    _atomic_write_json(json_path, report)
    _atomic_write_text(markdown_path, render_mean_reversion_evaluation_markdown(report))
    _atomic_write_csv(signal_csv_path, report.get("signal_summary") or [])
    _atomic_write_csv(strength_csv_path, report.get("strength_summary") or [])
    _atomic_write_csv(zscore_csv_path, report.get("zscore_summary") or [])
    _atomic_write_csv(direction_csv_path, report.get("direction_signal_summary") or [])

    latest_json_path = output / "latest_mean_reversion_evaluation.json"
    latest_markdown_path = output / "latest_mean_reversion_evaluation.md"
    latest_signal_csv_path = output / "latest_mean_reversion_signal_summary.csv"
    latest_strength_csv_path = output / "latest_mean_reversion_strength_summary.csv"
    latest_zscore_csv_path = output / "latest_mean_reversion_zscore_summary.csv"
    latest_direction_csv_path = output / "latest_mean_reversion_direction_signal_summary.csv"
    _atomic_write_json(latest_json_path, report)
    _atomic_write_text(latest_markdown_path, render_mean_reversion_evaluation_markdown(report))
    _atomic_write_csv(latest_signal_csv_path, report.get("signal_summary") or [])
    _atomic_write_csv(latest_strength_csv_path, report.get("strength_summary") or [])
    _atomic_write_csv(latest_zscore_csv_path, report.get("zscore_summary") or [])
    _atomic_write_csv(latest_direction_csv_path, report.get("direction_signal_summary") or [])

    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="mean_reversion_evaluation",
        report_date=report_date,
        mode="research_only",
        run_evaluation=True,
        narrative=False,
    )
    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "signal_csv_path": str(signal_csv_path),
        "strength_csv_path": str(strength_csv_path),
        "zscore_csv_path": str(zscore_csv_path),
        "direction_csv_path": str(direction_csv_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
        "latest_signal_csv_path": str(latest_signal_csv_path),
        "latest_strength_csv_path": str(latest_strength_csv_path),
        "latest_zscore_csv_path": str(latest_zscore_csv_path),
        "latest_direction_csv_path": str(latest_direction_csv_path),
        "manifest_path": str(manifest_path),
    }

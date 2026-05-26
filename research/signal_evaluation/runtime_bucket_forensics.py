"""Runtime composite bucket forensics.

This research-only report explains why a runtime score bucket performed better
or worse than nearby buckets.  It uses post-evaluation outcomes only as labels;
candidate explanatory fields are live-time fields.
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
from research.signal_evaluation.runtime_blindspot_feature_audit import (
    USE_COLUMNS as BLINDSPOT_AUDIT_COLUMNS,
    prepare_runtime_blindspot_feature_frame,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_BUCKET_FORENSICS_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_bucket_forensics"
)

HORIZONS: tuple[tuple[str, str, str], ...] = (
    ("5m", "signed_return_5m_bps", "correct_5m"),
    ("15m", "signed_return_15m_bps", "correct_15m"),
    ("30m", "signed_return_30m_bps", "correct_30m"),
    ("60m", "signed_return_60m_bps", "correct_60m"),
    ("120m", "signed_return_120m_bps", "correct_120m"),
    ("session_close", "signed_return_session_close_bps", "correct_session_close"),
)

EXTRA_COLUMNS = (
    "composite_signal_score",
    "runtime_composite_score",
    "mfe_60m_bps",
    "mae_60m_bps",
    *[column for _, return_col, hit_col in HORIZONS for column in (return_col, hit_col)],
)

SLICE_COLUMNS = (
    "direction",
    "volume_pcr_regime",
    "gamma_regime",
    "volatility_regime",
    "spot_vs_flip",
    "wall_context_state",
    "nearest_wall_bucket",
    "max_pain_zone",
    "confirmation_status",
    "ta_candle_state",
    "ta_entry_timing_state",
    "final_flow_signal",
    "provider_quality_mode",
    "provider_execution_context",
)

USE_COLUMNS = tuple(dict.fromkeys((*BLINDSPOT_AUDIT_COLUMNS, *EXTRA_COLUMNS, *SLICE_COLUMNS)))

INTERSECTION_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("direction_x_pcr", ("direction", "volume_pcr_regime")),
    ("direction_x_gamma", ("direction", "gamma_regime")),
    ("direction_x_confirmation", ("direction", "confirmation_status")),
    ("direction_x_candle", ("direction", "ta_entry_timing_state")),
    ("pcr_x_gamma", ("volume_pcr_regime", "gamma_regime")),
    ("confirmation_x_candle", ("confirmation_status", "ta_entry_timing_state")),
    ("gamma_x_wall", ("gamma_regime", "wall_context_state")),
    ("pcr_x_wall", ("volume_pcr_regime", "wall_context_state")),
)

BUCKET_BINS = [-0.01, 40, 50, 60, 70, 80, 100]
BUCKET_LABELS = ["0-40", "40-50", "50-60", "60-70", "70-80", "80-100"]


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if pd.isna(number) or not np.isfinite(number):
        return default
    return number


def _round(value: Any, digits: int = 3) -> float | None:
    number = _safe_float(value, None)
    return round(number, digits) if number is not None else None


def _mean(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.mean())


def _normalize_text(series: pd.Series, default: str = "UNKNOWN") -> pd.Series:
    return (
        series.astype("object")
        .where(series.notna(), default)
        .astype(str)
        .str.strip()
        .replace({"": default, "nan": default, "NaN": default, "None": default})
    )


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
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


def load_runtime_bucket_forensics_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset = Path(path)
    if not dataset.exists():
        raise FileNotFoundError(f"Signal dataset not found: {dataset}")
    return pd.read_csv(dataset, usecols=lambda column: column in USE_COLUMNS, low_memory=False)


def prepare_runtime_bucket_forensics_frame(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
) -> pd.DataFrame:
    working = prepare_runtime_blindspot_feature_frame(frame, report_date=report_date).copy()
    missing = [column for column in EXTRA_COLUMNS if column not in working.columns]
    if missing:
        working = pd.concat([working, pd.DataFrame({column: pd.NA for column in missing}, index=working.index)], axis=1)
    for column in EXTRA_COLUMNS:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    for column in SLICE_COLUMNS:
        if column not in working.columns:
            working[column] = pd.NA
        working[column] = _normalize_text(working[column])
    comparable = working.loc[
        working.get("runtime_composite_score", pd.Series(index=working.index)).between(0, 100)
        & working.get("composite_signal_score", pd.Series(index=working.index)).between(0, 100)
    ].copy()
    comparable["runtime_10pt_bucket"] = pd.cut(
        comparable["runtime_composite_score"],
        bins=BUCKET_BINS,
        labels=BUCKET_LABELS,
        include_lowest=True,
    )
    return comparable


def _mfe_mae_ratio(frame: pd.DataFrame) -> float | None:
    mfe = pd.to_numeric(frame.get("mfe_60m_bps", pd.Series(dtype=float)), errors="coerce")
    mae = pd.to_numeric(frame.get("mae_60m_bps", pd.Series(dtype=float)), errors="coerce").abs()
    avg_mfe = _mean(mfe)
    avg_mae = _mean(mae)
    if avg_mfe is None or avg_mae is None or avg_mae <= 0:
        return None
    return avg_mfe / avg_mae


def _top_value(frame: pd.DataFrame, column: str) -> str | None:
    if column not in frame.columns or frame.empty:
        return None
    counts = _normalize_text(frame[column]).value_counts(dropna=False)
    if counts.empty:
        return None
    value = str(counts.index[0])
    share = float(counts.iloc[0] / len(frame) * 100.0)
    return f"{value} ({share:.1f}%)"


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "row_count": int(len(frame)),
        "avg_runtime": _round(_mean(frame.get("runtime_composite_score", pd.Series(dtype=float)))),
        "avg_expost": _round(_mean(frame.get("composite_signal_score", pd.Series(dtype=float)))),
        "median_expost": _round(pd.to_numeric(frame.get("composite_signal_score", pd.Series(dtype=float)), errors="coerce").median()),
        "avg_volume_pcr_atm": _round(_mean(frame.get("volume_pcr_atm", pd.Series(dtype=float)))),
        "avg_volume_pcr": _round(_mean(frame.get("volume_pcr", pd.Series(dtype=float)))),
        "avg_mfe_60m_bps": _round(_mean(frame.get("mfe_60m_bps", pd.Series(dtype=float)))),
        "avg_mae_60m_bps": _round(_mean(frame.get("mae_60m_bps", pd.Series(dtype=float)))),
        "mfe_mae_ratio_60m": _round(_mfe_mae_ratio(frame)),
        "top_direction": _top_value(frame, "direction"),
        "top_pcr_regime": _top_value(frame, "volume_pcr_regime"),
        "top_gamma_regime": _top_value(frame, "gamma_regime"),
        "top_confirmation": _top_value(frame, "confirmation_status"),
        "top_candle_state": _top_value(frame, "ta_entry_timing_state"),
        "top_wall_context": _top_value(frame, "wall_context_state"),
        "top_provider_context": _top_value(frame, "provider_execution_context"),
    }
    for horizon, return_col, hit_col in HORIZONS:
        returns = pd.to_numeric(frame.get(return_col, pd.Series(index=frame.index)), errors="coerce")
        hits = pd.to_numeric(frame.get(hit_col, pd.Series(index=frame.index)), errors="coerce")
        payload[f"label_count_{horizon}"] = int(hits.notna().sum())
        payload[f"hit_rate_{horizon}"] = _round(float(hits.dropna().mean() * 100.0)) if hits.notna().any() else None
        payload[f"avg_return_{horizon}_bps"] = _round(float(returns.dropna().mean())) if returns.notna().any() else None
    return payload


def _bucket_summary(comparable: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket, group in comparable.groupby("runtime_10pt_bucket", observed=True):
        if group.empty:
            continue
        payload = {"runtime_bucket": str(bucket)}
        payload.update(_metrics(group))
        rows.append(payload)
    return rows


def _slice_summary(target: pd.DataFrame, *, min_rows: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for column in SLICE_COLUMNS:
        if column not in target.columns:
            continue
        normalized = _normalize_text(target[column])
        for value, index in normalized.groupby(normalized, dropna=False).groups.items():
            group = target.loc[index]
            if len(group) < min_rows:
                continue
            payload = {"slice_column": column, "slice_value": str(value)}
            payload.update(_metrics(group))
            rows.append(payload)
    return sorted(
        rows,
        key=lambda row: (
            -(row.get("label_count_60m") or 0),
            -float(row.get("avg_return_60m_bps") or -1e9),
            str(row.get("slice_column")),
        ),
    )


def _intersection_summary(target: pd.DataFrame, *, min_rows: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, columns in INTERSECTION_SPECS:
        if any(column not in target.columns for column in columns):
            continue
        grouped = target.groupby(list(columns), dropna=False)
        for keys, group in grouped:
            if len(group) < min_rows:
                continue
            if not isinstance(keys, tuple):
                keys = (keys,)
            payload = {
                "intersection": name,
                "condition": " | ".join(f"{column}={value}" for column, value in zip(columns, keys, strict=False)),
            }
            payload.update(_metrics(group))
            rows.append(payload)
    return sorted(
        rows,
        key=lambda row: (
            -float(row.get("avg_return_60m_bps") or -1e9),
            -float(row.get("hit_rate_60m") or -1e9),
            -(row.get("row_count") or 0),
        ),
    )


def _bucket_lookup(bucket_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("runtime_bucket")): row for row in bucket_rows}


def _contrast_rows(bucket_rows: list[dict[str, Any]], target_bucket: str) -> list[dict[str, Any]]:
    lookup = _bucket_lookup(bucket_rows)
    target = lookup.get(target_bucket)
    if not target:
        return []
    rows = []
    for bucket, row in lookup.items():
        if bucket == target_bucket:
            continue
        rows.append(
            {
                "comparison_bucket": bucket,
                "target_bucket": target_bucket,
                "row_count": row.get("row_count"),
                "target_row_count": target.get("row_count"),
                "delta_hit_rate_60m": _round(
                    (_safe_float(target.get("hit_rate_60m"), 0.0) or 0.0)
                    - (_safe_float(row.get("hit_rate_60m"), 0.0) or 0.0)
                )
                if target.get("hit_rate_60m") is not None and row.get("hit_rate_60m") is not None
                else None,
                "delta_avg_return_60m_bps": _round(
                    (_safe_float(target.get("avg_return_60m_bps"), 0.0) or 0.0)
                    - (_safe_float(row.get("avg_return_60m_bps"), 0.0) or 0.0)
                )
                if target.get("avg_return_60m_bps") is not None and row.get("avg_return_60m_bps") is not None
                else None,
                "delta_expost": _round(
                    (_safe_float(target.get("avg_expost"), 0.0) or 0.0)
                    - (_safe_float(row.get("avg_expost"), 0.0) or 0.0)
                )
                if target.get("avg_expost") is not None and row.get("avg_expost") is not None
                else None,
            }
        )
    return sorted(rows, key=lambda row: abs(float(row.get("delta_avg_return_60m_bps") or 0.0)), reverse=True)


def _best_horizon(metrics: dict[str, Any]) -> dict[str, Any] | None:
    candidates = []
    for horizon, _, _ in HORIZONS:
        value = _safe_float(metrics.get(f"avg_return_{horizon}_bps"))
        count = int(metrics.get(f"label_count_{horizon}") or 0)
        if value is None or count <= 0:
            continue
        candidates.append(
            {
                "horizon": horizon,
                "label_count": count,
                "avg_return_bps": _round(value),
                "hit_rate": metrics.get(f"hit_rate_{horizon}"),
            }
        )
    if not candidates:
        return None
    return max(candidates, key=lambda row: float(row.get("avg_return_bps") or -1e9))


def _diagnostic_read(report: dict[str, Any]) -> dict[str, Any]:
    target = report.get("target_bucket_summary") or {}
    intersections = report.get("target_intersections") or []
    contrast = report.get("bucket_contrasts") or []
    best_intersection = next(
        (
            row
            for row in intersections
            if int(row.get("label_count_60m") or 0) >= int((report.get("methodology") or {}).get("min_intersection_rows") or 0)
        ),
        None,
    )
    best_horizon = _best_horizon(target)
    return {
        "target_bucket": (report.get("methodology") or {}).get("target_bucket"),
        "target_rows": target.get("row_count"),
        "target_hit_rate_60m": target.get("hit_rate_60m"),
        "target_avg_return_60m_bps": target.get("avg_return_60m_bps"),
        "target_avg_expost": target.get("avg_expost"),
        "target_best_horizon": best_horizon,
        "strongest_contrast": contrast[0] if contrast else None,
        "best_target_intersection": best_intersection,
        "primary_read": _primary_read(target, best_horizon),
    }


def _primary_read(target: dict[str, Any], best_horizon: dict[str, Any] | None) -> str:
    rows = int(target.get("row_count") or 0)
    hit = _safe_float(target.get("hit_rate_60m"), 0.0) or 0.0
    ret = _safe_float(target.get("avg_return_60m_bps"), 0.0) or 0.0
    if rows < 20:
        return "TARGET_BUCKET_SAMPLE_SMALL"
    if hit >= 60.0 and ret > 0:
        if best_horizon and best_horizon.get("horizon") == "session_close":
            return "TARGET_BUCKET_DURABLE_EDGE"
        return "TARGET_BUCKET_TACTICAL_EDGE"
    if hit < 50.0 or ret < 0:
        return "TARGET_BUCKET_WEAK_OR_ADVERSE"
    return "TARGET_BUCKET_MIXED"


def build_runtime_bucket_forensics_report(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    target_bucket: str = "50-60",
    min_slice_rows: int = 5,
    min_intersection_rows: int = 3,
) -> dict[str, Any]:
    comparable = prepare_runtime_bucket_forensics_frame(frame, report_date=report_date)
    target = comparable.loc[comparable["runtime_10pt_bucket"].astype(str).eq(target_bucket)].copy()
    bucket_rows = _bucket_summary(comparable)
    target_summary = _metrics(target) if not target.empty else {"row_count": 0}
    report = {
        "report_type": "runtime_bucket_forensics",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "report_date": report_date,
            "target_bucket": target_bucket,
            "bucket_definition": "pd.cut(runtime_composite_score, [-0.01,40,50,60,70,80,100])",
            "min_slice_rows": int(min_slice_rows),
            "min_intersection_rows": int(min_intersection_rows),
            "hindsight_guardrail": (
                "Outcomes and composite_signal_score are used only as research labels. "
                "Candidate explanations are live-time fields."
            ),
        },
        "coverage": {
            "input_rows": int(len(frame)),
            "rows_after_date_filter": int(len(comparable)),
            "comparable_rows": int(len(comparable)),
            "target_bucket_rows": int(len(target)),
            "start_timestamp": comparable["signal_ts"].dropna().min().isoformat()
            if "signal_ts" in comparable.columns and comparable["signal_ts"].notna().any()
            else None,
            "end_timestamp": comparable["signal_ts"].dropna().max().isoformat()
            if "signal_ts" in comparable.columns and comparable["signal_ts"].notna().any()
            else None,
        },
        "runtime_bucket_summary": bucket_rows,
        "target_bucket_summary": target_summary,
        "bucket_contrasts": _contrast_rows(bucket_rows, target_bucket),
        "target_slices": _slice_summary(target, min_rows=min_slice_rows),
        "target_intersections": _intersection_summary(target, min_rows=min_intersection_rows),
    }
    report["diagnostic_read"] = _diagnostic_read(report)
    return _json_ready(report)


def render_runtime_bucket_forensics_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    target = report.get("target_bucket_summary") or {}
    lines = [
        "# Runtime Bucket Forensics",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only report compares runtime composite buckets, then zooms into the target bucket "
        "using live-time context fields. Outcomes are labels only; this report does not change runtime logic.",
        "",
        "## Coverage",
        "",
        f"- Rows after date filter: `{coverage.get('rows_after_date_filter')}`",
        f"- Comparable rows: `{coverage.get('comparable_rows')}`",
        f"- Target bucket rows: `{coverage.get('target_bucket_rows')}`",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Primary read: `{read.get('primary_read')}`",
        f"- Target bucket: `{read.get('target_bucket')}`",
        f"- Target 60m hit rate: `{read.get('target_hit_rate_60m')}`",
        f"- Target 60m avg return: `{read.get('target_avg_return_60m_bps')}` bps",
        f"- Target avg ex-post score: `{read.get('target_avg_expost')}`",
        f"- Best horizon: `{read.get('target_best_horizon')}`",
        f"- Strongest contrast: `{read.get('strongest_contrast')}`",
        f"- Best target intersection: `{read.get('best_target_intersection')}`",
        "",
        "## Target Bucket Snapshot",
        "",
    ]
    target_columns = [
        "row_count",
        "avg_runtime",
        "avg_expost",
        "avg_volume_pcr_atm",
        "top_direction",
        "top_pcr_regime",
        "top_gamma_regime",
        "top_confirmation",
        "top_candle_state",
        "top_provider_context",
    ]
    lines.extend(_markdown_table([target], target_columns))
    lines.extend(["", "## Runtime Bucket Summary", ""])
    lines.extend(
        _markdown_table(
            report.get("runtime_bucket_summary") or [],
            [
                "runtime_bucket",
                "row_count",
                "avg_runtime",
                "avg_expost",
                "hit_rate_15m",
                "avg_return_15m_bps",
                "hit_rate_30m",
                "avg_return_30m_bps",
                "hit_rate_60m",
                "avg_return_60m_bps",
                "hit_rate_120m",
                "avg_return_120m_bps",
                "hit_rate_session_close",
                "avg_return_session_close_bps",
                "mfe_mae_ratio_60m",
            ],
        )
    )
    lines.extend(["", "## Bucket Contrasts", ""])
    lines.extend(
        _markdown_table(
            report.get("bucket_contrasts") or [],
            [
                "comparison_bucket",
                "target_bucket",
                "row_count",
                "target_row_count",
                "delta_hit_rate_60m",
                "delta_avg_return_60m_bps",
                "delta_expost",
            ],
        )
    )
    lines.extend(["", "## Target Bucket Slices", ""])
    lines.extend(
        _markdown_table(
            report.get("target_slices") or [],
            [
                "slice_column",
                "slice_value",
                "row_count",
                "avg_runtime",
                "avg_expost",
                "avg_volume_pcr_atm",
                "hit_rate_60m",
                "avg_return_60m_bps",
                "mfe_mae_ratio_60m",
                "avg_return_session_close_bps",
            ],
            max_rows=40,
        )
    )
    lines.extend(["", "## Target Bucket Intersections", ""])
    lines.extend(
        _markdown_table(
            report.get("target_intersections") or [],
            [
                "intersection",
                "condition",
                "row_count",
                "avg_runtime",
                "avg_expost",
                "avg_volume_pcr_atm",
                "hit_rate_60m",
                "avg_return_60m_bps",
                "mfe_mae_ratio_60m",
                "avg_return_session_close_bps",
            ],
            max_rows=40,
        )
    )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This report is research-only and does not change runtime score calculation.",
            "- Do not use `composite_signal_score` directly in live logic.",
            "- Promote only after fresh-forward helped/hurt validation across multiple sessions.",
            "",
        ]
    )
    return "\n".join(lines)


def write_runtime_bucket_forensics_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_BUCKET_FORENSICS_REPORT_DIR,
    report_date: str | None = None,
    target_bucket: str = "50-60",
    min_slice_rows: int = 5,
    min_intersection_rows: int = 3,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = load_runtime_bucket_forensics_dataset(dataset)
    report = build_runtime_bucket_forensics_report(
        frame,
        report_date=report_date,
        target_bucket=target_bucket,
        min_slice_rows=min_slice_rows,
        min_intersection_rows=min_intersection_rows,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    json_path = output / f"runtime_bucket_forensics_{timestamp}.json"
    markdown_path = output / f"runtime_bucket_forensics_{timestamp}.md"
    latest_json_path = output / "latest_runtime_bucket_forensics.json"
    latest_markdown_path = output / "latest_runtime_bucket_forensics.md"
    bucket_csv_path = output / f"runtime_bucket_forensics_{timestamp}_buckets.csv"
    latest_bucket_csv_path = output / "latest_runtime_bucket_forensics_buckets.csv"
    slice_csv_path = output / f"runtime_bucket_forensics_{timestamp}_slices.csv"
    latest_slice_csv_path = output / "latest_runtime_bucket_forensics_slices.csv"
    intersection_csv_path = output / f"runtime_bucket_forensics_{timestamp}_intersections.csv"
    latest_intersection_csv_path = output / "latest_runtime_bucket_forensics_intersections.csv"

    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_runtime_bucket_forensics_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")
    pd.DataFrame(report.get("runtime_bucket_summary") or []).to_csv(bucket_csv_path, index=False)
    pd.DataFrame(report.get("runtime_bucket_summary") or []).to_csv(latest_bucket_csv_path, index=False)
    pd.DataFrame(report.get("target_slices") or []).to_csv(slice_csv_path, index=False)
    pd.DataFrame(report.get("target_slices") or []).to_csv(latest_slice_csv_path, index=False)
    pd.DataFrame(report.get("target_intersections") or []).to_csv(intersection_csv_path, index=False)
    pd.DataFrame(report.get("target_intersections") or []).to_csv(latest_intersection_csv_path, index=False)
    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="runtime_bucket_forensics",
        report_date=report_date,
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
        "bucket_csv_path": str(bucket_csv_path),
        "latest_bucket_csv_path": str(latest_bucket_csv_path),
        "slice_csv_path": str(slice_csv_path),
        "latest_slice_csv_path": str(latest_slice_csv_path),
        "intersection_csv_path": str(intersection_csv_path),
        "latest_intersection_csv_path": str(latest_intersection_csv_path),
        "manifest_path": str(manifest_path),
    }

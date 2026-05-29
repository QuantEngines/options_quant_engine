"""Forward monitor for live probability calibration.

This module is research-only. It tracks whether runtime move probabilities are
underconfident or overconfident by session, probability bucket, direction, and
regime after labels mature. It does not change runtime probabilities,
parameter packs, data-source routing, or execution behavior.
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
from research.signal_evaluation.signal_quality_model_audit import (
    DEFAULT_LABEL_FIELD,
    DEFAULT_PROBABILITY_FIELD,
    DEFAULT_RETURN_FIELD,
    _atomic_write_csv,
    _atomic_write_text,
    _prepare_labeled_frame,
    _probability_series,
    _round_or_none,
    _sanitize_value,
)
from utils.timestamp_helpers import coerce_timestamp_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROBABILITY_CALIBRATION_FORWARD_MONITOR_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "probability_calibration_forward_monitor"
)

DEFAULT_PROBABILITY_BUCKET_EDGES = (0.0, 0.35, 0.50, 0.65, 0.80, 1.000001)
DEFAULT_PROBABILITY_BUCKET_LABELS = ("0_35", "35_50", "50_65", "65_80", "80_100")
DEFAULT_GROUP_FIELDS = (
    "direction",
    "gamma_regime",
    "volatility_regime",
    "macro_regime",
    "global_risk_state",
    "trade_status",
    "runtime_composite_observation_tier",
    "provider_quality_mode",
    "option_source",
)
DEFAULT_MIN_LABELED_ROWS = 50
DEFAULT_MIN_SESSION_COUNT = 3
DEFAULT_MIN_SLICE_LABELS = 15
DEFAULT_ALERT_ABS_GAP = 0.10
DEFAULT_SEVERE_ABS_GAP = 0.20


def _load_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset = Path(path)
    if not dataset.exists():
        return pd.DataFrame()
    return pd.read_csv(dataset, low_memory=False)


def _normalize_text(series: pd.Series, default: str = "UNKNOWN") -> pd.Series:
    return (
        series.astype("object")
        .where(series.notna(), default)
        .astype(str)
        .str.strip()
        .replace({"": default, "nan": default, "NaN": default, "None": default})
    )


def _safe_mean(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.mean())


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if pd.isna(number) or not np.isfinite(number):
        return default
    return number


def _filter_date_range(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    working = frame.copy()
    if report_date:
        return working.loc[working["signal_date"] == str(report_date)].copy()
    if start_date:
        working = working.loc[working["signal_date"] >= str(start_date)].copy()
    if end_date:
        working = working.loc[working["signal_date"] <= str(end_date)].copy()
    return working


def _probability_bucket(probability: pd.Series) -> pd.Series:
    return pd.cut(
        probability,
        bins=list(DEFAULT_PROBABILITY_BUCKET_EDGES),
        labels=list(DEFAULT_PROBABILITY_BUCKET_LABELS),
        include_lowest=True,
        right=False,
    ).astype("string")


def prepare_probability_calibration_forward_monitor_frame(
    frame: pd.DataFrame,
    *,
    probability_field: str = DEFAULT_PROBABILITY_FIELD,
    label_field: str = DEFAULT_LABEL_FIELD,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return quality-labeled rows ready for forward calibration monitoring."""
    labeled = _prepare_labeled_frame(frame if frame is not None else pd.DataFrame())
    if labeled.empty:
        return labeled.assign(
            signal_ts=pd.Series(dtype="datetime64[ns, UTC]"),
            signal_date=pd.Series(dtype="object"),
            _probability=pd.Series(dtype="float64"),
            _label=pd.Series(dtype="float64"),
            probability_bucket=pd.Series(dtype="object"),
            monitor_eligible=pd.Series(dtype=bool),
        )

    working = labeled.copy()
    if "signal_timestamp" in working.columns:
        working["signal_ts"] = coerce_timestamp_series(working["signal_timestamp"])
    else:
        working["signal_ts"] = pd.Series(pd.NaT, index=working.index, dtype="datetime64[ns, UTC]")
    local_ts = working["signal_ts"].dt.tz_convert("Asia/Kolkata")
    working["signal_date"] = local_ts.dt.strftime("%Y-%m-%d")
    working["signal_date"] = working["signal_date"].fillna("UNKNOWN")
    working = _filter_date_range(working, report_date=report_date, start_date=start_date, end_date=end_date)

    working["_probability"] = _probability_series(working, probability_field)
    working["_label"] = pd.to_numeric(working.get(label_field, pd.Series(index=working.index)), errors="coerce")
    working["_return"] = pd.to_numeric(
        working.get(DEFAULT_RETURN_FIELD, pd.Series(index=working.index)),
        errors="coerce",
    )
    working["probability_bucket"] = _probability_bucket(working["_probability"])
    working["monitor_eligible"] = working["_probability"].notna() & working["_label"].notna()
    return working.reset_index(drop=True)


def _calibration_status(
    *,
    label_count: int,
    calibration_gap: float | None,
    abs_calibration_gap: float | None,
    min_labels: int,
    alert_abs_gap: float,
    severe_abs_gap: float,
) -> str:
    if label_count <= 0:
        return "NO_EVIDENCE"
    if label_count < int(min_labels):
        return "INSUFFICIENT_EVIDENCE"
    gap = _safe_float(calibration_gap, 0.0) or 0.0
    abs_gap = _safe_float(abs_calibration_gap, 0.0) or 0.0
    if abs_gap >= float(severe_abs_gap):
        return "SEVERE_UNDERCONFIDENCE" if gap < 0 else "SEVERE_OVERCONFIDENCE"
    if abs_gap >= float(alert_abs_gap):
        return "UNDERCONFIDENCE" if gap < 0 else "OVERCONFIDENCE"
    return "CALIBRATED"


def _metric_row(
    frame: pd.DataFrame,
    *,
    min_labels: int,
    alert_abs_gap: float,
    severe_abs_gap: float,
) -> dict[str, Any]:
    valid = frame["_probability"].notna() & frame["_label"].notna()
    label_count = int(valid.sum())
    if label_count <= 0:
        return {
            "row_count": int(len(frame)),
            "label_count": 0,
            "mean_predicted_probability": None,
            "actual_hit_rate": None,
            "calibration_gap": None,
            "abs_calibration_gap": None,
            "brier_score": None,
            "avg_signed_return_60m_bps": None,
            "avg_runtime_composite_score": _round_or_none(
                _safe_mean(frame.get("runtime_composite_score", pd.Series(index=frame.index))),
                4,
            ),
            "avg_trade_strength": _round_or_none(
                _safe_mean(frame.get("trade_strength", pd.Series(index=frame.index))),
                4,
            ),
            "mfe_mae_ratio_60m": None,
            "calibration_status": "NO_EVIDENCE",
        }

    probability = frame.loc[valid, "_probability"]
    labels = frame.loc[valid, "_label"].clip(lower=0.0, upper=1.0)
    returns = pd.to_numeric(frame.loc[valid, "_return"], errors="coerce")
    mean_predicted = float(probability.mean())
    actual_hit_rate = float(labels.mean())
    gap = mean_predicted - actual_hit_rate
    brier = float(((probability - labels) ** 2).mean())
    mfe = _safe_mean(frame.loc[valid].get("mfe_60m_bps", pd.Series(index=frame.loc[valid].index)))
    mae = _safe_mean(pd.to_numeric(frame.loc[valid].get("mae_60m_bps", pd.Series(index=frame.loc[valid].index)), errors="coerce").abs())
    mfe_mae_ratio = (mfe / mae) if mfe is not None and mae is not None and mae > 0 else None
    return {
        "row_count": int(len(frame)),
        "label_count": label_count,
        "mean_predicted_probability": _round_or_none(mean_predicted, 6),
        "actual_hit_rate": _round_or_none(actual_hit_rate, 6),
        "calibration_gap": _round_or_none(gap, 6),
        "abs_calibration_gap": _round_or_none(abs(gap), 6),
        "brier_score": _round_or_none(brier, 8),
        "avg_signed_return_60m_bps": _round_or_none(_safe_mean(returns), 4),
        "avg_runtime_composite_score": _round_or_none(
            _safe_mean(frame.get("runtime_composite_score", pd.Series(index=frame.index))),
            4,
        ),
        "avg_trade_strength": _round_or_none(
            _safe_mean(frame.get("trade_strength", pd.Series(index=frame.index))),
            4,
        ),
        "mfe_mae_ratio_60m": _round_or_none(mfe_mae_ratio, 4),
        "calibration_status": _calibration_status(
            label_count=label_count,
            calibration_gap=gap,
            abs_calibration_gap=abs(gap),
            min_labels=min_labels,
            alert_abs_gap=alert_abs_gap,
            severe_abs_gap=severe_abs_gap,
        ),
    }


def _ece(rows: list[dict[str, Any]]) -> float | None:
    total = sum(int(row.get("label_count") or 0) for row in rows)
    if total <= 0:
        return None
    weighted = 0.0
    for row in rows:
        count = int(row.get("label_count") or 0)
        gap = _safe_float(row.get("abs_calibration_gap"), 0.0) or 0.0
        weighted += (count / float(total)) * gap
    return weighted


def _group_rows(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    slice_type: str,
    min_labels: int,
    alert_abs_gap: float,
    severe_abs_gap: float,
    top_n: int = 200,
) -> list[dict[str, Any]]:
    available = [column for column in columns if column in frame.columns]
    if frame.empty or not available:
        return []
    working = frame.copy()
    for column in available:
        working[column] = _normalize_text(working[column])

    rows: list[dict[str, Any]] = []
    for keys, group in working.groupby(available, dropna=False, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {
            "slice_type": slice_type,
            "slice_key": " / ".join(str(value) for value in keys),
        }
        for column, value in zip(available, keys, strict=False):
            row[column] = str(value)
        row.update(
            _metric_row(
                group,
                min_labels=min_labels,
                alert_abs_gap=alert_abs_gap,
                severe_abs_gap=severe_abs_gap,
            )
        )
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("label_count") or 0),
            -_safe_float(row.get("abs_calibration_gap"), 0.0),
            str(row.get("slice_key") or ""),
        ),
    )[:top_n]


def _slice_rows(
    frame: pd.DataFrame,
    *,
    group_fields: tuple[str, ...],
    min_labels: int,
    alert_abs_gap: float,
    severe_abs_gap: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in group_fields:
        if field not in frame.columns:
            continue
        rows.extend(
            _group_rows(
                frame,
                [field],
                slice_type=field,
                min_labels=min_labels,
                alert_abs_gap=alert_abs_gap,
                severe_abs_gap=severe_abs_gap,
                top_n=50,
            )
        )
        rows.extend(
            _group_rows(
                frame,
                [field, "probability_bucket"],
                slice_type=f"{field}_x_probability_bucket",
                min_labels=min_labels,
                alert_abs_gap=alert_abs_gap,
                severe_abs_gap=severe_abs_gap,
                top_n=50,
            )
        )
    return rows


def _status_priority(status: str) -> int:
    return {
        "SEVERE_UNDERCONFIDENCE": 0,
        "SEVERE_OVERCONFIDENCE": 0,
        "UNDERCONFIDENCE": 1,
        "OVERCONFIDENCE": 1,
        "CALIBRATED": 2,
        "INSUFFICIENT_EVIDENCE": 3,
        "NO_EVIDENCE": 4,
    }.get(str(status), 5)


def _flagged_slices(
    rows: list[dict[str, Any]],
    *,
    min_slice_labels: int,
    alert_abs_gap: float,
) -> list[dict[str, Any]]:
    flagged = [
        row
        for row in rows
        if int(row.get("label_count") or 0) >= int(min_slice_labels)
        and (_safe_float(row.get("abs_calibration_gap"), 0.0) or 0.0) >= float(alert_abs_gap)
    ]
    return sorted(
        flagged,
        key=lambda row: (
            _status_priority(str(row.get("calibration_status"))),
            -_safe_float(row.get("abs_calibration_gap"), 0.0),
            -int(row.get("label_count") or 0),
        ),
    )[:50]


def _monitor_status(
    *,
    summary: dict[str, Any],
    session_count: int,
    min_labeled_rows: int,
    min_session_count: int,
    flagged: list[dict[str, Any]],
    bucket_ece: float | None,
    alert_abs_gap: float,
    severe_abs_gap: float,
) -> str:
    label_count = int(summary.get("label_count") or 0)
    if label_count <= 0:
        return "CALIBRATION_FORWARD_NO_EVIDENCE"
    if label_count < int(min_labeled_rows) or session_count < int(min_session_count):
        return "CALIBRATION_FORWARD_ACCUMULATING"
    if any(str(row.get("calibration_status", "")).startswith("SEVERE_") for row in flagged):
        return "CALIBRATION_FORWARD_ALERT"
    if bucket_ece is not None and bucket_ece >= float(severe_abs_gap):
        return "CALIBRATION_FORWARD_ALERT"
    if flagged or (bucket_ece is not None and bucket_ece >= float(alert_abs_gap)):
        return "CALIBRATION_FORWARD_WATCH"
    return "CALIBRATION_FORWARD_OK"


def _bucket_pattern(bucket_rows: list[dict[str, Any]], *, alert_abs_gap: float) -> dict[str, Any]:
    low_buckets = {"0_35", "35_50"}
    high_buckets = {"65_80", "80_100"}
    low_under = [
        row
        for row in bucket_rows
        if row.get("probability_bucket") in low_buckets
        and (_safe_float(row.get("calibration_gap"), 0.0) or 0.0) <= -float(alert_abs_gap)
    ]
    high_over = [
        row
        for row in bucket_rows
        if row.get("probability_bucket") in high_buckets
        and (_safe_float(row.get("calibration_gap"), 0.0) or 0.0) >= float(alert_abs_gap)
    ]
    return {
        "low_bucket_underconfidence": bool(low_under),
        "high_bucket_overconfidence": bool(high_over),
        "non_monotonic_calibration_risk": bool(low_under and high_over),
        "low_underconfidence_buckets": [row.get("probability_bucket") for row in low_under],
        "high_overconfidence_buckets": [row.get("probability_bucket") for row in high_over],
    }


def _recommended_actions(report: dict[str, Any]) -> list[str]:
    status = str(report.get("monitor_status") or "")
    read = report.get("diagnostic_read") or {}
    pattern = report.get("bucket_pattern") or {}
    actions: list[str] = []
    if status == "CALIBRATION_FORWARD_NO_EVIDENCE":
        return ["Collect quality-approved labeled rows before making probability-calibration decisions."]
    if status == "CALIBRATION_FORWARD_ACCUMULATING":
        actions.append("Continue collecting forward labels until minimum row and session guardrails are met.")
    if pattern.get("non_monotonic_calibration_risk"):
        actions.append(
            "Avoid a global probability uplift; low buckets are underconfident while high buckets are overconfident."
        )
    if int(read.get("underconfidence_slice_count") or 0) > 0:
        actions.append("Review underconfident slices for regime-conditioned probability calibration candidates.")
    if int(read.get("overconfidence_slice_count") or 0) > 0:
        actions.append("Review overconfident slices before raising thresholds or probabilities globally.")
    if status == "CALIBRATION_FORWARD_OK":
        actions.append("Keep monitoring; no calibration change is supported by this forward window.")
    if not actions:
        actions.append("Keep probability calibration research-only and rerun after the next data-rich session.")
    actions.append("Do not change live probabilities until guarded segmented candidates pass strict-forward validation.")
    return actions


def build_probability_calibration_forward_monitor_report(
    frame: pd.DataFrame,
    *,
    dataset_path: str | Path | None = None,
    probability_field: str = DEFAULT_PROBABILITY_FIELD,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    group_fields: tuple[str, ...] = DEFAULT_GROUP_FIELDS,
    min_labeled_rows: int = DEFAULT_MIN_LABELED_ROWS,
    min_session_count: int = DEFAULT_MIN_SESSION_COUNT,
    min_slice_labels: int = DEFAULT_MIN_SLICE_LABELS,
    alert_abs_gap: float = DEFAULT_ALERT_ABS_GAP,
    severe_abs_gap: float = DEFAULT_SEVERE_ABS_GAP,
) -> dict[str, Any]:
    raw = frame if frame is not None else pd.DataFrame()
    prepared = prepare_probability_calibration_forward_monitor_frame(
        raw,
        probability_field=probability_field,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    eligible = prepared.loc[prepared.get("monitor_eligible", pd.Series(False, index=prepared.index)).fillna(False)].copy()
    summary = _metric_row(
        eligible,
        min_labels=min_labeled_rows,
        alert_abs_gap=alert_abs_gap,
        severe_abs_gap=severe_abs_gap,
    )
    session_rows = _group_rows(
        eligible,
        ["signal_date"],
        slice_type="signal_date",
        min_labels=1,
        alert_abs_gap=alert_abs_gap,
        severe_abs_gap=severe_abs_gap,
        top_n=300,
    )
    bucket_rows = _group_rows(
        eligible,
        ["probability_bucket"],
        slice_type="probability_bucket",
        min_labels=min_slice_labels,
        alert_abs_gap=alert_abs_gap,
        severe_abs_gap=severe_abs_gap,
        top_n=20,
    )
    slices = _slice_rows(
        eligible,
        group_fields=group_fields,
        min_labels=min_slice_labels,
        alert_abs_gap=alert_abs_gap,
        severe_abs_gap=severe_abs_gap,
    )
    flagged = _flagged_slices(slices + bucket_rows, min_slice_labels=min_slice_labels, alert_abs_gap=alert_abs_gap)
    session_count = sum(1 for row in session_rows if int(row.get("label_count") or 0) > 0)
    bucket_ece = _ece(bucket_rows)
    status = _monitor_status(
        summary=summary,
        session_count=session_count,
        min_labeled_rows=min_labeled_rows,
        min_session_count=min_session_count,
        flagged=flagged,
        bucket_ece=bucket_ece,
        alert_abs_gap=alert_abs_gap,
        severe_abs_gap=severe_abs_gap,
    )
    underconfidence = [row for row in flagged if (_safe_float(row.get("calibration_gap"), 0.0) or 0.0) < 0]
    overconfidence = [row for row in flagged if (_safe_float(row.get("calibration_gap"), 0.0) or 0.0) > 0]

    start_ts = prepared["signal_ts"].dropna().min().isoformat() if "signal_ts" in prepared and prepared["signal_ts"].notna().any() else None
    end_ts = prepared["signal_ts"].dropna().max().isoformat() if "signal_ts" in prepared and prepared["signal_ts"].notna().any() else None
    report = {
        "report_type": "probability_calibration_forward_monitor",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_path": str(dataset_path) if dataset_path is not None else None,
        "runtime_config_changed": False,
        "parameter_pack_file_changed": False,
        "execution_behavior_changed": False,
        "methodology": {
            "probability_field": probability_field,
            "label_field": DEFAULT_LABEL_FIELD,
            "return_field": DEFAULT_RETURN_FIELD,
            "report_date": report_date,
            "start_date": start_date,
            "end_date": end_date,
            "group_fields": list(group_fields),
            "min_labeled_rows": int(min_labeled_rows),
            "min_session_count": int(min_session_count),
            "min_slice_labels": int(min_slice_labels),
            "alert_abs_gap": float(alert_abs_gap),
            "severe_abs_gap": float(severe_abs_gap),
            "hindsight_guardrail": (
                "Calibration buckets use runtime probability fields and quality-approved matured labels. "
                "The monitor creates research evidence only and does not alter live probabilities."
            ),
        },
        "coverage": {
            "input_rows": int(len(raw)),
            "rows_after_date_filter": int(len(prepared)),
            "eligible_labeled_rows": int(len(eligible)),
            "labeled_session_count": int(session_count),
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
        },
        "monitor_status": status,
        "diagnostic_read": {
            "label_count": summary.get("label_count"),
            "labeled_session_count": int(session_count),
            "mean_predicted_probability": summary.get("mean_predicted_probability"),
            "actual_hit_rate": summary.get("actual_hit_rate"),
            "calibration_gap": summary.get("calibration_gap"),
            "brier_score": summary.get("brier_score"),
            "bucket_ece": _round_or_none(bucket_ece, 6),
            "underconfidence_slice_count": int(len(underconfidence)),
            "overconfidence_slice_count": int(len(overconfidence)),
            "flagged_slice_count": int(len(flagged)),
        },
        "bucket_pattern": _bucket_pattern(bucket_rows, alert_abs_gap=alert_abs_gap),
        "summary": summary,
        "session_rows": session_rows,
        "probability_bucket_rows": bucket_rows,
        "slice_rows": slices,
        "flagged_slices": flagged,
    }
    report["recommended_next_actions"] = _recommended_actions(report)
    return _sanitize_value(report)


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


def render_probability_calibration_forward_monitor_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    summary = report.get("summary") or {}
    lines = [
        "# Probability Calibration Forward Monitor",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only monitor checks whether runtime move probabilities are calibrated "
        "after outcomes mature. It uses quality-approved labels and does not change live "
        "signal behavior.",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Rows after date filter: `{coverage.get('rows_after_date_filter')}`",
        f"- Eligible labeled rows: `{coverage.get('eligible_labeled_rows')}`",
        f"- Labeled sessions: `{coverage.get('labeled_session_count')}`",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Monitor status: `{report.get('monitor_status')}`",
        f"- Label count: `{read.get('label_count')}`",
        f"- Mean predicted probability: `{read.get('mean_predicted_probability')}`",
        f"- Actual hit rate: `{read.get('actual_hit_rate')}`",
        f"- Calibration gap: `{read.get('calibration_gap')}`",
        f"- Brier score: `{read.get('brier_score')}`",
        f"- Bucket ECE: `{read.get('bucket_ece')}`",
        f"- Underconfidence slices: `{read.get('underconfidence_slice_count')}`",
        f"- Overconfidence slices: `{read.get('overconfidence_slice_count')}`",
        "",
        "## Overall Summary",
        "",
    ]
    lines.extend(
        _markdown_table(
            [summary],
            [
                "row_count",
                "label_count",
                "mean_predicted_probability",
                "actual_hit_rate",
                "calibration_gap",
                "abs_calibration_gap",
                "brier_score",
                "avg_signed_return_60m_bps",
                "calibration_status",
            ],
        )
    )
    lines.extend(["", "## Probability Buckets", ""])
    lines.extend(
        _markdown_table(
            report.get("probability_bucket_rows") or [],
            [
                "probability_bucket",
                "label_count",
                "mean_predicted_probability",
                "actual_hit_rate",
                "calibration_gap",
                "brier_score",
                "avg_signed_return_60m_bps",
                "calibration_status",
            ],
        )
    )
    lines.extend(["", "## Sessions", ""])
    lines.extend(
        _markdown_table(
            report.get("session_rows") or [],
            [
                "signal_date",
                "label_count",
                "mean_predicted_probability",
                "actual_hit_rate",
                "calibration_gap",
                "brier_score",
                "avg_signed_return_60m_bps",
                "calibration_status",
            ],
            max_rows=30,
        )
    )
    lines.extend(["", "## Flagged Slices", ""])
    lines.extend(
        _markdown_table(
            report.get("flagged_slices") or [],
            [
                "slice_type",
                "slice_key",
                "label_count",
                "mean_predicted_probability",
                "actual_hit_rate",
                "calibration_gap",
                "brier_score",
                "avg_signed_return_60m_bps",
                "calibration_status",
            ],
            max_rows=40,
        )
    )
    lines.extend(["", "## Recommended Actions", ""])
    for action in report.get("recommended_next_actions") or []:
        lines.append(f"- {action}")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This report is research-only.",
            "- Runtime probabilities, parameter packs, and execution behavior are unchanged.",
            "- Probability changes require strict-forward guarded evidence before promotion.",
            "",
        ]
    )
    return "\n".join(lines)


def write_probability_calibration_forward_monitor_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_PROBABILITY_CALIBRATION_FORWARD_MONITOR_DIR,
    probability_field: str = DEFAULT_PROBABILITY_FIELD,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    group_fields: tuple[str, ...] = DEFAULT_GROUP_FIELDS,
    min_labeled_rows: int = DEFAULT_MIN_LABELED_ROWS,
    min_session_count: int = DEFAULT_MIN_SESSION_COUNT,
    min_slice_labels: int = DEFAULT_MIN_SLICE_LABELS,
    alert_abs_gap: float = DEFAULT_ALERT_ABS_GAP,
    severe_abs_gap: float = DEFAULT_SEVERE_ABS_GAP,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = _load_dataset(dataset)
    report = build_probability_calibration_forward_monitor_report(
        frame,
        dataset_path=dataset,
        probability_field=probability_field,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
        group_fields=group_fields,
        min_labeled_rows=min_labeled_rows,
        min_session_count=min_session_count,
        min_slice_labels=min_slice_labels,
        alert_abs_gap=alert_abs_gap,
        severe_abs_gap=severe_abs_gap,
    )

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    json_path = output / f"probability_calibration_forward_monitor_{timestamp}.json"
    markdown_path = output / f"probability_calibration_forward_monitor_{timestamp}.md"
    latest_json_path = output / "latest_probability_calibration_forward_monitor.json"
    latest_markdown_path = output / "latest_probability_calibration_forward_monitor.md"
    summary_csv_path = output / f"probability_calibration_forward_monitor_{timestamp}_summary.csv"
    latest_summary_csv_path = output / "latest_probability_calibration_forward_monitor_summary.csv"
    buckets_csv_path = output / f"probability_calibration_forward_monitor_{timestamp}_buckets.csv"
    latest_buckets_csv_path = output / "latest_probability_calibration_forward_monitor_buckets.csv"
    sessions_csv_path = output / f"probability_calibration_forward_monitor_{timestamp}_sessions.csv"
    latest_sessions_csv_path = output / "latest_probability_calibration_forward_monitor_sessions.csv"
    slices_csv_path = output / f"probability_calibration_forward_monitor_{timestamp}_slices.csv"
    latest_slices_csv_path = output / "latest_probability_calibration_forward_monitor_slices.csv"

    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_probability_calibration_forward_monitor_markdown(report)
    _atomic_write_text(json_path, json_text)
    _atomic_write_text(latest_json_path, json_text)
    _atomic_write_text(markdown_path, markdown_text)
    _atomic_write_text(latest_markdown_path, markdown_text)

    summary_row = {
        "monitor_status": report.get("monitor_status"),
        **(report.get("diagnostic_read") or {}),
        **{f"summary_{key}": value for key, value in (report.get("summary") or {}).items()},
    }
    _atomic_write_csv(pd.DataFrame([summary_row]), summary_csv_path)
    _atomic_write_csv(pd.DataFrame([summary_row]), latest_summary_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("probability_bucket_rows") or []), buckets_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("probability_bucket_rows") or []), latest_buckets_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("session_rows") or []), sessions_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("session_rows") or []), latest_sessions_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("slice_rows") or []), slices_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("slice_rows") or []), latest_slices_csv_path)

    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="probability_calibration_forward_monitor",
        report_date=report_date or start_date,
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
        "summary_csv_path": str(summary_csv_path),
        "latest_summary_csv_path": str(latest_summary_csv_path),
        "buckets_csv_path": str(buckets_csv_path),
        "latest_buckets_csv_path": str(latest_buckets_csv_path),
        "sessions_csv_path": str(sessions_csv_path),
        "latest_sessions_csv_path": str(latest_sessions_csv_path),
        "slices_csv_path": str(slices_csv_path),
        "latest_slices_csv_path": str(latest_slices_csv_path),
        "manifest_path": str(manifest_path),
    }

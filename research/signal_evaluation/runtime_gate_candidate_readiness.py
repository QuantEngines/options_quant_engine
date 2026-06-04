"""Forward-readiness gate for runtime-gate candidate monitoring.

This research-only report checks whether the segmented runtime-gate candidate
has enough exact forward component evidence for manual review. It never changes
runtime configuration, thresholds, parameter packs, data sources, or execution
behavior.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.signal_evaluation_scoring import SIGNAL_EVALUATION_SELECTION_POLICY
from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH
from research.signal_evaluation.runtime_component_outcome import (
    _load_dataset,
    _metrics,
    _num_series,
    _round_or_none,
    _text_series,
)
from research.signal_evaluation.runtime_gate_candidate_monitor import (
    DEFAULT_RUNTIME_GATE_CANDIDATE_MONITOR_DIR,
    prepare_runtime_gate_candidate_frame,
)
from research.signal_evaluation.signal_quality_model_audit import (
    _atomic_write_text,
    _sanitize_value,
)
from utils.timestamp_helpers import coerce_timestamp, coerce_timestamp_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_GATE_CANDIDATE_READINESS_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_gate_candidate_readiness"
)

LATEST_JSON_FILENAME = "latest_runtime_gate_candidate_readiness.json"
LATEST_MARKDOWN_FILENAME = "latest_runtime_gate_candidate_readiness.md"

RUNTIME_GATE_CANDIDATE_ACCUMULATING = "RUNTIME_GATE_CANDIDATE_ACCUMULATING"
RUNTIME_GATE_CANDIDATE_REVIEW_READY = "RUNTIME_GATE_CANDIDATE_REVIEW_READY"
RUNTIME_GATE_CANDIDATE_BLOCKED = "RUNTIME_GATE_CANDIDATE_BLOCKED"


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _truthy_component_source(frame: pd.DataFrame) -> pd.Series:
    if "runtime_component_source" not in frame.columns:
        return pd.Series(False, index=frame.index)
    return _text_series(frame, "runtime_component_source", default="").str.lower().eq("captured_json")


def _timestamp_series(frame: pd.DataFrame) -> pd.Series:
    if "_signal_ts" in frame.columns:
        return coerce_timestamp_series(frame["_signal_ts"], utc=True)
    if "signal_timestamp" in frame.columns:
        return coerce_timestamp_series(frame["signal_timestamp"], utc=True)
    return pd.Series(pd.NaT, index=frame.index)


def _signal_dates(frame: pd.DataFrame) -> pd.Series:
    ts = _timestamp_series(frame)
    return ts.dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")


def _component_capture_start(
    frame: pd.DataFrame,
    *,
    component_capture_start: str | None,
) -> tuple[pd.Timestamp | None, str]:
    explicit = coerce_timestamp(component_capture_start, fallback=None) if component_capture_start else None
    if explicit is not None:
        return explicit, "explicit"
    exact = frame.loc[_truthy_component_source(frame)].copy()
    if exact.empty:
        return None, "unavailable_no_exact_component_rows"
    timestamps = _timestamp_series(exact).dropna()
    if timestamps.empty:
        return None, "unavailable_exact_rows_missing_timestamps"
    return timestamps.min(), "inferred_from_first_exact_component_row"


def _bucket_metrics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for bucket, group in frame.groupby(_text_series(frame, "runtime_gate_candidate_bucket"), dropna=False):
        rows.append({"bucket": str(bucket), **_metrics(group)})
    return sorted(rows, key=lambda item: str(item.get("bucket")))


def _metric_delta(left: dict[str, Any] | None, right: dict[str, Any] | None, key: str) -> float | None:
    if not left or not right:
        return None
    left_value = left.get(key)
    right_value = right.get(key)
    if left_value is None or right_value is None:
        return None
    try:
        return float(left_value) - float(right_value)
    except (TypeError, ValueError):
        return None


def _performance_comparison(bucket_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    candidate = next((row for row in bucket_metrics if row.get("bucket") == "CANDIDATE_MONITOR"), None)
    guardrail = next((row for row in bucket_metrics if row.get("bucket") == "KEEP_BLOCKED_GUARDRAIL"), None)
    holdout = next((row for row in bucket_metrics if row.get("bucket") == "RESEARCH_HOLDOUT"), None)
    return {
        "candidate_minus_guardrail_hit_rate_60m": _round_or_none(
            _metric_delta(candidate, guardrail, "hit_rate_60m"),
            4,
        ),
        "candidate_minus_guardrail_return_60m_bps": _round_or_none(
            _metric_delta(candidate, guardrail, "avg_signed_return_60m_bps"),
            4,
        ),
        "candidate_minus_guardrail_mfe_mae_ratio_60m": _round_or_none(
            _metric_delta(candidate, guardrail, "mfe_mae_ratio_60m"),
            4,
        ),
        "candidate_minus_holdout_hit_rate_60m": _round_or_none(
            _metric_delta(candidate, holdout, "hit_rate_60m"),
            4,
        ),
        "candidate_minus_holdout_return_60m_bps": _round_or_none(
            _metric_delta(candidate, holdout, "avg_signed_return_60m_bps"),
            4,
        ),
        "candidate_minus_holdout_mfe_mae_ratio_60m": _round_or_none(
            _metric_delta(candidate, holdout, "mfe_mae_ratio_60m"),
            4,
        ),
    }


def _readiness_status(
    *,
    exact_candidate_rows: int,
    exact_guardrail_rows: int,
    exact_session_count: int,
    min_exact_candidate_rows: int,
    min_exact_guardrail_rows: int,
    min_exact_sessions: int,
    candidate_metrics: dict[str, Any] | None,
    comparison: dict[str, Any],
    min_candidate_hit_rate_60m: float,
    min_candidate_return_60m_bps: float,
    min_candidate_mfe_mae_ratio_60m: float,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if exact_candidate_rows < min_exact_candidate_rows:
        reasons.append(f"candidate_exact_rows {exact_candidate_rows}/{min_exact_candidate_rows}")
    if exact_guardrail_rows < min_exact_guardrail_rows:
        reasons.append(f"guardrail_exact_rows {exact_guardrail_rows}/{min_exact_guardrail_rows}")
    if exact_session_count < min_exact_sessions:
        reasons.append(f"exact_sessions {exact_session_count}/{min_exact_sessions}")
    if reasons:
        return RUNTIME_GATE_CANDIDATE_ACCUMULATING, reasons

    hit = candidate_metrics.get("hit_rate_60m") if candidate_metrics else None
    ret = candidate_metrics.get("avg_signed_return_60m_bps") if candidate_metrics else None
    ratio = candidate_metrics.get("mfe_mae_ratio_60m") if candidate_metrics else None
    if hit is None or float(hit) < float(min_candidate_hit_rate_60m):
        reasons.append(f"candidate_hit_rate_60m below {min_candidate_hit_rate_60m}")
    if ret is None or float(ret) < float(min_candidate_return_60m_bps):
        reasons.append(f"candidate_return_60m_bps below {min_candidate_return_60m_bps}")
    if ratio is None or float(ratio) < float(min_candidate_mfe_mae_ratio_60m):
        reasons.append(f"candidate_mfe_mae_ratio_60m below {min_candidate_mfe_mae_ratio_60m}")
    for key in (
        "candidate_minus_guardrail_return_60m_bps",
        "candidate_minus_guardrail_mfe_mae_ratio_60m",
        "candidate_minus_holdout_return_60m_bps",
        "candidate_minus_holdout_mfe_mae_ratio_60m",
    ):
        value = comparison.get(key)
        if value is None or float(value) <= 0.0:
            reasons.append(f"{key} not positive")
    if reasons:
        return RUNTIME_GATE_CANDIDATE_BLOCKED, reasons
    return RUNTIME_GATE_CANDIDATE_REVIEW_READY, ["exact forward candidate evidence meets review thresholds"]


def build_runtime_gate_candidate_readiness_report(
    frame: pd.DataFrame,
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    component_capture_start: str | None = None,
    probability_floor: float | None = None,
    min_preserve_matches: int = 3,
    min_exact_candidate_rows: int = 100,
    min_exact_guardrail_rows: int = 100,
    min_exact_sessions: int = 3,
    min_candidate_hit_rate_60m: float = 0.58,
    min_candidate_return_60m_bps: float = 0.0,
    min_candidate_mfe_mae_ratio_60m: float = 1.20,
    require_runtime_composite: bool = True,
) -> dict[str, Any]:
    """Build exact-forward readiness for the runtime-gate candidate monitor."""
    probability_floor = (
        float(probability_floor)
        if probability_floor is not None
        else float(SIGNAL_EVALUATION_SELECTION_POLICY.get("move_probability_floor", 0.60))
    )
    candidate_frame, component_source = prepare_runtime_gate_candidate_frame(
        frame if frame is not None else pd.DataFrame(),
        start_date=start_date,
        end_date=end_date,
        probability_floor=probability_floor,
        min_preserve_matches=min_preserve_matches,
        require_runtime_composite=require_runtime_composite,
    )
    capture_ts, capture_source = _component_capture_start(
        candidate_frame,
        component_capture_start=component_capture_start,
    )
    timestamps = _timestamp_series(candidate_frame)
    exact_mask = _truthy_component_source(candidate_frame)
    if capture_ts is not None:
        exact_forward_mask = exact_mask & timestamps.ge(capture_ts)
    else:
        exact_forward_mask = exact_mask & timestamps.notna()
    exact_forward = candidate_frame.loc[exact_forward_mask.fillna(False)].copy()
    exact_forward_dates = _signal_dates(exact_forward).dropna() if not exact_forward.empty else pd.Series(dtype=str)
    bucket_metrics = _bucket_metrics(exact_forward)
    candidate_metrics = next((row for row in bucket_metrics if row.get("bucket") == "CANDIDATE_MONITOR"), None)
    guardrail_metrics = next((row for row in bucket_metrics if row.get("bucket") == "KEEP_BLOCKED_GUARDRAIL"), None)
    comparison = _performance_comparison(bucket_metrics)
    exact_candidate_rows = int((exact_forward.get("runtime_gate_candidate_bucket") == "CANDIDATE_MONITOR").sum()) if not exact_forward.empty else 0
    exact_guardrail_rows = int((exact_forward.get("runtime_gate_candidate_bucket") == "KEEP_BLOCKED_GUARDRAIL").sum()) if not exact_forward.empty else 0
    status, reasons = _readiness_status(
        exact_candidate_rows=exact_candidate_rows,
        exact_guardrail_rows=exact_guardrail_rows,
        exact_session_count=int(exact_forward_dates.nunique()),
        min_exact_candidate_rows=min_exact_candidate_rows,
        min_exact_guardrail_rows=min_exact_guardrail_rows,
        min_exact_sessions=min_exact_sessions,
        candidate_metrics=candidate_metrics,
        comparison=comparison,
        min_candidate_hit_rate_60m=min_candidate_hit_rate_60m,
        min_candidate_return_60m_bps=min_candidate_return_60m_bps,
        min_candidate_mfe_mae_ratio_60m=min_candidate_mfe_mae_ratio_60m,
    )

    exact_timestamps = _timestamp_series(exact_forward).dropna() if not exact_forward.empty else pd.Series(dtype="datetime64[ns, UTC]")
    report = {
        "report_type": "runtime_gate_candidate_readiness",
        "generated_at": _now_utc(),
        "research_only": True,
        "runtime_config_changed": False,
        "parameter_pack_file_changed": False,
        "execution_behavior_changed": False,
        "dataset_path": str(dataset_path),
        "start_date": start_date,
        "end_date": end_date,
        "component_capture_start": capture_ts.isoformat() if capture_ts is not None else None,
        "component_capture_start_source": capture_source,
        "component_source_overall": component_source,
        "probability_floor": probability_floor,
        "min_preserve_matches": int(min_preserve_matches),
        "readiness_status": status,
        "readiness_reasons": reasons,
        "manual_review_ready": status == RUNTIME_GATE_CANDIDATE_REVIEW_READY,
        "promotion_ready": False,
        "thresholds": {
            "min_exact_candidate_rows": int(min_exact_candidate_rows),
            "min_exact_guardrail_rows": int(min_exact_guardrail_rows),
            "min_exact_sessions": int(min_exact_sessions),
            "min_candidate_hit_rate_60m": float(min_candidate_hit_rate_60m),
            "min_candidate_return_60m_bps": float(min_candidate_return_60m_bps),
            "min_candidate_mfe_mae_ratio_60m": float(min_candidate_mfe_mae_ratio_60m),
        },
        "exact_forward_summary": {
            "suppressed_directional_rows": int(len(candidate_frame)),
            "exact_component_rows": int(exact_mask.fillna(False).sum()),
            "exact_forward_rows": int(len(exact_forward)),
            "exact_forward_candidate_rows": exact_candidate_rows,
            "exact_forward_guardrail_rows": exact_guardrail_rows,
            "exact_forward_holdout_rows": int(
                (exact_forward.get("runtime_gate_candidate_bucket") == "RESEARCH_HOLDOUT").sum()
            )
            if not exact_forward.empty
            else 0,
            "exact_forward_session_count": int(exact_forward_dates.nunique()),
            "earliest_exact_forward_signal_timestamp": exact_timestamps.min().isoformat() if not exact_timestamps.empty else None,
            "latest_exact_forward_signal_timestamp": exact_timestamps.max().isoformat() if not exact_timestamps.empty else None,
        },
        "candidate_exact_metrics": candidate_metrics or {},
        "guardrail_exact_metrics": guardrail_metrics or {},
        "exact_bucket_metrics": bucket_metrics,
        "candidate_vs_guardrail_and_holdout": comparison,
        "recommended_next_actions": [
            "Keep the segmented gate candidate research-only; do not alter runtime thresholds.",
            "Continue collecting exact runtime_composite_components forward rows until readiness is REVIEW_READY.",
            "If readiness becomes BLOCKED with enough exact rows, discard or redesign the candidate rather than overriding the gate.",
        ],
    }
    return _sanitize_value(report)


def render_runtime_gate_candidate_readiness_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Runtime Gate Candidate Readiness",
        "",
        "> Author: Pramit Dutta | Organization: Quant Engines",
        "",
        f"- Generated at: {report.get('generated_at')}",
        f"- Research only: `{report.get('research_only')}`",
        f"- Readiness status: `{report.get('readiness_status')}`",
        f"- Manual review ready: `{report.get('manual_review_ready')}`",
        f"- Promotion ready: `{report.get('promotion_ready')}`",
        f"- Component capture start: `{report.get('component_capture_start')}`",
        f"- Component capture source: `{report.get('component_capture_start_source')}`",
        "",
        "## Exact Forward Summary",
        "",
    ]
    summary = report.get("exact_forward_summary") or {}
    for key in (
        "suppressed_directional_rows",
        "exact_component_rows",
        "exact_forward_rows",
        "exact_forward_candidate_rows",
        "exact_forward_guardrail_rows",
        "exact_forward_holdout_rows",
        "exact_forward_session_count",
        "earliest_exact_forward_signal_timestamp",
        "latest_exact_forward_signal_timestamp",
    ):
        lines.append(f"- {key}: `{summary.get(key)}`")
    lines.extend(["", "## Readiness Reasons", ""])
    for reason in report.get("readiness_reasons", []) or []:
        lines.append(f"- {reason}")
    lines.extend(["", "## Candidate Exact Metrics", ""])
    candidate = report.get("candidate_exact_metrics") or {}
    for key in ("row_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"):
        lines.append(f"- {key}: `{candidate.get(key)}`")
    lines.extend(["", "## Comparison", ""])
    comparison = report.get("candidate_vs_guardrail_and_holdout") or {}
    for key, value in comparison.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Recommended Next Actions", ""])
    for action in report.get("recommended_next_actions", []) or []:
        lines.append(f"- {action}")
    lines.extend(["", "*Research-only readiness gate. It does not alter live signal behavior.*", ""])
    return "\n".join(lines)


def write_runtime_gate_candidate_readiness_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_GATE_CANDIDATE_READINESS_DIR,
    start_date: str | None = None,
    end_date: str | None = None,
    component_capture_start: str | None = None,
    probability_floor: float | None = None,
    min_preserve_matches: int = 3,
    min_exact_candidate_rows: int = 100,
    min_exact_guardrail_rows: int = 100,
    min_exact_sessions: int = 3,
    min_candidate_hit_rate_60m: float = 0.58,
    min_candidate_return_60m_bps: float = 0.0,
    min_candidate_mfe_mae_ratio_60m: float = 1.20,
    require_runtime_composite: bool = True,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = _load_dataset(dataset)
    report = build_runtime_gate_candidate_readiness_report(
        frame,
        dataset_path=dataset,
        start_date=start_date,
        end_date=end_date,
        component_capture_start=component_capture_start,
        probability_floor=probability_floor,
        min_preserve_matches=min_preserve_matches,
        min_exact_candidate_rows=min_exact_candidate_rows,
        min_exact_guardrail_rows=min_exact_guardrail_rows,
        min_exact_sessions=min_exact_sessions,
        min_candidate_hit_rate_60m=min_candidate_hit_rate_60m,
        min_candidate_return_60m_bps=min_candidate_return_60m_bps,
        min_candidate_mfe_mae_ratio_60m=min_candidate_mfe_mae_ratio_60m,
        require_runtime_composite=require_runtime_composite,
    )
    date_part = f"{start_date or 'all'}_{end_date or 'latest'}".replace("-", "")
    stem = f"runtime_gate_candidate_readiness_{date_part}"
    json_path = output / f"{stem}.json"
    markdown_path = output / f"{stem}.md"
    latest_json_path = output / LATEST_JSON_FILENAME
    latest_markdown_path = output / LATEST_MARKDOWN_FILENAME

    markdown = render_runtime_gate_candidate_readiness_markdown(report)
    _atomic_write_text(json_path, json.dumps(report, indent=2, sort_keys=True, default=str))
    _atomic_write_text(markdown_path, markdown)
    _atomic_write_text(latest_json_path, json.dumps(report, indent=2, sort_keys=True, default=str))
    _atomic_write_text(latest_markdown_path, markdown)

    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
    }

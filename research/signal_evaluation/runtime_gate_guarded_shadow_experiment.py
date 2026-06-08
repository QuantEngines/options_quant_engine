"""Research-only guarded shadow experiment for runtime-gate candidates.

This report turns the manually reviewed runtime-gate preserve/guardrail map
into a shadow experiment artifact. It does not alter runtime scoring,
thresholds, parameter packs, data-source routing, or execution behavior.
"""

from __future__ import annotations

import json
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
    _safe_mean,
    _text_series,
)
from research.signal_evaluation.runtime_gate_candidate_monitor import prepare_runtime_gate_candidate_frame
from research.signal_evaluation.runtime_gate_candidate_readiness import (
    _component_capture_start,
    _signal_dates,
    _timestamp_series,
    _truthy_component_source,
)
from research.signal_evaluation.signal_quality_model_audit import (
    _atomic_write_csv,
    _atomic_write_text,
    _sanitize_value,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_gate_guarded_shadow_experiment"
)

LATEST_JSON_FILENAME = "latest_runtime_gate_guarded_shadow_experiment.json"
LATEST_MARKDOWN_FILENAME = "latest_runtime_gate_guarded_shadow_experiment.md"
LATEST_SEGMENTS_FILENAME = "latest_runtime_gate_guarded_shadow_experiment_segments.csv"

ACTION_PRESERVE_PREFERRED = "SHADOW_PRESERVE_PREFERRED"
ACTION_PRESERVE_REVIEW = "SHADOW_PRESERVE_REVIEW"
ACTION_KEEP_BLOCKED = "KEEP_BLOCKED_GUARDRAIL"
ACTION_DEFER_HOLDOUT = "DEFER_HOLDOUT"


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


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


def _add_shadow_actions(frame: pd.DataFrame, *, preferred_preserve_matches: int) -> pd.DataFrame:
    working = frame.copy()
    bucket = _text_series(working, "runtime_gate_candidate_bucket")
    preserve_count = _num_series(working, "candidate_preserve_match_count")
    guard_count = _num_series(working, "candidate_guardrail_count")

    action = pd.Series(ACTION_DEFER_HOLDOUT, index=working.index, dtype="object")
    action.loc[bucket == "KEEP_BLOCKED_GUARDRAIL"] = ACTION_KEEP_BLOCKED
    action.loc[(bucket == "CANDIDATE_MONITOR") & preserve_count.lt(float(preferred_preserve_matches))] = ACTION_PRESERVE_REVIEW
    action.loc[(bucket == "CANDIDATE_MONITOR") & preserve_count.ge(float(preferred_preserve_matches))] = ACTION_PRESERVE_PREFERRED

    reason = pd.Series("insufficient_preserve_matches", index=working.index, dtype="object")
    candidate_reason = _text_series(working, "runtime_gate_candidate_reason", default="")
    reason.loc[action == ACTION_KEEP_BLOCKED] = candidate_reason.loc[action == ACTION_KEEP_BLOCKED]
    reason.loc[action == ACTION_PRESERVE_REVIEW] = (
        "zero_guardrails_preserve_count_"
        + preserve_count.loc[action == ACTION_PRESERVE_REVIEW].fillna(0).astype(int).astype(str)
    )
    reason.loc[action == ACTION_PRESERVE_PREFERRED] = f"zero_guardrails_preserve_count>={int(preferred_preserve_matches)}"

    working["runtime_gate_shadow_action"] = action
    working["runtime_gate_shadow_reason"] = reason
    working["runtime_gate_shadow_preserve"] = action.isin({ACTION_PRESERVE_PREFERRED, ACTION_PRESERVE_REVIEW})
    working["runtime_gate_shadow_preferred_preserve"] = action.eq(ACTION_PRESERVE_PREFERRED)
    working["runtime_gate_shadow_guardrail_count_bucket"] = guard_count.fillna(0).astype(int).astype(str)
    working["runtime_gate_shadow_preserve_count_bucket"] = preserve_count.fillna(0).astype(int).astype(str)
    return working


def _shadow_metrics(group: pd.DataFrame) -> dict[str, Any]:
    row = _metrics(group)
    close_hit = _num_series(group, "correct_session_close")
    close_return = _num_series(group, "signed_return_session_close_bps")
    row["hit_rate_session_close"] = _round_or_none(_safe_mean(close_hit), 4)
    row["avg_signed_return_session_close_bps"] = _round_or_none(_safe_mean(close_return), 4)
    return row


def _bucket_metrics(frame: pd.DataFrame, *, field: str, label_key: str) -> list[dict[str, Any]]:
    if frame.empty or field not in frame.columns:
        return []
    rows: list[dict[str, Any]] = []
    for label, group in frame.groupby(_text_series(frame, field), dropna=False):
        rows.append({label_key: str(label), **_shadow_metrics(group)})
    return sorted(rows, key=lambda item: (-int(item.get("row_count") or 0), str(item.get(label_key))))


def _segment_rows(frame: pd.DataFrame, segment_name: str, field: str, *, min_rows: int) -> list[dict[str, Any]]:
    if frame.empty or field not in frame.columns:
        return []
    rows: list[dict[str, Any]] = []
    for value, group in frame.groupby(_text_series(frame, field), dropna=False):
        if len(group) < min_rows:
            continue
        rows.append({"segment": segment_name, "value": str(value), **_shadow_metrics(group)})
    return sorted(rows, key=lambda item: (-int(item.get("row_count") or 0), str(item.get("value"))))


def _action_comparison(action_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    preferred = next((row for row in action_metrics if row.get("shadow_action") == ACTION_PRESERVE_PREFERRED), None)
    review = next((row for row in action_metrics if row.get("shadow_action") == ACTION_PRESERVE_REVIEW), None)
    guardrail = next((row for row in action_metrics if row.get("shadow_action") == ACTION_KEEP_BLOCKED), None)
    holdout = next((row for row in action_metrics if row.get("shadow_action") == ACTION_DEFER_HOLDOUT), None)
    preserved = None
    preserve_rows = [row for row in action_metrics if row.get("shadow_action") in {ACTION_PRESERVE_PREFERRED, ACTION_PRESERVE_REVIEW}]
    if preserve_rows:
        preserved = {
            "row_count": sum(int(row.get("row_count") or 0) for row in preserve_rows),
            "label_count_60m": sum(int(row.get("label_count_60m") or 0) for row in preserve_rows),
        }
    return {
        "preferred_minus_guardrail_return_60m_bps": _round_or_none(
            _metric_delta(preferred, guardrail, "avg_signed_return_60m_bps"), 4
        ),
        "preferred_minus_guardrail_mfe_mae_ratio_60m": _round_or_none(
            _metric_delta(preferred, guardrail, "mfe_mae_ratio_60m"), 4
        ),
        "preferred_minus_review_return_60m_bps": _round_or_none(
            _metric_delta(preferred, review, "avg_signed_return_60m_bps"), 4
        ),
        "preferred_minus_review_mfe_mae_ratio_60m": _round_or_none(
            _metric_delta(preferred, review, "mfe_mae_ratio_60m"), 4
        ),
        "review_minus_guardrail_return_60m_bps": _round_or_none(
            _metric_delta(review, guardrail, "avg_signed_return_60m_bps"), 4
        ),
        "review_minus_guardrail_mfe_mae_ratio_60m": _round_or_none(
            _metric_delta(review, guardrail, "mfe_mae_ratio_60m"), 4
        ),
        "preferred_minus_holdout_return_60m_bps": _round_or_none(
            _metric_delta(preferred, holdout, "avg_signed_return_60m_bps"), 4
        ),
        "preferred_minus_holdout_mfe_mae_ratio_60m": _round_or_none(
            _metric_delta(preferred, holdout, "mfe_mae_ratio_60m"), 4
        ),
        "preserved_row_count": preserved.get("row_count") if preserved else 0,
        "preserved_label_count_60m": preserved.get("label_count_60m") if preserved else 0,
    }


def _shadow_read(
    *,
    exact_action_metrics: list[dict[str, Any]],
    exact_session_count: int,
    min_preferred_exact_rows: int,
    min_exact_sessions: int,
) -> str:
    preferred = next((row for row in exact_action_metrics if row.get("shadow_action") == ACTION_PRESERVE_PREFERRED), None)
    if not preferred or int(preferred.get("row_count") or 0) < int(min_preferred_exact_rows):
        return "GUARDED_SHADOW_ACCUMULATING_PREFERRED_ROWS"
    if int(exact_session_count) < int(min_exact_sessions):
        return "GUARDED_SHADOW_ACCUMULATING_EXACT_SESSIONS"
    ret = preferred.get("avg_signed_return_60m_bps")
    ratio = preferred.get("mfe_mae_ratio_60m")
    if ret is not None and ratio is not None and float(ret) > 0.0 and float(ratio) >= 1.2:
        return "GUARDED_SHADOW_ACTIVE_RESEARCH_ONLY"
    return "GUARDED_SHADOW_WEAK_KEEP_RESEARCH_ONLY"


def build_runtime_gate_guarded_shadow_report(
    frame: pd.DataFrame,
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    component_capture_start: str | None = None,
    probability_floor: float | None = None,
    min_preserve_matches: int = 3,
    preferred_preserve_matches: int = 4,
    min_preferred_exact_rows: int = 50,
    min_exact_sessions: int = 3,
    min_segment_rows: int = 30,
    require_runtime_composite: bool = True,
) -> dict[str, Any]:
    """Build a guarded shadow experiment report for the reviewed runtime gate."""
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
    shadow_frame = _add_shadow_actions(candidate_frame, preferred_preserve_matches=preferred_preserve_matches)
    capture_ts, capture_source = _component_capture_start(
        shadow_frame,
        component_capture_start=component_capture_start,
    )
    timestamps = _timestamp_series(shadow_frame)
    exact_mask = _truthy_component_source(shadow_frame)
    if capture_ts is not None:
        exact_forward_mask = exact_mask & timestamps.ge(capture_ts)
    else:
        exact_forward_mask = exact_mask & timestamps.notna()
    exact_forward = shadow_frame.loc[exact_forward_mask.fillna(False)].copy()
    exact_dates = _signal_dates(exact_forward).dropna() if not exact_forward.empty else pd.Series(dtype=str)

    action_metrics = _bucket_metrics(shadow_frame, field="runtime_gate_shadow_action", label_key="shadow_action")
    exact_action_metrics = _bucket_metrics(exact_forward, field="runtime_gate_shadow_action", label_key="shadow_action")
    segments: list[dict[str, Any]] = []
    for segment_name, field in (
        ("shadow_action", "runtime_gate_shadow_action"),
        ("shadow_reason", "runtime_gate_shadow_reason"),
        ("preserve_count", "runtime_gate_shadow_preserve_count_bucket"),
        ("guardrail_count", "runtime_gate_shadow_guardrail_count_bucket"),
        ("gamma_regime", "gamma_regime"),
        ("volatility_regime", "volatility_regime"),
        ("risk_flip_context", "risk_flip_context"),
        ("ta_entry_timing_state", "ta_entry_timing_state"),
    ):
        segments.extend(_segment_rows(shadow_frame, segment_name, field, min_rows=min_segment_rows))

    exact_segments: list[dict[str, Any]] = []
    for segment_name, field in (
        ("shadow_action", "runtime_gate_shadow_action"),
        ("shadow_reason", "runtime_gate_shadow_reason"),
        ("preserve_count", "runtime_gate_shadow_preserve_count_bucket"),
        ("guardrail_count", "runtime_gate_shadow_guardrail_count_bucket"),
    ):
        exact_segments.extend(_segment_rows(exact_forward, segment_name, field, min_rows=max(10, min_segment_rows // 2)))

    exact_timestamps = _timestamp_series(exact_forward).dropna() if not exact_forward.empty else pd.Series(dtype="datetime64[ns, UTC]")
    report = {
        "report_type": "runtime_gate_guarded_shadow_experiment",
        "generated_at": _now_utc(),
        "research_only": True,
        "runtime_config_changed": False,
        "parameter_pack_file_changed": False,
        "execution_behavior_changed": False,
        "live_promotion_ready": False,
        "dataset_path": str(dataset_path),
        "start_date": start_date,
        "end_date": end_date,
        "probability_floor": probability_floor,
        "min_preserve_matches": int(min_preserve_matches),
        "preferred_preserve_matches": int(preferred_preserve_matches),
        "min_preferred_exact_rows": int(min_preferred_exact_rows),
        "min_exact_sessions": int(min_exact_sessions),
        "min_segment_rows": int(min_segment_rows),
        "require_runtime_composite": bool(require_runtime_composite),
        "component_source_overall": component_source,
        "component_capture_start": capture_ts.isoformat() if capture_ts is not None else None,
        "component_capture_start_source": capture_source,
        "shadow_read": _shadow_read(
            exact_action_metrics=exact_action_metrics,
            exact_session_count=int(exact_dates.nunique()),
            min_preferred_exact_rows=min_preferred_exact_rows,
            min_exact_sessions=min_exact_sessions,
        ),
        "approved_shadow_scope": {
            "preserve_rule": "candidate_guardrail_count == 0 and candidate_preserve_match_count >= 3",
            "preferred_preserve_rule": f"candidate_guardrail_count == 0 and candidate_preserve_match_count >= {int(preferred_preserve_matches)}",
            "primary_horizons": ["30m", "60m"],
            "safety_horizons": ["120m", "session_close"],
        },
        "input_rows": int(len(frame if frame is not None else [])),
        "suppressed_directional_rows": int(len(shadow_frame)),
        "exact_forward_summary": {
            "exact_component_rows": int(exact_mask.fillna(False).sum()),
            "exact_forward_rows": int(len(exact_forward)),
            "exact_forward_session_count": int(exact_dates.nunique()),
            "earliest_exact_forward_signal_timestamp": exact_timestamps.min().isoformat() if not exact_timestamps.empty else None,
            "latest_exact_forward_signal_timestamp": exact_timestamps.max().isoformat() if not exact_timestamps.empty else None,
        },
        "overall_metrics": _shadow_metrics(shadow_frame) if not shadow_frame.empty else {},
        "action_metrics": action_metrics,
        "exact_action_metrics": exact_action_metrics,
        "action_comparison": _action_comparison(action_metrics),
        "exact_action_comparison": _action_comparison(exact_action_metrics),
        "segments": segments,
        "exact_segments": exact_segments,
        "promotion_requirements": [
            "At least 5 exact-forward sessions.",
            "At least 300 exact-forward candidate rows.",
            "Candidate beats guardrail and holdout on 60m signed bps and MFE/MAE.",
            "Candidate does not degrade 30m performance.",
            "Candidate does not create a materially worse 120m/session-close tail.",
            "Preserve-count 4+ remains stronger than preserve-count 3.",
            "Deferred compression slice is either split cleanly or remains blocked.",
            "No runtime config, parameter pack, data-source, or execution-behavior drift.",
        ],
        "recommended_next_actions": [
            "Keep this experiment research-only; do not alter runtime thresholds or trade decisions.",
            "Forward-monitor SHADOW_PRESERVE_PREFERRED separately from SHADOW_PRESERVE_REVIEW.",
            "Treat 30m/60m as primary horizons and 120m/session-close as tail-safety checks.",
        ],
    }
    return _sanitize_value(report)


def _markdown_table(rows: list[dict[str, Any]], columns: tuple[str, ...], *, limit: int | None = None) -> list[str]:
    selected = rows[:limit] if limit is not None else rows
    if not selected:
        return ["No rows available."]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in selected:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def render_runtime_gate_guarded_shadow_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Runtime Gate Guarded Shadow Experiment",
        "",
        "> Author: Pramit Dutta | Organization: Quant Engines",
        "",
        f"- Generated at: {report.get('generated_at')}",
        f"- Research only: `{report.get('research_only')}`",
        f"- Runtime config changed: `{report.get('runtime_config_changed')}`",
        f"- Execution behavior changed: `{report.get('execution_behavior_changed')}`",
        f"- Live promotion ready: `{report.get('live_promotion_ready')}`",
        f"- Shadow read: `{report.get('shadow_read')}`",
        f"- Component source: `{report.get('component_source_overall')}`",
        f"- Component capture start: `{report.get('component_capture_start')}`",
        "",
        "## Shadow Scope",
        "",
    ]
    scope = report.get("approved_shadow_scope") or {}
    for key, value in scope.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Exact Forward Summary", ""])
    for key, value in (report.get("exact_forward_summary") or {}).items():
        lines.append(f"- {key}: `{value}`")

    lines.extend(["", "## Shadow Actions", ""])
    lines.extend(
        _markdown_table(
            report.get("action_metrics", []) or [],
            (
                "shadow_action",
                "row_count",
                "hit_rate_30m",
                "avg_signed_return_30m_bps",
                "hit_rate_60m",
                "avg_signed_return_60m_bps",
                "mfe_mae_ratio_60m",
                "avg_signed_return_120m_bps",
                "avg_signed_return_session_close_bps",
            ),
        )
    )
    lines.extend(["", "## Exact Shadow Actions", ""])
    lines.extend(
        _markdown_table(
            report.get("exact_action_metrics", []) or [],
            (
                "shadow_action",
                "row_count",
                "hit_rate_30m",
                "avg_signed_return_30m_bps",
                "hit_rate_60m",
                "avg_signed_return_60m_bps",
                "mfe_mae_ratio_60m",
                "avg_signed_return_120m_bps",
                "avg_signed_return_session_close_bps",
            ),
        )
    )
    lines.extend(["", "## Exact Action Comparison", ""])
    for key, value in (report.get("exact_action_comparison") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Segments", ""])
    lines.extend(
        _markdown_table(
            report.get("segments", []) or [],
            (
                "segment",
                "value",
                "row_count",
                "hit_rate_60m",
                "avg_signed_return_60m_bps",
                "mfe_mae_ratio_60m",
            ),
            limit=40,
        )
    )
    lines.extend(["", "## Promotion Requirements", ""])
    for requirement in report.get("promotion_requirements", []) or []:
        lines.append(f"- {requirement}")
    lines.extend(["", "## Recommended Next Actions", ""])
    for action in report.get("recommended_next_actions", []) or []:
        lines.append(f"- {action}")
    lines.extend(["", "*Research-only shadow experiment. It does not alter live signal behavior.*", ""])
    return "\n".join(lines)


def write_runtime_gate_guarded_shadow_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_GATE_GUARDED_SHADOW_DIR,
    start_date: str | None = None,
    end_date: str | None = None,
    component_capture_start: str | None = None,
    probability_floor: float | None = None,
    min_preserve_matches: int = 3,
    preferred_preserve_matches: int = 4,
    min_preferred_exact_rows: int = 50,
    min_exact_sessions: int = 3,
    min_segment_rows: int = 30,
    require_runtime_composite: bool = True,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = _load_dataset(dataset)
    report = build_runtime_gate_guarded_shadow_report(
        frame,
        dataset_path=dataset,
        start_date=start_date,
        end_date=end_date,
        component_capture_start=component_capture_start,
        probability_floor=probability_floor,
        min_preserve_matches=min_preserve_matches,
        preferred_preserve_matches=preferred_preserve_matches,
        min_preferred_exact_rows=min_preferred_exact_rows,
        min_exact_sessions=min_exact_sessions,
        min_segment_rows=min_segment_rows,
        require_runtime_composite=require_runtime_composite,
    )
    date_part = f"{start_date or 'all'}_{end_date or 'latest'}".replace("-", "")
    stem = f"runtime_gate_guarded_shadow_experiment_{date_part}"
    json_path = output / f"{stem}.json"
    markdown_path = output / f"{stem}.md"
    segments_path = output / f"{stem}_segments.csv"
    latest_json_path = output / LATEST_JSON_FILENAME
    latest_markdown_path = output / LATEST_MARKDOWN_FILENAME
    latest_segments_path = output / LATEST_SEGMENTS_FILENAME

    markdown = render_runtime_gate_guarded_shadow_markdown(report)
    segments = pd.DataFrame((report.get("segments") or []) + (report.get("exact_segments") or []))
    _atomic_write_text(json_path, json.dumps(report, indent=2, sort_keys=True, default=str))
    _atomic_write_text(markdown_path, markdown)
    _atomic_write_csv(segments, segments_path)
    _atomic_write_text(latest_json_path, json.dumps(report, indent=2, sort_keys=True, default=str))
    _atomic_write_text(latest_markdown_path, markdown)
    _atomic_write_csv(segments, latest_segments_path)
    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "segments_path": str(segments_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
        "latest_segments_path": str(latest_segments_path),
    }

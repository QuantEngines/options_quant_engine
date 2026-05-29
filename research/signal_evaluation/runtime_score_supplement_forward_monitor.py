"""Forward monitor for research-only runtime-score supplement candidates.

The monitor reuses candidate supplement rules from
``runtime_score_supplement_replay`` and evaluates the rows those rules would
promote over the live runtime threshold.  It is deliberately research-only:
no runtime score, parameter pack, data source, or execution behavior changes.
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
from research.signal_evaluation.runtime_research_composite_gap import DEFAULT_RUNTIME_LOW_THRESHOLD
from research.signal_evaluation.runtime_score_supplement_replay import (
    _candidate_adjustments,
    _json_ready,
    _normalize_text,
    _outcome_metrics,
    _round,
    load_runtime_score_supplement_replay_dataset,
    prepare_runtime_score_supplement_replay_frame,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_SCORE_SUPPLEMENT_FORWARD_MONITOR_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_score_supplement_forward_monitor"
)

DEFAULT_CANDIDATES = ("candle_wall_plus_10", "guarded_candle_wall_plus_10")
DEFAULT_MIN_LABELED_ROWS = 50
DEFAULT_MIN_SESSION_COUNT = 3
DEFAULT_WEAK_SLICE_MIN_LABELS = 10


def _csv_tuple(value: str | tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


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


def prepare_runtime_score_supplement_forward_monitor_frame(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Prepare monitor rows without requiring ex-post composite availability."""
    prepared = prepare_runtime_score_supplement_replay_frame(frame, report_date=None)
    prepared = _filter_date_range(prepared, report_date=report_date, start_date=start_date, end_date=end_date)
    prepared["monitor_eligible"] = (
        prepared.get("has_direction", pd.Series(False, index=prepared.index)).fillna(False)
        & pd.to_numeric(prepared.get("runtime_composite_score", pd.Series(index=prepared.index)), errors="coerce").notna()
    )
    return prepared


def _group_summary(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    candidate_score_column: str,
    top_n: int = 20,
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
        row = {column: str(value) for column, value in zip(available, keys, strict=False)}
        row["subgroup"] = " / ".join(row[column] for column in available)
        row.update(_outcome_metrics(group, candidate_score_column=candidate_score_column))
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("label_count") or 0),
            -int(row.get("row_count") or 0),
            row.get("subgroup") or "",
        ),
    )[:top_n]


def _weak_slices(slices: list[dict[str, Any]], *, weak_slice_min_labels: int) -> list[dict[str, Any]]:
    weak: list[dict[str, Any]] = []
    for row in slices:
        label_count = int(row.get("label_count") or 0)
        if label_count < int(weak_slice_min_labels):
            continue
        hit_rate = _safe_float(row.get("hit_rate_60m"), None)
        avg_return = _safe_float(row.get("avg_signed_return_60m_bps"), None)
        path_ratio = _safe_float(row.get("mfe_mae_ratio_60m"), None)
        if (
            (hit_rate is not None and hit_rate < 50.0)
            or (avg_return is not None and avg_return <= 0.0)
            or (path_ratio is not None and path_ratio < 1.0)
        ):
            weak.append(row)
    return weak


def _candidate_status(
    metrics: dict[str, Any],
    *,
    session_count: int,
    weak_slice_count: int,
    min_labeled_rows: int,
    min_session_count: int,
) -> str:
    label_count = int(metrics.get("label_count") or 0)
    if label_count <= 0:
        return "FORWARD_MONITOR_PENDING_LABELS"
    if label_count < int(min_labeled_rows) or session_count < int(min_session_count):
        return "FORWARD_MONITOR_ACCUMULATING"
    hit_rate = _safe_float(metrics.get("hit_rate_60m"), 0.0)
    avg_return = _safe_float(metrics.get("avg_signed_return_60m_bps"), 0.0)
    path_ratio = _safe_float(metrics.get("mfe_mae_ratio_60m"), 0.0)
    if hit_rate >= 55.0 and avg_return > 0.0 and path_ratio >= 1.0 and weak_slice_count == 0:
        return "FORWARD_MONITOR_SUPPORTIVE"
    if hit_rate <= 45.0 or avg_return < 0.0 or path_ratio < 0.75:
        return "FORWARD_MONITOR_HURT"
    return "FORWARD_MONITOR_WATCH"


def _candidate_monitor_report(
    eligible: pd.DataFrame,
    *,
    candidate_name: str,
    definition: dict[str, Any],
    baseline_selected: pd.Series,
    baseline_threshold: float,
    min_labeled_rows: int,
    min_session_count: int,
    weak_slice_min_labels: int,
) -> dict[str, Any]:
    score = pd.to_numeric(eligible["runtime_composite_score"], errors="coerce")
    candidate_column = f"{candidate_name}_score"
    condition = definition["condition"].reindex(eligible.index).fillna(False)
    working = eligible.copy()
    working[candidate_column] = score + np.where(condition, float(definition["score_adjustment"]), 0.0)
    candidate_selected = working[candidate_column] >= float(baseline_threshold)
    promoted = working.loc[candidate_selected & ~baseline_selected.reindex(eligible.index).fillna(False)].copy()

    session_rows = _group_summary(
        promoted,
        ["signal_date"],
        candidate_score_column=candidate_column,
        top_n=200,
    )
    regime_rows = _group_summary(
        promoted,
        ["gamma_regime", "volatility_regime"],
        candidate_score_column=candidate_column,
    )
    wall_rows = _group_summary(promoted, ["wall_context_state"], candidate_score_column=candidate_column)
    direction_rows = _group_summary(promoted, ["direction"], candidate_score_column=candidate_column)
    provider_rows = _group_summary(
        promoted,
        ["provider_health_status", "provider_execution_context"],
        candidate_score_column=candidate_column,
    )
    candle_rows = _group_summary(
        promoted,
        ["confirmation_status", "ta_entry_timing_state"],
        candidate_score_column=candidate_column,
    )
    gamma_wall_rows = _group_summary(
        promoted,
        ["gamma_regime", "wall_context_state"],
        candidate_score_column=candidate_column,
    )
    all_slices = regime_rows + wall_rows + direction_rows + provider_rows + candle_rows + gamma_wall_rows
    weak = _weak_slices(all_slices, weak_slice_min_labels=weak_slice_min_labels)
    metrics = _outcome_metrics(promoted, candidate_score_column=candidate_column)
    session_count = sum(1 for row in session_rows if int(row.get("label_count") or 0) > 0)
    status = _candidate_status(
        metrics,
        session_count=session_count,
        weak_slice_count=len(weak),
        min_labeled_rows=min_labeled_rows,
        min_session_count=min_session_count,
    )
    if session_count < int(min_session_count) and status not in {
        "FORWARD_MONITOR_PENDING_LABELS",
        "FORWARD_MONITOR_ACCUMULATING",
    }:
        status = "FORWARD_MONITOR_WATCH"
    return {
        "candidate": candidate_name,
        "candidate_status": status,
        "rule_description": definition.get("rule_description"),
        "score_adjustment": float(definition["score_adjustment"]),
        "condition_rows": int(condition.sum()),
        "baseline_selected_rows": int(baseline_selected.sum()),
        "candidate_selected_rows": int(candidate_selected.sum()),
        "promoted_rows": int(len(promoted)),
        "promoted_label_count": int(metrics.get("label_count") or 0),
        "labeled_session_count": int(session_count),
        "min_labeled_rows": int(min_labeled_rows),
        "min_session_count": int(min_session_count),
        "weak_slice_count": int(len(weak)),
        "promoted_metrics": metrics,
        "session_rows": session_rows,
        "regime_rows": regime_rows,
        "wall_rows": wall_rows,
        "direction_rows": direction_rows,
        "provider_rows": provider_rows,
        "candle_rows": candle_rows,
        "gamma_wall_rows": gamma_wall_rows,
        "weak_slices": weak[:20],
    }


def _monitor_status(candidate_reports: list[dict[str, Any]]) -> str:
    if not candidate_reports:
        return "FORWARD_MONITOR_NO_CANDIDATES"
    statuses = {str(row.get("candidate_status")) for row in candidate_reports}
    if statuses == {"FORWARD_MONITOR_PENDING_LABELS"}:
        return "FORWARD_MONITOR_PENDING_LABELS"
    if "FORWARD_MONITOR_HURT" in statuses:
        return "FORWARD_MONITOR_HURT"
    if "FORWARD_MONITOR_SUPPORTIVE" in statuses:
        return "FORWARD_MONITOR_SUPPORTIVE"
    if "FORWARD_MONITOR_ACCUMULATING" in statuses:
        return "FORWARD_MONITOR_ACCUMULATING"
    return "FORWARD_MONITOR_WATCH"


def build_runtime_score_supplement_forward_monitor_report(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    candidate_names: tuple[str, ...] = DEFAULT_CANDIDATES,
    baseline_threshold: float = DEFAULT_RUNTIME_LOW_THRESHOLD,
    min_labeled_rows: int = DEFAULT_MIN_LABELED_ROWS,
    min_session_count: int = DEFAULT_MIN_SESSION_COUNT,
    weak_slice_min_labels: int = DEFAULT_WEAK_SLICE_MIN_LABELS,
) -> dict[str, Any]:
    prepared = prepare_runtime_score_supplement_forward_monitor_frame(
        frame,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    eligible = prepared.loc[prepared["monitor_eligible"]].copy()
    baseline_selected = pd.to_numeric(eligible["runtime_composite_score"], errors="coerce") >= float(baseline_threshold)
    all_definitions = _candidate_adjustments(eligible)
    selected_names = _csv_tuple(candidate_names) or DEFAULT_CANDIDATES
    candidate_reports = []
    for candidate_name in selected_names:
        definition = all_definitions.get(candidate_name)
        if not definition:
            continue
        candidate_reports.append(
            _candidate_monitor_report(
                eligible,
                candidate_name=candidate_name,
                definition=definition,
                baseline_selected=baseline_selected,
                baseline_threshold=baseline_threshold,
                min_labeled_rows=min_labeled_rows,
                min_session_count=min_session_count,
                weak_slice_min_labels=weak_slice_min_labels,
            )
        )
    candidate_reports = sorted(
        candidate_reports,
        key=lambda row: (
            row.get("candidate_status") not in {"FORWARD_MONITOR_SUPPORTIVE", "FORWARD_MONITOR_WATCH"},
            -int(row.get("promoted_label_count") or 0),
            -_safe_float((row.get("promoted_metrics") or {}).get("avg_signed_return_60m_bps"), -9999.0),
        ),
    )
    top = candidate_reports[0] if candidate_reports else {}
    report = {
        "report_type": "runtime_score_supplement_forward_monitor",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "report_date": report_date,
            "start_date": start_date,
            "end_date": end_date,
            "candidate_names": list(selected_names),
            "baseline_threshold": float(baseline_threshold),
            "min_labeled_rows": int(min_labeled_rows),
            "min_session_count": int(min_session_count),
            "weak_slice_min_labels": int(weak_slice_min_labels),
            "hindsight_guardrail": (
                "Candidate rows are selected with live-time fields only. Ex-post scores are not required "
                "for monitoring and are not used in candidate selection."
            ),
        },
        "coverage": {
            "input_rows": int(len(frame)),
            "rows_after_date_filter": int(len(prepared)),
            "eligible_rows": int(len(eligible)),
            "baseline_selected_rows": int(baseline_selected.sum()),
            "start_timestamp": prepared["signal_ts"].dropna().min().isoformat()
            if prepared["signal_ts"].notna().any()
            else None,
            "end_timestamp": prepared["signal_ts"].dropna().max().isoformat()
            if prepared["signal_ts"].notna().any()
            else None,
        },
        "monitor_status": _monitor_status(candidate_reports),
        "diagnostic_read": {
            "candidate_count": int(len(candidate_reports)),
            "top_candidate": top.get("candidate"),
            "top_candidate_status": top.get("candidate_status"),
            "top_candidate_promoted_rows": top.get("promoted_rows"),
            "top_candidate_promoted_label_count": top.get("promoted_label_count"),
            "top_candidate_labeled_session_count": top.get("labeled_session_count"),
            "top_candidate_hit_rate_60m": (top.get("promoted_metrics") or {}).get("hit_rate_60m"),
            "top_candidate_avg_return_60m_bps": (top.get("promoted_metrics") or {}).get(
                "avg_signed_return_60m_bps"
            ),
            "top_candidate_mfe_mae_ratio_60m": (top.get("promoted_metrics") or {}).get("mfe_mae_ratio_60m"),
            "top_candidate_weak_slice_count": top.get("weak_slice_count"),
        },
        "candidate_monitor": candidate_reports,
        "recommended_next_actions": _recommended_next_actions(candidate_reports),
    }
    return _json_ready(report)


def _recommended_next_actions(candidate_reports: list[dict[str, Any]]) -> list[str]:
    if not candidate_reports:
        return ["No configured supplement candidate could be evaluated; check candidate names."]
    top = candidate_reports[0]
    status = str(top.get("candidate_status") or "")
    if status == "FORWARD_MONITOR_PENDING_LABELS":
        return [
            "Keep collecting forward rows; no labeled promoted rows are available yet.",
            "Do not wire the supplement into runtime scoring before helped/hurt evidence matures.",
        ]
    if status == "FORWARD_MONITOR_ACCUMULATING":
        return [
            "Continue forward monitoring until minimum label and session guardrails are met.",
            "Review weak slices before considering any runtime score supplement.",
        ]
    if status == "FORWARD_MONITOR_SUPPORTIVE":
        return [
            "Open a manual research review for this supplement candidate.",
            "Require multi-session regime and provider robustness before live score wiring.",
        ]
    if status == "FORWARD_MONITOR_HURT":
        return [
            "Reject or redesign this supplement candidate before additional runtime work.",
            "Inspect weak slices to identify whether a narrow guarded version remains viable.",
        ]
    return [
        "Keep the candidate in WATCH and continue collecting helped/hurt evidence.",
        "Treat weak regime slices as explicit guardrails for any future candidate design.",
    ]


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


def render_runtime_score_supplement_forward_monitor_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    candidates = report.get("candidate_monitor") or []
    lines = [
        "# Runtime Score Supplement Forward Monitor",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only monitor tracks fixed live-time score supplement candidates over labeled rows. "
        "Candidate selection uses only runtime-available fields; ex-post scores are not required for monitoring. "
        "No live behavior is changed.",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Rows after date filter: `{coverage.get('rows_after_date_filter')}`",
        f"- Eligible rows: `{coverage.get('eligible_rows')}`",
        f"- Baseline selected rows: `{coverage.get('baseline_selected_rows')}`",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Monitor status: `{report.get('monitor_status')}`",
        f"- Candidate count: `{read.get('candidate_count')}`",
        f"- Top candidate: `{read.get('top_candidate')}`",
        f"- Top candidate status: `{read.get('top_candidate_status')}`",
        f"- Top candidate promoted rows: `{read.get('top_candidate_promoted_rows')}`",
        f"- Top candidate labeled rows: `{read.get('top_candidate_promoted_label_count')}`",
        f"- Top candidate labeled sessions: `{read.get('top_candidate_labeled_session_count')}`",
        f"- Top candidate hit rate 60m: `{read.get('top_candidate_hit_rate_60m')}`",
        f"- Top candidate avg return 60m bps: `{read.get('top_candidate_avg_return_60m_bps')}`",
        f"- Top candidate MFE/MAE 60m: `{read.get('top_candidate_mfe_mae_ratio_60m')}`",
        f"- Top candidate weak slices: `{read.get('top_candidate_weak_slice_count')}`",
        "",
        "## Candidate Summary",
        "",
    ]
    summary_rows = []
    for candidate in candidates:
        metrics = candidate.get("promoted_metrics") or {}
        summary_rows.append(
            {
                "candidate": candidate.get("candidate"),
                "status": candidate.get("candidate_status"),
                "promoted_rows": candidate.get("promoted_rows"),
                "label_count": candidate.get("promoted_label_count"),
                "sessions": candidate.get("labeled_session_count"),
                "hit_rate_60m": metrics.get("hit_rate_60m"),
                "avg_return_60m_bps": metrics.get("avg_signed_return_60m_bps"),
                "mfe_mae_ratio_60m": metrics.get("mfe_mae_ratio_60m"),
                "weak_slices": candidate.get("weak_slice_count"),
            }
        )
    lines.extend(
        _markdown_table(
            summary_rows,
            [
                "candidate",
                "status",
                "promoted_rows",
                "label_count",
                "sessions",
                "hit_rate_60m",
                "avg_return_60m_bps",
                "mfe_mae_ratio_60m",
                "weak_slices",
            ],
        )
    )
    for candidate in candidates:
        name = candidate.get("candidate")
        lines.extend(["", f"## {name} Monitor Detail", ""])
        lines.extend([f"- Rule: {candidate.get('rule_description')}"])
        lines.extend([f"- Score adjustment: `{candidate.get('score_adjustment')}`"])
        lines.extend(["", "### Sessions", ""])
        lines.extend(
            _markdown_table(
                candidate.get("session_rows") or [],
                ["signal_date", "row_count", "label_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"],
            )
        )
        lines.extend(["", "### Gamma X Volatility", ""])
        lines.extend(
            _markdown_table(
                candidate.get("regime_rows") or [],
                ["subgroup", "row_count", "label_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"],
            )
        )
        lines.extend(["", "### Wall Context", ""])
        lines.extend(
            _markdown_table(
                candidate.get("wall_rows") or [],
                ["subgroup", "row_count", "label_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"],
            )
        )
        lines.extend(["", "### Direction", ""])
        lines.extend(
            _markdown_table(
                candidate.get("direction_rows") or [],
                ["subgroup", "row_count", "label_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"],
            )
        )
        lines.extend(["", "### Provider Context", ""])
        lines.extend(
            _markdown_table(
                candidate.get("provider_rows") or [],
                ["subgroup", "row_count", "label_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"],
            )
        )
        lines.extend(["", "### Confirmation X Candle", ""])
        lines.extend(
            _markdown_table(
                candidate.get("candle_rows") or [],
                ["subgroup", "row_count", "label_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"],
            )
        )
        lines.extend(["", "### Weak Slices", ""])
        lines.extend(
            _markdown_table(
                candidate.get("weak_slices") or [],
                ["subgroup", "row_count", "label_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"],
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
            "- This report is research-only and does not change runtime score calculation.",
            "- Candidate rules use live-time fields only.",
            "- Ex-post scores are not used for monitor selection.",
            "- Any runtime wiring requires fresh-forward, multi-session helped/hurt validation.",
            "",
        ]
    )
    return "\n".join(lines)


def write_runtime_score_supplement_forward_monitor_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_SCORE_SUPPLEMENT_FORWARD_MONITOR_DIR,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    candidate_names: tuple[str, ...] = DEFAULT_CANDIDATES,
    baseline_threshold: float = DEFAULT_RUNTIME_LOW_THRESHOLD,
    min_labeled_rows: int = DEFAULT_MIN_LABELED_ROWS,
    min_session_count: int = DEFAULT_MIN_SESSION_COUNT,
    weak_slice_min_labels: int = DEFAULT_WEAK_SLICE_MIN_LABELS,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = load_runtime_score_supplement_replay_dataset(dataset)
    report = build_runtime_score_supplement_forward_monitor_report(
        frame,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
        candidate_names=candidate_names,
        baseline_threshold=baseline_threshold,
        min_labeled_rows=min_labeled_rows,
        min_session_count=min_session_count,
        weak_slice_min_labels=weak_slice_min_labels,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    json_path = output / f"runtime_score_supplement_forward_monitor_{timestamp}.json"
    markdown_path = output / f"runtime_score_supplement_forward_monitor_{timestamp}.md"
    latest_json_path = output / "latest_runtime_score_supplement_forward_monitor.json"
    latest_markdown_path = output / "latest_runtime_score_supplement_forward_monitor.md"
    summary_csv_path = output / f"runtime_score_supplement_forward_monitor_{timestamp}_summary.csv"
    latest_summary_csv_path = output / "latest_runtime_score_supplement_forward_monitor_summary.csv"
    sessions_csv_path = output / f"runtime_score_supplement_forward_monitor_{timestamp}_sessions.csv"
    latest_sessions_csv_path = output / "latest_runtime_score_supplement_forward_monitor_sessions.csv"
    slices_csv_path = output / f"runtime_score_supplement_forward_monitor_{timestamp}_slices.csv"
    latest_slices_csv_path = output / "latest_runtime_score_supplement_forward_monitor_slices.csv"

    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_runtime_score_supplement_forward_monitor_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")

    summary_rows = []
    session_rows = []
    slice_rows = []
    for candidate in report.get("candidate_monitor") or []:
        metrics = candidate.get("promoted_metrics") or {}
        summary_rows.append(
            {
                "candidate": candidate.get("candidate"),
                "candidate_status": candidate.get("candidate_status"),
                "promoted_rows": candidate.get("promoted_rows"),
                "promoted_label_count": candidate.get("promoted_label_count"),
                "labeled_session_count": candidate.get("labeled_session_count"),
                "hit_rate_60m": metrics.get("hit_rate_60m"),
                "avg_signed_return_60m_bps": metrics.get("avg_signed_return_60m_bps"),
                "mfe_mae_ratio_60m": metrics.get("mfe_mae_ratio_60m"),
                "weak_slice_count": candidate.get("weak_slice_count"),
            }
        )
        for row in candidate.get("session_rows") or []:
            item = dict(row)
            item["candidate"] = candidate.get("candidate")
            session_rows.append(item)
        for group_name in ("regime_rows", "wall_rows", "direction_rows", "provider_rows", "candle_rows", "gamma_wall_rows"):
            for row in candidate.get(group_name) or []:
                item = dict(row)
                item["candidate"] = candidate.get("candidate")
                item["slice_group"] = group_name
                slice_rows.append(item)
    pd.DataFrame(summary_rows).to_csv(summary_csv_path, index=False)
    pd.DataFrame(summary_rows).to_csv(latest_summary_csv_path, index=False)
    pd.DataFrame(session_rows).to_csv(sessions_csv_path, index=False)
    pd.DataFrame(session_rows).to_csv(latest_sessions_csv_path, index=False)
    pd.DataFrame(slice_rows).to_csv(slices_csv_path, index=False)
    pd.DataFrame(slice_rows).to_csv(latest_slices_csv_path, index=False)

    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="runtime_score_supplement_forward_monitor",
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
        "sessions_csv_path": str(sessions_csv_path),
        "latest_sessions_csv_path": str(latest_sessions_csv_path),
        "slices_csv_path": str(slices_csv_path),
        "latest_slices_csv_path": str(latest_slices_csv_path),
        "manifest_path": str(manifest_path),
    }

"""Research-only monitor for segmented runtime-gate redesign candidates.

This report studies whether selected suppressed directional rows deserve a
future guarded gate-redesign experiment. It does not change runtime scoring,
thresholds, parameter packs, data-source routing, or execution behavior.
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
    _filter_dates,
    _load_dataset,
    _metrics,
    _num_series,
    _observed_runtime_mask,
    _prepare_frame,
    _round_or_none,
    _safe_mean,
    _text_series,
)
from research.signal_evaluation.signal_quality_model_audit import (
    _atomic_write_csv,
    _atomic_write_text,
    _sanitize_value,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_GATE_CANDIDATE_MONITOR_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_gate_candidate_monitor"
)

LATEST_JSON_FILENAME = "latest_runtime_gate_candidate_monitor.json"
LATEST_MARKDOWN_FILENAME = "latest_runtime_gate_candidate_monitor.md"
LATEST_SEGMENTS_FILENAME = "latest_runtime_gate_candidate_monitor_segments.csv"

PROMISING_GAMMA_REGIMES = {"POSITIVE_GAMMA", "NEUTRAL_GAMMA"}
PROMISING_RISK_FLIP_CONTEXTS = {"RISK_OFF/RISK_OFF/BELOW_FLIP"}
DISCARD_GAMMA_REGIMES = {"NEGATIVE_GAMMA"}
DISCARD_VOLATILITY_REGIMES = {"LOW_VOL"}
DISCARD_RISK_FLIP_CONTEXTS = {"MACRO_NEUTRAL/GLOBAL_NEUTRAL/AT_FLIP"}


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _between(series: pd.Series, lower: float, upper: float, *, include_upper: bool = False) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if include_upper:
        return values.ge(lower) & values.le(upper)
    return values.ge(lower) & values.lt(upper)


def _risk_flip_context(frame: pd.DataFrame) -> pd.Series:
    if "risk_flip_context" in frame.columns:
        return _text_series(frame, "risk_flip_context")
    return (
        _text_series(frame, "macro_regime", default="UNKNOWN")
        + "/"
        + _text_series(frame, "global_risk_state", default="UNKNOWN")
        + "/"
        + _text_series(frame, "spot_vs_flip", default="UNKNOWN")
    )


def _add_candidate_columns(frame: pd.DataFrame, *, min_preserve_matches: int) -> pd.DataFrame:
    working = frame.copy()
    gamma = _text_series(working, "gamma_regime").str.upper()
    volatility = _text_series(working, "volatility_regime").str.upper()
    risk_context = _risk_flip_context(working).str.upper()
    pre_adjust = _num_series(working, "estimated_pre_adjust_score")
    runtime = _num_series(working, "runtime_composite_score")
    trade_strength = _num_series(working, "trade_strength")
    residual = _num_series(working, "estimated_composite_residual")

    preserve_flags: dict[str, pd.Series] = {
        "positive_or_neutral_gamma": gamma.isin(PROMISING_GAMMA_REGIMES),
        "risk_off_below_flip": risk_context.isin(PROMISING_RISK_FLIP_CONTEXTS),
        "pre_adjust_70_80": _between(pre_adjust, 70.0, 80.0),
        "runtime_35_50": _between(runtime, 35.0, 50.0),
        "trade_strength_60_70": _between(trade_strength, 60.0, 70.0),
        "compression_minus_25_to_minus_10": residual.gt(-25.0) & residual.le(-10.0),
    }
    guard_flags: dict[str, pd.Series] = {
        "negative_gamma": gamma.isin(DISCARD_GAMMA_REGIMES),
        "low_vol": volatility.isin(DISCARD_VOLATILITY_REGIMES),
        "pre_adjust_80_plus": pre_adjust.ge(80.0),
        "trade_strength_80_plus": trade_strength.ge(80.0),
        "macro_neutral_at_flip": risk_context.isin(DISCARD_RISK_FLIP_CONTEXTS),
        "extreme_or_positive_compression": residual.le(-40.0) | residual.ge(0.0),
    }
    for name, flag in preserve_flags.items():
        working[f"candidate_preserve_{name}"] = flag.fillna(False)
    for name, flag in guard_flags.items():
        working[f"candidate_guard_{name}"] = flag.fillna(False)

    preserve_count = sum(working[f"candidate_preserve_{name}"].astype(int) for name in preserve_flags)
    guard_count = sum(working[f"candidate_guard_{name}"].astype(int) for name in guard_flags)
    working["candidate_preserve_match_count"] = preserve_count
    working["candidate_guardrail_count"] = guard_count
    working["runtime_gate_candidate_bucket"] = "RESEARCH_HOLDOUT"
    working.loc[guard_count > 0, "runtime_gate_candidate_bucket"] = "KEEP_BLOCKED_GUARDRAIL"
    working.loc[
        (guard_count == 0) & (preserve_count >= int(min_preserve_matches)),
        "runtime_gate_candidate_bucket",
    ] = "CANDIDATE_MONITOR"

    reason = pd.Series("insufficient_preserve_matches", index=working.index, dtype="object")
    for name in guard_flags:
        reason = reason.where(
            ~((reason == "insufficient_preserve_matches") & working[f"candidate_guard_{name}"]),
            f"guard:{name}",
        )
    reason = reason.where(
        working["runtime_gate_candidate_bucket"] != "CANDIDATE_MONITOR",
        f"candidate:preserve_matches>={int(min_preserve_matches)}",
    )
    working["runtime_gate_candidate_reason"] = reason
    working["candidate_preserve_match_count_bucket"] = working["candidate_preserve_match_count"].astype(str)
    working["candidate_guardrail_count_bucket"] = working["candidate_guardrail_count"].astype(str)
    return working


def _segment_rows(frame: pd.DataFrame, segment_name: str, field: str, *, min_rows: int) -> list[dict[str, Any]]:
    if frame.empty or field not in frame.columns:
        return []
    rows: list[dict[str, Any]] = []
    values = _text_series(frame, field)
    for value, group in frame.groupby(values, dropna=False):
        if len(group) < min_rows:
            continue
        rows.append({"segment": segment_name, "value": str(value), **_metrics(group)})
    return sorted(rows, key=lambda item: (-int(item.get("row_count") or 0), str(item.get("value"))))


def _candidate_bucket_metrics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for bucket, group in frame.groupby(_text_series(frame, "runtime_gate_candidate_bucket"), dropna=False):
        row = {
            "bucket": str(bucket),
            **_metrics(group),
            "avg_preserve_match_count": _round_or_none(_safe_mean(_num_series(group, "candidate_preserve_match_count")), 4),
            "avg_guardrail_count": _round_or_none(_safe_mean(_num_series(group, "candidate_guardrail_count")), 4),
        }
        rows.append(row)
    return sorted(rows, key=lambda item: str(item.get("bucket")))


def _candidate_read(bucket_metrics: list[dict[str, Any]], *, min_candidate_rows: int) -> str:
    candidate = next((row for row in bucket_metrics if row.get("bucket") == "CANDIDATE_MONITOR"), None)
    if not candidate or int(candidate.get("row_count") or 0) < int(min_candidate_rows):
        return "CANDIDATE_EVIDENCE_ACCUMULATING"
    hit = candidate.get("hit_rate_60m")
    ret = candidate.get("avg_signed_return_60m_bps")
    ratio = candidate.get("mfe_mae_ratio_60m")
    if hit is not None and ret is not None and ratio is not None:
        if float(hit) >= 0.58 and float(ret) > 0 and float(ratio) >= 1.2:
            return "SEGMENTED_CANDIDATE_PROMISING_RESEARCH_ONLY"
        if float(ret) <= 0 or float(ratio) < 1.0:
            return "SEGMENTED_CANDIDATE_WEAK_KEEP_RESEARCH_ONLY"
    return "SEGMENTED_CANDIDATE_MIXED_RESEARCH_ONLY"


def prepare_runtime_gate_candidate_frame(
    frame: pd.DataFrame,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    probability_floor: float | None = None,
    min_preserve_matches: int = 3,
    require_runtime_composite: bool = True,
) -> tuple[pd.DataFrame, str]:
    """Return suppressed directional rows with runtime-gate candidate buckets.

    This helper is research-only and centralizes the candidate classification so
    monitor/readiness reports cannot drift from each other.
    """
    probability_floor = (
        float(probability_floor)
        if probability_floor is not None
        else float(SIGNAL_EVALUATION_SELECTION_POLICY.get("move_probability_floor", 0.60))
    )
    dated = _filter_dates(frame if frame is not None else pd.DataFrame(), start_date=start_date, end_date=end_date)
    prepared, component_source = _prepare_frame(dated, probability_floor=probability_floor)
    if require_runtime_composite and not prepared.empty:
        prepared = prepared.loc[_observed_runtime_mask(prepared)].copy()
    candidate_frame = (
        _add_candidate_columns(prepared, min_preserve_matches=min_preserve_matches)
        if not prepared.empty
        else prepared.copy()
    )
    return candidate_frame, component_source


def build_runtime_gate_candidate_monitor_report(
    frame: pd.DataFrame,
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    probability_floor: float | None = None,
    min_preserve_matches: int = 3,
    min_candidate_rows: int = 100,
    min_segment_rows: int = 30,
    require_runtime_composite: bool = True,
) -> dict[str, Any]:
    """Build a research-only segmented runtime-gate candidate report."""
    probability_floor = (
        float(probability_floor)
        if probability_floor is not None
        else float(SIGNAL_EVALUATION_SELECTION_POLICY.get("move_probability_floor", 0.60))
    )
    dated = _filter_dates(frame if frame is not None else pd.DataFrame(), start_date=start_date, end_date=end_date)
    candidate_frame, component_source = prepare_runtime_gate_candidate_frame(
        dated,
        probability_floor=probability_floor,
        min_preserve_matches=min_preserve_matches,
        require_runtime_composite=require_runtime_composite,
    )
    bucket_metrics = _candidate_bucket_metrics(candidate_frame)
    segments: list[dict[str, Any]] = []
    for segment_name, field in (
        ("signal_date", "_signal_date"),
        ("runtime_gate_candidate_bucket", "runtime_gate_candidate_bucket"),
        ("runtime_gate_candidate_reason", "runtime_gate_candidate_reason"),
        ("candidate_preserve_match_count", "candidate_preserve_match_count_bucket"),
        ("candidate_guardrail_count", "candidate_guardrail_count_bucket"),
        ("gamma_regime", "gamma_regime"),
        ("volatility_regime", "volatility_regime"),
        ("risk_flip_context", "risk_flip_context"),
        ("ta_entry_timing_state", "ta_entry_timing_state"),
    ):
        segments.extend(_segment_rows(candidate_frame, segment_name, field, min_rows=min_segment_rows))

    report = {
        "report_type": "runtime_gate_candidate_monitor",
        "generated_at": _now_utc(),
        "research_only": True,
        "runtime_config_changed": False,
        "parameter_pack_file_changed": False,
        "execution_behavior_changed": False,
        "dataset_path": str(dataset_path),
        "start_date": start_date,
        "end_date": end_date,
        "probability_floor": probability_floor,
        "min_preserve_matches": int(min_preserve_matches),
        "min_candidate_rows": int(min_candidate_rows),
        "min_segment_rows": int(min_segment_rows),
        "require_runtime_composite": bool(require_runtime_composite),
        "input_rows": int(len(dated)),
        "suppressed_directional_rows": int(len(candidate_frame)),
        "component_source": component_source,
        "overall_metrics": _metrics(candidate_frame) if not candidate_frame.empty else {},
        "candidate_bucket_metrics": bucket_metrics,
        "candidate_read": _candidate_read(bucket_metrics, min_candidate_rows=min_candidate_rows),
        "promotion_ready": False,
        "candidate_config": {
            "preserve_conditions": [
                "gamma_regime in POSITIVE_GAMMA, NEUTRAL_GAMMA",
                "risk context RISK_OFF/RISK_OFF/BELOW_FLIP",
                "estimated pre-adjust runtime component blend 70-80",
                "runtime composite 35-50",
                "trade strength 60-70",
                "compression -25 to -10",
            ],
            "guardrail_conditions": [
                "NEGATIVE_GAMMA",
                "LOW_VOL",
                "estimated pre-adjust >= 80",
                "trade strength >= 80",
                "MACRO_NEUTRAL/GLOBAL_NEUTRAL/AT_FLIP",
                "compression <= -40 or >= 0",
            ],
        },
        "segments": segments,
        "recommended_next_actions": [
            "Keep this candidate research-only; do not alter runtime composite thresholds.",
            "Require exact runtime_composite_components forward rows before promotion review.",
            "Promote only if candidate-monitor rows improve signed bps and MFE/MAE versus guardrail and holdout rows across multiple sessions.",
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


def render_runtime_gate_candidate_monitor_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Runtime Gate Candidate Monitor",
        "",
        "> Author: Pramit Dutta | Organization: Quant Engines",
        "",
        f"- Generated at: {report.get('generated_at')}",
        f"- Date range: `{report.get('start_date')}` to `{report.get('end_date')}`",
        f"- Research only: `{report.get('research_only')}`",
        f"- Runtime config changed: `{report.get('runtime_config_changed')}`",
        f"- Component source: `{report.get('component_source')}`",
        f"- Candidate read: `{report.get('candidate_read')}`",
        f"- Promotion ready: `{report.get('promotion_ready')}`",
        "",
        "## Overall",
        "",
    ]
    overall = report.get("overall_metrics") or {}
    for key in (
        "row_count",
        "label_count_60m",
        "avg_runtime_composite",
        "avg_estimated_pre_adjust",
        "avg_final_minus_estimated",
        "hit_rate_60m",
        "avg_signed_return_60m_bps",
        "mfe_mae_ratio_60m",
    ):
        lines.append(f"- {key}: `{overall.get(key)}`")
    lines.extend(["", "## Candidate Buckets", ""])
    lines.extend(
        _markdown_table(
            report.get("candidate_bucket_metrics", []) or [],
            (
                "bucket",
                "row_count",
                "hit_rate_60m",
                "avg_signed_return_60m_bps",
                "mfe_mae_ratio_60m",
                "avg_preserve_match_count",
                "avg_guardrail_count",
            ),
        )
    )
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
    lines.extend(["", "## Recommended Next Actions", ""])
    for action in report.get("recommended_next_actions", []) or []:
        lines.append(f"- {action}")
    lines.extend(["", "*Research-only monitor. It does not alter live signal behavior.*", ""])
    return "\n".join(lines)


def write_runtime_gate_candidate_monitor_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_GATE_CANDIDATE_MONITOR_DIR,
    start_date: str | None = None,
    end_date: str | None = None,
    probability_floor: float | None = None,
    min_preserve_matches: int = 3,
    min_candidate_rows: int = 100,
    min_segment_rows: int = 30,
    require_runtime_composite: bool = True,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = _load_dataset(dataset)
    report = build_runtime_gate_candidate_monitor_report(
        frame,
        dataset_path=dataset,
        start_date=start_date,
        end_date=end_date,
        probability_floor=probability_floor,
        min_preserve_matches=min_preserve_matches,
        min_candidate_rows=min_candidate_rows,
        min_segment_rows=min_segment_rows,
        require_runtime_composite=require_runtime_composite,
    )
    date_part = f"{start_date or 'all'}_{end_date or 'latest'}".replace("-", "")
    stem = f"runtime_gate_candidate_monitor_{date_part}"
    json_path = output / f"{stem}.json"
    markdown_path = output / f"{stem}.md"
    segments_path = output / f"{stem}_segments.csv"
    latest_json_path = output / LATEST_JSON_FILENAME
    latest_markdown_path = output / LATEST_MARKDOWN_FILENAME
    latest_segments_path = output / LATEST_SEGMENTS_FILENAME

    markdown = render_runtime_gate_candidate_monitor_markdown(report)
    _atomic_write_text(json_path, json.dumps(report, indent=2, sort_keys=True, default=str))
    _atomic_write_text(markdown_path, markdown)
    _atomic_write_text(latest_json_path, json.dumps(report, indent=2, sort_keys=True, default=str))
    _atomic_write_text(latest_markdown_path, markdown)
    segments = pd.DataFrame(report.get("segments", []) or [])
    _atomic_write_csv(segments, segments_path)
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

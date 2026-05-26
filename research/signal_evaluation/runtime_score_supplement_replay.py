"""Research-only replay for candidate runtime-score supplements.

This module tests whether live-time candle/range and level-context clues could
have recovered good low-runtime-score rows.  It does not change runtime engine
behavior.  The post-evaluation research score is used only for reporting
recovered blindspots, never as a candidate rule input.
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
    load_runtime_blindspot_feature_audit_dataset,
    prepare_runtime_blindspot_feature_frame,
)
from research.signal_evaluation.runtime_research_composite_gap import (
    DEFAULT_RESEARCH_HIGH_THRESHOLD,
    DEFAULT_RUNTIME_LOW_THRESHOLD,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_SCORE_SUPPLEMENT_REPLAY_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_score_supplement_replay"
)

DEFAULT_BASELINE_THRESHOLD = DEFAULT_RUNTIME_LOW_THRESHOLD
DEFAULT_MIN_PROMOTED_LABELS = 10


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


def _normalize_text(series: pd.Series, default: str = "UNKNOWN") -> pd.Series:
    return (
        series.astype("object")
        .where(series.notna(), default)
        .astype(str)
        .str.strip()
        .replace({"": default, "nan": default, "NaN": default, "None": default})
    )


def _truthy_series(series: pd.Series) -> pd.Series:
    text = series.fillna(False).astype(str).str.strip().str.upper()
    return text.isin({"1", "1.0", "TRUE", "YES", "Y", "ON"})


def _mean(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.mean())


def _share(mask: pd.Series) -> float | None:
    if mask.empty:
        return None
    return float(mask.fillna(False).mean() * 100.0)


def _mfe_mae_ratio(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    mfe = pd.to_numeric(frame.get("mfe_60m_bps", pd.Series(dtype=float)), errors="coerce")
    mae = pd.to_numeric(frame.get("mae_60m_bps", pd.Series(dtype=float)), errors="coerce").abs()
    avg_mfe = _mean(mfe)
    avg_mae = _mean(mae)
    if avg_mfe is None or avg_mae is None or avg_mae <= 0:
        return None
    return avg_mfe / avg_mae


def load_runtime_score_supplement_replay_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    return load_runtime_blindspot_feature_audit_dataset(path)


def prepare_runtime_score_supplement_replay_frame(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
) -> pd.DataFrame:
    working = prepare_runtime_blindspot_feature_frame(frame, report_date=report_date)
    for column in (
        "ta_candle_range_expansion_ratio",
        "ta_candle_momentum_3_bps",
        "ta_candle_momentum_5_bps",
        "ta_candle_close_location",
        "ta_entry_timing_score",
        "nearest_wall_distance_pct",
        "support_wall_distance_pct",
        "resistance_wall_distance_pct",
    ):
        if column not in working.columns:
            working[column] = pd.NA
        working[column] = pd.to_numeric(working[column], errors="coerce")
    return working


def _direction_sign(frame: pd.DataFrame) -> pd.Series:
    direction = _normalize_text(frame.get("direction", pd.Series(index=frame.index))).str.upper()
    return pd.Series(np.select([direction.eq("CALL"), direction.eq("PUT")], [1.0, -1.0], default=np.nan), index=frame.index)


def _range_expanded(frame: pd.DataFrame) -> pd.Series:
    explicit = _truthy_series(frame.get("ta_candle_range_expanded", pd.Series(index=frame.index)))
    ratio = pd.to_numeric(frame.get("ta_candle_range_expansion_ratio", pd.Series(index=frame.index)), errors="coerce")
    return explicit | (ratio >= 1.20)


def _candle_supportive(frame: pd.DataFrame) -> pd.Series:
    direction = _normalize_text(frame.get("direction", pd.Series(index=frame.index))).str.upper()
    candle_state = _normalize_text(frame.get("ta_candle_state", pd.Series(index=frame.index))).str.upper()
    entry_state = _normalize_text(frame.get("ta_entry_timing_state", pd.Series(index=frame.index))).str.upper()
    candle_direction = _normalize_text(frame.get("ta_candle_direction", pd.Series(index=frame.index))).str.upper()
    state_text = candle_state + "|" + entry_state
    sign = _direction_sign(frame)
    momentum_3 = pd.to_numeric(frame.get("ta_candle_momentum_3_bps", pd.Series(index=frame.index)), errors="coerce")
    momentum_5 = pd.to_numeric(frame.get("ta_candle_momentum_5_bps", pd.Series(index=frame.index)), errors="coerce")
    close_location = pd.to_numeric(frame.get("ta_candle_close_location", pd.Series(index=frame.index)), errors="coerce")
    timing_score = pd.to_numeric(frame.get("ta_entry_timing_score", pd.Series(index=frame.index)), errors="coerce")

    confirmed = (
        (direction.eq("CALL") & state_text.str.contains("CONFIRMED_CALL", na=False))
        | (direction.eq("PUT") & state_text.str.contains("CONFIRMED_PUT", na=False))
    )
    rejection_supports = (
        (direction.eq("CALL") & state_text.str.contains("REJECTION_BULLISH", na=False))
        | (direction.eq("PUT") & state_text.str.contains("REJECTION_BEARISH", na=False))
    )
    momentum_aligned = ((momentum_3 * sign) > 0) | ((momentum_5 * sign) > 0) | candle_direction.eq(direction)
    close_aligned = (direction.eq("CALL") & (close_location >= 0.60)) | (direction.eq("PUT") & (close_location <= 0.40))
    forming_aligned = state_text.str.contains("FORMING", na=False) & momentum_aligned & close_aligned
    not_late_chase = ~_truthy_series(frame.get("ta_candle_late_chase", pd.Series(index=frame.index)))
    not_contradictory_rejection = ~(
        (direction.eq("CALL") & state_text.str.contains("REJECTION_BEARISH", na=False))
        | (direction.eq("PUT") & state_text.str.contains("REJECTION_BULLISH", na=False))
    )
    score_support = timing_score.isna() | (timing_score >= 45.0)
    return (confirmed | rejection_supports | forming_aligned) & not_late_chase & not_contradictory_rejection & score_support


def _level_supportive(frame: pd.DataFrame) -> pd.Series:
    direction = _normalize_text(frame.get("direction", pd.Series(index=frame.index))).str.upper()
    wall_context = _normalize_text(frame.get("wall_context_state", pd.Series(index=frame.index))).str.upper()
    historical_wall = _normalize_text(frame.get("historical_wall_state", pd.Series(index=frame.index))).str.upper()
    nearest_bucket = _normalize_text(frame.get("nearest_wall_bucket", pd.Series(index=frame.index))).str.upper()
    max_pain_zone = _normalize_text(frame.get("max_pain_zone", pd.Series(index=frame.index))).str.upper()
    historical_max_pain = _normalize_text(frame.get("historical_max_pain_state", pd.Series(index=frame.index))).str.upper()
    wall_text = wall_context + "|" + historical_wall
    max_pain_text = max_pain_zone + "|" + historical_max_pain
    away_from_walls = wall_text.str.contains("AWAY_FROM_NEAREST_WALL", na=False) | nearest_bucket.eq("AWAY_FROM_WALL")
    far_from_max_pain = max_pain_text.str.contains("FAR_FROM_MAX_PAIN", na=False)
    directional_wall = (
        (direction.eq("CALL") & wall_text.str.contains("NEAR_RESISTANCE_WALL", na=False))
        | (direction.eq("PUT") & wall_text.str.contains("NEAR_SUPPORT_WALL", na=False))
    )
    return away_from_walls | far_from_max_pain | directional_wall


def _analytics_usable(frame: pd.DataFrame) -> pd.Series:
    return _truthy_series(frame.get("analytics_usable", pd.Series(index=frame.index)))


def _candidate_adjustments(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    range_expanded = _range_expanded(frame)
    candle_supportive = _candle_supportive(frame)
    level_supportive = _level_supportive(frame)
    analytics_usable = _analytics_usable(frame)
    return {
        "candle_range_plus_8": {
            "score_adjustment": 8.0,
            "condition": candle_supportive & range_expanded,
            "rule_description": "Add 8 when live candle structure supports direction and range is expanded.",
        },
        "level_wall_plus_6": {
            "score_adjustment": 6.0,
            "condition": level_supportive,
            "rule_description": "Add 6 when wall/max-pain context is not obvious friction or a directional wall is in play.",
        },
        "candle_wall_plus_10": {
            "score_adjustment": 10.0,
            "condition": candle_supportive & level_supportive,
            "rule_description": "Add 10 only when candle timing and level context agree.",
        },
        "guarded_candle_wall_plus_10": {
            "score_adjustment": 10.0,
            "condition": candle_supportive & level_supportive & analytics_usable,
            "rule_description": "Same as candle_wall_plus_10, but disabled when analytics is not usable.",
        },
    }


def _outcome_metrics(frame: pd.DataFrame, *, candidate_score_column: str | None = None) -> dict[str, Any]:
    if frame.empty:
        return {
            "row_count": 0,
            "label_count": 0,
            "hit_rate_60m": None,
            "avg_signed_return_60m_bps": None,
            "mfe_mae_ratio_60m": None,
            "avg_runtime_composite_score": None,
            "avg_candidate_score": None,
        }
    correct = pd.to_numeric(frame.get("correct_60m", pd.Series(dtype=float)), errors="coerce")
    outcome = _normalize_text(frame.get("outcome_status", pd.Series(index=frame.index))).str.upper()
    return {
        "row_count": int(len(frame)),
        "label_count": int(correct.notna().sum()),
        "complete_outcome_share": _round(_share(outcome.eq("COMPLETE"))),
        "partial_outcome_share": _round(_share(outcome.eq("PARTIAL"))),
        "hit_rate_60m": _round(_mean(correct) * 100.0) if _mean(correct) is not None else None,
        "avg_signed_return_60m_bps": _round(_mean(frame.get("signed_return_60m_bps", pd.Series(dtype=float)))),
        "avg_mfe_60m_bps": _round(_mean(frame.get("mfe_60m_bps", pd.Series(dtype=float)))),
        "avg_mae_60m_bps": _round(_mean(frame.get("mae_60m_bps", pd.Series(dtype=float)))),
        "mfe_mae_ratio_60m": _round(_mfe_mae_ratio(frame), 3),
        "avg_runtime_composite_score": _round(_mean(frame.get("runtime_composite_score", pd.Series(dtype=float)))),
        "avg_candidate_score": _round(_mean(frame.get(candidate_score_column, pd.Series(dtype=float))))
        if candidate_score_column
        else None,
    }


def _candidate_assessment(promoted: pd.DataFrame, *, min_promoted_labels: int) -> str:
    metrics = _outcome_metrics(promoted)
    label_count = int(metrics.get("label_count") or 0)
    if label_count < min_promoted_labels:
        return "INSUFFICIENT_PROMOTED_LABELS"
    hit_rate = _safe_float(metrics.get("hit_rate_60m"), 0.0)
    avg_return = _safe_float(metrics.get("avg_signed_return_60m_bps"), 0.0)
    path_ratio = _safe_float(metrics.get("mfe_mae_ratio_60m"), 0.0)
    if hit_rate >= 55.0 and avg_return > 0.0 and path_ratio >= 1.0:
        return "SUPPORTIVE_REPLAY"
    if hit_rate <= 45.0 or avg_return < 0.0 or path_ratio < 0.75:
        return "HURT_REPLAY"
    return "MIXED_REPLAY"


def _group_summary(frame: pd.DataFrame, columns: list[str], *, top_n: int = 8) -> list[dict[str, Any]]:
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
        row.update(_outcome_metrics(group))
        rows.append(row)
    return sorted(rows, key=lambda row: (-int(row.get("row_count") or 0), row.get("subgroup") or ""))[:top_n]


def _candidate_report(
    prepared: pd.DataFrame,
    *,
    candidate_name: str,
    score_adjustment: float,
    condition: pd.Series,
    baseline_selected: pd.Series,
    baseline_threshold: float,
    research_high_threshold: float,
    min_promoted_labels: int,
    rule_description: str,
) -> dict[str, Any]:
    score = pd.to_numeric(prepared["runtime_composite_score"], errors="coerce")
    candidate_column = f"{candidate_name}_score"
    working = prepared.copy()
    working[candidate_column] = score + np.where(condition.fillna(False), float(score_adjustment), 0.0)
    candidate_selected = working[candidate_column] >= float(baseline_threshold)
    promoted_mask = candidate_selected & ~baseline_selected
    promoted = working.loc[promoted_mask].copy()
    candidate_selected_frame = working.loc[candidate_selected].copy()
    baseline_selected_frame = working.loc[baseline_selected].copy()
    recovered_blindspot = promoted.loc[
        pd.to_numeric(promoted.get("composite_signal_score", pd.Series(dtype=float)), errors="coerce")
        >= float(research_high_threshold)
    ].copy()
    correct = pd.to_numeric(promoted.get("correct_60m", pd.Series(dtype=float)), errors="coerce")
    signed_return = pd.to_numeric(promoted.get("signed_return_60m_bps", pd.Series(dtype=float)), errors="coerce")
    metrics = _outcome_metrics(candidate_selected_frame, candidate_score_column=candidate_column)
    baseline_metrics = _outcome_metrics(baseline_selected_frame)
    promoted_metrics = _outcome_metrics(promoted, candidate_score_column=candidate_column)
    return {
        "candidate": candidate_name,
        "rule_description": rule_description,
        "score_adjustment": float(score_adjustment),
        "condition_rows": int(condition.fillna(False).sum()),
        "baseline_selected_rows": int(baseline_selected.sum()),
        "candidate_selected_rows": int(candidate_selected.sum()),
        "promoted_rows": int(promoted_mask.sum()),
        "recovered_research_blindspot_rows": int(len(recovered_blindspot)),
        "helpful_promoted_rows": int((correct == 1.0).sum()),
        "harmful_promoted_rows": int((correct == 0.0).sum()),
        "unknown_promoted_rows": int(correct.isna().sum()),
        "promoted_signed_return_sum_bps": _round(signed_return.sum(min_count=1)),
        "candidate_selected_metrics": metrics,
        "baseline_selected_metrics": baseline_metrics,
        "promoted_metrics": promoted_metrics,
        "delta_selected_hit_rate_60m": _round(
            _safe_float(metrics.get("hit_rate_60m"), 0.0) - _safe_float(baseline_metrics.get("hit_rate_60m"), 0.0)
        )
        if metrics.get("hit_rate_60m") is not None and baseline_metrics.get("hit_rate_60m") is not None
        else None,
        "delta_selected_avg_return_60m_bps": _round(
            _safe_float(metrics.get("avg_signed_return_60m_bps"), 0.0)
            - _safe_float(baseline_metrics.get("avg_signed_return_60m_bps"), 0.0)
        )
        if metrics.get("avg_signed_return_60m_bps") is not None
        and baseline_metrics.get("avg_signed_return_60m_bps") is not None
        else None,
        "assessment": _candidate_assessment(promoted, min_promoted_labels=min_promoted_labels),
        "promoted_by_gamma_vol": _group_summary(promoted, ["gamma_regime", "volatility_regime"]),
        "promoted_by_confirmation_candle": _group_summary(promoted, ["confirmation_status", "ta_entry_timing_state"]),
        "promoted_by_provider_context": _group_summary(promoted, ["provider_health_status", "provider_execution_context"]),
    }


def build_runtime_score_supplement_replay_report(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    baseline_threshold: float = DEFAULT_BASELINE_THRESHOLD,
    research_high_threshold: float = DEFAULT_RESEARCH_HIGH_THRESHOLD,
    min_promoted_labels: int = DEFAULT_MIN_PROMOTED_LABELS,
) -> dict[str, Any]:
    prepared = prepare_runtime_score_supplement_replay_frame(frame, report_date=report_date)
    comparable = prepared.loc[prepared["has_comparable_scores"]].copy()
    baseline_selected = pd.to_numeric(comparable["runtime_composite_score"], errors="coerce") >= float(baseline_threshold)
    candidates = []
    for candidate_name, definition in _candidate_adjustments(comparable).items():
        candidates.append(
            _candidate_report(
                comparable,
                candidate_name=candidate_name,
                score_adjustment=float(definition["score_adjustment"]),
                condition=definition["condition"],
                baseline_selected=baseline_selected,
                baseline_threshold=baseline_threshold,
                research_high_threshold=research_high_threshold,
                min_promoted_labels=min_promoted_labels,
                rule_description=str(definition["rule_description"]),
            )
        )
    candidates = sorted(
        candidates,
        key=lambda row: (
            row.get("assessment") != "SUPPORTIVE_REPLAY",
            -int(row.get("recovered_research_blindspot_rows") or 0),
            -int(row.get("helpful_promoted_rows") or 0),
        ),
    )
    report = {
        "report_type": "runtime_score_supplement_replay",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "report_date": report_date,
            "baseline_threshold": float(baseline_threshold),
            "research_high_threshold": float(research_high_threshold),
            "min_promoted_labels": int(min_promoted_labels),
            "hindsight_guardrail": (
                "Candidate supplements use live-time fields only. composite_signal_score is used only "
                "to report whether promoted rows were research blindspots."
            ),
        },
        "coverage": {
            "input_rows": int(len(frame)),
            "rows_after_date_filter": int(len(prepared)),
            "comparable_rows": int(len(comparable)),
            "baseline_selected_rows": int(baseline_selected.sum()),
            "start_timestamp": prepared["signal_ts"].dropna().min().isoformat()
            if prepared["signal_ts"].notna().any()
            else None,
            "end_timestamp": prepared["signal_ts"].dropna().max().isoformat()
            if prepared["signal_ts"].notna().any()
            else None,
        },
        "baseline_selected_metrics": _outcome_metrics(comparable.loc[baseline_selected].copy()),
        "candidate_replay": candidates,
    }
    report["diagnostic_read"] = _diagnostic_read(report)
    return _json_ready(report)


def _diagnostic_read(report: dict[str, Any]) -> dict[str, Any]:
    candidates = report.get("candidate_replay") or []
    supportive = [row for row in candidates if row.get("assessment") == "SUPPORTIVE_REPLAY"]
    top = candidates[0] if candidates else {}
    return {
        "candidate_count": int(len(candidates)),
        "supportive_candidate_count": int(len(supportive)),
        "top_candidate": top.get("candidate"),
        "top_candidate_assessment": top.get("assessment"),
        "top_candidate_promoted_rows": top.get("promoted_rows"),
        "top_candidate_recovered_blindspots": top.get("recovered_research_blindspot_rows"),
        "top_candidate_promoted_hit_rate_60m": (top.get("promoted_metrics") or {}).get("hit_rate_60m"),
        "top_candidate_promoted_avg_return_60m_bps": (top.get("promoted_metrics") or {}).get(
            "avg_signed_return_60m_bps"
        ),
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


def render_runtime_score_supplement_replay_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    candidates = report.get("candidate_replay") or []
    lines = [
        "# Runtime Score Supplement Replay",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only replay tests fixed live-time score supplements. Baseline selection is "
        "`runtime_composite_score >= baseline_threshold`; candidates only add rows that cross the "
        "same threshold after a supplement. No live behavior is changed.",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Rows after date filter: `{coverage.get('rows_after_date_filter')}`",
        f"- Comparable rows: `{coverage.get('comparable_rows')}`",
        f"- Baseline selected rows: `{coverage.get('baseline_selected_rows')}`",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Candidate count: `{read.get('candidate_count')}`",
        f"- Supportive candidates: `{read.get('supportive_candidate_count')}`",
        f"- Top candidate: `{read.get('top_candidate')}`",
        f"- Top candidate assessment: `{read.get('top_candidate_assessment')}`",
        f"- Top candidate promoted rows: `{read.get('top_candidate_promoted_rows')}`",
        f"- Top candidate recovered research blindspots: `{read.get('top_candidate_recovered_blindspots')}`",
        f"- Top candidate promoted hit rate 60m: `{read.get('top_candidate_promoted_hit_rate_60m')}`",
        f"- Top candidate promoted avg return 60m bps: `{read.get('top_candidate_promoted_avg_return_60m_bps')}`",
        "",
        "## Candidate Summary",
        "",
    ]
    summary_rows = []
    for candidate in candidates:
        promoted_metrics = candidate.get("promoted_metrics") or {}
        selected_metrics = candidate.get("candidate_selected_metrics") or {}
        summary_rows.append(
            {
                "candidate": candidate.get("candidate"),
                "assessment": candidate.get("assessment"),
                "condition_rows": candidate.get("condition_rows"),
                "promoted_rows": candidate.get("promoted_rows"),
                "recovered_research_blindspot_rows": candidate.get("recovered_research_blindspot_rows"),
                "helpful_promoted_rows": candidate.get("helpful_promoted_rows"),
                "harmful_promoted_rows": candidate.get("harmful_promoted_rows"),
                "unknown_promoted_rows": candidate.get("unknown_promoted_rows"),
                "promoted_hit_rate_60m": promoted_metrics.get("hit_rate_60m"),
                "promoted_avg_return_60m_bps": promoted_metrics.get("avg_signed_return_60m_bps"),
                "promoted_mfe_mae_ratio_60m": promoted_metrics.get("mfe_mae_ratio_60m"),
                "selected_delta_hit_rate_60m": candidate.get("delta_selected_hit_rate_60m"),
                "selected_delta_avg_return_60m_bps": candidate.get("delta_selected_avg_return_60m_bps"),
                "candidate_selected_hit_rate_60m": selected_metrics.get("hit_rate_60m"),
            }
        )
    lines.extend(
        _markdown_table(
            summary_rows,
            [
                "candidate",
                "assessment",
                "condition_rows",
                "promoted_rows",
                "recovered_research_blindspot_rows",
                "helpful_promoted_rows",
                "harmful_promoted_rows",
                "unknown_promoted_rows",
                "promoted_hit_rate_60m",
                "promoted_avg_return_60m_bps",
                "promoted_mfe_mae_ratio_60m",
                "selected_delta_hit_rate_60m",
                "selected_delta_avg_return_60m_bps",
                "candidate_selected_hit_rate_60m",
            ],
        )
    )
    lines.extend(["", "## Candidate Rules", ""])
    rule_rows = [
        {
            "candidate": candidate.get("candidate"),
            "score_adjustment": candidate.get("score_adjustment"),
            "rule_description": candidate.get("rule_description"),
        }
        for candidate in candidates
    ]
    lines.extend(_markdown_table(rule_rows, ["candidate", "score_adjustment", "rule_description"]))

    for candidate in candidates:
        lines.extend(["", f"## {candidate.get('candidate')} Promoted Slices", ""])
        lines.extend(["", "### Gamma X Volatility", ""])
        lines.extend(
            _markdown_table(
                candidate.get("promoted_by_gamma_vol") or [],
                ["subgroup", "row_count", "label_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"],
            )
        )
        lines.extend(["", "### Confirmation X Candle", ""])
        lines.extend(
            _markdown_table(
                candidate.get("promoted_by_confirmation_candle") or [],
                ["subgroup", "row_count", "label_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"],
            )
        )
        lines.extend(["", "### Provider Context", ""])
        lines.extend(
            _markdown_table(
                candidate.get("promoted_by_provider_context") or [],
                ["subgroup", "row_count", "label_count", "hit_rate_60m", "avg_signed_return_60m_bps", "mfe_mae_ratio_60m"],
            )
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This replay is research-only and does not change runtime score calculation.",
            "- Candidate rules use live-time fields only.",
            "- Recovered research blindspots use post-evaluation score only as an evaluation tag.",
            "- Any candidate needs fresh-forward validation before runtime wiring.",
            "",
        ]
    )
    return "\n".join(lines)


def write_runtime_score_supplement_replay_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_SCORE_SUPPLEMENT_REPLAY_REPORT_DIR,
    report_date: str | None = None,
    baseline_threshold: float = DEFAULT_BASELINE_THRESHOLD,
    research_high_threshold: float = DEFAULT_RESEARCH_HIGH_THRESHOLD,
    min_promoted_labels: int = DEFAULT_MIN_PROMOTED_LABELS,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = load_runtime_score_supplement_replay_dataset(dataset)
    report = build_runtime_score_supplement_replay_report(
        frame,
        report_date=report_date,
        baseline_threshold=baseline_threshold,
        research_high_threshold=research_high_threshold,
        min_promoted_labels=min_promoted_labels,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    json_path = output / f"runtime_score_supplement_replay_{timestamp}.json"
    markdown_path = output / f"runtime_score_supplement_replay_{timestamp}.md"
    latest_json_path = output / "latest_runtime_score_supplement_replay.json"
    latest_markdown_path = output / "latest_runtime_score_supplement_replay.md"
    summary_csv_path = output / f"runtime_score_supplement_replay_{timestamp}_summary.csv"
    latest_summary_csv_path = output / "latest_runtime_score_supplement_replay_summary.csv"

    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_runtime_score_supplement_replay_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")
    summary_rows = []
    for candidate in report.get("candidate_replay") or []:
        promoted = candidate.get("promoted_metrics") or {}
        summary_rows.append(
            {
                "candidate": candidate.get("candidate"),
                "assessment": candidate.get("assessment"),
                "condition_rows": candidate.get("condition_rows"),
                "promoted_rows": candidate.get("promoted_rows"),
                "recovered_research_blindspot_rows": candidate.get("recovered_research_blindspot_rows"),
                "helpful_promoted_rows": candidate.get("helpful_promoted_rows"),
                "harmful_promoted_rows": candidate.get("harmful_promoted_rows"),
                "unknown_promoted_rows": candidate.get("unknown_promoted_rows"),
                "promoted_hit_rate_60m": promoted.get("hit_rate_60m"),
                "promoted_avg_return_60m_bps": promoted.get("avg_signed_return_60m_bps"),
                "promoted_mfe_mae_ratio_60m": promoted.get("mfe_mae_ratio_60m"),
            }
        )
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(summary_csv_path, index=False)
    summary.to_csv(latest_summary_csv_path, index=False)
    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="runtime_score_supplement_replay",
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
        "summary_csv_path": str(summary_csv_path),
        "latest_summary_csv_path": str(latest_summary_csv_path),
        "manifest_path": str(manifest_path),
    }

"""Runtime-component outcome diagnostics.

This research-only report studies whether suppressed directional rows were
blocked for useful reasons. It does not change runtime scoring, thresholds,
parameter packs, data-source routing, or execution behavior.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from config.signal_evaluation_scoring import SIGNAL_EVALUATION_SELECTION_POLICY
from research.signal_evaluation.daily_suppression_attribution import attach_runtime_component_attribution
from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH
from research.signal_evaluation.signal_quality_model_audit import (
    _atomic_write_csv,
    _atomic_write_text,
    _round_or_none,
    _sanitize_value,
)
from utils.timestamp_helpers import coerce_timestamp_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_COMPONENT_OUTCOME_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_component_outcome"
)

LATEST_JSON_FILENAME = "latest_runtime_component_outcome.json"
LATEST_MARKDOWN_FILENAME = "latest_runtime_component_outcome.md"
LATEST_SEGMENTS_FILENAME = "latest_runtime_component_outcome_segments.csv"

COMPONENT_COLUMNS = (
    "trade_strength",
    "move_probability",
    "confirmation",
    "data_quality",
    "gamma_stability",
)

HORIZON_COLUMNS = (
    ("30m", "correct_30m", "signed_return_30m_bps"),
    ("60m", "correct_60m", "signed_return_60m_bps"),
    ("120m", "correct_120m", "signed_return_120m_bps"),
)


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _load_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset_path = Path(path)
    if not dataset_path.exists():
        return pd.DataFrame()
    return pd.read_csv(dataset_path, low_memory=False)


def _text_series(frame: pd.DataFrame, column: str, default: str = "UNKNOWN") -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="object")
    return (
        frame[column]
        .astype("object")
        .where(frame[column].notna(), default)
        .astype(str)
        .str.strip()
        .replace({"": default, "nan": default, "NaN": default, "None": default})
    )


def _num_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    raw = frame[column]
    if raw.dtype == bool:
        return raw.fillna(False)
    text = raw.astype("object").where(raw.notna(), "").astype(str).str.strip().str.lower()
    return text.isin({"true", "1", "yes", "y", "block", "blocked"})


def _filter_dates(frame: pd.DataFrame, *, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    if frame.empty or "signal_timestamp" not in frame.columns:
        return frame.iloc[0:0].copy()
    working = frame.copy()
    signal_ts = coerce_timestamp_series(working["signal_timestamp"], utc=True)
    working["_signal_ts"] = signal_ts
    working["_signal_date"] = signal_ts.dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
    mask = signal_ts.notna()
    if start_date:
        mask &= working["_signal_date"] >= str(start_date)
    if end_date:
        mask &= working["_signal_date"] <= str(end_date)
    return working.loc[mask.fillna(False)].copy()


def _directional_mask(frame: pd.DataFrame) -> pd.Series:
    return _text_series(frame, "direction", default="").str.upper().isin({"CALL", "PUT"})


def _safe_mean(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _mfe_mae_ratio(mfe: Any, mae: Any) -> float | None:
    mfe_value = _safe_mean(pd.Series(mfe))
    mae_value = _safe_mean(pd.Series(mae))
    if mfe_value is None or mae_value in (None, 0):
        return None
    return float(mfe_value) / abs(float(mae_value))


def _bucket(series: pd.Series, *, kind: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if kind == "residual":
        bins = [-float("inf"), -40, -25, -10, 0, float("inf")]
        labels = ["<=-40", "-40--25", "-25--10", "-10-0", ">=0"]
    elif kind == "score":
        bins = [-float("inf"), 35, 50, 60, 70, 80, float("inf")]
        labels = ["<35", "35-50", "50-60", "60-70", "70-80", "80+"]
    else:
        bins = [-float("inf"), 40, 60, 80, float("inf")]
        labels = ["<40", "40-60", "60-80", "80+"]
    return pd.cut(values, bins=bins, labels=labels, include_lowest=True).astype("object").where(values.notna(), "UNKNOWN")


def _probability_points(frame: pd.DataFrame) -> pd.Series:
    probability = _num_series(frame, "hybrid_move_probability").fillna(_num_series(frame, "move_probability"))
    valid = probability.dropna()
    if not valid.empty and float(valid.quantile(0.95)) <= 1.5:
        probability = probability * 100.0
    return probability.clip(0.0, 100.0)


def _metrics(group: pd.DataFrame) -> dict[str, Any]:
    row: dict[str, Any] = {
        "row_count": int(len(group)),
        "label_count_60m": int(_num_series(group, "correct_60m").notna().sum()),
        "avg_runtime_composite": _round_or_none(_safe_mean(_num_series(group, "runtime_composite_score")), 4),
        "avg_estimated_pre_adjust": _round_or_none(_safe_mean(_num_series(group, "estimated_pre_adjust_score")), 4),
        "avg_final_minus_estimated": _round_or_none(_safe_mean(_num_series(group, "estimated_composite_residual")), 4),
        "avg_trade_strength": _round_or_none(_safe_mean(_num_series(group, "trade_strength")), 4),
        "avg_probability": _round_or_none(_safe_mean(_num_series(group, "hybrid_move_probability")), 4),
        "avg_mfe_60m_bps": _round_or_none(_safe_mean(_num_series(group, "mfe_60m_bps")), 4),
        "avg_mae_60m_bps": _round_or_none(_safe_mean(_num_series(group, "mae_60m_bps")), 4),
        "mfe_mae_ratio_60m": _round_or_none(
            _mfe_mae_ratio(_num_series(group, "mfe_60m_bps"), _num_series(group, "mae_60m_bps")),
            4,
        ),
    }
    for label, hit_col, return_col in HORIZON_COLUMNS:
        hit = _num_series(group, hit_col)
        ret = _num_series(group, return_col)
        row[f"hit_rate_{label}"] = _round_or_none(_safe_mean(hit), 4)
        row[f"avg_signed_return_{label}_bps"] = _round_or_none(_safe_mean(ret), 4)
    return row


def _expost_winner_mask(frame: pd.DataFrame) -> pd.Series:
    hit = _num_series(frame, "correct_60m")
    ret = _num_series(frame, "signed_return_60m_bps")
    return hit.ge(1.0) & ret.gt(0.0)


def _clean_path_winner_mask(frame: pd.DataFrame) -> pd.Series:
    winner = _expost_winner_mask(frame)
    mfe = _num_series(frame, "mfe_60m_bps")
    mae = _num_series(frame, "mae_60m_bps").abs()
    return winner & mfe.gt(mae)


def _winner_metrics(group: pd.DataFrame) -> dict[str, Any]:
    hit = _num_series(group, "correct_60m")
    ret = _num_series(group, "signed_return_60m_bps")
    labeled = hit.notna() & ret.notna()
    winner = _expost_winner_mask(group)
    clean_winner = _clean_path_winner_mask(group)
    loser = labeled & ~winner
    return {
        "row_count": int(len(group)),
        "label_count_60m": int(labeled.sum()),
        "expost_winner_count_60m": int(winner.sum()),
        "expost_winner_rate_60m": _round_or_none(float(winner.sum()) / max(int(labeled.sum()), 1), 4),
        "clean_path_winner_count_60m": int(clean_winner.sum()),
        "clean_path_winner_rate_60m": _round_or_none(float(clean_winner.sum()) / max(int(labeled.sum()), 1), 4),
        "avg_winner_signed_return_60m_bps": _round_or_none(_safe_mean(ret.loc[winner]), 4),
        "avg_loser_signed_return_60m_bps": _round_or_none(_safe_mean(ret.loc[loser]), 4),
        "avg_winner_mfe_mae_ratio_60m": _round_or_none(
            _mfe_mae_ratio(_num_series(group.loc[winner], "mfe_60m_bps"), _num_series(group.loc[winner], "mae_60m_bps")),
            4,
        ),
    }


def _gap_bucket(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    bins = [-float("inf"), -25, -15, -5, 0, float("inf")]
    labels = ["<=-25", "-25--15", "-15--5", "-5-0", ">=0"]
    return pd.cut(values, bins=bins, labels=labels, include_lowest=True).astype("object").where(values.notna(), "UNKNOWN")


def _with_threshold_gap_columns(frame: pd.DataFrame, *, probability_floor: float) -> pd.DataFrame:
    working = frame.copy()
    probability_points = _probability_points(working)
    working["runtime_composite_gap_to_threshold"] = (
        _num_series(working, "runtime_composite_score") - _num_series(working, "effective_min_composite_score_threshold")
    )
    working["trade_strength_gap_to_threshold"] = (
        _num_series(working, "trade_strength") - _num_series(working, "effective_min_trade_strength_threshold")
    )
    working["move_probability_gap_to_floor_points"] = probability_points - float(probability_floor) * 100.0
    working["runtime_composite_gap_bucket"] = _gap_bucket(working["runtime_composite_gap_to_threshold"])
    working["trade_strength_gap_bucket"] = _gap_bucket(working["trade_strength_gap_to_threshold"])
    working["move_probability_gap_bucket"] = _gap_bucket(working["move_probability_gap_to_floor_points"])
    working["setup_activation_bucket"] = _bucket(_num_series(working, "setup_activation_score"), kind="score")
    working["setup_maturity_bucket"] = _bucket(_num_series(working, "setup_maturity_score"), kind="score")
    return working


def _segment_rows(frame: pd.DataFrame, segment_name: str, field: str, *, min_rows: int) -> list[dict[str, Any]]:
    if frame.empty or field not in frame.columns:
        return []
    rows: list[dict[str, Any]] = []
    values = _text_series(frame, field)
    for value, group in frame.groupby(values, dropna=False):
        if len(group) < min_rows:
            continue
        row = {
            "segment": segment_name,
            "value": str(value),
            **_metrics(group),
        }
        rows.append(row)
    return sorted(rows, key=lambda item: (-int(item.get("row_count") or 0), str(item.get("value"))))


def _winner_segment_rows(frame: pd.DataFrame, segment_name: str, field: str, *, min_rows: int) -> list[dict[str, Any]]:
    if frame.empty or field not in frame.columns:
        return []
    rows: list[dict[str, Any]] = []
    values = _text_series(frame, field)
    for value, group in frame.groupby(values, dropna=False):
        if len(group) < min_rows:
            continue
        row = {
            "segment": segment_name,
            "value": str(value),
            **_winner_metrics(group),
            "avg_runtime_composite_gap": _round_or_none(_safe_mean(_num_series(group, "runtime_composite_gap_to_threshold")), 4),
            "avg_trade_strength_gap": _round_or_none(_safe_mean(_num_series(group, "trade_strength_gap_to_threshold")), 4),
            "avg_move_probability_gap_points": _round_or_none(
                _safe_mean(_num_series(group, "move_probability_gap_to_floor_points")),
                4,
            ),
        }
        rows.append(row)
    return sorted(
        rows,
        key=lambda item: (
            -float(item.get("expost_winner_rate_60m") or 0.0),
            -int(item.get("label_count_60m") or 0),
            str(item.get("value")),
        ),
    )


def _signal_intensity_component_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    winner = _expost_winner_mask(frame)
    labeled = _num_series(frame, "correct_60m").notna() & _num_series(frame, "signed_return_60m_bps").notna()
    loser = labeled & ~winner
    primary = _text_series(frame, "primary_component_drag", default="UNKNOWN")
    for component in COMPONENT_COLUMNS:
        component_primary = primary.eq(component)
        component_score = _num_series(frame, f"{component}_score")
        component_deficit = _num_series(frame, f"{component}_weighted_deficit_to_100")
        group = frame.loc[component_primary].copy()
        winner_component_score = _safe_mean(component_score.loc[winner])
        loser_component_score = _safe_mean(component_score.loc[loser])
        rows.append(
            {
                "component": component,
                "primary_drag_rows": int(component_primary.sum()),
                "primary_drag_share": _round_or_none(float(component_primary.sum()) / max(int(len(frame)), 1), 4),
                **_winner_metrics(group),
                "avg_component_score": _round_or_none(_safe_mean(component_score), 4),
                "avg_winner_component_score": _round_or_none(winner_component_score, 4),
                "avg_loser_component_score": _round_or_none(loser_component_score, 4),
                "winner_minus_loser_component_score": _round_or_none(
                    (winner_component_score or 0.0) - (loser_component_score or 0.0),
                    4,
                )
                if winner_component_score is not None and loser_component_score is not None
                else None,
                "avg_weighted_deficit_to_100": _round_or_none(_safe_mean(component_deficit), 4),
                "avg_winner_weighted_deficit_to_100": _round_or_none(_safe_mean(component_deficit.loc[winner]), 4),
                "avg_loser_weighted_deficit_to_100": _round_or_none(_safe_mean(component_deficit.loc[loser]), 4),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            -int(item.get("expost_winner_count_60m") or 0),
            -int(item.get("primary_drag_rows") or 0),
            str(item.get("component")),
        ),
    )


def _capture_status(frame: pd.DataFrame) -> dict[str, Any]:
    total = max(int(len(frame)), 1)
    activation = _num_series(frame, "setup_activation_score")
    maturity = _num_series(frame, "setup_maturity_score")
    runtime_components = _text_series(frame, "runtime_component_source", default="UNKNOWN")
    return {
        "setup_activation_score_rows": int(activation.notna().sum()),
        "setup_activation_score_coverage": _round_or_none(float(activation.notna().sum()) / total, 4),
        "setup_maturity_score_rows": int(maturity.notna().sum()),
        "setup_maturity_score_coverage": _round_or_none(float(maturity.notna().sum()) / total, 4),
        "exact_runtime_component_rows": int(runtime_components.str.lower().eq("captured_json").sum()),
        "component_source_counts": [
            {"source": str(key), "count": int(value)}
            for key, value in runtime_components.value_counts(dropna=False).items()
        ],
        "note": (
            "setup_activation_score and setup_maturity_score were added to signal capture for future rows; "
            "older rows may have zero coverage."
        ),
    }


def _prepare_frame(frame: pd.DataFrame, *, probability_floor: float) -> tuple[pd.DataFrame, str]:
    if frame.empty:
        return frame.copy(), "none"
    working = frame.loc[_directional_mask(frame)].copy()
    trade_status = _text_series(working, "trade_status", default="UNKNOWN").str.upper()
    working = working.loc[trade_status != "TRADE"].copy()
    working, source = attach_runtime_component_attribution(working, probability_floor=probability_floor)
    if working.empty:
        return working, source
    working["estimated_pre_adjust_bucket"] = _bucket(working.get("estimated_pre_adjust_score"), kind="score")
    working["runtime_composite_bucket"] = _bucket(working.get("runtime_composite_score"), kind="score")
    working["compression_bucket"] = _bucket(working.get("estimated_composite_residual"), kind="residual")
    working["trade_strength_bucket"] = _bucket(working.get("trade_strength"), kind="score")
    working["probability_bucket"] = _bucket(_probability_points(working), kind="probability")
    working = _with_threshold_gap_columns(working, probability_floor=probability_floor)
    working["risk_flip_context"] = (
        _text_series(working, "macro_regime", default="UNKNOWN")
        + "/"
        + _text_series(working, "global_risk_state", default="UNKNOWN")
        + "/"
        + _text_series(working, "spot_vs_flip", default="UNKNOWN")
    )
    return working, source


def _observed_runtime_mask(frame: pd.DataFrame) -> pd.Series:
    return _num_series(frame, "runtime_composite_score").notna()


def _overall_read(report: dict[str, Any]) -> str:
    overall = report.get("overall_metrics") or {}
    hit = overall.get("hit_rate_60m")
    ret = overall.get("avg_signed_return_60m_bps")
    residual = (report.get("overall_metrics") or {}).get("avg_final_minus_estimated")
    if hit is not None and float(hit) >= 0.58 and ret is not None and float(ret) <= 0:
        return "DIRECTIONALLY_USEFUL_BUT_PATH_WEAK"
    if residual is not None and float(residual) <= -15:
        return "POST_COMPONENT_COMPRESSION_DOMINANT"
    return "MIXED_RESEARCH_ONLY"


def build_runtime_component_outcome_report(
    frame: pd.DataFrame,
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
    probability_floor: float | None = None,
    min_segment_rows: int = 30,
    require_runtime_composite: bool = True,
) -> dict[str, Any]:
    """Build a research-only multi-session runtime-component outcome report."""
    probability_floor = (
        float(probability_floor)
        if probability_floor is not None
        else float(SIGNAL_EVALUATION_SELECTION_POLICY.get("move_probability_floor", 0.60))
    )
    dated = _filter_dates(frame if frame is not None else pd.DataFrame(), start_date=start_date, end_date=end_date)
    prepared, component_source = _prepare_frame(dated, probability_floor=probability_floor)
    if require_runtime_composite and not prepared.empty:
        prepared = prepared.loc[_observed_runtime_mask(prepared)].copy()
    segments: list[dict[str, Any]] = []
    for segment_name, field in (
        ("signal_date", "_signal_date"),
        ("primary_component_drag", "primary_component_drag"),
        ("estimated_pre_adjust_bucket", "estimated_pre_adjust_bucket"),
        ("runtime_composite_bucket", "runtime_composite_bucket"),
        ("compression_bucket", "compression_bucket"),
        ("trade_strength_bucket", "trade_strength_bucket"),
        ("probability_bucket", "probability_bucket"),
        ("runtime_composite_gap_bucket", "runtime_composite_gap_bucket"),
        ("trade_strength_gap_bucket", "trade_strength_gap_bucket"),
        ("move_probability_gap_bucket", "move_probability_gap_bucket"),
        ("setup_activation_bucket", "setup_activation_bucket"),
        ("setup_maturity_bucket", "setup_maturity_bucket"),
        ("risk_flip_context", "risk_flip_context"),
        ("gamma_regime", "gamma_regime"),
        ("volatility_regime", "volatility_regime"),
        ("ta_entry_timing_state", "ta_entry_timing_state"),
    ):
        segments.extend(_segment_rows(prepared, segment_name, field, min_rows=min_segment_rows))

    overall = _metrics(prepared) if not prepared.empty else {}
    winner_segments: list[dict[str, Any]] = []
    for segment_name, field in (
        ("primary_component_drag", "primary_component_drag"),
        ("runtime_composite_gap_bucket", "runtime_composite_gap_bucket"),
        ("trade_strength_gap_bucket", "trade_strength_gap_bucket"),
        ("move_probability_gap_bucket", "move_probability_gap_bucket"),
        ("estimated_pre_adjust_bucket", "estimated_pre_adjust_bucket"),
        ("runtime_composite_bucket", "runtime_composite_bucket"),
        ("compression_bucket", "compression_bucket"),
        ("setup_activation_bucket", "setup_activation_bucket"),
        ("setup_maturity_bucket", "setup_maturity_bucket"),
        ("risk_flip_context", "risk_flip_context"),
        ("ta_entry_timing_state", "ta_entry_timing_state"),
    ):
        winner_segments.extend(_winner_segment_rows(prepared, segment_name, field, min_rows=min_segment_rows))

    report = {
        "report_type": "runtime_component_outcome",
        "generated_at": _now_utc(),
        "research_only": True,
        "runtime_config_changed": False,
        "parameter_pack_file_changed": False,
        "execution_behavior_changed": False,
        "dataset_path": str(dataset_path),
        "start_date": start_date,
        "end_date": end_date,
        "probability_floor": probability_floor,
        "min_segment_rows": int(min_segment_rows),
        "require_runtime_composite": bool(require_runtime_composite),
        "input_rows": int(len(dated)),
        "suppressed_directional_rows": int(len(prepared)),
        "component_source": component_source,
        "subcomponent_capture_status": _capture_status(prepared),
        "overall_metrics": overall,
        "expost_winner_summary_60m": _winner_metrics(prepared) if not prepared.empty else {},
        "component_summary": [
            {
                "component": component,
                "avg_score": _round_or_none(_safe_mean(_num_series(prepared, f"{component}_score")), 4),
                "avg_weighted_contribution": _round_or_none(
                    _safe_mean(_num_series(prepared, f"{component}_weighted_contribution")), 4
                ),
                "avg_weighted_deficit_to_100": _round_or_none(
                    _safe_mean(_num_series(prepared, f"{component}_weighted_deficit_to_100")), 4
                ),
            }
            for component in COMPONENT_COLUMNS
        ],
        "signal_intensity_component_decomposition": _signal_intensity_component_rows(prepared),
        "segments": segments,
        "expost_winner_segments": winner_segments,
        "recommended_next_actions": [],
    }
    report["overall_read"] = _overall_read(report)
    if report["overall_read"] == "DIRECTIONALLY_USEFUL_BUT_PATH_WEAK":
        report["recommended_next_actions"].append(
            "Do not relax the gate broadly; prioritize entry/exit timing and path-quality filters for this suppressed cohort."
        )
    if component_source != "captured_json":
        report["recommended_next_actions"].append(
            "Treat component rows as reconstructed until forward rows with exact runtime_composite_components mature."
        )
    report["recommended_next_actions"].append(
        "Promote only if multi-session component-gate redesign improves signed bps and MFE/MAE, not just hit rate."
    )
    return _sanitize_value(report)


def _markdown_table(rows: list[dict[str, Any]], columns: tuple[str, ...], *, limit: int | None = None) -> list[str]:
    selected = rows[:limit] if limit is not None else rows
    if not selected:
        return ["No rows available."]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in selected:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def render_runtime_component_outcome_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Runtime Component Outcome",
        "",
        "> Author: Pramit Dutta | Organization: Quant Engines",
        "",
        f"- Generated at: {report.get('generated_at')}",
        f"- Date range: `{report.get('start_date')}` to `{report.get('end_date')}`",
        f"- Research only: `{report.get('research_only')}`",
        f"- Runtime config changed: `{report.get('runtime_config_changed')}`",
        f"- Component source: `{report.get('component_source')}`",
        f"- Require runtime composite: `{report.get('require_runtime_composite')}`",
        f"- Overall read: `{report.get('overall_read')}`",
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
        "avg_mfe_60m_bps",
        "avg_mae_60m_bps",
        "mfe_mae_ratio_60m",
    ):
        lines.append(f"- {key}: `{overall.get(key)}`")
    lines.extend(["", "## Component Summary", ""])
    lines.extend(
        _markdown_table(
            report.get("component_summary", []),
            ("component", "avg_score", "avg_weighted_contribution", "avg_weighted_deficit_to_100"),
        )
    )
    capture = report.get("subcomponent_capture_status") or {}
    lines.extend(["", "## Subcomponent Capture Status", ""])
    for key in (
        "setup_activation_score_rows",
        "setup_activation_score_coverage",
        "setup_maturity_score_rows",
        "setup_maturity_score_coverage",
        "exact_runtime_component_rows",
    ):
        lines.append(f"- {key}: `{capture.get(key)}`")
    if capture.get("note"):
        lines.append(f"- note: {capture.get('note')}")
    lines.extend(["", "## Ex-Post Winner Summary", ""])
    winners = report.get("expost_winner_summary_60m") or {}
    for key in (
        "label_count_60m",
        "expost_winner_count_60m",
        "expost_winner_rate_60m",
        "clean_path_winner_count_60m",
        "clean_path_winner_rate_60m",
        "avg_winner_signed_return_60m_bps",
        "avg_loser_signed_return_60m_bps",
        "avg_winner_mfe_mae_ratio_60m",
    ):
        lines.append(f"- {key}: `{winners.get(key)}`")
    lines.extend(["", "## Signal-Intensity Component Decomposition", ""])
    lines.extend(
        _markdown_table(
            report.get("signal_intensity_component_decomposition", []),
            (
                "component",
                "primary_drag_rows",
                "expost_winner_count_60m",
                "expost_winner_rate_60m",
                "clean_path_winner_rate_60m",
                "avg_winner_component_score",
                "avg_loser_component_score",
                "avg_winner_weighted_deficit_to_100",
            ),
        )
    )
    lines.extend(["", "## Ex-Post Winner Segments", ""])
    lines.extend(
        _markdown_table(
            report.get("expost_winner_segments", []),
            (
                "segment",
                "value",
                "row_count",
                "label_count_60m",
                "expost_winner_rate_60m",
                "clean_path_winner_rate_60m",
                "avg_winner_signed_return_60m_bps",
                "avg_runtime_composite_gap",
                "avg_trade_strength_gap",
                "avg_move_probability_gap_points",
            ),
            limit=50,
        )
    )
    lines.extend(["", "## Segments", ""])
    lines.extend(
        _markdown_table(
            report.get("segments", []),
            (
                "segment",
                "value",
                "row_count",
                "hit_rate_60m",
                "avg_signed_return_60m_bps",
                "mfe_mae_ratio_60m",
                "avg_final_minus_estimated",
            ),
            limit=40,
        )
    )
    lines.extend(["", "## Recommended Next Actions", ""])
    for action in report.get("recommended_next_actions", []) or []:
        lines.append(f"- {action}")
    lines.extend(["", "*Research-only diagnostic. It does not alter live signal behavior.*", ""])
    return "\n".join(lines)


def write_runtime_component_outcome_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_COMPONENT_OUTCOME_DIR,
    start_date: str | None = None,
    end_date: str | None = None,
    probability_floor: float | None = None,
    min_segment_rows: int = 30,
    require_runtime_composite: bool = True,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = _load_dataset(dataset)
    report = build_runtime_component_outcome_report(
        frame,
        dataset_path=dataset,
        start_date=start_date,
        end_date=end_date,
        probability_floor=probability_floor,
        min_segment_rows=min_segment_rows,
        require_runtime_composite=require_runtime_composite,
    )
    date_part = f"{start_date or 'all'}_{end_date or 'latest'}".replace("-", "")
    stem = f"runtime_component_outcome_{date_part}"
    json_path = output / f"{stem}.json"
    markdown_path = output / f"{stem}.md"
    segments_path = output / f"{stem}_segments.csv"
    latest_json_path = output / LATEST_JSON_FILENAME
    latest_markdown_path = output / LATEST_MARKDOWN_FILENAME
    latest_segments_path = output / LATEST_SEGMENTS_FILENAME

    markdown = render_runtime_component_outcome_markdown(report)
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

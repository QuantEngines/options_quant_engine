"""Compare live-time runtime score with post-evaluation research score.

This report is deliberately diagnostic-only.  The research composite contains
realized outcome information, so it must never be used directly as a live
decision score.  Its useful role here is to reveal what the live-time runtime
score failed to see before the outcome matured.
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
DEFAULT_RUNTIME_RESEARCH_COMPOSITE_GAP_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_research_composite_gap"
)

DEFAULT_RESEARCH_HIGH_THRESHOLD = 80.0
DEFAULT_RUNTIME_LOW_THRESHOLD = 60.0
DEFAULT_RUNTIME_HIGH_THRESHOLD = 60.0
DEFAULT_RESEARCH_LOW_THRESHOLD = 50.0

SCORE_COMPONENTS = (
    "direction_score",
    "magnitude_score",
    "timing_score",
    "tradeability_score",
)

NUMERIC_COLUMNS = (
    "runtime_composite_score",
    "composite_signal_score",
    "trade_strength",
    "move_probability",
    "hybrid_move_probability",
    "rule_move_probability",
    "ml_move_probability",
    "signal_confidence_score",
    "target_reachability_score",
    "premium_efficiency_score",
    "strike_efficiency_score",
    "option_efficiency_score",
    "global_risk_score",
    "selected_option_ba_spread_pct",
    "support_wall_distance_pct",
    "resistance_wall_distance_pct",
    "max_pain_distance_pct",
    "gamma_flip_distance_pct",
    "historical_context_score_adjustment",
    "historical_context_probability_adjustment",
    "historical_interaction_score_adjustment",
    "historical_interaction_probability_adjustment",
    "statistical_context_score_adjustment",
    "statistical_context_probability_adjustment",
    "statistical_macro_score_adjustment",
    "statistical_macro_probability_adjustment",
    "ta_confidence",
    "ta_entry_timing_score",
    "ta_candle_confidence",
    "signed_return_15m_bps",
    "signed_return_30m_bps",
    "signed_return_60m_bps",
    "signed_return_120m_bps",
    "mfe_60m_bps",
    "mae_60m_bps",
    "mfe_120m_bps",
    "mae_120m_bps",
    "option_premium_return_60m_bps",
    "correct_60m",
    *SCORE_COMPONENTS,
)

TEXT_COLUMNS = (
    "signal_timestamp",
    "direction",
    "trade_status",
    "outcome_status",
    "label_quality_status",
    "confirmation_status",
    "provider_health_status",
    "provider_quality_mode",
    "provider_analytics_status",
    "provider_execution_status",
    "provider_direction_trust",
    "provider_execution_trust",
    "provider_quality_action",
    "data_quality_status",
    "analytics_usable",
    "execution_suggestion_usable",
    "gamma_regime",
    "volatility_regime",
    "global_risk_state",
    "macro_regime",
    "ta_direction",
    "ta_regime",
    "ta_candle_status",
    "ta_candle_direction",
    "ta_candle_state",
    "ta_entry_timing_state",
    "runtime_composite_observation_tier",
    "spot_vs_flip",
    "historical_wall_state",
    "historical_max_pain_state",
    "historical_pcr_state",
    "max_pain_zone",
)

USE_COLUMNS = tuple(dict.fromkeys((*TEXT_COLUMNS, *NUMERIC_COLUMNS)))


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
    if series.empty:
        return pd.Series(dtype=bool)
    text = series.fillna(False).astype(str).str.strip().str.upper()
    return text.isin({"1", "1.0", "TRUE", "YES", "Y", "ON"})


def _mean(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.mean())


def _pct_mean(series: pd.Series) -> float | None:
    value = _mean(series)
    return value * 100.0 if value is not None else None


def _share(mask: pd.Series) -> float | None:
    if mask.empty:
        return None
    return float(mask.fillna(False).mean() * 100.0)


def _mfe_mae_ratio(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    mfe = pd.to_numeric(frame.get("mfe_60m_bps", pd.Series(dtype=float)), errors="coerce")
    mae = pd.to_numeric(frame.get("mae_60m_bps", pd.Series(dtype=float)), errors="coerce").abs()
    avg_mae = _mean(mae)
    avg_mfe = _mean(mfe)
    if avg_mfe is None or avg_mae is None or avg_mae <= 0:
        return None
    return avg_mfe / avg_mae


def _runtime_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(
        pd.to_numeric(series, errors="coerce"),
        bins=[-np.inf, 49.999, 54.999, 59.999, 64.999, 69.999, np.inf],
        labels=["<50", "50-54", "55-59", "60-64", "65-69", "70+"],
    )


def _research_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(
        pd.to_numeric(series, errors="coerce"),
        bins=[-np.inf, 49.999, 64.999, 74.999, 79.999, np.inf],
        labels=["<50", "50-64", "65-74", "75-79", "80+"],
    )


def _nearest_wall_distance_pct(frame: pd.DataFrame) -> pd.Series:
    distances = []
    for column in ("support_wall_distance_pct", "resistance_wall_distance_pct"):
        if column in frame.columns:
            distances.append(pd.to_numeric(frame[column], errors="coerce").abs())
    if not distances:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.concat(distances, axis=1).min(axis=1, skipna=True)


def _level_distance_bucket(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    buckets = pd.Series("UNKNOWN", index=series.index, dtype=object)
    buckets.loc[numeric.notna() & (numeric <= 0.10)] = "AT_WALL"
    buckets.loc[numeric.notna() & (numeric > 0.10) & (numeric <= 0.30)] = "NEAR_WALL"
    buckets.loc[numeric.notna() & (numeric > 0.30)] = "AWAY_FROM_WALL"
    return buckets


def load_runtime_research_composite_gap_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Signal dataset not found: {dataset_path}")
    return pd.read_csv(
        dataset_path,
        usecols=lambda column: column in USE_COLUMNS,
        low_memory=False,
    )


def prepare_runtime_research_composite_frame(frame: pd.DataFrame, *, report_date: str | None = None) -> pd.DataFrame:
    working = frame.copy()
    if "signal_timestamp" not in working.columns:
        working["signal_timestamp"] = pd.NA
    working["signal_ts"] = coerce_timestamp_series(working["signal_timestamp"], utc=True)
    working["signal_date"] = working["signal_ts"].dt.tz_convert("Asia/Kolkata").dt.date.astype(str)
    for column in NUMERIC_COLUMNS:
        if column not in working.columns:
            working[column] = pd.NA
        working[column] = pd.to_numeric(working[column], errors="coerce")
    for column in TEXT_COLUMNS:
        if column not in working.columns:
            working[column] = pd.NA
        if column not in {"signal_timestamp"}:
            working[column] = _normalize_text(working[column])
    if report_date:
        working = working.loc[working["signal_date"] == str(report_date)].copy()

    working["runtime_bucket"] = _runtime_bucket(working["runtime_composite_score"])
    working["research_bucket"] = _research_bucket(working["composite_signal_score"])
    working["nearest_wall_distance_pct"] = _nearest_wall_distance_pct(working)
    working["nearest_wall_bucket"] = _level_distance_bucket(working["nearest_wall_distance_pct"])
    wall_state = _normalize_text(working.get("historical_wall_state", pd.Series(index=working.index, dtype=object)))
    working["wall_context_state"] = wall_state.where(~wall_state.isin({"UNKNOWN"}), working["nearest_wall_bucket"])
    working["score_gap_research_minus_runtime"] = working["composite_signal_score"] - working["runtime_composite_score"]
    working["has_direction"] = working["direction"].isin(["CALL", "PUT"])
    working["has_comparable_scores"] = (
        working["has_direction"]
        & working["runtime_composite_score"].notna()
        & working["composite_signal_score"].notna()
    )
    return working


def _summary_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "row_count": 0,
            "avg_runtime_composite_score": None,
            "avg_research_composite_score": None,
            "avg_score_gap": None,
        }
    provider = frame.get("provider_health_status", pd.Series(dtype=object)).astype(str).str.upper()
    data_quality = frame.get("data_quality_status", pd.Series(dtype=object)).astype(str).str.upper()
    confirmation = frame.get("confirmation_status", pd.Series(dtype=object)).astype(str).str.upper()
    outcome = frame.get("outcome_status", pd.Series(dtype=object)).astype(str).str.upper()
    label_quality = frame.get("label_quality_status", pd.Series(dtype=object)).astype(str).str.upper()
    ta_entry = frame.get("ta_entry_timing_state", pd.Series(dtype=object)).astype(str).str.upper()
    ta_candle = frame.get("ta_candle_state", pd.Series(dtype=object)).astype(str).str.upper()
    analytics_usable = _truthy_series(frame.get("analytics_usable", pd.Series(dtype=object)))
    execution_usable = _truthy_series(frame.get("execution_suggestion_usable", pd.Series(dtype=object)))
    return {
        "row_count": int(len(frame)),
        "avg_runtime_composite_score": _round(_mean(frame["runtime_composite_score"])),
        "avg_research_composite_score": _round(_mean(frame["composite_signal_score"])),
        "avg_score_gap": _round(_mean(frame["score_gap_research_minus_runtime"])),
        "avg_trade_strength": _round(_mean(frame.get("trade_strength", pd.Series(dtype=float)))),
        "avg_move_probability": _round(_mean(frame.get("move_probability", pd.Series(dtype=float)))),
        "avg_hybrid_move_probability": _round(_mean(frame.get("hybrid_move_probability", pd.Series(dtype=float)))),
        "avg_option_efficiency_score": _round(_mean(frame.get("option_efficiency_score", pd.Series(dtype=float)))),
        "avg_signal_confidence_score": _round(_mean(frame.get("signal_confidence_score", pd.Series(dtype=float)))),
        "avg_signed_return_60m_bps": _round(_mean(frame.get("signed_return_60m_bps", pd.Series(dtype=float)))),
        "hit_rate_60m": _round(_pct_mean(frame.get("correct_60m", pd.Series(dtype=float)))),
        "avg_mfe_60m_bps": _round(_mean(frame.get("mfe_60m_bps", pd.Series(dtype=float)))),
        "avg_mae_60m_bps": _round(_mean(frame.get("mae_60m_bps", pd.Series(dtype=float)))),
        "mfe_mae_ratio_60m": _round(_mfe_mae_ratio(frame), 3),
        "avg_direction_score": _round(_mean(frame.get("direction_score", pd.Series(dtype=float)))),
        "avg_magnitude_score": _round(_mean(frame.get("magnitude_score", pd.Series(dtype=float)))),
        "avg_timing_score": _round(_mean(frame.get("timing_score", pd.Series(dtype=float)))),
        "avg_tradeability_score": _round(_mean(frame.get("tradeability_score", pd.Series(dtype=float)))),
        "outcome_complete_share": _round(_share(outcome.eq("COMPLETE"))),
        "outcome_partial_share": _round(_share(outcome.eq("PARTIAL"))),
        "label_clean_or_usable_share": _round(_share(label_quality.isin({"CLEAN", "USABLE_WITH_WARNINGS"}))),
        "label_partial_share": _round(_share(label_quality.eq("PARTIAL"))),
        "provider_weak_share": _round(_share(provider.eq("WEAK"))),
        "data_quality_caution_or_weak_share": _round(_share(data_quality.isin({"CAUTION", "WEAK"}))),
        "analytics_usable_share": _round(_share(analytics_usable)),
        "execution_usable_share": _round(_share(execution_usable)),
        "strong_confirmation_share": _round(_share(confirmation.isin({"CONFIRMED", "STRONG_CONFIRMATION"}))),
        "candle_confirmed_share": _round(_share(ta_entry.str.contains("CANDLE_CONFIRMED", na=False))),
        "candle_rejection_share": _round(_share(ta_candle.str.contains("REJECTION", na=False))),
    }


def _component_driver_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for component in SCORE_COMPONENTS:
        rows.append(
            {
                "component": component,
                "avg_score": _round(_mean(frame.get(component, pd.Series(dtype=float)))),
                "high_component_share": _round(_share(pd.to_numeric(frame.get(component, pd.Series(dtype=float)), errors="coerce") >= 75.0)),
                "missing_share": _round(_share(frame.get(component, pd.Series(dtype=float)).isna())),
            }
        )
    return rows


def _cohort_report(name: str, frame: pd.DataFrame, baseline: pd.DataFrame) -> dict[str, Any]:
    metrics = _summary_metrics(frame)
    baseline_metrics = _summary_metrics(baseline)
    deltas = {}
    for key, value in metrics.items():
        if key == "row_count":
            continue
        base = baseline_metrics.get(key)
        if value is None or base is None:
            deltas[key] = None
        else:
            deltas[key] = _round(float(value) - float(base))
    return {
        "cohort": name,
        "metrics": metrics,
        "delta_vs_comparable": deltas,
        "research_component_drivers": _component_driver_rows(frame),
        "top_provider_health": _top_counts(frame, "provider_health_status"),
        "top_data_quality": _top_counts(frame, "data_quality_status"),
        "top_confirmation": _top_counts(frame, "confirmation_status"),
        "top_trade_status": _top_counts(frame, "trade_status"),
        "top_regime": _top_counts(frame, "gamma_regime"),
        "top_volatility_regime": _top_counts(frame, "volatility_regime"),
        "top_global_risk": _top_counts(frame, "global_risk_state"),
        "top_ta_entry_state": _top_counts(frame, "ta_entry_timing_state"),
    }


def _top_counts(frame: pd.DataFrame, column: str, *, top_n: int = 5) -> list[dict[str, Any]]:
    if frame.empty or column not in frame.columns:
        return []
    counts = frame[column].fillna("UNKNOWN").astype(str).value_counts(dropna=False).head(top_n)
    total = max(int(len(frame)), 1)
    return [
        {"value": str(index), "count": int(count), "share": _round(float(count) / total * 100.0)}
        for index, count in counts.items()
    ]


def _score_matrix(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    grouped = (
        frame.groupby(["runtime_bucket", "research_bucket"], dropna=False, observed=True)
        .agg(
            row_count=("runtime_composite_score", "size"),
            avg_runtime_composite_score=("runtime_composite_score", "mean"),
            avg_research_composite_score=("composite_signal_score", "mean"),
            avg_signed_return_60m_bps=("signed_return_60m_bps", "mean"),
            hit_rate_60m=("correct_60m", "mean"),
        )
        .reset_index()
    )
    rows: list[dict[str, Any]] = []
    for item in grouped.to_dict("records"):
        hit_rate = _safe_float(item.get("hit_rate_60m"), None)
        rows.append(
            {
                "runtime_bucket": str(item.get("runtime_bucket")),
                "research_bucket": str(item.get("research_bucket")),
                "row_count": int(item.get("row_count") or 0),
                "avg_runtime_composite_score": _round(item.get("avg_runtime_composite_score")),
                "avg_research_composite_score": _round(item.get("avg_research_composite_score")),
                "avg_signed_return_60m_bps": _round(item.get("avg_signed_return_60m_bps")),
                "hit_rate_60m": _round(hit_rate * 100.0) if hit_rate is not None else None,
            }
        )
    return rows


def _feature_gap_rows(blindspot: pd.DataFrame, baseline: pd.DataFrame) -> list[dict[str, Any]]:
    specs = (
        ("trade_strength", "avg_trade_strength", "runtime strength"),
        ("move_probability", "avg_move_probability", "move probability"),
        ("hybrid_move_probability", "avg_hybrid_move_probability", "hybrid probability"),
        ("option_efficiency_score", "avg_option_efficiency_score", "option efficiency"),
        ("signal_confidence_score", "avg_signal_confidence_score", "signal confidence"),
        ("provider_weak_share", "provider_weak_share", "provider weakness"),
        ("execution_usable_share", "execution_usable_share", "execution usability"),
        ("strong_confirmation_share", "strong_confirmation_share", "confirmation"),
        ("candle_confirmed_share", "candle_confirmed_share", "candle confirmation"),
        ("candle_rejection_share", "candle_rejection_share", "candle rejection"),
    )
    blind_metrics = _summary_metrics(blindspot)
    base_metrics = _summary_metrics(baseline)
    rows = []
    for _field, metric_key, label in specs:
        blind = blind_metrics.get(metric_key)
        base = base_metrics.get(metric_key)
        delta = None if blind is None or base is None else _round(float(blind) - float(base))
        rows.append(
            {
                "feature_group": label,
                "blindspot_value": blind,
                "comparable_value": base,
                "delta": delta,
                "interpretation": _interpret_feature_gap(metric_key, delta),
            }
        )
    return rows


SUBGROUP_METRIC_KEYS = (
    "avg_runtime_composite_score",
    "avg_research_composite_score",
    "avg_score_gap",
    "avg_trade_strength",
    "avg_move_probability",
    "avg_signed_return_60m_bps",
    "hit_rate_60m",
    "mfe_mae_ratio_60m",
    "outcome_complete_share",
    "provider_weak_share",
    "execution_usable_share",
    "strong_confirmation_share",
    "candle_confirmed_share",
)


def _format_group_value(value: Any) -> str:
    try:
        if pd.isna(value):
            return "UNKNOWN"
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text in {"", "nan", "NaN", "None"}:
        return "UNKNOWN"
    return text


def _subgroup_rows(
    frame: pd.DataFrame,
    group_columns: list[str],
    *,
    min_rows: int = 1,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    available_columns = [column for column in group_columns if column in frame.columns]
    if frame.empty or not available_columns:
        return []
    working = frame.copy()
    for column in available_columns:
        working[column] = _normalize_text(working[column])
    total = max(int(len(working)), 1)
    rows: list[dict[str, Any]] = []
    for keys, group in working.groupby(available_columns, dropna=False, observed=True):
        if len(group) < min_rows:
            continue
        if not isinstance(keys, tuple):
            keys = (keys,)
        metrics = _summary_metrics(group)
        row = {
            column: _format_group_value(value)
            for column, value in zip(available_columns, keys, strict=False)
        }
        row["subgroup"] = " / ".join(row[column] for column in available_columns)
        row["row_count"] = int(len(group))
        row["share_of_blindspots"] = _round(float(len(group)) / total * 100.0)
        for metric in SUBGROUP_METRIC_KEYS:
            row[metric] = metrics.get(metric)
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            -int(row.get("row_count") or 0),
            -float(row.get("avg_score_gap") or 0.0),
            row.get("subgroup") or "",
        ),
    )[:top_n]


def _blindspot_subgroups(blindspot: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    return {
        "runtime_bucket": _subgroup_rows(blindspot, ["runtime_bucket"]),
        "gamma_regime": _subgroup_rows(blindspot, ["gamma_regime"]),
        "volatility_regime": _subgroup_rows(blindspot, ["volatility_regime"]),
        "global_risk_state": _subgroup_rows(blindspot, ["global_risk_state"]),
        "macro_regime": _subgroup_rows(blindspot, ["macro_regime"]),
        "confirmation_status": _subgroup_rows(blindspot, ["confirmation_status"]),
        "ta_entry_timing_state": _subgroup_rows(blindspot, ["ta_entry_timing_state"]),
        "ta_candle_state": _subgroup_rows(blindspot, ["ta_candle_state"]),
        "provider_data_quality": _subgroup_rows(blindspot, ["provider_health_status", "data_quality_status"]),
        "runtime_observation_tier": _subgroup_rows(blindspot, ["runtime_composite_observation_tier"]),
        "spot_vs_flip": _subgroup_rows(blindspot, ["spot_vs_flip"]),
        "wall_context_state": _subgroup_rows(blindspot, ["wall_context_state"]),
        "nearest_wall_bucket": _subgroup_rows(blindspot, ["nearest_wall_bucket"]),
        "max_pain_zone": _subgroup_rows(blindspot, ["max_pain_zone"]),
        "pcr_state": _subgroup_rows(blindspot, ["historical_pcr_state"]),
        "gamma_x_volatility": _subgroup_rows(blindspot, ["gamma_regime", "volatility_regime"]),
        "gamma_x_global_risk": _subgroup_rows(blindspot, ["gamma_regime", "global_risk_state"]),
        "confirmation_x_candle": _subgroup_rows(blindspot, ["confirmation_status", "ta_entry_timing_state"]),
        "provider_x_confirmation": _subgroup_rows(blindspot, ["provider_health_status", "confirmation_status"]),
    }


def _interpret_feature_gap(metric_key: str, delta: float | None) -> str:
    if delta is None:
        return "insufficient_data"
    if metric_key in {"provider_weak_share", "candle_rejection_share"} and delta > 10:
        return "blindspot_cluster_has_more_suppression_or_noise"
    if metric_key == "execution_usable_share" and delta < -10:
        return "analytics_may_be_usable_while_execution_is_blocked"
    if metric_key in {"avg_trade_strength", "avg_move_probability", "avg_hybrid_move_probability"} and delta < -5:
        return "live_runtime_understated_later_quality"
    if metric_key in {"strong_confirmation_share", "candle_confirmed_share"} and delta > 10:
        return "confirmation_signal_may_be_underweighted_or_too_late"
    if metric_key in {"avg_option_efficiency_score", "avg_signal_confidence_score"} and delta < -5:
        return "supporting_live_feature_was_weak_or_missing"
    return "no_large_gap"


def _top_subgroup_read(report: dict[str, Any], subgroup_key: str) -> str | None:
    rows = (report.get("blindspot_subgroups") or {}).get(subgroup_key) or []
    if not rows:
        return None
    top = rows[0]
    subgroup = top.get("subgroup")
    count = top.get("row_count")
    gap = top.get("avg_score_gap")
    share = top.get("share_of_blindspots")
    return f"{subgroup} ({count} rows, {share}% share, gap {gap})"


def _build_diagnostic_read(report: dict[str, Any]) -> dict[str, Any]:
    blindspot = ((report.get("cohorts") or {}).get("research_high_runtime_low") or {}).get("metrics") or {}
    false_conf = ((report.get("cohorts") or {}).get("runtime_high_research_low") or {}).get("metrics") or {}
    coverage = report.get("coverage") or {}
    return {
        "comparable_sample_is_small": bool((coverage.get("comparable_rows") or 0) < 100),
        "blindspot_rows": blindspot.get("row_count"),
        "false_confidence_rows": false_conf.get("row_count"),
        "blindspot_avg_score_gap": blindspot.get("avg_score_gap"),
        "blindspot_provider_weak_share": blindspot.get("provider_weak_share"),
        "blindspot_execution_usable_share": blindspot.get("execution_usable_share"),
        "blindspot_strong_confirmation_share": blindspot.get("strong_confirmation_share"),
        "blindspot_candle_confirmed_share": blindspot.get("candle_confirmed_share"),
        "largest_blindspot_runtime_bucket": _top_subgroup_read(report, "runtime_bucket"),
        "largest_blindspot_regime_bucket": _top_subgroup_read(report, "gamma_x_volatility"),
        "largest_blindspot_provider_confirmation_bucket": _top_subgroup_read(report, "provider_x_confirmation"),
        "largest_blindspot_wall_bucket": _top_subgroup_read(report, "wall_context_state"),
        "primary_read": _primary_read(blindspot),
    }


def _primary_read(blindspot_metrics: dict[str, Any]) -> str:
    if not blindspot_metrics or not blindspot_metrics.get("row_count"):
        return "no_runtime_blindspot_rows_at_configured_thresholds"
    notes = []
    if _safe_float(blindspot_metrics.get("provider_weak_share"), 0.0) >= 70:
        notes.append("provider_quality_suppressed_execution_context")
    if _safe_float(blindspot_metrics.get("strong_confirmation_share"), 0.0) >= 60:
        notes.append("confirmation_present_despite_low_runtime_score")
    if _safe_float(blindspot_metrics.get("avg_move_probability"), 1.0) < 0.55:
        notes.append("live_probability_understated_realized_quality")
    if _safe_float(blindspot_metrics.get("avg_trade_strength"), 100.0) < 60:
        notes.append("trade_strength_understated_realized_quality")
    if not notes:
        notes.append("blindspot_exists_but_no_single_live_feature_dominates")
    return ", ".join(notes)


def build_runtime_research_composite_gap_report(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    research_high_threshold: float = DEFAULT_RESEARCH_HIGH_THRESHOLD,
    runtime_low_threshold: float = DEFAULT_RUNTIME_LOW_THRESHOLD,
    runtime_high_threshold: float = DEFAULT_RUNTIME_HIGH_THRESHOLD,
    research_low_threshold: float = DEFAULT_RESEARCH_LOW_THRESHOLD,
) -> dict[str, Any]:
    prepared = prepare_runtime_research_composite_frame(frame, report_date=report_date)
    directional = prepared.loc[prepared["has_direction"]].copy()
    comparable = prepared.loc[prepared["has_comparable_scores"]].copy()
    blindspot = comparable.loc[
        (comparable["composite_signal_score"] >= float(research_high_threshold))
        & (comparable["runtime_composite_score"] < float(runtime_low_threshold))
    ].copy()
    near_miss = comparable.loc[
        (comparable["composite_signal_score"] >= 75.0)
        & (comparable["runtime_composite_score"] < float(runtime_low_threshold))
    ].copy()
    false_confidence = comparable.loc[
        (comparable["runtime_composite_score"] >= float(runtime_high_threshold))
        & (comparable["composite_signal_score"] < float(research_low_threshold))
    ].copy()
    aligned_high = comparable.loc[
        (comparable["composite_signal_score"] >= float(research_high_threshold))
        & (comparable["runtime_composite_score"] >= float(runtime_low_threshold))
    ].copy()
    corr = None
    if len(comparable) >= 2:
        corr = comparable[["runtime_composite_score", "composite_signal_score"]].corr(method="spearman").iloc[0, 1]

    report = {
        "report_type": "runtime_research_composite_gap",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "report_date": report_date,
            "runtime_score_field": "runtime_composite_score",
            "research_score_field": "composite_signal_score",
            "research_score_warning": (
                "composite_signal_score is computed after realized outcomes and is used here only "
                "to diagnose missing live-time features"
            ),
            "research_high_threshold": float(research_high_threshold),
            "runtime_low_threshold": float(runtime_low_threshold),
            "runtime_high_threshold": float(runtime_high_threshold),
            "research_low_threshold": float(research_low_threshold),
        },
        "coverage": {
            "input_rows": int(len(frame)),
            "rows_after_date_filter": int(len(prepared)),
            "directional_rows": int(len(directional)),
            "runtime_score_rows": int(prepared["runtime_composite_score"].notna().sum()),
            "research_score_rows": int(prepared["composite_signal_score"].notna().sum()),
            "comparable_rows": int(len(comparable)),
            "trading_days": int(prepared["signal_ts"].dropna().dt.normalize().nunique()) if not prepared.empty else 0,
            "start_timestamp": prepared["signal_ts"].dropna().min().isoformat() if prepared["signal_ts"].notna().any() else None,
            "end_timestamp": prepared["signal_ts"].dropna().max().isoformat() if prepared["signal_ts"].notna().any() else None,
        },
        "score_alignment": {
            "spearman_correlation": _round(corr, 4),
            "avg_runtime_composite_score": _round(_mean(comparable.get("runtime_composite_score", pd.Series(dtype=float)))),
            "avg_research_composite_score": _round(_mean(comparable.get("composite_signal_score", pd.Series(dtype=float)))),
            "avg_score_gap": _round(_mean(comparable.get("score_gap_research_minus_runtime", pd.Series(dtype=float)))),
            "runtime_max": _round(comparable["runtime_composite_score"].max()) if not comparable.empty else None,
            "research_max": _round(comparable["composite_signal_score"].max()) if not comparable.empty else None,
        },
        "cohorts": {
            "research_high_runtime_low": _cohort_report("research_high_runtime_low", blindspot, comparable),
            "research_75_plus_runtime_low": _cohort_report("research_75_plus_runtime_low", near_miss, comparable),
            "runtime_high_research_low": _cohort_report("runtime_high_research_low", false_confidence, comparable),
            "aligned_high": _cohort_report("aligned_high", aligned_high, comparable),
        },
        "runtime_vs_research_matrix": _score_matrix(comparable),
        "blindspot_feature_gaps": _feature_gap_rows(blindspot, comparable),
        "blindspot_subgroups": _blindspot_subgroups(blindspot),
    }
    report["diagnostic_read"] = _build_diagnostic_read(report)
    return _json_ready(report)


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


def render_runtime_research_composite_gap_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    alignment = report.get("score_alignment") or {}
    read = report.get("diagnostic_read") or {}
    cohorts = report.get("cohorts") or {}
    lines = [
        "# Runtime vs Research Composite Gap Report",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only diagnostic compares the live-time `runtime_composite_score` "
        "against the post-evaluation `composite_signal_score`. The post-evaluation score "
        "contains realized outcome information, so it is used only to locate possible "
        "missing live-time features. It must not be used as a live decision score.",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Rows after date filter: `{coverage.get('rows_after_date_filter')}`",
        f"- Directional rows: `{coverage.get('directional_rows')}`",
        f"- Comparable rows with both scores: `{coverage.get('comparable_rows')}`",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Comparable sample is small: `{read.get('comparable_sample_is_small')}`",
        f"- Runtime blindspot rows: `{read.get('blindspot_rows')}`",
        f"- False-confidence rows: `{read.get('false_confidence_rows')}`",
        f"- Blindspot avg score gap: `{read.get('blindspot_avg_score_gap')}`",
        f"- Blindspot provider weak share: `{read.get('blindspot_provider_weak_share')}`",
        f"- Blindspot execution usable share: `{read.get('blindspot_execution_usable_share')}`",
        f"- Blindspot strong confirmation share: `{read.get('blindspot_strong_confirmation_share')}`",
        f"- Blindspot candle confirmed share: `{read.get('blindspot_candle_confirmed_share')}`",
        f"- Largest runtime bucket: `{read.get('largest_blindspot_runtime_bucket')}`",
        f"- Largest regime bucket: `{read.get('largest_blindspot_regime_bucket')}`",
        f"- Largest provider/confirmation bucket: `{read.get('largest_blindspot_provider_confirmation_bucket')}`",
        f"- Largest wall bucket: `{read.get('largest_blindspot_wall_bucket')}`",
        f"- Primary read: `{read.get('primary_read')}`",
        "",
        "## Score Alignment",
        "",
        f"- Spearman correlation: `{alignment.get('spearman_correlation')}`",
        f"- Avg runtime score: `{alignment.get('avg_runtime_composite_score')}`",
        f"- Avg research score: `{alignment.get('avg_research_composite_score')}`",
        f"- Avg research-runtime gap: `{alignment.get('avg_score_gap')}`",
        f"- Runtime max: `{alignment.get('runtime_max')}`",
        f"- Research max: `{alignment.get('research_max')}`",
        "",
        "## Cohort Summary",
        "",
    ]
    cohort_rows = []
    for name, cohort in cohorts.items():
        metrics = cohort.get("metrics") or {}
        cohort_rows.append({"cohort": name, **metrics})
    lines.extend(
        _markdown_table(
            cohort_rows,
            [
                "cohort",
                "row_count",
                "avg_runtime_composite_score",
                "avg_research_composite_score",
                "avg_score_gap",
                "avg_trade_strength",
                "avg_move_probability",
                "avg_signed_return_60m_bps",
                "hit_rate_60m",
                "mfe_mae_ratio_60m",
                "outcome_complete_share",
                "outcome_partial_share",
                "provider_weak_share",
                "execution_usable_share",
                "strong_confirmation_share",
                "candle_confirmed_share",
            ],
        )
    )
    lines.extend(["", "## Blindspot Feature Gaps", ""])
    lines.extend(
        _markdown_table(
            report.get("blindspot_feature_gaps") or [],
            ["feature_group", "blindspot_value", "comparable_value", "delta", "interpretation"],
        )
    )
    lines.extend(["", "## Blindspot Subgroups", ""])
    subgroup_sections = [
        ("Runtime Bucket", "runtime_bucket"),
        ("Gamma X Volatility", "gamma_x_volatility"),
        ("Global Risk", "global_risk_state"),
        ("Provider X Confirmation", "provider_x_confirmation"),
        ("Confirmation X Candle", "confirmation_x_candle"),
        ("Wall Context", "wall_context_state"),
        ("Nearest Wall Bucket", "nearest_wall_bucket"),
        ("Max Pain Zone", "max_pain_zone"),
    ]
    subgroup_columns = [
        "subgroup",
        "row_count",
        "share_of_blindspots",
        "avg_runtime_composite_score",
        "avg_research_composite_score",
        "avg_score_gap",
        "hit_rate_60m",
        "mfe_mae_ratio_60m",
        "provider_weak_share",
        "execution_usable_share",
        "strong_confirmation_share",
        "candle_confirmed_share",
    ]
    blindspot_subgroups = report.get("blindspot_subgroups") or {}
    for title, key in subgroup_sections:
        lines.extend(["", f"### {title}", ""])
        lines.extend(_markdown_table(blindspot_subgroups.get(key) or [], subgroup_columns, max_rows=10))
    lines.extend(["", "## Research Component Drivers In Runtime Blindspots", ""])
    blindspot = (cohorts.get("research_high_runtime_low") or {}).get("research_component_drivers") or []
    lines.extend(
        _markdown_table(
            blindspot,
            ["component", "avg_score", "high_component_share", "missing_share"],
        )
    )
    lines.extend(["", "## Runtime vs Research Score Matrix", ""])
    lines.extend(
        _markdown_table(
            report.get("runtime_vs_research_matrix") or [],
            [
                "runtime_bucket",
                "research_bucket",
                "row_count",
                "avg_runtime_composite_score",
                "avg_research_composite_score",
                "avg_signed_return_60m_bps",
                "hit_rate_60m",
            ],
            max_rows=50,
        )
    )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This report is hindsight-guided and research-only.",
            "- Use it to identify live feature gaps, not to tune live decisions directly.",
            "- Any candidate live feature must be tested with forward-only rows after implementation.",
            "",
        ]
    )
    return "\n".join(lines)


def write_runtime_research_composite_gap_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_RESEARCH_COMPOSITE_GAP_REPORT_DIR,
    report_date: str | None = None,
    research_high_threshold: float = DEFAULT_RESEARCH_HIGH_THRESHOLD,
    runtime_low_threshold: float = DEFAULT_RUNTIME_LOW_THRESHOLD,
    runtime_high_threshold: float = DEFAULT_RUNTIME_HIGH_THRESHOLD,
    research_low_threshold: float = DEFAULT_RESEARCH_LOW_THRESHOLD,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = load_runtime_research_composite_gap_dataset(dataset)
    report = build_runtime_research_composite_gap_report(
        frame,
        report_date=report_date,
        research_high_threshold=research_high_threshold,
        runtime_low_threshold=runtime_low_threshold,
        runtime_high_threshold=runtime_high_threshold,
        research_low_threshold=research_low_threshold,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    json_path = output / f"runtime_research_composite_gap_{timestamp}.json"
    markdown_path = output / f"runtime_research_composite_gap_{timestamp}.md"
    latest_json_path = output / "latest_runtime_research_composite_gap.json"
    latest_markdown_path = output / "latest_runtime_research_composite_gap.md"
    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_runtime_research_composite_gap_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")
    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="runtime_research_composite_gap",
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

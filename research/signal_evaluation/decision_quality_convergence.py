"""Research-only convergence diagnostics for live decision-quality metrics.

This module compares existing live-safe signal ingredients against matured
research labels.  It does not change runtime signal generation, parameter
packs, data-source routing, or execution behavior.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH
from research.signal_evaluation.decision_quality_bridge import compute_decision_quality_bridge
from research.signal_evaluation.label_quality import apply_quality_label_view
from research.signal_evaluation.report_manifest import write_report_reproducibility_manifest
from utils.timestamp_helpers import coerce_timestamp_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DECISION_QUALITY_CONVERGENCE_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "decision_quality_convergence"
)

HORIZONS: tuple[tuple[str, str, str], ...] = (
    ("5m", "signed_return_5m_bps", "correct_5m"),
    ("15m", "signed_return_15m_bps", "correct_15m"),
    ("30m", "signed_return_30m_bps", "correct_30m"),
    ("60m", "signed_return_60m_bps", "correct_60m"),
    ("120m", "signed_return_120m_bps", "correct_120m"),
    ("session_close", "signed_return_session_close_bps", "correct_session_close"),
)

LIVE_SCORE_COLUMNS = (
    "trade_strength",
    "runtime_composite_score",
    "decision_quality_score_v1",
    "decision_quality_score_v1_raw",
    "hybrid_move_probability",
    "move_probability",
    "rule_move_probability",
    "ml_move_probability",
    "signal_confidence_score",
    "option_efficiency_score",
    "target_reachability_score",
    "premium_efficiency_score",
    "strike_efficiency_score",
    "ta_entry_timing_score",
    "price_level_confluence_score",
    "price_structure_trend_day_proxy_score",
    "nearest_price_structure_anchor_distance_pct",
)

LIVE_CONTEXT_COLUMNS = (
    "signal_timestamp",
    "direction",
    "trade_status",
    "signal_quality",
    "confirmation_status",
    "effective_min_trade_strength_threshold",
    "effective_min_composite_score_threshold",
    "provider_quality_mode",
    "provider_health_status",
    "provider_analytics_status",
    "provider_execution_status",
    "provider_direction_trust",
    "provider_execution_trust",
    "provider_quality_blocks_direction",
    "provider_quality_blocks_execution",
    "data_quality_status",
    "execution_suggestion_usable",
    "tradable_data_status",
    "option_source",
    "requested_option_source",
    "gamma_regime",
    "volatility_regime",
    "macro_regime",
    "global_risk_state",
    "spot_vs_flip",
    "wall_context_state",
    "nearest_wall_bucket",
    "ta_entry_timing_state",
    "ta_candle_state",
    "ta_candle_late_chase",
    "final_flow_signal",
    "option_efficiency_status",
    "price_structure_acceptance_state",
)

RESEARCH_LABEL_COLUMNS = (
    "composite_signal_score",
    "mfe_60m_bps",
    "mae_60m_bps",
    "calibration_label",
    "primary_outcome_return_bps",
    "calibration_label_available",
    "label_quality_status",
    "label_quality_reasons",
    *[column for _, return_col, hit_col in HORIZONS for column in (return_col, hit_col)],
)

USE_COLUMNS = tuple(dict.fromkeys((*LIVE_CONTEXT_COLUMNS, *LIVE_SCORE_COLUMNS, *RESEARCH_LABEL_COLUMNS)))

SCORE_BUCKET_EDGES = (-0.01, 35.0, 50.0, 60.0, 70.0, 80.0, 100.0001)
SCORE_BUCKET_LABELS = ("0-35", "35-50", "50-60", "60-70", "70-80", "80-100")
GRID_BUCKET_EDGES = (-0.01, 50.0, 60.0, 70.0, 80.0, 100.0001)
GRID_BUCKET_LABELS = ("0-50", "50-60", "60-70", "70-80", "80-100")

DEFAULT_TRADE_STRENGTH_THRESHOLD = 60.0
DEFAULT_RUNTIME_COMPOSITE_THRESHOLD = 55.0


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if pd.isna(number) or not np.isfinite(number):
        return default
    return number


def _round_or_none(value: Any, digits: int = 4) -> float | None:
    number = _safe_float(value, None)
    return round(number, digits) if number is not None else None


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
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


def _truthy(series: pd.Series) -> pd.Series:
    text = series.astype("object").where(series.notna(), False).astype(str).str.strip().str.upper()
    return text.isin({"TRUE", "T", "YES", "Y", "1", "1.0"}).astype(bool)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        frame.to_csv(tmp_path, index=False)
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


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


def _safe_mean(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.mean())


def _score_bucket(series: pd.Series, *, grid: bool = False) -> pd.Series:
    edges = GRID_BUCKET_EDGES if grid else SCORE_BUCKET_EDGES
    labels = GRID_BUCKET_LABELS if grid else SCORE_BUCKET_LABELS
    return pd.cut(
        pd.to_numeric(series, errors="coerce"),
        bins=list(edges),
        labels=list(labels),
        include_lowest=True,
        right=False,
    ).astype("string")


def _probability_score(frame: pd.DataFrame) -> pd.Series:
    probability = pd.Series(np.nan, index=frame.index, dtype="float64")
    for column in ("hybrid_move_probability", "move_probability", "rule_move_probability", "ml_move_probability"):
        if column not in frame.columns:
            continue
        candidate = pd.to_numeric(frame[column], errors="coerce")
        if candidate.dropna().empty:
            continue
        probability = probability.combine_first(candidate)
    if probability.dropna().empty:
        return probability
    if float(probability.dropna().quantile(0.95)) <= 1.5:
        probability = probability * 100.0
    return probability.clip(lower=0.0, upper=100.0)


def _weighted_candidate_score(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    numerator = pd.Series(0.0, index=frame.index, dtype="float64")
    denominator = pd.Series(0.0, index=frame.index, dtype="float64")
    for column, weight in weights.items():
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce").clip(lower=0.0, upper=100.0)
        valid = values.notna()
        numerator = numerator.add(values.fillna(0.0) * float(weight), fill_value=0.0)
        denominator = denominator.add(valid.astype(float) * float(weight), fill_value=0.0)
    score = numerator / denominator.replace(0.0, np.nan)
    return score.clip(lower=0.0, upper=100.0)


def _guard_penalty(frame: pd.DataFrame) -> pd.Series:
    penalty = pd.Series(0.0, index=frame.index, dtype="float64")
    if "provider_quality_blocks_direction" in frame.columns:
        penalty += _truthy(frame["provider_quality_blocks_direction"]).astype(float) * 15.0
    if "provider_quality_blocks_execution" in frame.columns:
        penalty += _truthy(frame["provider_quality_blocks_execution"]).astype(float) * 5.0
    for column in ("provider_health_status", "data_quality_status"):
        if column in frame.columns:
            status = _normalize_text(frame[column])
            penalty += (~status.isin({"GOOD", "STRONG", "OK", "PASS"})).astype(float) * 4.0
    if "global_risk_state" in frame.columns:
        penalty += _normalize_text(frame["global_risk_state"]).str.contains("RISK_OFF", na=False).astype(float) * 3.0
    if "macro_regime" in frame.columns:
        penalty += _normalize_text(frame["macro_regime"]).str.contains("RISK_OFF", na=False).astype(float) * 3.0
    if "spot_vs_flip" in frame.columns:
        penalty += (_normalize_text(frame["spot_vs_flip"]) == "AT_FLIP").astype(float) * 2.0
    return penalty.clip(lower=0.0, upper=35.0)


def load_decision_quality_convergence_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset = Path(path)
    if not dataset.exists():
        raise FileNotFoundError(f"Signal dataset not found: {dataset}")
    return pd.read_csv(dataset, usecols=lambda column: column in USE_COLUMNS, low_memory=False)


def prepare_decision_quality_convergence_frame(
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

    if "signal_timestamp" in working.columns:
        working["signal_ts"] = coerce_timestamp_series(working["signal_timestamp"])
    else:
        working["signal_ts"] = pd.Series(pd.NaT, index=working.index, dtype="datetime64[ns, UTC]")
    local_ts = working["signal_ts"].dt.tz_convert("Asia/Kolkata")
    working["signal_date"] = local_ts.dt.strftime("%Y-%m-%d").fillna("UNKNOWN")

    if report_date:
        working = working.loc[working["signal_date"] == str(report_date)].copy()
    if start_date:
        working = working.loc[working["signal_date"] >= str(start_date)].copy()
    if end_date:
        working = working.loc[working["signal_date"] <= str(end_date)].copy()

    direction = _normalize_text(working["direction"]).str.upper()
    working = working.loc[direction.isin({"CALL", "PUT"})].copy()
    if working.empty:
        return working

    working = apply_quality_label_view(working, fallback_to_legacy=True, drop_unapproved=False)
    for column in (
        *LIVE_SCORE_COLUMNS,
        "composite_signal_score",
        "effective_min_trade_strength_threshold",
        "effective_min_composite_score_threshold",
        "mfe_60m_bps",
        "mae_60m_bps",
        *[column for _, return_col, hit_col in HORIZONS for column in (return_col, hit_col)],
    ):
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")

    for column in LIVE_CONTEXT_COLUMNS:
        if column in working.columns and column not in {
            "signal_timestamp",
            "effective_min_trade_strength_threshold",
            "effective_min_composite_score_threshold",
        }:
            working[column] = _normalize_text(working[column])

    working["probability_score_0_100"] = _probability_score(working)
    if "option_efficiency_score" in working.columns:
        option_eff = pd.to_numeric(working["option_efficiency_score"], errors="coerce")
    else:
        option_eff = pd.Series(np.nan, index=working.index)
    if option_eff.dropna().empty:
        premium = pd.to_numeric(working.get("premium_efficiency_score", pd.Series(index=working.index)), errors="coerce")
        strike = pd.to_numeric(working.get("strike_efficiency_score", pd.Series(index=working.index)), errors="coerce")
        option_eff = pd.concat([premium, strike], axis=1).mean(axis=1)
    working["option_efficiency_score_0_100"] = option_eff.clip(lower=0.0, upper=100.0)

    timing = pd.to_numeric(working.get("ta_entry_timing_score", pd.Series(index=working.index)), errors="coerce")
    working["timing_score_0_100"] = timing.clip(lower=0.0, upper=100.0)

    bridge_payloads = working.apply(lambda row: compute_decision_quality_bridge(row.to_dict()), axis=1)
    working["decision_quality_score_v1"] = bridge_payloads.map(lambda payload: payload.get("score"))
    working["decision_quality_score_v1_raw"] = bridge_payloads.map(lambda payload: payload.get("raw_score"))
    working["decision_quality_score_v1_penalty_total"] = bridge_payloads.map(lambda payload: payload.get("penalty_total"))
    working["decision_quality_score_v1_primary_drivers"] = bridge_payloads.map(
        lambda payload: "|".join(payload.get("primary_drivers") or [])
    )

    working["candidate_decision_quality_blend_v0"] = _weighted_candidate_score(
        working.assign(
            probability_score_0_100=working["probability_score_0_100"],
            option_efficiency_score_0_100=working["option_efficiency_score_0_100"],
            timing_score_0_100=working["timing_score_0_100"],
        ),
        {
            "trade_strength": 0.45,
            "runtime_composite_score": 0.25,
            "probability_score_0_100": 0.15,
            "option_efficiency_score_0_100": 0.10,
            "timing_score_0_100": 0.05,
        },
    )
    working["candidate_decision_quality_guarded_v0"] = (
        working["candidate_decision_quality_blend_v0"] - _guard_penalty(working)
    ).clip(lower=0.0, upper=100.0)

    trade_threshold = pd.to_numeric(
        working["effective_min_trade_strength_threshold"], errors="coerce"
    ).fillna(DEFAULT_TRADE_STRENGTH_THRESHOLD)
    runtime_threshold = pd.to_numeric(
        working["effective_min_composite_score_threshold"], errors="coerce"
    ).fillna(DEFAULT_RUNTIME_COMPOSITE_THRESHOLD)
    working["trade_strength_pass"] = working["trade_strength"] >= trade_threshold
    working["runtime_composite_pass"] = working["runtime_composite_score"] >= runtime_threshold
    working["trade_strength_gap"] = working["trade_strength"] - trade_threshold
    working["runtime_composite_gap"] = working["runtime_composite_score"] - runtime_threshold
    working["effective_gate_state"] = np.select(
        [
            working["trade_strength_pass"] & working["runtime_composite_pass"],
            working["trade_strength_pass"] & ~working["runtime_composite_pass"],
            ~working["trade_strength_pass"] & working["runtime_composite_pass"],
        ],
        ["BOTH_PASS", "TRADE_PASS_RUNTIME_FAIL", "RUNTIME_PASS_TRADE_FAIL"],
        default="BOTH_FAIL",
    )
    working["trade_strength_bucket"] = _score_bucket(working["trade_strength"])
    working["runtime_composite_bucket"] = _score_bucket(working["runtime_composite_score"])
    working["trade_strength_grid_bucket"] = _score_bucket(working["trade_strength"], grid=True)
    working["runtime_composite_grid_bucket"] = _score_bucket(working["runtime_composite_score"], grid=True)
    return working.reset_index(drop=True)


def _mfe_mae_ratio(frame: pd.DataFrame) -> float | None:
    mfe = _safe_mean(frame.get("mfe_60m_bps", pd.Series(index=frame.index)))
    mae = _safe_mean(pd.to_numeric(frame.get("mae_60m_bps", pd.Series(index=frame.index)), errors="coerce").abs())
    if mfe is None or mae is None or mae <= 0:
        return None
    return mfe / mae


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "row_count": int(len(frame)),
        "avg_expost_composite": _round_or_none(_safe_mean(frame.get("composite_signal_score", pd.Series(index=frame.index))), 3),
        "expost_ge80_rate": None,
        "avg_mfe_60m_bps": _round_or_none(_safe_mean(frame.get("mfe_60m_bps", pd.Series(index=frame.index))), 3),
        "avg_mae_60m_bps": _round_or_none(_safe_mean(frame.get("mae_60m_bps", pd.Series(index=frame.index))), 3),
        "mfe_mae_ratio_60m": _round_or_none(_mfe_mae_ratio(frame), 3),
    }
    expost = pd.to_numeric(frame.get("composite_signal_score", pd.Series(index=frame.index)), errors="coerce")
    if expost.notna().any():
        payload["expost_ge80_rate"] = _round_or_none(float((expost.dropna() >= 80.0).mean() * 100.0), 2)
    for horizon, return_col, hit_col in HORIZONS:
        hits = pd.to_numeric(frame.get(hit_col, pd.Series(index=frame.index)), errors="coerce")
        returns = pd.to_numeric(frame.get(return_col, pd.Series(index=frame.index)), errors="coerce")
        payload[f"label_count_{horizon}"] = int(hits.notna().sum())
        payload[f"hit_rate_{horizon}"] = (
            _round_or_none(float(hits.dropna().mean() * 100.0), 2) if hits.notna().any() else None
        )
        payload[f"avg_return_{horizon}_bps"] = (
            _round_or_none(float(returns.dropna().mean()), 3) if returns.notna().any() else None
        )
    return payload


def _correlations(frame: pd.DataFrame, score: str) -> dict[str, Any]:
    values = pd.to_numeric(frame.get(score, pd.Series(index=frame.index)), errors="coerce")
    payload: dict[str, Any] = {"metric": score, "non_null_rows": int(values.notna().sum())}
    targets = {
        "expost_composite": "composite_signal_score",
        "hit_60m": "correct_60m",
        "return_60m_bps": "signed_return_60m_bps",
        "hit_120m": "correct_120m",
        "return_120m_bps": "signed_return_120m_bps",
    }
    for target_name, column in targets.items():
        target = pd.to_numeric(frame.get(column, pd.Series(index=frame.index)), errors="coerce")
        paired = pd.concat([values, target], axis=1).dropna()
        if len(paired) < 3 or paired.iloc[:, 0].nunique() < 2 or paired.iloc[:, 1].nunique() < 2:
            payload[f"pearson_{target_name}"] = None
            payload[f"spearman_{target_name}"] = None
            continue
        payload[f"pearson_{target_name}"] = _round_or_none(paired.iloc[:, 0].corr(paired.iloc[:, 1], method="pearson"), 4)
        payload[f"spearman_{target_name}"] = _round_or_none(paired.iloc[:, 0].corr(paired.iloc[:, 1], method="spearman"), 4)
    return payload


def _bucket_summary(frame: pd.DataFrame, score: str) -> list[dict[str, Any]]:
    values = pd.to_numeric(frame.get(score, pd.Series(index=frame.index)), errors="coerce")
    bucketed = frame.loc[values.notna()].copy()
    if bucketed.empty:
        return []
    bucketed["_metric_bucket"] = _score_bucket(values.loc[bucketed.index])
    rows: list[dict[str, Any]] = []
    for bucket, group in bucketed.groupby("_metric_bucket", observed=True):
        if group.empty:
            continue
        row = {
            "metric": score,
            "bucket": str(bucket),
            "avg_metric": _round_or_none(_safe_mean(group[score]), 3),
        }
        row.update(_metrics(group))
        rows.append(row)
    return rows


def _monotonicity(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    selected = [row for row in rows if row.get("metric") == metric]
    if len(selected) < 3:
        return {
            "metric": metric,
            "bucket_count": len(selected),
            "spearman_bucket_hit_60m": None,
            "spearman_bucket_return_60m": None,
            "hit_60m_adjacent_violations": None,
            "return_60m_adjacent_violations": None,
        }
    order = {label: idx for idx, label in enumerate(SCORE_BUCKET_LABELS)}
    selected = sorted(selected, key=lambda row: order.get(str(row.get("bucket")), 999))
    bucket_index = pd.Series(range(len(selected)), dtype="float64")
    hit = pd.to_numeric(pd.Series([row.get("hit_rate_60m") for row in selected]), errors="coerce")
    ret = pd.to_numeric(pd.Series([row.get("avg_return_60m_bps") for row in selected]), errors="coerce")

    def violations(values: pd.Series) -> int | None:
        values = values.dropna()
        if len(values) < 2:
            return None
        return int((values.diff().dropna() < 0).sum())

    return {
        "metric": metric,
        "bucket_count": len(selected),
        "spearman_bucket_hit_60m": _round_or_none(bucket_index.corr(hit, method="spearman"), 4)
        if hit.notna().sum() >= 3
        else None,
        "spearman_bucket_return_60m": _round_or_none(bucket_index.corr(ret, method="spearman"), 4)
        if ret.notna().sum() >= 3
        else None,
        "hit_60m_adjacent_violations": violations(hit),
        "return_60m_adjacent_violations": violations(ret),
    }


def _gate_state_summary(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if "effective_gate_state" not in frame.columns:
        return []
    rows: list[dict[str, Any]] = []
    order = ("BOTH_PASS", "TRADE_PASS_RUNTIME_FAIL", "RUNTIME_PASS_TRADE_FAIL", "BOTH_FAIL")
    for state in order:
        group = frame.loc[frame["effective_gate_state"] == state]
        if group.empty:
            continue
        row = {
            "effective_gate_state": state,
            "avg_trade_strength": _round_or_none(_safe_mean(group.get("trade_strength", pd.Series(index=group.index))), 3),
            "avg_runtime_composite": _round_or_none(
                _safe_mean(group.get("runtime_composite_score", pd.Series(index=group.index))), 3
            ),
            "avg_trade_strength_gap": _round_or_none(_safe_mean(group.get("trade_strength_gap", pd.Series(index=group.index))), 3),
            "avg_runtime_composite_gap": _round_or_none(
                _safe_mean(group.get("runtime_composite_gap", pd.Series(index=group.index))), 3
            ),
        }
        row.update(_metrics(group))
        rows.append(row)
    return rows


def _two_dimensional_grid(frame: pd.DataFrame, *, min_rows: int = 5) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    grouped = frame.groupby(["trade_strength_grid_bucket", "runtime_composite_grid_bucket"], observed=True)
    for (trade_bucket, runtime_bucket), group in grouped:
        if len(group) < min_rows:
            continue
        row = {
            "trade_strength_bucket": str(trade_bucket),
            "runtime_composite_bucket": str(runtime_bucket),
            "avg_trade_strength": _round_or_none(_safe_mean(group.get("trade_strength", pd.Series(index=group.index))), 3),
            "avg_runtime_composite": _round_or_none(
                _safe_mean(group.get("runtime_composite_score", pd.Series(index=group.index))), 3
            ),
        }
        row.update(_metrics(group))
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            GRID_BUCKET_LABELS.index(row["trade_strength_bucket"]) if row["trade_strength_bucket"] in GRID_BUCKET_LABELS else 99,
            GRID_BUCKET_LABELS.index(row["runtime_composite_bucket"]) if row["runtime_composite_bucket"] in GRID_BUCKET_LABELS else 99,
        ),
    )


def _residual_splits(frame: pd.DataFrame, *, min_rows: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    specs = (
        ("runtime_bucket_trade_strength_high_low", "runtime_composite_bucket", "trade_strength"),
        ("trade_strength_bucket_runtime_high_low", "trade_strength_bucket", "runtime_composite_score"),
    )
    for split_name, bucket_col, split_col in specs:
        if bucket_col not in frame.columns or split_col not in frame.columns:
            continue
        for bucket, group in frame.groupby(bucket_col, observed=True):
            group = group.loc[pd.to_numeric(group[split_col], errors="coerce").notna()]
            if len(group) < min_rows:
                continue
            median = float(pd.to_numeric(group[split_col], errors="coerce").median())
            high = group.loc[pd.to_numeric(group[split_col], errors="coerce") >= median]
            low = group.loc[pd.to_numeric(group[split_col], errors="coerce") < median]
            if len(high) < max(5, min_rows // 4) or len(low) < max(5, min_rows // 4):
                continue
            high_metrics = _metrics(high)
            low_metrics = _metrics(low)
            rows.append(
                {
                    "split": split_name,
                    "bucket": str(bucket),
                    "split_metric": split_col,
                    "split_median": _round_or_none(median, 3),
                    "high_count": int(len(high)),
                    "low_count": int(len(low)),
                    "high_hit_60m": high_metrics.get("hit_rate_60m"),
                    "low_hit_60m": low_metrics.get("hit_rate_60m"),
                    "delta_hit_60m": _round_or_none(
                        (_safe_float(high_metrics.get("hit_rate_60m"), 0.0) or 0.0)
                        - (_safe_float(low_metrics.get("hit_rate_60m"), 0.0) or 0.0),
                        3,
                    ),
                    "high_return_60m_bps": high_metrics.get("avg_return_60m_bps"),
                    "low_return_60m_bps": low_metrics.get("avg_return_60m_bps"),
                    "delta_return_60m_bps": _round_or_none(
                        (_safe_float(high_metrics.get("avg_return_60m_bps"), 0.0) or 0.0)
                        - (_safe_float(low_metrics.get("avg_return_60m_bps"), 0.0) or 0.0),
                        3,
                    ),
                }
            )
    return sorted(rows, key=lambda row: abs(float(row.get("delta_return_60m_bps") or 0.0)), reverse=True)


def _top_quantile_lift(frame: pd.DataFrame, score: str, *, quantile: float = 0.80) -> dict[str, Any]:
    values = pd.to_numeric(frame.get(score, pd.Series(index=frame.index)), errors="coerce")
    usable = frame.loc[values.notna()].copy()
    if len(usable) < 10:
        return {"metric": score, "top_quantile": quantile, "error": "INSUFFICIENT_ROWS"}
    threshold = float(values.loc[usable.index].quantile(quantile))
    top = usable.loc[values.loc[usable.index] >= threshold]
    rest = usable.loc[values.loc[usable.index] < threshold]
    top_metrics = _metrics(top)
    rest_metrics = _metrics(rest)
    return {
        "metric": score,
        "top_quantile": quantile,
        "threshold": _round_or_none(threshold, 3),
        "top_count": int(len(top)),
        "rest_count": int(len(rest)),
        "top_hit_60m": top_metrics.get("hit_rate_60m"),
        "rest_hit_60m": rest_metrics.get("hit_rate_60m"),
        "lift_hit_60m": _round_or_none(
            (_safe_float(top_metrics.get("hit_rate_60m"), 0.0) or 0.0)
            - (_safe_float(rest_metrics.get("hit_rate_60m"), 0.0) or 0.0),
            3,
        ),
        "top_return_60m_bps": top_metrics.get("avg_return_60m_bps"),
        "rest_return_60m_bps": rest_metrics.get("avg_return_60m_bps"),
        "lift_return_60m_bps": _round_or_none(
            (_safe_float(top_metrics.get("avg_return_60m_bps"), 0.0) or 0.0)
            - (_safe_float(rest_metrics.get("avg_return_60m_bps"), 0.0) or 0.0),
            3,
        ),
        "top_expost_ge80_rate": top_metrics.get("expost_ge80_rate"),
        "rest_expost_ge80_rate": rest_metrics.get("expost_ge80_rate"),
    }


def _primary_read(report: dict[str, Any]) -> dict[str, Any]:
    correlations = {row.get("metric"): row for row in report.get("metric_alignment") or []}
    trade_corr = _safe_float((correlations.get("trade_strength") or {}).get("spearman_return_60m_bps"), None)
    runtime_corr = _safe_float((correlations.get("runtime_composite_score") or {}).get("spearman_return_60m_bps"), None)
    candidate_corr = _safe_float(
        (correlations.get("candidate_decision_quality_guarded_v0") or {}).get("spearman_return_60m_bps"),
        None,
    )
    bridge_corr = _safe_float(
        (correlations.get("decision_quality_score_v1") or {}).get("spearman_return_60m_bps"),
        None,
    )
    gate_rows = {row.get("effective_gate_state"): row for row in report.get("effective_gate_state_summary") or []}
    trade_pass_runtime_fail = gate_rows.get("TRADE_PASS_RUNTIME_FAIL") or {}
    both_fail = gate_rows.get("BOTH_FAIL") or {}
    tprf_count = int(trade_pass_runtime_fail.get("label_count_60m") or 0)
    tprf_return = _safe_float(trade_pass_runtime_fail.get("avg_return_60m_bps"), None)
    both_fail_return = _safe_float(both_fail.get("avg_return_60m_bps"), None)
    top_lift_rows = report.get("top_quantile_lift") or []
    best_lift = max(
        top_lift_rows,
        key=lambda row: _safe_float(row.get("lift_return_60m_bps"), float("-inf")) or float("-inf"),
        default={},
    )
    observations: list[str] = []
    if trade_corr is not None and runtime_corr is not None and trade_corr > runtime_corr + 0.05:
        observations.append("TRADE_STRENGTH_HAS_INCREMENTAL_ALIGNMENT")
    if candidate_corr is not None and trade_corr is not None and runtime_corr is not None:
        if candidate_corr >= max(trade_corr, runtime_corr) + 0.02:
            observations.append("GUARDED_BLEND_HAS_INCREMENTAL_ALIGNMENT")
    if bridge_corr is not None and trade_corr is not None and runtime_corr is not None:
        if bridge_corr >= max(trade_corr, runtime_corr) + 0.02:
            observations.append("DECISION_QUALITY_BRIDGE_HAS_INCREMENTAL_ALIGNMENT")
    if tprf_count >= 30 and tprf_return is not None and tprf_return > 0:
        if both_fail_return is not None and tprf_return > both_fail_return + 2.0:
            observations.append("TRADE_PASS_RUNTIME_FAIL_OUTPERFORMS_BOTH_FAIL")
        else:
            observations.append("TRADE_PASS_RUNTIME_FAIL_POSITIVE_BUT_NOT_DOMINANT")
    if not observations:
        observations.append("NO_SINGLE_METRIC_READY")
    return {
        "primary_read": observations[0],
        "observations": observations,
        "trade_strength_spearman_return_60m": _round_or_none(trade_corr, 4),
        "runtime_composite_spearman_return_60m": _round_or_none(runtime_corr, 4),
        "guarded_blend_spearman_return_60m": _round_or_none(candidate_corr, 4),
        "decision_quality_score_v1_spearman_return_60m": _round_or_none(bridge_corr, 4),
        "trade_pass_runtime_fail_label_count_60m": tprf_count,
        "trade_pass_runtime_fail_avg_return_60m_bps": _round_or_none(tprf_return, 3),
        "both_fail_avg_return_60m_bps": _round_or_none(both_fail_return, 3),
        "best_top_quantile_metric_by_return_lift": best_lift.get("metric"),
        "best_top_quantile_return_lift_60m_bps": best_lift.get("lift_return_60m_bps"),
        "recommendation": (
            "Keep PG1-009 research-only. Use this report to decide whether a future "
            "decision_quality_score should blend signal intensity with runtime quality gates."
        ),
    }


def build_decision_quality_convergence_report(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    grid_min_rows: int = 5,
) -> dict[str, Any]:
    prepared = prepare_decision_quality_convergence_frame(
        frame,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    score_metrics = (
        "trade_strength",
        "runtime_composite_score",
        "probability_score_0_100",
        "option_efficiency_score_0_100",
        "timing_score_0_100",
        "decision_quality_score_v1",
        "candidate_decision_quality_blend_v0",
        "candidate_decision_quality_guarded_v0",
    )
    bucket_rows: list[dict[str, Any]] = []
    for metric in score_metrics:
        bucket_rows.extend(_bucket_summary(prepared, metric))
    report = {
        "report_type": "decision_quality_convergence",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "report_date": report_date,
            "start_date": start_date,
            "end_date": end_date,
            "mode": "research_only",
            "live_safe_metric_inputs": list(score_metrics),
            "research_labels": ["composite_signal_score", "correct_60m", "signed_return_60m_bps"],
            "candidate_blend_v0_formula": (
                "weighted live-safe blend: 45% trade_strength, 25% runtime_composite_score, "
                "15% move probability, 10% option efficiency, 5% TA timing; available components "
                "are re-normalized row-wise."
            ),
            "candidate_guarded_v0_formula": (
                "candidate_blend_v0 minus provider/data-quality, macro risk-off, and at-flip "
                "diagnostic penalties. This is research-only and not a live threshold."
            ),
            "decision_quality_score_v1_formula": (
                "live-safe parity bridge using the currently evidence-backed score inputs: "
                "signal intensity, runtime quality, and option tradeability, then subtracting "
                "scaled guard penalties. Probability, TA timing, price structure, provider/data "
                "quality, and regime context are captured as diagnostics, but carry zero positive "
                "weight until forward evidence shows stable incremental value. This is "
                "research-only and not a live threshold."
            ),
            "guardrail": (
                "This report can use matured outcomes and ex-post composite labels only for research. "
                "No candidate score may affect live behavior without fresh-forward validation."
            ),
        },
        "coverage": {
            "input_rows": int(len(frame if frame is not None else [])),
            "prepared_directional_rows": int(len(prepared)),
            "quality_approved_60m_labels": int(pd.to_numeric(prepared.get("correct_60m", pd.Series()), errors="coerce").notna().sum()),
            "start_timestamp": prepared["signal_ts"].dropna().min().isoformat()
            if not prepared.empty and prepared["signal_ts"].notna().any()
            else None,
            "end_timestamp": prepared["signal_ts"].dropna().max().isoformat()
            if not prepared.empty and prepared["signal_ts"].notna().any()
            else None,
            "session_count": int(prepared["signal_date"].nunique()) if not prepared.empty else 0,
        },
        "overall_metrics": _metrics(prepared),
        "metric_alignment": [_correlations(prepared, metric) for metric in score_metrics],
        "metric_bucket_summary": bucket_rows,
        "metric_monotonicity": [_monotonicity(bucket_rows, metric) for metric in score_metrics],
        "effective_gate_state_summary": _gate_state_summary(prepared),
        "trade_strength_runtime_grid": _two_dimensional_grid(prepared, min_rows=grid_min_rows),
        "residual_splits": _residual_splits(prepared),
        "top_quantile_lift": [_top_quantile_lift(prepared, metric) for metric in score_metrics],
    }
    report["diagnostic_read"] = _primary_read(report)
    return _json_ready(report)


def render_decision_quality_convergence_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    lines = [
        "# Decision Quality Convergence Diagnostic",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only report studies whether the engine can eventually converge "
        "toward one live-safe decision-quality metric. It compares existing live-time "
        "ingredients against matured labels. It does not change runtime behavior.",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Prepared directional rows: `{coverage.get('prepared_directional_rows')}`",
        f"- Quality-approved 60m labels: `{coverage.get('quality_approved_60m_labels')}`",
        f"- Sessions: `{coverage.get('session_count')}`",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Primary read: `{read.get('primary_read')}`",
        f"- Observations: `{', '.join(read.get('observations') or [])}`",
        f"- Trade-strength Spearman to 60m return: `{read.get('trade_strength_spearman_return_60m')}`",
        f"- Runtime-composite Spearman to 60m return: `{read.get('runtime_composite_spearman_return_60m')}`",
        f"- Decision-quality v1 Spearman to 60m return: `{read.get('decision_quality_score_v1_spearman_return_60m')}`",
        f"- Guarded-blend Spearman to 60m return: `{read.get('guarded_blend_spearman_return_60m')}`",
        f"- Trade-pass/runtime-fail 60m labels: `{read.get('trade_pass_runtime_fail_label_count_60m')}`",
        f"- Trade-pass/runtime-fail avg 60m return: `{read.get('trade_pass_runtime_fail_avg_return_60m_bps')}` bps",
        f"- Both-fail avg 60m return: `{read.get('both_fail_avg_return_60m_bps')}` bps",
        f"- Best top-quantile return-lift metric: `{read.get('best_top_quantile_metric_by_return_lift')}` "
        f"(`{read.get('best_top_quantile_return_lift_60m_bps')}` bps)",
        "",
        "## Metric Alignment",
        "",
    ]
    lines.extend(
        _markdown_table(
            report.get("metric_alignment") or [],
            [
                "metric",
                "non_null_rows",
                "spearman_expost_composite",
                "spearman_hit_60m",
                "spearman_return_60m_bps",
                "spearman_hit_120m",
                "spearman_return_120m_bps",
            ],
        )
    )
    lines.extend(["", "## Effective Gate States", ""])
    lines.extend(
        _markdown_table(
            report.get("effective_gate_state_summary") or [],
            [
                "effective_gate_state",
                "row_count",
                "label_count_60m",
                "avg_trade_strength",
                "avg_runtime_composite",
                "avg_trade_strength_gap",
                "avg_runtime_composite_gap",
                "hit_rate_60m",
                "avg_return_60m_bps",
                "avg_expost_composite",
                "expost_ge80_rate",
                "mfe_mae_ratio_60m",
            ],
        )
    )
    lines.extend(["", "## Top-Quantile Lift", ""])
    lines.extend(
        _markdown_table(
            report.get("top_quantile_lift") or [],
            [
                "metric",
                "threshold",
                "top_count",
                "top_hit_60m",
                "rest_hit_60m",
                "lift_hit_60m",
                "top_return_60m_bps",
                "rest_return_60m_bps",
                "lift_return_60m_bps",
                "top_expost_ge80_rate",
            ],
        )
    )
    lines.extend(["", "## Metric Monotonicity", ""])
    lines.extend(
        _markdown_table(
            report.get("metric_monotonicity") or [],
            [
                "metric",
                "bucket_count",
                "spearman_bucket_hit_60m",
                "spearman_bucket_return_60m",
                "hit_60m_adjacent_violations",
                "return_60m_adjacent_violations",
            ],
        )
    )
    lines.extend(["", "## Metric Buckets", ""])
    lines.extend(
        _markdown_table(
            report.get("metric_bucket_summary") or [],
            [
                "metric",
                "bucket",
                "row_count",
                "label_count_60m",
                "avg_metric",
                "hit_rate_60m",
                "avg_return_60m_bps",
                "avg_expost_composite",
                "expost_ge80_rate",
                "mfe_mae_ratio_60m",
            ],
            max_rows=80,
        )
    )
    lines.extend(["", "## Trade Strength x Runtime Composite Grid", ""])
    lines.extend(
        _markdown_table(
            report.get("trade_strength_runtime_grid") or [],
            [
                "trade_strength_bucket",
                "runtime_composite_bucket",
                "row_count",
                "label_count_60m",
                "avg_trade_strength",
                "avg_runtime_composite",
                "hit_rate_60m",
                "avg_return_60m_bps",
                "avg_expost_composite",
                "expost_ge80_rate",
            ],
            max_rows=60,
        )
    )
    lines.extend(["", "## Residual Splits", ""])
    lines.extend(
        _markdown_table(
            report.get("residual_splits") or [],
            [
                "split",
                "bucket",
                "split_metric",
                "split_median",
                "high_count",
                "low_count",
                "high_hit_60m",
                "low_hit_60m",
                "delta_hit_60m",
                "high_return_60m_bps",
                "low_return_60m_bps",
                "delta_return_60m_bps",
            ],
            max_rows=40,
        )
    )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This report is research-only.",
            "- `composite_signal_score` is a matured ex-post label, not a live input.",
            "- Candidate blend scores in this report are diagnostic only.",
            "- No live behavior should change until fresh-forward helped/hurt evidence is stable.",
            "",
        ]
    )
    return "\n".join(lines)


def write_decision_quality_convergence_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_DECISION_QUALITY_CONVERGENCE_REPORT_DIR,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    grid_min_rows: int = 5,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = load_decision_quality_convergence_dataset(dataset)
    report = build_decision_quality_convergence_report(
        frame,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
        grid_min_rows=grid_min_rows,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    json_path = output / f"decision_quality_convergence_{timestamp}.json"
    markdown_path = output / f"decision_quality_convergence_{timestamp}.md"
    latest_json_path = output / "latest_decision_quality_convergence.json"
    latest_markdown_path = output / "latest_decision_quality_convergence.md"
    metric_csv_path = output / f"decision_quality_convergence_{timestamp}_metric_alignment.csv"
    latest_metric_csv_path = output / "latest_decision_quality_convergence_metric_alignment.csv"
    bucket_csv_path = output / f"decision_quality_convergence_{timestamp}_metric_buckets.csv"
    latest_bucket_csv_path = output / "latest_decision_quality_convergence_metric_buckets.csv"
    gate_csv_path = output / f"decision_quality_convergence_{timestamp}_gate_states.csv"
    latest_gate_csv_path = output / "latest_decision_quality_convergence_gate_states.csv"
    grid_csv_path = output / f"decision_quality_convergence_{timestamp}_grid.csv"
    latest_grid_csv_path = output / "latest_decision_quality_convergence_grid.csv"
    residual_csv_path = output / f"decision_quality_convergence_{timestamp}_residual_splits.csv"
    latest_residual_csv_path = output / "latest_decision_quality_convergence_residual_splits.csv"

    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_decision_quality_convergence_markdown(report)
    _atomic_write_text(json_path, json_text)
    _atomic_write_text(latest_json_path, json_text)
    _atomic_write_text(markdown_path, markdown_text)
    _atomic_write_text(latest_markdown_path, markdown_text)
    _atomic_write_csv(pd.DataFrame(report.get("metric_alignment") or []), metric_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("metric_alignment") or []), latest_metric_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("metric_bucket_summary") or []), bucket_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("metric_bucket_summary") or []), latest_bucket_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("effective_gate_state_summary") or []), gate_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("effective_gate_state_summary") or []), latest_gate_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("trade_strength_runtime_grid") or []), grid_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("trade_strength_runtime_grid") or []), latest_grid_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("residual_splits") or []), residual_csv_path)
    _atomic_write_csv(pd.DataFrame(report.get("residual_splits") or []), latest_residual_csv_path)

    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="decision_quality_convergence",
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
        "metric_csv_path": str(metric_csv_path),
        "latest_metric_csv_path": str(latest_metric_csv_path),
        "bucket_csv_path": str(bucket_csv_path),
        "latest_bucket_csv_path": str(latest_bucket_csv_path),
        "gate_csv_path": str(gate_csv_path),
        "latest_gate_csv_path": str(latest_gate_csv_path),
        "grid_csv_path": str(grid_csv_path),
        "latest_grid_csv_path": str(latest_grid_csv_path),
        "residual_csv_path": str(residual_csv_path),
        "latest_residual_csv_path": str(latest_residual_csv_path),
        "manifest_path": str(manifest_path),
    }

"""Research diagnostics for runtime score versus post-evaluation score.

The post-evaluation composite uses realized outcomes, so it is never a live
decision input.  This module treats it as a label for finding live-time
blindspots in the runtime composite score.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH
from research.signal_evaluation.report_manifest import write_report_reproducibility_manifest
from research.signal_evaluation.runtime_blindspot_feature_audit import (
    LIVE_CATEGORICAL_FEATURES,
    LIVE_NUMERIC_FEATURES,
    USE_COLUMNS as BLINDSPOT_AUDIT_COLUMNS,
    prepare_runtime_blindspot_feature_frame,
)
from research.signal_evaluation.runtime_research_composite_gap import (
    DEFAULT_RESEARCH_HIGH_THRESHOLD,
    DEFAULT_RUNTIME_LOW_THRESHOLD,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_EXPOST_COMPOSITE_RELATION_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_expost_composite_relation"
)

EXTRA_NUMERIC_FEATURES = (
    "data_quality_score",
    "india_vix_level",
    "india_vix_change_24h",
    "atm_iv_percentile",
    "atm_iv_scaled",
    "weekday",
    "runtime_composite_observation_threshold",
    "effective_min_composite_score_threshold",
    "effective_min_trade_strength_threshold",
)

EXTRA_CATEGORICAL_FEATURES = (
    "requested_option_source",
    "option_source",
    "spot_source",
    "market_data_source_consistency",
    "market_data_provenance_status",
    "market_data_trade_blocking_status",
    "signal_quality",
    "signal_regime",
    "execution_regime",
    "final_flow_signal",
)

MODEL_NUMERIC_FEATURES = tuple(
    dict.fromkeys(
        (
            "runtime_composite_score",
            "trade_strength",
            "move_probability",
            "hybrid_move_probability",
            "rule_move_probability",
            "ml_move_probability",
            "signal_confidence_score",
            "data_quality_score",
            "target_reachability_score",
            "premium_efficiency_score",
            "strike_efficiency_score",
            "option_efficiency_score",
            "selected_option_iv",
            "selected_option_delta",
            "selected_option_gamma",
            "selected_option_theta",
            "selected_option_vega",
            "option_premium_pct_of_spot",
            "expected_move_pct",
            "lookback_avg_range_pct",
            "volume_pcr",
            "volume_pcr_atm",
            "pcr_value",
            "global_risk_score",
            "oil_shock_score",
            "commodity_risk_score",
            "volatility_shock_score",
            "volatility_explosion_probability",
            "gamma_vol_acceleration_score",
            "dealer_hedging_pressure_score",
            "dealer_pressure_adjustment_score",
            "pinning_pressure_score",
            "support_wall_distance_pct",
            "resistance_wall_distance_pct",
            "max_pain_distance_pct",
            "gamma_flip_distance_pct",
            "nearest_wall_distance_pct",
            "historical_expected_range_bps",
            "historical_expected_abs_move_bps",
            "historical_range_multiplier",
            "historical_global_prior_score",
            "historical_context_score_adjustment",
            "historical_context_probability_adjustment",
            "historical_interaction_score_adjustment",
            "historical_interaction_probability_adjustment",
            "statistical_vol_stress_score",
            "statistical_expected_range_bps",
            "statistical_expected_abs_move_bps",
            "statistical_regime_confidence",
            "statistical_context_score_adjustment",
            "statistical_context_probability_adjustment",
            "statistical_macro_score_adjustment",
            "statistical_macro_probability_adjustment",
            "ta_confidence",
            "ta_candle_body_bps",
            "ta_candle_range_bps",
            "ta_candle_close_location",
            "ta_candle_upper_wick_share",
            "ta_candle_lower_wick_share",
            "ta_candle_range_expansion_ratio",
            "ta_candle_momentum_3_bps",
            "ta_candle_momentum_5_bps",
            "ta_candle_prior_move_15m_bps",
            "ta_candle_prior_move_30m_bps",
            "ta_candle_confidence",
            "ta_entry_timing_score",
            "india_vix_level",
            "india_vix_change_24h",
            "atm_iv_percentile",
            "atm_iv_scaled",
            "weekday",
        )
    )
)

MODEL_CATEGORICAL_FEATURES = tuple(
    dict.fromkeys(
        (
            "direction",
            "trade_status",
            "confirmation_status",
            "runtime_bucket",
            "runtime_composite_observation_tier",
            "provider_health_status",
            "provider_quality_mode",
            "provider_analytics_status",
            "provider_execution_status",
            "provider_direction_trust",
            "provider_execution_trust",
            "provider_quality_action",
            "provider_execution_context",
            "data_quality_status",
            "tradable_data_status",
            "gamma_regime",
            "volatility_regime",
            "global_risk_state",
            "macro_regime",
            "spot_vs_flip",
            "wall_context_state",
            "nearest_wall_bucket",
            "historical_wall_state",
            "max_pain_zone",
            "historical_max_pain_state",
            "volume_pcr_regime",
            "pcr_bucket",
            "pcr_basis",
            "vanna_regime",
            "charm_regime",
            "ta_direction",
            "ta_regime",
            "ta_candle_status",
            "ta_candle_direction",
            "ta_candle_state",
            "ta_entry_timing_state",
            "ta_candle_late_chase",
            "ta_candle_rejection",
            "ta_candle_range_expanded",
            "statistical_directional_followthrough_prior",
            "statistical_directional_basis",
            "statistical_hold_time_hint",
            "statistical_context_bucket_state",
            "statistical_macro_directional_prior",
            "statistical_macro_shock_state",
            "historical_global_prior_direction",
            "historical_pcr_state",
            "historical_interaction_bucket_state",
            "requested_option_source",
            "option_source",
            "spot_source",
            "market_data_source_consistency",
            "market_data_provenance_status",
            "signal_quality",
            "signal_regime",
            "execution_regime",
            "final_flow_signal",
        )
    )
)

USE_COLUMNS = tuple(
    dict.fromkeys(
        (
            *BLINDSPOT_AUDIT_COLUMNS,
            *EXTRA_NUMERIC_FEATURES,
            *EXTRA_CATEGORICAL_FEATURES,
            "composite_signal_score",
            "runtime_composite_score",
            "correct_60m",
            "signed_return_60m_bps",
        )
    )
)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if pd.isna(number) or not np.isfinite(number):
        return default
    return number


def _round(value: Any, digits: int = 4) -> float | None:
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


def _mean(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.mean())


def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float | None]:
    if len(y_true) == 0:
        return {"r2": None, "mae": None}
    residual = y_true - y_pred
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    mae = float(np.mean(np.abs(residual)))
    return {"r2": _round(r2), "mae": _round(mae, 3)}


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


def load_runtime_expost_composite_relation_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset = Path(path)
    if not dataset.exists():
        raise FileNotFoundError(f"Signal dataset not found: {dataset}")
    return pd.read_csv(dataset, usecols=lambda column: column in USE_COLUMNS, low_memory=False)


def prepare_runtime_expost_composite_relation_frame(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
) -> pd.DataFrame:
    working = prepare_runtime_blindspot_feature_frame(frame, report_date=report_date)
    missing_columns = [
        column
        for column in (*EXTRA_NUMERIC_FEATURES, *EXTRA_CATEGORICAL_FEATURES)
        if column not in working.columns
    ]
    if missing_columns:
        working = pd.concat(
            [working, pd.DataFrame({column: pd.NA for column in missing_columns}, index=working.index)],
            axis=1,
        )
    for column in EXTRA_NUMERIC_FEATURES:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    for column in EXTRA_CATEGORICAL_FEATURES:
        working[column] = _normalize_text(working[column])
    working = working.copy()
    working["high_expost_score"] = (
        pd.to_numeric(working.get("composite_signal_score", pd.Series(dtype=float)), errors="coerce")
        >= DEFAULT_RESEARCH_HIGH_THRESHOLD
    )
    working["runtime_blindspot"] = (
        (working["runtime_composite_score"] < DEFAULT_RUNTIME_LOW_THRESHOLD) & working["high_expost_score"]
    )
    return working


def _comparable_frame(prepared: pd.DataFrame) -> pd.DataFrame:
    comparable = prepared.loc[prepared["has_comparable_scores"]].copy()
    comparable = comparable.loc[
        comparable["runtime_composite_score"].between(0, 100)
        & comparable["composite_signal_score"].between(0, 100)
    ].copy()
    comparable["runtime_10pt_bucket"] = pd.cut(
        comparable["runtime_composite_score"],
        bins=[-0.01, 40, 50, 60, 70, 80, 100],
        labels=["0-40", "40-50", "50-60", "60-70", "70-80", "80-100"],
        include_lowest=True,
    )
    return comparable


def _score_alignment(comparable: pd.DataFrame) -> dict[str, Any]:
    if comparable.empty:
        return {
            "pearson_correlation": None,
            "spearman_correlation": None,
            "linear_intercept": None,
            "linear_slope": None,
            "linear_r2": None,
        }
    x = comparable["runtime_composite_score"].to_numpy(dtype=float)
    y = comparable["composite_signal_score"].to_numpy(dtype=float)
    pearson = float(np.corrcoef(x, y)[0, 1]) if len(comparable) > 1 and np.std(x) > 0 and np.std(y) > 0 else None
    spearman = comparable[["runtime_composite_score", "composite_signal_score"]].corr(method="spearman").iloc[0, 1]
    slope, intercept = np.polyfit(x, y, 1)
    metrics = _regression_metrics(y, slope * x + intercept)
    return {
        "pearson_correlation": _round(pearson),
        "spearman_correlation": _round(spearman),
        "linear_intercept": _round(intercept),
        "linear_slope": _round(slope),
        "linear_r2": metrics.get("r2"),
        "linear_mae": metrics.get("mae"),
    }


def _bucket_summary(comparable: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket, group in comparable.groupby("runtime_10pt_bucket", observed=True):
        if group.empty:
            continue
        score = pd.to_numeric(group["composite_signal_score"], errors="coerce")
        correct = pd.to_numeric(group.get("correct_60m", pd.Series(index=group.index)), errors="coerce")
        signed = pd.to_numeric(group.get("signed_return_60m_bps", pd.Series(index=group.index)), errors="coerce")
        rows.append(
            {
                "runtime_bucket": str(bucket),
                "row_count": int(len(group)),
                "avg_runtime": _round(_mean(group["runtime_composite_score"]), 3),
                "avg_expost": _round(_mean(score), 3),
                "median_expost": _round(score.median(), 3),
                "p25_expost": _round(score.quantile(0.25), 3),
                "p75_expost": _round(score.quantile(0.75), 3),
                "p90_expost": _round(score.quantile(0.90), 3),
                "expost_ge80_rate": _round(float((score >= DEFAULT_RESEARCH_HIGH_THRESHOLD).mean() * 100.0), 2),
                "blindspot_rate": _round(float(group["runtime_blindspot"].mean() * 100.0), 2),
                "hit_rate_60m": _round(float(correct.mean() * 100.0), 2) if correct.notna().any() else None,
                "avg_signed_60m_bps": _round(_mean(signed), 3),
            }
        )
    return rows


def _cv_indices(frame: pd.DataFrame, *, classification_target: pd.Series | None = None):
    from sklearn.model_selection import GroupKFold, KFold, StratifiedKFold

    n_rows = len(frame)
    if n_rows < 4:
        return None, "INSUFFICIENT_ROWS"
    dates = frame.get("signal_date", pd.Series(index=frame.index, dtype=object)).fillna("UNKNOWN").astype(str)
    unique_dates = int(dates.nunique())
    if classification_target is not None:
        counts = classification_target.value_counts()
        if len(counts) < 2 or int(counts.min()) < 2:
            return None, "INSUFFICIENT_CLASS_BALANCE"
        folds = int(min(5, counts.min(), n_rows))
        if folds < 2:
            return None, "INSUFFICIENT_CLASS_BALANCE"
        return StratifiedKFold(n_splits=folds, shuffle=True, random_state=42).split(frame, classification_target), (
            f"StratifiedKFold ({folds} folds)"
        )
    if unique_dates >= 5:
        folds = min(5, unique_dates)
        return GroupKFold(n_splits=folds).split(frame, groups=dates), f"GroupKFold by date ({folds} folds)"
    folds = min(5, n_rows)
    return KFold(n_splits=folds, shuffle=True, random_state=42).split(frame), f"KFold ({folds} folds)"


def _runtime_only_model_comparison(comparable: pd.DataFrame) -> tuple[list[dict[str, Any]], str | None]:
    try:
        from sklearn.linear_model import LinearRegression
        from sklearn.model_selection import cross_val_predict
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import PolynomialFeatures
        from sklearn.tree import DecisionTreeRegressor
    except Exception as exc:  # pragma: no cover - depends on optional local research dependency.
        return [{"model": "sklearn_unavailable", "error": repr(exc)}], None

    if len(comparable) < 4:
        return [{"model": "runtime_only", "error": "INSUFFICIENT_ROWS"}], None
    x = comparable[["runtime_composite_score"]].to_numpy(dtype=float)
    y = comparable["composite_signal_score"].to_numpy(dtype=float)
    leaf = max(2, min(20, len(comparable) // 12 or 2))
    models: list[tuple[str, Any]] = [
        ("linear_runtime_only", LinearRegression()),
        ("quadratic_runtime_only", Pipeline([("poly", PolynomialFeatures(degree=2, include_bias=False)), ("lr", LinearRegression())])),
        ("cubic_runtime_only", Pipeline([("poly", PolynomialFeatures(degree=3, include_bias=False)), ("lr", LinearRegression())])),
        ("tree_depth3_runtime_only", DecisionTreeRegressor(max_depth=3, min_samples_leaf=leaf, random_state=42)),
    ]
    rows: list[dict[str, Any]] = []
    cv_desc: str | None = None
    for name, model in models:
        split, desc = _cv_indices(comparable)
        cv_desc = desc
        if split is None:
            rows.append({"model": name, "feature_set": "runtime_only", "error": desc})
            continue
        pred = cross_val_predict(model, x, y, cv=split)
        model.fit(x, y)
        fitted = model.predict(x)
        cv_metrics = _regression_metrics(y, pred)
        fit_metrics = _regression_metrics(y, fitted)
        rows.append(
            {
                "model": name,
                "feature_set": "runtime_only",
                "cv_r2": cv_metrics.get("r2"),
                "cv_mae": cv_metrics.get("mae"),
                "in_sample_r2": fit_metrics.get("r2"),
                "in_sample_mae": fit_metrics.get("mae"),
            }
        )
    return rows, cv_desc


def _available_features(frame: pd.DataFrame, features: tuple[str, ...]) -> list[str]:
    return [feature for feature in features if feature in frame.columns]


def _context_preprocessor(numeric_features: list[str], categorical_features: list[str]):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder

    return ColumnTransformer(
        [
            ("num", SimpleImputer(strategy="median"), numeric_features),
            (
                "cat",
                Pipeline(
                    [
                        ("imp", SimpleImputer(strategy="most_frequent")),
                        ("oh", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical_features,
            ),
        ],
        remainder="drop",
    )


def _context_frame(comparable: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    numeric = []
    for feature in _available_features(comparable, MODEL_NUMERIC_FEATURES):
        values = pd.to_numeric(comparable[feature], errors="coerce")
        if values.notna().any():
            numeric.append(feature)
    categorical = _available_features(comparable, MODEL_CATEGORICAL_FEATURES)
    context = comparable[numeric + categorical].copy()
    for column in numeric:
        context[column] = pd.to_numeric(context[column], errors="coerce")
    for column in categorical:
        context[column] = _normalize_text(context[column])
    return context, numeric, categorical


def _context_model_comparison(comparable: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.model_selection import cross_val_predict
        from sklearn.pipeline import Pipeline
    except Exception as exc:  # pragma: no cover - depends on optional local research dependency.
        return [{"model": "sklearn_unavailable", "error": repr(exc)}], []

    if len(comparable) < 8:
        return [{"model": "random_forest_live_context", "error": "INSUFFICIENT_ROWS"}], []
    context, numeric, categorical = _context_frame(comparable)
    if not numeric and not categorical:
        return [{"model": "random_forest_live_context", "error": "NO_LIVE_CONTEXT_FEATURES"}], []
    y = comparable["composite_signal_score"].to_numpy(dtype=float)
    leaf = max(2, min(12, len(comparable) // 25 or 2))
    model = Pipeline(
        [
            ("pre", _context_preprocessor(numeric, categorical)),
            (
                "rf",
                RandomForestRegressor(
                    n_estimators=250,
                    max_depth=5,
                    min_samples_leaf=leaf,
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    split, desc = _cv_indices(comparable)
    if split is None:
        return [{"model": "random_forest_live_context", "feature_set": "runtime_plus_live_context", "error": desc}], []
    pred = cross_val_predict(model, context, y, cv=split)
    model.fit(context, y)
    fitted = model.predict(context)
    cv_metrics = _regression_metrics(y, pred)
    fit_metrics = _regression_metrics(y, fitted)
    model_row = {
        "model": "random_forest_live_context",
        "feature_set": "runtime_plus_live_context",
        "cv_scheme": desc,
        "cv_r2": cv_metrics.get("r2"),
        "cv_mae": cv_metrics.get("mae"),
        "in_sample_r2": fit_metrics.get("r2"),
        "in_sample_mae": fit_metrics.get("mae"),
    }
    importances = _context_feature_importances(model, numeric, categorical)
    return [model_row], importances


def _context_feature_importances(model: Any, numeric: list[str], categorical: list[str]) -> list[dict[str, Any]]:
    try:
        pre = model.named_steps["pre"]
        rf = model.named_steps["rf"]
        names: list[str] = list(numeric)
        if categorical:
            oh = pre.named_transformers_["cat"].named_steps["oh"]
            names.extend([f"cat:{name}" for name in oh.get_feature_names_out(categorical)])
        rows = [
            {"feature": str(name), "importance": _round(value, 5)}
            for name, value in zip(names, rf.feature_importances_, strict=False)
        ]
    except Exception as exc:
        return [{"feature": "IMPORTANCE_UNAVAILABLE", "importance": None, "reason": repr(exc)}]
    return sorted(rows, key=lambda row: float(row.get("importance") or 0.0), reverse=True)


def _classification_comparison(comparable: pd.DataFrame) -> list[dict[str, Any]]:
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import cross_val_predict
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:  # pragma: no cover - depends on optional local research dependency.
        return [{"model": "sklearn_unavailable", "target": "expost_ge80", "error": repr(exc)}]

    target = (comparable["composite_signal_score"] >= DEFAULT_RESEARCH_HIGH_THRESHOLD).astype(int)
    split, desc = _cv_indices(comparable, classification_target=target)
    if split is None:
        return [{"model": "classification", "target": "expost_ge80", "error": desc}]

    rows: list[dict[str, Any]] = []
    runtime_x = comparable[["runtime_composite_score"]].to_numpy(dtype=float)
    runtime_model = Pipeline(
        [
            ("scale", StandardScaler()),
            ("logit", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )
    proba = cross_val_predict(runtime_model, runtime_x, target, cv=split, method="predict_proba")[:, 1]
    rows.append(
        {
            "model": "logistic_runtime_only",
            "target": "expost_ge80",
            "cv_scheme": desc,
            "cv_auc": _round(roc_auc_score(target, proba)),
            "avg_predicted_positive_rate": _round(float(proba.mean())),
        }
    )

    context, numeric, categorical = _context_frame(comparable)
    split, desc = _cv_indices(comparable, classification_target=target)
    if split is None or (not numeric and not categorical):
        rows.append({"model": "random_forest_live_context", "target": "expost_ge80", "error": desc})
        return rows
    leaf = max(2, min(10, len(comparable) // 30 or 2))
    context_model = Pipeline(
        [
            ("pre", _context_preprocessor(numeric, categorical)),
            (
                "rf",
                RandomForestClassifier(
                    n_estimators=250,
                    max_depth=5,
                    min_samples_leaf=leaf,
                    random_state=42,
                    n_jobs=-1,
                    class_weight="balanced_subsample",
                ),
            ),
        ]
    )
    proba = cross_val_predict(context_model, context, target, cv=split, method="predict_proba")[:, 1]
    rows.append(
        {
            "model": "random_forest_live_context",
            "target": "expost_ge80",
            "cv_scheme": desc,
            "cv_auc": _round(roc_auc_score(target, proba)),
            "avg_predicted_positive_rate": _round(float(proba.mean())),
        }
    )
    return rows


def _condition_slices(comparable: pd.DataFrame, *, min_rows: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    columns = [
        "confirmation_status",
        "trade_status",
        "direction",
        "gamma_regime",
        "spot_vs_flip",
        "volatility_regime",
        "provider_quality_mode",
        "provider_execution_status",
        "provider_execution_context",
        "ta_candle_state",
        "ta_entry_timing_state",
        "final_flow_signal",
        "volume_pcr_regime",
        "macro_regime",
        "global_risk_state",
        "runtime_composite_observation_tier",
    ]
    for column in columns:
        if column not in comparable.columns:
            continue
        normalized = _normalize_text(comparable[column])
        for value, index in normalized.groupby(normalized).groups.items():
            group = comparable.loc[index]
            if len(group) < min_rows:
                continue
            x = group["runtime_composite_score"].to_numpy(dtype=float)
            y = group["composite_signal_score"].to_numpy(dtype=float)
            corr = None
            if len(group) > 2 and np.std(x) > 0 and np.std(y) > 0:
                corr = float(np.corrcoef(x, y)[0, 1])
            rows.append(
                {
                    "condition_column": column,
                    "condition_value": str(value),
                    "row_count": int(len(group)),
                    "avg_runtime": _round(_mean(group["runtime_composite_score"]), 3),
                    "avg_expost": _round(_mean(group["composite_signal_score"]), 3),
                    "median_expost": _round(group["composite_signal_score"].median(), 3),
                    "expost_ge80_rate": _round(float((group["composite_signal_score"] >= DEFAULT_RESEARCH_HIGH_THRESHOLD).mean() * 100.0), 2),
                    "blindspot_rate": _round(float(group["runtime_blindspot"].mean() * 100.0), 2),
                    "runtime_expost_corr": _round(corr),
                }
            )
    return sorted(rows, key=lambda row: (-float(row.get("expost_ge80_rate") or 0.0), -int(row.get("row_count") or 0)))


def _diagnostic_read(report: dict[str, Any]) -> dict[str, Any]:
    models = report.get("model_comparison") or []
    context = next((row for row in models if row.get("model") == "random_forest_live_context"), {})
    runtime_tree = next((row for row in models if row.get("model") == "tree_depth3_runtime_only"), {})
    top_importance = (report.get("feature_importance") or [{}])[0]
    alignment = report.get("score_alignment") or {}
    return {
        "comparable_rows": (report.get("coverage") or {}).get("comparable_rows"),
        "blindspot_rows": (report.get("coverage") or {}).get("blindspot_rows"),
        "pearson_correlation": alignment.get("pearson_correlation"),
        "linear_r2": alignment.get("linear_r2"),
        "best_runtime_only_cv_r2": runtime_tree.get("cv_r2"),
        "context_cv_r2": context.get("cv_r2"),
        "context_cv_mae": context.get("cv_mae"),
        "top_context_feature": top_importance.get("feature"),
        "top_context_feature_importance": top_importance.get("importance"),
        "primary_read": _primary_read(report),
    }


def _primary_read(report: dict[str, Any]) -> str:
    alignment = report.get("score_alignment") or {}
    linear_r2 = _safe_float(alignment.get("linear_r2"), 0.0) or 0.0
    context_row = next(
        (row for row in report.get("model_comparison") or [] if row.get("model") == "random_forest_live_context"),
        {},
    )
    context_r2 = _safe_float(context_row.get("cv_r2"), None)
    if context_r2 is not None and context_r2 > linear_r2 + 0.15:
        return "CONTEXT_CONDITIONED_RELATIONSHIP"
    if linear_r2 >= 0.25:
        return "RUNTIME_SCORE_HAS_DIRECT_SIGNAL"
    return "WEAK_DIRECT_RELATIONSHIP"


def build_runtime_expost_composite_relation_report(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    research_high_threshold: float = DEFAULT_RESEARCH_HIGH_THRESHOLD,
    runtime_low_threshold: float = DEFAULT_RUNTIME_LOW_THRESHOLD,
) -> dict[str, Any]:
    prepared = prepare_runtime_expost_composite_relation_frame(frame, report_date=report_date)
    comparable = _comparable_frame(prepared)
    comparable["high_expost_score"] = comparable["composite_signal_score"] >= float(research_high_threshold)
    comparable["runtime_blindspot"] = (
        (comparable["runtime_composite_score"] < float(runtime_low_threshold)) & comparable["high_expost_score"]
    )
    runtime_models, cv_desc = _runtime_only_model_comparison(comparable)
    context_models, importances = _context_model_comparison(comparable)
    report = {
        "report_type": "runtime_expost_composite_relation",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "report_date": report_date,
            "research_high_threshold": float(research_high_threshold),
            "runtime_low_threshold": float(runtime_low_threshold),
            "target": "composite_signal_score",
            "runtime_score": "runtime_composite_score",
            "runtime_only_validation": cv_desc,
            "hindsight_guardrail": (
                "composite_signal_score is a post-evaluation label. Models in this report are "
                "research diagnostics only and must not be used as live trade scores."
            ),
            "live_context_guardrail": "Context models use live-time features only; outcome columns are excluded.",
        },
        "coverage": {
            "input_rows": int(len(frame)),
            "rows_after_date_filter": int(len(prepared)),
            "comparable_rows": int(len(comparable)),
            "blindspot_rows": int(comparable["runtime_blindspot"].sum()) if not comparable.empty else 0,
            "high_expost_rows": int(comparable["high_expost_score"].sum()) if not comparable.empty else 0,
            "start_timestamp": prepared["signal_ts"].dropna().min().isoformat()
            if prepared["signal_ts"].notna().any()
            else None,
            "end_timestamp": prepared["signal_ts"].dropna().max().isoformat()
            if prepared["signal_ts"].notna().any()
            else None,
        },
        "score_alignment": _score_alignment(comparable),
        "runtime_bucket_summary": _bucket_summary(comparable),
        "model_comparison": [*runtime_models, *context_models],
        "high_expost_classifier": _classification_comparison(comparable),
        "feature_importance": importances[:40],
        "condition_slices": _condition_slices(comparable),
    }
    report["diagnostic_read"] = _diagnostic_read(report)
    return _json_ready(report)


def _lowess_points(comparable: pd.DataFrame) -> list[tuple[float, float]]:
    ordered = comparable[["runtime_composite_score", "composite_signal_score"]].dropna().sort_values(
        "runtime_composite_score"
    )
    if len(ordered) < 8:
        return list(ordered.itertuples(index=False, name=None))
    try:
        from statsmodels.nonparametric.smoothers_lowess import lowess

        smooth = lowess(
            ordered["composite_signal_score"],
            ordered["runtime_composite_score"],
            frac=0.35,
            it=1,
            return_sorted=True,
        )
        return [(float(x), float(y)) for x, y in smooth]
    except Exception:
        rolling = ordered["composite_signal_score"].rolling(window=max(5, len(ordered) // 12), center=True).median()
        rolling = rolling.bfill().ffill()
        return list(zip(ordered["runtime_composite_score"].astype(float), rolling.astype(float), strict=False))


def render_runtime_expost_relation_svg(report: dict[str, Any], comparable: pd.DataFrame) -> str:
    width, height = 1120, 760
    left, right, top, bottom = 90, 46, 84, 92
    plot_width, plot_height = width - left - right, height - top - bottom
    if comparable.empty:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
            '<rect width="100%" height="100%" fill="white"/>'
            '<text x="40" y="60" font-family="Arial" font-size="20">No comparable rows available.</text>'
            "</svg>"
        )
    xmin = max(0.0, math.floor(float(comparable["runtime_composite_score"].min()) / 5.0) * 5.0 - 5.0)
    xmax = min(100.0, max(85.0, math.ceil(float(comparable["runtime_composite_score"].max()) / 5.0) * 5.0 + 5.0))
    ymin, ymax = 0.0, 100.0

    def sx(value: float) -> float:
        return left + (float(value) - xmin) / (xmax - xmin) * plot_width

    def sy(value: float) -> float:
        return height - bottom - (float(value) - ymin) / (ymax - ymin) * plot_height

    rng = np.random.default_rng(17)
    x = comparable["runtime_composite_score"].to_numpy(dtype=float) + rng.normal(0, 0.35, len(comparable))
    y = comparable["composite_signal_score"].to_numpy(dtype=float) + rng.normal(0, 0.35, len(comparable))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        "<style>text{font-family:Arial,Helvetica,sans-serif}.title{font-size:24px;font-weight:700;fill:#0f172a}.label{font-size:15px;fill:#334155}.tick{font-size:12px;fill:#64748b}.note{font-size:14px;fill:#0f172a}</style>",
        f'<text x="{width/2}" y="38" text-anchor="middle" class="title">Runtime vs Ex-Post Composite: Nonlinear Diagnostic</text>',
        f'<text x="{width/2}" y="62" text-anchor="middle" class="label">Scatter, LOWESS smooth, and bucket median/IQR</text>',
    ]
    for tick in range(0, 101, 10):
        ypx = sy(tick)
        parts.append(f'<line x1="{left}" y1="{ypx:.1f}" x2="{width-right}" y2="{ypx:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{left-12}" y="{ypx+4:.1f}" text-anchor="end" class="tick">{tick}</text>')
    for tick in range(int(math.ceil(xmin / 10.0) * 10), int(xmax) + 1, 10):
        xpx = sx(tick)
        parts.append(f'<line x1="{xpx:.1f}" y1="{top}" x2="{xpx:.1f}" y2="{height-bottom}" stroke="#f1f5f9"/>')
        parts.append(f'<text x="{xpx:.1f}" y="{height-bottom+22}" text-anchor="middle" class="tick">{tick}</text>')
    parts.append(f'<rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" fill="none" stroke="#0f172a"/>')
    parts.append(
        f'<line x1="{left}" y1="{sy(DEFAULT_RESEARCH_HIGH_THRESHOLD):.1f}" x2="{width-right}" '
        f'y2="{sy(DEFAULT_RESEARCH_HIGH_THRESHOLD):.1f}" stroke="#16a34a" stroke-width="2" stroke-dasharray="8 6" opacity="0.7"/>'
    )
    if xmin <= DEFAULT_RUNTIME_LOW_THRESHOLD <= xmax:
        parts.append(
            f'<line x1="{sx(DEFAULT_RUNTIME_LOW_THRESHOLD):.1f}" y1="{top}" x2="{sx(DEFAULT_RUNTIME_LOW_THRESHOLD):.1f}" '
            f'y2="{height-bottom}" stroke="#f59e0b" stroke-width="2" stroke-dasharray="8 6" opacity="0.7"/>'
        )
    for xi, yi in zip(x, y, strict=False):
        if xmin <= xi <= xmax and ymin <= yi <= ymax:
            color = "#16a34a" if yi >= DEFAULT_RESEARCH_HIGH_THRESHOLD else "#2563eb"
            parts.append(f'<circle cx="{sx(xi):.1f}" cy="{sy(yi):.1f}" r="3" fill="{color}" opacity="0.30"/>')
    lowess = _lowess_points(comparable)
    if lowess:
        lowess_points = " ".join(
            f"{sx(a):.1f},{sy(b):.1f}" for a, b in lowess if xmin <= a <= xmax and ymin <= b <= ymax
        )
        parts.append(f'<polyline points="{lowess_points}" fill="none" stroke="#dc2626" stroke-width="3.2" opacity="0.95"/>')
    for row in report.get("runtime_bucket_summary") or []:
        label = str(row.get("runtime_bucket") or "")
        if "-" not in label:
            continue
        lo, hi = label.split("-", maxsplit=1)
        try:
            center = (float(lo) + float(hi)) / 2.0
        except ValueError:
            continue
        if not (xmin <= center <= xmax):
            continue
        xpx = sx(center)
        p25 = _safe_float(row.get("p25_expost"))
        p75 = _safe_float(row.get("p75_expost"))
        median = _safe_float(row.get("median_expost"))
        if p25 is not None and p75 is not None:
            parts.append(
                f'<line x1="{xpx:.1f}" y1="{sy(p25):.1f}" x2="{xpx:.1f}" y2="{sy(p75):.1f}" '
                'stroke="#111827" stroke-width="2.6" opacity="0.75"/>'
            )
        if median is not None:
            parts.append(f'<circle cx="{xpx:.1f}" cy="{sy(median):.1f}" r="6" fill="#111827" opacity="0.9"/>')
        parts.append(f'<text x="{xpx:.1f}" y="{height-bottom+42}" text-anchor="middle" class="tick">n={row.get("row_count")}</text>')
    read = report.get("diagnostic_read") or {}
    panel_x, panel_y, panel_w, panel_h = left + 18, top + 18, 435, 144
    parts.append(
        f'<rect x="{panel_x}" y="{panel_y}" width="{panel_w}" height="{panel_h}" rx="6" fill="#ffffff" stroke="#cbd5e1" opacity="0.94"/>'
    )
    stat_lines = [
        f"n = {read.get('comparable_rows')} comparable rows",
        f"Pearson = {read.get('pearson_correlation')}; linear R2 = {read.get('linear_r2')}",
        f"Context CV R2 = {read.get('context_cv_r2')}; MAE = {read.get('context_cv_mae')}",
        f"Blindspots = {read.get('blindspot_rows')}",
        "Black dots = bucket median; vertical bars = IQR",
    ]
    for i, line in enumerate(stat_lines):
        parts.append(f'<text x="{panel_x+14}" y="{panel_y+24+i*22}" class="note">{line}</text>')
    parts.append(f'<text x="{width/2}" y="{height-28}" text-anchor="middle" class="label">Runtime Composite Score</text>')
    parts.append(
        f'<text x="24" y="{height/2}" transform="rotate(-90 24 {height/2})" text-anchor="middle" class="label">Ex-Post Composite Score</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def render_runtime_expost_composite_relation_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    alignment = report.get("score_alignment") or {}
    read = report.get("diagnostic_read") or {}
    lines = [
        "# Runtime vs Ex-Post Composite Relation",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only report studies whether live-time runtime composite explains the "
        "post-evaluation composite label. The ex-post composite is never a live input; it is "
        "used here only to discover missing live-time context.",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Rows after date filter: `{coverage.get('rows_after_date_filter')}`",
        f"- Comparable rows: `{coverage.get('comparable_rows')}`",
        f"- High ex-post rows: `{coverage.get('high_expost_rows')}`",
        f"- Runtime blindspot rows: `{coverage.get('blindspot_rows')}`",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Primary read: `{read.get('primary_read')}`",
        f"- Pearson correlation: `{alignment.get('pearson_correlation')}`",
        f"- Spearman correlation: `{alignment.get('spearman_correlation')}`",
        f"- Linear fit: `ex_post = {alignment.get('linear_intercept')} + {alignment.get('linear_slope')} * runtime`",
        f"- Linear R2: `{alignment.get('linear_r2')}`",
        f"- Best runtime-only tree CV R2: `{read.get('best_runtime_only_cv_r2')}`",
        f"- Context model CV R2: `{read.get('context_cv_r2')}`",
        f"- Context model CV MAE: `{read.get('context_cv_mae')}`",
        f"- Top context feature: `{read.get('top_context_feature')}`",
        "",
        "## Runtime Bucket Summary",
        "",
    ]
    lines.extend(
        _markdown_table(
            report.get("runtime_bucket_summary") or [],
            [
                "runtime_bucket",
                "row_count",
                "avg_runtime",
                "avg_expost",
                "median_expost",
                "p25_expost",
                "p75_expost",
                "p90_expost",
                "expost_ge80_rate",
                "blindspot_rate",
                "hit_rate_60m",
                "avg_signed_60m_bps",
            ],
        )
    )
    lines.extend(["", "## Model Comparison", ""])
    lines.extend(
        _markdown_table(
            report.get("model_comparison") or [],
            ["model", "feature_set", "cv_scheme", "cv_r2", "cv_mae", "in_sample_r2", "in_sample_mae", "error"],
        )
    )
    lines.extend(["", "## High Ex-Post Classifier", ""])
    lines.extend(
        _markdown_table(
            report.get("high_expost_classifier") or [],
            ["model", "target", "cv_scheme", "cv_auc", "avg_predicted_positive_rate", "error"],
        )
    )
    lines.extend(["", "## Top Context Features", ""])
    lines.extend(_markdown_table(report.get("feature_importance") or [], ["feature", "importance", "reason"], max_rows=25))
    lines.extend(["", "## Highest Ex-Post Conditional Slices", ""])
    lines.extend(
        _markdown_table(
            report.get("condition_slices") or [],
            [
                "condition_column",
                "condition_value",
                "row_count",
                "avg_runtime",
                "avg_expost",
                "median_expost",
                "expost_ge80_rate",
                "blindspot_rate",
                "runtime_expost_corr",
            ],
            max_rows=30,
        )
    )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This report does not change runtime behavior.",
            "- Do not print a live predicted ex-post score from this model yet.",
            "- Use the output to design a forward-tested blindspot-risk diagnostic.",
            "- Promote only after fresh-forward validation proves helped/hurt stability.",
            "",
        ]
    )
    return "\n".join(lines)


def write_runtime_expost_composite_relation_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_EXPOST_COMPOSITE_RELATION_REPORT_DIR,
    report_date: str | None = None,
    research_high_threshold: float = DEFAULT_RESEARCH_HIGH_THRESHOLD,
    runtime_low_threshold: float = DEFAULT_RUNTIME_LOW_THRESHOLD,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = load_runtime_expost_composite_relation_dataset(dataset)
    prepared = prepare_runtime_expost_composite_relation_frame(frame, report_date=report_date)
    comparable = _comparable_frame(prepared)
    comparable["high_expost_score"] = comparable["composite_signal_score"] >= float(research_high_threshold)
    comparable["runtime_blindspot"] = (
        (comparable["runtime_composite_score"] < float(runtime_low_threshold)) & comparable["high_expost_score"]
    )
    report = build_runtime_expost_composite_relation_report(
        frame,
        report_date=report_date,
        research_high_threshold=research_high_threshold,
        runtime_low_threshold=runtime_low_threshold,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    json_path = output / f"runtime_expost_composite_relation_{timestamp}.json"
    markdown_path = output / f"runtime_expost_composite_relation_{timestamp}.md"
    svg_path = output / f"runtime_expost_composite_relation_{timestamp}.svg"
    latest_json_path = output / "latest_runtime_expost_composite_relation.json"
    latest_markdown_path = output / "latest_runtime_expost_composite_relation.md"
    latest_svg_path = output / "latest_runtime_expost_composite_relation.svg"
    bucket_csv_path = output / f"runtime_expost_composite_relation_{timestamp}_buckets.csv"
    latest_bucket_csv_path = output / "latest_runtime_expost_composite_relation_buckets.csv"
    model_csv_path = output / f"runtime_expost_composite_relation_{timestamp}_models.csv"
    latest_model_csv_path = output / "latest_runtime_expost_composite_relation_models.csv"
    feature_csv_path = output / f"runtime_expost_composite_relation_{timestamp}_features.csv"
    latest_feature_csv_path = output / "latest_runtime_expost_composite_relation_features.csv"
    slices_csv_path = output / f"runtime_expost_composite_relation_{timestamp}_slices.csv"
    latest_slices_csv_path = output / "latest_runtime_expost_composite_relation_slices.csv"

    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_runtime_expost_composite_relation_markdown(report)
    svg_text = render_runtime_expost_relation_svg(report, comparable)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")
    svg_path.write_text(svg_text, encoding="utf-8")
    latest_svg_path.write_text(svg_text, encoding="utf-8")
    pd.DataFrame(report.get("runtime_bucket_summary") or []).to_csv(bucket_csv_path, index=False)
    pd.DataFrame(report.get("runtime_bucket_summary") or []).to_csv(latest_bucket_csv_path, index=False)
    pd.DataFrame(report.get("model_comparison") or []).to_csv(model_csv_path, index=False)
    pd.DataFrame(report.get("model_comparison") or []).to_csv(latest_model_csv_path, index=False)
    pd.DataFrame(report.get("feature_importance") or []).to_csv(feature_csv_path, index=False)
    pd.DataFrame(report.get("feature_importance") or []).to_csv(latest_feature_csv_path, index=False)
    pd.DataFrame(report.get("condition_slices") or []).to_csv(slices_csv_path, index=False)
    pd.DataFrame(report.get("condition_slices") or []).to_csv(latest_slices_csv_path, index=False)
    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="runtime_expost_composite_relation",
        report_date=report_date,
        mode="research",
        run_evaluation=False,
        narrative=False,
    )
    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "svg_path": str(svg_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
        "latest_svg_path": str(latest_svg_path),
        "bucket_csv_path": str(bucket_csv_path),
        "latest_bucket_csv_path": str(latest_bucket_csv_path),
        "model_csv_path": str(model_csv_path),
        "latest_model_csv_path": str(latest_model_csv_path),
        "feature_csv_path": str(feature_csv_path),
        "latest_feature_csv_path": str(latest_feature_csv_path),
        "slices_csv_path": str(slices_csv_path),
        "latest_slices_csv_path": str(latest_slices_csv_path),
        "manifest_path": str(manifest_path),
    }

"""Research-only audit of live-time features behind runtime blindspots.

The audit starts from the runtime-vs-research composite gap: rows where the
post-evaluation research score is high, but the live runtime score was low.
The post-evaluation score is used only to define the blindspot cohort.  The
feature comparisons intentionally use live-time fields so candidate fixes can
be tested without hindsight leakage.
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
from research.signal_evaluation.runtime_research_composite_gap import (
    DEFAULT_RESEARCH_HIGH_THRESHOLD,
    DEFAULT_RUNTIME_LOW_THRESHOLD,
    prepare_runtime_research_composite_frame,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_BLINDSPOT_FEATURE_AUDIT_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "runtime_blindspot_feature_audit"
)

CORE_COLUMNS = (
    "signal_timestamp",
    "direction",
    "runtime_composite_score",
    "composite_signal_score",
    "outcome_status",
    "label_quality_status",
    "analytics_usable",
    "execution_suggestion_usable",
    "signed_return_60m_bps",
    "mfe_60m_bps",
    "mae_60m_bps",
    "correct_60m",
)

LIVE_NUMERIC_FEATURES = (
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
    "selected_option_ba_spread_pct",
    "selected_option_iv",
    "selected_option_delta",
    "selected_option_gamma",
    "selected_option_theta",
    "selected_option_vega",
    "selected_option_volume",
    "selected_option_open_interest",
    "option_premium_pct_of_spot",
    "expected_move_pct",
    "lookback_avg_range_pct",
    "open_interest_pcr",
    "volume_pcr",
    "volume_pcr_atm",
    "pcr_value",
    "global_risk_score",
    "oil_shock_score",
    "commodity_risk_score",
    "volatility_shock_score",
    "volatility_explosion_probability",
    "overnight_gap_risk_score",
    "volatility_expansion_risk_score",
    "global_risk_adjustment_score",
    "gamma_vol_acceleration_score",
    "gamma_vol_adjustment_score",
    "dealer_hedging_pressure_score",
    "dealer_pressure_adjustment_score",
    "pinning_pressure_score",
    "option_efficiency_adjustment_score",
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
)

LIVE_CATEGORICAL_FEATURES = (
    "trade_status",
    "runtime_bucket",
    "runtime_composite_observation_tier",
    "provider_health_status",
    "provider_quality_mode",
    "provider_analytics_status",
    "provider_execution_status",
    "provider_direction_trust",
    "provider_execution_trust",
    "provider_quality_action",
    "data_quality_status",
    "provider_health_pricing",
    "provider_health_iv",
    "tradable_data_status",
    "provider_execution_context",
    "confirmation_status",
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
    "option_premium_path_status",
    "statistical_directional_followthrough_prior",
    "statistical_directional_basis",
    "statistical_hold_time_hint",
    "statistical_context_bucket_state",
    "statistical_macro_directional_prior",
    "statistical_macro_shock_state",
    "historical_global_prior_direction",
    "historical_pcr_state",
    "historical_interaction_bucket_state",
)

USE_COLUMNS = tuple(dict.fromkeys((*CORE_COLUMNS, *LIVE_NUMERIC_FEATURES, *LIVE_CATEGORICAL_FEATURES)))

FEATURE_FAMILIES = {
    "trade_strength": "runtime_score",
    "move_probability": "runtime_score",
    "hybrid_move_probability": "runtime_score",
    "rule_move_probability": "runtime_score",
    "ml_move_probability": "runtime_score",
    "signal_confidence_score": "runtime_score",
    "runtime_bucket": "runtime_score",
    "runtime_composite_observation_tier": "runtime_score",
    "target_reachability_score": "option_tradeability",
    "premium_efficiency_score": "option_tradeability",
    "strike_efficiency_score": "option_tradeability",
    "option_efficiency_score": "option_tradeability",
    "selected_option_ba_spread_pct": "option_tradeability",
    "selected_option_iv": "option_tradeability",
    "selected_option_delta": "option_tradeability",
    "selected_option_gamma": "option_tradeability",
    "selected_option_theta": "option_tradeability",
    "selected_option_vega": "option_tradeability",
    "selected_option_volume": "option_tradeability",
    "selected_option_open_interest": "option_tradeability",
    "option_premium_pct_of_spot": "option_tradeability",
    "option_premium_path_status": "option_tradeability",
    "expected_move_pct": "range_context",
    "lookback_avg_range_pct": "range_context",
    "provider_health_status": "provider_quality",
    "provider_quality_mode": "provider_quality",
    "provider_analytics_status": "provider_quality",
    "provider_execution_status": "provider_quality",
    "provider_direction_trust": "provider_quality",
    "provider_execution_trust": "provider_quality",
    "provider_quality_action": "provider_quality",
    "data_quality_status": "provider_quality",
    "provider_health_pricing": "provider_quality",
    "provider_health_iv": "provider_quality",
    "tradable_data_status": "provider_quality",
    "provider_execution_context": "provider_quality",
    "gamma_regime": "regime_context",
    "volatility_regime": "regime_context",
    "global_risk_state": "regime_context",
    "macro_regime": "regime_context",
    "global_risk_score": "regime_context",
    "oil_shock_score": "regime_context",
    "commodity_risk_score": "regime_context",
    "volatility_shock_score": "regime_context",
    "volatility_explosion_probability": "regime_context",
    "gamma_vol_acceleration_score": "regime_context",
    "gamma_vol_adjustment_score": "regime_context",
    "dealer_hedging_pressure_score": "dealer_flow",
    "dealer_pressure_adjustment_score": "dealer_flow",
    "pinning_pressure_score": "dealer_flow",
    "vanna_regime": "dealer_flow",
    "charm_regime": "dealer_flow",
    "spot_vs_flip": "level_context",
    "wall_context_state": "level_context",
    "nearest_wall_bucket": "level_context",
    "historical_wall_state": "level_context",
    "support_wall_distance_pct": "level_context",
    "resistance_wall_distance_pct": "level_context",
    "max_pain_distance_pct": "level_context",
    "gamma_flip_distance_pct": "level_context",
    "nearest_wall_distance_pct": "level_context",
    "max_pain_zone": "level_context",
    "historical_max_pain_state": "level_context",
    "historical_expected_range_bps": "historical_statistical_context",
    "historical_expected_abs_move_bps": "historical_statistical_context",
    "historical_range_multiplier": "historical_statistical_context",
    "historical_global_prior_score": "historical_statistical_context",
    "historical_global_prior_direction": "historical_statistical_context",
    "historical_context_score_adjustment": "historical_statistical_context",
    "historical_context_probability_adjustment": "historical_statistical_context",
    "historical_interaction_score_adjustment": "historical_statistical_context",
    "historical_interaction_probability_adjustment": "historical_statistical_context",
    "historical_interaction_bucket_state": "historical_statistical_context",
    "statistical_vol_stress_score": "historical_statistical_context",
    "statistical_expected_range_bps": "historical_statistical_context",
    "statistical_expected_abs_move_bps": "historical_statistical_context",
    "statistical_regime_confidence": "historical_statistical_context",
    "statistical_context_score_adjustment": "historical_statistical_context",
    "statistical_context_probability_adjustment": "historical_statistical_context",
    "statistical_macro_score_adjustment": "historical_statistical_context",
    "statistical_macro_probability_adjustment": "historical_statistical_context",
    "statistical_directional_followthrough_prior": "historical_statistical_context",
    "statistical_directional_basis": "historical_statistical_context",
    "statistical_hold_time_hint": "historical_statistical_context",
    "statistical_context_bucket_state": "historical_statistical_context",
    "statistical_macro_directional_prior": "historical_statistical_context",
    "statistical_macro_shock_state": "historical_statistical_context",
    "confirmation_status": "confirmation_timing",
    "ta_direction": "confirmation_timing",
    "ta_regime": "confirmation_timing",
    "ta_confidence": "confirmation_timing",
    "ta_candle_status": "confirmation_timing",
    "ta_candle_direction": "confirmation_timing",
    "ta_candle_state": "confirmation_timing",
    "ta_entry_timing_state": "confirmation_timing",
    "ta_candle_late_chase": "confirmation_timing",
    "ta_candle_rejection": "confirmation_timing",
    "ta_candle_range_expanded": "confirmation_timing",
    "ta_candle_body_bps": "confirmation_timing",
    "ta_candle_range_bps": "confirmation_timing",
    "ta_candle_close_location": "confirmation_timing",
    "ta_candle_upper_wick_share": "confirmation_timing",
    "ta_candle_lower_wick_share": "confirmation_timing",
    "ta_candle_range_expansion_ratio": "confirmation_timing",
    "ta_candle_momentum_3_bps": "confirmation_timing",
    "ta_candle_momentum_5_bps": "confirmation_timing",
    "ta_candle_prior_move_15m_bps": "confirmation_timing",
    "ta_candle_prior_move_30m_bps": "confirmation_timing",
    "ta_candle_confidence": "confirmation_timing",
    "ta_entry_timing_score": "confirmation_timing",
    "open_interest_pcr": "pcr_context",
    "volume_pcr": "pcr_context",
    "volume_pcr_atm": "pcr_context",
    "pcr_value": "pcr_context",
    "volume_pcr_regime": "pcr_context",
    "pcr_bucket": "pcr_context",
    "pcr_basis": "pcr_context",
    "historical_pcr_state": "pcr_context",
}


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


def _family_for(feature: str) -> str:
    return FEATURE_FAMILIES.get(feature, "other_live_feature")


def load_runtime_blindspot_feature_audit_dataset(path: str | Path = CUMULATIVE_DATASET_PATH) -> pd.DataFrame:
    dataset = Path(path)
    if not dataset.exists():
        raise FileNotFoundError(f"Signal dataset not found: {dataset}")
    return pd.read_csv(dataset, usecols=lambda column: column in USE_COLUMNS, low_memory=False)


def prepare_runtime_blindspot_feature_frame(frame: pd.DataFrame, *, report_date: str | None = None) -> pd.DataFrame:
    working = prepare_runtime_research_composite_frame(frame, report_date=report_date)
    missing_columns = [
        column
        for column in (*LIVE_NUMERIC_FEATURES, *LIVE_CATEGORICAL_FEATURES)
        if column not in working.columns
    ]
    if missing_columns:
        working = pd.concat(
            [working, pd.DataFrame({column: pd.NA for column in missing_columns}, index=working.index)],
            axis=1,
        )
    for column in LIVE_NUMERIC_FEATURES:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    for column in LIVE_CATEGORICAL_FEATURES:
        working[column] = _normalize_text(working[column])

    analytics_usable = _truthy_series(working.get("analytics_usable", pd.Series(index=working.index)))
    execution_usable = _truthy_series(working.get("execution_suggestion_usable", pd.Series(index=working.index)))
    working["provider_execution_context"] = np.select(
        [
            analytics_usable & execution_usable,
            analytics_usable & ~execution_usable,
            ~analytics_usable & execution_usable,
        ],
        ["ANALYTICS_AND_EXECUTION_USABLE", "ANALYTICS_ONLY_EXECUTION_BLOCKED", "EXECUTION_ONLY_ANALYTICS_BLOCKED"],
        default="NOT_USABLE",
    )
    return working


def _outcome_summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "row_count": 0,
            "complete_outcome_share": None,
            "partial_outcome_share": None,
            "hit_rate_60m": None,
            "avg_signed_return_60m_bps": None,
            "mfe_mae_ratio_60m": None,
        }
    outcome = frame.get("outcome_status", pd.Series(dtype=object)).astype(str).str.upper()
    return {
        "row_count": int(len(frame)),
        "complete_outcome_share": _round(_share(outcome.eq("COMPLETE"))),
        "partial_outcome_share": _round(_share(outcome.eq("PARTIAL"))),
        "hit_rate_60m": _round(_mean(frame.get("correct_60m", pd.Series(dtype=float))) * 100.0)
        if _mean(frame.get("correct_60m", pd.Series(dtype=float))) is not None
        else None,
        "avg_signed_return_60m_bps": _round(_mean(frame.get("signed_return_60m_bps", pd.Series(dtype=float)))),
        "mfe_mae_ratio_60m": _round(_mfe_mae_ratio(frame), 3),
    }


def _numeric_feature_rows(blindspot: pd.DataFrame, baseline: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in LIVE_NUMERIC_FEATURES:
        if feature not in blindspot.columns or feature not in baseline.columns:
            continue
        blind = pd.to_numeric(blindspot[feature], errors="coerce")
        base = pd.to_numeric(baseline[feature], errors="coerce")
        blind_valid = blind.dropna()
        base_valid = base.dropna()
        if blind_valid.empty or base_valid.empty:
            continue
        blind_mean = float(blind_valid.mean())
        base_mean = float(base_valid.mean())
        delta = blind_mean - base_mean
        pooled_std = float(np.sqrt((blind_valid.std(ddof=0) ** 2 + base_valid.std(ddof=0) ** 2) / 2.0))
        standardized_delta = delta / pooled_std if pooled_std > 0 else None
        blind_missing = float(blind.isna().mean() * 100.0)
        base_missing = float(base.isna().mean() * 100.0)
        coverage_factor = max(0.0, 1.0 - blind_missing / 100.0)
        rank_score = abs(standardized_delta or 0.0) * coverage_factor
        rows.append(
            {
                "feature": feature,
                "feature_type": "numeric",
                "family": _family_for(feature),
                "rank_score": _round(rank_score, 4),
                "blindspot_mean": _round(blind_mean, 4),
                "baseline_mean": _round(base_mean, 4),
                "delta": _round(delta, 4),
                "standardized_delta": _round(standardized_delta, 4),
                "blindspot_missing_share": _round(blind_missing),
                "baseline_missing_share": _round(base_missing),
                "blindspot_n": int(blind_valid.count()),
                "baseline_n": int(base_valid.count()),
                "clue": "higher_in_blindspots" if delta > 0 else "lower_in_blindspots",
            }
        )
    return sorted(rows, key=lambda row: float(row.get("rank_score") or 0.0), reverse=True)


def _categorical_feature_rows(blindspot: pd.DataFrame, baseline: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in LIVE_CATEGORICAL_FEATURES:
        if feature not in blindspot.columns or feature not in baseline.columns:
            continue
        blind = _normalize_text(blindspot[feature])
        base = _normalize_text(baseline[feature])
        if blind.empty or base.empty:
            continue
        blind_counts = blind.value_counts(dropna=False)
        base_counts = base.value_counts(dropna=False)
        values = sorted(set(blind_counts.index).union(set(base_counts.index)))
        best_value = None
        best_delta = None
        best_blind_share = None
        best_base_share = None
        for value in values:
            blind_share = float(blind_counts.get(value, 0) / max(len(blind), 1) * 100.0)
            base_share = float(base_counts.get(value, 0) / max(len(base), 1) * 100.0)
            delta = blind_share - base_share
            if best_delta is None or abs(delta) > abs(best_delta):
                best_value = value
                best_delta = delta
                best_blind_share = blind_share
                best_base_share = base_share
        if best_value is None or best_delta is None:
            continue
        rows.append(
            {
                "feature": feature,
                "feature_type": "categorical",
                "family": _family_for(feature),
                "rank_score": _round(abs(best_delta), 4),
                "dominant_blindspot_value": str(blind_counts.index[0]) if not blind_counts.empty else None,
                "dominant_blindspot_share": _round(float(blind_counts.iloc[0] / max(len(blind), 1) * 100.0))
                if not blind_counts.empty
                else None,
                "largest_share_delta_value": str(best_value),
                "blindspot_share": _round(best_blind_share),
                "baseline_share": _round(best_base_share),
                "share_delta": _round(best_delta),
                "blindspot_unique_values": int(blind.nunique(dropna=False)),
                "baseline_unique_values": int(base.nunique(dropna=False)),
                "clue": "overrepresented_in_blindspots" if best_delta > 0 else "underrepresented_in_blindspots",
            }
        )
    return sorted(rows, key=lambda row: float(row.get("rank_score") or 0.0), reverse=True)


def _ranked_live_feature_candidates(
    numeric_rows: list[dict[str, Any]],
    categorical_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for row in numeric_rows:
        rows.append(
            {
                "feature": row.get("feature"),
                "feature_type": row.get("feature_type"),
                "family": row.get("family"),
                "rank_score": row.get("rank_score"),
                "clue": row.get("clue"),
                "detail": f"delta={row.get('delta')}, std_delta={row.get('standardized_delta')}",
            }
        )
    for row in categorical_rows:
        rows.append(
            {
                "feature": row.get("feature"),
                "feature_type": row.get("feature_type"),
                "family": row.get("family"),
                "rank_score": row.get("rank_score"),
                "clue": row.get("clue"),
                "detail": (
                    f"{row.get('largest_share_delta_value')}: blindspot={row.get('blindspot_share')}%, "
                    f"baseline={row.get('baseline_share')}%"
                ),
            }
        )
    return sorted(rows, key=lambda row: float(row.get("rank_score") or 0.0), reverse=True)


def _family_summary(ranked_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not ranked_rows:
        return []
    frame = pd.DataFrame(ranked_rows)
    rows = []
    for family, group in frame.groupby("family", dropna=False):
        scores = pd.to_numeric(group["rank_score"], errors="coerce").dropna().sort_values(ascending=False)
        top = group.sort_values("rank_score", ascending=False).head(3)
        rows.append(
            {
                "family": str(family),
                "feature_count": int(len(group)),
                "top_score": _round(scores.max() if not scores.empty else None, 4),
                "avg_top3_score": _round(scores.head(3).mean() if not scores.empty else None, 4),
                "top_features": ", ".join(str(value) for value in top["feature"].tolist()),
            }
        )
    return sorted(rows, key=lambda row: float(row.get("avg_top3_score") or 0.0), reverse=True)


def _recommended_actions(report: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    family_rows = report.get("family_summary") or []
    top_families = [str(row.get("family")) for row in family_rows[:3]]
    if "confirmation_timing" in top_families:
        actions.append("Test candle/lifecycle timing proxies as a runtime score supplement, not as direct trade triggers.")
    if "level_context" in top_families:
        actions.append("Replay wall distance, wall rejection, and retest context inside the runtime blindspot cohort.")
    if "provider_quality" in top_families:
        actions.append("Separate analytics conviction from execution usability before suppressing runtime score too aggressively.")
    if "regime_context" in top_families:
        actions.append("Check whether the blindspot is regime-specific before changing global thresholds.")
    if "option_tradeability" in top_families:
        actions.append("Audit option premium/efficiency fields as possible live-time path-quality proxies.")
    if "historical_statistical_context" in top_families:
        actions.append("Compare historical/statistical context adjustments against blindspot rows before changing runtime score weights.")
    if "range_context" in top_families:
        actions.append("Check whether expected-move/range context is underweighted in low runtime-score blindspots.")
    if not actions:
        actions.append("Collect another full session and rerun before proposing a live-time feature change.")
    actions.append("Do not use post-evaluation composite score directly in runtime logic; it is only the audit label.")
    return actions


def _diagnostic_read(report: dict[str, Any]) -> dict[str, Any]:
    ranked = report.get("ranked_live_feature_candidates") or []
    families = report.get("family_summary") or []
    return {
        "blindspot_rows": (report.get("coverage") or {}).get("blindspot_rows"),
        "baseline_rows": (report.get("coverage") or {}).get("baseline_rows"),
        "top_feature": ranked[0].get("feature") if ranked else None,
        "top_feature_family": ranked[0].get("family") if ranked else None,
        "top_feature_detail": ranked[0].get("detail") if ranked else None,
        "top_family": families[0].get("family") if families else None,
        "top_family_features": families[0].get("top_features") if families else None,
    }


def build_runtime_blindspot_feature_audit_report(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    research_high_threshold: float = DEFAULT_RESEARCH_HIGH_THRESHOLD,
    runtime_low_threshold: float = DEFAULT_RUNTIME_LOW_THRESHOLD,
) -> dict[str, Any]:
    prepared = prepare_runtime_blindspot_feature_frame(frame, report_date=report_date)
    comparable = prepared.loc[prepared["has_comparable_scores"]].copy()
    blindspot = comparable.loc[
        (comparable["composite_signal_score"] >= float(research_high_threshold))
        & (comparable["runtime_composite_score"] < float(runtime_low_threshold))
    ].copy()
    baseline = comparable.loc[~comparable.index.isin(blindspot.index)].copy()
    if baseline.empty:
        baseline = comparable.copy()

    numeric_rows = _numeric_feature_rows(blindspot, baseline)
    categorical_rows = _categorical_feature_rows(blindspot, baseline)
    ranked_rows = _ranked_live_feature_candidates(numeric_rows, categorical_rows)
    report = {
        "report_type": "runtime_blindspot_feature_audit",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "report_date": report_date,
            "research_high_threshold": float(research_high_threshold),
            "runtime_low_threshold": float(runtime_low_threshold),
            "blindspot_definition": (
                "composite_signal_score >= research_high_threshold and "
                "runtime_composite_score < runtime_low_threshold"
            ),
            "hindsight_guardrail": (
                "composite_signal_score is used only to identify the audit cohort; "
                "ranked features are live-time fields"
            ),
        },
        "coverage": {
            "input_rows": int(len(frame)),
            "rows_after_date_filter": int(len(prepared)),
            "comparable_rows": int(len(comparable)),
            "blindspot_rows": int(len(blindspot)),
            "baseline_rows": int(len(baseline)),
            "start_timestamp": prepared["signal_ts"].dropna().min().isoformat()
            if prepared["signal_ts"].notna().any()
            else None,
            "end_timestamp": prepared["signal_ts"].dropna().max().isoformat()
            if prepared["signal_ts"].notna().any()
            else None,
        },
        "outcome_summary": {
            "blindspot": _outcome_summary(blindspot),
            "baseline": _outcome_summary(baseline),
        },
        "ranked_live_feature_candidates": ranked_rows[:40],
        "family_summary": _family_summary(ranked_rows),
        "numeric_feature_audit": numeric_rows,
        "categorical_feature_audit": categorical_rows,
    }
    report["diagnostic_read"] = _diagnostic_read(report)
    report["recommended_actions"] = _recommended_actions(report)
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


def render_runtime_blindspot_feature_audit_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    outcome = report.get("outcome_summary") or {}
    blind_outcome = outcome.get("blindspot") or {}
    base_outcome = outcome.get("baseline") or {}
    lines = [
        "# Runtime Blindspot Feature Audit",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Method",
        "",
        "This research-only report uses high post-evaluation `composite_signal_score` "
        "only to define runtime blindspots. The ranked comparisons below use live-time "
        "features and should be treated as candidate explanations, not live rules.",
        "",
        "## Coverage",
        "",
        f"- Input rows: `{coverage.get('input_rows')}`",
        f"- Rows after date filter: `{coverage.get('rows_after_date_filter')}`",
        f"- Comparable rows: `{coverage.get('comparable_rows')}`",
        f"- Runtime blindspot rows: `{coverage.get('blindspot_rows')}`",
        f"- Baseline rows: `{coverage.get('baseline_rows')}`",
        f"- Time range: `{coverage.get('start_timestamp')}` to `{coverage.get('end_timestamp')}`",
        "",
        "## Diagnostic Read",
        "",
        f"- Top feature: `{read.get('top_feature')}`",
        f"- Top feature family: `{read.get('top_feature_family')}`",
        f"- Top feature detail: `{read.get('top_feature_detail')}`",
        f"- Top family: `{read.get('top_family')}`",
        f"- Top family features: `{read.get('top_family_features')}`",
        "",
        "## Outcome Context",
        "",
        "| Cohort | Rows | Complete % | Partial % | Hit 60m % | Avg 60m bps | MFE/MAE 60m |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| Blindspot | {blind_outcome.get('row_count')} | {blind_outcome.get('complete_outcome_share')} | "
            f"{blind_outcome.get('partial_outcome_share')} | {blind_outcome.get('hit_rate_60m')} | "
            f"{blind_outcome.get('avg_signed_return_60m_bps')} | {blind_outcome.get('mfe_mae_ratio_60m')} |"
        ),
        (
            f"| Baseline | {base_outcome.get('row_count')} | {base_outcome.get('complete_outcome_share')} | "
            f"{base_outcome.get('partial_outcome_share')} | {base_outcome.get('hit_rate_60m')} | "
            f"{base_outcome.get('avg_signed_return_60m_bps')} | {base_outcome.get('mfe_mae_ratio_60m')} |"
        ),
        "",
        "## Recommended Actions",
        "",
    ]
    for action in report.get("recommended_actions") or []:
        lines.append(f"- {action}")

    lines.extend(["", "## Ranked Live-Time Candidate Features", ""])
    lines.extend(
        _markdown_table(
            report.get("ranked_live_feature_candidates") or [],
            ["feature", "feature_type", "family", "rank_score", "clue", "detail"],
            max_rows=20,
        )
    )
    lines.extend(["", "## Feature Family Summary", ""])
    lines.extend(
        _markdown_table(
            report.get("family_summary") or [],
            ["family", "feature_count", "top_score", "avg_top3_score", "top_features"],
            max_rows=12,
        )
    )
    lines.extend(["", "## Top Numeric Differences", ""])
    lines.extend(
        _markdown_table(
            report.get("numeric_feature_audit") or [],
            [
                "feature",
                "family",
                "rank_score",
                "blindspot_mean",
                "baseline_mean",
                "delta",
                "standardized_delta",
                "blindspot_missing_share",
            ],
            max_rows=20,
        )
    )
    lines.extend(["", "## Top Categorical Differences", ""])
    lines.extend(
        _markdown_table(
            report.get("categorical_feature_audit") or [],
            [
                "feature",
                "family",
                "rank_score",
                "largest_share_delta_value",
                "blindspot_share",
                "baseline_share",
                "share_delta",
                "dominant_blindspot_value",
                "dominant_blindspot_share",
            ],
            max_rows=20,
        )
    )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- The research composite is a hindsight label and must not be used as a runtime input.",
            "- Candidate live-time features need replay and fresh-forward helped/hurt evidence before engine changes.",
            "- Provider weakness must be separated into analytics conviction versus execution usability.",
            "",
        ]
    )
    return "\n".join(lines)


def write_runtime_blindspot_feature_audit_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_RUNTIME_BLINDSPOT_FEATURE_AUDIT_REPORT_DIR,
    report_date: str | None = None,
    research_high_threshold: float = DEFAULT_RESEARCH_HIGH_THRESHOLD,
    runtime_low_threshold: float = DEFAULT_RUNTIME_LOW_THRESHOLD,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = load_runtime_blindspot_feature_audit_dataset(dataset)
    report = build_runtime_blindspot_feature_audit_report(
        frame,
        report_date=report_date,
        research_high_threshold=research_high_threshold,
        runtime_low_threshold=runtime_low_threshold,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    json_path = output / f"runtime_blindspot_feature_audit_{timestamp}.json"
    markdown_path = output / f"runtime_blindspot_feature_audit_{timestamp}.md"
    latest_json_path = output / "latest_runtime_blindspot_feature_audit.json"
    latest_markdown_path = output / "latest_runtime_blindspot_feature_audit.md"
    numeric_csv_path = output / f"runtime_blindspot_feature_audit_{timestamp}_numeric.csv"
    categorical_csv_path = output / f"runtime_blindspot_feature_audit_{timestamp}_categorical.csv"
    family_csv_path = output / f"runtime_blindspot_feature_audit_{timestamp}_families.csv"

    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_runtime_blindspot_feature_audit_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")
    pd.DataFrame(report.get("numeric_feature_audit") or []).to_csv(numeric_csv_path, index=False)
    pd.DataFrame(report.get("categorical_feature_audit") or []).to_csv(categorical_csv_path, index=False)
    pd.DataFrame(report.get("family_summary") or []).to_csv(family_csv_path, index=False)
    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="runtime_blindspot_feature_audit",
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
        "numeric_csv_path": str(numeric_csv_path),
        "categorical_csv_path": str(categorical_csv_path),
        "family_csv_path": str(family_csv_path),
        "manifest_path": str(manifest_path),
    }

"""Research-only feature lineage diagnostics.

This report maps captured live-safe inputs into factor buckets, score
contributions, gate context, and realized outcomes. It is intentionally
diagnostic only: it does not change signal generation, thresholds, parameter
packs, provider routing, or execution behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH
from research.signal_evaluation.label_quality import apply_quality_label_view
from research.signal_evaluation.report_manifest import write_report_reproducibility_manifest
from utils.timestamp_helpers import coerce_timestamp_series


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEATURE_LINEAGE_REPORT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "feature_lineage"
)

LATEST_JSON_FILENAME = "latest_feature_lineage_report.json"
LATEST_MARKDOWN_FILENAME = "latest_feature_lineage_report.md"
LATEST_FEATURE_CSV_FILENAME = "latest_feature_lineage_catalog.csv"
LATEST_FACTOR_CSV_FILENAME = "latest_feature_lineage_factor_summary.csv"
LATEST_STATE_CSV_FILENAME = "latest_feature_lineage_state_outcomes.csv"
LATEST_COMPONENT_CSV_FILENAME = "latest_feature_lineage_runtime_components.csv"


@dataclass(frozen=True)
class FeatureLineageSpec:
    feature_id: str
    factor_bucket: str
    description: str
    signal_only_role: str
    owner_module: str
    source_columns: tuple[str, ...]
    score_columns: tuple[str, ...] = ()
    state_columns: tuple[str, ...] = ()
    runtime_component_keys: tuple[str, ...] = ()
    promotion_state: str = "research_or_diagnostic"
    next_action: str = "Monitor coverage and outcome stability before promotion."


FEATURE_LINEAGE_SPECS: tuple[FeatureLineageSpec, ...] = (
    FeatureLineageSpec(
        feature_id="signal_intensity",
        factor_bucket="signal_core",
        description="Structural signal strength and confirmation context.",
        signal_only_role="DIRECT_SIGNAL_QUALITY_INPUT",
        owner_module="strategy/trade_strength.py, engine/signal_engine.py",
        source_columns=(
            "trade_strength",
            "setup_activation_score",
            "setup_maturity_score",
            "signal_quality",
            "confirmation_status",
            "direction_source",
            "final_flow_signal",
        ),
        score_columns=("trade_strength", "setup_activation_score", "setup_maturity_score"),
        state_columns=("signal_quality", "confirmation_status", "final_flow_signal"),
        runtime_component_keys=("trade_strength", "confirmation"),
        promotion_state="live_input_existing",
        next_action="Keep monitoring trade-strength/runtime-composite divergence by regime.",
    ),
    FeatureLineageSpec(
        feature_id="runtime_composite_gate",
        factor_bucket="score_gate",
        description="Live-safe composite gate used to suppress weak or unstable directional rows.",
        signal_only_role="DIRECT_SIGNAL_QUALITY_GATE",
        owner_module="engine/signal_engine.py",
        source_columns=(
            "runtime_composite_base_score",
            "runtime_composite_score",
            "runtime_composite_components",
            "effective_min_composite_score_threshold",
        ),
        score_columns=("runtime_composite_score", "runtime_composite_base_score"),
        state_columns=("runtime_composite_observation_tier", "trade_status"),
        runtime_component_keys=("trade_strength", "move_probability", "confirmation", "data_quality", "gamma_stability"),
        promotion_state="live_gate_existing",
        next_action="Use guarded shadow evidence before changing any runtime gate behavior.",
    ),
    FeatureLineageSpec(
        feature_id="decision_quality_bridge_v1",
        factor_bucket="score_convergence_research",
        description="Research-only bridge between trade strength, runtime composite, and tradeability.",
        signal_only_role="RESEARCH_FEATURE_ONLY",
        owner_module="research/signal_evaluation/decision_quality_bridge.py",
        source_columns=(
            "decision_quality_score_v1",
            "decision_quality_score_v1_components",
            "decision_quality_score_v1_penalties",
            "decision_quality_score_v1_primary_drivers",
        ),
        score_columns=("decision_quality_score_v1", "decision_quality_score_v1_raw"),
        state_columns=("decision_quality_score_v1_primary_drivers",),
        promotion_state="research_only_forward_monitoring",
        next_action="Require stable cumulative and same-day forward evidence before display or live use.",
    ),
    FeatureLineageSpec(
        feature_id="probability_layer",
        factor_bucket="probability_calibration",
        description="Rule, ML, and hybrid move-probability estimates.",
        signal_only_role="SIGNAL_CONFIDENCE_AND_CALIBRATION_INPUT",
        owner_module="engine/signal_engine.py, research/signal_evaluation/probability_calibration_forward_monitor.py",
        source_columns=("move_probability", "rule_move_probability", "hybrid_move_probability", "ml_move_probability"),
        score_columns=("hybrid_move_probability", "move_probability", "rule_move_probability", "ml_move_probability"),
        state_columns=("probability_calibration_bucket",),
        runtime_component_keys=("move_probability",),
        promotion_state="live_input_existing_with_guarded_recalibration",
        next_action="Keep recalibration segmented; recent sessions reject global uplift/deflation.",
    ),
    FeatureLineageSpec(
        feature_id="provider_data_quality",
        factor_bucket="data_quality",
        description="Provider health, analytics usability, execution usability, and source trust.",
        signal_only_role="TRADEABILITY_AND_CONFIDENCE_FEATURE",
        owner_module="data/option_chain_validation.py, data/multi_source_router.py",
        source_columns=(
            "provider_quality_mode",
            "provider_health_status",
            "provider_analytics_status",
            "provider_execution_status",
            "provider_quality_blocks_direction",
            "provider_quality_blocks_execution",
            "data_quality_status",
            "option_source",
        ),
        score_columns=("data_quality_score", "tradable_data_score"),
        state_columns=("provider_quality_mode", "provider_health_status", "data_quality_status", "option_source"),
        runtime_component_keys=("data_quality",),
        promotion_state="live_guard_existing",
        next_action="Continue field-level provider disagreement reports before automatic provider override.",
    ),
    FeatureLineageSpec(
        feature_id="dealer_gamma_structure",
        factor_bucket="dealer_positioning",
        description="Gamma regime, flip state, wall distance, and dealer hedging pressure.",
        signal_only_role="DIRECT_SIGNAL_CONTEXT_AND_RISK_FEATURE",
        owner_module="analytics/gamma_flip.py, engine/signal_engine.py",
        source_columns=(
            "gamma_regime",
            "spot_vs_flip",
            "gamma_flip",
            "support_wall_distance_pct",
            "resistance_wall_distance_pct",
            "dealer_hedging_pressure_score",
            "dealer_flow_state",
        ),
        score_columns=("gamma_vol_acceleration_score", "dealer_hedging_pressure_score", "pinning_pressure_score"),
        state_columns=("gamma_regime", "spot_vs_flip", "dealer_flow_state", "directional_convexity_state"),
        runtime_component_keys=("gamma_stability",),
        promotion_state="live_input_existing",
        next_action="Segment runtime-gate shadow evidence by gamma/flip state before any gate relaxation.",
    ),
    FeatureLineageSpec(
        feature_id="option_tradeability_efficiency",
        factor_bucket="strike_tradeability",
        description="Selected strike liquidity, spread, reachability, and premium efficiency.",
        signal_only_role="TRADEABILITY_FEATURE",
        owner_module="strategy/enhanced_strike_scoring.py, strategy/strike_selector.py",
        source_columns=(
            "selected_option_ba_spread_pct",
            "selected_option_score",
            "target_reachability_score",
            "premium_efficiency_score",
            "strike_efficiency_score",
            "option_efficiency_score",
        ),
        score_columns=(
            "option_efficiency_score",
            "target_reachability_score",
            "premium_efficiency_score",
            "strike_efficiency_score",
            "selected_option_score",
        ),
        state_columns=("option_efficiency_status", "tradeability_tier"),
        promotion_state="live_tradeability_context",
        next_action="Evaluate option-efficiency contribution by provider and expiry before increasing influence.",
    ),
    FeatureLineageSpec(
        feature_id="technical_entry_timing",
        factor_bucket="entry_timing",
        description="Intraday candle state, late-chase warnings, and TA entry timing score.",
        signal_only_role="RESEARCH_AND_TIMING_FEATURE",
        owner_module="features/ta_indicators.py, research/signal_evaluation/entry_timing_diagnostics.py",
        source_columns=(
            "ta_entry_timing_state",
            "ta_entry_timing_score",
            "ta_candle_state",
            "ta_candle_late_chase",
            "ta_candle_rejection",
            "ta_candle_range_expansion_ratio",
        ),
        score_columns=("ta_entry_timing_score", "ta_candle_confidence"),
        state_columns=("ta_entry_timing_state", "ta_candle_state", "ta_candle_late_chase"),
        promotion_state="research_only",
        next_action="Keep evaluating delayed/second-confirmation paths before live timing influence.",
    ),
    FeatureLineageSpec(
        feature_id="price_structure_confluence",
        factor_bucket="price_structure",
        description="VWAP/TWAP proxy, opening range, CPR, pivots, Fibonacci, and confluence context.",
        signal_only_role="RESEARCH_AND_OPERATOR_CONTEXT",
        owner_module="analytics/price_structure.py, app/terminal_output.py",
        source_columns=(
            "nearest_price_structure_anchor_label",
            "nearest_price_structure_anchor_distance_pct",
            "price_level_confluence_state",
            "price_level_confluence_score",
            "price_structure_acceptance_state",
            "price_structure_day_type_proxy",
            "spot_vs_cpr_state",
            "spot_vs_pivot_state",
        ),
        score_columns=("price_level_confluence_score", "price_structure_trend_day_proxy_score"),
        state_columns=("price_level_confluence_state", "price_structure_acceptance_state", "price_structure_day_type_proxy"),
        promotion_state="display_and_research_only",
        next_action="Evaluate confluence/acceptance fields against hit rate, bps, and MAE/MFE before live influence.",
    ),
    FeatureLineageSpec(
        feature_id="macro_global_risk",
        factor_bucket="macro_risk",
        description="Global and India-specific macro context, risk-off pressure, and lagged institutional flows.",
        signal_only_role="RISK_CONTEXT_AND_CONFIDENCE_FEATURE",
        owner_module="risk/global_risk_regime.py, data/macro_context.py",
        source_columns=(
            "macro_regime",
            "global_risk_state",
            "global_risk_state_score",
            "global_risk_dominant_driver",
            "oil_change_24h",
            "us_vix_change_24h",
            "dxy_change_24h",
            "usdinr_change_24h",
            "gift_nifty_change_24h",
            "fii_cash_net",
            "dii_cash_net",
            "india_10y_yield",
            "india_us_10y_spread_bp",
        ),
        score_columns=("global_risk_state_score", "global_risk_overlay_score", "global_risk_adjustment_score"),
        state_columns=("macro_regime", "global_risk_state", "global_risk_dominant_driver"),
        promotion_state="live_risk_context_with_research_inputs",
        next_action="Keep stale macro rows labeled; evaluate FII/DII and India bonds before score influence.",
    ),
    FeatureLineageSpec(
        feature_id="volatility_surface",
        factor_bucket="volatility_surface",
        description="ATM IV, surface quality, Heston diagnostics, IV/HV state, and volatility shock context.",
        signal_only_role="VOLATILITY_CONTEXT_AND_RESEARCH_FEATURE",
        owner_module="analytics/volatility_surface.py, models/heston/",
        source_columns=(
            "selected_option_iv",
            "atm_iv_percentile",
            "volatility_regime",
            "iv_hv_regime",
            "heston_surface_quality",
            "heston_calibration_error",
            "heston_skew_state",
            "heston_forward_variance_proxy",
        ),
        score_columns=("volatility_shock_score", "volatility_explosion_probability", "greek_model_divergence_score"),
        state_columns=("volatility_regime", "heston_surface_quality", "heston_skew_state"),
        promotion_state="bs_live_default_heston_research_only",
        next_action="Build surface-state stability evidence before any live decision influence.",
    ),
    FeatureLineageSpec(
        feature_id="mean_reversion",
        factor_bucket="entry_timing",
        description="Research-only stretched-vs-recent-history diagnostic.",
        signal_only_role="RESEARCH_FEATURE_ONLY",
        owner_module="analytics/mean_reversion_detector.py, research/signal_evaluation/mean_reversion_evaluation.py",
        source_columns=(
            "mean_reversion_signal",
            "mean_reversion_zscore",
            "mean_reversion_strength",
            "mean_reversion_distance_pct",
            "mean_reversion_reason",
        ),
        score_columns=("mean_reversion_strength",),
        state_columns=("mean_reversion_signal", "mean_reversion_reason"),
        promotion_state="research_only_not_promotable_broadly",
        next_action="Monitor only narrow regime/direction pockets; broad mean reversion underperforms.",
    ),
)

FEATURE_BUCKETS = {spec.feature_id: spec.factor_bucket for spec in FEATURE_LINEAGE_SPECS}

BLOCKER_FEATURE_LINEAGE = {
    "provider_execution_blocked": "provider_data_quality",
    "provider_direction_blocked": "provider_data_quality",
    "provider_health_not_good": "provider_data_quality",
    "data_quality_not_strong": "provider_data_quality",
    "runtime_composite_below_threshold": "runtime_composite_gate",
    "move_probability_below_floor": "probability_layer",
    "trade_strength_below_threshold": "signal_intensity",
    "weak_signal_quality": "signal_intensity",
    "at_gamma_flip": "dealer_gamma_structure",
    "risk_off_macro": "macro_global_risk",
    "risk_off_global": "macro_global_risk",
    "low_ta_entry_timing": "technical_entry_timing",
}

RUNTIME_COMPONENT_FEATURE_LINEAGE = {
    "trade_strength": "signal_intensity",
    "move_probability": "probability_layer",
    "confirmation": "signal_intensity",
    "data_quality": "provider_data_quality",
    "gamma_stability": "dealer_gamma_structure",
}

HORIZON_HIT_COLUMN = "correct_60m"
HORIZON_RETURN_COLUMN = "signed_return_60m_bps"


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


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


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(_json_ready(payload), indent=2, sort_keys=True))


def _atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
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


def _text_series(frame: pd.DataFrame, column: str, default: str = "UNKNOWN") -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="object")
    return (
        frame[column]
        .astype("object")
        .where(frame[column].notna(), default)
        .astype(str)
        .str.strip()
        .replace({"": default, "nan": default, "NaN": default, "None": default, "<NA>": default})
    )


def _num_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _nonempty_mask(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    values = frame[column]
    text = values.astype("object").where(values.notna(), "").astype(str).str.strip().str.upper()
    return values.notna() & ~text.isin({"", "NAN", "NA", "N/A", "NONE", "NULL", "<NA>"})


def _filter_dates(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    if frame.empty or "signal_timestamp" not in frame.columns:
        return frame.iloc[0:0].copy()
    working = frame.copy()
    signal_ts = coerce_timestamp_series(working["signal_timestamp"], utc=True)
    signal_date = signal_ts.dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
    mask = signal_ts.notna()
    if report_date:
        mask &= signal_date == str(report_date)
    if start_date:
        mask &= signal_date >= str(start_date)
    if end_date:
        mask &= signal_date <= str(end_date)
    working["_signal_ts"] = signal_ts
    working["_signal_date"] = signal_date
    return working.loc[mask.fillna(False)].copy()


def _directional_mask(frame: pd.DataFrame) -> pd.Series:
    return _text_series(frame, "direction", default="").str.upper().isin({"CALL", "PUT"})


def feature_bucket(feature_id: str) -> str:
    return FEATURE_BUCKETS.get(str(feature_id or ""), "unmapped")


def lineage_for_blocker(blocker: str, component_drag: str | None = None) -> tuple[str, str, str]:
    normalized_blocker = str(blocker or "").strip()
    normalized_component = str(component_drag or "").strip()
    if (
        normalized_blocker == "runtime_composite_below_threshold"
        and normalized_component in RUNTIME_COMPONENT_FEATURE_LINEAGE
    ):
        feature_id = RUNTIME_COMPONENT_FEATURE_LINEAGE[normalized_component]
        return (
            feature_id,
            feature_bucket(feature_id),
            f"runtime_component_drag:{normalized_component}",
        )
    feature_id = BLOCKER_FEATURE_LINEAGE.get(normalized_blocker, "unmapped")
    return feature_id, feature_bucket(feature_id), f"primary_blocker:{normalized_blocker or 'unclassified'}"


def lineage_for_runtime_component(component_drag: str | None) -> tuple[str, str, str]:
    normalized_component = str(component_drag or "").strip()
    feature_id = RUNTIME_COMPONENT_FEATURE_LINEAGE.get(normalized_component, "unmapped")
    return feature_id, feature_bucket(feature_id), f"runtime_component_drag:{normalized_component or 'UNKNOWN'}"


def attach_lineage_columns(
    frame: pd.DataFrame,
    *,
    blocker_column: str | None = None,
    component_drag_column: str = "primary_component_drag",
) -> pd.DataFrame:
    """Attach lineage factor columns to a research frame.

    If ``blocker_column`` is provided, runtime-composite blockers drill through
    the primary runtime component drag. Without a blocker column, the component
    drag alone determines lineage. This helper is diagnostic only.
    """
    if frame is None or frame.empty:
        working = pd.DataFrame() if frame is None else frame.copy()
        working["lineage_feature_id"] = pd.Series(dtype="object")
        working["lineage_factor_bucket"] = pd.Series(dtype="object")
        working["lineage_reason"] = pd.Series(dtype="object")
        return working

    working = frame.copy()
    if component_drag_column not in working.columns:
        working[component_drag_column] = "UNKNOWN"
    if blocker_column and blocker_column in working.columns:
        lineage = [
            lineage_for_blocker(row.get(blocker_column), row.get(component_drag_column))
            for _, row in working.iterrows()
        ]
    else:
        lineage = [lineage_for_runtime_component(value) for value in working[component_drag_column]]
    working["lineage_feature_id"] = [item[0] for item in lineage]
    working["lineage_factor_bucket"] = [item[1] for item in lineage]
    working["lineage_reason"] = [item[2] for item in lineage]
    return working


def lineage_outcome_summary(
    frame: pd.DataFrame,
    *,
    group_columns: tuple[str, ...] = ("lineage_factor_bucket", "lineage_feature_id"),
    min_rows: int = 1,
    action_column: str | None = None,
) -> list[dict[str, Any]]:
    """Summarize lineage groups with 60m outcome fields."""
    if frame is None or frame.empty:
        return []
    if not set(group_columns).issubset(frame.columns):
        return []

    working = frame.copy()
    if action_column and action_column in working.columns:
        group_by = (action_column, *group_columns)
    else:
        group_by = group_columns

    total = max(int(len(working)), 1)
    rows: list[dict[str, Any]] = []
    for keys, group in working.groupby(list(group_by), dropna=False):
        if len(group) < int(min_rows):
            continue
        key_values = keys if isinstance(keys, tuple) else (keys,)
        row = {column: str(value) for column, value in zip(group_by, key_values, strict=False)}
        labels = _num_series(group, HORIZON_HIT_COLUMN)
        returns = _num_series(group, HORIZON_RETURN_COLUMN)
        labeled = labels.notna()
        row.update(
            {
                "row_count": int(len(group)),
                "share_of_rows": _round_or_none(float(len(group)) / total, 4),
                "label_count_60m": int(labeled.sum()),
                "hit_rate_60m": _round_or_none(_safe_mean(labels.loc[labeled]), 4) if labeled.any() else None,
                "avg_signed_return_60m_bps": _round_or_none(_safe_mean(returns), 4),
                "avg_runtime_composite": _round_or_none(_safe_mean(_num_series(group, "runtime_composite_score")), 4),
                "avg_trade_strength": _round_or_none(_safe_mean(_num_series(group, "trade_strength")), 4),
            }
        )
        rows.append(row)
    return sorted(rows, key=lambda item: (-int(item.get("row_count") or 0), str(item)))


def prepare_feature_lineage_frame(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Return a quality-label-aware directional frame for lineage reporting."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    working = _filter_dates(
        frame,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    if working.empty:
        return working
    working = working.loc[_directional_mask(working)].copy()
    if working.empty:
        return working
    return apply_quality_label_view(working, fallback_to_legacy=True, drop_unapproved=False)


def _parse_runtime_component_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text or text.upper() in {"NAN", "NONE", "NULL"}:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _runtime_component_frame(frame: pd.DataFrame) -> pd.DataFrame:
    components = ("trade_strength", "move_probability", "confirmation", "data_quality", "gamma_stability")
    if frame.empty or "runtime_composite_components" not in frame.columns:
        return pd.DataFrame(index=frame.index)
    parsed = [_parse_runtime_component_payload(value) for value in frame["runtime_composite_components"]]
    rows: list[dict[str, Any]] = []
    for payload in parsed:
        component_payload = payload.get("components") if isinstance(payload.get("components"), dict) else {}
        row: dict[str, Any] = {}
        for component in components:
            detail = component_payload.get(component) if isinstance(component_payload.get(component), dict) else {}
            for field in ("score", "weight", "weighted_contribution", "weighted_deficit_to_100"):
                row[f"runtime_component_{component}_{field}"] = _safe_float(detail.get(field), None)
        rows.append(row)
    return pd.DataFrame(rows, index=frame.index)


def _safe_mean(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _safe_spearman(left: pd.Series, right: pd.Series) -> float | None:
    joined = pd.concat(
        [pd.to_numeric(left, errors="coerce"), pd.to_numeric(right, errors="coerce")],
        axis=1,
    ).dropna()
    if len(joined) < 5 or joined.iloc[:, 0].nunique() < 2 or joined.iloc[:, 1].nunique() < 2:
        return None
    return float(joined.iloc[:, 0].corr(joined.iloc[:, 1], method="spearman"))


def _coverage_for_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> tuple[int, float | None]:
    present = [column for column in columns if column in frame.columns]
    if frame.empty or not present:
        return 0, None
    mask = pd.Series(False, index=frame.index, dtype=bool)
    for column in present:
        mask |= _nonempty_mask(frame, column)
    count = int(mask.sum())
    return count, float(count / len(frame)) if len(frame) else None


def _first_numeric_column(frame: pd.DataFrame, columns: tuple[str, ...]) -> str | None:
    for column in columns:
        if column in frame.columns and _num_series(frame, column).notna().any():
            return column
    return None


def _feature_row(frame: pd.DataFrame, spec: FeatureLineageSpec, component_frame: pd.DataFrame) -> dict[str, Any]:
    present_columns = [
        column
        for column in (*spec.source_columns, *spec.score_columns, *spec.state_columns)
        if column in frame.columns
    ]
    missing_columns = [
        column
        for column in (*spec.source_columns, *spec.score_columns, *spec.state_columns)
        if column not in frame.columns
    ]
    populated_count, coverage_pct = _coverage_for_columns(frame, tuple(present_columns))
    primary_score_col = _first_numeric_column(frame, spec.score_columns)
    score = _num_series(frame, primary_score_col) if primary_score_col else pd.Series(np.nan, index=frame.index)
    labels = _num_series(frame, HORIZON_HIT_COLUMN)
    returns = _num_series(frame, HORIZON_RETURN_COLUMN)
    label_mask = labels.notna()

    component_contributions: list[pd.Series] = []
    component_weights: list[pd.Series] = []
    for key in spec.runtime_component_keys:
        contribution_col = f"runtime_component_{key}_weighted_contribution"
        weight_col = f"runtime_component_{key}_weight"
        if contribution_col in component_frame.columns:
            component_contributions.append(_num_series(component_frame, contribution_col))
        if weight_col in component_frame.columns:
            component_weights.append(_num_series(component_frame, weight_col))
    if component_contributions:
        contribution = pd.concat(component_contributions, axis=1).sum(axis=1, min_count=1)
    else:
        contribution = pd.Series(np.nan, index=frame.index)
    if component_weights:
        weight = pd.concat(component_weights, axis=1).sum(axis=1, min_count=1)
    else:
        weight = pd.Series(np.nan, index=frame.index)

    populated_mask = pd.Series(False, index=frame.index, dtype=bool)
    for column in present_columns:
        populated_mask |= _nonempty_mask(frame, column)
    populated_labeled = frame.loc[populated_mask & label_mask]
    return {
        "feature_id": spec.feature_id,
        "factor_bucket": spec.factor_bucket,
        "description": spec.description,
        "signal_only_role": spec.signal_only_role,
        "owner_module": spec.owner_module,
        "promotion_state": spec.promotion_state,
        "next_action": spec.next_action,
        "present_column_count": int(len(set(present_columns))),
        "missing_column_count": int(len(set(missing_columns))),
        "missing_columns": ",".join(sorted(set(missing_columns))) if missing_columns else "",
        "populated_rows": int(populated_count),
        "coverage_pct": _round_or_none((coverage_pct or 0.0) * 100.0, 2) if coverage_pct is not None else None,
        "primary_score_column": primary_score_col,
        "primary_score_avg": _round_or_none(_safe_mean(score), 4),
        "score_spearman_return_60m": _round_or_none(_safe_spearman(score, returns), 4),
        "runtime_component_keys": ",".join(spec.runtime_component_keys),
        "avg_runtime_component_weight": _round_or_none(_safe_mean(weight), 4),
        "avg_runtime_weighted_contribution": _round_or_none(_safe_mean(contribution), 4),
        "quality_label_count_60m": int(label_mask.sum()),
        "populated_quality_label_count_60m": int(len(populated_labeled)),
        "populated_hit_rate_60m": _round_or_none(_safe_mean(_num_series(populated_labeled, HORIZON_HIT_COLUMN)), 4),
        "populated_avg_return_60m_bps": _round_or_none(
            _safe_mean(_num_series(populated_labeled, HORIZON_RETURN_COLUMN)),
            4,
        ),
    }


def _component_summary(frame: pd.DataFrame, component_frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty or component_frame.empty:
        return []
    returns = _num_series(frame, HORIZON_RETURN_COLUMN)
    labels = _num_series(frame, HORIZON_HIT_COLUMN)
    rows: list[dict[str, Any]] = []
    for component in ("trade_strength", "move_probability", "confirmation", "data_quality", "gamma_stability"):
        score = _num_series(component_frame, f"runtime_component_{component}_score")
        weight = _num_series(component_frame, f"runtime_component_{component}_weight")
        contribution = _num_series(component_frame, f"runtime_component_{component}_weighted_contribution")
        deficit = _num_series(component_frame, f"runtime_component_{component}_weighted_deficit_to_100")
        available = score.notna()
        if not bool(available.any()):
            continue
        labeled = available & labels.notna()
        rows.append(
            {
                "runtime_component": component,
                "available_rows": int(available.sum()),
                "coverage_pct": _round_or_none(float(available.mean()) * 100.0, 2),
                "avg_score": _round_or_none(_safe_mean(score), 4),
                "avg_weight": _round_or_none(_safe_mean(weight), 4),
                "avg_weighted_contribution": _round_or_none(_safe_mean(contribution), 4),
                "avg_weighted_deficit_to_100": _round_or_none(_safe_mean(deficit), 4),
                "score_spearman_return_60m": _round_or_none(_safe_spearman(score, returns), 4),
                "labeled_rows_60m": int(labeled.sum()),
                "hit_rate_60m": _round_or_none(_safe_mean(labels.loc[labeled]), 4),
                "avg_return_60m_bps": _round_or_none(_safe_mean(returns.loc[labeled]), 4),
            }
        )
    return rows


def _state_outcome_rows(
    frame: pd.DataFrame,
    specs: tuple[FeatureLineageSpec, ...],
    *,
    min_rows: int,
) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    labels = _num_series(frame, HORIZON_HIT_COLUMN)
    returns = _num_series(frame, HORIZON_RETURN_COLUMN)
    for spec in specs:
        for column in spec.state_columns:
            if column not in frame.columns:
                continue
            values = _text_series(frame, column)
            for value, group_index in values.groupby(values).groups.items():
                group = frame.loc[group_index]
                if len(group) < min_rows:
                    continue
                group_labels = labels.loc[group.index]
                labeled = group_labels.notna()
                if int(labeled.sum()) <= 0:
                    continue
                rows.append(
                    {
                        "feature_id": spec.feature_id,
                        "factor_bucket": spec.factor_bucket,
                        "state_column": column,
                        "state_value": str(value),
                        "row_count": int(len(group)),
                        "quality_label_count_60m": int(labeled.sum()),
                        "hit_rate_60m": _round_or_none(_safe_mean(group_labels.loc[labeled]), 4),
                        "avg_return_60m_bps": _round_or_none(_safe_mean(returns.loc[group.index][labeled]), 4),
                    }
                )
    return sorted(
        rows,
        key=lambda item: (
            str(item.get("factor_bucket")),
            str(item.get("feature_id")),
            -int(item.get("quality_label_count_60m") or 0),
            str(item.get("state_value")),
        ),
    )


def _factor_summary_rows(feature_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not feature_rows:
        return []
    frame = pd.DataFrame(feature_rows)
    rows: list[dict[str, Any]] = []
    for factor, group in frame.groupby("factor_bucket", dropna=False):
        rows.append(
            {
                "factor_bucket": str(factor),
                "feature_count": int(len(group)),
                "avg_coverage_pct": _round_or_none(_safe_mean(group["coverage_pct"]), 4),
                "avg_score_spearman_return_60m": _round_or_none(
                    _safe_mean(group["score_spearman_return_60m"]),
                    4,
                ),
                "avg_populated_return_60m_bps": _round_or_none(
                    _safe_mean(group["populated_avg_return_60m_bps"]),
                    4,
                ),
                "features": ",".join(sorted(group["feature_id"].astype(str))),
            }
        )
    return sorted(rows, key=lambda item: str(item.get("factor_bucket")))


def _diagnostic_read(feature_rows: list[dict[str, Any]], component_rows: list[dict[str, Any]]) -> dict[str, Any]:
    observations: list[str] = []
    low_coverage = [
        row["feature_id"]
        for row in feature_rows
        if (row.get("coverage_pct") is not None and float(row.get("coverage_pct") or 0) < 50)
    ]
    missing = [row["feature_id"] for row in feature_rows if int(row.get("present_column_count") or 0) == 0]
    score_rows = [
        row
        for row in feature_rows
        if row.get("score_spearman_return_60m") is not None
    ]
    best = max(score_rows, key=lambda row: float(row.get("score_spearman_return_60m") or -999), default=None)
    worst = min(score_rows, key=lambda row: float(row.get("score_spearman_return_60m") or 999), default=None)
    if missing:
        observations.append("Some cataloged features have no matching captured dataset columns.")
    if low_coverage:
        observations.append("Some captured features have low population coverage and need capture-quality review.")
    if best:
        observations.append(
            f"Best current 60m score alignment: {best['feature_id']} "
            f"({best['score_spearman_return_60m']})."
        )
    if worst and worst is not best:
        observations.append(
            f"Weakest current 60m score alignment: {worst['feature_id']} "
            f"({worst['score_spearman_return_60m']})."
        )

    component_best = max(
        [row for row in component_rows if row.get("score_spearman_return_60m") is not None],
        key=lambda row: float(row.get("score_spearman_return_60m") or -999),
        default=None,
    )
    if component_best:
        observations.append(
            f"Runtime component with best 60m alignment: {component_best['runtime_component']} "
            f"({component_best['score_spearman_return_60m']})."
        )

    if best and float(best.get("score_spearman_return_60m") or 0.0) > 0.10:
        primary = "LINEAGE_CAPTURE_ACTIVE_WITH_USEFUL_ALIGNMENT"
    elif score_rows:
        primary = "LINEAGE_CAPTURE_ACTIVE_ALIGNMENT_WEAK_OR_SEGMENTED"
    else:
        primary = "LINEAGE_CAPTURE_ACTIVE_OUTCOME_ALIGNMENT_UNAVAILABLE"

    return {
        "primary_read": primary,
        "observations": observations,
        "low_coverage_features": low_coverage,
        "missing_feature_columns": missing,
        "best_score_feature": best.get("feature_id") if best else None,
        "best_score_spearman_return_60m": best.get("score_spearman_return_60m") if best else None,
        "weakest_score_feature": worst.get("feature_id") if worst else None,
        "weakest_score_spearman_return_60m": worst.get("score_spearman_return_60m") if worst else None,
        "best_runtime_component": component_best.get("runtime_component") if component_best else None,
        "best_runtime_component_spearman_return_60m": (
            component_best.get("score_spearman_return_60m") if component_best else None
        ),
    }


def build_feature_lineage_report(
    frame: pd.DataFrame,
    *,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    state_min_rows: int = 20,
) -> dict[str, Any]:
    prepared = prepare_feature_lineage_frame(
        frame,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
    )
    component_frame = _runtime_component_frame(prepared)
    feature_rows = [_feature_row(prepared, spec, component_frame) for spec in FEATURE_LINEAGE_SPECS]
    component_rows = _component_summary(prepared, component_frame)
    state_rows = _state_outcome_rows(prepared, FEATURE_LINEAGE_SPECS, min_rows=max(int(state_min_rows), 1))
    factor_rows = _factor_summary_rows(feature_rows)
    labels = _num_series(prepared, HORIZON_HIT_COLUMN)
    returns = _num_series(prepared, HORIZON_RETURN_COLUMN)

    return {
        "report_type": "feature_lineage_report",
        "generated_at": _now_utc(),
        "report_date": report_date,
        "start_date": start_date,
        "end_date": end_date,
        "mode": "research_only",
        "signal_only_boundary": (
            "Feature lineage is diagnostic only and must not route orders, manage fills, "
            "or alter live signal behavior."
        ),
        "coverage": {
            "input_rows": int(len(frame) if frame is not None else 0),
            "prepared_directional_rows": int(len(prepared)),
            "quality_label_count_60m": int(labels.notna().sum()),
            "avg_hit_rate_60m": _round_or_none(_safe_mean(labels), 4),
            "avg_signed_return_60m_bps": _round_or_none(_safe_mean(returns), 4),
            "feature_count": int(len(feature_rows)),
            "runtime_component_rows": int(len(component_rows)),
            "state_outcome_rows": int(len(state_rows)),
        },
        "diagnostic_read": _diagnostic_read(feature_rows, component_rows),
        "feature_lineage": feature_rows,
        "factor_summary": factor_rows,
        "runtime_component_summary": component_rows,
        "state_outcome_summary": state_rows,
    }


def render_feature_lineage_markdown(report: dict[str, Any]) -> str:
    coverage = report.get("coverage") or {}
    read = report.get("diagnostic_read") or {}
    lines: list[str] = [
        "# Feature Lineage Report",
        "",
        "Author: Pramit Dutta  ",
        "Organization: Quant Engines",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Research Boundary",
        "",
        str(report.get("signal_only_boundary") or ""),
        "",
        "## Coverage",
        "",
        f"- Prepared directional rows: {coverage.get('prepared_directional_rows')}",
        f"- Quality-approved 60m labels: {coverage.get('quality_label_count_60m')}",
        f"- Average 60m hit rate: {coverage.get('avg_hit_rate_60m')}",
        f"- Average signed 60m return: {coverage.get('avg_signed_return_60m_bps')} bps",
        f"- Cataloged feature groups: {coverage.get('feature_count')}",
        "",
        "## Diagnostic Read",
        "",
        f"- Primary read: {read.get('primary_read')}",
    ]
    for observation in read.get("observations") or []:
        lines.append(f"- {observation}")

    lines.extend(
        [
            "",
            "## Feature Catalog",
            "",
            *_markdown_table(
                report.get("feature_lineage") or [],
                [
                    "feature_id",
                    "factor_bucket",
                    "signal_only_role",
                    "coverage_pct",
                    "primary_score_column",
                    "score_spearman_return_60m",
                    "avg_runtime_weighted_contribution",
                    "promotion_state",
                ],
            ),
            "",
            "## Factor Summary",
            "",
            *_markdown_table(
                report.get("factor_summary") or [],
                [
                    "factor_bucket",
                    "feature_count",
                    "avg_coverage_pct",
                    "avg_score_spearman_return_60m",
                    "avg_populated_return_60m_bps",
                    "features",
                ],
            ),
            "",
            "## Runtime Composite Components",
            "",
            *_markdown_table(
                report.get("runtime_component_summary") or [],
                [
                    "runtime_component",
                    "coverage_pct",
                    "avg_score",
                    "avg_weight",
                    "avg_weighted_contribution",
                    "score_spearman_return_60m",
                    "hit_rate_60m",
                    "avg_return_60m_bps",
                ],
            ),
            "",
            "## State Outcome Snapshot",
            "",
            *_markdown_table(
                report.get("state_outcome_summary") or [],
                [
                    "feature_id",
                    "state_column",
                    "state_value",
                    "quality_label_count_60m",
                    "hit_rate_60m",
                    "avg_return_60m_bps",
                ],
                max_rows=40,
            ),
            "",
            "## Usage Rules",
            "",
            "- This report may identify candidates for deeper research only.",
            "- No feature should affect live signal logic until it is point-in-time logged, evaluated, segmented, and explicitly promoted.",
            "- ML or research overlays must not override the structural signal engine without approval.",
            "- Execution/order-routing logic remains out of scope.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_feature_lineage_report(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_FEATURE_LINEAGE_REPORT_DIR,
    report_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    state_min_rows: int = 20,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    frame = pd.read_csv(dataset, low_memory=False) if dataset.exists() else pd.DataFrame()
    report = build_feature_lineage_report(
        frame,
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
        state_min_rows=state_min_rows,
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    suffix = report_date or end_date or "cumulative"

    json_path = output / f"feature_lineage_report_{suffix}_{stamp}.json"
    markdown_path = output / f"feature_lineage_report_{suffix}_{stamp}.md"
    feature_csv_path = output / f"feature_lineage_catalog_{suffix}_{stamp}.csv"
    factor_csv_path = output / f"feature_lineage_factor_summary_{suffix}_{stamp}.csv"
    state_csv_path = output / f"feature_lineage_state_outcomes_{suffix}_{stamp}.csv"
    component_csv_path = output / f"feature_lineage_runtime_components_{suffix}_{stamp}.csv"

    _atomic_write_json(json_path, report)
    _atomic_write_text(markdown_path, render_feature_lineage_markdown(report))
    _atomic_write_csv(feature_csv_path, report.get("feature_lineage") or [])
    _atomic_write_csv(factor_csv_path, report.get("factor_summary") or [])
    _atomic_write_csv(state_csv_path, report.get("state_outcome_summary") or [])
    _atomic_write_csv(component_csv_path, report.get("runtime_component_summary") or [])

    latest_json_path = output / LATEST_JSON_FILENAME
    latest_markdown_path = output / LATEST_MARKDOWN_FILENAME
    latest_feature_csv_path = output / LATEST_FEATURE_CSV_FILENAME
    latest_factor_csv_path = output / LATEST_FACTOR_CSV_FILENAME
    latest_state_csv_path = output / LATEST_STATE_CSV_FILENAME
    latest_component_csv_path = output / LATEST_COMPONENT_CSV_FILENAME

    _atomic_write_json(latest_json_path, report)
    _atomic_write_text(latest_markdown_path, render_feature_lineage_markdown(report))
    _atomic_write_csv(latest_feature_csv_path, report.get("feature_lineage") or [])
    _atomic_write_csv(latest_factor_csv_path, report.get("factor_summary") or [])
    _atomic_write_csv(latest_state_csv_path, report.get("state_outcome_summary") or [])
    _atomic_write_csv(latest_component_csv_path, report.get("runtime_component_summary") or [])

    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="feature_lineage_report",
        report_date=report_date or end_date,
        mode="research_only",
        run_evaluation=True,
        narrative=False,
    )
    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "feature_csv_path": str(feature_csv_path),
        "factor_csv_path": str(factor_csv_path),
        "state_csv_path": str(state_csv_path),
        "component_csv_path": str(component_csv_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
        "latest_feature_csv_path": str(latest_feature_csv_path),
        "latest_factor_csv_path": str(latest_factor_csv_path),
        "latest_state_csv_path": str(latest_state_csv_path),
        "latest_component_csv_path": str(latest_component_csv_path),
        "manifest_path": str(manifest_path),
    }

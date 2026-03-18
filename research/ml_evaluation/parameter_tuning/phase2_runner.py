"""
Walk-Forward Parameter Tuning — Phase 2: Selection Threshold Tuning
====================================================================

Phase 1 Finding:
  Groups like trade_strength, confirmation_filter, large_move_probability change
  score COMPUTATION parameters, but the backtest dataset has PRE-COMPUTED scores.
  Parameter overrides for those groups cannot alter outcomes on a fixed dataset.

Phase 2 Strategy:
  Tune the `evaluation_thresholds` group, which controls:
  - Selection floors (trade_strength_floor=45, composite_floor=55, etc.)
  - Score weights (direction=0.3, magnitude=0.25, timing=0.2, tradeability=0.25)
  - Direction weights (correct_5m=1.0, correct_15m=1.2, etc.)
  - Timing weights (realized_return_5m=1.4, realized_return_15m=1.2, etc.)

  These parameters flow through `get_signal_evaluation_selection_policy()` →
  `resolve_mapping()` → `apply_selection_policy()` and directly change which
  signals pass the filter, enabling genuine objective optimization.

Output: research/ml_evaluation/parameter_tuning/phase2/
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ── Project imports ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from config.signal_evaluation_scoring import get_signal_evaluation_selection_policy
from tuning.runtime import temporary_parameter_pack
from tuning.campaigns import run_group_tuning_campaign
from tuning.objectives import (
    compute_objective,
    compute_frame_metrics,
    apply_selection_policy,
)
from tuning.registry import get_parameter_registry
from tuning.validation import run_walk_forward_validation
from tuning.regimes import label_validation_regimes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────
BACKTEST_PARQUET = PROJECT_ROOT / "research" / "signal_evaluation" / "backtest_signals_dataset.parquet"
OUTPUT_DIR = PROJECT_ROOT / "research" / "ml_evaluation" / "parameter_tuning" / "phase2"
TEMP_DATASET_CSV = OUTPUT_DIR / "_tuning_dataset.csv"

# ── Walk-forward configuration ─────────────────────────────────
WALK_FORWARD_CONFIG = {
    "split_type": "anchored",
    "train_window_days": 365,
    "validation_window_days": 120,
    "step_size_days": 90,
    "minimum_train_rows": 50,
    "minimum_validation_rows": 20,
}

# The group that actually affects outcomes on pre-computed data
TUNING_GROUP = "evaluation_thresholds"

HOLDOUT_YEAR = 2025
TRAIN_END_YEAR = 2024


def _ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _load_and_split() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load backtest data and split into train/holdout."""
    df = pd.read_parquet(BACKTEST_PARQUET)
    df["signal_timestamp"] = pd.to_datetime(df["signal_timestamp"], errors="coerce")
    years = df["signal_timestamp"].dt.year
    train = df[years <= TRAIN_END_YEAR].copy().reset_index(drop=True)
    holdout = df[years == HOLDOUT_YEAR].copy().reset_index(drop=True)
    log.info("Dataset: %d total, Train: %d (2016-%d), Holdout: %d (%d)",
             len(df), len(train), TRAIN_END_YEAR, len(holdout), HOLDOUT_YEAR)
    return train, holdout


def _evaluate_with_pack(df: pd.DataFrame, overrides: dict | None = None, label: str = "default") -> dict:
    """Evaluate a DataFrame using the parameter pack selection policy."""
    with temporary_parameter_pack("baseline_v1", overrides=overrides):
        thresholds = dict(get_signal_evaluation_selection_policy())
        selected = apply_selection_policy(df, thresholds=thresholds)
        metrics = compute_frame_metrics(selected, len(df))
        objective = compute_objective(
            df, thresholds=thresholds, parameter_count=len(overrides or {})
        )

    return {
        "label": label,
        "thresholds_used": thresholds,
        "selected_count": metrics["selected_count"],
        "total_count": len(df),
        "signal_frequency": metrics["signal_frequency"],
        "direction_hit_rate": metrics["direction_hit_rate"],
        "avg_composite": metrics["average_composite_signal_score"],
        "avg_tradeability": metrics["average_tradeability_score"],
        "avg_return_60m_bps": metrics["average_realized_return_60m_bps"],
        "drawdown_proxy": metrics["drawdown_proxy"],
        "regime_stability": metrics["regime_stability"],
        "objective_score": objective.objective_score,
        "metrics": metrics,
        "train_metrics": objective.train_metrics,
        "validation_metrics": objective.validation_metrics,
        "safeguards": objective.safeguards,
    }


def _run_wf_validation_with_pack(df: pd.DataFrame, overrides: dict | None = None) -> dict:
    """Run walk-forward validation using the pack's selection policy."""
    with temporary_parameter_pack("baseline_v1", overrides=overrides):
        thresholds = dict(get_signal_evaluation_selection_policy())
        wf = run_walk_forward_validation(
            df,
            selection_thresholds=thresholds,
            parameter_count=len(overrides or {}),
            walk_forward_config=WALK_FORWARD_CONFIG,
        )
    return wf


def main():
    _ensure_output_dir()
    t_start = time.time()

    log.info("=" * 70)
    log.info("PHASE 2: EVALUATION THRESHOLD TUNING")
    log.info("=" * 70)

    # 1. Load and split
    train, holdout = _load_and_split()
    train = label_validation_regimes(train)
    holdout = label_validation_regimes(holdout)

    # Export for tuning pipeline
    train.to_csv(TEMP_DATASET_CSV, index=False)
    log.info("Exported train CSV: %s", TEMP_DATASET_CSV)

    # 2. Baseline evaluation (with proper selection policy)
    log.info("Computing baseline with proper selection policy...")
    baseline_train = _evaluate_with_pack(train, overrides=None, label="baseline_train")
    baseline_holdout = _evaluate_with_pack(holdout, overrides=None, label="baseline_holdout")
    baseline_wf = _run_wf_validation_with_pack(train, overrides=None)

    log.info("Baseline train: selected=%d/%d, HR=%.4f, return=%.2f bps, objective=%.4f",
             baseline_train["selected_count"], baseline_train["total_count"],
             baseline_train["direction_hit_rate"], baseline_train["avg_return_60m_bps"],
             baseline_train["objective_score"])
    log.info("Baseline holdout: selected=%d/%d, HR=%.4f, return=%.2f bps, objective=%.4f",
             baseline_holdout["selected_count"], baseline_holdout["total_count"],
             baseline_holdout["direction_hit_rate"], baseline_holdout["avg_return_60m_bps"],
             baseline_holdout["objective_score"])
    log.info("Baseline WF OOS: %.4f", baseline_wf.get("aggregate_out_of_sample_score", 0))
    log.info("Baseline selection thresholds: %s", baseline_train["thresholds_used"])

    # Save baseline
    with open(OUTPUT_DIR / "baseline_evaluation.json", "w") as f:
        json.dump({
            "train": _serialize(baseline_train),
            "holdout": _serialize(baseline_holdout),
            "walk_forward": _serialize(baseline_wf),
        }, f, indent=2, default=str)

    # 3. Run campaign for evaluation_thresholds
    log.info("=" * 60)
    log.info("TUNING GROUP: %s (29 parameters)", TUNING_GROUP)
    log.info("=" * 60)

    t_campaign = time.time()
    campaign_result = run_group_tuning_campaign(
        parameter_pack_name="baseline_v1",
        dataset_path=str(TEMP_DATASET_CSV),
        groups=[TUNING_GROUP],
        allow_live_unsafe=True,  # evaluation_thresholds are not live_safe; OK for research
        walk_forward_config=WALK_FORWARD_CONFIG,
        comparison_baseline_pack="baseline_v1",
        seed=42,
        persist=False,
    )
    campaign_elapsed = time.time() - t_campaign

    best_overrides = campaign_result.get("final_overrides", {})
    best_score = campaign_result.get("best_score")
    steps = campaign_result.get("steps", [])
    total_trials = sum(s.get("lhs_trial_count", 0) + s.get("coordinate_trial_count", 0) for s in steps)

    log.info("Campaign complete: score=%.6f, trials=%d, elapsed=%.1fs",
             best_score or 0, total_trials, campaign_elapsed)

    # Show changed parameters
    registry = get_parameter_registry()
    changed = {}
    for key, val in sorted(best_overrides.items()):
        defn = registry.get(key)
        if defn and val != defn.default_value:
            changed[key] = {"default": defn.default_value, "tuned": val}
            log.info("  %s: %s → %s", key, defn.default_value, val)

    log.info("Parameters changed: %d / %d total overrides", len(changed), len(best_overrides))

    # Save campaign
    with open(OUTPUT_DIR / "campaign_result.json", "w") as f:
        json.dump(_serialize(campaign_result), f, indent=2, default=str)

    # 4. Evaluate tuned on holdout
    log.info("Evaluating tuned parameters on holdout...")
    tuned_train = _evaluate_with_pack(train, overrides=best_overrides, label="tuned_train")
    tuned_holdout = _evaluate_with_pack(holdout, overrides=best_overrides, label="tuned_holdout")
    tuned_wf = _run_wf_validation_with_pack(train, overrides=best_overrides)

    log.info("Tuned train: selected=%d/%d, HR=%.4f, return=%.2f bps, objective=%.4f",
             tuned_train["selected_count"], tuned_train["total_count"],
             tuned_train["direction_hit_rate"], tuned_train["avg_return_60m_bps"],
             tuned_train["objective_score"])
    log.info("Tuned holdout: selected=%d/%d, HR=%.4f, return=%.2f bps, objective=%.4f",
             tuned_holdout["selected_count"], tuned_holdout["total_count"],
             tuned_holdout["direction_hit_rate"], tuned_holdout["avg_return_60m_bps"],
             tuned_holdout["objective_score"])
    log.info("Tuned WF OOS: %.4f", tuned_wf.get("aggregate_out_of_sample_score", 0))
    log.info("Tuned selection thresholds: %s", tuned_train["thresholds_used"])

    # 5. Comparison table
    deltas = {
        "selected_count": tuned_holdout["selected_count"] - baseline_holdout["selected_count"],
        "signal_frequency": tuned_holdout["signal_frequency"] - baseline_holdout["signal_frequency"],
        "direction_hit_rate": tuned_holdout["direction_hit_rate"] - baseline_holdout["direction_hit_rate"],
        "avg_return_60m_bps": tuned_holdout["avg_return_60m_bps"] - baseline_holdout["avg_return_60m_bps"],
        "avg_composite": tuned_holdout["avg_composite"] - baseline_holdout["avg_composite"],
        "drawdown_proxy": tuned_holdout["drawdown_proxy"] - baseline_holdout["drawdown_proxy"],
        "objective_score": tuned_holdout["objective_score"] - baseline_holdout["objective_score"],
    }

    # 6. Build report
    elapsed = time.time() - t_start
    lines = [
        "# Phase 2: Evaluation Threshold Tuning Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Group tuned**: `{TUNING_GROUP}` (29 parameters)",
        f"**Trials**: {total_trials}",
        f"**Runtime**: {elapsed:.0f}s",
        "",
        "## Context",
        "",
        "Phase 1 revealed that tuning score-computation groups (trade_strength, confirmation_filter,",
        "large_move_probability) has **no effect** on a pre-computed backtest dataset because column",
        "values are baked in. Only the `evaluation_thresholds` group —  which controls **selection",
        "floors, scoring weights, direction weights, and timing weights** — can affect outcomes.",
        "",
        "## Baseline vs Tuned: Training Set (2016-2024)",
        "",
        "| Metric | Baseline | Tuned | Delta |",
        "|--------|----------|-------|-------|",
        f"| Selected signals | {baseline_train['selected_count']} | {tuned_train['selected_count']} | {tuned_train['selected_count'] - baseline_train['selected_count']:+d} |",
        f"| Signal frequency | {baseline_train['signal_frequency']:.4f} | {tuned_train['signal_frequency']:.4f} | {tuned_train['signal_frequency'] - baseline_train['signal_frequency']:+.4f} |",
        f"| Direction hit rate | {baseline_train['direction_hit_rate']:.4f} | {tuned_train['direction_hit_rate']:.4f} | {tuned_train['direction_hit_rate'] - baseline_train['direction_hit_rate']:+.4f} |",
        f"| Avg return 60m (bps) | {baseline_train['avg_return_60m_bps']:.2f} | {tuned_train['avg_return_60m_bps']:.2f} | {tuned_train['avg_return_60m_bps'] - baseline_train['avg_return_60m_bps']:+.2f} |",
        f"| Composite score | {baseline_train['avg_composite']:.2f} | {tuned_train['avg_composite']:.2f} | {tuned_train['avg_composite'] - baseline_train['avg_composite']:+.2f} |",
        f"| Drawdown proxy | {baseline_train['drawdown_proxy']:.2f} | {tuned_train['drawdown_proxy']:.2f} | {tuned_train['drawdown_proxy'] - baseline_train['drawdown_proxy']:+.2f} |",
        f"| Objective score | {baseline_train['objective_score']:.4f} | {tuned_train['objective_score']:.4f} | {tuned_train['objective_score'] - baseline_train['objective_score']:+.4f} |",
        "",
        "## Baseline vs Tuned: Holdout Set (2025, unseen)",
        "",
        "| Metric | Baseline | Tuned | Delta |",
        "|--------|----------|-------|-------|",
        f"| Selected signals | {baseline_holdout['selected_count']} | {tuned_holdout['selected_count']} | {deltas['selected_count']:+d} |",
        f"| Signal frequency | {baseline_holdout['signal_frequency']:.4f} | {tuned_holdout['signal_frequency']:.4f} | {deltas['signal_frequency']:+.4f} |",
        f"| Direction hit rate | {baseline_holdout['direction_hit_rate']:.4f} | {tuned_holdout['direction_hit_rate']:.4f} | {deltas['direction_hit_rate']:+.4f} |",
        f"| Avg return 60m (bps) | {baseline_holdout['avg_return_60m_bps']:.2f} | {tuned_holdout['avg_return_60m_bps']:.2f} | {deltas['avg_return_60m_bps']:+.2f} |",
        f"| Composite score | {baseline_holdout['avg_composite']:.2f} | {tuned_holdout['avg_composite']:.2f} | {deltas['avg_composite']:+.2f} |",
        f"| Drawdown proxy | {baseline_holdout['drawdown_proxy']:.2f} | {tuned_holdout['drawdown_proxy']:.2f} | {deltas['drawdown_proxy']:+.2f} |",
        f"| Objective score | {baseline_holdout['objective_score']:.4f} | {tuned_holdout['objective_score']:.4f} | {deltas['objective_score']:+.4f} |",
        "",
        "## Walk-Forward Validation",
        "",
        f"| Metric | Baseline | Tuned | Delta |",
        f"|--------|----------|-------|-------|",
        f"| Aggregate OOS score | {baseline_wf.get('aggregate_out_of_sample_score', 0):.4f} | {tuned_wf.get('aggregate_out_of_sample_score', 0):.4f} | {(tuned_wf.get('aggregate_out_of_sample_score', 0) - baseline_wf.get('aggregate_out_of_sample_score', 0)):+.4f} |",
        f"| Robustness score | {baseline_wf.get('robustness_metrics', {}).get('robustness_score', 0):.4f} | {tuned_wf.get('robustness_metrics', {}).get('robustness_score', 0):.4f} | {(tuned_wf.get('robustness_metrics', {}).get('robustness_score', 0) - baseline_wf.get('robustness_metrics', {}).get('robustness_score', 0)):+.4f} |",
        "",
        "## Selection Thresholds Comparison",
        "",
        "| Threshold | Default | Tuned |",
        "|-----------|---------|-------|",
    ]

    baseline_thresholds = baseline_holdout["thresholds_used"]
    tuned_thresholds = tuned_holdout["thresholds_used"]
    for key in sorted(baseline_thresholds.keys()):
        bv = baseline_thresholds.get(key, "?")
        tv = tuned_thresholds.get(key, "?")
        marker = " **" if bv != tv else ""
        lines.append(f"| `{key}` | {bv} | {tv}{marker} |")

    lines.extend([
        "",
        "## Key Parameter Changes",
        "",
        "| Parameter | Default | Tuned |",
        "|-----------|---------|-------|",
    ])
    for key, vals in sorted(changed.items()):
        lines.append(f"| `{key}` | {vals['default']} | {vals['tuned']} |")

    lines.extend([
        "",
        "## Interpretation",
        "",
        "- **Selection thresholds** directly control which signals are traded.",
        "- Lowering floors increases signal frequency but may include lower-quality signals.",
        "- Raising floors increases average quality but reduces available trade count.",
        "- The optimization balances these trade-offs using the 11-metric weighted objective.",
        "- Holdout performance (2025) validates whether in-sample improvements generalize.",
        "",
        "## Phase 1 vs Phase 2 Summary",
        "",
        "| Phase | Groups | Can Affect Outcome? | Result |",
        "|-------|--------|--------------------|---------| ",
        "| Phase 1 | trade_strength, confirmation_filter, large_move_probability | No (pre-computed scores) | 0 holdout delta |",
        f"| Phase 2 | evaluation_thresholds | Yes (selection filters) | {deltas['direction_hit_rate']:+.4f} HR, {deltas['avg_return_60m_bps']:+.2f} bps |",
        "",
    ])

    report = "\n".join(lines)
    with open(OUTPUT_DIR / "phase2_report.md", "w") as f:
        f.write(report)
    log.info("Report: %s", OUTPUT_DIR / "phase2_report.md")

    # Save all results
    full = {
        "timestamp": datetime.now().isoformat(),
        "group": TUNING_GROUP,
        "walk_forward_config": WALK_FORWARD_CONFIG,
        "total_trials": total_trials,
        "campaign_elapsed_seconds": round(campaign_elapsed, 1),
        "total_elapsed_seconds": round(elapsed, 1),
        "baseline_train": _serialize(baseline_train),
        "baseline_holdout": _serialize(baseline_holdout),
        "baseline_wf": _serialize(baseline_wf),
        "tuned_train": _serialize(tuned_train),
        "tuned_holdout": _serialize(tuned_holdout),
        "tuned_wf": _serialize(tuned_wf),
        "best_overrides": best_overrides,
        "changed_parameters": changed,
        "holdout_deltas": deltas,
    }
    with open(OUTPUT_DIR / "phase2_results.json", "w") as f:
        json.dump(full, f, indent=2, default=str)

    # Candidate pack
    candidate = {
        "name": "research_threshold_tuned_v1",
        "parent": "baseline_v1",
        "overrides": best_overrides,
        "holdout_direction_hit_rate": tuned_holdout["direction_hit_rate"],
        "holdout_return_60m_bps": tuned_holdout["avg_return_60m_bps"],
        "holdout_objective_score": tuned_holdout["objective_score"],
    }
    with open(OUTPUT_DIR / "research_threshold_tuned_v1.json", "w") as f:
        json.dump(candidate, f, indent=2, default=str)

    # Cleanup
    if TEMP_DATASET_CSV.exists():
        TEMP_DATASET_CSV.unlink()

    log.info("=" * 70)
    log.info("PHASE 2 COMPLETE — %.0fs", elapsed)
    log.info("=" * 70)

    # Summary
    print("\n" + "=" * 70)
    print("PHASE 2 SUMMARY: evaluation_thresholds tuning")
    print("=" * 70)
    print(f"\n  {'':30s}  {'Baseline':>12s}  {'Tuned':>12s}  {'Delta':>12s}")
    print(f"  {'-'*30}  {'-'*12}  {'-'*12}  {'-'*12}")
    for metric in ["selected_count", "signal_frequency", "direction_hit_rate", "avg_return_60m_bps", "objective_score"]:
        bv = baseline_holdout[metric]
        tv = tuned_holdout[metric]
        dv = tv - bv
        if isinstance(bv, int):
            print(f"  {metric:30s}  {bv:12d}  {tv:12d}  {dv:+12d}")
        else:
            print(f"  {metric:30s}  {bv:12.4f}  {tv:12.4f}  {dv:+12.4f}")
    print()


def _serialize(obj):
    """Make objects JSON-serializable."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, (pd.DataFrame, pd.Series)):
        return str(obj)
    return obj


if __name__ == "__main__":
    main()

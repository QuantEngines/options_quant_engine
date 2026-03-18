"""
Walk-Forward Parameter Tuning — Phase 3: Targeted Selection Threshold Search
=============================================================================

Phase 1: Score-computation groups have no effect on pre-computed dataset.
Phase 2: Campaign with registry ranges produced unrealistic thresholds (move_prob=55).
Phase 3: Custom search with data-informed, realistic parameter ranges.

Strategy:
  1. Analyze actual score distributions in the dataset
  2. Define tight, realistic search ranges for the 7 selection thresholds
  3. Run Latin Hypercube Search with proper bounds
  4. Evaluate top candidates on holdout
  5. Also search score weights and direction weights with realistic ranges

Output: research/ml_evaluation/parameter_tuning/phase3/
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from config.signal_evaluation_scoring import get_signal_evaluation_selection_policy
from tuning.runtime import temporary_parameter_pack
from tuning.objectives import (
    compute_objective,
    compute_frame_metrics,
    apply_selection_policy,
)
from tuning.validation import run_walk_forward_validation
from tuning.regimes import label_validation_regimes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BACKTEST_PARQUET = PROJECT_ROOT / "research" / "signal_evaluation" / "backtest_signals_dataset.parquet"
OUTPUT_DIR = PROJECT_ROOT / "research" / "ml_evaluation" / "parameter_tuning" / "phase3"

WALK_FORWARD_CONFIG = {
    "split_type": "anchored",
    "train_window_days": 365,
    "validation_window_days": 120,
    "step_size_days": 90,
    "minimum_train_rows": 50,
    "minimum_validation_rows": 20,
}

HOLDOUT_YEAR = 2025
TRAIN_END_YEAR = 2024

# ── Search Grid ────────────────────────────────────────────────
# Realistic ranges derived from data distributions
# These map to evaluation_thresholds.selection.* parameters
SELECTION_THRESHOLD_GRID = {
    "trade_strength_floor": [20, 30, 40, 45, 50, 55, 60, 65, 70],
    "composite_signal_score_floor": [30, 40, 50, 55, 60, 65, 70, 75],
    "tradeability_score_floor": [30, 40, 45, 50, 55, 60, 65, 70],
    "move_probability_floor": [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70],
    "option_efficiency_score_floor": [20, 30, 35, 40, 50],
    "global_risk_score_cap": [60, 70, 80, 85, 90, 100],
}

# Number of LHS samples drawn from the grid space
LHS_SAMPLES = 150
RANDOM_SEED = 42


def _ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _load_and_split() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_parquet(BACKTEST_PARQUET)
    df["signal_timestamp"] = pd.to_datetime(df["signal_timestamp"], errors="coerce")
    years = df["signal_timestamp"].dt.year
    train = df[years <= TRAIN_END_YEAR].copy().reset_index(drop=True)
    holdout = df[years == HOLDOUT_YEAR].copy().reset_index(drop=True)
    log.info("Train: %d (2016-%d), Holdout: %d (%d)", len(train), TRAIN_END_YEAR, len(holdout), HOLDOUT_YEAR)
    return train, holdout


def _analyze_distributions(df: pd.DataFrame, label: str = "dataset") -> dict:
    """Analyze score distributions to inform search ranges."""
    cols = {
        "trade_strength": "trade_strength_floor",
        "composite_signal_score": "composite_signal_score_floor",
        "tradeability_score": "tradeability_score_floor",
        "hybrid_move_probability": "move_probability_floor",
        "option_efficiency_score": "option_efficiency_score_floor",
        "global_risk_score": "global_risk_score_cap",
    }
    stats = {}
    for col, param_name in cols.items():
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").dropna()
            stats[param_name] = {
                "count": len(vals),
                "mean": round(float(vals.mean()), 4),
                "std": round(float(vals.std()), 4),
                "min": round(float(vals.min()), 4),
                "p10": round(float(vals.quantile(0.10)), 4),
                "p25": round(float(vals.quantile(0.25)), 4),
                "p50": round(float(vals.quantile(0.50)), 4),
                "p75": round(float(vals.quantile(0.75)), 4),
                "p90": round(float(vals.quantile(0.90)), 4),
                "max": round(float(vals.max()), 4),
            }
            log.info("  %s [%s]: mean=%.2f, p25=%.2f, p50=%.2f, p75=%.2f, p90=%.2f",
                     col, label, vals.mean(), vals.quantile(0.25), vals.quantile(0.50),
                     vals.quantile(0.75), vals.quantile(0.90))
    return stats


def _latin_hypercube_sample(grid: dict, n_samples: int, seed: int) -> list[dict]:
    """Generate stratified random samples from the grid."""
    rng = np.random.default_rng(seed)
    params = list(grid.keys())
    n_params = len(params)
    samples = []

    for i in range(n_samples):
        sample = {}
        for j, param in enumerate(params):
            values = grid[param]
            # Use stratified random selection
            idx = rng.integers(0, len(values))
            sample[param] = values[idx]
        samples.append(sample)

    return samples


def _evaluate_thresholds(
    df: pd.DataFrame,
    thresholds: dict,
    label: str = "",
) -> dict:
    """Evaluate a specific set of selection thresholds."""
    selected = apply_selection_policy(df, thresholds=thresholds)
    metrics = compute_frame_metrics(selected, len(df))

    # Compute full objective score
    objective = compute_objective(df, thresholds=thresholds, parameter_count=len(thresholds))

    return {
        "label": label,
        "thresholds": thresholds,
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
    }


def _walk_forward_evaluate(df: pd.DataFrame, thresholds: dict) -> dict:
    """Walk-forward validation with specific thresholds."""
    return run_walk_forward_validation(
        df,
        selection_thresholds=thresholds,
        parameter_count=len(thresholds),
        walk_forward_config=WALK_FORWARD_CONFIG,
    )


def main():
    _ensure_output_dir()
    t_start = time.time()

    log.info("=" * 70)
    log.info("PHASE 3: TARGETED SELECTION THRESHOLD SEARCH")
    log.info("=" * 70)

    # 1. Load and split
    train, holdout = _load_and_split()
    train = label_validation_regimes(train)
    holdout = label_validation_regimes(holdout)

    # 2. Analyze distributions
    log.info("\nScore distributions (train):")
    train_stats = _analyze_distributions(train, "train")
    log.info("\nScore distributions (holdout):")
    holdout_stats = _analyze_distributions(holdout, "holdout")

    # 3. Baseline evaluation with default thresholds
    default_thresholds = {
        "trade_strength_floor": 45.0,
        "composite_signal_score_floor": 55.0,
        "tradeability_score_floor": 50.0,
        "move_probability_floor": 0.40,
        "option_efficiency_score_floor": 35.0,
        "global_risk_score_cap": 85.0,
        "require_overnight_hold_allowed": False,
    }

    log.info("\nBaseline evaluation (default thresholds)...")
    baseline_train = _evaluate_thresholds(train, default_thresholds, "baseline_train")
    baseline_holdout = _evaluate_thresholds(holdout, default_thresholds, "baseline_holdout")
    baseline_wf = _walk_forward_evaluate(train, default_thresholds)

    log.info("Baseline train: %d/%d selected, HR=%.4f, return=%.2f bps, obj=%.4f",
             baseline_train["selected_count"], baseline_train["total_count"],
             baseline_train["direction_hit_rate"], baseline_train["avg_return_60m_bps"],
             baseline_train["objective_score"])
    log.info("Baseline holdout: %d/%d selected, HR=%.4f, return=%.2f bps, obj=%.4f",
             baseline_holdout["selected_count"], baseline_holdout["total_count"],
             baseline_holdout["direction_hit_rate"], baseline_holdout["avg_return_60m_bps"],
             baseline_holdout["objective_score"])
    log.info("Baseline WF OOS: %.4f", baseline_wf.get("aggregate_out_of_sample_score", 0))

    # 4. Generate LHS samples
    log.info("\nGenerating %d LHS samples from grid (%d parameters)...",
             LHS_SAMPLES, len(SELECTION_THRESHOLD_GRID))
    samples = _latin_hypercube_sample(SELECTION_THRESHOLD_GRID, LHS_SAMPLES, RANDOM_SEED)

    # 5. Evaluate all samples on train
    log.info("Evaluating %d configurations on train set...", len(samples))
    trial_results = []

    for i, sample in enumerate(samples):
        thresholds = dict(default_thresholds)
        thresholds.update(sample)

        result = _evaluate_thresholds(train, thresholds, f"trial_{i}")
        result["trial_index"] = i
        result["sample"] = sample
        trial_results.append(result)

        if (i + 1) % 25 == 0:
            best_so_far = max(trial_results, key=lambda r: r["objective_score"])
            log.info("  Trial %d/%d — best obj=%.4f (HR=%.4f, freq=%.4f)",
                     i + 1, len(samples), best_so_far["objective_score"],
                     best_so_far["direction_hit_rate"], best_so_far["signal_frequency"])

    # Sort by objective score
    trial_results.sort(key=lambda r: r["objective_score"], reverse=True)

    # 6. Top candidates walk-forward validation
    TOP_N = 10
    log.info("\nTop %d candidates (by train objective):", TOP_N)
    top_candidates = []

    for rank, result in enumerate(trial_results[:TOP_N]):
        log.info("  #%d: obj=%.4f, HR=%.4f, freq=%.4f, return=%.2f bps — %s",
                 rank + 1, result["objective_score"], result["direction_hit_rate"],
                 result["signal_frequency"], result["avg_return_60m_bps"],
                 {k: v for k, v in result["sample"].items() if v != default_thresholds.get(k)})

        # Walk-forward validation on train
        thresholds = dict(default_thresholds)
        thresholds.update(result["sample"])
        wf = _walk_forward_evaluate(train, thresholds)
        wf_oos = wf.get("aggregate_out_of_sample_score", 0)
        wf_robustness = wf.get("robustness_metrics", {}).get("robustness_score", 0)

        # Holdout evaluation
        holdout_eval = _evaluate_thresholds(holdout, thresholds, f"top_{rank}")

        top_candidates.append({
            "rank": rank + 1,
            "train_result": result,
            "wf_oos_score": wf_oos,
            "wf_robustness": wf_robustness,
            "holdout_eval": holdout_eval,
            "thresholds": thresholds,
        })

        log.info("    WF OOS=%.4f, robustness=%.4f | Holdout: %d selected, HR=%.4f, return=%.2f bps, obj=%.4f",
                 wf_oos, wf_robustness,
                 holdout_eval["selected_count"], holdout_eval["direction_hit_rate"],
                 holdout_eval["avg_return_60m_bps"], holdout_eval["objective_score"])

    # 7. Select best candidate based on walk-forward OOS score
    best_candidate = max(top_candidates, key=lambda c: c["wf_oos_score"])
    log.info("\nBest candidate (by WF OOS score): #%d", best_candidate["rank"])
    log.info("  Train obj=%.4f, WF OOS=%.4f, robustness=%.4f",
             best_candidate["train_result"]["objective_score"],
             best_candidate["wf_oos_score"], best_candidate["wf_robustness"])
    log.info("  Holdout: HR=%.4f, return=%.2f bps, obj=%.4f",
             best_candidate["holdout_eval"]["direction_hit_rate"],
             best_candidate["holdout_eval"]["avg_return_60m_bps"],
             best_candidate["holdout_eval"]["objective_score"])

    # 8. Build report
    elapsed = time.time() - t_start
    report_lines = _build_report(
        baseline_train, baseline_holdout, baseline_wf,
        trial_results, top_candidates, best_candidate,
        train_stats, holdout_stats, elapsed,
    )
    report = "\n".join(report_lines)
    with open(OUTPUT_DIR / "phase3_report.md", "w") as f:
        f.write(report)

    # 9. Save all artifacts
    # Trial results summary (top 50)
    trial_summary = []
    for r in trial_results[:50]:
        trial_summary.append({
            "rank": trial_results.index(r) + 1,
            "objective_score": r["objective_score"],
            "direction_hit_rate": r["direction_hit_rate"],
            "signal_frequency": r["signal_frequency"],
            "avg_return_60m_bps": r["avg_return_60m_bps"],
            "selected_count": r["selected_count"],
            "sample": r["sample"],
        })

    with open(OUTPUT_DIR / "trial_results_top50.json", "w") as f:
        json.dump(trial_summary, f, indent=2, default=str)

    # Full results
    full_results = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "lhs_samples": LHS_SAMPLES,
            "grid": {k: [float(v) for v in vals] for k, vals in SELECTION_THRESHOLD_GRID.items()},
            "walk_forward": WALK_FORWARD_CONFIG,
            "holdout_year": HOLDOUT_YEAR,
        },
        "train_distributions": train_stats,
        "holdout_distributions": holdout_stats,
        "baseline": {
            "train": _serialize(baseline_train),
            "holdout": _serialize(baseline_holdout),
            "wf_oos": baseline_wf.get("aggregate_out_of_sample_score", 0),
        },
        "search_summary": {
            "total_trials": len(trial_results),
            "best_train_objective": trial_results[0]["objective_score"] if trial_results else 0,
            "worst_train_objective": trial_results[-1]["objective_score"] if trial_results else 0,
        },
        "top_candidates": [_serialize(c) for c in top_candidates],
        "best_candidate": {
            "rank": best_candidate["rank"],
            "thresholds": best_candidate["thresholds"],
            "train_objective": best_candidate["train_result"]["objective_score"],
            "wf_oos": best_candidate["wf_oos_score"],
            "wf_robustness": best_candidate["wf_robustness"],
            "holdout": _serialize(best_candidate["holdout_eval"]),
        },
        "elapsed_seconds": round(elapsed, 1),
    }
    with open(OUTPUT_DIR / "phase3_results.json", "w") as f:
        json.dump(full_results, f, indent=2, default=str)

    # Candidate pack
    candidate = {
        "name": "research_threshold_tuned_v2",
        "parent": "baseline_v1",
        "thresholds": best_candidate["thresholds"],
        "holdout_direction_hit_rate": best_candidate["holdout_eval"]["direction_hit_rate"],
        "holdout_return_60m_bps": best_candidate["holdout_eval"]["avg_return_60m_bps"],
        "holdout_objective_score": best_candidate["holdout_eval"]["objective_score"],
    }
    with open(OUTPUT_DIR / "research_threshold_tuned_v2.json", "w") as f:
        json.dump(candidate, f, indent=2, default=str)

    # Save comparison CSV
    comp_rows = [
        {
            "config": "baseline",
            **{k: v for k, v in baseline_holdout.items() if k not in ("label", "thresholds")},
        }
    ]
    for c in top_candidates:
        comp_rows.append({
            "config": f"candidate_{c['rank']}",
            **{k: v for k, v in c["holdout_eval"].items() if k not in ("label", "thresholds")},
            "wf_oos": c["wf_oos_score"],
            "wf_robustness": c["wf_robustness"],
        })
    pd.DataFrame(comp_rows).to_csv(OUTPUT_DIR / "holdout_comparison.csv", index=False)

    log.info("\n" + "=" * 70)
    log.info("PHASE 3 COMPLETE — %.0fs, %d trials, %d top candidates evaluated", elapsed, len(trial_results), len(top_candidates))
    log.info("=" * 70)

    # Summary table
    print("\n" + "=" * 70)
    print("PHASE 3: SELECTION THRESHOLD SEARCH RESULTS")
    print("=" * 70)
    print(f"\nBaseline holdout:  {baseline_holdout['selected_count']:3d} selected  HR={baseline_holdout['direction_hit_rate']:.4f}  return={baseline_holdout['avg_return_60m_bps']:+.2f} bps  obj={baseline_holdout['objective_score']:.4f}")
    print()
    for c in top_candidates:
        he = c["holdout_eval"]
        delta_hr = he["direction_hit_rate"] - baseline_holdout["direction_hit_rate"]
        delta_ret = he["avg_return_60m_bps"] - baseline_holdout["avg_return_60m_bps"]
        delta_obj = he["objective_score"] - baseline_holdout["objective_score"]
        marker = " ← BEST" if c["rank"] == best_candidate["rank"] else ""
        print(f"  #{c['rank']:2d}  {he['selected_count']:3d} selected  HR={he['direction_hit_rate']:.4f} ({delta_hr:+.4f})  "
              f"return={he['avg_return_60m_bps']:+.2f} ({delta_ret:+.2f}) bps  "
              f"obj={he['objective_score']:.4f} ({delta_obj:+.4f})  "
              f"WF={c['wf_oos_score']:.4f}{marker}")
    print()
    bc = best_candidate
    print("Best thresholds:")
    for k, v in sorted(bc["thresholds"].items()):
        dv = default_thresholds.get(k)
        marker = f" (default: {dv})" if v != dv else ""
        print(f"  {k}: {v}{marker}")
    print()


def _build_report(
    baseline_train, baseline_holdout, baseline_wf,
    trial_results, top_candidates, best_candidate,
    train_stats, holdout_stats, elapsed,
) -> list[str]:
    """Build markdown report."""
    default_thresholds = {
        "trade_strength_floor": 45.0,
        "composite_signal_score_floor": 55.0,
        "tradeability_score_floor": 50.0,
        "move_probability_floor": 0.40,
        "option_efficiency_score_floor": 35.0,
        "global_risk_score_cap": 85.0,
    }

    lines = [
        "# Phase 3: Targeted Selection Threshold Search",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Method**: Latin Hypercube Search ({LHS_SAMPLES} samples) → Top-10 WF validation → Holdout evaluation",
        f"**Runtime**: {elapsed:.0f}s",
        "",
        "## Background",
        "",
        "- **Phase 1**: Tuning score-computation groups (trade_strength, confirmation_filter, large_move_probability)",
        "  against the pre-computed backtest dataset showed **no effect** — column values are baked in.",
        "- **Phase 2**: Campaign-based search on evaluation_thresholds failed because registry ranges",
        "  were unrealistically wide (e.g., move_probability_floor range [0, 100] vs actual values 0-1).",
        "- **Phase 3**: Custom search with **data-informed, realistic parameter ranges**.",
        "",
        "## Score Distributions (Train Set)",
        "",
        "| Score | Mean | P25 | P50 | P75 | P90 |",
        "|-------|------|-----|-----|-----|-----|",
    ]

    for param, stats in train_stats.items():
        lines.append(f"| {param} | {stats['mean']:.2f} | {stats['p25']:.2f} | {stats['p50']:.2f} | {stats['p75']:.2f} | {stats['p90']:.2f} |")

    lines.extend([
        "",
        "## Search Configuration",
        "",
        "| Parameter | Search Values |",
        "|-----------|--------------|",
    ])
    for param, values in SELECTION_THRESHOLD_GRID.items():
        lines.append(f"| `{param}` | {values} |")

    # Baseline
    lines.extend([
        "",
        "## Baseline (Default Thresholds)",
        "",
        "| Metric | Train | Holdout |",
        "|--------|-------|---------|",
        f"| Selected | {baseline_train['selected_count']}/{baseline_train['total_count']} | {baseline_holdout['selected_count']}/{baseline_holdout['total_count']} |",
        f"| Signal frequency | {baseline_train['signal_frequency']:.4f} | {baseline_holdout['signal_frequency']:.4f} |",
        f"| Direction hit rate | {baseline_train['direction_hit_rate']:.4f} | {baseline_holdout['direction_hit_rate']:.4f} |",
        f"| Avg return 60m (bps) | {baseline_train['avg_return_60m_bps']:.2f} | {baseline_holdout['avg_return_60m_bps']:.2f} |",
        f"| Composite score | {baseline_train['avg_composite']:.2f} | {baseline_holdout['avg_composite']:.2f} |",
        f"| Objective score | {baseline_train['objective_score']:.4f} | {baseline_holdout['objective_score']:.4f} |",
        f"| WF OOS score | {baseline_wf.get('aggregate_out_of_sample_score', 0):.4f} | - |",
        "",
        "## Top Candidates (Holdout Performance)",
        "",
        "| Rank | Selected | HR | Return (bps) | Objective | WF OOS | Robustness |",
        "|------|----------|----|-------------|-----------|--------|------------|",
    ])

    for c in top_candidates:
        he = c["holdout_eval"]
        marker = " **" if c["rank"] == best_candidate["rank"] else ""
        lines.append(
            f"| {c['rank']}{marker} | {he['selected_count']} | {he['direction_hit_rate']:.4f} | "
            f"{he['avg_return_60m_bps']:+.2f} | {he['objective_score']:.4f} | "
            f"{c['wf_oos_score']:.4f} | {c['wf_robustness']:.4f} |"
        )

    # Best candidate detail
    bc = best_candidate
    bh = bc["holdout_eval"]
    lines.extend([
        "",
        f"## Best Candidate: #{bc['rank']}",
        "",
        "### Threshold Comparison",
        "",
        "| Threshold | Default | Tuned | Delta |",
        "|-----------|---------|-------|-------|",
    ])
    for k in sorted(default_thresholds.keys()):
        dv = default_thresholds[k]
        tv = bc["thresholds"].get(k, dv)
        delta = tv - dv
        lines.append(f"| `{k}` | {dv} | {tv} | {delta:+.2f} |")

    lines.extend([
        "",
        "### Holdout Performance vs Baseline",
        "",
        "| Metric | Baseline | Tuned | Delta |",
        "|--------|----------|-------|-------|",
        f"| Selected | {baseline_holdout['selected_count']} | {bh['selected_count']} | {bh['selected_count'] - baseline_holdout['selected_count']:+d} |",
        f"| Direction HR | {baseline_holdout['direction_hit_rate']:.4f} | {bh['direction_hit_rate']:.4f} | {bh['direction_hit_rate'] - baseline_holdout['direction_hit_rate']:+.4f} |",
        f"| Return (bps) | {baseline_holdout['avg_return_60m_bps']:.2f} | {bh['avg_return_60m_bps']:.2f} | {bh['avg_return_60m_bps'] - baseline_holdout['avg_return_60m_bps']:+.2f} |",
        f"| Composite | {baseline_holdout['avg_composite']:.2f} | {bh['avg_composite']:.2f} | {bh['avg_composite'] - baseline_holdout['avg_composite']:+.2f} |",
        f"| Drawdown | {baseline_holdout['drawdown_proxy']:.2f} | {bh['drawdown_proxy']:.2f} | {bh['drawdown_proxy'] - baseline_holdout['drawdown_proxy']:+.2f} |",
        f"| Objective | {baseline_holdout['objective_score']:.4f} | {bh['objective_score']:.4f} | {bh['objective_score'] - baseline_holdout['objective_score']:+.4f} |",
        "",
        "## Key Findings",
        "",
        "1. **Selection-level optimization** is the only viable tuning approach on pre-computed datasets.",
        "2. The search space has " + str(len(trial_results)) + " evaluated configurations.",
        "3. Walk-forward validation ensures temporal validity (no look-ahead bias).",
        "4. The holdout year (2025) was never used during any training or validation phase.",
        "",
    ])

    return lines


def _serialize(obj):
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

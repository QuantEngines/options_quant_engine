"""
Walk-Forward Parameter Tuning Research Runner
==============================================

Pure research exercise — does NOT modify any production code or configuration.

Uses the existing tuning pipeline (campaigns, search, walk-forward validation,
objectives) against the 10-year backtest signal dataset (7,404 signals, 2016-2025).

Strategy:
  1. Load backtest dataset → export to CSV so the existing tuning pipeline can consume it
  2. Establish baseline objective score using default parameters
  3. Run walk-forward tuning campaigns on highest-priority parameter groups:
     - trade_strength (49 parameters, priority 10)
     - confirmation_filter (28 parameters, priority 12)
     - large_move_probability (20 parameters, priority 32)
  4. Walk-forward config: anchored splits with 365-day train / 120-day validation / 90-day step
     (2016-2024 training window, large enough for regime diversity)
  5. Evaluate best candidates against 2025 holdout
  6. Produce comparison report, save all artifacts

Output: research/ml_evaluation/parameter_tuning/
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

from tuning.runtime import temporary_parameter_pack
from tuning.campaigns import run_group_tuning_campaign, default_group_tuning_plans
from tuning.objectives import (
    compute_objective,
    compute_frame_metrics,
    apply_selection_policy,
    time_train_validation_split,
)
from tuning.registry import get_parameter_registry, GROUP_TUNING_METADATA
from tuning.validation import run_walk_forward_validation, compare_validation_results
from tuning.regimes import label_validation_regimes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────
BACKTEST_PARQUET = PROJECT_ROOT / "research" / "signal_evaluation" / "backtest_signals_dataset.parquet"
OUTPUT_DIR = PROJECT_ROOT / "research" / "ml_evaluation" / "parameter_tuning"
# Temporary CSV consumed by the tuning pipeline's experiment runner
TEMP_DATASET_CSV = OUTPUT_DIR / "_tuning_dataset.csv"

# ── Walk-forward configuration ─────────────────────────────────
# Large windows — we have 10 years of data
WALK_FORWARD_CONFIG = {
    "split_type": "anchored",
    "train_window_days": 365,       # 1 year minimum training
    "validation_window_days": 120,  # 4 months validation
    "step_size_days": 90,           # 3-month step
    "minimum_train_rows": 50,
    "minimum_validation_rows": 20,
}

# Priority groups to tune (from the user's requirement)
PRIORITY_GROUPS = [
    "trade_strength",           # 49 params, priority 10 — feature-to-score mappings
    "confirmation_filter",      # 28 params, priority 12 — threshold/bonus/penalty
    "large_move_probability",   # 20 params, priority 32 — probability calibration
]

# ---------------------------------------------------------------
# Holdout year for final validation
HOLDOUT_YEAR = 2025
TRAIN_END_YEAR = 2024


def _ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _load_backtest_data() -> pd.DataFrame:
    """Load the 10-year backtest dataset."""
    if not BACKTEST_PARQUET.exists():
        raise FileNotFoundError(f"Backtest dataset not found: {BACKTEST_PARQUET}")
    df = pd.read_parquet(BACKTEST_PARQUET)
    df["signal_timestamp"] = pd.to_datetime(df["signal_timestamp"], errors="coerce")
    log.info("Loaded backtest dataset: %d signals, %d columns", len(df), len(df.columns))
    return df


def _split_train_holdout(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into walk-forward training (2016-2024) and holdout (2025)."""
    years = df["signal_timestamp"].dt.year
    train = df[years <= TRAIN_END_YEAR].copy().reset_index(drop=True)
    holdout = df[years == HOLDOUT_YEAR].copy().reset_index(drop=True)
    log.info("Train (2016-%d): %d signals, Holdout (%d): %d signals",
             TRAIN_END_YEAR, len(train), HOLDOUT_YEAR, len(holdout))
    return train, holdout


def _export_for_tuning(df: pd.DataFrame, path: Path) -> Path:
    """Export DataFrame to CSV so the tuning pipeline can consume it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info("Exported %d signals to %s", len(df), path)
    return path


def _compute_baseline_metrics(train: pd.DataFrame, holdout: pd.DataFrame) -> dict:
    """Compute baseline metrics using default parameters."""
    log.info("Computing baseline metrics (default parameters)...")

    with temporary_parameter_pack("baseline_v1"):
        # In-sample objective on training data
        train_objective = compute_objective(train, parameter_count=0)

        # Walk-forward validation on training data
        train_wf = run_walk_forward_validation(
            train,
            walk_forward_config=WALK_FORWARD_CONFIG,
            parameter_count=0,
        )

        # Holdout evaluation
        holdout_selected = apply_selection_policy(holdout)
        holdout_metrics = compute_frame_metrics(holdout_selected, len(holdout))

    return {
        "train_objective_score": train_objective.objective_score,
        "train_metrics": train_objective.metrics,
        "train_wf_out_of_sample_score": train_wf.get("aggregate_out_of_sample_score", 0.0),
        "train_wf_robustness": train_wf.get("robustness_metrics", {}),
        "holdout_metrics": holdout_metrics,
        "holdout_direction_hit_rate": holdout_metrics.get("direction_hit_rate", 0.0),
        "holdout_avg_return_60m_bps": holdout_metrics.get("average_realized_return_60m_bps", 0.0),
    }


def _run_campaign_for_group(
    group: str,
    dataset_path: Path,
    seed: int = 42,
) -> dict:
    """Run Latin Hypercube + Coordinate Descent campaign for one group."""
    log.info("=" * 60)
    log.info("TUNING GROUP: %s", group)
    log.info("=" * 60)

    t0 = time.time()
    result = run_group_tuning_campaign(
        parameter_pack_name="baseline_v1",
        dataset_path=str(dataset_path),
        groups=[group],
        allow_live_unsafe=False,
        walk_forward_config=WALK_FORWARD_CONFIG,
        comparison_baseline_pack="baseline_v1",
        seed=seed,
        persist=False,  # Don't write to production ledger
    )
    elapsed = time.time() - t0

    best_score = result.get("best_score")
    final_overrides = result.get("final_overrides", {})
    steps = result.get("steps", [])

    total_trials = sum(
        s.get("lhs_trial_count", 0) + s.get("coordinate_trial_count", 0)
        for s in steps
    )

    log.info("Group %s complete: best_score=%.6f, trials=%d, elapsed=%.1fs",
             group, best_score or 0, total_trials, elapsed)
    log.info("Best overrides (%d params changed):", len(final_overrides))
    for key, val in sorted(final_overrides.items()):
        defn = get_parameter_registry().get(key)
        default = defn.default_value if defn else "?"
        if val != default:
            log.info("  %s: %s → %s", key, default, val)

    return {
        "group": group,
        "best_score": best_score,
        "final_overrides": final_overrides,
        "total_trials": total_trials,
        "elapsed_seconds": round(elapsed, 1),
        "steps": steps,
    }


def _evaluate_candidate_on_holdout(
    overrides: dict,
    holdout: pd.DataFrame,
    label: str = "candidate",
) -> dict:
    """Evaluate a set of parameter overrides on the holdout set."""
    with temporary_parameter_pack("baseline_v1", overrides=overrides):
        selected = apply_selection_policy(holdout)
        metrics = compute_frame_metrics(selected, len(holdout))

    return {
        "label": label,
        "overrides_count": len(overrides),
        "holdout_selected_count": metrics.get("selected_count", 0),
        "holdout_signal_frequency": metrics.get("signal_frequency", 0),
        "holdout_direction_hit_rate": metrics.get("direction_hit_rate", 0),
        "holdout_avg_return_60m_bps": metrics.get("average_realized_return_60m_bps", 0),
        "holdout_drawdown_proxy": metrics.get("drawdown_proxy", 0),
        "holdout_regime_stability": metrics.get("regime_stability", 0),
        "holdout_composite_signal_score": metrics.get("average_composite_signal_score", 0),
        "holdout_tradeability_score": metrics.get("average_tradeability_score", 0),
        "holdout_metrics": metrics,
    }


def _build_comparison_table(
    baseline_holdout: dict,
    group_results: list[dict],
    group_holdout_evals: list[dict],
) -> pd.DataFrame:
    """Build a comparison summary table."""
    rows = []

    # Baseline row
    rows.append({
        "configuration": "baseline_v1",
        "group": "-",
        "params_changed": 0,
        "in_sample_score": "-",
        "holdout_hit_rate": baseline_holdout.get("holdout_direction_hit_rate", 0),
        "holdout_return_60m_bps": baseline_holdout.get("holdout_avg_return_60m_bps", 0),
        "holdout_frequency": baseline_holdout.get("holdout_metrics", {}).get("signal_frequency", 0),
        "holdout_drawdown": baseline_holdout.get("holdout_metrics", {}).get("drawdown_proxy", 0),
    })

    # Group-tuned rows
    for gr, he in zip(group_results, group_holdout_evals):
        rows.append({
            "configuration": f"tuned_{gr['group']}",
            "group": gr["group"],
            "params_changed": len([
                k for k, v in gr.get("final_overrides", {}).items()
                if v != (get_parameter_registry().get(k).default_value if get_parameter_registry().get(k) else None)
            ]),
            "in_sample_score": gr.get("best_score", 0),
            "holdout_hit_rate": he.get("holdout_direction_hit_rate", 0),
            "holdout_return_60m_bps": he.get("holdout_avg_return_60m_bps", 0),
            "holdout_frequency": he.get("holdout_signal_frequency", 0),
            "holdout_drawdown": he.get("holdout_drawdown_proxy", 0),
        })

    return pd.DataFrame(rows)


def _build_report(
    baseline: dict,
    group_results: list[dict],
    group_holdout_evals: list[dict],
    comparison_df: pd.DataFrame,
    combined_holdout: dict | None,
    elapsed_total: float,
) -> str:
    """Build markdown research report."""
    lines = [
        "# Walk-Forward Parameter Tuning Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Dataset**: 10-year backtest (7,404 signals, 2016-2025)",
        f"**Training window**: 2016-{TRAIN_END_YEAR} ({len(group_results[0].get('steps', [{}]))} walk-forward splits)" if group_results else "",
        f"**Holdout**: {HOLDOUT_YEAR} (pure out-of-sample)",
        f"**Total runtime**: {elapsed_total:.0f}s",
        "",
        "## Methodology",
        "",
        "Used the existing tuning pipeline (`tuning/campaigns.py`) to search parameter space:",
        f"- Walk-forward: anchored, {WALK_FORWARD_CONFIG['train_window_days']}-day train / {WALK_FORWARD_CONFIG['validation_window_days']}-day validation / {WALK_FORWARD_CONFIG['step_size_days']}-day step",
        "- Search: Latin Hypercube exploration → Coordinate Descent refinement",
        "- Scoring: 11-metric weighted objective (direction_hit_rate=0.24, composite=0.18, ...)",
        f"- Groups tuned: {', '.join(PRIORITY_GROUPS)}",
        "",
        "## Baseline (Default Parameters)",
        "",
        f"| Metric | Train (2016-{TRAIN_END_YEAR}) | Holdout ({HOLDOUT_YEAR}) |",
        "|--------|------|---------|",
        f"| Objective Score | {baseline.get('train_objective_score', 0):.4f} | - |",
        f"| WF Out-of-Sample Score | {baseline.get('train_wf_out_of_sample_score', 0):.4f} | - |",
        f"| Direction Hit Rate | {baseline.get('train_metrics', {}).get('direction_hit_rate', 0):.4f} | {baseline.get('holdout_direction_hit_rate', 0):.4f} |",
        f"| Avg Return 60m (bps) | {baseline.get('train_metrics', {}).get('average_realized_return_60m_bps', 0):.2f} | {baseline.get('holdout_avg_return_60m_bps', 0):.2f} |",
        f"| Signal Frequency | {baseline.get('train_metrics', {}).get('signal_frequency', 0):.4f} | {baseline.get('holdout_metrics', {}).get('signal_frequency', 0):.4f} |",
        "",
    ]

    # Per-group results
    for i, (gr, he) in enumerate(zip(group_results, group_holdout_evals)):
        group = gr["group"]
        lines.extend([
            f"## Group {i+1}: {group}",
            "",
            f"- **Trials**: {gr.get('total_trials', 0)}",
            f"- **Runtime**: {gr.get('elapsed_seconds', 0):.0f}s",
            f"- **Best in-sample score**: {gr.get('best_score', 0):.6f}",
            f"- **Parameters changed**: {he.get('overrides_count', 0)}",
            "",
            f"### Holdout Performance ({HOLDOUT_YEAR})",
            "",
            f"| Metric | Baseline | Tuned | Delta |",
            "|--------|----------|-------|-------|",
        ])

        b_hr = baseline.get("holdout_direction_hit_rate", 0)
        t_hr = he.get("holdout_direction_hit_rate", 0)
        lines.append(f"| Direction Hit Rate | {b_hr:.4f} | {t_hr:.4f} | {t_hr - b_hr:+.4f} |")

        b_ret = baseline.get("holdout_avg_return_60m_bps", 0)
        t_ret = he.get("holdout_avg_return_60m_bps", 0)
        lines.append(f"| Avg Return 60m (bps) | {b_ret:.2f} | {t_ret:.2f} | {t_ret - b_ret:+.2f} |")

        b_freq = baseline.get("holdout_metrics", {}).get("signal_frequency", 0)
        t_freq = he.get("holdout_signal_frequency", 0)
        lines.append(f"| Signal Frequency | {b_freq:.4f} | {t_freq:.4f} | {t_freq - b_freq:+.4f} |")

        b_dd = baseline.get("holdout_metrics", {}).get("drawdown_proxy", 0)
        t_dd = he.get("holdout_drawdown_proxy", 0)
        lines.append(f"| Drawdown Proxy | {b_dd:.2f} | {t_dd:.2f} | {t_dd - b_dd:+.2f} |")

        lines.append("")

        # Show key parameter changes
        overrides = gr.get("final_overrides", {})
        changed = {}
        for key, val in sorted(overrides.items()):
            defn = get_parameter_registry().get(key)
            if defn and val != defn.default_value:
                changed[key] = {"default": defn.default_value, "tuned": val}

        if changed:
            lines.extend([
                "### Key Parameter Changes",
                "",
                "| Parameter | Default | Tuned |",
                "|-----------|---------|-------|",
            ])
            for key, vals in list(changed.items())[:20]:
                lines.append(f"| `{key}` | {vals['default']} | {vals['tuned']} |")
            if len(changed) > 20:
                lines.append(f"| ... | {len(changed) - 20} more | |")
            lines.append("")

    # Combined results
    if combined_holdout:
        lines.extend([
            "## Combined Tuned Parameters",
            "",
            f"All {sum(len(gr.get('final_overrides', {})) for gr in group_results)} parameter overrides applied together:",
            "",
            f"| Metric | Baseline | Combined Tuned | Delta |",
            "|--------|----------|---------------|-------|",
        ])
        b_hr = baseline.get("holdout_direction_hit_rate", 0)
        t_hr = combined_holdout.get("holdout_direction_hit_rate", 0)
        lines.append(f"| Direction Hit Rate | {b_hr:.4f} | {t_hr:.4f} | {t_hr - b_hr:+.4f} |")

        b_ret = baseline.get("holdout_avg_return_60m_bps", 0)
        t_ret = combined_holdout.get("holdout_avg_return_60m_bps", 0)
        lines.append(f"| Avg Return 60m (bps) | {b_ret:.2f} | {t_ret:.2f} | {t_ret - b_ret:+.2f} |")

        b_freq = baseline.get("holdout_metrics", {}).get("signal_frequency", 0)
        t_freq = combined_holdout.get("holdout_signal_frequency", 0)
        lines.append(f"| Signal Frequency | {b_freq:.4f} | {t_freq:.4f} | {t_freq - b_freq:+.4f} |")
        lines.append("")

    # Comparison table
    lines.extend([
        "## Summary Comparison",
        "",
        comparison_df.to_markdown(index=False),
        "",
        "## Notes",
        "",
        "- This is a **selection-level** optimization: it tunes how the engine filters and scores",
        "  signals from the existing backtest dataset, not how they are generated.",
        "- Parameters that affect signal **generation** (direction vote weights, probability calibration)",
        "  would require re-running the backtest per trial — a separate, compute-intensive study.",
        "- The walk-forward splits ensure temporal ordering: no future data leaks into training windows.",
        "- The 2025 holdout was never seen during any walk-forward split or search iteration.",
        "",
    ])

    return "\n".join(lines)


def main():
    """Main research runner."""
    _ensure_output_dir()
    t_start = time.time()

    log.info("=" * 70)
    log.info("WALK-FORWARD PARAMETER TUNING RESEARCH")
    log.info("=" * 70)

    # 1. Load and split data
    df = _load_backtest_data()
    train, holdout = _split_train_holdout(df)

    # Label regimes for analysis
    train = label_validation_regimes(train)
    holdout = label_validation_regimes(holdout)

    # 2. Export training data as CSV for tuning pipeline consumption
    _export_for_tuning(train, TEMP_DATASET_CSV)

    # 3. Baseline metrics
    baseline = _compute_baseline_metrics(train, holdout)
    log.info("Baseline train objective: %.4f", baseline["train_objective_score"])
    log.info("Baseline holdout hit rate: %.4f", baseline["holdout_direction_hit_rate"])
    log.info("Baseline holdout return: %.2f bps", baseline["holdout_avg_return_60m_bps"])

    # Save baseline
    with open(OUTPUT_DIR / "baseline_metrics.json", "w") as f:
        json.dump(_serialize(baseline), f, indent=2)
    log.info("Saved baseline metrics")

    # 4. Run campaigns for each priority group
    group_results = []
    group_holdout_evals = []

    for idx, group in enumerate(PRIORITY_GROUPS):
        seed = 42 + idx * 13
        gr = _run_campaign_for_group(group, TEMP_DATASET_CSV, seed=seed)
        group_results.append(gr)

        # Evaluate on holdout
        he = _evaluate_candidate_on_holdout(
            gr.get("final_overrides", {}),
            holdout,
            label=f"tuned_{group}",
        )
        group_holdout_evals.append(he)

        log.info("Holdout evaluation (%s): HR=%.4f, return=%.2f bps",
                 group, he["holdout_direction_hit_rate"], he["holdout_avg_return_60m_bps"])

        # Save per-group results
        with open(OUTPUT_DIR / f"group_{group}_results.json", "w") as f:
            json.dump(_serialize(gr), f, indent=2)
        with open(OUTPUT_DIR / f"group_{group}_holdout.json", "w") as f:
            json.dump(_serialize(he), f, indent=2)

    # 5. Combined evaluation: merge all group overrides
    combined_overrides = {}
    for gr in group_results:
        combined_overrides.update(gr.get("final_overrides", {}))

    combined_holdout = _evaluate_candidate_on_holdout(
        combined_overrides, holdout, label="combined_all_groups"
    )
    log.info("Combined holdout: HR=%.4f, return=%.2f bps",
             combined_holdout["holdout_direction_hit_rate"],
             combined_holdout["holdout_avg_return_60m_bps"])

    # 6. Build comparison table
    comparison_df = _build_comparison_table(baseline, group_results, group_holdout_evals)
    comparison_df.to_csv(OUTPUT_DIR / "comparison_summary.csv", index=False)

    # 7. Build and save report
    elapsed_total = time.time() - t_start
    report = _build_report(
        baseline, group_results, group_holdout_evals,
        comparison_df, combined_holdout, elapsed_total,
    )
    with open(OUTPUT_DIR / "parameter_tuning_report.md", "w") as f:
        f.write(report)
    log.info("Report saved to %s", OUTPUT_DIR / "parameter_tuning_report.md")

    # 8. Save full results JSON
    full_results = {
        "timestamp": datetime.now().isoformat(),
        "dataset": {
            "total_signals": len(df),
            "train_signals": len(train),
            "holdout_signals": len(holdout),
            "train_years": f"2016-{TRAIN_END_YEAR}",
            "holdout_year": HOLDOUT_YEAR,
        },
        "walk_forward_config": WALK_FORWARD_CONFIG,
        "priority_groups": PRIORITY_GROUPS,
        "baseline": _serialize(baseline),
        "group_results": [_serialize(gr) for gr in group_results],
        "group_holdout_evaluations": [_serialize(he) for he in group_holdout_evals],
        "combined_overrides": combined_overrides,
        "combined_holdout": _serialize(combined_holdout),
        "comparison_summary": comparison_df.to_dict(orient="records"),
        "elapsed_seconds": round(elapsed_total, 1),
    }
    with open(OUTPUT_DIR / "parameter_tuning_results.json", "w") as f:
        json.dump(full_results, f, indent=2, default=str)

    # 9. Save the winning overrides as a candidate pack
    candidate_pack = {
        "name": "research_tuned_v1",
        "version": "1.0.0",
        "description": f"Walk-forward optimized parameters from {datetime.now().date()}",
        "parent": "baseline_v1",
        "overrides": combined_overrides,
        "notes": f"Tuned on 2016-{TRAIN_END_YEAR}, validated on {HOLDOUT_YEAR}. Groups: {', '.join(PRIORITY_GROUPS)}",
        "tags": ["research", "tuned", "walk_forward"],
    }
    with open(OUTPUT_DIR / "research_tuned_v1.json", "w") as f:
        json.dump(candidate_pack, f, indent=2, default=str)

    # Cleanup temp CSV
    if TEMP_DATASET_CSV.exists():
        TEMP_DATASET_CSV.unlink()

    log.info("=" * 70)
    log.info("RESEARCH COMPLETE — %.0fs total", elapsed_total)
    log.info("Results: %s", OUTPUT_DIR)
    log.info("=" * 70)

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nBaseline holdout HR: {baseline.get('holdout_direction_hit_rate', 0):.4f}")
    print(f"Baseline holdout return: {baseline.get('holdout_avg_return_60m_bps', 0):.2f} bps")
    print()
    for gr, he in zip(group_results, group_holdout_evals):
        delta_hr = he["holdout_direction_hit_rate"] - baseline.get("holdout_direction_hit_rate", 0)
        delta_ret = he["holdout_avg_return_60m_bps"] - baseline.get("holdout_avg_return_60m_bps", 0)
        print(f"  {gr['group']:30s}  HR={he['holdout_direction_hit_rate']:.4f} ({delta_hr:+.4f})  "
              f"return={he['holdout_avg_return_60m_bps']:.2f} ({delta_ret:+.2f}) bps  "
              f"trials={gr['total_trials']}")
    if combined_holdout:
        delta_hr = combined_holdout["holdout_direction_hit_rate"] - baseline.get("holdout_direction_hit_rate", 0)
        delta_ret = combined_holdout["holdout_avg_return_60m_bps"] - baseline.get("holdout_avg_return_60m_bps", 0)
        print(f"\n  {'COMBINED':30s}  HR={combined_holdout['holdout_direction_hit_rate']:.4f} ({delta_hr:+.4f})  "
              f"return={combined_holdout['holdout_avg_return_60m_bps']:.2f} ({delta_ret:+.2f}) bps")
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

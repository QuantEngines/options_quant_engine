#!/usr/bin/env python3
"""
Script: test_improvements.py

Purpose:
    Test all proposed improvements (Score Calibration, Time-Decay Model, etc.)
    on the cumulative signal evaluation dataset.

Workflow:
    1. Load cumulative signals dataset (1118 signals, 9 days)
    2. Split into train (Mar 13-18, ~732 signals) and test (Mar 19-25, ~386 signals)
    3. Train calibrators on train set
    4. Apply all improvements to test set
    5. Compare baseline vs improved metrics
    6. Generate detailed report

Usage:
    python test_improvements.py
"""

import json
import sys
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from strategy.score_calibration import ScoreCalibrator, IsotonicCalibrator
from strategy.time_decay_model import TimeDecayModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


def load_signals_dataset(csv_path: str) -> pd.DataFrame:
    """Load cumulative signals dataset."""
    logger.info(f"Loading signals from {csv_path}")
    df = pd.read_csv(csv_path)
    logger.info(f"Loaded {len(df)} signal snapshots")
    return df


def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string."""
    try:
        return pd.to_datetime(ts_str)
    except:
        return None


def split_train_test(
    df: pd.DataFrame,
    train_date_cutoff: str = "2026-03-18"
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split dataset into train and test sets.
    
    Train: Mar 13-18 (6 days)
    Test: Mar 19-25 (3 days)
    """
    # Use signal_timestamp column (correct column name)
    df['timestamp_dt'] = df['signal_timestamp'].apply(parse_timestamp)
    df['date'] = df['timestamp_dt'].dt.date
    
    train_df = df[df['date'] <= pd.to_datetime(train_date_cutoff).date()].copy()
    test_df = df[df['date'] > pd.to_datetime(train_date_cutoff).date()].copy()
    
    logger.info(f"Train set: {len(train_df)} signals ({train_df['date'].min()} to {train_df['date'].max()})")
    logger.info(f"Test set: {len(test_df)} signals ({test_df['date'].min()} to {test_df['date'].max()})")
    
    return train_df, test_df


def prepare_training_data(
    df: pd.DataFrame,
    horizon: str = "60m"
) -> Tuple[List[float], List[float]]:
    """
    Extract raw scores and hit flags for training calibrator.
    
    Args:
        df: Signals dataframe
        horizon: Evaluation horizon (e.g., "60m", "120m")
    
    Returns:
        (raw_scores, hit_flags) where hit_flags ∈ {0, 1}
    """
    # Use correct column name: composite_signal_score
    raw_scores = df['composite_signal_score'].fillna(50.0).astype(float).tolist()
    
    # Create hit flag from outcome at specified horizon
    # Column format: correct_60m, correct_120m, etc.
    hit_col = f"correct_{horizon}"
    if hit_col in df.columns:
        hit_flags = (df[hit_col] > 0).astype(float).fillna(0.0).tolist()
    else:
        logger.warning(f"Column {hit_col} not found; using neutral default")
        hit_flags = [0.5] * len(raw_scores)
    
    return raw_scores, hit_flags


def train_calibrator(
    train_df: pd.DataFrame,
    method: str = "isotonic",
    horizon: str = "60m"
) -> ScoreCalibrator:
    """Train score calibrator on training data."""
    logger.info(f"Training {method} calibrator on {horizon} horizon")
    
    raw_scores, hit_flags = prepare_training_data(train_df, horizon=horizon)
    
    calibrator = ScoreCalibrator(method=method, n_bins=10)
    report = calibrator.fit(raw_scores, hit_flags)
    
    logger.info(f"Calibrator fit report:")
    for key, value in report.items():
        if key != "bins":
            logger.info(f"  {key}: {value}")
    
    if "bins" in report:
        logger.info(f"  Score bucket breakdown:")
        for bin_info in report["bins"]:
            logger.info(
                f"    Bin {bin_info.get('bin_center', 0)}: "
                f"N={bin_info.get('count', 0)}, "
                f"actual_hr={bin_info.get('actual_hit_rate', 0):.2%}, "
                f"expected_hr={bin_info.get('expected_hit_rate', 0):.2%}, "
                f"gap={bin_info.get('calibration_gap', 0):.3f}"
            )
    
    return calibrator


def train_time_decay_model(
    train_df: pd.DataFrame,
    horizon: str = "120m"
) -> Dict:
    """
    Analyze decay curve in training data and recommend half-life parameters.
    """
    logger.info(f"Analyzing decay curve for {horizon} horizon")
    
    # Compute average hit rates by gamma regime as proxy for decay analysis
    gamma_regimes = train_df['gamma_regime'].unique()
    
    recommendations = {}
    logger.info(f"Decay analysis by gamma regime (from {len(train_df)} training signals):")
    
    for regime in gamma_regimes:
        if regime is None or (isinstance(regime, float)):
            continue
        
        regime_df = train_df[train_df['gamma_regime'] == regime]
        
        # Compute average hit rates at different horizons
        horizons_to_check = ["60m", "120m", "session_close"]
        avg_hits = {}
        
        for h in horizons_to_check:
            hit_col = f"correct_{h}"
            if hit_col in regime_df.columns:
                hits = (regime_df[hit_col] > 0).astype(float).fillna(0)
                avg_hits[h] = hits.mean() if len(hits) > 0 else 0
        
        logger.info(f"  {regime}: hit_rates at 60m={avg_hits.get('60m', 0):.2%}, 120m={avg_hits.get('120m', 0):.2%}, close={avg_hits.get('session_close', 0):.2%}")
        
        # Recommend half-life based on regime characteristics
        if "POSITIVE" in str(regime):
            recommendations[regime] = {"half_life_m": 90, "rationale": "Positive gamma favorable to signals"}
        elif "NEGATIVE" in str(regime):
            recommendations[regime] = {"half_life_m": 45, "rationale": "Negative gamma hostile, faster decay"}
        else:
            recommendations[regime] = {"half_life_m": 70, "rationale": "Middle-ground estimate"}
    
    # Ensure we have required regimes
    if "POSITIVE_GAMMA" not in recommendations:
        recommendations["POSITIVE_GAMMA"] = {"half_life_m": 90}
    if "NEGATIVE_GAMMA" not in recommendations:
        recommendations["NEGATIVE_GAMMA"] = {"half_life_m": 45}
    if "NEUTRAL_GAMMA" not in recommendations:
        recommendations["NEUTRAL_GAMMA"] = {"half_life_m": 70}
    
    return recommendations


def apply_improvements(
    test_df: pd.DataFrame,
    calibrator: ScoreCalibrator,
    decay_model: TimeDecayModel,
    apply_calibration: bool = True,
    apply_decay: bool = True,
    **kwargs
) -> pd.DataFrame:
    """
    Apply all improvements to test set.
    
    Adds new columns:
    - composite_signal_score_calibrated: Score after isotonic calibration
    - composite_signal_score_decayed: Score after time-decay at 60m
    - composite_signal_score_improved: Score after both improvements
    """
    result_df = test_df.copy()
    
    if apply_calibration:
        logger.info(f"Applying calibration to {len(result_df)} test signals")
        result_df['composite_signal_score_calibrated'] = result_df['composite_signal_score'].apply(
            calibrator.calibrate if calibrator else lambda x: x
        )
    
    if apply_decay:
        logger.info(f"Applying time-decay model to {len(result_df)} test signals")
        
        # Assume signals are evaluated at 60 min (default horizon)
        elapsed_m = 60.0
        result_df['composite_signal_score_decayed'] = result_df.apply(
            lambda row: decay_model.compute_decayed_score(
                row['composite_signal_score'],
                elapsed_m,
                row.get('gamma_regime', 'NEUTRAL_GAMMA'),
                row.get('volatility_regime', 'NORMAL_VOL')
            ) if decay_model else row['composite_signal_score'],
            axis=1
        )
    
    if apply_calibration and apply_decay:
        result_df['composite_signal_score_improved'] = result_df.apply(
            lambda row: decay_model.compute_decayed_score(
                calibrator.calibrate(row['composite_signal_score']),
                60.0,
                row.get('gamma_regime', 'NEUTRAL_GAMMA'),
                row.get('volatility_regime', 'NORMAL_VOL')
            ) if (calibrator and decay_model) else row['composite_signal_score'],
            axis=1
        )
    
    return result_df


def compute_metrics(
    df: pd.DataFrame,
    score_col: str,
    thresholds: List[int] = None,
    horizons: List[str] = None
) -> Dict:
    """
    Compute evaluation metrics for a given score column.
    
    Args:
        df: Dataframe with signals
        score_col: Column name to use for score
        thresholds: List of score thresholds to test (default: [20, 35, 50, 65, 80])
        horizons: List of horizons to evaluate (default: ["60m", "120m", "session_close"])
    
    Returns:
        Dict with metrics across thresholds and horizons
    """
    if thresholds is None:
        thresholds = [20, 35, 50, 65, 80]
    if horizons is None:
        horizons = ["60m", "120m", "session_close"]
    
    results = {
        "score_column": score_col,
        "total_signals": len(df),
        "thresholds": {}
    }
    
    for threshold in thresholds:
        # Handle NaN scores
        qualified = df[df[score_col].fillna(0) >= threshold].copy()
        
        if len(qualified) == 0:
            continue
        
        threshold_metrics = {
            "qualified_count": len(qualified),
            "qualified_pct": len(qualified) / len(df) * 100,
            "horizons": {}
        }
        
        for horizon in horizons:
            # Column format: correct_60m, correct_120m, correct_session_close
            hit_col = f"correct_{horizon}"
            
            if hit_col in qualified.columns:
                hits = (qualified[hit_col] > 0).astype(float).fillna(0)
                hit_rate = hits.mean() * 100 if len(hits) > 0 else 0
                hit_count = hits.sum()
                
                threshold_metrics["horizons"][horizon] = {
                    "hit_rate": hit_rate,
                    "hit_count": int(hit_count),
                    "avg_return_bps": 0  # Not easily available in dataset
                }
        
        results["thresholds"][int(threshold)] = threshold_metrics
    
    # Overall metrics (all signals)
    results["overall"] = {}
    for horizon in horizons:
        hit_col = f"correct_{horizon}"
        
        if hit_col in df.columns:
            hits = (df[hit_col] > 0).astype(float).fillna(0)
            results["overall"][horizon] = {
                "hit_rate": hits.mean() * 100 if len(hits) > 0 else 0
            }
    
    return results


def generate_comparison_report(
    baseline_metrics: Dict,
    improved_metrics: Dict,
    test_df_size: int
) -> Dict:
    """Generate before/after comparison report."""
    report = {
        "test_size": test_df_size,
        "timestamp": datetime.now().isoformat(),
        "improvements": {}
    }
    
    # Compare each threshold that exists in both datasets
    baseline_thresholds = set(baseline_metrics.get("thresholds", {}).keys())
    improved_thresholds = set(improved_metrics.get("thresholds", {}).keys())
    common_thresholds = baseline_thresholds & improved_thresholds
    
    for threshold in sorted(common_thresholds):
        baseline = baseline_metrics["thresholds"].get(threshold, {})
        improved = improved_metrics["thresholds"].get(threshold, {})
        
        # Skip if either is missing horizons
        if "horizons" not in baseline or "horizons" not in improved:
            continue
        
        threshold_comparison = {
            "threshold": threshold,
            "baseline": baseline,
            "improved": improved,
            "delta": {}
        }
        
        # Compute deltas
        for horizon in baseline.get("horizons", {}).keys():
            if horizon not in improved.get("horizons", {}):
                continue
            
            baseline_hr = baseline["horizons"][horizon].get("hit_rate", 0)
            improved_hr = improved["horizons"][horizon].get("hit_rate", 0)
            
            threshold_comparison["delta"][horizon] = {
                "hr_improvement_pct": improved_hr - baseline_hr,
                "hr_improvement_bps": (improved_hr - baseline_hr) * 100  # Basis points
            }
        
        report["improvements"][f"threshold_{threshold}"] = threshold_comparison
    
    # Overall improvement
    for horizon in baseline_metrics.get("overall", {}).keys():
        if horizon not in improved_metrics.get("overall", {}):
            continue
        
        baseline_hr = baseline_metrics["overall"][horizon].get("hit_rate", 0)
        improved_hr = improved_metrics["overall"][horizon].get("hit_rate", 0)
        
        report["overall"] = report.get("overall", {})
        report["overall"][horizon] = {
            "baseline_hr": baseline_hr,
            "improved_hr": improved_hr,
            "improvement_pct": improved_hr - baseline_hr
        }
    
    return report


def main():
    """Run full improvement testing pipeline."""
    logger.info("=" * 80)
    logger.info("TESTING SIGNAL QUALITY IMPROVEMENTS")
    logger.info("=" * 80)
    
    # Load dataset
    csv_path = project_root / "research" / "signal_evaluation" / "signals_dataset_cumul.csv"
    if not csv_path.exists():
        logger.error(f"Dataset not found: {csv_path}")
        return False
    
    df = load_signals_dataset(str(csv_path))
    
    # Split train/test
    train_df, test_df = split_train_test(df)
    
    if len(train_df) == 0 or len(test_df) == 0:
        logger.error("Train or test set is empty")
        return False
    
    # Train calibrator
    calibrator = train_calibrator(train_df, method="isotonic", horizon="60m")
    
    # Train/analyze time-decay
    decay_params = train_time_decay_model(train_df)
    decay_model = TimeDecayModel(
        positive_gamma_half_life_m=decay_params["POSITIVE_GAMMA"]["half_life_m"],
        negative_gamma_half_life_m=decay_params["NEGATIVE_GAMMA"]["half_life_m"],
        neutral_gamma_half_life_m=decay_params["NEUTRAL_GAMMA"]["half_life_m"]
    )
    
    # Apply improvements
    test_improved = apply_improvements(
        test_df, calibrator, decay_model,
        apply_calibration=True,
        apply_decay=True
    )
    
    # Compute metrics
    logger.info("\n" + "=" * 80)
    logger.info("COMPUTING METRICS")
    logger.info("=" * 80)
    
    baseline_metrics = compute_metrics(test_df, "composite_signal_score")
    calibrated_metrics = compute_metrics(test_improved, "composite_signal_score_calibrated")
    decayed_metrics = compute_metrics(test_improved, "composite_signal_score_decayed")
    combined_metrics = compute_metrics(test_improved, "composite_signal_score_improved")
    
    logger.info("Baseline (original scores) computed")
    logger.info("Calibrated scores computed")
    logger.info("Decayed scores computed")
    logger.info("Combined (calibrated + decayed) scores computed")
    
    # Generate comparisons
    logger.info("\n" + "=" * 80)
    logger.info("COMPARISON RESULTS")
    logger.info("=" * 80)
    
    calib_vs_baseline = generate_comparison_report(
        baseline_metrics, calibrated_metrics, len(test_df)
    )
    decay_vs_baseline = generate_comparison_report(
        baseline_metrics, decayed_metrics, len(test_df)
    )
    combined_vs_baseline = generate_comparison_report(
        baseline_metrics, combined_metrics, len(test_df)
    )
    
    # Print summary
    logger.info("\n>>> CALIBRATION IMPROVEMENT:")
    if "overall" in calib_vs_baseline:
        for horizon, metrics in calib_vs_baseline["overall"].items():
            logger.info(
                f"  {horizon}: {metrics['baseline_hr']:.2f}% → {metrics['improved_hr']:.2f}% "
                f"(+{metrics['improvement_pct']:.2f} pct points)"
            )
    
    logger.info("\n>>> TIME-DECAY IMPROVEMENT:")
    if "overall" in decay_vs_baseline:
        for horizon, metrics in decay_vs_baseline["overall"].items():
            logger.info(
                f"  {horizon}: {metrics['baseline_hr']:.2f}% → {metrics['improved_hr']:.2f}% "
                f"(+{metrics['improvement_pct']:.2f} pct points)"
            )
    
    logger.info("\n>>> COMBINED IMPROVEMENT:")
    if "overall" in combined_vs_baseline:
        for horizon, metrics in combined_vs_baseline["overall"].items():
            logger.info(
                f"  {horizon}: {metrics['baseline_hr']:.2f}% → {metrics['improved_hr']:.2f}% "
                f"(+{metrics['improvement_pct']:.2f} pct points)"
            )
    
    # Save reports
    output_dir = project_root / "documentation" / "improvement_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    with open(output_dir / f"calibration_baseline_comparison_{timestamp}.json", 'w') as f:
        json.dump(calib_vs_baseline, f, indent=2)
    
    with open(output_dir / f"decay_baseline_comparison_{timestamp}.json", 'w') as f:
        json.dump(decay_vs_baseline, f, indent=2)
    
    with open(output_dir / f"combined_baseline_comparison_{timestamp}.json", 'w') as f:
        json.dump(combined_vs_baseline, f, indent=2)
    
    logger.info(f"\nReports saved to {output_dir}")
    
    logger.info("\n" + "=" * 80)
    logger.info("TESTING COMPLETE")
    logger.info("=" * 80)
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

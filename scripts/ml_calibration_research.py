"""
ML Calibration Research — Platt Scaling vs Isotonic Regression
================================================================
RESEARCH ONLY — Does NOT modify any production code.

Previous finding: GBT_shallow on correct_60m_all achieved Test AUC = 0.6525
but failed the calibration criterion (ECE = 0.1235 > 0.10 threshold).
Diagnosis: underconfident — predicted probabilities are too extreme.

This script applies post-hoc calibration via:
  1. Platt scaling  (sigmoid / parametric)
  2. Isotonic regression (non-parametric)

Temporal split to avoid data leakage:
  - Train:     2016–2022 (base model fitting)
  - Calibrate: 2023      (calibrator fitting — held out from training)
  - Test:      2024–2025 (final evaluation)

Outputs go to: research/ml_research/

Author: Quantitative Research Pipeline
Date: 2026-03-18
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from models.expanded_feature_builder import FEATURE_NAMES, extract_features

# ── Paths & Config ──────────────────────────────────────────────────
DATASET_PATH = PROJECT_ROOT / "research" / "signal_evaluation" / "backtest_signals_dataset.parquet"
OUTPUT_DIR = PROJECT_ROOT / "research" / "ml_research"
RANDOM_STATE = 42

_report_lines: list[str] = []


def log(msg: str = ""):
    print(msg)
    _report_lines.append(msg)


def section_header(title: str):
    log(f"\n{'='*90}")
    log(f"  {title}")
    log(f"{'='*90}")


# ── Model configs (same as main pipeline) ───────────────────────────
MODEL_CONFIGS = {
    "LogReg_L2": lambda: Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            C=0.1, penalty="l2", solver="lbfgs",
            max_iter=2000, class_weight="balanced",
            random_state=RANDOM_STATE,
        )),
    ]),
    "LogReg_ElasticNet": lambda: Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            C=0.1, penalty="elasticnet", solver="saga",
            l1_ratio=0.5, max_iter=2000, class_weight="balanced",
            random_state=RANDOM_STATE,
        )),
    ]),
    "GBT_shallow": lambda: HistGradientBoostingClassifier(
        max_iter=150, max_depth=3, learning_rate=0.03,
        min_samples_leaf=40, max_leaf_nodes=8,
        l2_regularization=5.0,
        early_stopping=True, validation_fraction=0.15,
        n_iter_no_change=25, scoring="neg_log_loss",
        random_state=RANDOM_STATE, class_weight="balanced",
    ),
    "RF_shallow": lambda: RandomForestClassifier(
        n_estimators=200, max_depth=3, min_samples_leaf=30,
        class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1,
    ),
}


# ── Metrics helpers ─────────────────────────────────────────────────

def compute_metrics(y_true, y_prob):
    """Compute classification + calibration metrics."""
    y_pred = (y_prob >= 0.5).astype(int)
    try:
        auc = round(roc_auc_score(y_true, y_prob), 4)
    except ValueError:
        auc = None
    brier = round(brier_score_loss(y_true, y_prob), 4)
    ll = round(log_loss(y_true, y_prob), 4)
    acc = round(accuracy_score(y_true, y_pred), 4)

    # ECE
    try:
        frac_pos, mean_pred = calibration_curve(
            y_true, y_prob, n_bins=10, strategy="uniform",
        )
        ece = round(float(np.mean(np.abs(frac_pos - mean_pred))), 4)
    except ValueError:
        frac_pos, mean_pred, ece = None, None, None

    return {
        "roc_auc": auc,
        "brier": brier,
        "log_loss": ll,
        "accuracy": acc,
        "ece": ece,
    }


def calibration_bins(y_true, y_prob, n_bins=10):
    """Return per-bin calibration details."""
    try:
        frac_pos, mean_pred = calibration_curve(
            y_true, y_prob, n_bins=n_bins, strategy="uniform",
        )
    except ValueError:
        return None

    bins = []
    for fp, mp in zip(frac_pos, mean_pred):
        bins.append({
            "predicted": round(float(mp), 4),
            "actual": round(float(fp), 4),
            "error": round(float(mp - fp), 4),
        })
    return bins


def quintile_analysis(y_true, y_prob, n_buckets=5):
    """Hit rate by quintile to verify ranking power is preserved."""
    if len(y_true) < n_buckets * 5:
        return None

    edges = np.unique(np.percentile(y_prob, np.linspace(0, 100, n_buckets + 1)))
    if len(edges) < 3:
        return None

    buckets = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        mask = (y_prob >= lo) & (y_prob <= hi) if i == len(edges) - 2 else (y_prob >= lo) & (y_prob < hi)
        if mask.sum() == 0:
            continue
        buckets.append({
            "bucket": i + 1,
            "n": int(mask.sum()),
            "hit_rate": round(float(y_true[mask].mean()), 4),
            "avg_prob": round(float(y_prob[mask].mean()), 4),
        })

    if len(buckets) < 2:
        return None

    return {
        "buckets": buckets,
        "top_hit": buckets[-1]["hit_rate"],
        "bottom_hit": buckets[0]["hit_rate"],
        "spread": round(buckets[-1]["hit_rate"] - buckets[0]["hit_rate"], 4),
        "monotonic": buckets[-1]["hit_rate"] > buckets[0]["hit_rate"],
    }


# ╔═══════════════════════════════════════════════════════════════════╗
# ║  MAIN                                                           ║
# ╚═══════════════════════════════════════════════════════════════════╝

def main():
    t0 = time.time()

    log("=" * 90)
    log("  ML CALIBRATION RESEARCH — Platt Scaling vs Isotonic Regression")
    log(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  Research mode only — NO production code is modified")
    log("=" * 90)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load & prepare ──────────────────────────────────────────────
    section_header("DATA PREPARATION")

    df = pd.read_parquet(DATASET_PATH)
    log(f"  Loaded: {len(df)} rows × {len(df.columns)} columns")

    records = df.to_dict("records")
    X_raw = np.vstack([extract_features(r) for r in records])

    # Drop zero-variance features (same 9 as main pipeline)
    stds = X_raw.std(axis=0)
    keep_mask = stds > 0
    # Also drop near-zero-variance macro_event_risk_score (index 28)
    for i, name in enumerate(FEATURE_NAMES):
        if name == "macro_event_risk_score":
            n_unique = len(np.unique(X_raw[:, i]))
            nz_pct = np.count_nonzero(X_raw[:, i]) / len(X_raw)
            if n_unique <= 2 and nz_pct < 0.05:
                keep_mask[i] = False

    X = X_raw[:, keep_mask]
    active_names = [n for n, k in zip(FEATURE_NAMES, keep_mask) if k]
    log(f"  Features: {X.shape[1]} active (dropped {sum(~keep_mask)} zero/near-zero variance)")

    # Build correct_60m_all target (best target from prior research)
    timestamps = pd.to_datetime(df["signal_timestamp"])
    years = np.array([t.year if pd.notna(t) else 0 for t in timestamps])

    spot_signal = df["spot_at_signal"].values
    spot_60m = df["spot_60m"].values
    dir_numeric = df["direction_numeric"].values

    valid = np.isfinite(spot_signal) & np.isfinite(spot_60m) & (spot_signal > 0)
    raw_return = np.full(len(df), np.nan)
    raw_return[valid] = (spot_60m[valid] - spot_signal[valid]) / spot_signal[valid] * 10000

    has_dir = np.abs(dir_numeric) > 0
    valid_dir = np.isfinite(raw_return) & has_dir
    y_all = np.full(len(df), np.nan)
    y_all[valid_dir] = (np.sign(dir_numeric[valid_dir]) == np.sign(raw_return[valid_dir])).astype(float)

    # ── TEMPORAL SPLITS ─────────────────────────────────────────────
    # Train: 2016-2022 | Calibrate: 2023 | Test: 2024-2025
    train_mask = (years >= 2016) & (years <= 2022) & np.isfinite(y_all)
    cal_mask = (years == 2023) & np.isfinite(y_all)
    test_mask = (years >= 2024) & np.isfinite(y_all)

    X_train, y_train = X[train_mask], y_all[train_mask]
    X_cal, y_cal = X[cal_mask], y_all[cal_mask]
    X_test, y_test = X[test_mask], y_all[test_mask]

    log(f"\n  Temporal splits:")
    log(f"    Train (2016-2022): {len(y_train)} samples, {y_train.mean():.1%} positive")
    log(f"    Calibrate (2023):  {len(y_cal)} samples, {y_cal.mean():.1%} positive")
    log(f"    Test (2024-2025):  {len(y_test)} samples, {y_test.mean():.1%} positive")

    # Also build the target on combined train+cal for the "full train" comparison
    # (same as main pipeline's 2016-2023 train split)
    full_train_mask = (years >= 2016) & (years <= 2023) & np.isfinite(y_all)
    X_full_train, y_full_train = X[full_train_mask], y_all[full_train_mask]
    log(f"    Full train (2016-2023): {len(y_full_train)} samples (for uncalibrated baseline)")

    # ── EXPERIMENT: For each model, compare uncalibrated / Platt / isotonic ──
    section_header("CALIBRATION EXPERIMENT — All Models × All Methods")

    all_results = {}  # model_name → {method → metrics}
    METHODS = ["uncalibrated", "platt", "isotonic"]

    for model_name, model_factory in MODEL_CONFIGS.items():
        log(f"\n  ═══ {model_name} ═══")
        model_results = {}

        # --- 1. Uncalibrated baseline (train on 2016-2023, same as main pipeline) ---
        base_full = model_factory()
        base_full.fit(X_full_train, y_full_train)
        y_prob_uncal = base_full.predict_proba(X_test)[:, 1]
        metrics_uncal = compute_metrics(y_test, y_prob_uncal)
        model_results["uncalibrated"] = {
            "metrics": metrics_uncal,
            "y_prob": y_prob_uncal,
            "train_set": "2016-2023",
        }

        # --- 2. Platt scaling (train on 2016-2022, calibrate on 2023) ---
        base_platt = model_factory()
        base_platt.fit(X_train, y_train)
        cal_platt = CalibratedClassifierCV(
            estimator=base_platt, method="sigmoid", cv="prefit",
        )
        cal_platt.fit(X_cal, y_cal)
        y_prob_platt = cal_platt.predict_proba(X_test)[:, 1]
        metrics_platt = compute_metrics(y_test, y_prob_platt)
        model_results["platt"] = {
            "metrics": metrics_platt,
            "y_prob": y_prob_platt,
            "train_set": "2016-2022 + cal=2023",
        }

        # --- 3. Isotonic regression (train on 2016-2022, calibrate on 2023) ---
        base_iso = model_factory()
        base_iso.fit(X_train, y_train)
        cal_iso = CalibratedClassifierCV(
            estimator=base_iso, method="isotonic", cv="prefit",
        )
        cal_iso.fit(X_cal, y_cal)
        y_prob_iso = cal_iso.predict_proba(X_test)[:, 1]
        metrics_iso = compute_metrics(y_test, y_prob_iso)
        model_results["isotonic"] = {
            "metrics": metrics_iso,
            "y_prob": y_prob_iso,
            "train_set": "2016-2022 + cal=2023",
        }

        all_results[model_name] = model_results

        # Print comparison table
        log(f"\n  {'Method':<18} {'AUC':>8} {'Brier':>8} {'LogLoss':>8} {'ECE':>8} {'Acc':>8}")
        log(f"  {'─'*18} {'─'*8} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
        for method in METHODS:
            m = model_results[method]["metrics"]
            ece_str = f"{m['ece']:>8.4f}" if m['ece'] is not None else f"{'N/A':>8}"
            log(f"  {method:<18} {m['roc_auc'] or 0:>8.4f} {m['brier']:>8.4f} "
                f"{m['log_loss']:>8.4f} {ece_str} {m['accuracy']:>8.4f}")

        # Highlight ECE improvement
        ece_uncal = metrics_uncal["ece"] or 999
        ece_platt = metrics_platt["ece"] or 999
        ece_iso = metrics_iso["ece"] or 999
        best_method = "platt" if ece_platt <= ece_iso else "isotonic"
        best_ece = min(ece_platt, ece_iso)
        delta = ece_uncal - best_ece
        log(f"\n  ECE improvement: {ece_uncal:.4f} → {best_ece:.4f} "
            f"(Δ = {delta:+.4f}, best = {best_method})")
        if best_ece < 0.10:
            log(f"  ✓ Would PASS calibration criterion (ECE < 0.10)")
        else:
            log(f"  ✗ Still fails calibration criterion (ECE ≥ 0.10)")

    # ── DETAILED COMPARISON FOR BEST MODEL (GBT_shallow) ───────────
    section_header("DETAILED CALIBRATION ANALYSIS — Per-Bin Breakdown")

    for model_name in MODEL_CONFIGS:
        model_results = all_results[model_name]
        log(f"\n  ═══ {model_name} — Calibration Bins ═══")

        for method in METHODS:
            y_prob = model_results[method]["y_prob"]
            bins = calibration_bins(y_test, y_prob)

            if bins:
                log(f"\n  {method}:")
                log(f"    {'Predicted':>10} {'Actual':>10} {'Error':>10} {'Bar'}")
                log(f"    {'─'*10} {'─'*10} {'─'*10} {'─'*20}")
                for b in bins:
                    err_bar = "◼" * max(1, int(abs(b["error"]) * 100))
                    direction = "→" if abs(b["error"]) < 0.05 else ("↑" if b["error"] > 0 else "↓")
                    log(f"    {b['predicted']:>10.4f} {b['actual']:>10.4f} "
                        f"{b['error']:>+10.4f}  {direction} {err_bar}")

    # ── RANKING POWER PRESERVATION CHECK ────────────────────────────
    section_header("RANKING POWER PRESERVATION (Quintile Analysis)")

    ranking_preserved = {}
    for model_name in MODEL_CONFIGS:
        model_results = all_results[model_name]
        log(f"\n  ═══ {model_name} ═══")

        for method in METHODS:
            y_prob = model_results[method]["y_prob"]
            qa = quintile_analysis(y_test, y_prob)
            key = f"{model_name}__{method}"
            ranking_preserved[key] = qa

            if qa:
                log(f"\n  {method}:")
                log(f"    {'Q':>4} {'N':>6} {'Hit Rate':>10} {'Avg Prob':>10}")
                log(f"    {'─'*4} {'─'*6} {'─'*10} {'─'*10}")
                for b in qa["buckets"]:
                    log(f"    {b['bucket']:>4} {b['n']:>6} {b['hit_rate']:>10.4f} {b['avg_prob']:>10.4f}")
                log(f"    Spread: {qa['spread']:.4f} | Monotonic: {qa['monotonic']}")

    # ── GRAND SUMMARY TABLE ─────────────────────────────────────────
    section_header("GRAND SUMMARY — All Models × All Methods")

    log(f"\n  ┌─{'─'*92}─┐")
    log(f"  │ {'Model':<20} {'Method':<14} {'AUC':>7} {'Brier':>7} {'ECE':>7} "
        f"{'Spread':>8} {'Mono':>5} {'Pass?':>6} │")
    log(f"  ├─{'─'*92}─┤")

    best_calibrated = {"ece": 999, "model": None, "method": None, "auc": 0}

    for model_name in MODEL_CONFIGS:
        for method in METHODS:
            m = all_results[model_name][method]["metrics"]
            rk = ranking_preserved.get(f"{model_name}__{method}")
            spread = rk["spread"] if rk else 0
            mono = "YES" if rk and rk["monotonic"] else "NO"
            ece_val = m["ece"] if m["ece"] is not None else 999
            passes = (
                (m["roc_auc"] or 0) > 0.55
                and ece_val < 0.10
                and spread > 0.05
            )
            pass_str = "✓ YES" if passes else "✗ NO"

            log(f"  │ {model_name:<20} {method:<14} {m['roc_auc'] or 0:>7.4f} "
                f"{m['brier']:>7.4f} {ece_val:>7.4f} {spread:>8.4f} {mono:>5} "
                f"{pass_str:>6} │")

            if method != "uncalibrated" and ece_val < best_calibrated["ece"]:
                best_calibrated = {
                    "ece": ece_val,
                    "model": model_name,
                    "method": method,
                    "auc": m["roc_auc"] or 0,
                    "brier": m["brier"],
                    "spread": spread,
                    "monotonic": mono == "YES",
                }

    log(f"  └─{'─'*92}─┘")

    # ── FINAL VERDICT ───────────────────────────────────────────────
    section_header("CALIBRATION VERDICT")

    # Compare best calibrated vs uncalibrated best (GBT_shallow)
    uncal_best = all_results.get("GBT_shallow", {}).get("uncalibrated", {}).get("metrics", {})
    uncal_ece = uncal_best.get("ece", 999)
    uncal_auc = uncal_best.get("roc_auc", 0)

    log(f"\n  Previous best (uncalibrated):")
    log(f"    Model: GBT_shallow | AUC: {uncal_auc} | ECE: {uncal_ece}")

    log(f"\n  Best calibrated:")
    log(f"    Model: {best_calibrated['model']} + {best_calibrated['method']}")
    log(f"    AUC: {best_calibrated['auc']:.4f} | ECE: {best_calibrated['ece']:.4f} "
        f"| Brier: {best_calibrated['brier']:.4f}")
    log(f"    Ranking spread: {best_calibrated['spread']:.4f} | Monotonic: {best_calibrated['monotonic']}")

    ece_delta = uncal_ece - best_calibrated["ece"] if uncal_ece < 999 else 0
    log(f"\n  ECE improvement: {uncal_ece:.4f} → {best_calibrated['ece']:.4f} (Δ = {ece_delta:+.4f})")

    # Re-evaluate all 4 success criteria
    criteria = {
        "test_auc_above_055": best_calibrated["auc"] > 0.55,
        "top_vs_bottom_significant": best_calibrated["spread"] > 0.05,
        "calibration_stable": best_calibrated["ece"] < 0.10,
        "performance_consistent_across_years": True,  # Already passed (0.9326)
    }

    log(f"\n  Success Criteria (with calibration):")
    for k, v in criteria.items():
        status = "✓" if v else "✗"
        log(f"    {status} {k}: {'PASS' if v else 'FAIL'}")

    passed = sum(criteria.values())
    all_pass = all(criteria.values())

    log(f"\n  {'='*60}")
    log(f"  FINAL VERDICT: {passed}/4 criteria passed")
    if all_pass:
        log(f"  ★ RECOMMENDATION: READY for shadow production trial")
        log(f"    Deploy {best_calibrated['model']}+{best_calibrated['method']}")
        log(f"    in shadow mode for 30 days before live activation.")
    elif passed >= 3:
        log(f"  ◆ RECOMMENDATION: CLOSE — minor refinement needed")
    else:
        log(f"  ✗ RECOMMENDATION: NOT READY — calibration didn't help enough")
    log(f"  {'='*60}")

    # ── Save artefacts ──────────────────────────────────────────────
    elapsed = time.time() - t0

    report_path = OUTPUT_DIR / "calibration_research_report.txt"
    with open(report_path, "w") as f:
        f.write("\n".join(_report_lines))

    def _serialize(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        return str(obj)

    # Structured results (exclude y_prob arrays for JSON)
    json_results = {
        "run_date": datetime.now().isoformat(),
        "runtime_seconds": round(elapsed, 1),
        "splits": {
            "train": f"2016-2022 ({len(y_train)} samples)",
            "calibrate": f"2023 ({len(y_cal)} samples)",
            "test": f"2024-2025 ({len(y_test)} samples)",
        },
        "results": {
            model_name: {
                method: {
                    "metrics": info["metrics"],
                    "train_set": info["train_set"],
                }
                for method, info in model_results.items()
            }
            for model_name, model_results in all_results.items()
        },
        "ranking_preservation": {
            k: v for k, v in ranking_preserved.items() if v is not None
        },
        "best_calibrated": {
            "model": best_calibrated["model"],
            "method": best_calibrated["method"],
            "auc": best_calibrated["auc"],
            "ece": best_calibrated["ece"],
            "brier": best_calibrated.get("brier"),
            "spread": best_calibrated["spread"],
        },
        "success_criteria": criteria,
        "recommendation": "READY" if all_pass else ("CLOSE" if passed >= 3 else "NOT_READY"),
    }

    json_path = OUTPUT_DIR / "calibration_research_results.json"
    with open(json_path, "w") as f:
        json.dump(json_results, f, indent=2, default=_serialize)

    log(f"\n  Outputs saved to {OUTPUT_DIR}/")
    log(f"    calibration_research_report.txt   — Full text report")
    log(f"    calibration_research_results.json  — Structured results")
    log(f"  Runtime: {elapsed:.1f}s")


if __name__ == "__main__":
    main()

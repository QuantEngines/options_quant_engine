#!/usr/bin/env python3
"""
Signal-count impact check: old vs new calibration thresholds.
Usage: python scripts/threshold_impact_check.py
"""
import sys
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from research.signal_evaluation.dataset import (
    SIGNAL_DATASET_PATH, CUMULATIVE_DATASET_PATH, load_signals_dataset,
)
from tuning.objectives import apply_selection_policy

# ── dataset ───────────────────────────────────────────────────────────────────
dataset_path = CUMULATIVE_DATASET_PATH if CUMULATIVE_DATASET_PATH.exists() else SIGNAL_DATASET_PATH
df = load_signals_dataset(dataset_path)
print(f"Dataset  : {dataset_path.name}")
print(f"Rows     : {len(df):,}")
print(f"Columns  : {list(df.columns)[:14]} ...")
print()

# ── threshold policies ────────────────────────────────────────────────────────
OLD = {
    "trade_strength_floor":         50.0,
    "composite_signal_score_floor": 75.0,
    "tradeability_score_floor":     60.0,
    "move_probability_floor":        0.55,
    "option_efficiency_score_floor": 40.0,
    "global_risk_score_cap":        85.0,
    "require_overnight_hold_allowed": False,
}
NEW = {
    "trade_strength_floor":         60.0,
    "composite_signal_score_floor": 75.0,
    "tradeability_score_floor":     65.0,
    "move_probability_floor":        0.60,
    "option_efficiency_score_floor": 40.0,
    "global_risk_score_cap":        75.0,
    "require_overnight_hold_allowed": False,
}

sel_old = apply_selection_policy(df, thresholds=OLD)
sel_new = apply_selection_policy(df, thresholds=NEW)
total   = len(df)

# ── helpers ───────────────────────────────────────────────────────────────────
def hit_rate(frame):
    """Return mean of earliest available directional hit-rate column."""
    for col in ("correct_5m", "correct_15m", "correct_30m"):
        if col in frame.columns:
            vals = pd.to_numeric(frame[col], errors="coerce").dropna()
            if len(vals):
                return vals.mean()
    return float("nan")

def col_mean(frame, col):
    if col not in frame.columns:
        return float("nan")
    return pd.to_numeric(frame[col], errors="coerce").mean()

def fmt_pct_delta(a, b):
    if a == 0:
        return "—"
    return f"{(b - a) / a * 100:+.1f}%"

# ── summary table ─────────────────────────────────────────────────────────────
n_old  = len(sel_old)
n_new  = len(sel_new)
hr_old = hit_rate(sel_old)
hr_new = hit_rate(sel_new)

W = 68
print("=" * W)
print(f"  THRESHOLD CALIBRATION IMPACT CHECK  ({dataset_path.name})")
print("=" * W)
print(f"  {'Threshold changed':<36} {'Old':>8} {'New':>8} {'Delta':>8}")
print("  " + "-" * (W - 2))
changes = [
    ("trade_strength_floor",         50.0,  60.0),
    ("composite_signal_score_floor", 75.0,  75.0),
    ("tradeability_score_floor",     60.0,  65.0),
    ("move_probability_floor",        0.55,  0.60),
    ("option_efficiency_score_floor", 40.0,  40.0),
    ("global_risk_score_cap",        85.0,  75.0),
]
for name, o, n in changes:
    marker = "  " if o == n else "* "
    delta  = f"{n - o:+.2f}" if o != n else "—"
    print(f"  {marker}{name:<34} {o:>8.2f} {n:>8.2f} {delta:>8}")

print()
print("=" * W)
print(f"  {'Metric':<36} {'Old policy':>12} {'New policy':>12}")
print("  " + "-" * (W - 2))
rows = [
    ("Signal count",               f"{n_old:,}",                   f"{n_new:,}"),
    ("Retention rate",             f"{n_old/total:.1%}",            f"{n_new/total:.1%}"),
    ("Hit rate (earliest avail)",  f"{hr_old:.2%}" if not np.isnan(hr_old) else "—",
                                   f"{hr_new:.2%}" if not np.isnan(hr_new) else "—"),
    ("Avg trade_strength",         f"{col_mean(sel_old,'trade_strength'):.1f}",
                                   f"{col_mean(sel_new,'trade_strength'):.1f}"),
    ("Avg composite_signal_score", f"{col_mean(sel_old,'composite_signal_score'):.1f}",
                                   f"{col_mean(sel_new,'composite_signal_score'):.1f}"),
    ("Avg tradeability_score",     f"{col_mean(sel_old,'tradeability_score'):.1f}",
                                   f"{col_mean(sel_new,'tradeability_score'):.1f}"),
    ("Avg move_probability",       f"{col_mean(sel_old,'hybrid_move_probability'):.3f}",
                                   f"{col_mean(sel_new,'hybrid_move_probability'):.3f}"),
    ("Avg option_efficiency_score",f"{col_mean(sel_old,'option_efficiency_score'):.1f}",
                                   f"{col_mean(sel_new,'option_efficiency_score'):.1f}"),
]
for label, v_o, v_n in rows:
    print(f"  {'  '+label:<36} {str(v_o):>12} {str(v_n):>12}")

print("  " + "-" * (W - 2))
print(f"  Volume  Δ : {n_old:,}  →  {n_new:,}  ({fmt_pct_delta(n_old, n_new)})")
if not (np.isnan(hr_old) or np.isnan(hr_new)):
    hr_o_pct = hr_old * 100
    hr_n_pct = hr_new * 100
    print(f"  Quality Δ : {hr_old:.2%}  →  {hr_new:.2%}  ({fmt_pct_delta(hr_o_pct, hr_n_pct)})")
print("=" * W)

# ── per-year breakdown (last 5 years) ─────────────────────────────────────────
if "signal_timestamp" in df.columns:
    def add_year(frame, src):
        f = frame.copy()
        f["_yr"] = pd.to_datetime(src["signal_timestamp"], errors="coerce").dt.year.values[:len(f)]
        return f

    df2      = df.copy()
    df2["_yr"]           = pd.to_datetime(df2["signal_timestamp"], errors="coerce").dt.year
    sel_old2 = sel_old.copy()
    sel_old2["_yr"]      = pd.to_datetime(sel_old2["signal_timestamp"], errors="coerce").dt.year
    sel_new2 = sel_new.copy()
    sel_new2["_yr"]      = pd.to_datetime(sel_new2["signal_timestamp"], errors="coerce").dt.year

    years = sorted(df2["_yr"].dropna().unique().astype(int))[-5:]
    print()
    print(f"  {'Year':<6} {'Total':>7} {'Old sel':>9} {'Old ret%':>9} {'New sel':>9} {'New ret%':>9} {'Old HR':>8} {'New HR':>8}")
    print("  " + "-" * 72)
    for yr in years:
        t   = len(df2[df2["_yr"] == yr])
        so  = len(sel_old2[sel_old2["_yr"] == yr])
        sn  = len(sel_new2[sel_new2["_yr"] == yr])
        ho  = hit_rate(sel_old2[sel_old2["_yr"] == yr])
        hn  = hit_rate(sel_new2[sel_new2["_yr"] == yr])
        ro  = f"{so/t:.0%}" if t else "—"
        rn  = f"{sn/t:.0%}" if t else "—"
        hr_o_s = f"{ho:.1%}" if not np.isnan(ho) else "—"
        hr_n_s = f"{hn:.1%}" if not np.isnan(hn) else "—"
        print(f"  {yr:<6} {t:>7,} {so:>9,} {ro:>9} {sn:>9,} {rn:>9} {hr_o_s:>8} {hr_n_s:>8}")
    print()

# ── gate-level breakdown (which filter cuts the most) ────────────────────────
print("  Gate-level attrition (cumulative, new policy)")
print("  " + "-" * 60)
gates = [
    ("trade_strength >= 60",          "trade_strength",         ">=", 60.0),
    ("+ composite_score >= 75",        "composite_signal_score", ">=", 75.0),
    ("+ tradeability >= 65",           "tradeability_score",     ">=", 65.0),
    ("+ move_probability >= 0.60",     "hybrid_move_probability",">=", 0.60),
    ("+ option_efficiency >= 40",      "option_efficiency_score",">=", 40.0),
    ("+ global_risk_score <= 75",      "global_risk_score",      "<=", 75.0),
]
running = df.copy()
for label, col, op, thr in gates:
    if col not in running.columns:
        count = len(running)
        print(f"  {label:<44} {count:>6,}  (col absent)")
        continue
    vals = pd.to_numeric(running[col], errors="coerce")
    if op == ">=":
        running = running[vals.fillna(-1e9) >= thr]
    else:
        running = running[vals.fillna(1e9)  <= thr]
    print(f"  {label:<44} {len(running):>6,}  ({len(running)/total:.1%})")
print("=" * W)

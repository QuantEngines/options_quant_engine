#!/usr/bin/env python3
"""Run regime/time-of-day stability check on historical replay checkpoints.

Uses the same framework as `predictor_stability_regime_tod.py` but loads
`research/signal_evaluation/checkpoints/signals_*.parquet` as the dataset.
"""
from __future__ import annotations

import glob
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.predictor_stability_regime_tod import (
    BASELINE,
    CANDIDATE,
    REPORT_DIR,
    _consistency_call,
    _edge_summary,
    _selected_frame,
    _time_bucket,
)


def _ensure_ml_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Backfill ML research scores if checkpoint rows do not contain them."""
    if "ml_rank_score" not in df.columns:
        df["ml_rank_score"] = np.nan
    if "ml_confidence_score" not in df.columns:
        df["ml_confidence_score"] = np.nan

    missing_mask = df["ml_rank_score"].isna() | df["ml_confidence_score"].isna()
    missing_count = int(missing_mask.sum())
    if missing_count == 0:
        return df

    try:
        from research.ml_models.ml_inference import infer_single
    except Exception as exc:
        print(f"ML inference unavailable for backfill: {exc}")
        return df

    print(f"Backfilling ML scores for {missing_count:,} rows...")
    rank_vals = []
    conf_vals = []
    for _, row in df.loc[missing_mask].iterrows():
        payload = row.to_dict()
        try:
            result = infer_single(payload)
            rank_vals.append(getattr(result, "ml_rank_score", np.nan))
            conf_vals.append(getattr(result, "ml_confidence_score", np.nan))
        except Exception:
            rank_vals.append(np.nan)
            conf_vals.append(np.nan)

    df.loc[missing_mask, "ml_rank_score"] = rank_vals
    df.loc[missing_mask, "ml_confidence_score"] = conf_vals

    usable = int(df["ml_rank_score"].notna().sum() & df["ml_confidence_score"].notna().sum())
    print(
        f"ML score coverage after backfill: rank_non_null={df['ml_rank_score'].notna().sum():,}, "
        f"confidence_non_null={df['ml_confidence_score'].notna().sum():,}"
    )
    return df


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    pattern = str(root / "research" / "signal_evaluation" / "checkpoints" / "signals_*.parquet")
    files = sorted(glob.glob(pattern))

    if not files:
        print("No historical checkpoint files found for pattern:", pattern)
        return 1

    frames = []
    for f in files:
        try:
            yr = Path(f).stem.split("_")[-1]
            df = pd.read_parquet(f)
            df = df.copy()
            df["checkpoint_year"] = yr
            df["checkpoint_file"] = Path(f).name
            frames.append(df)
        except Exception as exc:
            print(f"Skipping {f}: {exc}")

    if not frames:
        print("No checkpoint files could be loaded.")
        return 1

    df = pd.concat(frames, ignore_index=True)
    df = _ensure_ml_scores(df)
    ts = pd.to_datetime(df.get("signal_timestamp"), errors="coerce")
    df["time_bucket"] = ts.apply(_time_bucket)

    # Same predictor-vs-baseline selection logic.
    base_sel = _selected_frame(df, BASELINE)
    cand_sel = _selected_frame(df, CANDIDATE)

    group_cols = [
        "time_bucket",
        "gamma_regime",
        "volatility_regime",
        "global_risk_state",
        "mode",
        "source",
        "checkpoint_year",
    ]

    summaries = {}
    all_rows = []
    for gc in group_cols:
        edge_df = _edge_summary(base_sel, cand_sel, gc)
        summaries[gc] = edge_df
        if not edge_df.empty:
            all_rows.append(edge_df)

    all_edges = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()

    today = date.today().isoformat()
    csv_path = REPORT_DIR / f"predictor_stability_regime_tod_historical_{today}.csv"
    json_path = REPORT_DIR / f"predictor_stability_regime_tod_historical_{today}.json"

    if not all_edges.empty:
        all_edges.to_csv(csv_path, index=False)
    else:
        pd.DataFrame(columns=["group_col", "group"]).to_csv(csv_path, index=False)

    consistency_overall = _consistency_call(all_edges)
    consistency_by_dim = {gc: _consistency_call(df_gc) for gc, df_gc in summaries.items()}

    payload = {
        "date": today,
        "dataset_scope": "historical_checkpoints_signals_*.parquet",
        "files_used": [Path(f).name for f in files],
        "rows_total": int(len(df)),
        "baseline_predictor": BASELINE,
        "candidate_predictor": CANDIDATE,
        "selection_counts": {
            "baseline": int(len(base_sel)),
            "candidate": int(len(cand_sel)),
        },
        "consistency_overall": consistency_overall,
        "consistency_by_dimension": consistency_by_dim,
        "top_positive_edges_5m": (
            all_edges.sort_values("edge_hit_5m_pp", ascending=False).head(20).to_dict(orient="records")
            if not all_edges.empty else []
        ),
        "top_negative_edges_5m": (
            all_edges.sort_values("edge_hit_5m_pp", ascending=True).head(20).to_dict(orient="records")
            if not all_edges.empty else []
        ),
    }

    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print("=" * 92)
    print("Historical Stability Check: research_decision_policy vs blended")
    print("=" * 92)
    print(f"Files: {len(files)} | Rows: {len(df):,}")
    print(f"Selected counts -> blended={len(base_sel):,}, research_decision_policy={len(cand_sel):,}")
    print()

    print("Overall consistency:")
    for k, v in consistency_overall.items():
        print(f"  {k}: {v}")
    print()

    for gc, summary in summaries.items():
        if summary.empty:
            print(f"[{gc}] no overlapping groups with minimum sample size.")
            continue
        print(f"[{gc}] groups={len(summary)}")
        top = summary.sort_values("edge_hit_5m_pp", ascending=False).head(3)
        bot = summary.sort_values("edge_hit_5m_pp", ascending=True).head(3)
        print("  Top +edge (5m hit-rate pp):")
        for _, r in top.iterrows():
            print(
                f"    {r['group']}: {r['edge_hit_5m_pp']:+.2f}pp | n_base={int(r['n_base']) if pd.notna(r['n_base']) else 0}, n_cand={int(r['n_cand']) if pd.notna(r['n_cand']) else 0}"
            )
        print("  Top -edge (5m hit-rate pp):")
        for _, r in bot.iterrows():
            print(
                f"    {r['group']}: {r['edge_hit_5m_pp']:+.2f}pp | n_base={int(r['n_base']) if pd.notna(r['n_base']) else 0}, n_cand={int(r['n_cand']) if pd.notna(r['n_cand']) else 0}"
            )
        print()

    print(f"Saved CSV : {csv_path}")
    print(f"Saved JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

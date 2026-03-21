"""
Multi-Year Holistic Backtest: 2016-2025
========================================
Production-grade signal-centric backtest runner across the full 10-year
historical database.  Exports the complete signal evaluation dataset for
downstream ML training (MovePredictor), probability calibration, trade
strength optimization, and feature importance analysis.

Key features:
  - Year-by-year execution with memory cleanup between years
  - Intermediate per-year checkpoint files for crash resilience
  - Enriched ML feature columns added to every signal row
  - Full macro event + global market + lookback_avg_range_pct integration
  - Comprehensive analytics report at the end
"""
import sys, os, time, json, csv, gc, logging
from datetime import date, timedelta
from pathlib import Path
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from backtest.holistic_backtest_runner import (
    run_holistic_backtest,
    _load_spot_daily,
    _spot_df_cache,
)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# ── Config ──────────────────────────────────────────────────────────
START_YEAR = 2016
END_YEAR   = 2025
SYMBOL     = "NIFTY"
MAX_EXPIRIES = 3
COMPUTE_IV = False          # skip Newton-Raphson for speed
OUTPUT_DIR = Path("research/signal_evaluation")
CHECKPOINT_DIR = OUTPUT_DIR / "checkpoints"
DATASET_CSV = OUTPUT_DIR / "backtest_signals_dataset.csv"
DATASET_PARQUET = OUTPUT_DIR / "backtest_signals_dataset.parquet"
SUMMARY_JSON = OUTPUT_DIR / "backtest_multiyear_summary.json"

# ── Helpers ─────────────────────────────────────────────────────────
def fmt(v, d=2):
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.{d}f}"
    return str(v)


def pct(v):
    return f"{v*100:.1f}%" if v is not None else "N/A"


def _clean(v):
    """Return None if NaN, else float."""
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_avg(vals):
    clean = [v for v in (_clean(x) for x in vals) if v is not None]
    return round(sum(clean) / len(clean), 4) if clean else None


def _enrich_signal_row(row: dict, spot_df: pd.DataFrame) -> dict:
    """Add derived ML-ready features to a signal row.

    These augmented features supplement the 136-column evaluation schema
    with numerical encodings and contextual indicators that the ML
    MovePredictor and tuning pipeline need.
    """
    sig_date_str = row.get("signal_timestamp", "")
    try:
        sig_date = pd.to_datetime(sig_date_str).date()
    except Exception:
        sig_date = None

    spot = _clean(row.get("spot_at_signal"))
    day_open = _clean(row.get("day_open"))
    day_high = _clean(row.get("day_high"))
    day_low = _clean(row.get("day_low"))
    prev_close = _clean(row.get("prev_close"))

    # Intraday range features
    if day_high is not None and day_low is not None and spot and spot > 0:
        row["intraday_range_pct"] = round(((day_high - day_low) / spot) * 100, 4)
    if spot and prev_close and prev_close > 0:
        row["gap_pct"] = round(((day_open - prev_close) / prev_close) * 100, 4) if day_open else None
        row["close_vs_prev_close_pct"] = round(((spot - prev_close) / prev_close) * 100, 4)

    # Days to expiry
    expiry_str = row.get("selected_expiry")
    if expiry_str and sig_date:
        try:
            exp_d = pd.to_datetime(expiry_str).date()
            row["days_to_expiry"] = (exp_d - sig_date).days
        except Exception:
            pass

    # Moneyness
    strike = _clean(row.get("strike"))
    if strike and spot and spot > 0:
        row["moneyness"] = round(strike / spot, 4)
        row["moneyness_pct"] = round(((strike - spot) / spot) * 100, 4)

    # Spot position relative to day range
    if day_high is not None and day_low is not None and day_high > day_low and spot:
        row["spot_in_day_range"] = round((spot - day_low) / (day_high - day_low), 4)

    # Historical volatility from spot data (trailing 5d and 20d)
    if sig_date and not spot_df.empty:
        prior = spot_df[spot_df["date"].dt.date < sig_date]
        if len(prior) >= 5:
            closes = prior.tail(20)["close"].astype(float)
            log_rets = np.log(closes / closes.shift(1)).dropna()
            if len(log_rets) >= 4:
                row["hist_vol_5d"] = round(float(log_rets.tail(5).std() * np.sqrt(252) * 100), 4)
            if len(log_rets) >= 15:
                row["hist_vol_20d"] = round(float(log_rets.tail(20).std() * np.sqrt(252) * 100), 4)

    # Numerical encoding of categorical features for ML
    dir_map = {"CALL": 1, "PUT": -1}
    row["direction_numeric"] = dir_map.get(row.get("direction"), 0)

    regime_map = {"LOW_VOL": 0, "NORMAL_VOL": 1, "VOL_EXPANSION": 2,
                  "HIGH_VOL": 2}
    row["vol_regime_numeric"] = regime_map.get(row.get("volatility_regime"), 1)

    gamma_map = {"POSITIVE_GAMMA": 1, "LONG_GAMMA": 1,
                 "NEUTRAL_GAMMA": 0, "NEUTRAL": 0,
                 "NEGATIVE_GAMMA": -1, "SHORT_GAMMA": -1}
    row["gamma_regime_numeric"] = gamma_map.get(row.get("gamma_regime"), 0)

    flow_map = {"BULLISH_FLOW": 1, "BEARISH_FLOW": -1,
                "NEUTRAL_FLOW": 0, "MIXED_FLOW": 0, "NO_FLOW": 0}
    row["flow_signal_numeric"] = flow_map.get(row.get("final_flow_signal"), 0)

    flip_map = {"ABOVE_FLIP": 1, "BELOW_FLIP": -1, "AT_FLIP": 0}
    row["spot_vs_flip_numeric"] = flip_map.get(row.get("spot_vs_flip"), 0)

    macro_map = {
        "NO_EVENT": 0,
        "NO_EVENT_DATA": 0,
        "CLEAR": 0,
        "POST_EVENT": 1,
        "POST_EVENT_COOLDOWN": 1,
        "PRE_EVENT": 2,
        "PRE_EVENT_WATCH": 2,
        "PRE_EVENT_LOCKDOWN": 3,
        "DURING_EVENT": 3,
        "LIVE_EVENT": 3,
    }
    row["macro_event_numeric"] = macro_map.get(
        row.get("macro_regime", "NO_EVENT"), 0
    )

    risk_map = {"LOW_RISK": 0, "MODERATE_RISK": 1, "ELEVATED_RISK": 2,
                "HIGH_RISK": 3, "EXTREME_RISK": 4}
    row["global_risk_numeric"] = risk_map.get(row.get("global_risk_state"), 0)

    confirm_map = {"STRONG_CONFIRMATION": 3, "CONFIRMED": 2, "MIXED": 1, "CONFLICT": 0}
    row["confirmation_numeric"] = confirm_map.get(row.get("confirmation_status"), 1)

    # Year/month/weekday for temporal analysis
    if sig_date:
        row["year"] = sig_date.year
        row["month"] = sig_date.month
        row["weekday"] = sig_date.weekday()

    # Binary outcome target columns for ML
    for h in (1, 2, 3, 5):
        c = _clean(row.get(f"correct_{h}d"))
        row[f"target_{h}d"] = int(c) if c is not None else None
    c = _clean(row.get("correct_at_expiry"))
    row["target_at_expiry"] = int(c) if c is not None else None
    row["target_hit_binary"] = int(row.get("target_hit") is True)
    row["stop_loss_hit_binary"] = int(row.get("stop_loss_hit") is True)

    return row


def _save_checkpoint(year: int, signals: list[dict], daily: list[dict]):
    """Save intermediate results for crash resilience."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    ckpt = CHECKPOINT_DIR / f"year_{year}.json"
    data = {"year": year, "signal_count": len(signals), "daily_count": len(daily)}
    with open(ckpt, "w") as f:
        json.dump(data, f)

    # Save signals as parquet for fast reload
    if signals:
        df = pd.DataFrame(signals)
        df.to_parquet(CHECKPOINT_DIR / f"signals_{year}.parquet", index=False)
    if daily:
        df = pd.DataFrame(daily)
        df.to_parquet(CHECKPOINT_DIR / f"daily_{year}.parquet", index=False)


def _load_checkpoint(year: int):
    """Load intermediate signals from a completed year checkpoint."""
    sig_file = CHECKPOINT_DIR / f"signals_{year}.parquet"
    daily_file = CHECKPOINT_DIR / f"daily_{year}.parquet"
    if sig_file.exists():
        df = pd.read_parquet(sig_file)
        signals = df.to_dict("records")
    else:
        signals = []
    if daily_file.exists():
        df = pd.read_parquet(daily_file)
        daily = df.to_dict("records")
    else:
        daily = []
    return signals, daily


def _has_checkpoint(year: int) -> bool:
    return (CHECKPOINT_DIR / f"signals_{year}.parquet").exists()


# ── Main ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 90)
    print("  MULTI-YEAR HOLISTIC BACKTEST: NIFTY 2016-2025")
    print("  Signal-Centric Evaluation — Full Historical Database")
    print("  With: Global Market + Macro Events + Lookback Range + ML Feature Enrichment")
    print("=" * 90)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    # Preload spot data for enrichment
    spot_df = _load_spot_daily()

    all_signals = []
    all_daily = []
    yearly_metrics = {}
    grand_t0 = time.time()

    for year in range(START_YEAR, END_YEAR + 1):
        # Check for existing checkpoint (resume support)
        if _has_checkpoint(year):
            print(f"\n  [{year}] Loading from checkpoint...")
            yr_signals, yr_daily = _load_checkpoint(year)
            trades = [s for s in yr_signals if s.get("trade_status") == "TRADE"]
            print(f"  [{year}] Restored: {len(yr_signals)} signals, {len(trades)} trades")
            all_signals.extend(yr_signals)
            all_daily.extend(yr_daily)
            # Rebuild yearly_metrics from restored data
            yearly_metrics[year] = {
                "evaluated": len(yr_daily),
                "signals": len(yr_signals),
                "trades": len(trades),
                "elapsed_sec": 0,
            }
            continue

        start = f"{year}-01-01"
        end = f"{year}-12-31"

        print(f"\n{'─'*90}")
        print(f"  YEAR {year}")
        print(f"{'─'*90}")

        t0 = time.time()
        result = run_holistic_backtest(
            SYMBOL,
            start_date=start,
            end_date=end,
            max_expiries=MAX_EXPIRIES,
            compute_iv=COMPUTE_IV,
            include_global_market=True,
            include_macro_events=True,
            progress_callback=lambda i, t, d, y=year: (
                print(f"  [{y}] {i+1:3d}/{t} {d}", end="\r", flush=True)
            ),
        )
        elapsed = time.time() - t0

        signals = result.get("signals", [])
        daily = result.get("daily_summary", [])
        trades = [s for s in signals if s.get("trade_status") == "TRADE"]
        metrics = result.get("metrics", {})

        # Enrich every signal with ML features
        for sig in signals:
            _enrich_signal_row(sig, spot_df)

        # Save checkpoint
        _save_checkpoint(year, signals, daily)

        all_signals.extend(signals)
        all_daily.extend(daily)

        # Year summary
        acc = metrics.get("directional_accuracy", {})
        scores = metrics.get("avg_scores", {})
        yearly_metrics[year] = {
            "days": result.get("total_days", 0),
            "evaluated": result.get("evaluated_days", 0),
            "skipped": result.get("skipped_days", 0),
            "signals": len(signals),
            "trades": len(trades),
            "no_trades": len(signals) - len(trades),
            "trade_rate": metrics.get("trade_rate"),
            "correct_1d": acc.get("correct_1d"),
            "correct_5d": acc.get("correct_5d"),
            "correct_at_expiry": acc.get("correct_at_expiry"),
            "composite_score": scores.get("composite_signal_score"),
            "direction_score": scores.get("direction_score"),
            "magnitude_score": scores.get("magnitude_score"),
            "timing_score": scores.get("timing_score"),
            "tradeability_score": scores.get("tradeability_score"),
            "target_hit_rate": metrics.get("target_hit_rate"),
            "stop_loss_hit_rate": metrics.get("stop_loss_hit_rate"),
            "avg_mfe_bps": metrics.get("avg_eod_mfe_bps"),
            "avg_mae_bps": metrics.get("avg_eod_mae_bps"),
            "elapsed_sec": round(elapsed, 1),
        }

        print(f"\n  {year}: {result.get('evaluated_days',0)} days | "
              f"{len(signals)} signals | {len(trades)} trades | "
              f"composite={fmt(scores.get('composite_signal_score'))} | "
              f"T+1d={pct(acc.get('correct_1d'))} | "
              f"target_hit={pct(metrics.get('target_hit_rate'))} | "
              f"{elapsed:.1f}s")

        # Memory cleanup between years
        del result, signals, daily
        gc.collect()

    grand_elapsed = time.time() - grand_t0

    # ── Aggregate Stats ─────────────────────────────────────────────
    trade_signals = [s for s in all_signals if s.get("trade_status") == "TRADE"]
    total_signals = len(all_signals)
    total_trades = len(trade_signals)

    print(f"\n\n{'='*90}")
    print(f"  AGGREGATE RESULTS: {START_YEAR}-{END_YEAR}")
    print(f"{'='*90}")
    print(f"  Total runtime:        {grand_elapsed:.1f}s ({grand_elapsed/60:.1f} min)")
    print(f"  Total days evaluated: {sum(1 for d in all_daily if d.get('status') == 'EVALUATED')}")
    print(f"  Total signals:        {total_signals}")
    print(f"  Total TRADE signals:  {total_trades}")
    print(f"  Total NO_TRADE:       {total_signals - total_trades}")
    print(f"  Overall trade rate:   {pct(total_trades / total_signals if total_signals else 0)}")

    # Overall directional accuracy
    print(f"\n  DIRECTIONAL ACCURACY (all TRADE signals):")
    for h, label in [("correct_1d","T+1d"), ("correct_2d","T+2d"), ("correct_3d","T+3d"),
                     ("correct_5d","T+5d"), ("correct_at_expiry","At Expiry")]:
        vals = [s.get(h) for s in trade_signals]
        clean = [_clean(v) for v in vals]
        clean = [v for v in clean if v is not None]
        if clean:
            acc_val = sum(clean) / len(clean)
            correct = sum(1 for v in clean if v == 1)
            print(f"    {label:<12}: {pct(acc_val):>8}  ({correct}/{len(clean)})")

    # Overall scores
    print(f"\n  AVERAGE SCORES:")
    for key, label in [("direction_score","Direction"), ("magnitude_score","Magnitude"),
                       ("timing_score","Timing"), ("tradeability_score","Tradeability"),
                       ("composite_signal_score","COMPOSITE")]:
        vals = [_clean(s.get(key)) for s in trade_signals]
        vals = [v for v in vals if v is not None]
        if vals:
            print(f"    {label:<15}: {np.mean(vals):>8.2f}")

    # Overall MFE/MAE
    mfe = [_clean(s.get("eod_mfe_bps")) for s in trade_signals]
    mfe = [v for v in mfe if v is not None]
    mae = [_clean(s.get("eod_mae_bps")) for s in trade_signals]
    mae = [v for v in mae if v is not None]
    if mfe and mae:
        print(f"\n  MFE/MAE:")
        print(f"    Avg MFE:     {np.mean(mfe):>8.2f} bps")
        print(f"    Avg MAE:     {np.mean(mae):>8.2f} bps")
        paired = [(m, a) for m, a in zip(mfe, mae) if a != 0]
        if paired:
            ratios = [abs(m/a) for m, a in paired]
            print(f"    Edge Ratio:  {np.mean(ratios):>8.2f}")
            print(f"    Edge > 1.0:  {sum(1 for r in ratios if r>1)}/{len(ratios)}")

    # Target/SL
    th = sum(1 for s in trade_signals if s.get("target_hit") is True)
    sl = sum(1 for s in trade_signals if s.get("stop_loss_hit") is True)
    if total_trades:
        print(f"\n  TARGET/STOP-LOSS:")
        print(f"    Target hit:  {th}/{total_trades} ({th/total_trades*100:.1f}%)")
        print(f"    SL hit:      {sl}/{total_trades} ({sl/total_trades*100:.1f}%)")

    # Yearly summary table
    print(f"\n  YEARLY SUMMARY:")
    hdr = (f"  {'Year':>6} {'Days':>6} {'Signals':>8} {'Trades':>7} {'Rate':>7} "
           f"{'T+1d':>7} {'T+5d':>7} {'Comp':>7} {'TgtHit':>7} {'SLHit':>7} "
           f"{'MFE':>8} {'MAE':>8} {'Time':>7}")
    print(hdr)
    print(f"  {'─'*6} {'─'*6} {'─'*8} {'─'*7} {'─'*7} "
          f"{'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7} "
          f"{'─'*8} {'─'*8} {'─'*7}")
    for y in range(START_YEAR, END_YEAR + 1):
        m = yearly_metrics.get(y, {})
        print(f"  {y:>6} {m.get('evaluated',0):>6} {m.get('signals',0):>8} "
              f"{m.get('trades',0):>7} {pct(m.get('trade_rate')):>7} "
              f"{pct(m.get('correct_1d')):>7} {pct(m.get('correct_5d')):>7} "
              f"{fmt(m.get('composite_score')):>7} "
              f"{pct(m.get('target_hit_rate')):>7} {pct(m.get('stop_loss_hit_rate')):>7} "
              f"{fmt(m.get('avg_mfe_bps')):>8} {fmt(m.get('avg_mae_bps')):>8} "
              f"{m.get('elapsed_sec', 0):>6.1f}s")

    # Direction & regime distribution
    dirs = Counter(s.get("direction") for s in trade_signals)
    print(f"\n  DIRECTION DISTRIBUTION: {dict(dirs)}")
    regimes = Counter(s.get("signal_regime") for s in trade_signals)
    print(f"  REGIME DISTRIBUTION:    {dict(regimes)}")
    vol_regimes = Counter(s.get("volatility_regime") for s in trade_signals)
    print(f"  VOL REGIME DIST:        {dict(vol_regimes)}")
    macro_states = Counter(s.get("macro_regime") for s in trade_signals if s.get("macro_regime"))
    print(f"  MACRO EVENT DIST:       {dict(macro_states)}")
    risk_states = Counter(s.get("global_risk_state") for s in trade_signals if s.get("global_risk_state"))
    print(f"  GLOBAL RISK DIST:       {dict(risk_states)}")

    # ── Export Dataset ──────────────────────────────────────────────
    print(f"\n{'─'*90}")
    print(f"  EXPORTING SIGNAL DATASET")
    print(f"{'─'*90}")

    if all_signals:
        df = pd.DataFrame(all_signals)

        # 1. Parquet export (primary — preserves types, fast to load)
        df.to_parquet(DATASET_PARQUET, index=False)
        print(f"  Parquet: {DATASET_PARQUET} ({len(df)} rows, {len(df.columns)} columns)")

        # 2. CSV export (secondary — human-readable)
        df.to_csv(DATASET_CSV, index=False)
        print(f"  CSV:     {DATASET_CSV} ({len(df)} rows)")

        # 3. Column inventory
        print(f"\n  Column inventory ({len(df.columns)} total):")
        for col in sorted(df.columns):
            non_null = df[col].notna().sum()
            fill_pct = non_null / len(df) * 100
            print(f"    {col:<50} {non_null:>6}/{len(df)} ({fill_pct:5.1f}%)")

    # 4. Summary JSON
    summary = {
        "run_date": str(date.today()),
        "symbol": SYMBOL,
        "date_range": f"{START_YEAR}-01-01 to {END_YEAR}-12-31",
        "total_days_evaluated": sum(1 for d in all_daily if d.get("status") == "EVALUATED"),
        "total_signals": total_signals,
        "total_trades": total_trades,
        "trade_rate": round(total_trades / total_signals, 4) if total_signals else 0,
        "runtime_seconds": round(grand_elapsed, 1),
        "data_sources_used": {
            "option_chain": "NSE bhav copy parquet (2016-2025)",
            "spot": "NIFTY_spot_daily.parquet",
            "global_market": "global_market_features.parquet (11 tickers)",
            "macro_events": "india_macro_events_historical.json (743 events)",
            "lookback_avg_range_pct": "computed from trailing 10-day spot H/L/C",
        },
        "ml_enrichment_columns": [
            "intraday_range_pct", "gap_pct", "close_vs_prev_close_pct",
            "days_to_expiry", "moneyness", "moneyness_pct", "spot_in_day_range",
            "hist_vol_5d", "hist_vol_20d",
            "direction_numeric", "vol_regime_numeric", "gamma_regime_numeric",
            "flow_signal_numeric", "spot_vs_flip_numeric", "macro_event_numeric",
            "global_risk_numeric", "confirmation_numeric",
            "year", "month", "weekday",
            "target_1d", "target_2d", "target_3d", "target_5d",
            "target_at_expiry", "target_hit_binary", "stop_loss_hit_binary",
        ],
        "yearly": {str(k): v for k, v in yearly_metrics.items()},
    }
    with open(SUMMARY_JSON, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  Summary: {SUMMARY_JSON}")

    print(f"\n{'='*90}")
    print(f"  DONE — {total_signals} signals exported for ML training & parameter optimization")
    print(f"  Outputs: {DATASET_PARQUET}")
    print(f"           {DATASET_CSV}")
    print(f"           {SUMMARY_JSON}")
    print(f"  Runtime: {grand_elapsed:.1f}s ({grand_elapsed/60:.1f} min)")
    print(f"{'='*90}")

# Decision Policy Robustness Report

**Author:** Pramit Dutta  
**Organization:** Quant Engines  
**Date:** March 18, 2026  
**Status:** Research Only — no production logic modified

---

## Executive Summary

This report presents a comprehensive robustness analysis of the decision policy
layer applied to 7,404 backtest signals spanning 2016–2025 (10 years). Five
policies were evaluated against the baseline engine across retention trade-offs,
yearly stability, regime sensitivity, threshold optimality, filter attribution,
and cumulative risk.

**Key result:** The `dual_threshold` policy delivers the best risk-adjusted
performance — 74.12% hit rate, +18.98 bps average return, Sharpe proxy 0.35,
with the lowest max drawdown (−932 bps) — while consistently beating baseline
across all 10 years and all regime conditions.

---

## 1. Policy Descriptions

| Policy | Mechanism | Retention |
|--------|-----------|-----------|
| **agreement_only** | Requires both engine (≥ 0.50) and ML confidence (≥ 0.50) | 54.6% allowed |
| **rank_filter_bottom_20pct** | Blocks bottom 20% by GBT rank | 80.0% allowed |
| **rank_filter_bottom_30pct** | Blocks bottom 30% by GBT rank | 70.0% allowed |
| **dual_threshold** | Requires rank ≥ 0.40 AND confidence ≥ 0.50 | 48.7% allowed |
| **sizing_simulation** | No blocking; confidence-tier size multipliers | 100% allowed |

---

## 2. Retention Trade-offs

The core trade-off in any filter policy is: *how many signals do you discard,
and is what remains actually better?*

| Policy | Allowed | Blocked | Hit Rate (60m) | Avg Return (bps) |
|--------|---------|---------|----------------|------------------|
| Baseline (all) | 7,404 | 0 | 50.35% | −2.60 |
| agreement_only | 4,044 | 11 | 67.48% | +10.92 |
| rank_filter_20% | 5,925 | 1,479 | 65.56% | +14.81 |
| rank_filter_30% | 5,183 | 2,221 | 70.97% | +19.34 |
| dual_threshold | 3,603 | 2,247 | 74.12% | +18.98 |
| sizing_simulation | 7,404 | 0 | 50.35% | −2.60 |

The rank-filter and dual-threshold policies occupy the optimal trade-off zone:
removing 30% of signals produces a 20+ percentage-point improvement in hit rate
and a 21+ bps swing in average return.

---

## 3. Efficiency Frontier

The efficiency frontier plots retention % (x-axis) against hit rate (y-axis).
Policies on the frontier cannot be dominated — no other point achieves a higher
hit rate at the same or greater retention.

**Frontier members:**
- `dual_threshold` (48.7% retention, 74.1% HR)
- `rank_filter_bottom_30pct` (70.0% retention, 71.0% HR)
- `rank_filter_bottom_20pct` (80.0% retention, 65.6% HR)
- `baseline_all` (100% retention, 50.4% HR)

`agreement_only` is **dominated** by `rank_filter_bottom_30pct`: similar
retention but 3.5 pp lower hit rate.

---

## 4. Yearly Stability

A critical robustness check: does each policy beat baseline *every year*, or
only in specific regimes?

| Policy | Beats baseline every year? | Avg yearly Δ HR |
|--------|---------------------------|-----------------|
| agreement_only | ✅ Yes (10/10) | +17.2 pp |
| rank_filter_20% | ✅ Yes (10/10) | +15.2 pp |
| rank_filter_30% | ✅ Yes (10/10) | +20.0 pp |
| dual_threshold | ✅ Yes (10/10) | +23.1 pp |
| sizing_simulation | ⚠️ No (identity) | 0 pp |

All filtering policies beat baseline in every single year from 2016 to 2025.
The coefficient of variation (CV) of yearly hit rates is lowest for
`rank_filter_bottom_30pct` (4.8%) and `rank_filter_bottom_20pct` (6.1%),
indicating stable, predictable performance.

---

## 5. Regime Sensitivity

Policies were tested across four regime dimensions:

- **Macro regime:** EVENT_LOCKDOWN, MACRO_NEUTRAL
- **Gamma regime:** NEGATIVE_GAMMA, NEUTRAL_GAMMA, POSITIVE_GAMMA
- **Volatility regime:** VOL_EXPANSION
- **Global risk:** EVENT_LOCKDOWN, GLOBAL_NEUTRAL, VOL_SHOCK

Key finding: **All filtering policies improve hit rate in every regime
condition**. The edge is structural (model quality) rather than
regime-dependent (lucky timing).

Notably, `dual_threshold` in NEGATIVE_GAMMA achieves 72% hit rate vs. 37%
baseline — a +35 pp improvement — demonstrating the model excels at filtering
out false signals in adverse regimes.

---

## 6. Rank Threshold Sweep

Testing GBT rank-score thresholds at 10% increments reveals the optimal
removal/performance curve:

| Bottom % Removed | Hit Rate | Avg Return (bps) |
|------------------|----------|------------------|
| 0% (baseline) | 50.4% | −2.60 |
| 10% | 58.1% | +7.77 |
| 20% | 65.6% | +14.81 |
| **30%** | **71.0%** | **+19.34** |
| 40% | 73.8% | +22.13 |
| 50% | 74.0% | +22.78 |
| 60% | 73.7% | +22.48 |
| 70% | 77.2% | +24.13 |

The curve shows diminishing returns beyond 30-40% removal. The 30% threshold
is near-optimal: it captures most of the improvement while retaining 70% of
the signal universe — sufficient for statistical power and diversification.

---

## 7. Confidence Threshold Sweep

| Threshold | Retention | Hit Rate | Return (bps) |
|-----------|-----------|----------|--------------|
| 0.00 | 100% | 50.4% | −2.60 |
| 0.40 | 71.6% | 65.6% | +11.27 |
| **0.50** | **54.6%** | **67.5%** | **+10.92** |
| 0.60 | 30.5% | 67.9% | +11.35 |
| 0.70 | 4.8% | 61.6% | +4.66 |

Confidence filtering plateaus at ~67% hit rate regardless of threshold (0.45–
0.65 range). This confirms that **rank filtering is the primary value driver**,
while confidence is a secondary refinement. The 0.50 threshold is well-
positioned: further tightening adds negligible hit-rate improvement while
halving sample size.

---

## 8. Filter Attribution

What types of signals get removed?

| Category | Count | % | Hit Rate | Return |
|----------|-------|---|----------|--------|
| Low rank only | 441 | 6.0% | 20.6% | −45.14 bps |
| Low confidence only | 1,113 | 15.0% | 70.3% | +30.17 bps |
| Both low | 2,247 | 30.4% | 25.5% | −26.98 bps |
| Neither (passed) | 3,603 | 48.7% | 74.1% | +18.98 bps |

**Critical insight:** The `low_rank_only` and `both_low` categories are genuine
noise (20–25% HR, negative returns). However, the `low_confidence_only` category
shows 70% HR and +30 bps — these are good signals the confidence gate rejects.
This means the rank model alone provides strong filtering; the confidence filter
adds selectivity at some cost to retained alpha.

---

## 9. Risk & Drawdown Analysis

| Policy | Cumulative (bps) | Max Drawdown | Return Vol | Sharpe |
|--------|-----------------|-------------|------------|--------|
| Baseline | −7,022 | −15,724 | 80.6 | −0.03 |
| agreement_only | +13,799 | −2,326 | 63.5 | 0.17 |
| rank_filter_20% | +26,356 | −1,779 | 64.4 | 0.23 |
| rank_filter_30% | +29,240 | −1,385 | 62.8 | 0.31 |
| **dual_threshold** | **+20,977** | **−932** | **54.5** | **0.35** |

`dual_threshold` has the highest Sharpe (0.35) and lowest drawdown (−932 bps),
confirming improvements are genuine and not due to hidden risk concentration.
`rank_filter_30%` delivers the highest cumulative return (+29,240 bps) but with
larger drawdown.

---

## 10. Final Recommendation

| Assessment | Policy |
|------------|--------|
| **Best Precision** | `dual_threshold` (0.35 Sharpe, 74.1% HR) |
| **Best Cumulative Return** | `rank_filter_bottom_30pct` (+29,240 bps) |
| **Best Balanced** | `dual_threshold` |
| **Production Candidate** | `dual_threshold` — for paper-trade validation |

### Conclusion

1. All filtering policies produce statistically robust improvements that persist
   across 10 independent yearly windows and 4 regime dimensions.
2. No evidence of overfitting — performance is consistent, not concentrated in
   specific years or market conditions.
3. The GBT rank model is the primary source of filtering edge; the LogReg
   confidence model adds incremental selectivity.
4. `dual_threshold` is recommended as the **candidate for future production
   testing** (paper-trade phase). All other policies remain in research for
   continued monitoring.

---

## Artifacts

All analysis artifacts are saved to:
```
research/ml_evaluation/policy_robustness/
├── policy_robustness_report.md         # Full Markdown analysis report
├── policy_robustness_results.json      # Machine-readable master results
├── retention_coverage.csv              # Section 2 data
├── yearly_stability.csv                # Section 3 data
├── rank_threshold_sweep.csv            # Section 6 sweep data
├── confidence_threshold_sweep.csv      # Section 7 sweep data
├── filter_attribution.csv              # Section 8 attribution data
├── risk_analysis.csv                   # Section 9 risk data
├── efficiency_frontier.png             # Pareto frontier chart
├── rank_threshold_sweep.png            # Rank sweep curve
├── confidence_threshold_sweep.png      # Confidence sweep curve
├── yearly_hit_rate.png                 # Year-by-year hit rate bars
├── yearly_avg_return.png               # Year-by-year return bars
├── regime_heatmap_macro.png            # Macro regime heatmap
├── regime_heatmap_gamma.png            # Gamma regime heatmap
├── regime_heatmap_global_risk.png      # Global risk regime heatmap
└── risk_drawdown_comparison.png        # Cumulative return / drawdown / Sharpe
```

---

*End of Policy Robustness Report*

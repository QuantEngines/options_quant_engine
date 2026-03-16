---
title: "Daily Signal Research Report — March 16, 2026"
subtitle: "Signal Quality and Predictive Performance Analysis"
author: "Pramit Dutta — Quant Engines"
date: "2026-03-16"
---

# Daily Signal Research Report — March 16, 2026

> **Author:** Pramit Dutta | **Organization:** Quant Engines | **Date:** 2026-03-16

---

## 1. Executive Summary

*This section provides a high-level overview of the day's signal generation activity, including total signal volume, directional bias distribution, dominant market regimes, and the best-performing evaluation horizon. It serves as a quick read for senior researchers to assess whether the session warrants deeper investigation.*

**Date:** March 16, 2026

The engine generated **43 signal snapshots** during the session, of which **22** carried a directional bias and **22** qualified as actionable trade signals.

- **Mean composite signal score:** 46.8
- **Best horizon hit rate:** 60m (100.0%)
- **Dominant macro regime:** RISK_OFF
- **Dominant gamma regime:** POSITIVE_GAMMA

## 2. Macroeconomic Environment

*This section captures the macro backdrop under which signals were generated. It includes global risk indicators (oil, commodity, volatility shocks), local macro regime classifications, and news/headline confirmation status. Understanding the macro environment is essential for contextualizing signal quality — a signal that performs well in RISK_OFF may behave very differently under RISK_ON conditions.*

### Global Macro Indicators

| Indicator | Value |
| --- | ---: |
| Oil Shock Score | 0.0 |
| Commodity Risk Score | 0.0 |
| Volatility Shock Score | 0.0 |
| Global Risk Score | 39.14 |
| Global Risk State | RISK_OFF |
| Volatility Explosion Probability | 0.0 |

### Local Macro Indicators

| Indicator | Value |
| --- | ---: |
| Macro Regime | RISK_OFF |
| Macro Event Risk Score | 0.0 |
| Volatility Regime | VOL_EXPANSION |

### News & Headline Analysis

| Indicator | Value |
| --- | ---: |
| Confirmation Status | STRONG_CONFIRMATION |
| Data Quality Status | STRONG |
| Provider Health Status | CAUTION |

### Narrative Summary

The session operated under a **RISK_OFF** macro regime with **VOL_EXPANSION** volatility conditions. Global risk state was **RISK_OFF**. 
The average global risk score was **39.1** / 100.

## 3. Market Structure Context

*Market structure describes the microstructural environment at the time of signal generation — gamma positioning, dealer hedging behavior, volatility regime, and liquidity conditions. These structural dimensions directly influence how price responds to order flow and whether directional signals are likely to follow through or face structural resistance.*

| Dimension | Observed State |
| --- | --- |
| Gamma Regime | POSITIVE_GAMMA (dominant, 3 states observed) |
| Dealer Positioning | Long Gamma |
| Spot vs Gamma Flip | ABOVE_FLIP (dominant, 3 states observed) |
| Volatility Regime | VOL_EXPANSION |
| Liquidity Structure | NORMAL |
| Dealer Hedging Bias | DOWNSIDE_PINNING (dominant, 2 states observed) |
| Squeeze Risk State | LOW_ACCELERATION_RISK (dominant, 2 states observed) |
| Directional Convexity | NO_CONVEXITY_EDGE (dominant, 3 states observed) |
| Dealer Flow State | HEDGING_NEUTRAL (dominant, 2 states observed) |
| Session High | 23502.0 |
| Session Low | 22955.55 |
| Session Range | 546.45 pts |

## 4. Signal Generation Summary

*This section quantifies the engine's output for the session — how many total signal snapshots were produced, how many carried a directional bias (CALL/PUT), and how many passed the composite threshold to qualify as actionable trade signals versus watchlist entries. A healthy session should show a meaningful ratio of directional to neutral signals.*

| Metric | Count |
| --- | ---: |
| Total signal snapshots | 43 |
| Directional signals | 22 |
| Neutral / no-direction | 21 |
| Qualified trade signals | 22 |
| Watchlist / no-signal | 21 |

**Direction breakdown:**

- CALL: 22

## 5. Horizon Performance

*Horizon performance measures how signals performed at each evaluation window (5m through session close). The signed return reflects alpha in the predicted direction, while the hit rate shows the fraction of signals where the market moved favorably. Comparing across horizons reveals the optimal holding period for the engine's signal type.*

| Horizon | Samples | Avg Return (bps) | Avg Signed Return (bps) | Hit Rate |
| --- | ---: | ---: | ---: | ---: |
| 5m | 21 | 0.0004 | 3.93 | 71.43% |
| 15m | 21 | 0.0007 | 7.05 | 52.38% |
| 30m | 18 | 0.0005 | 4.86 | 61.11% |
| 60m | 5 | 0.0012 | 11.82 | 100.0% |
| 120m | 0 | — | — | — |
| session_close | 22 | — | -20.81 | 27.27% |

## 6. Signal Alpha Decay Curve

*The alpha decay curve tracks how the signal's directional edge evolves over time from generation to session close. A well-behaved signal should show peak alpha at the intended holding period, with gradual decay afterward. Abrupt reversals from positive to negative indicate that the signal captures a real but short-lived effect, and holding period management is critical.*

Average directional-signed return (bps) by time horizon:

| Horizon | Avg Signed Return (bps) |
| --- | ---: |
| 5m | 3.93 |
| 15m | 7.05 |
| 30m | 4.86 |
| 60m | 11.82 |
| 120m | — |
| session_close | -20.81 |

**Decay Curve (ASCII):**

```
               5m |                                  +++++++ +3.9 bps
              15m |                            +++++++++++++ +7.1 bps
              30m |                                +++++++++ +4.9 bps
              60m |                   ++++++++++++++++++++++ +11.8 bps
             120m | ???
    session_close | ---------------------------------------- -20.8 bps
```

The decay curve reveals how long the signal edge persists after generation. Steeper decay suggests shorter-lived alpha.

## 7. Decay Curve by Score Bucket

*This section disaggregates the alpha decay curve by composite signal score tier (80–100 being the highest conviction, 0–34 the lowest). If the scoring model is well-calibrated, higher-tier signals should show stronger and more persistent alpha across horizons. Score tiers that decay rapidly or show negative returns may indicate over-scoring.*

Average signed return (bps) by composite score bucket and horizon:

| Score Bucket | 5m | 15m | 30m | 60m | 120m | session_close | N |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 80–100 | 13.3 | 40.18 | 54.9 | 11.82 | — | 12.0 | 5 |
| 65–79 | 16.23 | 31.75 | 16.75 | — | — | -7.46 | 3 |
| 50–64 | 9.66 | 16.18 | 8.33 | — | — | -26.74 | 2 |
| 35–49 | 9.62 | 9.71 | 1.69 | — | — | -32.31 | 1 |
| 0–34 | -5.63 | -18.23 | -36.45 | — | — | -38.96 | 10 |

Higher-scoring signals should ideally maintain positive alpha across longer horizons to confirm score calibration.

## 8. Decay Curve by Regime

*This section slices the alpha decay curve by market regime (macro, gamma, volatility, and global risk state). Regime-conditional analysis reveals whether the engine's alpha is regime-dependent — for example, signals may work well in POSITIVE_GAMMA but fail under NEGATIVE_GAMMA. This is essential for regime-aware position sizing and signal filtering.*

### Macro Regime

| Macro Regime | 5m | 15m | 30m | 60m | 120m | session_close | N |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RISK_OFF | 3.93 | 7.05 | 4.86 | 11.82 | — | -20.81 | 22 |

### Gamma Regime

| Gamma Regime | 5m | 15m | 30m | 60m | 120m | session_close | N |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| POSITIVE_GAMMA | 3.93 | 7.05 | 4.86 | 11.82 | — | -20.81 | 22 |

### Volatility Regime

| Volatility Regime | 5m | 15m | 30m | 60m | 120m | session_close | N |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| VOL_EXPANSION | 3.93 | 7.05 | 4.86 | 11.82 | — | -20.81 | 22 |

### Global Risk State

| Global Risk State | 5m | 15m | 30m | 60m | 120m | session_close | N |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RISK_OFF | 3.93 | 7.05 | 4.86 | 11.82 | — | -20.81 | 22 |

Regime-dependent decay curves help identify where alpha is persistent versus where it decays rapidly.

## 9. Directional Accuracy

*Directional accuracy measures the binary question: did the market move in the direction the signal predicted? This is the most fundamental quality metric for a directional signal engine. A hit rate above 50% indicates the signal has positive directional edge; rates above 60% at the optimal horizon suggest strong predictive power.*

Directional hit rate per horizon (excludes neutral/no-direction signals):

| Horizon | Samples | Correct | Hit Rate |
| --- | ---: | ---: | ---: |
| 5m | 21 | 15 | 71.43% |
| 15m | 21 | 11 | 52.38% |
| 30m | 18 | 11 | 61.11% |
| 60m | 5 | 5 | 100.0% |
| 120m | 0 | 0 | — |
| session_close | 22 | 6 | 27.27% |

## 10. Magnitude Adequacy

*Magnitude adequacy evaluates whether the realized market moves were large enough relative to the expected move and historical range. Even with correct direction, signals are only useful if the magnitude exceeds transaction costs and provides meaningful profit opportunity. MFE (Maximum Favorable Excursion) and MAE (Maximum Adverse Excursion) show the best and worst points reached during each horizon window.*

Comparison of realized move magnitude vs expected market range:

| Metric | Value |
| --- | ---: |
| Expected Move (%) | 1.7161 |
| Lookback Avg Range (%) | 1.3841 |
| Avg Realized Return 60m | 0.0012 |
| Avg Realized Return 120m | — |
| Realized / Expected Ratio (60m) | 0.07 |

- **Avg MFE (60m):** 19.72 bps
- **Avg MAE (60m):** -22.33 bps
- **Avg MFE (120m):** 19.72 bps
- **Avg MAE (120m):** -22.33 bps

## 11. Tradeability Analysis

*Tradeability goes beyond direction and magnitude — it asks whether the price path after signal generation was actually tradable. The MFE/MAE ratio measures path efficiency: a ratio above 1.0 means favorable excursion exceeded adverse excursion, suggesting a trader could have captured profit with reasonable stop placement. The tradeability and target reachability scores aggregate multiple path quality factors.*

Evaluates whether signals produced tradable path conditions:

| Metric | Value |
| --- | ---: |
| Avg MFE 60m (bps) | 19.72 |
| Avg MAE 60m (bps) | -22.33 |
| Avg MFE/MAE Ratio (60m) | 0.77 |
| Avg MFE 120m (bps) | 19.72 |
| Avg MAE 120m (bps) | -22.33 |
| Avg Tradeability Score | 44.7 |
| Avg Target Reachability | 90.0 |

- Target reachability score distribution: mean=90.0, median=90.0

## 12. Score Calibration

*Score calibration tests whether the engine's composite signal score is a reliable rank-ordering of signal quality. If calibration is good, higher score buckets should show monotonically better hit rates and signed returns. Poor calibration (e.g., low scores outperforming high scores) indicates the scoring model needs reweighting.*

Do higher composite scores correspond to better outcomes?

| Score Bucket | N | Hit Rate 60m | Avg Signed Return 60m (bps) | Avg Composite |
| --- | ---: | ---: | ---: | ---: |
| 80–100 | 5 | 100.0% | 11.82 | 87.9 |
| 65–79 | 3 | — | — | 76.8 |
| 50–64 | 2 | — | — | 55.7 |
| 35–49 | 1 | — | — | 48.1 |
| 0–34 | 10 | — | — | 13.5 |

Well-calibrated scores should show monotonically improving hit rates and returns as the score bucket increases.

## 13. Probability Calibration

*Probability calibration compares the model's predicted move probability against the actual realized hit rate. A well-calibrated model should have predicted probabilities that closely match realized frequencies — e.g., signals predicted at 70% probability should be correct roughly 70% of the time. Large calibration gaps indicate the probability model is overconfident or underconfident and needs recalibration.*

Predicted move probability vs realized directional outcomes:

| Probability Bucket | N | Predicted Avg P | Realized Hit Rate | Calibration Gap |
| --- | ---: | ---: | ---: | ---: |
| 35–49% | 3 | 48.0% | — | — |
| 50–64% | 40 | 58.77% | 100.0% | -0.4123 |

## 14. Reversal Diagnostics

*Reversal diagnostics measure how much profit is surrendered after the signal reaches its peak favorable excursion (MFE). Peak-to-close decay quantifies the average give-back from MFE to session end. The late-session reversal rate tracks how often signals that were profitable at 60m end up negative by close — a high rate suggests the alpha is real but short-lived, and exit timing is critical.*

Intraday reversal and profit decay analysis:

| Metric | Value |
| --- | ---: |
| Avg Peak-to-Close Decay (bps) | 40.52 |
| Avg Profit Decay After MFE 60m (bps) | 44.14 |
| Late-Session Reversal Rate | 0.0% |

## 15. Regime Performance

*This section breaks down signal performance by each regime dimension (macro, gamma, volatility, global risk). Unlike the decay curves in Section 8, this view focuses on the 60-minute horizon hit rate and returns. Regime-specific performance helps determine whether certain market conditions amplify or suppress signal reliability, informing regime-conditional filtering rules.*

### Macro Regime

| Regime | N | Hit Rate 60m | Avg Signed Return 60m (bps) | Avg Composite |
| --- | ---: | ---: | ---: | ---: |
| RISK_OFF | 22 | 100.0% | 11.82 | 46.8 |

### Gamma Regime

| Regime | N | Hit Rate 60m | Avg Signed Return 60m (bps) | Avg Composite |
| --- | ---: | ---: | ---: | ---: |
| POSITIVE_GAMMA | 22 | 100.0% | 11.82 | 46.8 |

### Volatility Regime

| Regime | N | Hit Rate 60m | Avg Signed Return 60m (bps) | Avg Composite |
| --- | ---: | ---: | ---: | ---: |
| VOL_EXPANSION | 22 | 100.0% | 11.82 | 46.8 |

### Global Risk State

| Regime | N | Hit Rate 60m | Avg Signed Return 60m (bps) | Avg Composite |
| --- | ---: | ---: | ---: | ---: |
| RISK_OFF | 22 | 100.0% | 11.82 | 46.8 |

## 16. Model Diagnostics

*Model diagnostics surface the raw feature inputs that drove the engine's signal decisions. Reviewing mean, median, min, and max values helps identify feature concentration (low variance = low discriminative power), outliers that may have skewed scoring, and features that were inactive during the session. This is the primary debugging tool for understanding why the engine produced the signals it did.*

Average feature values across all signals for the session:

| Feature | Mean | Median | Min | Max |
| --- | ---: | ---: | ---: | ---: |
| Spot vs Gamma Flip | ABOVE_FLIP | — | — | — |
| Volatility Shock Score | 0.0 | 0.0 | 0.0 | 0.0 |
| Global Risk Score | 39.14 | 22.0 | 20.0 | 58.0 |
| Dealer Hedging Pressure | 17.4 | 16.0 | 10.0 | 35.0 |
| Gamma-Vol Acceleration | 13.37 | 0.0 | 0.0 | 47.0 |
| Option Efficiency Score | 67.37 | 81.0 | 50.0 | 86.0 |
| Macro Event Risk Score | 0.0 | 0.0 | 0.0 | 0.0 |
| Move Probability | 0.58 | 0.6 | 0.48 | 0.63 |
| Target Reachability | 70.47 | 90.0 | 50.0 | 90.0 |
| Premium Efficiency | 66.51 | 74.0 | 50.0 | 88.0 |
| Data Quality Score | 92.0 | 92.0 | 92.0 | 92.0 |

## 17. Key Insights

*Automated observations drawn from the data above. These insights highlight the most noteworthy patterns from the session — dominant regime effects, hit rate performance, score quality assessment, reversal risk indicators, and path efficiency. Each insight is derived from quantitative thresholds and should be treated as a starting point for deeper investigation, not a definitive conclusion.*

- The session was dominated by **RISK_OFF** macro conditions.
- Best directional hit rate was at **60m** (100.0%).
- Mean composite score (46.8) indicates moderate signal quality.
- Signals showed **positive alpha at 60m that reversed by session close** — late-session risk is elevated.

## 18. Research Actions

*This section generates actionable research recommendations based on patterns detected in the session data. Recommendations are triggered by specific quantitative criteria — sample size thresholds, calibration gaps, scoring variance, regime concentration, and reversal patterns. These are prioritized suggestions for improving model quality in subsequent iterations.*

Suggested research improvements based on observed behavior:

1. **Recalibrate probability model** — calibration gap of 0.42 exceeds 15% threshold.
2. **Investigate late-session reversals** — signals profitable at 60m but negative by close. Consider shorter holding periods or session-time-weighted exit logic.

---

*Report generated by Options Quant Engine — Signal Research Reporting System*

*Dataset: signals_dataset.csv | Signals: 43 | Date: 2026-03-16*
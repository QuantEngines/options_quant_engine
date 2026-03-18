# Signal State Dictionary — Options Quant Engine

**Author:** Pramit Dutta  
**Organization:** Quant Engines  
**Version:** 1.0  
**Last Updated:** 2025-07-16

---

## Table of Contents

1. [Overview](#overview)
2. [State Dependency Diagram](#state-dependency-diagram)
3. [Category A — Macro Regime](#category-a--macro-regime)
4. [Category B — Event Window Status](#category-b--event-window-status)
5. [Category C — Event Severity Level](#category-c--event-severity-level)
6. [Category D — Global Risk State](#category-d--global-risk-state)
7. [Category E — Global Risk Action](#category-e--global-risk-action)
8. [Category F — Global Risk Level](#category-f--global-risk-level)
9. [Category G — Gamma Regime](#category-g--gamma-regime)
10. [Category H — Gamma Exposure Signal](#category-h--gamma-exposure-signal)
11. [Category I — Volatility Regime](#category-i--volatility-regime)
12. [Category J — Intraday Gamma Shift & Volatility Implication](#category-j--intraday-gamma-shift--volatility-implication)
13. [Category K — Flow Signal](#category-k--flow-signal)
14. [Category L — Smart Money Flow](#category-l--smart-money-flow)
15. [Category M — Dealer Positioning](#category-m--dealer-positioning)
16. [Category N — Dealer Hedging Bias](#category-n--dealer-hedging-bias)
17. [Category O — Liquidity Signal](#category-o--liquidity-signal)
18. [Category P — Squeeze Risk State (Gamma-Vol Acceleration)](#category-p--squeeze-risk-state)
19. [Category Q — Directional Convexity State (Gamma-Vol Acceleration)](#category-q--directional-convexity-state)
20. [Category R — Dealer Flow State (Dealer Hedging Pressure)](#category-r--dealer-flow-state)
21. [Category S — Data Quality Status](#category-s--data-quality-status)
22. [Category T — Provider Health Status](#category-t--provider-health-status)
23. [Category U — Confirmation Status](#category-u--confirmation-status)
24. [Category V — Trade Direction](#category-v--trade-direction)
25. [Category W — Signal Regime](#category-w--signal-regime)
26. [Category X — Execution Regime](#category-x--execution-regime)
27. [Category Y — Trade Status](#category-y--trade-status)
28. [Category Z — Capture Policy](#category-z--capture-policy)
29. [Category AA — Composite Risk Metrics](#category-aa--composite-risk-metrics)
30. [Category AB — Regime Fingerprint](#category-ab--regime-fingerprint)
31. [Final Summary](#final-summary)

---

## Overview

This document catalogues every symbolic state label, regime label, and classification term used by the Options Quant Engine. Each entry specifies the term's origin module, decision rule with exact thresholds, upstream inputs, and downstream interpretation.

**Total terms documented:** 91  
**Categories:** 28 + 3 composite metrics  
**Layers traversed:** Market Data → Analytics → Risk/Overlay → Signal Engine → Trade Decision

---

## State Dependency Diagram

The diagram below shows how raw market data flows through successive classification layers to produce a final trade decision. Each box represents a classification function; arrows show data dependencies.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            MARKET DATA LAYER                                    │
│  Spot Price · Option Chain · Open Interest · Volume · Headlines · Calendar      │
└────────┬──────────┬──────────┬──────────┬──────────┬──────────┬─────────────────┘
         │          │          │          │          │          │
         ▼          ▼          ▼          ▼          ▼          ▼
┌────────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────────────┐
│ Gamma Flip ││ GEX      ││ Vol      ││ Flow     ││ Dealer   ││ Macro / Sched.   │
│ gamma_     ││ gamma_   ││ regime   ││ imbal.   ││ inventory││ Events / News    │
│ regime     ││ exposure ││ vol_     ││ flow_    ││ dealer_  ││ macro_regime     │
│ (3 vals)   ││ (2 vals) ││ regime   ││ signal   ││ position ││ event_window_    │
│            ││          ││ (3 vals) ││ (3 vals) ││ (2 vals) ││ status (7 vals)  │
└─────┬──────┘└────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘└───────┬──────────┘
      │            │           │           │           │              │
      ▼            ▼           ▼           ▼           ▼              ▼
┌──────────────────────────────────────┐  ┌───────────────────────────────────────┐
│       ANALYTICS LAYER (derived)      │  │         RISK / OVERLAY LAYER          │
│ market_gamma_map → gamma_regime (4)  │  │ global_risk_state (5 vals)            │
│ vol_surface → vol_regime (4)         │  │ global_risk_action (4 vals)           │
│ smart_money → smart_flow (4)        │  │ global_risk_level (3 vals)            │
│ hedging_sim → hedging_bias (5)      │  │ squeeze_risk_state (4 vals)           │
│ gamma_shift → shift_signal (3→3)    │  │ directional_convexity_state (4 vals)  │
│ liquidity → liq_signal (2+2+2)      │  │ dealer_flow_state (5 vals)            │
└──────────────┬───────────────────────┘  └────────────────┬──────────────────────┘
               │                                           │
               └────────────────┬──────────────────────────┘
                                ▼
                 ┌──────────────────────────────┐
                 │     SIGNAL ENGINE LAYER       │
                 │ data_quality_status (4 vals)  │
                 │ confirmation_status (4 vals)  │
                 │ direction (CALL/PUT/None)     │
                 │ signal_regime (6 vals)        │
                 │ execution_regime (5 vals)     │
                 │ trade_status (6 vals)         │
                 │ regime_fingerprint (hash)     │
                 └──────────────────────────────┘
```

---

## Category A — Macro Regime

**Source:** `macro/macro_news_aggregator.py`  
**Field name:** `macro_regime`  
**Downstream consumers:** `risk/global_risk_regime.py`, `engine/signal_engine.py`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 1 | `EVENT_LOCKDOWN` | `event_lockdown_flag == True` (hard override from event window) | All trading blocked; scheduled macro event imminent or live |
| 2 | `RISK_OFF` | Any of: `sentiment ≤ -18` \| `global_bias ≤ -0.22` \| `india_bias ≤ -0.22` \| `vol_shock ≥ 65` | Bearish macro conditions; position sizing reduced |
| 3 | `RISK_ON` | `sentiment ≥ 18` AND `global_bias ≥ 0.22` AND `vol_shock < 55` | Bullish macro conditions; full sizing allowed |
| 4 | `MACRO_NEUTRAL` | Fallback when none of the above triggers | No strong macro directional bias |

**Priority order:** EVENT_LOCKDOWN → RISK_OFF → RISK_ON → MACRO_NEUTRAL (first match wins)

---

## Category B — Event Window Status

**Source:** `macro/scheduled_event_risk.py`  
**Field name:** `event_window_status`  
**Downstream consumers:** `macro/macro_news_aggregator.py` → `macro_regime`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 5 | `CLEAR` | No active event in the schedule | No event risk; risk = 0 |
| 6 | `PRE_EVENT_WATCH` | `lockdown_min < minutes_until_event ≤ warning_min` (warning = 180 min) | Event approaching; heightened awareness, no lockdown |
| 7 | `PRE_EVENT_LOCKDOWN` | `minutes_until_event ≤ lockdown_min` (lockdown = 30 min) | Event imminent; `event_lockdown_flag = True` |
| 8 | `LIVE_EVENT` | `0 ≤ minutes_since_event ≤ event_duration` (duration = 10 min) | Event in progress; `event_lockdown_flag = True` |
| 9 | `POST_EVENT_COOLDOWN` | `event_duration < minutes_since_event ≤ cooldown_min` (cooldown = 30 min) | Event concluded; residual volatility possible |
| 10 | `NO_EVENT_DATA` | Schedule file missing or empty | Treat as no events; risk = 0 |
| 11 | `EVENT_FILTER_DISABLED` | Event filtering feature disabled in policy | Feature disabled; risk = 0 |

---

## Category C — Event Severity Level

**Source:** `config/event_window_policy.py`  
**Field name:** `severity`  
**Downstream consumers:** `macro/scheduled_event_risk.py` → base risk calculation

| # | Label | Base Risk Score | Interpretation |
|---|-------|----------------|----------------|
| 12 | `CRITICAL` | 95 | RBI policy, GDP print, major global event |
| 13 | `MAJOR` | 80 | CPI/WPI release, FOMC, PMI |
| 14 | `MEDIUM` | 55 | Trade balance, industrial production |
| 15 | `MINOR` | 30 | Secondary indicators, regional data |

---

## Category D — Global Risk State

**Source:** `risk/global_risk_regime.py`  
**Field name:** `global_risk_state`  
**Inputs:** `volatility_explosion_probability`, `event_lockdown_flag`, `macro_event_risk_norm`, `regime_score`, `macro_regime`  
**Downstream consumers:** `engine/signal_engine.py` → trade decision modifiers

| # | Label | Decision Rule | Adjustment | Size Cap |
|---|-------|--------------|------------|----------|
| 16 | `VOL_SHOCK` | `volatility_explosion_probability > 0.7` | -6 | 0.35 |
| 17 | `EVENT_LOCKDOWN` | `event_lockdown_flag == True` OR `macro_event_risk_norm > 0.7` | -4 | 0.0 (if lockdown) / 0.65 |
| 18 | `RISK_OFF` | `regime_score > 0.6` OR `macro_regime == "RISK_OFF"` | -4 | 0.65 |
| 19 | `RISK_ON` | `regime_score < -0.3` AND `neutral_fallback == False` | 0 | 1.0 |
| 20 | `GLOBAL_NEUTRAL` | Fallback (none of the above) | 0 | 1.0 |

**Priority order:** VOL_SHOCK → EVENT_LOCKDOWN → RISK_OFF → RISK_ON → GLOBAL_NEUTRAL

---

## Category E — Global Risk Action

**Source:** `risk/global_risk_layer.py`  
**Field name:** `global_risk_action`  
**Downstream consumers:** `engine/signal_engine.py` → trade admission gate

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 21 | `BLOCK` | `data_fatal` OR `event_lockdown` OR `global_risk_veto` | Trade rejected; hard block |
| 22 | `WATCHLIST` | Overnight gap / confirmation / strength / data caution flags | Trade demoted to watchlist |
| 23 | `REDUCE` | `size_cap < 1.0` and no block triggers | Trade allowed at reduced size |
| 24 | `ALLOW` | All checks passed | Full trade allowed |

---

## Category F — Global Risk Level

**Source:** `risk/global_risk_layer.py`  
**Field name:** `global_risk_level`  
**Input:** `global_risk_score` (0–100)

| # | Label | Threshold | Interpretation |
|---|-------|-----------|----------------|
| 25 | `LOW` | Score 0–34 | Benign risk environment |
| 26 | `MEDIUM` | Score 35–59 | Moderate risk; caution warranted |
| 27 | `HIGH` | Score 60–100 | Elevated risk; defensive posture |

---

## Category G — Gamma Regime

### G.1 — Gamma Flip Classification

**Source:** `analytics/gamma_flip.py`  
**Field name:** `gamma_regime`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 28 | `POSITIVE_GAMMA` | `spot > gamma_flip_level` | Dealers long gamma; market self-stabilizing |
| 29 | `NEGATIVE_GAMMA` | `spot ≤ gamma_flip_level` | Dealers short gamma; market self-amplifying |
| 30 | `UNKNOWN` | Flip level cannot be computed | Insufficient data |

### G.2 — Market Gamma Map Classification

**Source:** `analytics/market_gamma_map.py`  
**Field name:** `gamma_regime`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 31 | `POSITIVE_GAMMA` | `total_gex > 0` AND `abs(total_gex) > gross_gex × 0.05` | Net positive dealer gamma exposure |
| 32 | `NEGATIVE_GAMMA` | `total_gex < 0` AND `abs(total_gex) > gross_gex × 0.05` | Net negative dealer gamma exposure |
| 33 | `NEUTRAL_GAMMA` | `abs(total_gex) ≤ gross_gex × 0.05` | Balanced gamma; neither positive nor negative |
| 34 | `UNKNOWN` | GEX computation fails | Insufficient data |

---

## Category H — Gamma Exposure Signal

**Source:** `analytics/gamma_exposure.py`  
**Field name:** `gamma_exposure_signal`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 35 | `LONG_GAMMA` | `total_gamma > 0` | Net long gamma in the chain |
| 36 | `SHORT_GAMMA` | `total_gamma ≤ 0` | Net short gamma in the chain |

---

## Category I — Volatility Regime

### I.1 — Realized Volatility Regime

**Source:** `analytics/volatility_regime.py`  
**Field name:** `volatility_regime`  
**Input:** Intraday returns standard deviation  
**Config:** `config/analytics_feature_policy.py` → `VolatilityRegimePolicyConfig`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 37 | `LOW_VOL` | `realized_vol < 0.01` | Subdued volatility; potential compression |
| 38 | `NORMAL_VOL` | `0.01 ≤ realized_vol < 0.03` | Typical volatility conditions |
| 39 | `VOL_EXPANSION` | `realized_vol ≥ 0.03` | Elevated volatility; regime shift possible |

### I.2 — Implied Volatility Regime (from Surface)

**Source:** `analytics/volatility_surface.py`  
**Field name:** `vol_regime`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 40 | `HIGH_VOL` | `implied_vol > 25` | Elevated IV; premium rich |
| 41 | `NORMAL_VOL` | `15 ≤ implied_vol ≤ 25` | Typical IV conditions |
| 42 | `LOW_VOL` | `implied_vol < 15` | Compressed IV; potential expansion ahead |
| 43 | `UNKNOWN` | IV computation fails | Insufficient data |

---

## Category J — Intraday Gamma Shift & Volatility Implication

**Source:** `analytics/intraday_gamma_shift.py`  
**Field name:** `gamma_shift` → mapped to `vol_implication`

### Gamma Shift Signal

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 44 | `NO_SHIFT` | `abs(gamma_change) < noise_threshold` (5%) | No meaningful gamma movement |
| 45 | `GAMMA_INCREASE` | `gamma_change ≥ noise_threshold` | Gamma exposure increasing |
| 46 | `GAMMA_DECREASE` | `gamma_change ≤ -noise_threshold` | Gamma exposure decreasing |

### Volatility Implication (Derived from Gamma Shift)

| # | Label | Mapped From | Interpretation |
|---|-------|------------|----------------|
| 47 | `VOL_EXPANSION` | `GAMMA_DECREASE` | Less gamma hedging → more volatility |
| 48 | `VOL_SUPPRESSION` | `GAMMA_INCREASE` | More gamma hedging → less volatility |
| 49 | `NEUTRAL` | `NO_SHIFT` | No volatility implication |

---

## Category K — Flow Signal

**Source:** `analytics/options_flow_imbalance.py`  
**Field name:** `flow_signal`  
**Input:** Call/put volume imbalance ratio  
**Config:** `config/analytics_feature_policy.py` → `FlowImbalancePolicyConfig`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 50 | `BULLISH_FLOW` | `imbalance_ratio ≥ 1.20` | Call-heavy flow dominance |
| 51 | `BEARISH_FLOW` | `imbalance_ratio ≤ 0.83` | Put-heavy flow dominance |
| 52 | `NEUTRAL_FLOW` | `0.83 < imbalance_ratio < 1.20` | Balanced call/put activity |

---

## Category L — Smart Money Flow

**Source:** `analytics/smart_money_flow.py`  
**Field name:** `smart_money_signal`  
**Input:** Large-block/unusual volume ratio  
**Config:** `config/analytics_feature_policy.py` → `SmartMoneyFlowPolicyConfig`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 53 | `BULLISH_FLOW` | `smart_ratio ≥ 1.15` | Institutional call-side accumulation |
| 54 | `BEARISH_FLOW` | `smart_ratio ≤ 0.87` | Institutional put-side accumulation |
| 55 | `MIXED_FLOW` | `0.87 < smart_ratio < 1.15` | Ambiguous institutional activity |
| 56 | `NO_FLOW` | No qualifying large-block activity detected | No institutional signal |

---

## Category M — Dealer Positioning

**Source:** `analytics/dealer_inventory.py`  
**Field name:** `dealer_position`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 57 | `Long Gamma` | Net dealer gamma > 0 | Dealers will hedge against moves (stabilizing) |
| 58 | `Short Gamma` | Net dealer gamma ≤ 0 | Dealers will hedge with moves (amplifying) |

---

## Category N — Dealer Hedging Bias

### N.1 — Hedging Flow Direction

**Source:** `analytics/dealer_hedging_flow.py`  
**Field name:** `dealer_hedging_flow`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 59 | `BUY_FUTURES` | Net dealer hedging requires buying | Upside pressure from hedging |
| 60 | `SELL_FUTURES` | Net dealer hedging requires selling | Downside pressure from hedging |

### N.2 — Hedging Bias (from Simulator)

**Source:** `analytics/dealer_hedging_simulator.py`  
**Field name:** `dealer_hedging_bias`  
**Input:** Spot vs key gamma levels (2% tolerance threshold)

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 61 | `PINNING` | Spot within 2% of major gamma level; balanced gamma | Price pinned by hedging flows |
| 62 | `UPSIDE_PINNING` | Spot near positive gamma wall above | Resistance from dealer hedging |
| 63 | `DOWNSIDE_PINNING` | Spot near negative gamma wall below | Support from dealer hedging |
| 64 | `UPSIDE_ACCELERATION` | Spot breaking above in negative gamma zone | Dealer hedging amplifies upside |
| 65 | `DOWNSIDE_ACCELERATION` | Spot breaking below in negative gamma zone | Dealer hedging amplifies downside |

---

## Category O — Liquidity Signal

### O.1 — Liquidity Heatmap

**Source:** `analytics/liquidity_heatmap.py`  
**Field name:** `liquidity_signal`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 66 | `STRONG_LEVEL_NEAR` | High OI concentration within 50 points of spot | Strong support/resistance nearby |
| 67 | `LEVEL_FAR` | No significant OI concentration within 50 points | No proximate liquidity wall |

### O.2 — Liquidity Vacuum

**Source:** `analytics/liquidity_vacuum.py`  
**Field name:** `vacuum_direction`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 68 | `BREAKOUT_ZONE` | OI in adjacent strikes < 25% of previous level | Void in liquidity; sharp move risk |
| 69 | `NORMAL` | Adequate OI in adjacent strikes | No vacuum; orderly market |

### O.3 — Liquidity Void

**Source:** `analytics/liquidity_void.py`  
**Field name:** `liquidity_void_signal`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 70 | `VOID_NEAR` | OI < 50 threshold within 50 points of spot | Nearby liquidity gap; slippage risk |
| 71 | `VOID_FAR` | OI < 50 threshold exists but beyond 50 points | Distant void; less immediate risk |

---

## Category P — Squeeze Risk State

**Source:** `risk/gamma_vol_acceleration_regime.py` → `_classify_squeeze_risk_state()`  
**Field name:** `squeeze_risk_state`  
**Input:** `gamma_vol_acceleration_score` (0–100)  
**Config:** `config/gamma_vol_acceleration_policy.py`

| # | Label | Threshold | Interpretation |
|---|-------|-----------|----------------|
| 72 | `EXTREME_ACCELERATION_RISK` | Score ≥ 78 | Gamma squeeze extremely likely; maximum caution |
| 73 | `HIGH_ACCELERATION_RISK` | Score ≥ 60 | High squeeze probability; reduced sizing |
| 74 | `MODERATE_ACCELERATION_RISK` | Score ≥ 40 | Moderate squeeze risk; monitor closely |
| 75 | `LOW_ACCELERATION_RISK` | Score < 40 | Low squeeze risk; normal operations |

---

## Category Q — Directional Convexity State

**Source:** `risk/gamma_vol_acceleration_regime.py` → `_directional_state()`  
**Field name:** `directional_convexity_state`  
**Inputs:** `gamma_vol_acceleration_score`, `upside_risk` (0–1), `downside_risk` (0–1)  
**Config thresholds:** `directional_edge = 0.58`, `two_sided_edge = 0.48`, `two_sided_balance_tolerance = 0.12`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 76 | `UPSIDE_SQUEEZE_RISK` | `upside ≥ 0.58` AND `upside > downside` | Directional gamma squeeze risk to the upside |
| 77 | `DOWNSIDE_AIRPOCKET_RISK` | `downside ≥ 0.58` AND `downside > upside` | Directional air-pocket risk to the downside |
| 78 | `TWO_SIDED_VOLATILITY_RISK` | Both `upside ≥ 0.48` AND `downside ≥ 0.48` AND `abs(upside - downside) ≤ 0.12` | Bidirectional volatility risk |
| 79 | `NO_CONVEXITY_EDGE` | Score < 25 AND `max(upside, downside) < 0.25`; or fallback | No significant convexity edge |

---

## Category R — Dealer Flow State

**Source:** `risk/dealer_hedging_pressure_regime.py` → `_state()`  
**Field name:** `dealer_flow_state`  
**Inputs:** `upside_pressure` (0–1), `downside_pressure` (0–1), `pinning_pressure` (0–1)  
**Config thresholds:** `upside/downside = 0.60`, `pinning = 0.62`, `two_sided = 0.48`, `balance_tolerance = 0.12`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 80 | `UPSIDE_HEDGING_ACCELERATION` | `upside ≥ 0.60` AND `upside > downside + 0.12` | Dealer hedging drives upside momentum |
| 81 | `DOWNSIDE_HEDGING_ACCELERATION` | `downside ≥ 0.60` AND `downside > upside + 0.12` | Dealer hedging drives downside momentum |
| 82 | `PINNING_DOMINANT` | `pinning ≥ 0.62` AND `pinning > max(upside, downside) + 0.08` | Dealer hedging pins price to gamma level |
| 83 | `TWO_SIDED_INSTABILITY` | Both `upside ≥ 0.48` AND `downside ≥ 0.48`; or near-balanced pressures ≥ 0.38 | Unstable hedging; whipsaw risk |
| 84 | `HEDGING_NEUTRAL` | Fallback (none of the above) | No dominant hedging pressure |

---

## Category S — Data Quality Status

**Source:** `engine/trading_support/signal_state.py`  
**Field name:** `data_quality_status`  
**Input:** `data_quality_score` (starts at 100, penalties applied)  
**Penalties:** Invalid spot (-45), stale spot (-10), invalid chain (-45), stale chain (-10), provider WEAK (-18), provider CAUTION (-8), missing analytics (variable)

| # | Label | Threshold | Interpretation |
|---|-------|-----------|----------------|
| 85 | `STRONG` | Score ≥ 85 | All data sources healthy |
| 86 | `GOOD` | Score ≥ 70 | Minor data gaps; signals reliable |
| 87 | `CAUTION` | Score ≥ 55 | Significant data issues; signals degraded |
| 88 | `WEAK` | Score < 55 | Critical data missing; signals unreliable |

---

## Category T — Provider Health Status

**Source:** `data/option_chain_validation.py`  
**Field name:** `provider_health.summary_status`  
**Downstream consumers:** Data quality score (Category S)

| # | Label | Decision Rule | Penalty |
|---|-------|--------------|---------|
| 89 | `WEAK` | Any individual provider rated WEAK | -18 to data quality |
| 90 | `CAUTION` | Any individual provider rated CAUTION (none WEAK) | -8 to data quality |
| 91 | `GOOD` | All providers healthy (implicit default) | No penalty |

---

## Category U — Confirmation Status

**Source:** `strategy/confirmation_filters.py`  
**Field name:** `confirmation_status`  
**Input:** Composite score from 8 confirmation voters  
**Config:** `config/signal_policy.py` → `CONFIRMATION_FILTER_CONFIG`

| # | Label | Threshold | Interpretation |
|---|-------|-----------|----------------|
| 92 | `STRONG_CONFIRMATION` | Score ≥ 6 | Multiple confirming signals aligned |
| 93 | `CONFIRMED` | Score ≥ 2 | Adequate confirmation for trade |
| 94 | `MIXED` | Score > -3 | Partial confirmation; watchlist candidate |
| 95 | `CONFLICT` | Score ≤ -3 | Conflicting signals; trade suppressed |

### Confirmation Voters (9 components)

| Voter | Field | Logic |
|-------|-------|-------|
| Open Alignment | `open_alignment_score` | Spot direction vs session open |
| Prev Close Alignment | `prev_close_alignment_score` | Spot direction vs previous close |
| Range Expansion | `range_expansion_score` | Intraday range vs microstructure thresholds |
| Flow Confirmation | `flow_confirmation_score` | Flow signal polarity match |
| Hedging Confirmation | `hedging_confirmation_score` | Hedging bias alignment (strong weight) |
| Gamma Event Confirmation | `gamma_event_confirmation_score` | Gamma squeeze event boost |
| Move Probability Confirmation | `move_probability_confirmation_score` | Hybrid move probability thresholds |
| Flip Alignment | `flip_alignment_score` | Spot vs gamma flip level alignment |
| Flip-Zone Gamma | `flip_zone_gamma_score` | Penalty when AT_FLIP with non-positive gamma regime (-3 negative, -2 neutral) |

---

## Category V — Trade Direction

**Source:** `engine/trading_support/signal_state.py` → `decide_direction()`  
**Field names:** `direction`, `direction_source`, `direction_vote_count`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 96 | `CALL` | `bullish_score ≥ 1.75` AND margin ≥ 0.7 AND bullish > bearish | Bullish directional trade |
| 97 | `PUT` | `bearish_score ≥ 1.75` AND margin ≥ 0.7 AND bearish > bullish | Bearish directional trade |
| 98 | `None` | Neither side meets minimum score/margin thresholds | No directional conviction |

### Direction Vote Weights

| Voter | Weight | Source Signal |
|-------|--------|--------------|
| FLOW | 1.20 | `final_flow_signal` polarity |
| HEDGING_BIAS | 1.10 | `dealer_hedging_bias` direction |
| GAMMA_SQUEEZE | 0.90 | Squeeze conditions detected |
| GAMMA_FLIP | 0.85 | Spot vs flip level position |
| DEALER_VOL | 0.80 | Dealer volatility positioning |
| VANNA | 0.45 | Vanna exposure signal |
| CHARM | 0.45 | Charm decay signal |
| BACKTEST_FALLBACK | 0.60 | Historical backtest bias |

**`direction_source` format:** Concatenation of winning voter names, e.g., `"FLOW+HEDGING_BIAS+GAMMA_SQUEEZE"`

**`direction_vote_count`:** Number of independent vote sources behind the chosen direction (derived from `direction_source`). A count of 2 (e.g., FLOW+CHARM) indicates thin conviction breadth; 4+ indicates broad structural alignment.

---

## Category W — Signal Regime

**Source:** `engine/trading_support/signal_state.py` → `classify_signal_regime()`  
**Field name:** `signal_regime`  
**Config thresholds:** `expansion_bias = 75`, `directional_bias = 55`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 99 | `LOCKDOWN` | `event_lockdown_flag == True` | All signals suppressed; macro event active |
| 100 | `EXPANSION_BIAS` | `strength ≥ 75` AND directional flow AND unstable gamma AND confirmation ∈ {STRONG, CONFIRMED} | Maximum conviction setup; gamma squeeze likely |
| 101 | `DIRECTIONAL_BIAS` | `strength ≥ 55` AND directional flow | Clear directional edge detected |
| 102 | `CONFLICTED` | `data_quality ∈ {CAUTION, WEAK}` OR `confirmation == CONFLICT` | Signals unreliable or contradictory |
| 103 | `BALANCED` | Falls through all checks (with valid direction) | Moderate conviction; standard setup |
| 104 | `NEUTRAL` | `direction is None` | No directional bias detected |

---

## Category X — Execution Regime

**Source:** `engine/trading_support/signal_state.py` → `classify_execution_regime()`  
**Field name:** `execution_regime`  
**Config thresholds:** `reduced_size_multiplier = 1.0`, `observe_data_quality = 70`

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 105 | `BLOCKED` | `trade_status ∈ {DATA_INVALID, EVENT_LOCKDOWN, NO_TRADE, BUDGET_FAIL}` | Trade execution prevented |
| 106 | `RISK_REDUCED` | `trade_status == TRADE` AND `size_multiplier < 1.0` | Trade allowed at reduced position size |
| 107 | `ACTIVE` | `trade_status == TRADE` (full size) | Full execution authorized |
| 108 | `OBSERVE` | `signal_regime == CONFLICTED` OR `data_quality_score < 70` | Monitor only; no execution |
| 109 | `SETUP` | Fallback (watchlist or near-actionable) | Setup forming; awaiting confirmation |

---

## Category Y — Trade Status

**Source:** `engine/signal_engine.py`  
**Field name:** `trade_status`  
**Final trade admission decision

| # | Label | Decision Rule | Interpretation |
|---|-------|--------------|----------------|
| 110 | `TRADE` | All gates passed; direction confirmed; strength above threshold | Execute trade |
| 111 | `WATCHLIST` | Partial conditions met; insufficient confirmation or strength | Monitor for entry |
| 112 | `NO_TRADE` | Signal too weak or conditions unfavorable | No opportunity |
| 113 | `DATA_INVALID` | Critical data missing or corrupt | Cannot evaluate |
| 114 | `NO_SIGNAL` | No meaningful signal generated | Flat market conditions |
| 115 | `BUDGET_FAIL` | Risk budget exhausted | Position limits reached |

---

## Category Z — Capture Policy

**Source:** `research/signal_evaluation/policy.py`  
**Field name:** `capture_policy`  
**Used by:** Signal evaluation framework for research capture filtering

| # | Label | Captures | Interpretation |
|---|-------|---------|----------------|
| 116 | `TRADE_ONLY` | `trade_status == "TRADE"` | Capture only executed trades |
| 117 | `ACTIONABLE` | `trade_status ∈ {"TRADE", "WATCHLIST"}` | Capture trades and watchlist signals |
| 118 | `ALL_SIGNALS` | All non-empty `trade_status` | Capture everything for research |

---

## Category AA — Composite Risk Metrics

These are continuous (0–1) scores rather than discrete labels. They feed into the categorical classifications above.

### AA.1 — Risk-Off Intensity

**Source:** `risk/global_risk_regime.py`  
**Field name:** `risk_off_intensity`  
**Range:** 0.0 – 1.0

**Formula:**
```
risk_off_intensity = 0.28 × volatility_component
                   + 0.20 × us_equity_component
                   + 0.12 × rates_component
                   + 0.12 × fx_component
                   + 0.16 × commodity_component
                   + 0.12 × macro_event_component
```

### AA.2 — Volatility Explosion Probability

**Source:** `risk/global_risk_regime.py`  
**Field name:** `volatility_explosion_probability`  
**Range:** 0.0 – 1.0  
**Critical threshold:** > 0.7 triggers `VOL_SHOCK` state

**Formula:**
```
volatility_explosion_probability = compression_score × (vol_shock_norm + macro_event_norm)
```

### AA.3 — Volatility Compression Score

**Source:** `risk/global_risk_regime.py`  
**Field name:** `volatility_compression_score`  
**Range:** 0.0 – 1.0  
**Input:** Ratio of 5-day to 30-day realized volatility

| Compression Level | Ratio Range | Score |
|-------------------|-------------|-------|
| Extreme | < 0.45 | Near 1.0 |
| Medium | 0.45 – 0.60 | 0.5 – 0.8 |
| Low | 0.60 – 0.75 | 0.2 – 0.5 |
| None | ≥ 0.75 | Near 0.0 |

---

## Category AB — Regime Fingerprint

**Source:** `research/signal_evaluation/evaluator.py` → `build_regime_fingerprint()`  
**Field names:** `regime_fingerprint`, `regime_fingerprint_id`

A deterministic hash encoding the full regime state for signal evaluation and deduplication.

### Components

```
signal_regime | macro_regime | gamma_regime | spot_vs_flip | flow
dealer_pos | hedging | vol | vacuum | confirm | dataq | provider
```

**Format:** `"signal_regime=EXPANSION_BIAS|macro_regime=RISK_ON|gamma_regime=NEGATIVE_GAMMA|..."`  
**`regime_fingerprint_id`:** First 16 characters of SHA-256 hash of the fingerprint string.

---

## Final Summary

### Statistics

| Metric | Count |
|--------|-------|
| **Total distinct symbolic labels** | 118 |
| **Categorical classifications** | 28 categories |
| **Composite continuous metrics** | 3 |
| **Confirmation voters** | 8 |
| **Direction voters** | 8 |
| **Layers traversed** | 5 (Data → Analytics → Risk/Overlay → Signal → Trade) |

### Ambiguities and Naming Inconsistencies

| Issue | Details | Suggestion |
|-------|---------|------------|
| **Duplicate `gamma_regime` field** | `gamma_flip.py` (3 values) and `market_gamma_map.py` (4 values) both produce `gamma_regime` | Rename one to `gamma_flip_regime` vs `gamma_map_regime` |
| **Overlapping `volatility_regime`** | `volatility_regime.py` (realized vol) and `volatility_surface.py` (implied vol) use similar names | Rename to `realized_vol_regime` vs `implied_vol_regime` |
| **Mixed flow label sets** | `options_flow_imbalance.py` uses `NEUTRAL_FLOW` while `smart_money_flow.py` uses `MIXED_FLOW` and `NO_FLOW` | Standardize: use `NEUTRAL_FLOW` / `NO_SIGNAL` consistently |
| **Dealer position strings** | `dealer_inventory.py` uses `"Long Gamma"` / `"Short Gamma"` (spaces, title case) while all other labels use `UPPER_SNAKE_CASE` | Standardize to `LONG_GAMMA` / `SHORT_GAMMA` |
| **`EVENT_LOCKDOWN` collision** | Both `macro_regime` and `global_risk_state` define `EVENT_LOCKDOWN` with slightly different triggers | Prefix: `MACRO_EVENT_LOCKDOWN` vs `GLOBAL_EVENT_LOCKDOWN` |
| **`RISK_OFF` collision** | Both `macro_regime` and `global_risk_state` define `RISK_OFF` | Prefix consistently or keep clear which layer owns the label |

### Standardization Recommendations

1. **Adopt UPPER_SNAKE_CASE universally** for all state labels (fix `"Long Gamma"` / `"Short Gamma"` in `dealer_inventory.py`)
2. **Prefix ambiguous labels** with their layer: `MACRO_`, `GLOBAL_`, `GAMMA_FLIP_`, `GAMMA_MAP_`
3. **Unify flow signal taxonomy** — choose one set of labels for bullish/bearish/neutral/no-signal across flow modules
4. **Document all threshold values in a central config registry** to avoid magic numbers scattered across modules
5. **Add `UNKNOWN` fallback** to every classifier that operates on potentially missing data (some classifiers already do this; make it universal)

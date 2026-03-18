---
title: Options Quant Engine
subtitle: Research Memo - Trade Signal Logic and Overlay Architecture
author: Research Architecture Note
date: 2026-03-14
---

<div class="memo-cover">
  <div class="cover-kicker">Options Quant Engine</div>
  <h1 class="cover-title">Research Memo</h1>
  <div class="cover-subtitle">Trade Signal Logic and Overlay Architecture</div>
  <div class="cover-rule"></div>
  <div class="cover-summary">
    A production-oriented options-buying engine for Indian index derivatives built around
    market microstructure, then refined through structured risk, convexity, dealer-flow,
    and option-efficiency overlays.
  </div>
  <div class="cover-meta">
    <div><span>Document Type</span>Research architecture memo</div>
    <div><span>Scope</span>Live engine, overlays, research dataset</div>
    <div><span>Status</span>Current implementation baseline</div>
    <div><span>Updated</span>2026-03-14</div>
  </div>
</div>

<div class="page-break"></div>

## Executive Summary

<div class="executive-summary">
<div class="summary-label">Investment Relevance</div>

This engine is designed to answer a specific execution question for directional option buying:

<strong>is there enough directional edge, enough path quality, and enough economic efficiency to justify buying this option now?</strong>

</div>

<div class="summary-grid">
<div class="summary-card">
<div class="summary-card-title">Primary Edge</div>
Dealer positioning, gamma structure, flow, and liquidity topology drive the core directional thesis.
</div>
<div class="summary-card">
<div class="summary-card-title">Control Layers</div>
Macro/news, global risk, convexity, dealer pressure, and option efficiency act as modifiers and filters rather than standalone direction engines.
</div>
<div class="summary-card">
<div class="summary-card-title">Research Posture</div>
Every captured signal is written into a canonical dataset so the overlays can be validated and calibrated empirically over time.
</div>
</div>

### Key Takeaways

- The engine is a layered execution-quality model, not a one-factor predictor.
- Direction comes primarily from dealer/gamma/flow/liquidity structure.
- Overlay layers improve trade selection by controlling exogenous risk, convexity instability, dealer-flow amplification, and option-pricing efficiency.
- Overnight decisions are conservative and combine multiple independent filters.
- The canonical signal dataset is the right place to calibrate and tune the system later.

<div class="page-break"></div>

## Key Findings

### Finding 1

The core signal engine is best understood as a microstructure thesis generator. Its strongest raw inputs are dealer state, gamma regime, flow, liquidity topology, and volatility context.

### Finding 2

The overlay stack materially improves execution discipline because it addresses different failure modes:

- macro/news and global risk address exogenous shocks
- gamma-vol acceleration addresses convex extension risk
- dealer hedging pressure addresses amplification versus pinning
- option efficiency addresses whether the option itself is worth buying

### Finding 3

The research dataset architecture is a strategic asset. Because the engine logs one canonical row per signal and enriches it over time, it supports later calibration without turning the live engine into an opaque tuned black box.

## Document Scope

This memo covers:

- the microstructure state vector
- the direction and move-quality logic
- the overlay architecture
- strike selection and overnight handling
- the canonical research data model

It does not attempt to present a theoretical options-pricing framework or a full statistical calibration study.

## Architecture

### Core Engine Flow

The live engine works in this order:

1. normalize and validate spot + option-chain inputs
2. build a microstructure state vector
3. infer direction conservatively
4. estimate move quality and path risk
5. apply structured overlay layers
6. rank strikes and set exits
7. emit a live trade decision and log the signal for research

The core implementation sits in `engine/signal_engine.py`, with helper logic in `engine/trading_support/` (a subpackage covering market state, probability, signal state, and trade modifiers). `engine/trading_engine.py` and `engine/trading_engine_support.py` remain as backward-compatible facades.

### State Vector

At each snapshot the engine builds a market state composed of:

- dealer state:
  - `dealer_pos`
  - `dealer_hedging_bias`
  - `dealer_hedging_flow`
- gamma state:
  - `gamma`
  - `gamma_flip`
  - `gamma_regime`
  - `gamma_event`
- flow state:
  - `flow_signal`
  - `smart_money_flow`
  - `final_flow_signal`
- liquidity state:
  - `support_wall`
  - `resistance_wall`
  - `liquidity_levels`
  - `liquidity_void_signal`
  - `liquidity_vacuum_state`
- volatility state:
  - `vol_regime`
  - `surface_regime`
  - `atm_iv`
- intraday context:
  - `spot_vs_flip`
  - `intraday_gamma_state`
  - `intraday_range_pct`

This is the core directional substrate of the engine.

### Direction Model

Direction is inferred with a weighted consensus model, not a single trigger.

Conceptually:

`S_bull = sum(w_i * bullish_i)`

`S_bear = sum(w_i * bearish_i)`

The engine only chooses a direction when:

- one side clears the minimum score threshold
- one side beats the other by a minimum margin
- the broader structure is not too conflicted

Inputs into the vote include:

- final flow
- gamma regime
- spot vs gamma flip
- dealer positioning
- hedging bias
- gamma squeeze context
- vanna/charm reinforcement when available

If the directional edge is not clear, the engine returns `NO_SIGNAL`.

### Move Probability Layer

The engine estimates whether the environment supports a meaningful move through a hybrid model:

- rule-based move probability
- ML move probability
- blended hybrid move probability

Useful inputs include:

- gamma regime
- vacuum state
- hedging bias
- flow alignment
- flip distance
- intraday range normalization
- ATM IV percentile

This is still a supporting layer. It does not override the directional vote by itself.

### Trade Strength

Conditional on direction, the engine builds a trade-strength score from aligned and conflicting evidence.

Main components include:

- flow alignment
- smart-money alignment
- gamma squeeze context
- dealer positioning
- volatility regime
- spot vs flip
- liquidity vacuum / void structure
- wall proximity
- intraday gamma shift
- move probability contribution
- directional consensus bonus or penalty

Interpretation:

- high score means thesis, path, and structure align
- low score means the market is noisy, pinned, or structurally conflicted

## Overlay Architecture

The engine applies five important overlay layers after the core microstructure thesis is built.

### Macro / News Layer

Purpose:

- classify headline sentiment and risk impact
- detect proximity to scheduled macro events (RBI, CPI, GDP, etc.)
- adjust or suppress trade decisions around high-impact event windows

Key outputs include:

- `macro_regime`
- `event_window_status`
- `event_severity_level`
- `headline_sentiment`
- `macro_news_score`

This layer is applied first and can gate all subsequent overlays.

### Global Risk Layer

Purpose:

- classify external/global regime stress
- penalize unstable overnight setups
- reduce or veto trades under event or volatility shock conditions

Key outputs include:

- `global_risk_state`
- `global_risk_score`
- `overnight_gap_risk_score`
- `volatility_expansion_risk_score`
- `overnight_hold_allowed`

This layer is intentionally non-directional.

### Gamma-Vol Acceleration Layer

Purpose:

- detect when a normal move may accelerate into squeeze, air pocket, or convex extension

Typical inputs:

- gamma regime
- spot vs flip
- flip proximity
- liquidity vacuum state
- volatility compression / shock transition
- macro/global stress

Key outputs:

- `gamma_vol_acceleration_score`
- `squeeze_risk_state`
- `upside_squeeze_risk`
- `downside_airpocket_risk`
- `overnight_convexity_risk`

This is a convexity overlay, not a primary direction engine.

### Dealer Hedging Pressure Layer

Purpose:

- estimate whether dealer hedging flows are likely to accelerate, destabilize, or pin the move

Typical inputs:

- gamma regime
- dealer hedging bias
- dealer hedging flow
- flip distance
- wall/liquidity structure
- flow confirmation
- macro/global stress as a modifier

Key outputs:

- `dealer_hedging_pressure_score`
- `dealer_flow_state`
- `upside_hedging_pressure`
- `downside_hedging_pressure`
- `pinning_pressure_score`

This layer improves trade filtering and ranking, especially for option buying.

### Expected Move / Option Efficiency Layer

Purpose:

- evaluate whether the option trade is economically attractive relative to the move the market is likely to make

Baseline expected move model:

`expected_move_points ~= spot * iv * sqrt(TTE_years)`

where:

- IV is normalized carefully from percent or decimal units
- TTE comes from the chain if present, otherwise parsed expiry metadata

Key outputs:

- `expected_move_points`
- `expected_move_pct`
- `target_reachability_score`
- `premium_efficiency_score`
- `strike_efficiency_score`
- `option_efficiency_score`

This is not a full theoretical pricing model. It is a practical trade-efficiency overlay for live filtering and research.

## Risk and Control Framework

### Strike Selection

After the engine has a direction, it ranks strikes by:

- proximity to spot and walls
- option liquidity and OI
- budget constraints
- optional overlay hooks

The expected move / option efficiency layer contributes a conservative ranking adjustment rather than replacing the strike selector.

### Overnight Logic

Overnight handling is deliberately conservative and combines multiple layers:

- global risk
- gamma-vol acceleration
- dealer hedging pressure
- option efficiency

The engine only allows overnight holds when these layers remain sufficiently contained. Otherwise it produces:

- `overnight_hold_allowed = False`
- an interpretable `overnight_hold_reason`
- accumulated overnight penalty fields

### Operational Philosophy

- degrade to neutral under missing or stale data
- keep overlays interpretable and auditable
- preserve backward compatibility for the live engine and research dataset
- prefer conservative filtering over overfit optimism

## Research Data Model

Every captured signal maps to one canonical row in `research/signal_evaluation/signals_dataset.csv`.

Important properties:

- one signal = one row
- keyed by `signal_id`
- rows are enriched over time
- dedupe-safe upsert
- stable schema for research

The dataset stores not just core signal fields, but also overlay outputs from:

- global risk
- gamma-vol acceleration
- dealer hedging pressure
- option efficiency

That makes it possible to test questions like:

- do convexity overlays improve ranking?
- do pinning-dominant regimes reduce option-buying profitability?
- does option efficiency reduce premium burn?
- do overnight filters improve next-open outcomes?

## Conclusion

This system should be read as a hierarchical execution-quality model:

- the core edge comes from dealer/gamma/flow/liquidity structure
- move probability estimates whether the move is large enough to matter
- overlay layers decide whether the path is amplified, dangerous, pinned, or inefficient
- the final decision is whether the setup is executable as an options trade

The right next research step is calibration of these overlays against the canonical dataset, not hidden rule growth.

<div class="page-break"></div>

## Appendix A - Core Formulas

<div class="appendix-note">
The live engine uses deterministic, interpretable formulas and bounded transformations rather than an opaque monolithic model.
</div>

| Component | Expression | Purpose |
| --- | --- | --- |
| Direction vote | `S_bull = sum(w_i * bullish_i)` | Weighted bullish evidence |
| Direction vote | `S_bear = sum(w_i * bearish_i)` | Weighted bearish evidence |
| Hybrid move probability | `clip(0.10 + 0.80 * (0.35 * p_rule + 0.65 * p_ml), 0.05, 0.95)` | Conservative move-quality blend |
| Expected move | `spot * iv * sqrt(TTE_years)` | Expected underlying move baseline |
| Flip distance | `abs(spot - gamma_flip) / spot * 100` | Local gamma instability proxy |
| Expected move coverage | `expected_move_points / target_distance_points` | Target reachability check |
| Premium coverage | `expected_option_move_value / entry_price` | Option efficiency check |

## Appendix B - Feature Layer Inventory

### Overlay Registry

| Layer | Role | Example Outputs |
| --- | --- | --- |
| Global risk | regime / veto / overnight filter | `global_risk_state`, `overnight_gap_risk_score` |
| Gamma-vol acceleration | convexity and squeeze overlay | `gamma_vol_acceleration_score`, `upside_squeeze_risk` |
| Dealer pressure | amplification vs pinning | `dealer_flow_state`, `pinning_pressure_score` |
| Option efficiency | expected move and premium economics | `option_efficiency_score`, `target_reachability_score` |

### Research-Friendly Feature Families

- microstructure features:
  - gamma regime
  - spot vs flip
  - dealer positioning
  - flow alignment
  - wall and vacuum context
- exogenous risk features:
  - macro event risk
  - global risk state
  - volatility shock / expansion state
- convexity features:
  - gamma-vol acceleration
  - upside squeeze risk
  - downside air-pocket risk
  - dealer hedging pressure
- economic-efficiency features:
  - expected move points
  - premium efficiency
  - strike efficiency
  - overnight option-efficiency penalty

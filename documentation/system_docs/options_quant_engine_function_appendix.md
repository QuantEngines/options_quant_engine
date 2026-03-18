---
title: "Options Quant Engine"
subtitle: "Function-Level Inventory and Logic Reference"
author: "Pramit Dutta"
date: "March 2026"
---

<div class="memo-cover">
<div class="cover-kicker">Technical Appendix</div>
<h1 class="cover-title">Options Quant Engine</h1>
<div class="cover-subtitle">Function-Level Inventory and Logic Reference</div>
<div class="cover-rule"></div>
<p class="cover-summary">A structured appendix enumerating the major logic-bearing functions in the codebase, together with their purposes, inputs, outputs, mathematical or heuristic basis, and downstream dependencies across the broader system architecture.</p>
<div class="cover-meta">
<div><span>Author</span>Pramit Dutta</div>
<div><span>Organization</span>Quant Engines</div>
<div><span>Document</span>Function Appendix</div>
<div><span>Date</span>March 2026</div>
<div><span>Scope</span>Major functions grouped by subsystem and operational role</div>
<div><span>Audience</span>Developers, reviewers, and research engineers navigating the codebase</div>
</div>
</div>

## Scope

This appendix lists the major logic-bearing functions in the codebase, grouped by subsystem and module. It focuses on functions that materially affect:

- data ingestion and normalization,
- analytical state construction,
- signal formation,
- overlay risk logic,
- research capture and evaluation,
- tuning, validation, promotion, and shadow workflows,
- backtest and replay behavior,
- interface orchestration.

For each major function, the appendix now explicitly records:

- file path,
- function name,
- purpose,
- key inputs,
- key outputs,
- math / logic basis,
- downstream dependencies.

Small utility helpers such as `_safe_float(...)`, `_clip(...)`, and trivial formatters have been consolidated into the `utils/` package (`utils/numerics.py`, `utils/math_helpers.py`, `utils/timestamp_helpers.py`). All modules now import from `utils/` rather than defining local copies. Class-only modules are noted where relevant, especially provider adapters whose primary surface is a class rather than a top-level function.

## 1. analytics

### [analytics/gamma_exposure.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/gamma_exposure.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `approximate_gamma` | Fallback gamma proxy when row-level gamma is absent | `strike`, `spot` | heuristic gamma value | inverse-distance style curvature proxy around spot; larger near-ATM, smaller far away | `calculate_gamma_exposure` |
| `calculate_gamma_exposure` | Compute aggregate signed gamma exposure | `option_chain`, optional `spot` | numeric net gamma exposure | sum of row gamma exposure using provider `GAMMA * OI * sign`; falls back to `approximate_gamma * OI * sign` | `gamma_signal`, `engine/trading_support/market_state.py::_collect_market_state` |
| `gamma_signal` | Classify long-gamma vs short-gamma regime | `option_chain`, optional `spot` | categorical gamma regime | sign test on aggregate gamma exposure | trade strength, overlays, direction logic |
| `calculate_gex` | Convenience wrapper for gamma exposure | `option_chain`, optional `spot` | same as net gamma exposure | wrapper around aggregate GEX computation | engine analytics state |

### [analytics/gamma_flip.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/gamma_flip.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `gamma_flip_level` | Estimate zero-crossing level of signed gamma exposure | `option_chain`, optional `spot`, `strike_window_steps` | gamma flip price or `None` | front-expiry near-ATM filtering, aggregate signed gamma by strike, locate sign change, linearly interpolate zero crossing | market state, dealer-liquidity map, overlays |
| `gamma_flip_distance` | Distance from spot to flip | `spot`, `flip` | absolute distance | simple absolute-distance metric | market state |
| `gamma_regime` | Above/below-flip regime classification | `spot`, `flip` | categorical regime | compare spot and estimated flip level | direction logic, overlays |

### [analytics/market_gamma_map.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/market_gamma_map.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `calculate_market_gamma` | Build strike-wise gamma map with notionalized weighting | `option_chain` | dataframe/series of gamma by strike | strike-level exposure using `gamma * open_interest * strike * sign` | `largest_gamma_strikes`, engine market state |
| `market_gamma_regime` | Classify aggregate market gamma regime | `gex` | categorical regime | sign/magnitude-based regime mapping | engine market state |
| `largest_gamma_strikes` | Identify dominant gamma clusters | `gex`, `top_n` | top gamma strike list | rank strikes by absolute or signed exposure magnitude | strike selection, liquidity map, overlays |

### [analytics/greeks_engine.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/greeks_engine.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `compute_option_greeks` | Scalar Black-Scholes Greek calculator | `spot`, `strike`, `time_to_expiry/expiry`, `iv`, `rate`, `option_type`, optional `q` | dict of `DELTA`, `GAMMA`, `THETA`, `VEGA`, `RHO`, `VANNA`, `CHARM` | Black-Scholes closed-form sensitivities via `d1`, `d2`, normal CDF/PDF | chain enrichment, research diagnostics |
| `enrich_chain_with_greeks` | Add Greek columns to chain rows | `option_chain`, optional `spot`, optional `valuation_time` | enriched dataframe | row-wise Greek evaluation with expiry parsing and numeric coercion | many analytics modules, engine support |
| `summarize_greek_exposures` | Collapse chain Greeks into exposure totals and regime labels | `option_chain` | aggregate exposures and qualitative labels | sum row Greeks weighted by OI/notional-like proxies; map sign to regime labels | engine market state, dealer dashboard |

### [analytics/dealer_inventory.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/dealer_inventory.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `dealer_inventory_metrics` | Estimate call/put OI change bias and inventory proxy | `option_chain` | metrics dict including OI change summaries | compare aggregate call vs put OI and OI-change; fall back to static OI if change unavailable | `dealer_inventory_position`, engine state |
| `dealer_inventory_position` | Classify dealer positioning regime | `option_chain` | categorical dealer position | map relative call/put inventory asymmetry to directional position label | overlays, dashboards |

### [analytics/dealer_hedging_flow.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/dealer_hedging_flow.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `dealer_hedging_flow` | Infer hedge direction from delta inventory | `option_chain` | coarse hedge-flow label or value | sum of `delta * open_interest`; sign mapped to buy-futures / sell-futures style interpretation | dealer-pressure features, engine state |

### [analytics/dealer_hedging_simulator.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/dealer_hedging_simulator.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `simulate_dealer_hedging` | Stress-test hedge demand under hypothetical move | `option_chain`, `price_move` | dict of hedge response up/down | local hedge simulation from net delta plus gross gamma sensitivity under `+/- price_move` shock | `hedging_bias`, engine state |
| `hedging_bias` | Convert simulated hedge response into pinning/acceleration label | `simulation` | categorical hedging bias | compare asymmetry between up-move and down-move hedge needs | direction logic, overlays, dashboards |

### [analytics/dealer_gamma_path.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/dealer_gamma_path.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `simulate_gamma_path` | Recompute aggregate gamma over hypothetical price grid | `option_chain`, `spot`, optional `step`, optional `range_points` | price grid and gamma curve | repeated gamma recomputation over hypothetical spot path | `detect_gamma_squeeze`, engine state |
| `detect_gamma_squeeze` | Detect sharp gamma-slope regions suggesting squeeze risk | `prices`, `gamma_curve` | squeeze score/state | normalized slope / steepness test on gamma curve | direction logic, gamma-vol overlay |

### [analytics/dealer_liquidity_map.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/dealer_liquidity_map.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `nearest_support_resistance` | Find nearest structural levels relative to spot | `spot`, `levels` | nearest support/resistance | nearest-level search on sorted structural levels | trade strength, strike selector |
| `estimate_squeeze_zone` | Bound the zone where squeeze-like extension is plausible | `spot`, `gamma_flip`, `gamma_clusters` | zone definition | band construction around flip and dominant gamma clusters | engine state, dashboards |
| `summarize_vacuum` | Normalize vacuum-zone descriptions | `vacuum_zones` | structured vacuum summary | clean and order vacuum intervals | engine state |
| `predict_large_move_band` | Produce coarse structural move band | `spot`, support/resistance/flip/structure inputs | price band / directional band | heuristic band expansion from nearby structural barriers and vacuum topology | large-move model, dashboards |
| `build_dealer_liquidity_map` | Build unified structural map from walls, clusters, vacuums | option-chain structural fields and `spot` | map dict | merge support/resistance, squeeze zone, vacuum summary, move band into one state object | trade strength, strike selection, overlays |

### [analytics/liquidity_heatmap.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/liquidity_heatmap.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_liquidity_heatmap` | Aggregate OI by strike | `option_chain` | liquidity summary | group-by strike and sum OI | `strongest_liquidity_levels` |
| `strongest_liquidity_levels` | Return dominant liquidity levels | `option_chain`, `top_n` | strike list | top-N ranking on strike-wise OI | engine state, strike selector |
| `liquidity_signal` | Classify spot relative to dominant liquidity levels | `spot`, `levels` | signal label | nearest-level comparison | trade strength |

### [analytics/liquidity_void.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/liquidity_void.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `detect_liquidity_voids` | Find low absolute OI regions | `option_chain`, `threshold` | void strike list | fixed-threshold filter on strike-wise OI | trade strength, engine state |
| `nearest_liquidity_void` | Find closest void to spot | `spot`, `voids` | nearest void | nearest-distance search | engine state |
| `liquidity_void_signal` | Convert void structure into label | `spot`, `voids` | categorical signal | compare spot to nearest void location | trade strength |

### [analytics/liquidity_vacuum.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/liquidity_vacuum.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `detect_liquidity_vacuum` | Find discontinuity-like strike gaps in OI | `option_chain` | vacuum zone list | adjacent-strike OI gap test, often using a ratio threshold | gamma-vol and dealer-pressure overlays |
| `vacuum_direction` | Classify likely directional vulnerability relative to vacuums | `spot`, `vacuum_zones` | direction label | compare spot location to vacuum intervals above/below | engine state |

### [analytics/options_flow_imbalance.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/options_flow_imbalance.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `calculate_flow_imbalance` | Compare front-expiry near-ATM call vs put notional flow | `option_chain`, optional `spot` | imbalance metric | near-ATM front-expiry notional aggregation, call-vs-put ratio/difference | `flow_signal`, engine state |
| `flow_signal` | Convert imbalance into bullish/bearish/neutral label | `option_chain`, optional `spot` | flow label | thresholding on imbalance metric | direction logic, trade strength |

### [analytics/smart_money_flow.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/smart_money_flow.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `detect_unusual_volume` | Identify unusual volume/OI behavior | `option_chain`, optional `spot` | candidate unusual-flow records | heuristics over volume/OI ratio, OI change, and flow notional | `classify_flow` |
| `classify_flow` | Convert unusual volume records to flow classification | `spikes` | bullish/bearish/mixed classification | rule-based aggregation across unusual-flow records | `smart_money_signal` |
| `smart_money_signal` | Public wrapper for smart-money-like flow label | `option_chain`, optional `spot` | signal label | unusual-volume detection plus classifier | direction logic, trade strength |

### [analytics/volatility_surface.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/volatility_surface.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_vol_surface` | Create simplified IV surface representation | `option_chain` | surface summary | organize IV by strike/expiry slices | engine state |
| `atm_vol` | Extract ATM IV proxy | `option_chain`, `spot` | ATM IV | nearest-strike-to-spot IV lookup / averaging | engine state, option efficiency |
| `vol_regime` | Classify IV regime | `atm_iv` | low/normal/high regime | thresholding on ATM IV | trade strength, overlays |

### [analytics/volatility_regime.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/volatility_regime.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `compute_realized_volatility` | Heuristic realized-vol measure from option-chain context | `option_chain` | realized vol estimate | standard-deviation-like measure on available price changes in chain context | `detect_volatility_regime` |
| `detect_volatility_regime` | Convert realized-vol estimate into regime label | `option_chain` | vol regime | threshold mapping on realized-vol estimate | engine state |
| `volatility_signal` | Public wrapper for vol regime | `option_chain` | signal label | wrapper over realized-vol regime classification | trade strength |

### [analytics/intraday_gamma_shift.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/intraday_gamma_shift.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `compute_gamma_profile` | Compute current profile summary for comparison | `option_chain`, optional `spot` | gamma profile | summarize gamma exposure over current snapshot | `detect_gamma_shift` |
| `detect_gamma_shift` | Compare previous and current profiles | `previous_chain`, `current_chain`, optional `spot` | shift metrics | difference or directional change in profile statistics | `gamma_shift_signal`, engine state |
| `gamma_shift_signal` | Classify shift direction | `previous_chain`, `current_chain`, optional `spot` | categorical state | thresholding on change metrics | trade strength, overlays |

### [analytics/flow_utils.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/flow_utils.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `infer_strike_step` | Infer strike granularity from chain | `option_chain` | numeric strike step | minimum positive difference across sorted unique strikes | front-expiry slice helpers |
| `front_expiry_atm_slice` | Restrict analysis to front expiry and ATM window | `option_chain`, optional `spot`, `strike_window_steps` | filtered dataframe | select chosen expiry then keep strikes within `spot +/- strike_window_steps * strike_step` | gamma-flip and flow analytics |

### [analytics/gamma_walls.py](/Users/pramitdutta/Desktop/options_quant_engine/analytics/gamma_walls.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `detect_gamma_walls` | Legacy wall detector using highest OI strikes | `option_chain`, `top_n` | strike list | rank strikes by aggregated OI using legacy column names | older structure logic / conceptual support |
| `classify_walls` | Legacy support/resistance wall classifier | `option_chain` | dict with support/resistance | max call OI = resistance, max put OI = support | older structure logic |

## 2. engine

### [engine/trading_engine.py](/Users/pramitdutta/Desktop/options_quant_engine/engine/trading_engine.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `generate_trade` | Main signal/trade construction entrypoint | `symbol`, `spot`, `option_chain`, `previous_chain`, validations, macro/news/global risk state, budget inputs, valuation time | comprehensive trade payload | staged inference pipeline: normalize -> analytics -> probability -> direction -> trade strength -> confirmation -> macro adjustment -> overlay modifiers -> strike ranking -> option efficiency -> budget sizing -> status classification | CLI, Streamlit, replay, research capture, shadow mode, backtest |

### engine/trading_support/ (re-exported via engine/trading_engine_support.py facade)

The actual implementations live in `engine/trading_support/common.py`, `engine/trading_support/market_state.py`, `engine/trading_support/probability.py`, `engine/trading_support/signal_state.py`, and `engine/trading_support/trade_modifiers.py`. The facade `engine/trading_engine_support.py` re-exports all public names for backward compatibility.

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `normalize_option_chain` | Canonicalize chain columns and numeric fields | `option_chain`, optional `spot`, optional `valuation_time` | normalized dataframe | schema harmonization, type coercion, optional Greek enrichment | `generate_trade`, analytics |
| `derive_global_risk_trade_modifiers` | Convert global-risk state into score/status modifiers | `global_risk_state` | modifier dict | rule-based mapping from state and penalties to score/status/overnight blocks | `generate_trade` |
| `derive_gamma_vol_trade_modifiers` | Convert gamma-vol state into modifiers | `gamma_vol_state`, optional `direction` | modifier dict | align or oppose directional convexity state with trade direction to compute boosts/penalties | `generate_trade` |
| `derive_dealer_pressure_trade_modifiers` | Convert dealer-pressure state into modifiers | `dealer_pressure_state`, optional `direction` | modifier dict | boost aligned acceleration, damp pinning, penalize two-sided instability | `generate_trade` |
| `derive_option_efficiency_trade_modifiers` | Convert option-efficiency state into score/overnight modifiers | `option_efficiency_state` | modifier dict | threshold-based economic-efficiency adjustments | `generate_trade` |
| `classify_spot_vs_flip` | Standardize spot-vs-flip relationship | `spot`, `flip` | categorical label | sign comparison and distance interpretation | engine state, overlays |
| `classify_spot_vs_flip_for_symbol` | Symbol-aware spot-vs-flip classifier | `symbol`, `spot`, `flip` | categorical label | same as above with symbol-specific config hook | direction logic |
| `classify_signal_quality` | Map trade strength to quality bucket | `trade_strength` | quality label | threshold bucketing | payload, research capture |
| `classify_signal_regime` | Map state variables to higher-level signal regime | score, direction, analytics and overlay context | regime label | rule-based combination of direction, volatility, gamma, and risk context | payload, research capture |
| `classify_execution_regime` | Convert trade/policy state into execution regime | `trade_status`, `signal_regime`, `data_quality_score`, `macro_position_size_multiplier` | execution regime label | threshold and status mapping | payload, dashboards |
| `normalize_flow_signal` | Merge flow/smart-flow signals into normalized representation | `flow_signal_value`, `smart_money_signal_value` | normalized directional label | precedence/consensus logic across flow signals | direction logic |
| `decide_direction` | Weighted-vote directional inference | large market-state dict | direction + source metadata | additive weighted voting across flow, hedging bias, gamma squeeze, flip regime, charm/vanna, move probability context | `generate_trade` |
| `_collect_market_state` | Build full analytical state from normalized chain | `df`, `spot`, optional `symbol`, optional `prev_df` | market-state dict | orchestrated calls into analytics modules plus derived metrics such as `gamma_flip_distance_pct`, `intraday_range_pct`, `atm_iv_percentile` | probability state, trade strength, overlays |
| `_compute_probability_state` | Build rule/ML/hybrid move-probability state; dispatches through pluggable predictor factory when `PREDICTION_METHOD` is non-default | market-state dict plus predictor config | probability dict | fast-path blended pipeline or factory-resolved predictor dispatch (pure_ml, pure_rule, research_dual_model, or custom) | direction logic, trade strength, confirmation |
| `_compute_signal_state` | Assemble direction, score, confirmation, and quality state | market state, probability state, macro adjustments | signal-state dict | combines directional vote, score aggregation, confirmation output, and runtime threshold metadata | `generate_trade` |
| `_compute_data_quality` | Collapse data-health signals into numeric/qualitative score | validations, analytics state, probability state | data-quality dict | score aggregation across validation flags and missing-state penalties | trade gating, execution regime |

### [engine/runtime_metadata.py](/Users/pramitdutta/Desktop/options_quant_engine/engine/runtime_metadata.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `split_trade_payload` | Split a merged trade payload into execution-facing and audit-facing views | trade dict | execution trade dict, audit dict | key-partitioning between routing/monitoring fields and research diagnostics | runner, operator views |
| `attach_trade_views` | Attach explicit trade subviews while preserving the legacy merged payload | trade dict | enriched trade dict | stable structural split over known execution keys | signal engine, runner |
| `empty_scoring_breakdown` | Create empty scoring scaffold | none | dict | default-initialization helper | UI payload defaults |
| `empty_confirmation_state` | Create empty confirmation scaffold | none | dict | default-initialization helper | UI payload defaults |

## 3. strategy

### [strategy/trade_strength.py](/Users/pramitdutta/Desktop/options_quant_engine/strategy/trade_strength.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `compute_trade_strength` | Aggregate aligned directional and structural evidence | market-state fields, direction, move probabilities | scalar trade strength and component breakdown | weighted additive score over bounded feature transforms for flow, hedging, flip, liquidity, walls, probability, and consensus | `generate_trade`, research capture |

### [strategy/confirmation_filters.py](/Users/pramitdutta/Desktop/options_quant_engine/strategy/confirmation_filters.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `compute_confirmation_filters` | Confirm or veto directional hypothesis | direction, spot/open/prev-close/range, flow, hedging, gamma, probability inputs | confirmation dict | rule-based consistency checks with positive and negative confirmations, converted to confirmation score/state | `generate_trade`, global-risk gating |

### [strategy/strike_selector.py](/Users/pramitdutta/Desktop/options_quant_engine/strategy/strike_selector.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `rank_strike_candidates` | Score option contracts for the chosen direction | option-chain slice, direction, spot, structure context, optional hook | ranked candidate records | additive strike score over moneyness, directional side, premium band, liquidity, wall distance, gamma-cluster distance, IV, optional hook | `generate_trade`, Streamlit ranked-strike tables |
| `select_best_strike` | Select top candidate from ranked list | ranked candidates | chosen candidate | choose maximum-ranked feasible candidate | `generate_trade` |

### [strategy/budget_optimizer.py](/Users/pramitdutta/Desktop/options_quant_engine/strategy/budget_optimizer.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `optimize_lots` | Compute feasible lot sizing under capital limit | `entry_price`, `lot_size`, `requested_lots`, `max_capital` | lot plan dict | integer lot affordability under premium-cost cap | `generate_trade`, backtest |

### [strategy/exit_model.py](/Users/pramitdutta/Desktop/options_quant_engine/strategy/exit_model.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `calculate_exit` | Build target/stop from entry premium and configured percents | `entry_price`, target/stop parameters | target and stop values | `target = entry * (1 + tp)` and `stop = entry * (1 - sl)` style fixed-percentage rule | `generate_trade`, backtest |

## 4. risk

### [risk/global_risk_features.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/global_risk_features.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_global_risk_features` | Build cross-asset and macro-based risk feature set | `macro_event_state`, `macro_news_state`, `global_market_snapshot`, `holding_profile`, `as_of` | feature dict | deterministic transforms on 24h cross-asset changes, realized-vol compression, macro event risk, holding/session context, with stale-data neutralization | `classify_global_risk_state` |

### [risk/global_risk_regime.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/global_risk_regime.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `classify_global_risk_state` | Convert raw features to interpretable regime state | feature dict | `GlobalRiskState` dataclass | thresholded regime rules over volatility explosion probability, macro-event risk, signed risk score, overnight-risk logic | engine gating, research capture |

### [risk/global_risk_layer.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/global_risk_layer.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_global_risk_state` | Public facade for global-risk-state construction | macro event/news state, global market snapshot, holding context | structured risk state dict | feature build followed by regime classification | runner, trading engine |
| `evaluate_global_risk_layer` | Translate global risk into actionability and size policy | global-risk state plus trade/confirmation/data context | gating result dict | explicit policy map from risk state, risk score, event context, and confirmation to action/size cap/trade status | `generate_trade` |

### [risk/gamma_vol_acceleration_features.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/gamma_vol_acceleration_features.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_gamma_vol_acceleration_features` | Build convexity-acceleration feature set | gamma/flip/liquidity/vol/macro/global inputs | feature dict | additive bounded feature model over gamma regime, flip proximity, volatility transition, vacuum state, hedging bias, intraday extension, macro/global boost | `classify_gamma_vol_acceleration_state` |

### [risk/gamma_vol_acceleration_regime.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/gamma_vol_acceleration_regime.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `classify_gamma_vol_acceleration_state` | Produce squeeze/air-pocket/overnight-convexity state | feature dict | `GammaVolAccelerationState` | thresholded score classification plus directional decomposition into upside/downside/two-sided convexity states | engine overlay modifiers, research capture |

### [risk/gamma_vol_acceleration_layer.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/gamma_vol_acceleration_layer.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_gamma_vol_acceleration_state` | Public facade for acceleration layer | market state + macro/global inputs | structured acceleration state | feature build + regime classification | `generate_trade` |

### [risk/dealer_hedging_pressure_features.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/dealer_hedging_pressure_features.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_dealer_hedging_pressure_features` | Build feature set for hedging reinforcement and pinning | gamma/flip/hedging/flow/structure/macro/global inputs | feature dict | additive directional pressure model across gamma base, flip sensitivity, hedging bias, hedge flow, flow confirmation, structural concentration, macro/global boost | `classify_dealer_hedging_pressure_state` |

### [risk/dealer_hedging_pressure_regime.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/dealer_hedging_pressure_regime.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `classify_dealer_hedging_pressure_state` | Convert features into dealer-flow regime state | feature dict | `DealerHedgingPressureState` | compare upside/downside/pinning pressure magnitudes and classify dominant or unstable regime | engine overlay modifiers, research capture |

### [risk/dealer_hedging_pressure_layer.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/dealer_hedging_pressure_layer.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_dealer_hedging_pressure_state` | Public facade for dealer-pressure layer | market state + macro/global inputs | structured dealer-pressure state | feature build + regime classification | `generate_trade` |

### [risk/option_efficiency_features.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/option_efficiency_features.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_option_efficiency_features` | Build expected-move and contract-efficiency feature set | `spot`, `atm_iv`, `expiry/TTE`, `direction`, `strike`, `entry_price`, `target`, `stop_loss`, overlay context | feature dict | expected move via `spot * iv * sqrt(T)`, target distance vs expected move, premium coverage ratio, strike moneyness, convexity-adjusted payoff hints | option-efficiency layer |

### [risk/option_efficiency_layer.py](/Users/pramitdutta/Desktop/options_quant_engine/risk/option_efficiency_layer.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `classify_option_efficiency_state` | Score reachability, premium efficiency, strike efficiency, overnight penalty | feature dict | `OptionEfficiencyState` | deterministic scoring functions over target reachability, premium burden, strike geometry, then weighted adjustment and overnight evaluation | engine overlay modifiers, research capture |
| `build_option_efficiency_state` | Public facade for full contract-efficiency evaluation | keyword args for feature builder and classifier | structured option-efficiency state | feature build + state classification | `generate_trade` |
| `score_option_efficiency_candidate` | Lightweight hook for strike-ranking enhancement | candidate contract inputs + market context | scalar candidate adjustment | reduced-form option-efficiency scoring without full final-trade evaluation | `strategy/strike_selector.py`, `generate_trade` |

## 5. data

### [data/expiry_resolver.py](/Users/pramitdutta/Desktop/options_quant_engine/data/expiry_resolver.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `normalize_expiry_value` | Standardize provider expiry formats | raw expiry | normalized expiry string | string/date normalization and canonical formatting | resolver helpers, validation |
| `ordered_expiries` | Return sorted expiry list from chain | `option_chain` | ordered expiries | normalize then sort parsed expiry values | `resolve_selected_expiry` |
| `resolve_selected_expiry` | Choose primary expiry for analysis | `option_chain` | selected expiry | front/nearest expiry preference | runner, analytics helpers, backtest |
| `filter_option_chain_by_expiry` | Restrict chain to one expiry | `option_chain`, `selected_expiry` | filtered dataframe | exact normalized-expiry match filter | runner, analytics, backtest |

### [data/option_chain_validation.py](/Users/pramitdutta/Desktop/options_quant_engine/data/option_chain_validation.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `validate_option_chain` | Evaluate whether chain is usable for live/replay analysis | `option_chain` | validation dict | rule-based quality checks on schema, CE/PE balance, IV presence, pairing integrity, duplicates, expiry breadth | runner, trading engine |

### [data/provider_normalization.py](/Users/pramitdutta/Desktop/options_quant_engine/data/provider_normalization.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `normalize_live_option_chain` | Canonicalize provider-specific chain columns | raw provider chain, `source`, `symbol` | normalized dataframe | alias mapping and numeric coercion into canonical schema | router, analytics, engine |

### [data/spot_downloader.py](/Users/pramitdutta/Desktop/options_quant_engine/data/spot_downloader.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `get_spot_snapshot` | Fetch live spot snapshot and context fields | `symbol` | spot snapshot dict | Yahoo intraday/daily retrieval plus lookback range computation and snapshot assembly | runner |
| `validate_spot_snapshot` | Check snapshot freshness and completeness | spot snapshot dict, `replay_mode` | validation dict | rule checks on age, presence of key fields, and live-vs-replay policy | runner, engine data quality |
| `get_spot_price` | Convenience spot fetch | `symbol` | scalar spot | thin wrapper over spot snapshot acquisition | support tooling |
| `save_spot_snapshot` | Persist spot snapshot for replay/debug | snapshot dict, output dir | file path | JSON persistence of spot state | runner, replay workflows |

### [data/global_market_snapshot.py](/Users/pramitdutta/Desktop/options_quant_engine/data/global_market_snapshot.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_global_market_snapshot` | Fetch cross-asset market snapshot with neutral fallback | `symbol`, optional `as_of` | snapshot dict | download histories for mapped global tickers, compute 24h changes and realized vols, degrade to neutral if missing/stale/disabled | runner, global risk layer |

### [data/replay_loader.py](/Users/pramitdutta/Desktop/options_quant_engine/data/replay_loader.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `load_spot_snapshot` | Load saved replay spot JSON | `path` | snapshot dict | JSON file read and decode | runner, replay regression |
| `load_option_chain_snapshot` | Load saved replay chain file | `path` | dataframe | CSV/JSON loader with schema restoration | runner, replay regression |
| `save_option_chain_snapshot` | Persist chain for replay/debug | dataframe, symbol, source | file path | file serialization with timestamped naming | runner |
| `latest_replay_snapshot_paths` | Find newest matching replay files | `symbol`, `replay_dir` | `(spot_path, chain_path)` | filename pattern matching and timestamp ordering | runner |

### [data/historical_iv_surface.py](/Users/pramitdutta/Desktop/options_quant_engine/data/historical_iv_surface.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `load_historical_iv_surface` | Load cached IV-surface history | `symbol`, `years` | dataframe or empty | candidate-path search and CSV load | historical chain builder |
| `get_surface_iv` | Query cached IV surface for timestamp/strike/type | IV dataframe, `timestamp`, `strike`, `option_type`, `default_iv` | IV value | nearest/filtered lookup with fallback to default IV | historical chain builder |

### [data/historical_option_chain.py](/Users/pramitdutta/Desktop/options_quant_engine/data/historical_option_chain.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `load_option_chain` | Load cached or synthetic historical option chain | `symbol`, `years` | dataframe | load cached history if present; otherwise synthesize option chain from spot history, next-expiry logic, IV fallback, and simplified Black-Scholes pricing | intraday backtester |

### Class-centric provider modules

These files are major data modules, but their primary public surface is class-based rather than top-level functions:

- [data/data_source_router.py](/Users/pramitdutta/Desktop/options_quant_engine/data/data_source_router.py): `DataSourceRouter`
  - Math / logic basis: provider selection, fetch delegation, normalization routing.
- [data/nse_option_chain_downloader.py](/Users/pramitdutta/Desktop/options_quant_engine/data/nse_option_chain_downloader.py): `NSEOptionChainDownloader`
  - Math / logic basis: provider-specific HTTP/session handling and response parsing.
- [data/icici_breeze_option_chain.py](/Users/pramitdutta/Desktop/options_quant_engine/data/icici_breeze_option_chain.py): `ICICIBreezeOptionChain`
  - Math / logic basis: Breeze API orchestration and provider normalization.
- [data/zerodha_option_chain.py](/Users/pramitdutta/Desktop/options_quant_engine/data/zerodha_option_chain.py): `ZerodhaOptionChain`
  - Math / logic basis: Zerodha-specific acquisition workflow.

Their downstream dependency is straightforward: they feed normalized chains into the router, and the router feeds the runner.

## 6. models

### [models/feature_builder.py](/Users/pramitdutta/Desktop/options_quant_engine/models/feature_builder.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_features` | Build compact feature vector for move prediction | selected analytics fields | numeric feature array/list | deterministic feature extraction and ordering from market-state fields | `models/move_predictor.py`, research experiments |

### [models/large_move_probability.py](/Users/pramitdutta/Desktop/options_quant_engine/models/large_move_probability.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `large_move_probability` | Produce deterministic move-probability estimate from structure | gamma, liquidity, flow, vol, structure features | probability-like scalar | clipped heuristic additive model over structural features, bounded to \[0,1] | engine probability state |

### [models/ml_move_predictor.py](/Users/pramitdutta/Desktop/options_quant_engine/models/ml_move_predictor.py)

| Function / class surface | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `MovePredictor` | Live-facing prediction wrapper with fallback behavior | feature vectors / market-state inputs | move probability | delegates to base model if present, otherwise uses stable heuristic fallback mapping | engine probability state |

### [models/move_predictor.py](/Users/pramitdutta/Desktop/options_quant_engine/models/move_predictor.py)

| Function / class surface | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `MovePredictor` | Trainable RandomForest wrapper | training data or feature vectors | class prediction / probability | scikit-learn RandomForest classification | research-only or optional ML workflow |

### engine/predictors/ (pluggable predictor architecture)

| Function / class surface | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `MovePredictor` (Protocol) | Defines the predictor contract | — | `name` property, `predict(market_ctx)` method | `typing.Protocol` with `@runtime_checkable` | all predictors, factory |
| `PredictionResult` (dataclass) | Standardized prediction output | — | `rule_move_probability`, `ml_move_probability`, `hybrid_move_probability`, `model_features`, `components`, `predictor_name` | frozen dataclass | all callers |
| `get_predictor` | Return singleton active predictor resolved from config | `PREDICTION_METHOD` setting | `MovePredictor` instance | registry lookup with lazy initialization | `_compute_probability_state`, backtester |
| `reset_predictor` | Clear singleton for re-initialization | — | — | state reset | testing, hot-swap |
| `register_predictor` | Register custom predictor class | name, class | — | registry mutation | custom extensions |
| `prediction_method_override` | Context manager for temporary predictor swap | method name | `MovePredictor` instance | save/swap/restore singleton state | backtester, research |
| `DefaultBlendedPredictor` | Production blended predictor | `market_ctx` dict | `PredictionResult` | delegates to `_compute_probability_state_impl(...)` | default production path |
| `PureRulePredictor` | Rule-only predictor | `market_ctx` dict | `PredictionResult` | calls impl with `_force_rule_only=True`, sets `hybrid = rule_probability` | research, backtesting |
| `PureMLPredictor` | ML-only predictor | `market_ctx` dict | `PredictionResult` | calls impl with `_force_ml_only=True`, sets `hybrid = ml_probability` | research, backtesting |
| `ResearchDualModelPredictor` | GBT ranking + LogReg calibration | `market_ctx` dict | `PredictionResult` | runs standard pipeline, overlays research `infer_single(...)`, uses calibrated confidence as hybrid | research evaluation |
| `ResearchDecisionPolicyPredictor` | Dual-model + decision-policy overlay | `market_ctx` dict | `PredictionResult` | runs dual-model pipeline, evaluates dual-threshold policy from `research/decision_policy/`, BLOCK → 0.0, DOWNGRADE → ×0.5 | research evaluation |

## 7. macro and news

### [macro/scheduled_event_risk.py](/Users/pramitdutta/Desktop/options_quant_engine/macro/scheduled_event_risk.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `load_scheduled_macro_events` | Load event schedule JSON | optional schedule path | list of event dicts | JSON load plus event normalization | `evaluate_scheduled_event_risk` |
| `evaluate_scheduled_event_risk` | Produce event-window risk state for current timestamp | `symbol`, optional `as_of`, schedule settings | event-state dict | relative-time logic around warning / lockdown / live-event / cooldown windows with severity-to-risk mapping | runner, macro-news aggregator, global risk |

### [macro/macro_news_aggregator.py](/Users/pramitdutta/Desktop/options_quant_engine/macro/macro_news_aggregator.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_macro_news_state` | Aggregate event risk and classified headlines into macro-news state | `event_state`, `headline_state`, optional `as_of` | `MacroNewsState` | age-decayed headline weighting, sentiment/impact aggregation, macro regime derivation | runner, trading engine, global risk |

### [macro/engine_adjustments.py](/Users/pramitdutta/Desktop/options_quant_engine/macro/engine_adjustments.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `compute_macro_news_adjustments` | Convert macro-news state into score/confirmation/size modifiers | `direction`, optional `macro_news_state` | modifier dict | deterministic directional adjustment map based on macro regime, event lock, and macro bias | `generate_trade` |

### [macro/scope_utils.py](/Users/pramitdutta/Desktop/options_quant_engine/macro/scope_utils.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `normalize_scope` | Standardize scope labels for headline/event mapping | raw scope value | normalized list | string/list normalization | headline classifier, event handling |
| `symbol_scope_matches` | Check whether scope applies to symbol | `symbol`, `scopes` | boolean | symbol membership / matching logic | macro-news aggregation |
| `headline_mentions_symbol` | Detect symbol mentions in text | `symbol`, `headline` | boolean | keyword/string match | headline classification relevance |

### [news/classifier.py](/Users/pramitdutta/Desktop/options_quant_engine/news/classifier.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `classify_headline` | Deterministically score one headline | `HeadlineRecord` | `HeadlineClassification` | keyword/category matching with category multipliers for sentiment, vol, impact, India/global bias | `classify_headlines`, macro-news aggregator |
| `classify_headlines` | Batch-classify headline records | list of `HeadlineRecord` | classification list | map single-headline classifier over records | macro-news aggregator |

### [news/service.py](/Users/pramitdutta/Desktop/options_quant_engine/news/service.py)

| Function / class surface | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `HeadlineIngestionService` | Fetch and normalize headlines with stale fallback | `symbol`, optional `as_of`, replay mode | `HeadlineIngestionState` | provider fetch + stale-data checks + neutral fallback policy | runner, macro-news aggregator |
| `build_default_headline_service` | Construct default ingestion service | none | service instance | provider factory assembly | CLI, Streamlit, smoke tests |
| `headline_records_to_frame` | Convert records to dataframe | headline records | dataframe | dataclass-to-table conversion | Streamlit displays, research tooling |

### [news/providers.py](/Users/pramitdutta/Desktop/options_quant_engine/news/providers.py)

| Function / class surface | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `MockHeadlineProvider` | JSON/mock headline source | configuration / symbol | headline records | local fixture loading / filtering | ingestion service |
| `RSSHeadlineProvider` | RSS-based live headline source | feed configuration / symbol | headline records | RSS parsing, timestamp normalization, record construction | ingestion service |
| `build_headline_provider` | Provider factory | provider type/config | provider instance | configuration-to-provider dispatch | ingestion service |

## 8. research

### [research/signal_evaluation/dataset.py](/Users/pramitdutta/Desktop/options_quant_engine/research/signal_evaluation/dataset.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `load_signals_dataset` | Load canonical signal dataset | optional dataset path | dataframe | CSV load followed by schema normalization | evaluator, reports, tuning |
| `write_signals_dataset` | Persist canonical dataset | dataframe, path | file path | schema-preserving CSV write | evaluator, maintenance scripts |
| `ensure_signals_dataset_exists` | Create empty dataset if needed | optional path | file path | create canonical empty frame on disk | runner, scripts |
| `upsert_signal_rows` | Insert/update signal rows by `signal_id` | row dict(s), path | updated dataframe | dedupe on stable key and preserve schema ordering | `save_signal_evaluation`, scripts |

### [research/signal_evaluation/evaluator.py](/Users/pramitdutta/Desktop/options_quant_engine/research/signal_evaluation/evaluator.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_signal_id` | Build stable signal identifier | trade/result fields | signal ID string | deterministic concatenation/hash-like stable key construction | dataset upsert |
| `build_regime_fingerprint` | Create compact regime signature for research grouping | trade dict, optional provider health | `(fingerprint_id, fingerprint_string)` | concatenate salient regime fields into research grouping key | research rows, reports |
| `build_signal_evaluation_row` | Convert runtime payload into canonical dataset row | result payload, optional notes | row dict | field extraction from trade/result payload into canonical schema | `save_signal_evaluation` |
| `compute_signal_evaluation_scores` | Convert realized outcome fields into research scores | row dict | score dict | weighted multi-metric scoring over direction, magnitude, timing, tradeability | `evaluate_signal_outcomes`, reports, tuning |
| `evaluate_signal_outcomes` | Enrich row with realized path outcomes | row dict, realized spot path, optional `as_of` | updated row dict | horizon return computation, MFE/MAE windows, session/next-day outcome extraction, score recomputation | dataset update |
| `fetch_realized_spot_path` | Download realized post-signal spot path | `symbol`, `signal_timestamp`, optional `as_of`, `interval` | dataframe | Yahoo history retrieval and timestamp normalization | outcome evaluation |
| `save_signal_evaluation` | Build and upsert row from runtime result | result payload | dataframe / persisted row | row build + dataset upsert | runner |
| `update_signal_dataset_outcomes` | Refresh existing rows with realized outcomes | dataset path and optional filters | updated dataframe | iterate unresolved rows, fetch paths, compute outcomes, upsert | maintenance script |

### [research/signal_evaluation/policy.py](/Users/pramitdutta/Desktop/options_quant_engine/research/signal_evaluation/policy.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `normalize_capture_policy` | Normalize capture-policy string | policy string | canonical policy | string normalization and enum-like validation | runner |
| `should_capture_signal` | Decide whether to persist signal | trade dict, policy | boolean | policy rules over trade status/actionability | runner |

### [research/signal_evaluation/reports.py](/Users/pramitdutta/Desktop/options_quant_engine/research/signal_evaluation/reports.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `hit_rate_by_trade_strength` | Compute grouped hit-rate report | dataset frame | dataframe | group-by bucket plus mean of hit flag | dashboards, research analysis |
| `hit_rate_by_macro_regime` | Compute macro-regime hit rates | dataset frame | dataframe | group-by regime plus hit-rate mean | dashboards |
| `average_score_by_signal_quality` | Summarize quality buckets | dataset frame | dataframe | grouped means over scoring columns | dashboards |
| `average_realized_return_by_horizon` | Summarize returns across horizons | dataset frame | dataframe | horizon-wise numeric mean | research analysis |
| `signal_count_by_regime` | Count signals by regime fields | dataset frame | dataframe | group-by counts | research analysis |
| `regime_fingerprint_performance` | Evaluate performance by regime fingerprint | dataset frame, `top_n` | dataframe | grouped counts and average performance metrics | research analysis |
| `move_probability_calibration` | Compare move-probability buckets to hit rate | dataset frame | dataframe | grouped average predicted probability vs realized hit rate | calibration review |
| `build_research_report` | Build bundled report set | dataset frame | dict of dataframes | package multiple grouped summaries | scripts, UI |

## 9. tuning

### [tuning/registry.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/registry.py)

| Function / class surface | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `ParameterRegistry` | Metadata-rich parameter registry | parameter definitions | registry object | key-indexed metadata store | runtime, experiments, campaigns |
| `build_default_parameter_registry` | Build canonical registry from policy/config surfaces | none | `ParameterRegistry` | harvest config dataclasses/mappings into unified metadata model | `get_parameter_registry` |
| `get_parameter_registry` | Singleton-style registry accessor | none | registry object | cached access to default registry | runtime, search, campaigns |

### [tuning/packs.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/packs.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `list_parameter_packs` | Enumerate available pack files | packs dir | pack name list | filesystem glob over JSON pack files | UI, campaigns, ops |
| `load_parameter_pack` | Load one pack from disk | pack name | `ParameterPack` | JSON-to-dataclass coercion | runtime, experiments |
| `resolve_parameter_pack` | Resolve pack inheritance | pack name | merged `ParameterPack` | recursive parent resolution with override merge | runtime, experiments |

### [config/policy_resolver.py](/Users/pramitdutta/Desktop/Trading%20Engines/options_quant_engine/config/policy_resolver.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `get_active_parameter_pack` | Read active pack name and merged overrides | none | active pack dict | contextvar-backed runtime pack state with default-pack fallback | config getters, runner, tuning compatibility |
| `set_active_parameter_pack` | Activate pack and optional override set | pack name, overrides | active pack dict | resolve inherited pack, merge explicit overrides, update runtime context | CLI/tests/ops |
| `temporary_parameter_pack` | Context manager for temporary pack activation | pack name, overrides | context-managed active pack | save/restore runtime state around temporary override context | experiments, shadow runs |
| `get_parameter_value` | Resolve one parameter value without importing the registry | parameter key, explicit default | concrete value | active overrides take precedence; caller-supplied default is the production fallback | config getters |
| `resolve_mapping` | Resolve dict-like config block against active pack | prefix, default mapping | resolved mapping | prefix-based override extraction from flattened pack keys | config policy getters |
| `resolve_dataclass_config` | Resolve dataclass config against active pack | prefix, dataclass instance | resolved dataclass | dataclass-to-dict resolution then reconstruction | config and macro policy getters |

### [tuning/runtime.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/runtime.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `get_active_parameter_pack` | Read active pack name and overrides | none | active pack dict | environment/default fallback plus cached overrides | runner, diagnostics |
| `set_active_parameter_pack` | Activate pack and optional override set | pack name, overrides | active pack dict | resolve pack, merge explicit overrides, update runtime globals | CLI/tests/ops |
| `temporary_parameter_pack` | Context manager for temporary pack activation | pack name, overrides | context-managed active pack | save/restore runtime state around temporary override context | experiments, shadow runs |
| `get_parameter_value` | Resolve one parameter value with registry-aware fallback for tuning workflows | parameter key, optional default | concrete value | active override first, otherwise explicit default or registry default | tuning diagnostics, compatibility code |
| `resolve_mapping` | Compatibility re-export of mapping resolution | prefix, default mapping | resolved mapping | delegates to `config/policy_resolver.py` | tuning-facing callers |
| `resolve_dataclass_config` | Compatibility re-export of dataclass resolution | prefix, dataclass instance | resolved dataclass | delegates to `config/policy_resolver.py` | tuning-facing callers |
| `serialize_current_registry` | Serialize registry with active values | none | serializable dict | merge current overrides into registry serialization | diagnostics, docs |

### [tuning/objectives.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/objectives.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `time_train_validation_split` | Build deterministic train/validation split | dataset frame, `validation_fraction` | `SplitFrames` | chronological split by signal timestamp | objective computation |
| `apply_selection_policy` | Filter dataset rows by research thresholds | dataset frame, thresholds | selected dataframe | threshold filters on trade strength, composite score, tradeability, move probability, risk cap, overnight flag | objective, validation |
| `compute_frame_metrics` | Compute per-frame research metrics | selected frame, total sample count | metric dict | grouped means and counts for hit rate, scores, returns, drawdown proxy, regime stability | objective, validation |
| `compute_objective_score` | Combine metrics and penalties into objective | metric components, optional weights | scalar score | weighted linear combination with penalties | experiments |
| `compute_objective` | Full objective computation with safeguards | dataset frame, thresholds, weights, parameter count | `ObjectiveResult` | train/validation split, threshold selection, metric computation, selectivity/stability/parsimony/validation-gap penalties | experiments |

### [tuning/walk_forward.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/walk_forward.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_walk_forward_splits` | Build anchored or rolling OOS splits | dataset frame, split config | list of `WalkForwardSplit` | deterministic timestamp-ordered rolling or anchored window construction | validation |
| `apply_walk_forward_split` | Materialize train/validation frames for one split | dataset frame, split object | split frames | timestamp slicing by split boundaries | validation |

### [tuning/regimes.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/regimes.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `label_validation_regimes` | Add regime-bucket columns to research rows | dataset frame | labeled dataframe | deterministic bucketing from logged fields such as vol regime, gamma regime, event risk, overnight flag, squeeze risk | validation |

### [tuning/validation.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/validation.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `summarize_metrics_by_regime` | Compute metrics by regime bucket | labeled dataset, thresholds, objective weights | regime summary dict | group-by regime with repeated metric/objective computation | validation reports, comparison |
| `compute_robustness_metrics` | Quantify split/regime stability and collapse risk | split results, regime summaries | robustness dict | dispersion, collapse, insufficient-sample, and signal-frequency penalties summarized into robustness score | validation, promotion |
| `run_walk_forward_validation` | Run full walk-forward and regime-aware validation | dataset frame, thresholds, objective weights, split config | validation result dict | iterate splits, compute OOS metrics and regime summaries, aggregate robustness | experiments, promotion |
| `compare_validation_results` | Compare baseline vs candidate validation outputs | baseline validation, candidate validation, pack names | comparison summary | aggregate deltas plus regime-wise differences | experiments, promotion |

### [tuning/experiments.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/experiments.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `append_experiment_result` | Append experiment JSONL ledger row | `ExperimentResult`, path | file path | JSONL persistence | ops/reporting |
| `run_parameter_experiment` | Run one pack against dataset and optional validation | pack name, dataset path, overrides, thresholds, weights, walk-forward config | `ExperimentResult` | activate pack, compute objective, optionally run walk-forward validation and baseline comparison, persist result | search, campaigns, promotion review |

### [tuning/search.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/search.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `run_grid_search` | Exhaustive search across small explicit grid | pack name, parameter grid, evaluation settings | experiment result list | Cartesian product over provided grid values | research campaigns |
| `run_random_search` | Random search within parameter bounds | pack name, parameter keys, iterations, seed | experiment result list | bounded random sampling with reproducible RNG seed | research campaigns |
| `run_latin_hypercube_search` | Space-filling search for medium parameter sets | pack name, parameter keys, iterations, seed, base overrides | experiment result list | Latin hypercube sampling across eligible parameter bounds | campaigns |
| `run_coordinate_descent_search` | Local refinement around incumbent solution | pack name, parameter keys, initial overrides, passes | experiment result list | neighbor search around current incumbent parameter values | campaigns |

### [tuning/campaigns.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/campaigns.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `_group_parameter_keys` | Enumerate tunable keys in one group | group, live-safe flag | ordered key list | filter registry by group and live-safety, sort by tuning priority | plan construction |
| `default_group_tuning_plans` | Build default campaign plans from registry | live-safe flag | list of `TuningGroupPlan` | infer per-group search strategy and validation mode from registry metadata | campaign runner |
| `run_group_tuning_campaign` | Execute conservative group-by-group tuning campaign | pack name, dataset path, groups, validation settings | campaign result dict | per-group Latin hypercube search + coordinate descent refinement + robustness-aware ranking | tuning research workflow |

### [tuning/promotion.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/promotion.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `load_promotion_state` | Read or initialize promotion state | optional path | state dict | JSON load with normalization/default initialization | runtime context, ops |
| `write_promotion_state` | Persist promotion state | state dict, path | file path | normalized JSON persistence | ops |
| `append_promotion_event` | Append promotion ledger event | event payload, path | file path | JSONL persistence | reporting |
| `get_active_live_pack` | Read current live pack | optional path | pack name | state lookup | runner |
| `get_active_shadow_pack` | Read current shadow pack | optional path | pack name or `None` | state lookup | runner |
| `get_promotion_runtime_context` | Export state needed by live runner | optional path | context dict | state extraction and shallow normalization | `app/engine_runner.py` |
| `update_pack_state` | Change one named state assignment | state name, pack name, metadata | updated state | explicit state transition with ledger event | ops, promotion workflow |
| `record_manual_approval` | Persist human approval record | pack name, approval flags, reviewer | updated state | approval record write plus ledger event | promotion workflow |
| `evaluate_promotion` | Compare baseline vs candidate against criteria | baseline result, candidate result, thresholds, optional approval | `PromotionDecision` | threshold-based governance test on sample count, score improvement, OOS improvement, robustness, drawdown proxy, regime collapse, manual approval | human governance |
| `promote_candidate` | Move candidate into live and update state/ledger | candidate pack, baseline pack, metadata | state file path | explicit live assignment update with previous-live preservation | live rollout workflow |
| `move_candidate_to_shadow` | Assign candidate to shadow state | pack name, metadata | updated state | explicit shadow-state transition | shadow-mode rollout |
| `rollback_live_pack` | Revert live assignment to prior/baseline pack | optional pack name, reviewer, reason | updated state | explicit rollback transition with ledger event | operational rollback |

### [tuning/shadow.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/shadow.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_shadow_signal_summary` | Extract comparable summary from one trade payload | result payload, pack name, role | summary dict | field selection from trade payload for side-by-side comparison | shadow comparison |
| `compare_shadow_trade_outputs` | Produce baseline-vs-shadow comparison record | baseline payload, shadow payload, pack names | comparison dict | compute deltas and disagreement flags across shared trade fields | runner, shadow log |
| `append_shadow_log` | Persist shadow comparison | record, path | file path | JSONL persistence | ops/reporting |
| `load_shadow_log` | Read shadow log | path | dataframe | JSONL load | reporting |
| `summarize_shadow_log` | Summarize disagreement history | path | summary dict | counts, mean disagreement rates, average trade-strength delta | reporting |

### [tuning/reporting.py](/Users/pramitdutta/Desktop/options_quant_engine/tuning/reporting.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `load_experiment_ledger` | Load experiment ledger | path | dataframe | JSONL load | research dashboards |
| `load_promotion_ledger` | Load promotion ledger | path | dataframe | JSONL load | research dashboards |
| `summarize_experiments` | Summarize top packs and validation rows | path, `top_n` | summary dict | sort/group experiments by objective and validation metadata | docs, dashboards |
| `summarize_promotion_workflow` | Summarize current rollout state and shadow stats | state/log paths | summary dict | combine promotion state, recent events, shadow disagreement summary | ops |

## 10. backtest

### [backtest/intraday_backtester.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/intraday_backtester.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `run_intraday_backtest` | Sequentially replay historical snapshots through the live engine | `symbol`, `years`, persistence/hold/target/stop settings | backtest result dict incl. trade log | chronological replay, signal persistence gate, target/stop/max-hold exit policy, performance aggregation | `backtest_runner.py`, parameter sweep |
| `intraday_backtester` | Thin wrapper around `run_intraday_backtest` | `symbol`, `years` | backtest result | wrapper alias | legacy callers |

### [backtest/pnl_engine.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/pnl_engine.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `calculate_trade_pnl` | Approximate realized option PnL from later snapshot | trade dict, exit snapshot | pnl result dict | locate contract in later snapshot, apply slippage/spread adjustments, target/stop/time-exit logic, `PnL = (exit-entry)*lot_size*lots - charges` | backtester |
| `pnl_engine` | Thin wrapper | trade dict, exit snapshot | pnl result | wrapper alias | legacy callers |

### [backtest/performance_metrics.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/performance_metrics.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `compute_performance_metrics` | Aggregate trade log into performance summary | trade log, starting capital | metrics dict | trade-level PnL aggregation, win/loss decomposition, equity curve, max drawdown, Sharpe-like ratio, expectancy | backtester, CLI |
| `performance_metrics` | Thin wrapper | trade log, starting capital | metrics dict | wrapper alias | legacy callers |

### [backtest/monte_carlo.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/monte_carlo.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `monte_carlo_reshuffle` | Shuffle trade PnL sequence for path-dependence robustness | trade log, simulations | summary dict | repeated random permutation of realized trade PnLs and total-PnL summary | backtest runner |

### [backtest/backtest_runner.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/backtest_runner.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `run_backtest` | CLI harness for single backtest or sweep | interactive inputs | printed output / returned summary | input-driven selection of single backtest vs sweep mode | standalone backtest workflow |

### [backtest/parameter_sweep.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/parameter_sweep.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `build_parameter_grid` | Generate classic backtest sweep grid | config values | parameter combinations | Cartesian grid generation over backtest parameters | `backtest_runner.py` |
| `summarize_sweep_results` | Rank sweep outputs | backtest result list | ranked summary | sort/rank by backtest metrics | `backtest_runner.py` |

### [backtest/replay_regression.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/replay_regression.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `run_regression` | Replay stored snapshots through engine and summarize directional buckets | `symbol`, `source`, `replay_dir`, optional `limit` | result list + counters | align nearest spot and chain snapshots, rerun engine, bucket resulting trade status/direction | CLI regression harness |
| `main` | CLI entrypoint | command-line args | printed summary | wrapper around replay-regression runner | standalone regression workflow |

### Scenario runners

| File path | Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|---|
| [backtest/global_risk_scenario_runner.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/global_risk_scenario_runner.py) | `run_scenario` | Execute named global-risk scenario | scenario dict | scenario result | deterministic fixture -> feature build -> regime classification | tests, R&D validation |
| [backtest/macro_news_scenario_runner.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/macro_news_scenario_runner.py) | `run_scenario` | Execute macro-news scenario | scenario dict | scenario result | deterministic fixture -> headline/event aggregation | tests |
| [backtest/gamma_vol_acceleration_scenario_runner.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/gamma_vol_acceleration_scenario_runner.py) | `run_gamma_vol_scenario` | Execute gamma-vol scenario | scenario name/path | scenario result | deterministic fixture -> acceleration feature/regime pipeline | tests |
| [backtest/dealer_hedging_pressure_scenario_runner.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/dealer_hedging_pressure_scenario_runner.py) | `run_dealer_pressure_scenario` | Execute dealer-pressure scenario | scenario name/path | scenario result | deterministic fixture -> dealer-pressure feature/regime pipeline | tests |
| [backtest/option_efficiency_scenario_runner.py](/Users/pramitdutta/Desktop/options_quant_engine/backtest/option_efficiency_scenario_runner.py) | `run_option_efficiency_scenario` | Execute option-efficiency scenario | scenario name/path | scenario result | deterministic fixture -> expected-move / efficiency pipeline | tests |

## 11. app / interface / orchestration

### [app/engine_runner.py](/Users/pramitdutta/Desktop/options_quant_engine/app/engine_runner.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `_set_runtime_credentials` | Map runtime credentials to environment variables | `source`, credential dict | side effects on env | source-specific env-name mapping | live data providers |
| `_jsonable_headline_state` | Convert headline state dataclass to JSONable dict | headline state | serializable dict | dataclass-like field extraction | result payload, Streamlit |
| `_trade_view_rows` | Build trader-view dataframe | trade dict | dataframe | select trader-facing fields into tabular display format | Streamlit/CLI |
| `_prepare_option_chain_frame` | Numeric-clean display frame | option chain dataframe | dataframe | numeric coercion on display-relevant columns | Streamlit |
| `_evaluate_snapshot_for_pack` | Evaluate one snapshot under one parameter pack | pack name + shared market snapshot state | dict with pack name, macro/global state, trade | temporary pack activation, macro/global state build, then authoritative engine call | authoritative and shadow execution |
| `run_preloaded_engine_snapshot` | Shared execution path once spot and option-chain inputs are already loaded | runtime settings, spot snapshot, option chain, optional precomputed context | full result payload | build shared snapshot context, evaluate authoritative pack, split execution vs audit views, optionally run shadow trade and capture results | backtest, replay, CLI, Streamlit |
| `run_engine_snapshot` | Shared live/replay loader wrapper around the preloaded execution path | runtime settings, data source, budget, replay paths, pack names | full result payload | branch live vs replay for data loading, persist snapshots when needed, then delegate to `run_preloaded_engine_snapshot(...)` | CLI, Streamlit, research capture, shadow mode |

### [app/streamlit_app.py](/Users/pramitdutta/Desktop/options_quant_engine/app/streamlit_app.py)

This file is render-helper heavy. The major functions are presentation-oriented rather than computational:

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `_render_workstation` | Main live workstation renderer | result payload | Streamlit UI side effects | render result payload into panels/tables/charts | interactive app |
| `_render_signal_research_dashboard` | Render research tables/metrics | dataset/report frames | Streamlit UI side effects | display grouped research outputs | interactive app |
| `_render_option_chain_charts` | Visualize chain structure | option-chain dataframe | Streamlit charts | charting / aggregation for display | interactive app |
| `_render_macro_lab` | Render macro/headline diagnostics | macro state, headline records, event state | Streamlit UI side effects | display-oriented summarization | interactive app |
| `main` | Streamlit entrypoint | widget state/user selections | UI application | widget orchestration plus `run_engine_snapshot(...)` execution | `streamlit run app/streamlit_app.py` |

### [main.py](/Users/pramitdutta/Desktop/options_quant_engine/main.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `parse_runtime_args` | Parse CLI flags | CLI argv | args namespace | argparse-based parsing | CLI entrypoint |
| `choose_data_source` | Interactive source chooser | stdin | source string | prompt and fallback validation | CLI run |
| `choose_underlying_symbol` | Interactive symbol chooser | stdin | symbol string | prompt logic and default fallback | CLI run |
| `choose_budget_mode` | Interactive budget mode chooser | stdin | bool | prompt logic and default fallback | CLI run |
| `prompt_provider_credentials` | Interactive credential prompts | source | env var side effects | prompt + env assignment | CLI live mode |
| `get_budget_inputs` | Interactive budget fields | budget mode | lot/capital tuple | prompt parsing with defaults | CLI live mode |
| `print_trader_view` | CLI rendering of trade fields | trade dict | stdout | display helper | CLI output |
| `print_validation_block` | CLI rendering of validation dict | title, validation dict | stdout | ordered display helper | CLI output |
| `print_key_value_block` | CLI rendering helper | title, dict | stdout | display helper | CLI output |
| `print_dealer_dashboard` | CLI rendering of analytics summary | summary dict | stdout | formatted field presentation | CLI output |

## 12. config and support

### [config/signal_policy.py](/Users/pramitdutta/Desktop/options_quant_engine/config/signal_policy.py)

| Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|
| `get_direction_vote_weights` | Return active direction-vote weight mapping | none | mapping | runtime resolution of pack-governed config | engine support |
| `get_direction_thresholds` | Return direction decision thresholds | none | mapping | runtime resolution of pack-governed config | engine support |
| `get_trade_strength_weights` | Return trade-strength score weights | none | mapping | runtime resolution of pack-governed config | `strategy/trade_strength.py` |
| `get_consensus_score_config` | Return consensus scoring config | none | mapping | runtime resolution of pack-governed config | `strategy/trade_strength.py` |
| `get_trade_runtime_thresholds` | Return final runtime status thresholds | none | mapping | runtime resolution of pack-governed config | `generate_trade` |
| `get_confirmation_filter_config` | Return confirmation thresholds | none | dataclass/mapping | runtime resolution of pack-governed config | `strategy/confirmation_filters.py` |

### Other config getter surfaces

| File path | Function | Purpose | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|
| [config/global_risk_policy.py](/Users/pramitdutta/Desktop/options_quant_engine/config/global_risk_policy.py) | `get_global_risk_policy_config` | active global-risk policy dataclass | runtime resolution of pack-governed config | global-risk feature/regime logic |
| [config/gamma_vol_acceleration_policy.py](/Users/pramitdutta/Desktop/options_quant_engine/config/gamma_vol_acceleration_policy.py) | `get_gamma_vol_acceleration_policy_config` | active acceleration policy | runtime resolution of pack-governed config | acceleration features/regime |
| [config/dealer_hedging_pressure_policy.py](/Users/pramitdutta/Desktop/options_quant_engine/config/dealer_hedging_pressure_policy.py) | `get_dealer_hedging_pressure_policy_config` | active dealer-pressure policy | runtime resolution of pack-governed config | dealer-pressure features/regime |
| [config/option_efficiency_policy.py](/Users/pramitdutta/Desktop/options_quant_engine/config/option_efficiency_policy.py) | `get_option_efficiency_policy_config` | active option-efficiency policy | runtime resolution of pack-governed config | option-efficiency layer |
| [config/strike_selection_policy.py](/Users/pramitdutta/Desktop/options_quant_engine/config/strike_selection_policy.py) | `get_strike_selection_score_config` | active strike-scoring config | runtime resolution of pack-governed config | strike selector |
| [config/large_move_policy.py](/Users/pramitdutta/Desktop/options_quant_engine/config/large_move_policy.py) | `get_large_move_probability_config` | active move-probability config | runtime resolution of pack-governed config | large-move model |
| [config/event_window_policy.py](/Users/pramitdutta/Desktop/options_quant_engine/config/event_window_policy.py) | `get_event_window_policy_config` | active event-window policy | runtime resolution of pack-governed config | scheduled-event logic |
| [config/news_category_policy.py](/Users/pramitdutta/Desktop/options_quant_engine/config/news_category_policy.py) | category multiplier getters | active headline-category multipliers | runtime resolution of pack-governed config | headline classifier |
| [config/signal_evaluation_scoring.py](/Users/pramitdutta/Desktop/options_quant_engine/config/signal_evaluation_scoring.py) | scoring getter functions | research scoring/selection config | runtime resolution of pack-governed config | evaluator, tuning objective |
| [config/symbol_microstructure.py](/Users/pramitdutta/Desktop/options_quant_engine/config/symbol_microstructure.py) | `get_microstructure_config` | symbol-specific microstructure assumptions | symbol-to-config mapping | engine support / strike logic |

### Support / maintenance scripts

| File path | Function | Purpose | Key inputs | Key outputs | Math / Logic basis | Downstream dependencies |
|---|---|---|---|---|---|---|
| [smoke_macro_news.py](/Users/pramitdutta/Desktop/options_quant_engine/smoke_macro_news.py) | `main` | Smoke test macro/headline stack | symbol, timestamp | printed diagnostic output | run event-state + headline fetch + macro aggregation and print results | manual validation |
| [scripts/signal_evaluation_report.py](/Users/pramitdutta/Desktop/options_quant_engine/scripts/signal_evaluation_report.py) | script entrypoint | Generate research report from dataset | dataset path/options | printed or saved report | load dataset and call research report builders | research workflow |
| [scripts/update_signal_outcomes.py](/Users/pramitdutta/Desktop/options_quant_engine/scripts/update_signal_outcomes.py) | script entrypoint | Refresh realized outcomes in dataset | dataset/options | updated dataset | iterate saved signals and run outcome evaluation | maintenance workflow |

## Notes on omissions

1. Common numeric helpers (`_safe_float`, `_clip`, `_to_numeric`, timestamp coercers) are now centralized in the `utils/` package and imported by all modules that need them. They are omitted from individual module entries to avoid repetition.
2. Provider-adapter class internals are not exploded method-by-method here because the present codebase exposes them primarily through router classes rather than a broad top-level function API.
3. Render-helper functions in `app/streamlit_app.py` are represented selectively. The file contains many UI formatting helpers, but the major computationally meaningful entrypoint remains `main`, with rendering clustered around the result payload produced by `run_engine_snapshot(...)`.

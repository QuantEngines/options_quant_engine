---
title: "Options Quant Engine"
subtitle: "Quantitative Microstructure, Convexity, and Signal Research"
author: "Pramit Dutta"
date: "March 2026"
---

<div class="memo-cover">
<div class="cover-kicker">Academic Research Paper</div>
<h1 class="cover-title">Options Quant Engine</h1>
<div class="cover-subtitle">Quantitative Microstructure, Convexity, and Signal Research</div>
<div class="cover-rule"></div>
<p class="cover-summary">A formal research paper describing the theoretical basis, empirical orientation, inference architecture, and operational realization of a systematic options-market framework grounded in microstructure, convexity, dealer hedging feedback, liquidity topology, and regime-aware signal evaluation.</p>
<div class="cover-meta">
<div><span>Author</span>Pramit Dutta</div>
<div><span>Organization</span>Quant Engines</div>
<div><span>Date</span>March 2026</div>
<div><span>Document</span>Academic Paper</div>
<div><span>Focus</span>Options microstructure, convexity, and systematic signal research</div>
</div>
</div>

## Abstract

This paper presents the conceptual design, quantitative motivation, and
research architecture of the Options Quant Engine, a systematic framework for
the analysis of listed options markets. The central premise is that options
markets cannot be modeled adequately as simple leveraged expressions of
directional views in the underlying asset. Their dynamics are shaped by the
interaction of nonlinear payoff structure, volatility repricing, strike-level
inventory concentration, dealer hedging activity, liquidity discontinuities,
and macroeconomic regime variation.

The proposed framework addresses this problem by constructing a layered
market-state representation from option-chain microstructure, Greek-based
sensitivity estimates, liquidity topology, volatility structure, and exogenous
macro and cross-asset risk signals. Rather than relying on a single predictive
model, the system aggregates a set of interpretable inferential layers, each of
which captures a distinct structural mechanism believed to influence option
payoff quality and short-horizon market dynamics.

The methodological orientation of the framework is signal-evaluation-first.
Signals are recorded in a canonical research dataset and evaluated against
subsequent realized market behavior over multiple horizons. This design
separates market-state inference from trade execution, and thereby supports
disciplined parameter governance, walk-forward validation, regime-aware
evaluation, and controlled promotion of candidate model configurations.

The contribution of the framework is therefore not a claim of perfect
forecasting, nor the construction of a complete structural model of dealer
inventory, but the development of an operationally tractable, interpretable,
and research-governed architecture for studying options markets as convexity and
microstructure systems.


## 1. Research Motivation and Problem Statement

Systematic trading in options markets presents a research problem that differs
materially from the corresponding problem in linear instruments such as cash
equities or futures. In a linear asset, profit and loss is approximately
proportional to the movement of the underlying:

$$
\Delta \Pi \approx q \, \Delta S
$$

where $q$ denotes position size and $\Delta S$ denotes the change in the
underlying price. Under this structure, a sufficiently accurate forecast of
direction and magnitude is often enough to produce a profitable trade, subject
to implementation frictions.

In listed options, this simplification fails. Option value is a function not
only of the level of the underlying asset but also of time to expiration,
implied volatility, carry variables, strike location, and the distribution of
future paths:

$$
V = V(S, K, T, \sigma, r, q)
$$

where $S$ denotes spot price, $K$ strike, $T$ time to expiry, $\sigma$
volatility, $r$ the risk-free rate, and $q$ dividend yield or carry
adjustment. Consequently, an accurate directional view may still produce an
economically poor option trade if the move occurs too slowly, if implied
volatility compresses, if the option premium is inefficient relative to the
expected move, or if the strike is selected poorly.

The research problem is therefore not merely directional forecasting. It is the
construction of a framework capable of estimating when convexity is likely to
become valuable. This requires modeling market mechanisms that are often absent
from conventional technical trading frameworks:

- dealer gamma exposure and regime transitions
- dealer hedge demand and reinforcement or dampening feedback loops
- strike-level concentration of open interest and liquidity
- liquidity vacuums and structural discontinuities between defended regions
- volatility compression and expansion dynamics
- macroeconomic and cross-asset states that condition local market behavior

The present system is motivated by the proposition that these structural
features may carry predictive information about subsequent short-horizon market
behavior, especially in options markets where price formation is affected by
both speculative demand and hedging-related inventory management.

This problem is especially relevant in Indian index options markets, where:

- weekly expiries create concentrated strike-level risk transfer
- gamma sensitivity can become large near expiry
- open-interest clustering frequently produces local structure
- macro and global risk transmission can strongly influence overnight gap risk

The system therefore seeks to model option markets not merely as directional
prediction problems, but as nonlinear microstructure environments in which the
interaction between convexity, liquidity, and hedging may alter both the path
and magnitude of price movement.


## 2. Research Questions and Hypotheses

The present framework is organized around a set of research questions that can
be studied empirically through signal evaluation and regime-conditioned
analysis.

### 2.1 Research Questions

1. Under what market conditions do option-chain-derived structural variables
   contain predictive information about subsequent market movement?
2. Does inferred dealer gamma regime affect realized short-horizon volatility?
3. Do liquidity vacuums increase the probability of accelerated directional
   movement relative to dense strike clusters?
4. Does inferred dealer hedging pressure contain information about short-horizon
   directional continuation?
5. Does the joint presence of short-gamma exposure, volatility compression, and
   macro stress increase the likelihood of convex price expansion?
6. Do cross-asset risk indicators improve the conditioning of overnight-hold
   decisions in local index options?
7. Can an interpretable, signal-evaluation-first framework produce a more
   robust research program than an opaque forecasting architecture optimized
   directly on realized trade profit and loss?

### 2.2 Hypotheses

- **H1:** Short-gamma regimes are associated with higher realized volatility
  than long-gamma regimes over short evaluation horizons.
- **H2:** Liquidity vacuums are associated with greater breakout probability
  than dense strike clusters.
- **H3:** Dealer hedging pressure proxies are associated with directional
  continuation in the direction of hedging reinforcement.
- **H4:** Convexity expansion risk increases when short-gamma structure,
  volatility compression, and macro stress are jointly present.
- **H5:** Cross-asset global-risk conditioning improves the quality of
  overnight signal filtering relative to local-only inference.
- **H6:** Option-efficiency filters improve the economic quality of option
  buying signals by rejecting trades whose expected move support is weak
  relative to premium and strike geometry.

These hypotheses are not treated as axioms. Rather, they constitute the
organizing empirical questions of the system. The architecture is designed so
that these propositions can be evaluated in a disciplined manner through the
canonical signal dataset and subsequent validation pipeline.


## 3. Methodological Orientation

The methodology is best understood as a structured market-state inference
framework rather than a pure forecasting model.

### 3.1 Interpretability and hybrid design

The present framework is deliberately hybrid:

- it borrows theoretical language from derivative pricing and market
  microstructure
- it uses heuristic approximations where direct structural observation is not
  available
- it operationalizes these approximations in an interpretable signal engine
- it evaluates outputs through a canonical empirical dataset

This places the methodology between formal quantitative market microstructure
modeling and systematic signal engineering. The aim is not to derive a fully
closed structural equilibrium model of dealer inventory, nor to delegate
inference entirely to a black-box learner. Instead, the system attempts to
preserve explanatory structure while remaining operationally tractable.

### 3.2 Distinguishing theory, approximation, implementation, and evaluation

The paper maintains a five-part distinction throughout:

1. **Theoretical concept**  
   The financial or mathematical principle motivating a variable or layer.

2. **Market interpretation**  
   The trading or microstructure intuition associated with that concept.

3. **Operational approximation**  
   The proxy, heuristic, or bounded statistic used when direct observation is
   unavailable.

4. **Implementation in the present system**  
   The computational realization within the codebase.

5. **Limitations and caveats**  
   The conditions under which the approximation may fail or become unstable.

This distinction is essential because the system contains both principled
mathematical content and heuristic structural approximations. Conflating these
would create false claims of precision.

### 3.3 Signal-evaluation-first architecture

An important methodological commitment of the framework is that research
calibration is based on signal evaluation rather than on discretionary or
execution-contaminated trade records. The learning loop is:

$$
\text{Market Data}
\rightarrow
\text{Signal Generation}
\rightarrow
\text{Canonical Signal Dataset}
\rightarrow
\text{Validation and Tuning}
\rightarrow
\text{Promotion Governance}
$$

This architecture has several methodological advantages:

- it separates market intelligence from fill quality and execution noise
- it makes evaluation horizons explicit
- it allows regime-aware analysis of the same signal family
- it supports controlled tuning through parameter packs and walk-forward
  validation

### 3.4 Scope of the framework

The framework should not be interpreted as:

- a complete option pricing engine
- a complete structural model of dealer books
- an execution management or broker-routing platform
- an online self-learning system

It is better understood as an empirical inference architecture for the study of
options microstructure and convexity-sensitive signal generation.


## 4. Foundational Concepts in Options and Nonlinear Payoff Structure

### 4.1 Theoretical foundation

An option is a contingent claim that grants the right, but not the obligation,
to transact the underlying asset at strike $K$ on or before expiration. For a
European call and put, expiration payoffs are:

$$
\Pi_{call}(S_T) = \max(S_T - K, 0)
$$

$$
\Pi_{put}(S_T) = \max(K - S_T, 0)
$$

If one includes the premium paid at initiation, long-option profit is:

$$
\Pi^{net}_{call}(S_T) = \max(S_T - K, 0) - C_0
$$

$$
\Pi^{net}_{put}(S_T) = \max(K - S_T, 0) - P_0
$$

These payoffs are convex, in contrast to the linear payoff of the underlying.

### 4.2 Market interpretation

The relevance of these formulas is not merely pedagogical. Convexity implies
that option profitability depends on:

- whether the move occurs
- whether it occurs quickly enough
- whether it exceeds strike and premium hurdles
- whether volatility reprices favorably or unfavorably

This is the first reason a linear trading framework is insufficient.

### 4.3 Operational approximation

For research purposes, it is useful to distinguish:

$$
\text{Option Premium} = \text{Intrinsic Value} + \text{Time Value}
$$

where intrinsic value is immediate exercise value and time value is the market's
valuation of remaining optionality. In live trading, most short-horizon option
buying involves significant time value. Thus a correct directional view may
still fail economically if time value decays faster than underlying movement
accumulates.

### 4.4 Computational realization

The present framework operationalizes this distinction not by continuously
decomposing every live trade into full arbitrage components, but through:

- strike selection logic in `strategy/strike_selector.py`
- target and stop construction in `strategy/exit_model.py`
- option-efficiency estimation in `risk/option_efficiency_features.py` and
  `risk/option_efficiency_layer.py`

### 4.5 Caveats

Elementary payoff theory alone is insufficient for live options inference. It
does not determine:

- fair premium
- path sensitivity before expiry
- volatility dependence
- hedge feedback
- liquidity discontinuities

These additional dimensions motivate the sections that follow.


## 5. Option Pricing and Sensitivity Framework

### 5.1 Theoretical foundation

Under arbitrage-free pricing, an option may be represented as the discounted
expected payoff under a risk-neutral measure:

$$
V_0 = e^{-rT}\mathbb{E}^{\mathbb{Q}}[\text{Payoff}]
$$

Within the Black-Scholes framework:

$$
C = S e^{-qT} N(d_1) - K e^{-rT} N(d_2)
$$

$$
P = K e^{-rT} N(-d_2) - S e^{-qT} N(-d_1)
$$

with

$$
d_1 = \frac{\ln(S/K) + (r - q + \frac{1}{2}\sigma^2)T}{\sigma \sqrt{T}},
\qquad
d_2 = d_1 - \sigma \sqrt{T}
$$

and put-call parity:

$$
C - P = S e^{-qT} - K e^{-rT}.
$$

The option value is thus a state-dependent surface:

$$
V = V(S, K, T, \sigma, r, q).
$$

### 5.2 Market interpretation

These formulas establish a local coordinate system for understanding exposure:

- $S$ controls directional sensitivity
- $T$ controls remaining optionality and time decay
- $\sigma$ governs the value of uncertainty
- $K$ determines moneyness and strike geometry

The terms $d_1$ and $d_2$ may be read informally as standardized measures of
how far the strike is from the center of the relevant risk-neutral
distribution. A large positive $d_1$ indicates that a call is deeply
in-the-money in standardized terms; a large negative $d_1$ implies the option
is far out-of-the-money.

### 5.3 Operational approximation

The present framework does not attempt to use Black-Scholes as a complete model
of market reality. Rather, it uses the framework to obtain disciplined local
sensitivity measures. For small changes:

$$
\Delta V
\approx
\Delta \, \Delta S
\;+\;
\frac{1}{2}\Gamma (\Delta S)^2
\;+\;
\nu \, \Delta \sigma
\;+\;
\Theta \, \Delta t
$$

where $\Delta$, $\Gamma$, $\nu$, and $\Theta$ denote delta, gamma, vega, and
theta respectively.

This local expansion is central because it shows that option PnL is not a
single-channel object. Spot movement, curvature, volatility repricing, and time
decay all matter simultaneously.

### 5.4 Computational realization

The system computes contract-level sensitivities in
`analytics/greeks_engine.py`. These include:

- `DELTA`
- `GAMMA`
- `THETA`
- `VEGA`
- `VANNA`
- `CHARM`

The choice of explicit formula-based sensitivities rather than opaque vendor
Greeks reflects methodological priorities:

- transparency of assumptions
- recomputability across providers
- consistency for research and tuning
- interpretability of downstream structural variables

### 5.5 Caveats

The Black-Scholes framework imposes restrictive assumptions:

- lognormal diffusion
- constant volatility
- continuous hedging
- frictionless trading

Real options markets exhibit smiles, skews, jumps, discrete hedging, and
state-dependent liquidity. The system therefore treats Greek estimates as local
sensitivity approximations rather than complete structural truths.


## 6. Market Microstructure of Listed Options

### 6.1 Theoretical foundation

Listed options markets are organized across strikes and expiries, with each node
in the option chain representing a tradable locus of inventory, liquidity, and
volatility. Key observables include:

- open interest
- traded volume
- implied volatility
- last traded price
- expiry location

### 6.2 Market interpretation

The option chain is not merely a menu of contracts. It is a map of:

- inventory concentration
- locally important strikes
- potential support and resistance
- potential pinning regions
- zones of sparse participation

Large open interest does not reveal participant identity with certainty, but it
does indicate that a strike is structurally important to someone. In aggregate,
such concentrations frequently influence short-horizon price formation.

### 6.3 Operational approximation

The framework uses public and broker-normalized option-chain fields as proxies
for latent market structure. It infers:

- strike clustering from open-interest concentrations
- directional and structural relevance from call-versus-put distributions
- liquidity density from volume and open-interest combinations
- expiry-related sensitivity from time-to-expiry and ATM proximity

### 6.4 Computational realization

These ideas are implemented across the analytics layer, especially:

- `analytics/gamma_walls.py`
- `analytics/liquidity_heatmap.py`
- `analytics/liquidity_void.py`
- `analytics/liquidity_vacuum.py`
- `analytics/market_gamma_map.py`

The proposed architecture separates raw structural inference from the trade
decision layer. This is methodologically useful because it permits
microstructure variables to be studied as standalone explanatory objects.

### 6.5 Caveats

The available chain does not reveal full participant attribution, hidden
liquidity, or complete order-book dynamics. Accordingly, the framework should
be interpreted as a structured public-data inference architecture, not as a
complete reconstruction of the exchange's latent state.


## 7. Dealer Gamma Exposure and Hedging Feedback

### 7.1 Theoretical foundation

Aggregate gamma exposure is a central structural concept because it determines
how hedge sensitivity changes as spot moves. In proxy form:

$$
\text{GEX} \approx \sum_i \Gamma_i \cdot OI_i \cdot \text{sign}_i
$$

where $\Gamma_i$ denotes contract gamma, $OI_i$ open interest, and
$\text{sign}_i$ the chosen convention for directional aggregation.

If the market is effectively long gamma, dealer hedging tends to oppose price
movement. If it is effectively short gamma, hedging tends to reinforce price
movement.

### 7.2 Market interpretation

This gives rise to the widely used intuition:

- long gamma $\Rightarrow$ mean reversion and dampening
- short gamma $\Rightarrow$ momentum reinforcement and acceleration

The gamma flip is the spot level at which net gamma changes sign:

$$
\text{Gamma Flip} = \{S : \text{Net Gamma}(S) = 0\}
$$

Near the flip, small spot changes may alter the sign of hedge feedback, so
market behavior can become unstable even if absolute spot movement is initially
modest.

### 7.3 Operational approximation

Institutional-quality gamma estimation ideally requires granular contract
Greeks, inventory assumptions, contract multipliers, and expiry-aware
aggregation. In many public-data settings, those inputs are incomplete. The
present framework therefore uses a robust approximation:

- true contract gamma where available
- otherwise a distance-from-ATM proxy to preserve regime structure

This choice prioritizes regime identification over false numerical precision.

### 7.4 Computational realization

The present framework operationalizes gamma structure through:

- `analytics/gamma_exposure.py`
- `analytics/gamma_flip.py`
- `analytics/market_gamma_map.py`
- `engine/trading_support/market_state.py`

These outputs enter the wider inference architecture as:

- `gamma_regime`
- `spot_vs_flip`
- `gamma_flip_distance_pct`

### 7.5 Caveats

All dealer-gamma inference based on public chain data is necessarily
model-dependent. The framework cannot directly observe:

- true dealer versus customer side
- OTC offsetting positions
- internal crossing or hedge warehousing
- intra-day inventory transfers

Thus gamma regime should be interpreted as an empirical structural proxy, not
as a direct measure of institutional books.


## 8. Volatility Structure and Convexity Expansion

### 8.1 Theoretical foundation

Volatility is both an input to option value and an empirical property of market
behavior. Two notions are especially important:

- **realized volatility**, measured from actual price variation
- **implied volatility**, extracted from option prices

Expected move over horizon $T$ may be approximated as:

$$
\text{Expected Move} \approx S \sigma_{ATM}\sqrt{T}
$$

This follows from diffusion scaling, where the standard deviation of returns
over horizon $T$ is approximately $\sigma\sqrt{T}$.

### 8.2 Market interpretation

Volatility matters in at least three distinct ways:

1. it changes option premium directly
2. it conditions whether option buying is economically sensible
3. it interacts with dealer hedging and liquidity structure to shape realized
   movement

Particularly important are transitions between:

- suppressed volatility
- normal volatility
- expanding volatility

The framework is especially interested in the empirical circumstance in which
volatility compression coexists with latent structural fragility. In such
regimes, realized movement may remain temporarily subdued while convexity
becomes increasingly valuable.

### 8.3 Operational approximation

The methodology uses tractable proxies rather than a full stochastic-volatility
estimation stack. These include:

- ATM implied volatility
- realized-volatility ratios
- volatility shock measures
- volatility compression scores
- volatility explosion probability

### 8.4 Computational realization

Relevant system components include:

- `analytics/volatility_regime.py`
- `analytics/volatility_surface.py`
- `risk/global_risk_features.py`
- `risk/gamma_vol_acceleration_features.py`
- `risk/option_efficiency_features.py`

The present framework thus treats volatility not as a single background
variable, but as a layered state interacting with convexity and liquidity.

### 8.5 Caveats

Volatility inference in public-data environments is inherently approximate.
ATM IV may be noisy, realized-vol proxies may depend on data granularity, and
volatility surfaces may be only partially observed. These limitations imply
that expected-move estimates should be interpreted as scale parameters rather
than point forecasts.


## 9. Liquidity Topology and Structural Discontinuities

### 9.1 Theoretical foundation

Strike space in listed options markets has topology. Strikes are not uniformly
equivalent. Some represent dense inventory nodes; others lie within sparse
regions where support from inventory or liquidity may be weak.

### 9.2 Market interpretation

Two structural motifs are especially important:

- **walls**: strikes with concentrated open interest or hedging importance
- **vacuums**: sparse regions between defended zones

Dense regions may promote:

- pinning
- local mean reversion
- slower price discovery

Sparse regions may promote:

- rapid traversal
- breakout acceleration
- reduced resistance to directional flow

### 9.3 Operational approximation

The present framework infers liquidity topology using public chain quantities
such as open interest and volume. It does not claim to recover the full latent
limit-order-book geometry. Rather, it identifies structural zones that are
plausibly relevant for short-horizon movement.

### 9.4 Computational realization

These ideas are implemented in:

- `analytics/gamma_walls.py`
- `analytics/liquidity_vacuum.py`
- `analytics/liquidity_void.py`
- `analytics/dealer_liquidity_map.py`

These outputs also feed into:

- strike ranking
- gamma-vol acceleration inference
- dealer hedging pressure estimation

### 9.5 Caveats

Liquidity topology inferred from option chains is only a proxy for true
transaction-cost geometry. Hidden liquidity, participant-specific behavior, and
changing order-book conditions may weaken the correspondence between the
inferred structural map and true executable liquidity.


## 10. Macro and Cross-Asset Risk Conditioning

### 10.1 Theoretical foundation

Options markets are conditioned not only by local microstructure but also by
exogenous information shocks and cross-asset regimes. Scheduled macroeconomic
events, geopolitical developments, global equity stress, currency shifts, and
commodity shocks can alter both directional beliefs and volatility demand.

### 10.2 Market interpretation

These effects are particularly relevant for:

- overnight gap risk
- event-window volatility repricing
- volatility-of-volatility conditions
- cross-market risk transmission into local index options

The key methodological choice is to treat macro and global variables as
conditioning variables rather than as a primary directional engine.

### 10.3 Operational approximation

The framework distinguishes:

- scheduled domestic macro-event risk
- headline-driven macro/news state
- cross-asset global-risk features

Global-risk features include variables such as:

- oil shocks
- gold stress
- copper growth deterioration
- US equity stress
- US yield shocks
- USDINR shocks
- volatility compression and explosion features

### 10.4 Computational realization

These layers are implemented in:

- `macro/scheduled_event_risk.py`
- `news/classifier.py`
- `macro/macro_news_aggregator.py`
- `risk/global_risk_features.py`
- `risk/global_risk_regime.py`
- `risk/global_risk_layer.py`

The methodology relies on interpretability and conservative fallback behavior.
Missing or stale exogenous data causes the system to degrade toward neutral
states rather than inventing directional information.

### 10.5 Caveats

Macro and global-risk mapping is one of the most overfit-prone components of
any options framework. The empirical challenge is not merely feature selection
but the identification of stable cross-asset relationships under changing
regimes. The present framework therefore prefers bounded and interpretable
regime conditioning over opaque exogenous prediction models.


## 11. Signal Construction Framework

### 11.1 Theoretical foundation

The signal layer may be abstracted as a structured evidence-aggregation
framework:

$$
\text{Signal Strength}
=
\sum_{j=1}^{m} w_j x_j
\;+\;
\sum_{k=1}^{n} b_k \mathbf{1}_{A_k}
$$

where $x_j$ denotes normalized evidence components, $w_j$ tunable weights, and
$b_k$ alignment bonuses or conflict penalties associated with structural event
sets $A_k$.

### 11.2 Market interpretation

The purpose of this design is not to claim that price formation is additive in
an economic sense. Rather, it is to operationalize a portfolio of structured
signals:

- flow
- smart-money proxies
- gamma state
- hedging bias
- volatility regime
- liquidity topology
- large-move probability
- overlay-derived modifications

This approach is more interpretable than a single opaque forecast, and it
permits disaggregation of signal failure.

### 11.3 Operational approximation

The system separates:

- **direction proposal**
- **trade strength aggregation**
- **confirmation filtering**
- **overlay adjustments**

This separation is methodologically valuable because it allows a researcher to
distinguish between a weak signal, a strong signal with poor confirmation, and
a strong signal later downgraded by exogenous or convexity-aware overlays.

### 11.4 Computational realization

Core components include:

- `strategy/trade_strength.py`
- `strategy/confirmation_filters.py`
- `models/large_move_probability.py`
- `engine/trading_support/` (market state, probability, signal state, trade modifiers)
- `engine/signal_engine.py`

The proposed architecture keeps primary signal generation separate from
secondary veto or conditioning layers. This is preferable to a monolithic score
from the standpoint of diagnostic clarity.

### 11.5 Caveats

Evidence aggregation remains a heuristic approximation. Even when the weights
are tuned systematically, the additive structure cannot fully capture all
nonlinear interactions among market-state variables. This is a deliberate trade
off favoring interpretability.


## 12. Evaluation Methodology

### 12.1 Theoretical foundation

The empirical value of a signal cannot be reduced to a single win-rate number,
especially in options markets where timing, magnitude, and tradeability matter
simultaneously. The evaluation architecture therefore defines a richer outcome
surface.

### 12.2 Market interpretation

A signal may be useful in different ways:

- directionally correct over 15 minutes
- economically useful over 60 minutes
- supportive of overnight continuation
- high quality in one regime but not another

Accordingly, the methodology evaluates signals across multiple horizons and
multiple score dimensions.

### 12.3 Operational approximation

The canonical research dataset records each signal once and enriches it over
time with realized market outcomes. Composite evaluation may be abstracted as:

$$
\text{Composite Signal Score}
=
w_d D + w_m M + w_t T + w_q Q
$$

where:

- $D$ = direction score
- $M$ = magnitude score
- $T$ = timing score
- $Q$ = tradeability score

The tuning problem is then formulated as a constrained objective:

$$
\max_{\theta \in \Theta} \; \mathcal{J}(\theta)
$$

subject to constraints on sample count, frequency, robustness, and
out-of-sample behavior:

$$
\text{frequency}(\theta) \ge f_{min}, \qquad
\text{robustness}(\theta) \ge r_{min}, \qquad
\text{sample}(\theta) \ge n_{min}
$$

### 12.4 Computational realization

The evaluation and governance stack is implemented in:

- `research/signal_evaluation/dataset.py`
- `research/signal_evaluation/evaluator.py`
- `tuning/objectives.py`
- `tuning/experiments.py`
- `tuning/walk_forward.py`
- `tuning/regimes.py`
- `tuning/validation.py`
- `tuning/promotion.py`
- `tuning/shadow.py`

The methodology is explicitly signal-evaluation-first. Real or discretionary
trades are not used as the primary research calibration source.

### 12.5 Caveats

The evaluation framework still depends on choices of:

- horizon definition
- composite-score weighting
- selection thresholds
- regime labels

These choices introduce model risk at the research layer. The framework
mitigates this through walk-forward validation, regime-aware reporting, and
promotion governance, but it does not eliminate specification risk.


## 13. System Architecture and Implementation

### 13.1 High-level architecture

The present architecture may be summarized as:

```text
data ingestion
    -> normalization and validation
    -> microstructure analytics
    -> core signal inference
    -> convexity and risk overlays
    -> strike and trade construction
    -> canonical signal capture
    -> evaluation, tuning, and promotion governance
```

It is also useful to distinguish two coupled systems:

```text
Inference system:
market data -> analytics -> signal engine -> trade payload

Governance system:
trade payload -> signal dataset -> validation -> tuning -> promotion / shadow review
```

### 13.2 Computational realization by subsystem

#### Analytics layer

The analytics layer provides structural state variables through modules such as:

- `analytics/greeks_engine.py`
- `analytics/gamma_exposure.py`
- `analytics/gamma_flip.py`
- `analytics/gamma_walls.py`
- `analytics/liquidity_vacuum.py`
- `analytics/dealer_hedging_flow.py`
- `analytics/volatility_regime.py`

#### Core inference layer

The core signal engine is operationalized mainly in:

- `engine/trading_support/` (subpackage: market state, probability, signal state, trade modifiers)
- `engine/signal_engine.py`
- `strategy/trade_strength.py`
- `strategy/confirmation_filters.py`
- `strategy/strike_selector.py`

#### Overlay layer

The overlay architecture is implemented through:

- `risk/global_risk_*`
- `risk/gamma_vol_acceleration_*`
- `risk/dealer_hedging_pressure_*`
- `risk/option_efficiency_*`

#### Research and governance layer

The empirical and governance stack is implemented through:

- `research/signal_evaluation/*`
- `tuning/registry.py`
- `tuning/packs.py`
- `tuning/search.py`
- `tuning/campaigns.py`
- `tuning/validation.py`
- `tuning/promotion.py`
- `tuning/shadow.py`

### 13.3 Architectural rationale

The proposed architecture separates:

- structural inference
- directional scoring
- exogenous conditioning
- strike economics
- research governance

This separation is conceptually important. It permits the same market-state
variables to be studied for explanatory power even when they do not directly
change the final trade decision. In other words, the architecture supports both
operation and research.

### 13.4 Caveats

The architecture is disciplined, but it remains subject to:

- data-provider dependency
- approximation error in inferred structural state
- nonstationarity across regimes
- configuration complexity from a large governed parameter surface


## 14. Limitations

### 14.1 Epistemic limitations

The present framework relies on partial observability. It does not observe the
full latent state of options markets. In particular, it cannot directly observe:

- proprietary dealer inventory
- OTC offsets to listed positions
- hidden liquidity
- internal hedge-transfer arrangements
- trader-specific intent behind open-interest changes

Consequently, many structural variables in the system are inferential proxies
rather than directly measured quantities.

### 14.2 Identifiability and proxy-measurement limitations

Several quantities of interest are only weakly identified from public data:

- aggregate dealer gamma sign
- the effective side of net customer positioning
- the strength of hedge reinforcement versus pinning
- the precise geometric location of executable liquidity barriers

This creates an identifiability problem. Different latent market states may
generate observably similar public-data patterns.

### 14.3 Model misspecification risk

The framework combines theory, heuristic approximation, and engineered scoring.
This introduces several misspecification risks:

- incorrect sign conventions in gamma aggregation
- inaccurate mapping from chain variables to dealer behavior
- over-simplified liquidity topology
- use of additive scores where nonlinear interactions dominate
- misaligned expected-move scaling under unusual volatility surfaces

### 14.4 Nonstationarity and structural instability

Microstructure relationships are not stationary. The empirical relationship
between gamma regime, liquidity topology, and realized movement may vary across:

- expiry cycles
- volatility regimes
- macro environments
- market participation mixes
- exchange or market-structure changes

Accordingly, a parameter set that appears strong in one historical regime may
degrade materially in another.

### 14.5 Public-data dealer inference limits

Dealer inference from public chain data is inherently indirect. Even well-known
structural ideas such as long-gamma versus short-gamma regimes become
model-dependent when participant attribution and internal inventory are
unobserved. This does not invalidate such inference, but it places strict
limits on causal interpretation.

### 14.6 Limits of heuristic signal aggregation

The signal-construction layer is interpretable precisely because it is not a
fully free-form nonlinear model. That interpretability comes at a cost:

- additive score structures may omit higher-order interactions
- threshold regimes may be brittle near classification boundaries
- confirmation logic may under-represent nonlinear joint effects
- overlay layers may still interact in ways not fully captured by individual
  modifiers

### 14.7 Research and evaluation limitations

Even with a signal-evaluation-first architecture, empirical evaluation remains
subject to:

- horizon choice sensitivity
- regime imbalance
- sparse tail events
- circularity risk in evaluation-selection thresholds
- limited sample support for high-dimensional tuning surfaces

The presence of a rich parameter-governance stack does not eliminate the
statistical difficulty of identifying stable structure in noisy, regime-varying
financial data.

### 14.8 Implementation and operational limitations

The present system is not a live order-routing platform. Execution remains
outside the scope of the framework. Consequently:

- slippage is not inferred from real fills
- transaction costs are modeled only approximately in research tooling
- queue effects and exchange micro-timing are not represented
- operational broker behavior is external to the inference loop

The framework should therefore be interpreted as a market-state and signal
research system with implementation relevance, not as a complete production
trading stack.


## 15. Future Research

### 15.1 Volatility modeling

Promising extensions include:

- richer volatility-surface state summaries
- skew-aware expected-move estimation
- event-specific term-structure diagnostics
- realized-volatility forecasting conditioned on gamma and liquidity state

### 15.2 Dealer and inventory inference

Future work may consider:

- improved sign conventions for gamma aggregation
- expiry-specific dealer maps
- sensitivity analysis of hedge-pressure estimates to customer-positioning
  assumptions
- pathwise hedge-demand simulation under alternative spot shocks

### 15.3 Liquidity and topology

Liquidity inference can be deepened through:

- more refined strike-cluster topology measures
- better void and vacuum persistence estimation
- strike-transition hazard modeling
- explicit integration of executable spread dynamics

### 15.4 Macro and cross-asset conditioning

Further work could incorporate:

- explicit surprise modeling for scheduled macro events
- richer global-risk transmission modeling
- better decomposition of overnight gap risk
- regime-conditioned integration of macro and local microstructure states

### 15.5 Machine learning and statistical learning

The architecture is compatible with more advanced research layers, including:

- surrogate optimization over parameter packs
- regime-conditional pack recommendation
- experiment-ledger meta-modeling
- eventually neural meta-models under strict governance

Any such extension should preserve the present signal-evaluation-first and
promotion-governed structure.

### 15.6 Portfolio and execution research

Future research may extend beyond single-signal analysis toward:

- portfolio-level convexity budgeting
- cross-signal capital allocation
- exposure correlation control
- execution-quality attribution relative to signal-quality attribution


## 16. Conclusion

This work proposes a systematic framework for the study and operationalization
of options-market microstructure and convexity-sensitive inference. The central
conceptual contribution is the argument that options markets are not adequately
described by directional forecasting alone. Their short-horizon dynamics are
shaped by the interaction of nonlinear payoff structure, dealer hedging
feedback, strike-level inventory concentration, liquidity discontinuities, and
macro regime variation.

The methodological contribution of the framework lies in its layered
architecture. The present system separates theoretical concept, structural
approximation, computational realization, and empirical evaluation. It combines
Greek-based local sensitivity estimates, public-data microstructure inference,
global-risk conditioning, convexity overlays, and option-efficiency filters
within a signal-evaluation-first research program.

The intellectual position of the framework is therefore specific. It is not a
pure forecasting model, nor a full structural equilibrium model of dealer
inventory, nor an execution-only trading application. It is better understood
as an interpretable convexity and microstructure inference system whose outputs
are subjected to canonical signal evaluation, walk-forward validation, and
promotion governance.

In this sense, the Options Quant Engine should be viewed as a research platform
for the empirical study of options markets as convexity systems. Its value lies
not only in the signals it produces, but also in the disciplined methodology by
which those signals are formulated, evaluated, and revised.

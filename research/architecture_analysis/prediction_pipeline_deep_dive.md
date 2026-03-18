# Prediction Pipeline Deep Dive — Surgical Reference
**Date:** March 18, 2026  
**Purpose:** Complete structural map for implementing a pluggable predictor architecture

---

## 1. engine/trading_support/probability.py (690 lines)

### Imports (L1–L25)
```python
from config.probability_feature_policy import get_probability_feature_policy_config
from config.symbol_microstructure import get_microstructure_config
import models.feature_builder as feature_builder_mod
import models.large_move_probability as large_move_probability_mod
import models.ml_move_predictor as ml_move_predictor_mod
from .common import _call_first, _clip, _safe_float
```

### Global State (L27)
```python
_MOVE_PREDICTOR = None   # Singleton MLMovePredictor instance; lazily initialized
```

### Key Functions — Exact Signatures and Line Numbers

| Function | Line | Purpose |
|----------|------|---------|
| `_map_vacuum_strength(vacuum_state, liquidity_voids=None, nearest_vacuum_gap_pct=None)` | L30 | Converts vacuum diagnostics → bounded 0-1 feature |
| `_map_hedging_flow_ratio(hedging_bias, hedge_flow_value=None)` | L70 | Converts dealer-hedging → signed [-1,1] feature |
| `_map_smart_money_flow_score(smart_money_flow, flow_imbalance=None)` | L100 | Maps flow signals → bounded [-1,1] score |
| `_compute_gamma_flip_distance_pct(spot_price, gamma_flip)` | L131 | Returns `abs(spot - flip) / spot * 100` or None |
| `_compute_intraday_range_pct(symbol, spot_price, day_high, day_low, day_open, prev_close, lookback_avg_range_pct)` | L157 | Normalized session range vs historical baseline |
| `_compute_atm_iv_percentile(atm_iv)` | L237 | Linear percentile mapping between atm_iv_low..atm_iv_high |
| `_blend_move_probability(rule_prob, ml_prob)` | L258 | **THE BLEND FUNCTION** — weighted combo + logistic recalibration |
| `_get_move_predictor()` | L296 | **SINGLETON LOADER** — loads MLMovePredictor with optional registry base_model |
| `_extract_nearest_vacuum_gap_pct(spot, vacuum_zones)` | L338 | Finds closest vacuum zone gap from spot |
| `_extract_hedge_flow_value(hedging_flow)` | L380 | Extracts scalar flow value from dict/float |
| `_categorical_flow_score(value)` | L425 | Simple map: BULLISH→1.0, BEARISH→-1.0, else 0.0 |
| `_extract_probability(result)` | L445 | Extracts scalar probability from model result |
| **`_compute_probability_state(df, *, spot, symbol, market_state, day_high, day_low, day_open, prev_close, lookback_avg_range_pct, global_context)`** | **L473** | **MAIN ORCHESTRATOR** — builds all features, calls both predictors, returns full state dict |

### _compute_probability_state() — Complete Flow (L473–L690)

1. **Build 7-feature vector** (L510–L523): Calls `feature_builder_mod.build_features()` via `_call_first()` with basic market_state fields
2. **Compute probability sub-features** (L525–L556):
   - `nearest_vacuum_gap_pct` ← `_extract_nearest_vacuum_gap_pct(spot, market_state["vacuum_zones"])`
   - `hedge_flow_value` ← `_extract_hedge_flow_value(market_state["hedging_flow"])`
   - `flow_imbalance` ← weighted sum of categorical flow scores
   - `gamma_flip_distance_pct` ← `_compute_gamma_flip_distance_pct()`
   - `vacuum_strength` ← `_map_vacuum_strength()`
   - `hedging_flow_ratio` ← `_map_hedging_flow_ratio()`
   - `smart_money_flow_score` ← `_map_smart_money_flow_score()`
   - `atm_iv_percentile` ← `_compute_atm_iv_percentile()`
   - `intraday_range_pct` ← `_compute_intraday_range_pct()`
3. **Build 33-feature vector** (L559–L601): Calls `feature_builder_mod.build_features()` again with `**extra_context` (all sub-features + global context). Falls back to 7-feature if v2 unavailable.
4. **Rule-based probability** (L604–L618): Calls `large_move_probability_mod.large_move_probability()` via `_call_first()` with 4 positional args + 6 keyword sub-features.
5. **ML probability** (L620–L639): 
   - Gets predictor via `_get_move_predictor()` (singleton)
   - Calls `predictor.predict_probability(model_features)` 
   - Extracts + clips result
   - Silently falls back to None on any exception
6. **Returns dict** (L653–L690):
```python
{
    "rule_move_probability": float | None,
    "ml_move_probability": float | None,
    "hybrid_move_probability": float,  # ← _blend_move_probability(rule, ml)
    "model_features": ndarray | None,
    "components": {
        "gamma_flip_distance_pct", "nearest_vacuum_gap_pct",
        "vacuum_strength", "hedging_flow_ratio",
        "smart_money_flow_score", "atm_iv_percentile",
        "intraday_range_pct", "flow_imbalance",
        "hedge_flow_value", "day_high", "day_low",
        "day_open", "prev_close", "lookback_avg_range_pct"
    }
}
```

### _blend_move_probability() — Exact Logic (L258–L293)

```python
cfg = get_probability_feature_policy_config()
rule_prob = _safe_float(rule_prob, cfg.probability_default_rule)  # 0.22
if ml_prob is None:
    raw = clip(rule_prob, floor, ceiling)
else:
    ml_prob = _safe_float(ml_prob, rule_prob)
    hybrid = (cfg.probability_rule_weight * rule_prob) + (cfg.probability_ml_weight * ml_prob)
    #         0.35                                        0.65
    hybrid = cfg.probability_intercept + (cfg.probability_scale * hybrid)
    #         0.10                        0.80
    raw = clip(hybrid, floor, ceiling)

# Post-blend logistic recalibration (if enabled)
if cfg.calibration_enabled:
    calibrated = sigmoid(cfg.calibration_steepness * (raw - cfg.calibration_midpoint))
    #                     5.0                              0.40
    raw = clip(calibrated, floor, ceiling)
```

### _get_move_predictor() — Singleton Loading (L296–L336)

1. Checks if `MLMovePredictor` class exists on the module
2. On first call: tries to load `models_store/registry/{ACTIVE_MODEL}/model.joblib` via joblib
3. Creates `MLMovePredictor(base_model=loaded_model_or_None)`
4. Caches in `_MOVE_PREDICTOR` global; uses `False` sentinel for failed init
5. Returns cached instance on subsequent calls

---

## 2. models/ml_move_predictor.py (186 lines)

### Class: MLMovePredictor

| Method | Line | Signature | Purpose |
|--------|------|-----------|---------|
| `__init__` | L36 | `(self, base_model=None)` | Stores `self.base_model` |
| `_sigmoid` | L56 | `(self, x: float) -> float` | Clipped sigmoid [-8, 8] |
| `_normalize_row` | L72 | `(self, row: Iterable[float]) -> list[float]` | Pads to 7 features, clips each to [-1,1] |
| `_heuristic_probability` | L103 | `(self, X)` | Weighted sum → sigmoid → probability in [0.05, 0.95] |
| **`predict_probability`** | L139 | **(self, X)** | **Main entry point** |

### predict_probability() — Exact Flow (L139–L186)
```python
def predict_probability(self, X):
    if self.base_model is not None:
        try:
            result = self.base_model.predict_probability(X)
            return float(result[0]) if hasattr(result, "__len__") else float(result)
        except Exception:
            pass
    return self._heuristic_probability(X)
```

### Key Observations:
- **Input contract:** `X` = numpy array, shape `(1, N)` where N ≥ 7
- **Output contract:** scalar float probability
- **base_model contract:** must have `.predict_probability(X)` method returning array-like or scalar
- **Fallback:** the 7-feature heuristic is always available regardless of base_model
- **Heuristic weights (L120–L127):** `0.55*gamma + 0.65*flow + 0.35*vol + 0.70*hedging + 0.45*spot_flip + 0.55*vacuum + 0.25*iv` → sigmoid → `0.18 + 0.64 * sigmoid(score)` → [0.05, 0.95]

---

## 3. models/large_move_probability.py (152 lines)

### Single Function

```python
def large_move_probability(
    gamma_regime: str,          # positional
    vacuum_state: str,          # positional
    hedging_bias: str,          # positional
    smart_money_flow: str,      # positional
    *,
    gamma_flip_distance_pct: Optional[float] = None,
    vacuum_strength: Optional[float] = None,
    hedging_flow_ratio: Optional[float] = None,
    smart_money_flow_score: Optional[float] = None,
    atm_iv_percentile: Optional[float] = None,
    intraday_range_pct: Optional[float] = None,
) -> float
```

**Line:** L25  
**Config:** `get_large_move_probability_config()` from `config/large_move_policy.py`

### Logic Flow:
1. Start from `cfg["base_probability"]` (calibrated prior)
2. **Categorical adjustments:** gamma regime (+/- bonus), vacuum state (+bonus), hedging bias (+/-), flow direction (+/-)
3. **Continuous refinements:** gamma_flip_distance (inverted), vacuum_strength, hedging_flow_ratio (magnitude), smart_money_flow_score (magnitude), atm_iv_percentile, intraday_range
4. **Conflict penalties:** directional disagreement between flow and hedging, gamma-vacuum contradictions
5. **Output:** `clip(prob, floor, ceiling)` → float

### Key: This is the **rule-based leg** — essentially an additive evidence model. Each feature contributes a bounded delta to the probability.

---

## 4. models/feature_builder.py (140 lines)

### Global State (L24–L25)
```python
_REGISTRY_MODEL_AVAILABLE = None  # cached bool
```

### _check_registry_model() (L27–L40)
Checks if `config.settings.ACTIVE_MODEL` is set AND `models_store/registry/{ACTIVE_MODEL}/model.joblib` exists.

### build_features() — The Branching Point (L43–L140)

**Signature (L43):**
```python
def build_features(
    option_chain,
    spot=None, gamma_regime=None, final_flow_signal=None,
    vol_regime=None, hedging_bias=None, spot_vs_flip=None,
    vacuum_state=None, atm_iv=None,
    **extra_context,   # ← This is how v2 features pass through
)
```

**Branching Logic (L114–L128):**
```python
if _check_registry_model() and extra_context:
    # Build 33-feature vector via expanded_feature_builder
    row = {
        "gamma_regime": gamma_regime,
        "final_flow_signal": final_flow_signal,
        "volatility_regime": vol_regime,
        ...
        **extra_context,
    }
    expanded = _extract_expanded(row)
    return expanded.reshape(1, -1)

# Default: 7-feature compact vector
features = np.array([gamma_sign, flow_bias, vol_expansion, hedging_bias_score,
                      spot_flip_score, vacuum_score, iv_level])
return features.reshape(1, -1)
```

### Key: The branch is controlled by ACTIVE_MODEL config + whether extra_context is passed. When a registry model exists, the 33-feature `expanded_feature_builder.extract_features()` is used.

---

## 5. models/expanded_feature_builder.py (251 lines)

### Constants
- `FEATURE_NAMES` (L38–L87): List of 33 feature names in canonical order
- `N_FEATURES = 33` (L89)
- Intentionally zeroed features: `hist_vol_5d`, `hist_vol_20d`, `confirmation_numeric`, `moneyness_pct` (not available at prediction time)

### `extract_features(row: dict) -> np.ndarray`
Converts a dict of market state fields into a 33-dimensional numpy array using encoding maps.

---

## 6. config/probability_feature_policy.py (132 lines)

### ProbabilityFeaturePolicyConfig (frozen dataclass, L17)

**Critical blend weights:**
| Field | Default | Purpose |
|-------|---------|---------|
| `probability_rule_weight` | **0.35** | Weight for rule-based leg |
| `probability_ml_weight` | **0.65** | Weight for ML leg |
| `probability_intercept` | 0.10 | Additive offset after blending |
| `probability_scale` | 0.80 | Multiplicative scale after blending |
| `probability_default_rule` | 0.22 | Fallback when rule_prob is None |
| `probability_floor` | 0.05 | Hard lower bound |
| `probability_ceiling` | 0.95 | Hard upper bound |
| `calibration_enabled` | True | Post-blend logistic recalibration on/off |
| `calibration_midpoint` | 0.40 | Logistic center |
| `calibration_steepness` | 5.0 | Logistic steepness |

### Getter (L123):
```python
def get_probability_feature_policy_config() -> ProbabilityFeaturePolicyConfig:
    return resolve_dataclass_config("signal_engine.probability", ProbabilityFeaturePolicyConfig())
```
Uses `policy_resolver` which can override defaults from parameter packs or YAML configs.

---

## 7. engine/trading_support/signal_state.py (597 lines)

### Imports (L15–L25)
From `config.signal_policy`: direction thresholds, vote weights, execution regime policy, trade runtime thresholds  
From `strategy`: `compute_confirmation_filters`, `compute_trade_strength`

### Key Functions

| Function | Line | Purpose |
|----------|------|---------|
| `_compute_data_quality(...)` | L29 | Scores data quality 0-100 from spot/chain/analytics/probability validation |
| `classify_spot_vs_flip(spot, flip)` | L131 | Returns ABOVE_FLIP / BELOW_FLIP / AT_FLIP / UNKNOWN |
| `classify_spot_vs_flip_for_symbol(symbol, spot, flip)` | L149 | Same with per-symbol flip buffer |
| `classify_signal_quality(trade_strength)` | L172 | Returns STRONG / MEDIUM / WEAK / VERY_WEAK |
| `classify_signal_regime(...)` | L188 | Returns EXPANSION_BIAS / DIRECTIONAL_BIAS / CONFLICTED / BALANCED / LOCKDOWN / NEUTRAL |
| `classify_execution_regime(...)` | L236 | Returns BLOCKED / RISK_REDUCED / ACTIVE / OBSERVE / SETUP |
| `normalize_flow_signal(flow, smart_money)` | L264 | Combines two categorical flow signals via vote |
| **`decide_direction(...)`** | **L298** | **THE DIRECTION DECISION** — weighted vote system → CALL / PUT / None |
| **`_compute_signal_state(...)`** | **L520** | **Orchestrates direction + trade_strength + confirmation** |

### decide_direction() — Exact Flow (L298–L518)

**Signature:**
```python
def decide_direction(
    final_flow_signal, dealer_pos, vol_regime, spot_vs_flip,
    gamma_regime, hedging_bias, gamma_event,
    vanna_regime=None, charm_regime=None, backtest_mode=False,
)
```

**Vote Sources (L413–L468):**
1. `FLOW` vote: from `final_flow_signal` (BULLISH/BEARISH)
2. `HEDGING_BIAS` vote: from `hedging_bias` + `gamma_regime` (only in SHORT_GAMMA)
3. `GAMMA_SQUEEZE` vote: from `gamma_event` + `spot_vs_flip`
4. `GAMMA_FLIP` vote: from `spot_vs_flip` + `dealer_pos`
5. `DEALER_VOL` vote: from `dealer_pos` + `vol_regime` + `spot_vs_flip`
6. `VANNA` vote: vanna_regime + spot_vs_flip
7. `CHARM` vote: charm_regime + spot_vs_flip

**Decision Logic (L484–L505):**
```python
bullish_score = sum(weight for _, weight in bullish_votes)
bearish_score = sum(weight for _, weight in bearish_votes)
score_margin = abs(bullish_score - bearish_score)

if bullish_score >= min_score AND bullish > bearish AND margin >= min_margin:
    return "CALL", source_string
if bearish_score >= min_score AND bearish > bullish AND margin >= min_margin:
    return "PUT", source_string
return None, None
```

### _compute_signal_state() — Complete Flow (L520–L597)

1. Calls `decide_direction()` → direction, source
2. If direction is None → returns empty signal state with strength=0
3. Calls `compute_trade_strength()` → trade_strength, scoring_breakdown  
   - Passes: market_state fields, `probability_state["hybrid_move_probability"]`, `probability_state["ml_move_probability"]`
4. Calls `compute_confirmation_filters()` → confirmation state
5. Returns dict with direction, direction_source, trade_strength, scoring_breakdown, confirmation

**CRITICAL:** Direction is decided BEFORE probability is used for trade_strength. The direction vote system does NOT use probability at all. Probability feeds into trade_strength scoring.

---

## 8. backtest/holistic_backtest_runner.py (622 lines)

### How It Calls the Engine (L443–L471)

```python
signal_result = run_preloaded_engine_snapshot(
    symbol=symbol,
    mode="BACKTEST",
    source="HISTORICAL_HOLISTIC",
    spot_snapshot=spot_snapshot,
    option_chain=expiry_chain,
    previous_chain=previous_chain,
    apply_budget_constraint=BACKTEST_ENABLE_BUDGET,
    ...
    global_market_snapshot=snap["global_market_snapshot"],
    macro_event_state=snap["macro_event_state"],
    target_profit_percent=target_profit_percent,
    stop_loss_percent=stop_loss_percent,
)
```

### Backtest Loop (L413–L523)
For each `trade_date` in available dates:
1. `replay_historical_snapshot(trade_date, symbol, ...)` → full snapshot
2. `ordered_expiries(option_chain)` → get up to `max_expiries`
3. For each expiry: `filter_option_chain_by_expiry()` → `run_preloaded_engine_snapshot()` → capture signal row
4. Evaluate outcomes against realized spot path

### Key Injection Point: The backtest has NO direct access to the predictor. It calls `run_preloaded_engine_snapshot()` which calls `_evaluate_snapshot_for_pack()` which calls `generate_trade()` which calls `_compute_probability_state()` which calls `_get_move_predictor()`.

**To inject a different predictor in backtesting:** You'd need to either:
- Change `_MOVE_PREDICTOR` global before the backtest runs
- Provide a different ACTIVE_MODEL config
- Or add a predictor parameter to the chain

---

## 9. app/engine_runner.py (1365 lines)

### Two Entry Points

1. **`run_engine_snapshot()`** (L1220): Live + Replay. Loads market data, then calls `run_preloaded_engine_snapshot()`
2. **`run_preloaded_engine_snapshot()`** (L1022): Backtest + all modes. This is the shared orchestration seam.

### `run_preloaded_engine_snapshot()` Flow (L1022–L1200)

1. Resolve parameter packs (authoritative + shadow)
2. `_prepare_snapshot_context()` → validates spot, resolves expiry, filters chain, assembles macro/headline/global-market state
3. `_evaluate_snapshot_for_pack()` → the actual engine call
4. `_build_result_payload()` → assembles the 30+ field result dict
5. `_maybe_attach_shadow_evaluation()` → optional shadow A/B comparison
6. `_apply_signal_capture()` → persists signal for research

### `_evaluate_snapshot_for_pack()` (L940–L1015)

The critical function that calls `generate_trade()`:
```python
with temporary_parameter_pack(parameter_pack_name):
    macro_news_state = build_macro_news_state(...)
    global_risk_state = build_global_risk_state(...)
    trade = generate_trade(
        symbol=symbol,
        spot=spot,
        option_chain=option_chain,
        previous_chain=previous_chain,
        day_high=day_high, day_low=day_low, day_open=day_open,
        prev_close=prev_close, lookback_avg_range_pct=lookback_avg_range_pct,
        spot_validation=spot_validation,
        option_chain_validation=option_chain_validation,
        apply_budget_constraint=...,
        backtest_mode=backtest_mode,
        macro_event_state=macro_event_state,
        macro_news_state=macro_news_state,
        global_risk_state=global_risk_state,
        holding_profile=holding_profile,
        valuation_time=spot_timestamp,
        target_profit_percent=...,
        stop_loss_percent=...,
    )
```

---

## 10. engine/signal_engine.py — generate_trade() (L467–L650+)

### The Signal Pipeline — Exact Sequence

```
generate_trade()                                    # L467
  ├── normalize_option_chain(option_chain, spot)    # L537
  ├── _collect_market_state(df, spot, symbol)       # L541
  ├── Build _global_ctx dict for v2 features        # L545-L556
  ├── _compute_probability_state(                   # L558 ← from probability.py
  │       df, spot, symbol, market_state,
  │       day_high, day_low, day_open, prev_close,
  │       lookback_avg_range_pct, global_context)
  │     ├── build_features() [7-feature]
  │     ├── compute sub-features (vacuum, hedging, flow, etc.)
  │     ├── build_features() [33-feature if ACTIVE_MODEL]
  │     ├── large_move_probability()   → rule_prob
  │     ├── _get_move_predictor()      → MLMovePredictor
  │     ├── predict_probability(X)     → ml_prob
  │     └── _blend_move_probability(rule, ml) → hybrid_prob
  ├── _compute_data_quality(...)                    # L593
  ├── _compute_signal_state(                        # L604 ← from signal_state.py
  │       spot, symbol, market_state,
  │       probability_state)
  │     ├── decide_direction()   → CALL/PUT/None (weighted vote, NO probability)
  │     ├── compute_trade_strength() → uses hybrid_probability + ml_probability
  │     └── compute_confirmation_filters()
  ├── compute_macro_news_adjustments()              # L617
  ├── derive_global_risk_trade_modifiers()          # L649
  ├── compute adjusted_trade_strength               # (further down)
  ├── strike selection + position sizing             # (further down)
  └── build final trade/no-trade payload
```

---

## CRITICAL DATA FLOW MAP

```
                          ┌─────────────────────────────────┐
                          │      config/settings.py          │
                          │   ACTIVE_MODEL = "model_name"    │
                          └───────────┬─────────────────────┘
                                      │
                          ┌───────────▼─────────────────────┐
                          │   models/feature_builder.py      │
                          │   _check_registry_model()        │
                          │   build_features(**extra_context) │
                          │   → 7-feature OR 33-feature ndarray
                          └───────────┬─────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────────┐
          │                           │                               │
          ▼                           ▼                               ▼
  ┌───────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
  │ large_move_prob() │   │ _get_move_predictor() │   │ ProbabilityFeature   │
  │  (rule-based)     │   │  → MLMovePredictor    │   │  PolicyConfig        │
  │  returns float    │   │  .predict_probability │   │  (blend weights)     │
  └────────┬──────────┘   │  returns float        │   └──────────┬───────────┘
           │               └──────────┬───────────┘              │
           │                          │                           │
           └──────────┬───────────────┘                           │
                      ▼                                           ▼
             ┌────────────────────────────────────────────────────────┐
             │          _blend_move_probability(rule, ml)             │
             │   hybrid = 0.35*rule + 0.65*ml                       │
             │   hybrid = 0.10 + 0.80*hybrid                        │
             │   → logistic recalibration (midpoint=0.40, steep=5.0) │
             └────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
                     { "hybrid_move_probability": float,
                       "rule_move_probability": float,
                       "ml_move_probability": float,
                       "model_features": ndarray,
                       "components": {...} }
                                  │
                                  ▼
            ┌─────────────────────────────────────────┐
            │       _compute_signal_state()           │
            │  decide_direction() → CALL/PUT/None     │
            │  compute_trade_strength() ← uses hybrid │
            │  compute_confirmation_filters()         │
            └─────────────────────────────────────────┘
```

---

## PLUGGABLE PREDICTOR — KEY SURGICAL EDIT POINTS

### Files That Must Change for a Protocol-Based Predictor

| # | File | Line(s) | What to Change |
|---|------|---------|----------------|
| 1 | `engine/trading_support/probability.py` | L27 | `_MOVE_PREDICTOR` global — replace with predictor factory/registry |
| 2 | `engine/trading_support/probability.py` | L296–L336 | `_get_move_predictor()` — replace singleton loading with protocol dispatch |
| 3 | `engine/trading_support/probability.py` | L620–L639 | ML probability call site — currently `predictor.predict_probability(model_features)` |
| 4 | `models/ml_move_predictor.py` | L36 | `MLMovePredictor.__init__` — extract Protocol/ABC from this class |
| 5 | `models/ml_move_predictor.py` | L139–L186 | `predict_probability()` — this defines the interface contract |
| 6 | `models/feature_builder.py` | L114–L128 | Feature vector selection — must support predictor-specific feature dimensions |
| 7 | `config/probability_feature_policy.py` | L80–L87 | Blend weights — may need per-predictor overrides |

### What Does NOT Need to Change
- `models/large_move_probability.py` — the rule-based leg is independent
- `engine/trading_support/signal_state.py` — direction decision doesn't use probability
- `backtest/holistic_backtest_runner.py` — calls through `run_preloaded_engine_snapshot()`; no direct predictor access
- `app/engine_runner.py` — orchestration layer; no direct predictor knowledge
- `engine/signal_engine.py` — calls `_compute_probability_state()` opaquely

### The Implicit Predictor Interface (duck-typed today)

```python
class MovePredictor(Protocol):
    def predict_probability(self, X: np.ndarray) -> float | np.ndarray:
        """
        X: shape (1, N) where N is 7 (compact) or 33 (expanded)
        Returns: scalar float or array of floats, clipped to [0.05, 0.95]
        """
        ...
```

### How ACTIVE_MODEL Controls Everything

```
config/settings.py::ACTIVE_MODEL = "my_model_v3"
    │
    ├── feature_builder.py::_check_registry_model()
    │   → checks models_store/registry/my_model_v3/model.joblib exists
    │   → if True: build_features() returns 33-dim vector
    │   → if False: build_features() returns 7-dim vector
    │
    └── probability.py::_get_move_predictor()
        → loads models_store/registry/my_model_v3/model.joblib as base_model
        → MLMovePredictor(base_model=loaded_model)
        → predict_probability() delegates to base_model first, heuristic fallback
```

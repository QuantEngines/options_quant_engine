# Prediction Pipeline Architecture Report

**Date:** March 18, 2026  
**Scope:** How the production engine makes predictions, and whether the codebase supports swapping between prediction methods  
**Type:** Research-only analysis — no code changes

---

## 1. Executive Summary

The prediction pipeline is a **two-leg blend** (rule-based + ML) with a single config knob (`ACTIVE_MODEL`) that controls whether the ML leg is active. The architecture is **moderately coupled** — it already supports graceful degradation from ML → heuristic, but it does **not** have a formal strategy/factory/plugin pattern for swapping entire prediction methodologies. Switching from the current blend to a completely different prediction approach (e.g., pure deep learning, ensemble of different model types, or regime-conditional dispatch) would require code changes in 3–4 specific files.

**Key finding:** The system is designed around a specific prediction *topology* (rule + ML → blend → direction + strength → overlays → trade), not around a pluggable prediction *interface*. The coupling is at the pipeline structure level, not at the component level.

---

## 2. Complete Prediction Pipeline Flow

```
Market Data → Option Chain Normalization
         ↓
    Market State Assembly (_collect_market_state)
         ↓
    Feature Building (7-feature OR 33-feature)
         ↓
    ┌─────────────────────────────────────────┐
    │         Probability State Assembly       │
    │                                          │
    │  ┌─ Rule Leg: large_move_probability()  │
    │  │     (additive evidence model)         │
    │  │                                       │
    │  ├─ ML Leg: MLMovePredictor              │
    │  │     .predict_probability(features)    │
    │  │     (TrainedMovePredictor or heuristic)│
    │  │                                       │
    │  └─ Blend: _blend_move_probability()     │
    │      rule_weight=0.35, ml_weight=0.65    │
    │      + logistic recalibration            │
    └─────────────────────────────────────────┘
         ↓
    Direction Decision (weighted vote system)
         ↓
    Trade Strength Scoring (additive)
         ↓
    Confirmation Filters
         ↓
    Risk Overlays (global risk, macro, gamma-vol, dealer, option efficiency)
         ↓
    Strike Selection → Exit Model → Budget Optimizer
         ↓
    Signal Confidence (post-hoc display metric)
         ↓
    Final Trade/No-Trade Payload
```

---

## 3. Component-by-Component Analysis

### 3.1 Engine Orchestrator: `engine/signal_engine.py`

**Entry point:** `generate_trade()` at line 467

- **Interface:** Pure function, no class, no abstract base
- **Configurable?** Parameters accepted via function args (backtest_mode, target_profit_percent, etc.) but prediction method is not parameterized
- **Coupling:** Directly imports and calls `_compute_probability_state`, `_compute_signal_state`, `_compute_data_quality` from `engine/trading_support/`
- **Key observation:** The `generate_trade()` function IS the prediction pipeline. It's a procedural orchestration, not a strategy-pattern dispatch.

**Coupling location:** Lines 554–567 — `_compute_probability_state()` call is hardcoded inline.

### 3.2 Probability Pipeline: `engine/trading_support/probability.py`

This is where the three probability values are computed.

#### 3.2.1 Rule-Based Leg: `large_move_probability()`
- **File:** `models/large_move_probability.py`
- **Type:** Pure function (no class), additive bounded evidence model
- **Configurable?** Yes — all weights/thresholds come from `get_large_move_probability_config()` which routes through the policy resolver and parameter pack system
- **Interface:** None — it's a concrete function, not behind an interface

#### 3.2.2 ML Leg: `MLMovePredictor` class
- **File:** `models/ml_move_predictor.py`
- **Type:** Concrete class with `predict_probability(X)` method
- **Delegation pattern:** If `base_model` is provided, delegates to `base_model.predict_probability(X)`. On failure, falls back to internal `_heuristic_probability()` (sigmoid over weighted 7-feature sum).
- **Interface:** Implicit duck-typing — `base_model` must have `predict_probability(X)` method. NO formal Protocol/ABC defined.
- **Key lines:** Lines 163–185 — `predict_probability()` tries base_model, falls back to heuristic.

#### 3.2.3 `TrainedMovePredictor` wrapper
- **File:** `models/trained_predictor.py`
- **Type:** Concrete class wrapping sklearn model
- **Interface:** Implements `predict_probability(X)` (matching `MLMovePredictor.base_model` duck-type contract)
- **Feature masking:** Automatically applies stored `feature_mask` to handle 33→N feature projection
- **Coupling:** Tightly bound to sklearn's `predict_proba()` API

#### 3.2.4 Model Loading: `_get_move_predictor()`
- **File:** `engine/trading_support/probability.py`, lines 316–350
- **Mechanism:** Module-level singleton cached in `_MOVE_PREDICTOR` global
- **Model discovery:** Reads `config.settings.ACTIVE_MODEL` → looks for `models_store/registry/{name}/model.joblib` → loads via joblib
- **No model loaded?** `MLMovePredictor(base_model=None)` → purely heuristic
- **Configurable via:** `ACTIVE_MODEL` in `config/settings.py` (line 168) or `OQE_ACTIVE_MODEL` env var
- **NOT configurable:** Cannot swap the predictor class itself, only the sklearn model inside it

#### 3.2.5 Blending: `_blend_move_probability()`
- **File:** `engine/trading_support/probability.py`, lines 270–303
- **Formula:** `hybrid = (rule_weight × rule) + (ml_weight × ml)`, then intercept + scale, then optional logistic recalibration
- **Weights from:** `ProbabilityFeaturePolicyConfig` (default: rule=0.35, ml=0.65)
- **Configurable via:** Parameter pack overrides on `signal_engine.probability.*` keys
- **Fallback:** If ML is None, uses rule probability directly (still clipped and calibrated)

### 3.3 Feature Building: `models/feature_builder.py`

- **Branching logic at line 117:** If `_check_registry_model()` returns True AND `extra_context` kwargs are provided → builds 33-feature vector via `expanded_feature_builder.extract_features()`. Otherwise → builds 7-feature vector.
- **Key coupling:** `_check_registry_model()` reads `config.settings.ACTIVE_MODEL` the same way `_get_move_predictor()` does. The two are implicitly linked but NOT formally connected.
- **33-feature builder:** `models/expanded_feature_builder.py` — canonical 33-feature vector with topological dependency ordering. Features are deterministic from market state (no circularity).

### 3.4 Direction Decision: `engine/trading_support/signal_state.py`

- **Function:** `decide_direction()` at line 341
- **Mechanism:** Weighted voting system — each market mechanism (flow, hedging bias, gamma squeeze, gamma flip, dealer vol, vanna, charm) casts votes with configurable weights
- **Configuration:** Weights from `signal_policy.get_direction_vote_weights()`, thresholds from `get_direction_thresholds()`
- **Coupling:** Does NOT use probability output — direction is decided from market-state signals, independently of the probability model
- **Interface:** None — concrete function

### 3.5 Trade Strength: `strategy/trade_strength.py`

- **Mechanism:** Additive score from market-state features (flow alignment, gamma regime, wall proximity, hedging bias, etc.)
- **Uses `hybrid_move_probability`:** Yes, as one scoring input
- **Configuration:** All weights from `get_trade_strength_weights()` policy config
- **Interface:** None — concrete function

### 3.6 Confirmation Filters: `strategy/confirmation_filters.py`

- **Function:** `compute_confirmation_filters()`
- **Uses `hybrid_move_probability`:** Yes, as one confirmation signal
- **Configuration:** All thresholds from `get_confirmation_filter_config()`
- **Interface:** None — concrete function

### 3.7 Signal Confidence: `analytics/signal_confidence.py`

- **Function:** `compute_signal_confidence(trade)`
- **Type:** Post-hoc analysis — operates on the already-built trade payload
- **Modular?** Yes — five independent weighted component scorers, each 0–100
- **Components:** signal_strength (0.30), confirmation (0.25), market_stability (0.20), data_integrity (0.15), option_efficiency (0.10)
- **Interface:** None, but fully decoupled — reads from trade dict, doesn't import engine internals

### 3.8 App Runner: `app/engine_runner.py`

- **Orchestration:** `_evaluate_snapshot_for_pack()` (line ~880) → calls `generate_trade()` directly
- **Parameter pack system:** Wraps call in `temporary_parameter_pack()` context manager so different packs can be evaluated
- **Shadow mode:** Runs same snapshot under shadow pack for A/B comparison
- **Runtime sinks:** Uses `Protocol` classes (`SignalCaptureSink`, `ShadowEvaluationSink`) — these are the ONLY formal Protocol contracts in the pipeline
- **Wiring:** No dependency injection for the prediction pipeline itself — `generate_trade` is imported directly

### 3.9 Configuration / Policy System

**Three-tier configuration architecture:**

1. **`config/settings.py`** — Module-level constants (ACTIVE_MODEL, lot sizes, thresholds)
2. **`config/*_policy.py`** files — Frozen dataclass configs with defaults, resolved through `policy_resolver.py`
3. **Parameter packs** (`config/parameter_packs/*.json`) — Override bundles merged via `policy_resolver.resolve_dataclass_config(prefix, defaults)`

**Critical setting:** `ACTIVE_MODEL` at `config/settings.py` line 168
- `None` → heuristic-only (7-feature) path
- `"GBT_shallow_v1"` (or any registry name) → loads trained model, switches to 33-feature path

**Blend weights are overridable** via parameter packs:
- `signal_engine.probability.probability_rule_weight` (default 0.35)
- `signal_engine.probability.probability_ml_weight` (default 0.65)
- `signal_engine.probability.calibration_enabled` / `calibration_midpoint` / `calibration_steepness`

---

## 4. Pattern Inventory

| Pattern | Present? | Where |
|---------|----------|-------|
| **Strategy Pattern** | ❌ No | No interface for swappable prediction strategies |
| **Factory Pattern** | ❌ No | Model loading is inline in `_get_move_predictor()` |
| **Plugin Pattern** | ❌ No | No discovery/registration mechanism for predictors |
| **Protocol/ABC** | ⚠️ Partial | `runtime_sinks.py` uses `Protocol` for sinks; `news/providers.py` uses `ABC` for headline providers. But none for predictors. |
| **Duck Typing** | ✅ Yes | `MLMovePredictor.base_model` expects `predict_probability(X)` — implicit contract |
| **Config-driven branching** | ✅ Yes | `ACTIVE_MODEL` controls 7-feature heuristic vs 33-feature trained model |
| **Parameter Pack overrides** | ✅ Yes | Blend weights, thresholds, calibration params are all overridable |
| **Dependency Injection** | ⚠️ Partial | Sinks are injected; predictor is NOT injected |
| **Singleton/Global** | ✅ Yes | `_MOVE_PREDICTOR` module-level global in `probability.py` |

---

## 5. Coupling Analysis

### 5.1 Tight Coupling Points

| Location | File | Lines | What's Coupled |
|----------|------|-------|----------------|
| Model loading | `engine/trading_support/probability.py` | 316–350 | `_get_move_predictor()` hardcodes `MLMovePredictor` class lookup, joblib loading from `models_store/registry/`, and `ACTIVE_MODEL` reading |
| Feature vector branching | `models/feature_builder.py` | 117–140 | `build_features()` has if/else for 7 vs 33 features tied to `_check_registry_model()` |
| Probability assembly | `engine/trading_support/probability.py` | 486–700 | `_compute_probability_state()` hardcodes the three-step pipeline: features → rule + ML → blend |
| Blend formula | `engine/trading_support/probability.py` | 270–303 | `_blend_move_probability()` assumes exactly two inputs (rule, ml) with a linear combination |
| Generate trade orchestration | `engine/signal_engine.py` | 467–680+ | `generate_trade()` calls functions in fixed order with no dispatch mechanism |

### 5.2 Loose Coupling Points (Leverage Opportunities)

| Location | What's Already Decoupled |
|----------|--------------------------|
| `MLMovePredictor.base_model` duck-type | Any object with `predict_probability(X)` works |
| `TrainedMovePredictor` wrapper | Adapts sklearn to the duck-type contract |
| All policy configs via `resolve_dataclass_config()` | Blend weights, calibration, feature mappings are all overridable |
| `_call_first()` helper | Used to call model functions by name with fallback — adds robustness but not pluggability |
| Signal confidence | Fully decoupled post-hoc analysis |
| Direction decision | Independent of the probability model |
| Parameter pack system | Can override any policy dataclass field per-pack |

---

## 6. What Would Need to Change to Support Method Switching

### Scenario A: Swap the ML model (ALREADY SUPPORTED)
**Effort: Zero code changes**
- Set `ACTIVE_MODEL = "new_model_name"` in `config/settings.py`
- Place trained model at `models_store/registry/{name}/model.joblib`
- Model must be a `TrainedMovePredictor` wrapping an sklearn classifier with `predict_proba()`
- The 33-feature expanded vector is automatically built

### Scenario B: Change blend weights between rule & ML (ALREADY SUPPORTED)
**Effort: Zero code changes**
- Create or modify a parameter pack JSON with overrides:
  ```json
  {
    "overrides": {
      "signal_engine.probability.probability_rule_weight": 0.50,
      "signal_engine.probability.probability_ml_weight": 0.50
    }
  }
  ```
- Or go fully ML: `{"signal_engine.probability.probability_rule_weight": 0.0, "signal_engine.probability.probability_ml_weight": 1.0}`

### Scenario C: Use ONLY rule-based prediction, no ML (ALREADY SUPPORTED)
**Effort: Zero code changes**
- Unset `ACTIVE_MODEL` (set to `None` or empty string)
- The ML leg returns `None`, and `_blend_move_probability` falls back to calibrated rule-only

### Scenario D: Replace the entire prediction topology (NEW APPROACH)
**Effort: Moderate code changes in 3–4 files**

What would need to change:

1. **Define a `MovePredictor` Protocol** (new file or in `models/__init__.py`)
   - `predict(market_state, option_chain, global_context) → ProbabilityState`
   - Could return the full `{rule_move_probability, ml_move_probability, hybrid_move_probability, components}` dict

2. **Refactor `_compute_probability_state()`** in `engine/trading_support/probability.py`
   - Replace the hardcoded three-step pipeline with a dispatch to the configured predictor
   - Move current logic into a `DefaultBlendedPredictor` class implementing the Protocol

3. **Add predictor selection to `config/settings.py`**
   - e.g., `PREDICTION_METHOD = "blended"` | `"pure_ml"` | `"rule_only"` | `"custom"`
   - Factory function to instantiate the right predictor class

4. **Update `_get_move_predictor()`** → migrate to a registry/factory pattern
   - Currently returns `MLMovePredictor` only
   - Would need to return any predictor implementing the Protocol

5. **Feature builder flexibility**
   - Current `build_features()` has two hardcoded paths (7 vs 33)
   - A new prediction approach might need different features entirely

### Scenario E: Regime-conditional dispatch (e.g., different models for different market regimes)
**Effort: Moderate — touches probability.py + new dispatcher**

- `market_state["gamma_regime"]` and `market_state["vol_regime"]` are already computed before probability
- A regime-aware dispatcher could select different predictors based on market state
- Currently no infrastructure for this — would need a new routing layer

---

## 7. Existing Abstractions That Could Be Leveraged

1. **`predict_probability(X)` duck-type contract** — Already used by both `MLMovePredictor` and `TrainedMovePredictor`. Formalizing this as a `Protocol` would enable proper type checking and documentation.

2. **`resolve_dataclass_config()` in `policy_resolver.py`** — The parameter pack system can override ANY field in a frozen dataclass. This means adding new config fields (like `prediction_method`) would automatically become overridable per-pack.

3. **`temporary_parameter_pack()` context manager** — Already supports running the same snapshot under different configs (shadow mode uses this). Could be extended to swap prediction methods per-pack.

4. **`SignalCaptureSink` / `ShadowEvaluationSink` Protocols** — Prove the codebase already uses Protocol-based DI for some concerns. The same pattern could be applied to predictors.

5. **`_call_first()` helper** — Used for resilient function dispatch by trying candidate function names in order. Could be extended for predictor method resolution.

---

## 8. Architecture Diagram

```
config/settings.py                    config/parameter_packs/*.json
  ACTIVE_MODEL ──┐                         │
                 │                         ▼
                 │              config/policy_resolver.py
                 │              resolve_dataclass_config()
                 │                         │
                 ▼                         ▼
  models/feature_builder.py       config/probability_feature_policy.py
  ┌──────────────────────┐       ┌──────────────────────────────┐
  │ if ACTIVE_MODEL:     │       │ probability_rule_weight: 0.35│
  │   33-feature vector  │       │ probability_ml_weight: 0.65  │
  │ else:                │       │ calibration_enabled: True    │
  │   7-feature vector   │       └──────────────────────────────┘
  └──────────┬───────────┘                   │
             │                               │
             ▼                               │
  engine/trading_support/probability.py      │
  ┌──────────────────────────────────────────┤
  │ _get_move_predictor()                    │
  │   → MLMovePredictor(base_model)          │
  │     base_model = TrainedMovePredictor    │
  │     (if ACTIVE_MODEL set)                │
  │                                          │
  │ _compute_probability_state()             │
  │   ├── rule_move_probability              │
  │   │   └── large_move_probability()       │
  │   │       (models/large_move_prob.py)    │
  │   ├── ml_move_probability               │
  │   │   └── predictor.predict_probability()│
  │   └── hybrid = blend(rule, ml) ◄────────┘
  │       (weighted per policy config)
  └──────────────┬───────────────────
                 │
                 ▼
  engine/trading_support/signal_state.py
  ┌──────────────────────────────────┐
  │ decide_direction() ← market_state│
  │ compute_trade_strength()         │
  │   ← direction + hybrid_prob      │
  │ compute_confirmation_filters()   │
  └──────────────┬───────────────────┘
                 │
                 ▼
  engine/signal_engine.py::generate_trade()
  ┌──────────────────────────────────┐
  │ Risk overlays                    │
  │ Strike selection                 │
  │ Exit model                       │
  │ Budget optimizer                 │
  │ Signal confidence (post-hoc)     │
  │ → Final Trade/No-Trade Payload   │
  └──────────────────────────────────┘
```

---

## 9. Summary Table

| Question | Answer |
|----------|--------|
| Can you swap the ML model via config? | **YES** — `ACTIVE_MODEL` setting |
| Can you change blend weights via config? | **YES** — parameter pack overrides |
| Can you go pure rule-based via config? | **YES** — unset `ACTIVE_MODEL` |
| Can you go pure ML (no rule leg) via config? | **Partially** — set rule_weight=0.0 in pack, but rule function still executes |
| Can you swap the entire prediction approach via config? | **NO** — requires code changes |
| Is there a formal predictor interface? | **NO** — duck typing only |
| Is the predictor injected or hardcoded? | **Hardcoded** — singleton in `probability.py` |
| Are there strategy/factory/plugin patterns? | **NO** — procedural pipeline |
| Does the parameter pack system help? | **YES** — already overrides blend weights, thresholds, calibration |
| What's the minimum change for full pluggability? | Define Protocol + refactor `_compute_probability_state()` + add factory |

---

## 10. Risk Assessment for Modifications

| Change | Risk | Reason |
|--------|------|--------|
| Swap registry model | **LOW** | Already supported, tested path |
| Adjust blend weights via pack | **LOW** | Config-only, reversible |
| Add new feature to 33-vector | **MEDIUM** | Must update `expanded_feature_builder.py` + retrain model |
| Add new prediction Protocol | **MEDIUM** | Requires touching `probability.py`, `feature_builder.py`, `settings.py` |
| Regime-conditional dispatch | **MEDIUM-HIGH** | New routing layer + multiple model artifacts |
| Replace `generate_trade()` pipeline | **HIGH** | Downstream consumers depend on payload shape |

---

*Report generated from source code analysis. No code was modified.*

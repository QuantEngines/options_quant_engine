---
title: "Options Quant Engine"
subtitle: "Architecture Audit Report"
author: "Pramit Dutta"
date: "March 2026"
---

<div class="memo-cover">
<div class="cover-kicker">Technical Audit</div>
<h1 class="cover-title">Options Quant Engine</h1>
<div class="cover-subtitle">Architecture Audit Report</div>
<div class="cover-rule"></div>
<p class="cover-summary">Full structural review of the options_quant_engine codebase covering drift detection, coupling analysis, centrality metrics, pipeline integrity, research/production separation, Streamlit safety, and scalability assessment.</p>
<div class="cover-meta">
<div><span>Author</span>Pramit Dutta</div>
<div><span>Organization</span>Quant Engines</div>
<div><span>Date</span>March 2026</div>
<div><span>Document</span>Architecture Audit</div>
<div><span>Scope</span>Drift, coupling, centrality, pipeline integrity, and scalability</div>
</div>
</div>

# Architecture Audit Report

**Scope**: Full structural review of `options_quant_engine` — drift, coupling, centrality, pipeline integrity, research/production separation, Streamlit safety, and scalability.

---

## 1. Layer Dependency Graph

The codebase enforces a clean, unidirectional data flow:

```
app/streamlit_app  →  app/engine_runner  →  engine/signal_engine
                                                   ↓
                      ┌────────────────────────────┤
                      ↓                            ↓
                 strategy/                    risk/ (4 overlays)
              (strike_selector,                    ↓
               confirmation_filters,        macro/ → news/
               exit_model,
               budget_optimizer)                   ↓
                      ↓                       analytics/
                      └──────────┬─────────────────┘
                                 ↓
                              data/
                                 ↓
                            config/settings
```

**No reverse dependencies detected.** None of `analytics/`, `strategy/`, `risk/`, `macro/`, `news/`, `models/`, or `data/` import from `engine.signal_engine` or `app.engine_runner`. This is the single most important architectural invariant in the codebase and it holds.

---

## 2. Architecture Drift Assessment

| Area | Status | Detail |
|------|--------|--------|
| Layer boundaries | **Clean** | No upward imports detected across any layer |
| Config pattern | **Consistent** | All 30+ policy files use `policy_resolver.resolve_dataclass_config()` |
| Risk overlay ordering | **Codified** | `engine_runner.py` applies overlays in fixed sequence: macro/news → global_risk → gamma_vol → dealer_hedging → option_efficiency |
| Utility duplication | **Fixed** | `_safe_float` (20 copies), `_clip` (17 copies), `_norm_cdf` (2 copies) consolidated into `utils/` package |
| Tuning governance | **Complete** | Full 6-stage lifecycle: registry → experiments → search → shadow → promotion → rollback |

**Drift verdict**: No structural drift detected. The codebase has strong layering discipline.

---

## 3. Coupling Hotspots

### 3.1 `config/settings.py` — Highest Fan-In (28 dependents)

This module is imported by 28 files across every layer. It holds runtime constants (`LOT_SIZE`, `STOP_LOSS_PERCENT`, `DATA_DIR`, API keys, etc.) that are consumed everywhere.

**Risk level**: Low. This is intentional — `settings.py` is the canonical source for system-wide constants. The coupling is read-only (no module mutates settings). The only concern is that adding new settings creates implicit coupling, but the `policy_resolver` pattern already handles dynamic config.

### 3.2 `app/engine_runner.py` — Highest Fan-Out (17 import statements)

The engine runner orchestrates the full pipeline: data acquisition → macro context → risk state → signal generation → trade construction → evaluation → tuning. It imports from 17 distinct modules.

**Risk level**: Medium. This is the "God orchestrator" pattern. The fan-out is justified because the runner genuinely needs to wire everything together. However, if the runner grows beyond its current ~1,100 lines, consider extracting a `pipeline_builder` module that handles dependency assembly.

### 3.3 `engine/signal_engine.py` — Pipeline Core (10 imports, ~1,275 lines)

The signal engine is the second-highest centrality node. It imports from `config`, `engine.trading_support` (14 helpers), `macro`, `risk`, `strategy`, and `engine.runtime_metadata`.

**Risk level**: Medium. The `generate_trade()` function is long (~800 lines with nested `_finalize()`). This is not a correctness issue but makes the function harder to review. The nested `_finalize()` closure captures many local variables; extracting it would require passing ~15 parameters explicitly, so the current approach is a reasonable trade-off.

---

## 4. Pipeline Integrity

### 4.1 Signal Formation Funnel

The pipeline follows a strict narrowing pattern:

```
Raw data → Normalization → Analytics features (20 modules)
  → Market-state assembly → Probability scoring (via pluggable predictor factory)
  → Directional voting → Trade strength (0-100) → Confirmation filters
  → Risk overlays (4 layers) → Strike selection → Budget sizing
  → Explainability → Final payload
```

Each stage can only narrow or enrich — no stage can inject data that bypasses an earlier stage. This is verified by the fact that:
- `generate_trade()` is the single entry point for signal production
- All risk overlays receive the same `context` dict and can only reduce/modify the trade
- Strike selection operates on the filtered option chain, not raw input

### 4.2 Overlay Application Order

Risk overlays are applied in a fixed sequence in `engine_runner.py`:
1. Macro/news adjustments (headline sentiment, event proximity)
2. Global risk layer (multi-asset regime, VIX, correlation)
3. Gamma-vol acceleration (gamma exposure × volatility regime interaction)
4. Dealer hedging pressure (net inventory, flow imbalance)
5. Option efficiency (liquidity, spread, volume filters)

This ordering is important: macro context gates first (can block entirely), then risk sizing adjusts, then market-structure filters refine. The order is hardcoded — there is no configuration to reorder overlays — which is appropriate since the semantic dependencies between layers require this sequence.

---

## 5. Research / Production Separation

| Mechanism | Status |
|-----------|--------|
| `config.policy_resolver` bridge | **Only** path from tuning experiments to live parameters |
| `ContextVar`-based shadow mode | Isolates experimental parameters from production signals |
| Promotion lifecycle | shadow → approval → live → rollback with full audit trail |
| Signal evaluation | Records predictions with timestamps; evaluation runs independently after market data arrives |

**Verdict**: Clean separation. Research code (`research/signal_evaluation/`, `tuning/`) cannot directly influence production signals. The `policy_resolver` is the sole bridge, and shadow mode uses `contextvars.ContextVar` to prevent parameter leakage.

---

## 6. Streamlit Safety

`app/streamlit_app.py` (1,942 lines) was reviewed for decision-layer leakage.

| Check | Result |
|-------|--------|
| Signal computation in Streamlit | **None** — all computation happens in `engine_runner.py` |
| Direct model/analytics imports | **None** — Streamlit imports only `engine_runner` and display helpers |
| State mutation of engine objects | **None** — Streamlit uses `st.session_state` only for UI state |
| Parameter overrides in Streamlit | **None** — all tuning goes through `policy_resolver` |

**Verdict**: Streamlit is a pure presentation layer. It calls `run_engine_snapshot()` or `run_preloaded_engine_snapshot()` and displays the returned dict. No trading logic lives in the Streamlit code.

---

## 7. Scalability Considerations

### 7.1 Current Architecture

The engine runs synchronously: one symbol, one snapshot, one thread. This is appropriate for the current use case (Indian options market, single-symbol analysis at a time).

### 7.2 Growth Vectors

| Vector | Current State | Scaling Path |
|--------|--------------|--------------|
| Multi-symbol | Sequential via Streamlit dropdown | The engine is stateless — parallelization would require only an outer loop with concurrent calls to `run_engine_snapshot()` |
| Real-time streaming | Not implemented | Would require replacing `yfinance` polling with a WebSocket feed and converting the pipeline to incremental updates |
| Backtest throughput | Single-threaded `intraday_backtester.py` | `parameter_sweep.py` already supports `ProcessPoolExecutor` for parallel parameter search |
| Data volume | In-memory DataFrames | Adequate for single-symbol option chains (~500-2000 rows). Historical data stored as CSV/Parquet files |

### 7.3 Bottleneck

The primary bottleneck is I/O (data download from yfinance/broker APIs), not computation. The signal engine itself runs in <1 second for a single snapshot.

---

## 8. Issues Resolved During This Audit

### 8.1 Utility Function Duplication (FIXED)

**Before**: `_safe_float` was copy-pasted into 20 modules, `_clip` into 17 modules, `_norm_cdf`/`_norm_pdf` into 2+ modules each. Every copy was semantically identical.

**After**: Created `utils/` package with three focused modules:
- `utils/numerics.py` — `clip()`, `safe_float()`, `safe_div()`, `to_python_number()`
- `utils/math_helpers.py` — `norm_pdf()`, `norm_cdf()`
- `utils/timestamp_helpers.py` — `coerce_timestamp()`

All 20+ modules now import from `utils/` with backward-compatible aliases (`from utils.numerics import clip as _clip`). The `engine/trading_support/common.py` module delegates its existing exports to `utils/` so all downstream callers remain unaffected.

**Impact**: 130 tests pass. ~600 lines of duplicate boilerplate removed.

### 8.2 Streamlit Auto-Refresh (FIXED)

The Streamlit auto-refresh mechanism used `window.parent.location.reload()` which wiped `st.session_state`, requiring the user to re-click "Run Snapshot" after each timed reload.

**Fix**: Added `auto_run` query parameter that survives browser reloads, so the app auto-executes on refresh when auto-refresh is enabled.

---

## 9. Recommendations (Not Yet Implemented)

These are observations, not blockers:

1. **`generate_trade()` length**: At ~800 lines with nested `_finalize()`, this function is the most complex single unit. Consider extracting the risk-overlay application loop and the trade-construction logic into separate functions if further features are added to this path.

2. **`config/settings.py` surface area**: With 28 dependents, any change to settings.py has wide blast radius. Consider splitting into `settings_data.py` (data paths, API keys) and `settings_trade.py` (lot sizes, stop-loss, thresholds) if the file grows.

3. **Instance-method `_safe_float`/`_norm_cdf`**: Two data provider classes (`IciciBreezeOptionChain`, `NseOptionChainDownloader`) define `_safe_float`/`_norm_cdf` as instance methods. These could be refactored to use `utils/` but would require changing `self._safe_float(x)` → `_safe_float(x)` throughout each class.

---

*Generated during holistic codebase audit. All 130 tests passing after changes.*

---
title: "Options Quant Engine"
subtitle: "Developer Guide"
author: "Pramit Dutta"
date: "March 2026"
---

<div class="memo-cover">
<div class="cover-kicker">Developer Reference</div>
<h1 class="cover-title">Options Quant Engine</h1>
<div class="cover-subtitle">Developer Guide</div>
<div class="cover-rule"></div>
<p class="cover-summary">A practical reference for understanding and working with the options_quant_engine codebase — covering package layout, data flow, design conventions, and step-by-step instructions for common development tasks.</p>
<div class="cover-meta">
<div><span>Author</span>Pramit Dutta</div>
<div><span>Organization</span>Quant Engines</div>
<div><span>Date</span>March 2026</div>
<div><span>Document</span>Developer Guide</div>
<div><span>Audience</span>Engineers extending or maintaining the codebase</div>
</div>
</div>

# Developer Guide

A practical reference for understanding and working with the `options_quant_engine` codebase.

---

## Package Layout

```
options_quant_engine/
├── analytics/          # 20 modules — option chain analytics (gamma, greeks, liquidity, volatility)
├── app/                # Streamlit UI + engine orchestrator (engine_runner.py)
├── backtest/           # Intraday backtester, scenario runners, Monte Carlo, PnL engine
├── config/             # 30+ policy files, settings, policy_resolver pattern
├── data/               # Market data ingestion — NSE, ICICI Breeze, Zerodha, yfinance
├── engine/             # Signal engine (generate_trade) + trading_support helpers + pluggable predictors
├── macro/              # Scheduled event risk, macro/news aggregation
├── models/             # Large-move probability, ML move predictor, feature builders
├── news/               # Headline classification, provider adapters, ingestion service
├── research/           # Signal evaluation dataset, evaluator, reporting, decision-policy research
├── risk/               # 4 risk overlays: global, gamma-vol, dealer hedging, option efficiency
├── strategy/           # Strike selection, confirmation filters, exit model, budget optimizer
├── tuning/             # Parameter governance: registry → experiments → search → shadow → promotion
├── utils/              # Centralized numerics, math, timestamp helpers
├── tests/              # pytest suite (27 test files, 130+ tests)
├── scripts/            # CLI tools (signal evaluation reports, outcome updates)
└── documentation/      # System monograph, academic papers, tuning memos, audit reports
```

## Data Flow

```
Data providers (NSE/ICICI/Zerodha/yfinance)
    ↓
data/ (download, normalize, validate)
    ↓
analytics/ (gamma exposure, greeks, volatility surface, flow metrics)
    ↓
engine/signal_engine.py::generate_trade()
    ├── strategy/ (direction voting, confirmation, strike selection, exit model)
    ├── macro/ (event risk, headline aggregation)
    └── risk/ (4 overlays applied in sequence)
    ↓
Trade payload (TRADE / WATCHLIST / NO_TRADE / BUDGET_FAIL)
    ↓
app/engine_runner.py (orchestration + signal evaluation logging)
    ↓
app/streamlit_app.py (presentation) or main.py (terminal)
```

## Key Conventions

### Policy Resolver Pattern

All tunable parameters flow through `config.policy_resolver`:

```python
from config.policy_resolver import resolve_dataclass_config

@dataclass(frozen=True)
class MyPolicyConfig:
    threshold: float = 0.5
    enabled: bool = True

def get_my_policy_config() -> MyPolicyConfig:
    return resolve_dataclass_config(MyPolicyConfig, "my_policy")
```

This pattern is used by every module that needs configurable parameters. The resolver checks for active tuning packs (via `tuning/runtime.py`) before falling back to dataclass defaults.

### Utils Package

Common numeric operations live in `utils/`:

```python
from utils.numerics import clip, safe_float, safe_div, to_python_number
from utils.math_helpers import norm_pdf, norm_cdf
from utils.timestamp_helpers import coerce_timestamp
```

When a module needs these internally with underscore-prefixed names (for backward compatibility), use aliased imports:

```python
from utils.numerics import clip as _clip, safe_float as _safe_float
```

**Do not** define local copies of these functions in new modules.

### Risk Overlay Ordering

Risk overlays are applied in `engine_runner.py` in this fixed sequence:

1. **Macro/news** — headline sentiment, event proximity (can block entirely)
2. **Global risk** — multi-asset regime, VIX, correlation
3. **Gamma-vol acceleration** — gamma exposure × volatility regime interaction
4. **Dealer hedging pressure** — net inventory, flow imbalance
5. **Option efficiency** — liquidity, spread, volume filters

This order matters: macro gates first, then risk sizing, then market-structure refinement.

### Test Structure

Tests use pytest and live in `tests/`. Run the full suite:

```bash
python -m pytest tests/ -x -q
```

Each risk overlay has both a unit test (`test_*_layer.py`) and a scenario test (`test_*_scenarios.py`). Scenario tests use JSON fixtures from `config/*_scenarios.json`.

## Adding a New Risk Overlay

1. Create feature, regime, model, and layer modules in `risk/`:
   - `risk/my_overlay_features.py` — feature extraction
   - `risk/my_overlay_regime.py` — regime classification
   - `risk/my_overlay_models.py` — dataclass for state
   - `risk/my_overlay_layer.py` — public `build_my_overlay_state()` function

2. Create a policy config in `config/my_overlay_policy.py` using the resolver pattern.

3. Re-export the builder from `risk/__init__.py`.

4. Wire the call into `app/engine_runner.py` at the appropriate position in the overlay sequence.

5. Add tests and scenario JSON.

## Adding a New Analytics Module

1. Create `analytics/my_module.py` with a public function that takes an option chain DataFrame and returns a dict of features.

2. Wire the call into `engine/signal_engine.py` or `app/engine_runner.py` depending on where the features are consumed.

3. If the module needs `safe_float`, `clip`, etc., import from `utils/`.

## Tuning Workflow

The parameter governance lifecycle:

```
1. Define parameter surface in config/*_policy.py (dataclass defaults)
2. Register in tuning/registry.py
3. Run experiments via tuning/experiments.py
4. Search parameter space via tuning/search.py
5. Shadow-test candidates via tuning/shadow.py
6. Promote to production via tuning/promotion.py
7. Monitor and optionally rollback
```

Research artifacts (candidate packs, ledgers, reports) are stored in `research/parameter_tuning/`.

## Common Tasks

| Task | Command |
|------|---------|
| Run engine (terminal) | `python main.py` |
| Run Streamlit UI | `streamlit run app/streamlit_app.py` |
| Run tests | `python -m pytest tests/ -x -q` |
| Refresh signal outcomes | `python scripts/update_signal_outcomes.py` |
| Generate research report | `python scripts/signal_evaluation_report.py` |
| Run intraday backtest | See `backtest/intraday_backtester.py` |
| Run parameter sweep | See `backtest/parameter_sweep.py` |

# EV-Based Sizing & Regime-Switching Policy — Research Module

**Author:** Pramit Dutta  
**Organization:** Quant Engines  
**Status:** Research modules under `research/ml_evaluation/`; EV-based sizing is also available as an optional production prediction method (`ev_sizing`) via the pluggable predictor architecture  

---

## Overview

Two self-contained research modules that extend the existing signal-evaluation
framework:

| Module | Purpose |
|--------|---------|
| **EV-based sizing** | Replaces confidence-only sizing with expected-value estimates derived from historical conditional return tables. |
| **Regime-switching policy** | Selects the optimal decision policy per-signal based on the prevailing market regime (gamma, volatility, macro). |

---

## Module Map

```
research/ml_evaluation/ev_and_regime_policy/
├── __init__.py                     # Package marker
├── conditional_return_tables.py    # Conditional return table builder
├── ev_sizing_model.py              # EV computation & sizing logic
├── ev_evaluation.py                # EV sizing evaluation runner
├── regime_switching_policy.py      # Regime-switching policy layer
├── regime_policy_evaluation.py     # Regime policy evaluation runner
├── runner.py                       # Combined entry point (runs both)
└── README.md                       # This file
```

---

## Part 1 — EV-Based Sizing

### Concept

Instead of mapping a single ML confidence score to a sizing multiplier, we
estimate the **expected value (EV)** of each signal using historical conditional
lookup tables:

$$
\text{EV} = P(\text{win}) \times \mathbb{E}[\text{gain} \mid \text{win}] \;-\; (1 - P(\text{win})) \times |\mathbb{E}[\text{loss} \mid \text{loss}]|
$$

### Pipeline

1. **Conditional Return Table** (`conditional_return_tables.py`)
   - Group historical signals by *rank bucket × confidence bucket × regime*
   - Compute per-cell: p_win, mean_win, mean_loss, n, std_return
   - Hierarchical back-off: 3-way cell → rank-only parent → global
   - Bayesian smoothing (default weight 30 %) towards parent statistics
   - Minimum sample threshold: 10 signals per cell

2. **EV Scoring** (`ev_sizing_model.py`)
   - For each live signal, look up its conditional cell
   - Compute raw EV + reliability score
   - Normalize to [0, 1] using 10th/90th percentile bounds
   - Map to sizing multiplier via EV bucket

3. **Evaluation** (`ev_evaluation.py`)
   - Compares five strategies: baseline (all signals), rank-filtered unsized,
     rank-filtered confidence-sized, rank-filtered EV-sized, all-EV-sized
   - Metrics: hit rate, avg return, cumulative return, max drawdown, Sharpe proxy
   - Yearly stability analysis
   - Chart outputs: comparison bar charts, EV bucket breakdown, cumulative equity
   - Report outputs: Markdown + JSON + CSV

### Key Assumptions

- EV estimation assumes stationarity within regime cells — regime transitions
  are **not** modeled dynamically.
- Smoothing weight (30 %) is a prior; sensitivity should be tested.
- The sizing map is piecewise linear by design (easy to override).

---

## Part 2 — Regime-Switching Policy

### Concept

Rather than applying a single static policy (e.g., dual_threshold or rank_gate)
to all signals, the regime layer **selects** which policy to use per-signal
based on the market's current gamma, volatility, and macro regime.

### Policy Candidates

| Policy | Description |
|--------|-------------|
| `dual_threshold` | Existing: requires both rank and confidence gates |
| `rank_gate_20` | Pass if rank ≥ 20th percentile |
| `rank_gate_30` | Pass if rank ≥ 30th percentile |
| `rank_gate_40` | Pass if rank ≥ 40th percentile |
| `rank_gate_30_ev` | Rank gate + EV-based sizing multiplier |

### Regime Key Resolution

Keys are generated from most-specific to least-specific:

```
MACRO_NEUTRAL+POSITIVE_GAMMA+LOW_VOL   ← 3-way (if a mapping exists)
MACRO_NEUTRAL+POSITIVE_GAMMA           ← 2-way
POSITIVE_GAMMA                         ← single dimension
<fallback>                             ← default policy
```

### Search Space

Eight pre-defined regime-to-policy mappings are evaluated
(`generate_regime_map_variants()`):

1. **static_dual_threshold** — baseline, same policy for every signal
2. **static_rank_gate_30** — baseline rank gate
3. **static_rank_gate_40** — tighter baseline rank gate
4. **default_gamma_driven** — gamma-aware switching
5. **aggressive_risk_on** — looser gates in favorable regimes
6. **defensive_gamma_vol** — tightens in negative gamma + high vol
7. **ev_favorable_regime** — uses EV sizing where regimes are favorable
8. **gamma_only_switch** — simplest dynamic: only gamma dimension
9. **vol_aware_gamma** — gamma primary, vol secondary

### Evaluation (`regime_policy_evaluation.py`)

- Applies each variant to the full backtest dataset
- Metrics per variant: hit rate, avg return, cumulative return, drawdown, Sharpe
- Regime × policy heatmap (hit rate color-coded)
- Yearly stability per variant
- Identifies best variant by Sharpe proxy

---

## How to Run

### Combined (recommended)

```bash
cd /path/to/options_quant_engine
python -m research.ml_evaluation.ev_and_regime_policy.runner
```

### Individual modules

```python
from research.ml_evaluation.ev_and_regime_policy.ev_evaluation import run_ev_sizing_evaluation
ev_results = run_ev_sizing_evaluation()

from research.ml_evaluation.ev_and_regime_policy.regime_policy_evaluation import run_regime_policy_evaluation
regime_results = run_regime_policy_evaluation()
```

### Output artifacts

After running, the directory will contain:

| File | Description |
|------|-------------|
| `conditional_return_table.json` / `.csv` | Raw lookup table |
| `ev_sizing_report.json` / `.md` | EV evaluation results |
| `regime_switching_report.json` / `.md` | Regime evaluation results |
| `regime_policy_comparison.csv` | Search results table |
| `regime_policy_heatmap.csv` | Regime × policy cross-tab |
| `combined_research_report.json` | Combined summary |
| `*.png` | Charts |

---

## Research Questions Addressed

1. **Does EV-based sizing outperform confidence-only sizing?**
   → Compare `rank_filtered_ev_sized` vs `rank_filtered_confidence_sized` in
   `ev_sizing_report.json`.

2. **Does regime-switching improve over static policies?**
   → Compare dynamic variants vs static baselines in
   `regime_switching_report.json` (best variant by Sharpe proxy).

3. **Is the improvement robust across years?**
   → Check yearly stability tables in both reports.

---

## Safety & Guardrails

- **Production default unchanged.** The `blended` prediction method remains the default.
- **EV sizing available as optional predictor.** Set `OQE_PREDICTION_METHOD=ev_sizing` to activate the EV-based sizing predictor (`engine/predictors/ev_sizing_predictor.py`), which uses the conditional return tables and EV computation from this research module.
- **Research evaluation modules are standalone.** All files under `research/ml_evaluation/` are self-contained evaluation runners.
- **Toggleable.** Nothing runs unless explicitly invoked or configured.
- **Reversible.** Delete this directory to remove the research modules. The predictor can be deregistered by removing the factory entry.
- **No external network calls.** All data comes from local backtest dataset.
- **Deterministic.** Same input data produces same output (no random seeds).

---

## Dependencies

Uses only packages already present in `requirements.txt`:

- pandas, numpy, scipy, scikit-learn
- matplotlib (Agg backend — no display needed)

Internal imports from research layer only:

- `research.decision_policy.policy_config`
- `research.decision_policy.policy_definitions`
- `research.ml_models.ml_config`
- `research.ml_models.ml_inference` (lazy, only if ML columns are missing)

---

*Last updated: auto-generated by runner*

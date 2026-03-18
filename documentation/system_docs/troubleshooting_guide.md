---
title: "Options Quant Engine"
subtitle: "Troubleshooting Guide"
author: "Pramit Dutta"
date: "March 2026"
---

<div class="memo-cover">
<div class="cover-kicker">Operational Reference</div>
<h1 class="cover-title">Options Quant Engine</h1>
<div class="cover-subtitle">Troubleshooting Guide</div>
<div class="cover-rule"></div>
<p class="cover-summary">Diagnostic reference covering common issues and their solutions — import errors, data provider problems, Streamlit issues, test failures, tuning/governance issues, and performance bottlenecks.</p>
<div class="cover-meta">
<div><span>Author</span>Pramit Dutta</div>
<div><span>Organization</span>Quant Engines</div>
<div><span>Date</span>March 2026</div>
<div><span>Document</span>Troubleshooting Guide</div>
<div><span>Audience</span>Developers and operators diagnosing runtime issues</div>
</div>
</div>

# Troubleshooting Guide

Common issues and their solutions.

---

## Import Errors

### `ModuleNotFoundError: No module named 'utils'`

**Cause**: Running from a directory other than the project root, or the virtual environment is not activated.

**Fix**:
```bash
cd /path/to/options_quant_engine
source .venv/bin/activate
python main.py
```

### `ImportError: cannot import name 'X' from 'config.settings'`

**Cause**: A new setting was added to `config/settings.py` but is missing from your local `.env` file.

**Fix**: Check `config/settings.py` for the expected environment variable and add it to your `.env`.

---

## Data Provider Issues

### `No data returned from provider`

**Cause**: API credentials are missing, expired, or the market is closed.

**Fix**:
1. Verify credentials in `.env` match your broker account
2. Check if the market is open (NSE hours: 9:15 AM – 3:30 PM IST)
3. Try a different data source via the `--source` flag or settings

### `yfinance` returning empty DataFrames

**Cause**: yfinance rate limiting or symbol format mismatch.

**Fix**: The engine normalizes symbols internally. If you see issues, check `data/spot_downloader.py::normalize_underlying_symbol()` for the expected format.

---

## Streamlit Issues

### Auto-refresh requires re-clicking "Run Snapshot"

**Status**: Fixed. The auto-refresh now uses a query parameter (`auto_run=1`) to survive browser reloads. If this regresses, check `app/streamlit_app.py::_inject_autorefresh()` and `main()` for the `auto_run_triggered` logic.

### Session state lost on refresh

**Cause**: Streamlit's `st.session_state` is wiped on full page reloads. The engine uses query parameters for state that must survive reloads.

### Streamlit crashes with `KeyError`

**Cause**: Usually a missing key in the trade result dict. The Streamlit app accesses result fields with `.get()` to be safe, but if a new field is expected, ensure `generate_trade()` always returns it.

---

## Test Failures

### `IndentationError` or `SyntaxError` in risk modules

**Cause**: Incomplete edit during utils extraction. Verify the module's import section is clean:

```python
from utils.numerics import clip as _clip, safe_float as _safe_float
```

No leftover function body fragments should remain below the import.

### Tests pass locally but fail in CI

**Cause**: Python version mismatch. The engine is developed on Python 3.9.6 (venv) but the system may have a different version. Tests should work on 3.9+.

---

## Tuning / Governance

### `No active pack found`

**Cause**: No parameter pack has been promoted to production. The system falls back to dataclass defaults, which is the intended behavior for a fresh installation.

### Shadow mode not applying experimental parameters

**Cause**: The `ContextVar` mechanism requires the shadow context to be entered before calling the signal engine. Check `tuning/shadow.py` for proper context manager usage.

---

## Performance

### Engine snapshot takes >10 seconds

**Cause**: Almost always data download latency (yfinance, broker APIs). The signal computation itself takes <1 second.

**Fix**: Use replay mode for development/testing to avoid live data fetches. See `data/replay_loader.py`.

### Backtest running slowly

**Fix**: Use `backtest/parameter_sweep.py` with `ProcessPoolExecutor` for parallel parameter search. Single-run backtests are inherently sequential.

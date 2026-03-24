"""
Module: volatility_regime.py

Purpose:
    Compute volatility regime analytics used by downstream signal and risk layers.

Role in the System:
    Part of the analytics layer that transforms raw option-chain and market snapshots into interpretable features.

Key Outputs:
    Structured features, regime labels, and market-state diagnostics derived from market data.

Downstream Usage:
    Consumed by market-state assembly, probability estimation, risk overlays, and research diagnostics.
"""

import pandas as pd
import numpy as np

from config.analytics_feature_policy import get_volatility_regime_policy_config
from utils.regime_normalization import normalize_iv_decimal


def compute_realized_volatility(option_chain):

    """
    Purpose:
        Compute realized volatility from the supplied inputs.
    
    Context:
        Public function within the analytics layer. It exposes a reusable step in this module's workflow.
    
    Inputs:
        option_chain (Any): Input associated with option chain.
    
    Returns:
        Any: Computed value returned by the helper.
    
    Notes:
        Keeping this step explicit makes it easier to audit how the final feature, score, or trade decision was assembled.
    """
    if option_chain.empty:
        return 0

    # This module is invoked on single option-chain snapshots, so using
    # cross-strike premium pct-changes is not a valid time-series volatility
    # estimate. We instead infer the current volatility level from normalized
    # implied vol observations.
    iv_col = "IV" if "IV" in option_chain.columns else "impliedVolatility"
    iv_series = pd.to_numeric(option_chain.get(iv_col), errors="coerce")
    iv_series = iv_series.replace([np.inf, -np.inf], np.nan).dropna()
    if iv_series.empty:
        return 0

    normalized = iv_series.apply(lambda value: normalize_iv_decimal(value, default=np.nan))
    normalized = pd.to_numeric(normalized, errors="coerce")
    normalized = normalized.replace([np.inf, -np.inf], np.nan).dropna()
    normalized = normalized[normalized > 0]
    if normalized.empty:
        return 0

    # Median is robust to stale/deep-OTM tails and gives a stable per-snapshot
    # volatility level in decimal units.
    return float(normalized.median())


def detect_volatility_regime(option_chain):
    """
    Purpose:
        Detect the volatility regime from the available market signals.

    Context:
        Function inside the `volatility regime` module. The module sits in the analytics layer that turns option-chain and market-structure data into tradable features.

    Inputs:
        option_chain (Any): Option-chain snapshot in dataframe form.

    Returns:
        str | Any: Classification label returned by the current logic.

    Notes:
        Part of the module API used by downstream runtime, research, backtest, or governance workflows.
    """
    cfg = get_volatility_regime_policy_config()

    vol = compute_realized_volatility(option_chain)

    if vol < cfg.low_vol_threshold:
        return "LOW_VOL"

    if vol < cfg.normal_vol_threshold:
        return "NORMAL_VOL"

    return "VOL_EXPANSION"

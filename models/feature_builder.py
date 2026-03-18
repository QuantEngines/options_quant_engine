"""
Module: feature_builder.py

Purpose:
    Implement feature builder modeling logic used by predictive or heuristic components.

Role in the System:
    Part of the modeling layer that builds statistical features and predictive estimates.

Key Outputs:
    Model-ready feature sets, fitted estimators, or predictive outputs.

Downstream Usage:
    Consumed by analytics, the probability stack, and research workflows.
"""

import numpy as np

from models.expanded_feature_builder import (
    FEATURE_NAMES as EXPANDED_FEATURE_NAMES,
    N_FEATURES as N_EXPANDED_FEATURES,
    extract_features as _extract_expanded,
)


# Check if a registry ML model is configured (replaces the old v2 joblib gate).
_REGISTRY_MODEL_AVAILABLE = None

def _check_registry_model():
    global _REGISTRY_MODEL_AVAILABLE
    if _REGISTRY_MODEL_AVAILABLE is not None:
        return _REGISTRY_MODEL_AVAILABLE
    try:
        from config import settings as _settings
        active = getattr(_settings, "ACTIVE_MODEL", None)
        if not active:
            _REGISTRY_MODEL_AVAILABLE = False
            return False
        from pathlib import Path
        model_path = Path(__file__).parent.parent / "models_store" / "registry" / active / "model.joblib"
        _REGISTRY_MODEL_AVAILABLE = model_path.exists()
    except Exception:
        _REGISTRY_MODEL_AVAILABLE = False
    return _REGISTRY_MODEL_AVAILABLE


def build_features(
    option_chain,
    spot=None,
    gamma_regime=None,
    final_flow_signal=None,
    vol_regime=None,
    hedging_bias=None,
    spot_vs_flip=None,
    vacuum_state=None,
    atm_iv=None,
    # Extended kwargs for 33-feature v2 model
    **extra_context,
):
    """
    Purpose:
        Build the features used by downstream components.
    
    Context:
        Public function within the modeling layer. It exposes a reusable step in this module's workflow.
    
    Inputs:
        option_chain (Any): Input associated with option chain.
        spot (Any): Input associated with spot.
        gamma_regime (Any): Input associated with gamma regime.
        final_flow_signal (Any): Input associated with final flow signal.
        vol_regime (Any): Input associated with vol regime.
        hedging_bias (Any): Input associated with hedging bias.
        spot_vs_flip (Any): Input associated with spot vs flip.
        vacuum_state (Any): Structured state payload for vacuum.
        atm_iv (Any): Input associated with ATM IV.
    
    Returns:
        Any: Computed value returned by the helper.
    
    Notes:
        The helper keeps the surrounding module readable without changing runtime behavior.
    """
    gamma_sign = 0.0
    if gamma_regime in ["NEGATIVE_GAMMA", "SHORT_GAMMA_ZONE"]:
        gamma_sign = 1.0
    elif gamma_regime in ["POSITIVE_GAMMA", "LONG_GAMMA_ZONE"]:
        gamma_sign = -0.5
    elif gamma_regime == "NEUTRAL_GAMMA":
        gamma_sign = 0.0

    flow_bias = 0.0
    if final_flow_signal == "BULLISH_FLOW":
        flow_bias = 1.0
    elif final_flow_signal == "BEARISH_FLOW":
        flow_bias = -1.0

    vol_expansion = 1.0 if vol_regime == "VOL_EXPANSION" else 0.0

    hedging_bias_score = 0.0
    if hedging_bias == "UPSIDE_ACCELERATION":
        hedging_bias_score = 1.0
    elif hedging_bias == "DOWNSIDE_ACCELERATION":
        hedging_bias_score = -1.0

    spot_flip_score = 0.0
    if spot_vs_flip == "ABOVE_FLIP":
        spot_flip_score = 1.0
    elif spot_vs_flip == "BELOW_FLIP":
        spot_flip_score = -1.0

    vacuum_score = 1.0 if vacuum_state == "BREAKOUT_ZONE" else 0.0
    iv_level = float(atm_iv) / 100.0 if atm_iv is not None else 0.0

    # If a registry ML model is active, build the 33-feature vector from context
    if _check_registry_model() and extra_context:
        row = {
            "gamma_regime": gamma_regime,
            "final_flow_signal": final_flow_signal,
            "volatility_regime": vol_regime,
            "dealer_hedging_bias": hedging_bias,
            "spot_vs_flip": spot_vs_flip,
            "liquidity_vacuum_state": vacuum_state,
            "atm_iv_scaled": iv_level,
            **extra_context,
        }
        expanded = _extract_expanded(row)
        return expanded.reshape(1, -1)

    features = np.array([
        gamma_sign,
        flow_bias,
        vol_expansion,
        hedging_bias_score,
        spot_flip_score,
        vacuum_score,
        iv_level
    ], dtype=float)

    return features.reshape(1, -1)

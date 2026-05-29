"""
Module: enhanced_strike_scoring.py

Purpose:
    Compute institutional-grade strike scoring factors that complement the
    base strike ranking model.

Role in the System:
    Part of the strategy layer. Sits alongside strike_selector.py to enrich
    each candidate strike with market-microstructure factors and tradeability
    diagnostics.

Key Outputs:
    Per-strike scores for liquidity gravity, gamma magnetism, dealer hedging
    pressure, volatility convexity, and premium efficiency, plus a composite
    enhanced_strike_score and tradeability flags.

Downstream Usage:
    Consumed by strike_selector.py (merged into ranked_strike_candidates) and
    displayed by the Streamlit operator interface.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from config.strike_selection_policy import (
    STRIKE_SELECTION_SCORE_CONFIG,
    get_strike_selection_score_config,
)
from utils.numerics import clip, safe_float
from utils.regime_normalization import normalize_iv_decimal


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------

def _policy_config(policy_config: dict[str, Any] | None = None) -> dict[str, Any]:
    return policy_config if isinstance(policy_config, dict) else get_strike_selection_score_config()


def _cfg_float(policy_config: dict[str, Any], key: str) -> float:
    return safe_float(policy_config.get(key), STRIKE_SELECTION_SCORE_CONFIG[key])


def _enhanced_score_weights(policy_config: dict[str, Any]) -> dict[str, float]:
    return {
        "liquidity": _cfg_float(policy_config, "enhanced_weight_liquidity"),
        "gamma_magnetism": _cfg_float(policy_config, "enhanced_weight_gamma_magnetism"),
        "dealer_pressure": _cfg_float(policy_config, "enhanced_weight_dealer_pressure"),
        "volatility_convexity": _cfg_float(policy_config, "enhanced_weight_volatility_convexity"),
        "premium_efficiency": _cfg_float(policy_config, "enhanced_weight_premium_efficiency"),
    }


def _payoff_weights(policy_config: dict[str, Any]) -> dict[str, float]:
    return {
        "premium_efficiency": _cfg_float(policy_config, "payoff_weight_premium_efficiency"),
        "delta_alignment": _cfg_float(policy_config, "payoff_weight_delta_alignment"),
        "liquidity_score": _cfg_float(policy_config, "payoff_weight_liquidity_score"),
        "distance_to_target": _cfg_float(policy_config, "payoff_weight_distance_to_target"),
        "iv_efficiency": _cfg_float(policy_config, "payoff_weight_iv_efficiency"),
    }


def _expected_move_from_policy(
    *,
    spot: float,
    atm_iv: float | None,
    days_to_expiry: float | None,
    policy_config: dict[str, Any],
) -> float:
    iv = normalize_iv_decimal(atm_iv, default=_cfg_float(policy_config, "expected_move_default_iv"))
    dte = max(
        safe_float(days_to_expiry, _cfg_float(policy_config, "expected_move_default_dte")),
        _cfg_float(policy_config, "expected_move_min_dte"),
    )
    return float(spot) * iv * math.sqrt(dte / 365.0)


ENHANCED_SCORE_WEIGHTS = {
    "liquidity": STRIKE_SELECTION_SCORE_CONFIG["enhanced_weight_liquidity"],
    "gamma_magnetism": STRIKE_SELECTION_SCORE_CONFIG["enhanced_weight_gamma_magnetism"],
    "dealer_pressure": STRIKE_SELECTION_SCORE_CONFIG["enhanced_weight_dealer_pressure"],
    "volatility_convexity": STRIKE_SELECTION_SCORE_CONFIG["enhanced_weight_volatility_convexity"],
    "premium_efficiency": STRIKE_SELECTION_SCORE_CONFIG["enhanced_weight_premium_efficiency"],
}


# ---------------------------------------------------------------------------
# 1. Liquidity Gravity
# ---------------------------------------------------------------------------

def _rank_normalize(series: pd.Series) -> pd.Series:
    """Rank-normalize a series to [0, 1] using average rank."""
    if series.empty:
        return pd.Series(0.5, index=series.index)

    values = pd.to_numeric(series, errors="coerce").fillna(0.0).to_numpy(dtype=float, copy=False)
    n = values.size
    if n <= 1:
        return pd.Series(0.5, index=series.index)

    vmin = float(values.min())
    vmax = float(values.max())
    if abs(vmax - vmin) < 1e-12:
        return pd.Series(0.5, index=series.index)

    order = np.argsort(values, kind="mergesort")
    sorted_vals = values[order]
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)

    # Assign average ranks for tie groups to preserve previous behavior.
    tie_bounds = np.flatnonzero(
        np.concatenate(([True], sorted_vals[1:] != sorted_vals[:-1], [True]))
    )
    for idx in range(len(tie_bounds) - 1):
        start = tie_bounds[idx]
        end = tie_bounds[idx + 1]
        if end - start > 1:
            avg_rank = (start + 1 + end) / 2.0
            ranks[order[start:end]] = avg_rank

    normalized = (ranks - 1.0) / (n - 1.0)
    return pd.Series(normalized, index=series.index)


def _safe_series(rows: pd.DataFrame, *col_names) -> pd.Series:
    """Return the first matching column as a numeric Series, or zeros."""
    for name in col_names:
        if name in rows.columns:
            return pd.to_numeric(rows[name], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=rows.index)


def compute_liquidity_gravity(
    rows: pd.DataFrame,
    *,
    policy_config: dict[str, Any] | None = None,
) -> pd.Series:
    policy_config = _policy_config(policy_config)
    volume = _safe_series(rows, "_normalized_volume", "totalTradedVolume", "VOLUME")
    oi = _safe_series(rows, "_normalized_open_interest", "openInterest", "OPEN_INT")
    oi_change = _safe_series(rows, "changeinOI", "CHANGE_IN_OI").abs()

    vol_rank = _rank_normalize(volume)
    oi_rank = _rank_normalize(oi)
    oi_change_rank = _rank_normalize(oi_change)

    return (
        _cfg_float(policy_config, "enhanced_liquidity_weight_volume") * vol_rank
        + _cfg_float(policy_config, "enhanced_liquidity_weight_open_interest") * oi_rank
        + _cfg_float(policy_config, "enhanced_liquidity_weight_oi_change") * oi_change_rank
    ).round(4)


# ---------------------------------------------------------------------------
# 2. Gamma Magnetism
# ---------------------------------------------------------------------------

def compute_gamma_magnetism(
    strikes: pd.Series,
    gamma_clusters: list | None,
) -> pd.Series:
    if not gamma_clusters:
        return pd.Series(0.5, index=strikes.index)

    strikes_f = strikes.astype(float)
    cluster_arr = np.array([float(c) for c in gamma_clusters if c is not None])
    if len(cluster_arr) == 0:
        return pd.Series(0.5, index=strikes.index)

    # Distance to nearest gamma cluster
    distances = np.abs(strikes_f.values[:, None] - cluster_arr[None, :]).min(axis=1)
    raw = 1.0 / (1.0 + distances)

    # Normalize to [0, 1]
    rmin, rmax = raw.min(), raw.max()
    if rmax - rmin < 1e-9:
        return pd.Series(0.5, index=strikes.index)
    normalized = (raw - rmin) / (rmax - rmin)
    return pd.Series(np.round(normalized, 4), index=strikes.index)


# ---------------------------------------------------------------------------
# 3. Dealer Hedging Pressure
# ---------------------------------------------------------------------------

def _gamma_regime_scores(policy_config: dict[str, Any]) -> dict[str, float]:
    return {
        "SHORT_GAMMA_ZONE": _cfg_float(policy_config, "dealer_gamma_regime_score_short_gamma_zone"),
        "NEGATIVE_GAMMA": _cfg_float(policy_config, "dealer_gamma_regime_score_negative_gamma"),
        "NEUTRAL_GAMMA": _cfg_float(policy_config, "dealer_gamma_regime_score_neutral_gamma"),
        "LONG_GAMMA_ZONE": _cfg_float(policy_config, "dealer_gamma_regime_score_long_gamma_zone"),
        "POSITIVE_GAMMA": _cfg_float(policy_config, "dealer_gamma_regime_score_positive_gamma"),
    }


def _hedging_bias_scores(policy_config: dict[str, Any]) -> dict[str, float]:
    return {
        "DOWNSIDE_HEDGING_ACCELERATION": _cfg_float(
            policy_config, "dealer_hedging_bias_score_downside_acceleration"
        ),
        "UPSIDE_HEDGING_ACCELERATION": _cfg_float(policy_config, "dealer_hedging_bias_score_upside_acceleration"),
        "TWO_SIDED_INSTABILITY": _cfg_float(policy_config, "dealer_hedging_bias_score_two_sided_instability"),
        "PINNING_DOMINANT": _cfg_float(policy_config, "dealer_hedging_bias_score_pinning_dominant"),
        "DOWNSIDE_PINNING": _cfg_float(policy_config, "dealer_hedging_bias_score_downside_pinning"),
        "UPSIDE_PINNING": _cfg_float(policy_config, "dealer_hedging_bias_score_upside_pinning"),
        "NEUTRAL": _cfg_float(policy_config, "dealer_hedging_bias_score_neutral"),
    }


def _flip_context_scores(policy_config: dict[str, Any]) -> dict[str, float]:
    return {
        "AT_FLIP": _cfg_float(policy_config, "dealer_flip_context_score_at_flip"),
        "ABOVE_FLIP": _cfg_float(policy_config, "dealer_flip_context_score_above_flip"),
        "BELOW_FLIP": _cfg_float(policy_config, "dealer_flip_context_score_below_flip"),
    }


def compute_dealer_pressure(
    strikes: pd.Series,
    *,
    gamma_regime: str | None = None,
    spot_vs_flip: str | None = None,
    dealer_hedging_bias: str | None = None,
    gamma_flip_distance_pct: float | None = None,
    dealer_gamma_exposure: float | None = None,
    policy_config: dict[str, Any] | None = None,
) -> pd.Series:
    policy_config = _policy_config(policy_config)
    regime_score = _gamma_regime_scores(policy_config).get(
        str(gamma_regime or "").upper().strip(), 0.5
    )

    # Flip proximity: higher when closer to flip level.
    flip_dist = abs(safe_float(gamma_flip_distance_pct, _cfg_float(policy_config, "dealer_flip_proximity_default_pct")))
    flip_cap = max(_cfg_float(policy_config, "dealer_flip_proximity_cap_pct"), 1e-6)
    flip_proximity = clip(1.0 - min(flip_dist, flip_cap) / flip_cap, 0.0, 1.0)

    # Spot-vs-flip context is directional instability information.
    flip_context = _flip_context_scores(policy_config).get(
        str(spot_vs_flip or "").upper().strip(),
        _cfg_float(policy_config, "dealer_flip_context_score_default"),
    )

    # Hedging bias amplification
    bias_score = _hedging_bias_scores(policy_config).get(
        str(dealer_hedging_bias or "").upper().strip(), 0.5
    )

    # Convert raw gamma exposure to bounded intensity; only magnitude matters.
    gex_value = abs(safe_float(dealer_gamma_exposure, 0.0))
    gex_scale = max(_cfg_float(policy_config, "dealer_gex_log_scale"), 1e-6)
    gex_intensity = clip(math.log1p(gex_value) / gex_scale, 0.0, 1.0)

    # Combine components
    base_pressure = (
        _cfg_float(policy_config, "dealer_pressure_weight_regime") * regime_score
        + _cfg_float(policy_config, "dealer_pressure_weight_flip_proximity") * flip_proximity
        + _cfg_float(policy_config, "dealer_pressure_weight_bias") * bias_score
        + _cfg_float(policy_config, "dealer_pressure_weight_flip_context") * flip_context
        + _cfg_float(policy_config, "dealer_pressure_weight_gex") * gex_intensity
    )

    return pd.Series(round(clip(base_pressure, 0.0, 1.0), 4), index=strikes.index)


# ---------------------------------------------------------------------------
# 4. Volatility Convexity
# ---------------------------------------------------------------------------

def compute_volatility_convexity(rows: pd.DataFrame) -> pd.Series:
    gamma = _safe_series(rows, "GAMMA")
    vega = _safe_series(rows, "VEGA")

    raw = (gamma * vega).abs()

    rmin, rmax = raw.min(), raw.max()
    if rmax - rmin < 1e-12:
        return pd.Series(0.5, index=rows.index)
    normalized = (raw - rmin) / (rmax - rmin)
    return normalized.round(4)


# ---------------------------------------------------------------------------
# 5. Premium Efficiency
# ---------------------------------------------------------------------------

def compute_premium_efficiency(
    rows: pd.DataFrame,
    *,
    spot: float,
    atm_iv: float | None,
    days_to_expiry: float | None,
    expected_move: float | None = None,
    policy_config: dict[str, Any] | None = None,
) -> pd.Series:
    policy_config = _policy_config(policy_config)
    # Guard: validate spot is numeric and positive
    spot = safe_float(spot, None)
    if spot is None or spot <= 0:
        # Cannot compute premium efficiency without valid spot
        return pd.Series(0.5, index=rows.index)
    
    if expected_move is None:
        expected_move = _expected_move_from_policy(
            spot=float(spot),
            atm_iv=atm_iv,
            days_to_expiry=days_to_expiry,
            policy_config=policy_config,
        )

    premium = _safe_series(rows, "_normalized_last_price", "lastPrice", "LAST_PRICE")
    min_premium = _cfg_float(policy_config, "premium_efficiency_min_premium")
    safe_premium = premium.where(premium > min_premium, np.nan)
    raw = expected_move / safe_premium

    valid = raw.dropna()
    if valid.empty:
        return pd.Series(0.0, index=rows.index)

    rmin, rmax = valid.min(), valid.max()
    if rmax - rmin < 1e-9:
        flat = pd.Series(0.5, index=rows.index)
        flat[raw.isna()] = 0.0
        return flat
    normalized = (raw - rmin) / (rmax - rmin)
    return normalized.fillna(0.0).clip(lower=0.0, upper=1.0).round(4)


# ---------------------------------------------------------------------------
# 6. Payoff Efficiency — composite strike efficiency for execution quality
# ---------------------------------------------------------------------------

def compute_payoff_efficiency(
    rows: pd.DataFrame,
    *,
    spot: float,
    direction: str,
    atm_iv: float | None,
    days_to_expiry: float | None,
    support_wall: float | None = None,
    resistance_wall: float | None = None,
    expected_move: float | None = None,
    policy_config: dict[str, Any] | None = None,
) -> tuple[pd.Series, dict[str, pd.Series]]:
    """Compute per-strike payoff efficiency and sub-component scores.

    Returns
    -------
    payoff_score : pd.Series
        0–100 composite payoff efficiency score.
    components : dict[str, pd.Series]
        Keys: pe_premium_eff, pe_delta_align, pe_liquidity,
        pe_dist_target, pe_iv_eff (each 0–100).
    """
    policy_config = _policy_config(policy_config)
    if expected_move is None:
        expected_move = _expected_move_from_policy(
            spot=float(spot),
            atm_iv=atm_iv,
            days_to_expiry=days_to_expiry,
            policy_config=policy_config,
        )

    premium = _safe_series(rows, "_normalized_last_price", "lastPrice", "LAST_PRICE")
    strikes = pd.to_numeric(
        rows.get("_normalized_strike", rows.get("strikePrice")),
        errors="coerce",
    ).fillna(float(spot))
    delta = _safe_series(rows, "DELTA")
    volume = _safe_series(rows, "_normalized_volume", "totalTradedVolume", "VOLUME")
    oi = _safe_series(rows, "_normalized_open_interest", "openInterest", "OPEN_INT")
    iv_col = _safe_series(rows, "_normalized_iv", "impliedVolatility", "IV")

    # 1. Premium efficiency: expected_move / premium
    pe_raw = expected_move / premium.clip(lower=_cfg_float(policy_config, "premium_efficiency_min_premium"))
    pe_norm = _rank_normalize(pe_raw) * 100

    # 2. Delta alignment: prefer |delta| in [0.35, 0.55]
    delta_abs = delta.abs()
    # Score peaks at 0.45 centre, falls off outside [0.35, 0.55]
    delta_ideal = _cfg_float(policy_config, "payoff_delta_ideal")
    delta_norm = max(_cfg_float(policy_config, "payoff_delta_normalization"), 1e-6)
    delta_dist = (delta_abs - delta_ideal).abs()
    pe_delta = (1.0 - (delta_dist / delta_norm).clip(upper=1.0)) * 100

    # 3. Liquidity: rank-normalised blend of volume + OI
    liq_blend = (
        _cfg_float(policy_config, "payoff_liquidity_weight_volume") * _rank_normalize(volume)
        + _cfg_float(policy_config, "payoff_liquidity_weight_open_interest") * _rank_normalize(oi)
    )
    pe_liq = liq_blend * 100

    # 4. Distance to target: penalise strikes far from expected move endpoint
    if direction == "CALL":
        target_level = float(spot) + expected_move
    else:
        target_level = float(spot) - expected_move
    target_dist = (strikes - target_level).abs()
    pe_dist = (1.0 - _rank_normalize(target_dist)) * 100

    # 5. IV efficiency: penalise excessively high IV; rank-invert
    pe_iv = (1.0 - _rank_normalize(iv_col)) * 100

    w = _payoff_weights(policy_config)
    composite = (
        w["premium_efficiency"] * pe_norm
        + w["delta_alignment"] * pe_delta
        + w["liquidity_score"] * pe_liq
        + w["distance_to_target"] * pe_dist
        + w["iv_efficiency"] * pe_iv
    ).round(1)

    components = {
        "pe_premium_eff": pe_norm.round(1),
        "pe_delta_align": pe_delta.round(1),
        "pe_liquidity": pe_liq.round(1),
        "pe_dist_target": pe_dist.round(1),
        "pe_iv_eff": pe_iv.round(1),
    }

    return composite, components


def compute_tradeability_flags(
    rows: pd.DataFrame,
    *,
    spot: float,
    atm_iv: float | None,
    days_to_expiry: float | None,
    expected_move: float | None = None,
    policy_config: dict[str, Any] | None = None,
) -> dict[str, pd.Series]:
    policy_config = _policy_config(policy_config)
    spot_safe = safe_float(spot, None)
    if spot_safe is None or spot_safe <= 0:
        return {
            "tradable_intraday": pd.Series(False, index=rows.index),
            "tradable_overnight": pd.Series(False, index=rows.index),
            "liquidity_ok": pd.Series(False, index=rows.index),
            "premium_reasonable": pd.Series(False, index=rows.index),
        }

    volume = _safe_series(rows, "_normalized_volume", "totalTradedVolume", "VOLUME")
    oi = _safe_series(rows, "_normalized_open_interest", "openInterest", "OPEN_INT")
    premium = _safe_series(rows, "_normalized_last_price", "lastPrice", "LAST_PRICE")

    if expected_move is None:
        expected_move = _expected_move_from_policy(
            spot=float(spot_safe),
            atm_iv=atm_iv,
            days_to_expiry=days_to_expiry,
            policy_config=policy_config,
        )

    flags = {
        "tradable_intraday": volume >= _cfg_float(policy_config, "tradeability_min_intraday_volume"),
        "tradable_overnight": volume >= _cfg_float(policy_config, "tradeability_min_overnight_volume"),
        "liquidity_ok": oi >= _cfg_float(policy_config, "tradeability_min_liquidity_oi"),
        "premium_reasonable": premium <= max(
            expected_move * _cfg_float(policy_config, "tradeability_max_premium_ratio"),
            _cfg_float(policy_config, "tradeability_min_premium_cap"),
        ),
    }

    return flags


# ---------------------------------------------------------------------------
# Composite enhanced scoring
# ---------------------------------------------------------------------------

def compute_enhanced_strike_scores(
    rows: pd.DataFrame,
    *,
    spot: float,
    direction: str,
    gamma_clusters: list | None = None,
    gamma_regime: str | None = None,
    spot_vs_flip: str | None = None,
    dealer_hedging_bias: str | None = None,
    gamma_flip_distance_pct: float | None = None,
    dealer_gamma_exposure: float | None = None,
    atm_iv: float | None = None,
    days_to_expiry: float | None = None,
    vol_surface_regime: str | None = None,
    weights: dict[str, float] | None = None,
    support_wall: float | None = None,
    resistance_wall: float | None = None,
) -> pd.DataFrame:
    """Compute all enhanced scoring factors and the composite score.

    Returns a DataFrame aligned with ``rows`` containing per-strike factor
    scores, tradeability flags, context fields, and the weighted composite
    ``enhanced_strike_score``.
    """
    if rows.empty:
        return pd.DataFrame()

    policy_config = get_strike_selection_score_config()
    spot_safe = safe_float(spot, None)
    if spot_safe is None or spot_safe <= 0:
        inferred_spot = safe_float(
            pd.to_numeric(rows.get("_normalized_strike", rows.get("strikePrice")), errors="coerce").median(),
            None,
        )
        spot_safe = inferred_spot
    if spot_safe is None or spot_safe <= 0:
        return pd.DataFrame(index=rows.index)

    w = weights or _enhanced_score_weights(policy_config)
    strikes = pd.to_numeric(
        rows.get("_normalized_strike", rows.get("strikePrice")),
        errors="coerce",
    ).fillna(0.0)

    # Factor scores
    liquidity = compute_liquidity_gravity(rows, policy_config=policy_config)
    gamma_mag = compute_gamma_magnetism(strikes, gamma_clusters)
    dealer = compute_dealer_pressure(
        strikes,
        gamma_regime=gamma_regime,
        spot_vs_flip=spot_vs_flip,
        dealer_hedging_bias=dealer_hedging_bias,
        gamma_flip_distance_pct=gamma_flip_distance_pct,
        dealer_gamma_exposure=dealer_gamma_exposure,
        policy_config=policy_config,
    )
    convexity = compute_volatility_convexity(rows)
    # Compute expected_move once for all sub-functions
    _expected_move = _expected_move_from_policy(
        spot=float(spot_safe),
        atm_iv=atm_iv,
        days_to_expiry=days_to_expiry,
        policy_config=policy_config,
    )

    prem_eff = compute_premium_efficiency(
        rows, spot=spot_safe, atm_iv=atm_iv, days_to_expiry=days_to_expiry,
        expected_move=_expected_move, policy_config=policy_config,
    )

    # Composite
    composite = (
        w.get("liquidity", 0.30) * liquidity
        + w.get("gamma_magnetism", 0.25) * gamma_mag
        + w.get("dealer_pressure", 0.20) * dealer
        + w.get("volatility_convexity", 0.15) * convexity
        + w.get("premium_efficiency", 0.10) * prem_eff
    )
    # Scale to 0-100
    enhanced_score = (composite * 100).round(0).astype(int)

    # Tradeability
    flags = compute_tradeability_flags(
        rows, spot=spot_safe, atm_iv=atm_iv, days_to_expiry=days_to_expiry,
        expected_move=_expected_move, policy_config=policy_config,
    )

    # Distance from spot
    spot_f = float(spot_safe)
    dist_pts = (strikes - spot_f).round(2)
    dist_pct = ((strikes - spot_f) / max(spot_f, 1e-6) * 100).round(2)

    # Payoff efficiency
    payoff_score, payoff_components = compute_payoff_efficiency(
        rows,
        spot=spot_safe,
        direction=direction,
        atm_iv=atm_iv,
        days_to_expiry=days_to_expiry,
        support_wall=support_wall,
        resistance_wall=resistance_wall,
        expected_move=_expected_move,
        policy_config=policy_config,
    )

    result_data = {
        "liquidity_score": liquidity,
        "gamma_magnetism": gamma_mag,
        "dealer_pressure": dealer,
        "convexity_score": convexity,
        "premium_efficiency": prem_eff,
        "enhanced_strike_score": enhanced_score,
        "payoff_efficiency_score": payoff_score,
        **payoff_components,
        "distance_from_spot_pts": dist_pts,
        "distance_from_spot_pct": dist_pct,
        "gamma_regime": gamma_regime or "",
        "spot_vs_flip": spot_vs_flip or "",
        "dealer_hedging_bias": dealer_hedging_bias or "",
        "vol_surface_regime": vol_surface_regime or "",
        "tradable_intraday": flags["tradable_intraday"],
        "tradable_overnight": flags["tradable_overnight"],
        "liquidity_ok": flags["liquidity_ok"],
        "premium_reasonable": flags["premium_reasonable"],
    }

    return pd.DataFrame(result_data, index=rows.index)

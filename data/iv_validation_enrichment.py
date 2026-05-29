"""
Validation-only IV enrichment for providers that omit IV fields.

This module does not replace provider data and does not alter the raw chain
used for persistence.  It builds a separate frame for data-quality validation
when live option prices are usable but provider IV columns are empty or zero.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from analytics.greeks_engine import enrich_chain_with_greeks


def positive_iv_row_count(option_chain: pd.DataFrame | None) -> int:
    if not isinstance(option_chain, pd.DataFrame) or option_chain.empty:
        return 0

    iv_columns = [col for col in ("impliedVolatility", "IV") if col in option_chain.columns]
    if not iv_columns:
        return 0

    positive_mask = pd.Series(False, index=option_chain.index)
    for column in iv_columns:
        positive_mask = positive_mask | pd.to_numeric(option_chain[column], errors="coerce").gt(0)
    return int(positive_mask.sum())


def _median_strike(option_chain: pd.DataFrame | None):
    if not isinstance(option_chain, pd.DataFrame) or option_chain.empty:
        return None
    strike_col = "strikePrice" if "strikePrice" in option_chain.columns else "STRIKE_PR" if "STRIKE_PR" in option_chain.columns else None
    if strike_col is None:
        return None
    strikes = pd.to_numeric(option_chain[strike_col], errors="coerce").dropna()
    if strikes.empty:
        return None
    return float(strikes.median())


def build_iv_validation_frame(
    option_chain: pd.DataFrame,
    *,
    spot: Any = None,
    valuation_time: Any = None,
    source_label: str = "MODEL_DERIVED_FROM_OPTION_PRICE",
    allow_spot_proxy: bool = True,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Return a validation frame plus diagnostics for IV source provenance."""
    raw_positive_iv_rows = positive_iv_row_count(option_chain)
    diagnostics: dict[str, object] = {
        "iv_validation_source": "PROVIDER_SUPPLIED" if raw_positive_iv_rows > 0 else "RAW_PROVIDER_IV_MISSING",
        "raw_positive_iv_rows": raw_positive_iv_rows,
        "validation_positive_iv_rows": raw_positive_iv_rows,
        "model_derived_iv_applied": False,
    }

    if raw_positive_iv_rows > 0:
        return option_chain, diagnostics

    validation_spot = spot
    if validation_spot in (None, ""):
        if allow_spot_proxy:
            validation_spot = _median_strike(option_chain)
            if validation_spot is not None:
                diagnostics["iv_validation_spot_source"] = "MEDIAN_STRIKE_PROXY"
        else:
            diagnostics["iv_validation_spot_source"] = "UNAVAILABLE"
    else:
        diagnostics["iv_validation_spot_source"] = "SPOT"

    if validation_spot in (None, ""):
        diagnostics["iv_validation_source"] = "RAW_PROVIDER_IV_MISSING_NO_SPOT"
        return option_chain, diagnostics

    try:
        validation_frame = enrich_chain_with_greeks(
            option_chain,
            spot=validation_spot,
            valuation_time=valuation_time,
        )
    except Exception as exc:
        diagnostics["iv_validation_source"] = "RAW_PROVIDER_IV_MISSING_DERIVATION_FAILED"
        diagnostics["iv_derivation_error"] = str(exc)
        return option_chain, diagnostics

    derived_positive_iv_rows = positive_iv_row_count(validation_frame)
    diagnostics["validation_positive_iv_rows"] = derived_positive_iv_rows
    if derived_positive_iv_rows > raw_positive_iv_rows:
        diagnostics["iv_validation_source"] = source_label
        diagnostics["model_derived_iv_applied"] = True
        return validation_frame, diagnostics

    diagnostics["iv_validation_source"] = "RAW_PROVIDER_IV_MISSING_DERIVATION_UNAVAILABLE"
    return option_chain, diagnostics


def attach_iv_validation_diagnostics(validation: dict, diagnostics: dict[str, object]) -> dict:
    if not isinstance(validation, dict) or not diagnostics:
        return validation

    updated = dict(validation)
    updated.update(diagnostics)
    warnings = list(updated.get("warnings") or [])
    if diagnostics.get("model_derived_iv_applied"):
        warning = "iv_model_derived_from_option_price"
        if warning not in warnings:
            warnings.append(warning)
        updated["warnings"] = warnings

    provider_health = updated.get("provider_health")
    if isinstance(provider_health, dict):
        provider_health = dict(provider_health)
        provider_health.update(diagnostics)
        updated["provider_health"] = provider_health
    return updated

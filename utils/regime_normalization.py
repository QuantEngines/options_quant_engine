"""Shared normalization helpers for regime and IV inputs.

These helpers keep cross-module contracts stable when upstream data uses
mixed label vocabularies or IV unit conventions.
"""

from __future__ import annotations


def normalize_iv_decimal(value, *, percent_unit_threshold: float = 1.5, default=None):
    """Normalize IV to decimal units.

    Values above ``percent_unit_threshold`` are treated as percent points and
    converted to decimal form.
    """
    try:
        iv = float(value)
    except Exception:
        return default

    if iv <= 0:
        return default
    if iv > float(percent_unit_threshold):
        return iv / 100.0
    return iv


def detect_iv_unit(value, *, percent_unit_threshold: float = 1.5) -> str | None:
    """Return ``PERCENT`` or ``DECIMAL`` based on value magnitude."""
    try:
        iv = float(value)
    except Exception:
        return None
    if iv <= 0:
        return None
    return "PERCENT" if iv > float(percent_unit_threshold) else "DECIMAL"


def canonical_gamma_regime(label) -> str:
    """Map gamma-regime synonyms into canonical labels.

    Canonical outputs: ``POSITIVE_GAMMA``, ``NEGATIVE_GAMMA``,
    ``NEUTRAL_GAMMA``, or the uppercased original label for unknown values.
    """
    normalized = str(label or "").upper().strip()
    if normalized in {"POSITIVE_GAMMA", "LONG_GAMMA", "LONG_GAMMA_ZONE"}:
        return "POSITIVE_GAMMA"
    if normalized in {"NEGATIVE_GAMMA", "SHORT_GAMMA", "SHORT_GAMMA_ZONE"}:
        return "NEGATIVE_GAMMA"
    if normalized in {"NEUTRAL_GAMMA", "NEUTRAL"}:
        return "NEUTRAL_GAMMA"
    if not normalized:
        return "UNKNOWN"
    return normalized

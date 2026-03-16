"""
Numeric helpers: safe coercion, clamping, division.

These are pure functions with no project imports and no domain logic.
"""

from __future__ import annotations


def clip(x, lo, hi):
    """Clamp *x* to the interval [*lo*, *hi*]."""
    return max(lo, min(hi, x))


def safe_float(x, default=0.0):
    """Coerce *x* to ``float``, returning *default* on failure."""
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def safe_div(a, b, default=0.0):
    """Safe division, returning *default* when *b* is zero or unusable."""
    try:
        a = float(a)
        b = float(b)
        if b == 0:
            return default
        return a / b
    except Exception:
        return default


def to_python_number(x):
    """Convert numpy scalars to native Python ints/floats.

    Plain Python numbers pass through unchanged.
    """
    if x is None:
        return x
    if hasattr(x, "item"):
        return x.item()
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return x

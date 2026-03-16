"""
Timestamp coercion helpers.

Uses pandas for parsing but carries no project-specific logic.
"""

from __future__ import annotations

import pandas as pd


def coerce_timestamp(value, *, tz: str | None = None, fallback=None):
    """Parse *value* into a timezone-aware ``pd.Timestamp``.

    Parameters
    ----------
    value : str | datetime | pd.Timestamp | None
        Raw timestamp to parse.
    tz : str, optional
        Target timezone (e.g. ``"Asia/Kolkata"``).  When *value* already
        carries timezone info it is converted; otherwise it is localized.
    fallback : optional
        Returned when *value* cannot be parsed.

    Returns
    -------
    pd.Timestamp | fallback
    """
    if value is None:
        return fallback
    try:
        ts = pd.to_datetime(value, errors="coerce", utc=True)
        if ts is pd.NaT:
            return fallback
        if tz:
            ts = ts.tz_convert(tz)
        return ts
    except Exception:
        return fallback

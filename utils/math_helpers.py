"""
Pure-math helpers: standard-normal PDF and CDF.

No project imports, no domain logic.
"""

from __future__ import annotations

import math


def norm_pdf(x: float) -> float:
    """Standard-normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def norm_cdf(x: float) -> float:
    """Standard-normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

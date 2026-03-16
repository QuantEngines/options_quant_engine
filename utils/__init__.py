"""
Module: utils

Purpose:
    Shared low-level helpers used across analytics, engine, strategy, risk,
    macro, data, and research packages.

Role in the System:
    Centralizes trivial utility functions that were previously copied into
    every module.  These helpers have no domain knowledge and no project
    imports so they can be safely consumed by any layer.
"""

from utils.numerics import clip, safe_float, safe_div, to_python_number  # noqa: F401
from utils.math_helpers import norm_cdf, norm_pdf  # noqa: F401
from utils.timestamp_helpers import coerce_timestamp  # noqa: F401

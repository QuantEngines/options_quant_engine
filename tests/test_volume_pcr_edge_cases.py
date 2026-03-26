from __future__ import annotations

import pandas as pd

from analytics.volume_pcr import compute_volume_pcr


def test_volume_pcr_extreme_when_calls_are_zero_and_puts_positive():
    chain = pd.DataFrame(
        {
            "OPTION_TYP": ["CE", "PE"],
            "VOLUME": [0.0, 2500.0],
            "STRIKE_PR": [22000.0, 22000.0],
            "EXPIRY_DT": ["2026-03-26", "2026-03-26"],
        }
    )

    out = compute_volume_pcr(chain, spot=22000.0)

    assert out["volume_pcr"] is not None
    assert out["volume_pcr"] >= 1.30
    assert out["volume_pcr_regime"] == "PUT_DOMINANT"

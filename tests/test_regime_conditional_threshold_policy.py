from __future__ import annotations

from config.signal_policy import get_trade_runtime_thresholds


def test_regime_defaults_tighten_negative_gamma_and_relax_positive_gamma():
    cfg = get_trade_runtime_thresholds()

    assert float(cfg["regime_positive_gamma_composite_delta"]) < 0
    assert float(cfg["regime_positive_gamma_strength_delta"]) < 0
    assert float(cfg["regime_positive_gamma_position_size_mult"]) > 1.0
    assert float(cfg["regime_positive_gamma_holding_delta_m"]) > 0

    assert float(cfg["regime_negative_gamma_composite_delta"]) > 0
    assert float(cfg["regime_negative_gamma_strength_delta"]) > 0
    assert float(cfg["regime_negative_gamma_position_size_mult"]) < 1.0
    assert float(cfg["regime_negative_gamma_holding_delta_m"]) < 0

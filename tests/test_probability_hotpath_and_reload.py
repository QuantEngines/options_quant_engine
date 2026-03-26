from __future__ import annotations

import time

from engine.trading_support import probability as prob


class _DummyPredictor:
    init_count = 0

    def __init__(self, base_model=None):
        type(self).init_count += 1
        self.base_model = base_model

    def predict_probability(self, model_features):
        return 0.5


def _market_state_template():
    return {
        "gamma_regime": "NEUTRAL_GAMMA",
        "final_flow_signal": "NEUTRAL_FLOW",
        "vol_regime": "NORMAL_VOL",
        "hedging_bias": "NEUTRAL",
        "spot_vs_flip": "ABOVE_FLIP",
        "vacuum_state": "VACUUM_WATCH",
        "atm_iv": 18.0,
        "vacuum_zones": [],
        "hedging_flow": {},
        "flow_signal_value": "NEUTRAL_FLOW",
        "smart_money_signal_value": "NEUTRAL_FLOW",
        "flip": None,
        "voids": [],
        "dealer_pos": "NEUTRAL",
        "greek_exposures": {},
        "confirmation_status": "MIXED",
    }


def test_move_predictor_reloads_when_active_model_changes(monkeypatch):
    import config.settings as settings

    _DummyPredictor.init_count = 0
    monkeypatch.setattr(prob.ml_move_predictor_mod, "MLMovePredictor", _DummyPredictor)
    monkeypatch.setattr(settings, "ACTIVE_MODEL", None, raising=False)

    prob._MOVE_PREDICTOR = None
    prob._MOVE_PREDICTOR_SIGNATURE = None

    first = prob._get_move_predictor()
    assert first is not None
    assert _DummyPredictor.init_count == 1

    monkeypatch.setattr(settings, "ACTIVE_MODEL", "nonexistent_registry_model", raising=False)
    second = prob._get_move_predictor()
    assert second is not None
    assert _DummyPredictor.init_count == 2


def test_probability_feature_builder_single_call_per_snapshot(monkeypatch):
    calls = {"count": 0}

    def _build_features(*args, **kwargs):
        calls["count"] += 1
        return [0.1] * 7

    monkeypatch.setattr(prob.feature_builder_mod, "build_features", _build_features)

    def _rule_prob(*args, **kwargs):
        return 0.55

    monkeypatch.setattr(prob.large_move_probability_mod, "large_move_probability", _rule_prob, raising=False)

    state = _market_state_template()
    out = prob._compute_probability_state_impl(
        df=None,
        spot=22000.0,
        symbol="NIFTY",
        market_state=state,
        day_high=22100.0,
        day_low=21900.0,
        day_open=22010.0,
        prev_close=21980.0,
        lookback_avg_range_pct=1.2,
        global_context={},
        _force_rule_only=True,
    )

    assert calls["count"] == 1
    assert out["model_features"] is not None


def test_probability_hotpath_benchmark_call_count(monkeypatch):
    calls = {"count": 0}

    def _build_features(*args, **kwargs):
        calls["count"] += 1
        return [0.1] * 7

    monkeypatch.setattr(prob.feature_builder_mod, "build_features", _build_features)
    monkeypatch.setattr(
        prob.large_move_probability_mod,
        "large_move_probability",
        lambda *args, **kwargs: 0.52,
        raising=False,
    )

    state = _market_state_template()
    n = 200
    t0 = time.perf_counter()
    for _ in range(n):
        prob._compute_probability_state_impl(
            df=None,
            spot=22000.0,
            symbol="NIFTY",
            market_state=state,
            day_high=22100.0,
            day_low=21900.0,
            day_open=22010.0,
            prev_close=21980.0,
            lookback_avg_range_pct=1.2,
            global_context={},
            _force_rule_only=True,
        )
    elapsed = time.perf_counter() - t0

    # Performance proxy: one builder call per snapshot.
    assert calls["count"] == n
    # Keep this loose to avoid environment flakiness while catching regressions.
    assert elapsed < 3.0

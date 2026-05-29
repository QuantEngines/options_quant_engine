from app.terminal_output import (
    _build_global_macro_snapshot_fields,
    _describe_effective_strength_gate,
    _format_atm_iv_market_summary,
    _format_multi_source_ingestion,
    _format_probability_display,
    _format_provider_quality_market_summary,
    _format_runtime_composite_for_decision,
    _format_runtime_composite_supplement_for_decision,
    _format_trigger_for_display,
    _format_provider_note_for_display,
    _is_provider_execution_blocked,
    _provider_execution_block_phrase,
    _render_data_usability_diagnostics,
    _render_dealer_gamma_levels,
    _render_provider_health_compact_detail,
    _render_regime_rollout_status,
    _render_score_threshold_block,
    _should_render_provider_compact_diagnostics,
    _summarize_confidence_guards,
)
from contextlib import redirect_stdout
from io import StringIO


def test_format_probability_display_preserves_small_nonzero_values() -> None:
    assert _format_probability_display(0.0) == "0%"
    assert _format_probability_display(0.004) == "<1%"
    assert _format_probability_display(0.056) == "5.6%"
    assert _format_probability_display(0.42) == "42%"


def test_format_multi_source_ingestion_labels_primary_and_secondary_roles() -> None:
    result = {
        "multi_source_ingestion": {
            "enabled": True,
            "primary_decision_source": "ZERODHA",
            "secondary_research_sources": ["ICICI"],
            "requested_sources": ["ZERODHA", "ICICI"],
            "successful_sources": ["ZERODHA", "ICICI"],
            "failed_sources": [],
        }
    }

    assert _format_multi_source_ingestion(result) == (
        "primary_decision=ZERODHA; secondary_research=ICICI; "
        "requested=ZERODHA,ICICI; ok=ZERODHA,ICICI"
    )


def test_global_macro_snapshot_fields_suppresses_empty_unavailable_block() -> None:
    assert _build_global_macro_snapshot_fields(trade={}, global_market_snapshot={}) is None


def test_format_atm_iv_market_summary_exposes_weak_iv_context() -> None:
    trade = {
        "atm_iv": 12.66,
        "provider_health": {
            "atm_iv_health": "WEAK",
            "core_iv_health": "WEAK",
            "iv_health": "CAUTION",
        },
    }

    assert _format_atm_iv_market_summary(trade) == "12.66 (atm=WEAK, iv=CAUTION)"


def test_format_atm_iv_market_summary_labels_validation_midpoint() -> None:
    trade = {
        "atm_iv": 14.29,
        "provider_health": {
            "atm_iv_health": "GOOD",
            "core_iv_health": "GOOD",
            "atm_iv_midpoint": 0.126,
            "iv_validation_source": "MODEL_DERIVED_FROM_OPTION_PRICE",
        },
    }

    assert _format_atm_iv_market_summary(trade) == "14.29 (atm=GOOD, validation_mid=12.6%)"


def test_format_provider_quality_market_summary_separates_analytics_and_execution() -> None:
    trade = {
        "analytics_usable": True,
        "execution_suggestion_usable": False,
        "provider_quality_mode": "ANALYTICS_ONLY_EXECUTION_BLOCKED",
        "provider_health": {"summary_status": "WEAK"},
    }

    assert _format_provider_quality_market_summary(trade) == (
        "health=WEAK; analytics=usable; execution=blocked; "
        "mode=ANALYTICS_ONLY_EXECUTION_BLOCKED"
    )


def test_format_provider_quality_market_summary_uses_effective_execution_block() -> None:
    trade = {
        "analytics_usable": True,
        "execution_suggestion_usable": True,
        "provider_execution_status": "BLOCKED",
        "provider_quality_blocks_execution": True,
        "provider_quality_mode": "ANALYTICS_ONLY_EXECUTION_BLOCKED",
        "provider_health": {"summary_status": "WEAK"},
    }

    assert _format_provider_quality_market_summary(trade) == (
        "health=WEAK; analytics=usable; execution=blocked; "
        "mode=ANALYTICS_ONLY_EXECUTION_BLOCKED"
    )
    assert _is_provider_execution_blocked(trade) is True


def test_format_runtime_composite_supplement_for_decision_only_when_applied() -> None:
    trade = {
        "runtime_composite_supplement_applied": True,
        "runtime_composite_supplement_score_adjustment": 6,
        "runtime_composite_supplement_rule": "level_wall_plus_6",
        "runtime_composite_supplement_base_score": 53,
        "runtime_composite_supplement_adjusted_score": 59,
    }

    assert _format_runtime_composite_supplement_for_decision(trade) == "+6 level_wall_plus_6 (53->59)"
    assert _format_runtime_composite_supplement_for_decision({}) is None


def test_provider_execution_block_phrase_uses_iv_surface_when_raw_quotes_pass() -> None:
    trade = {
        "execution_suggestion_usable": True,
        "provider_execution_status": "BLOCKED",
        "provider_quality_blocks_execution": True,
        "provider_health": {"trade_blocking_reasons": ["core_iv_weak", "atm_iv_weak"]},
    }

    assert _provider_execution_block_phrase(trade) == (
        "provider IV/surface health is blocking execution readiness"
    )
    assert _format_provider_note_for_display(trade) == (
        "Raw quotes are usable, but provider IV/surface health is blocking execution readiness."
    )


def test_format_runtime_composite_for_decision_explains_direction_pending() -> None:
    trade = {
        "confirmation_status": "NO_DIRECTION",
        "effective_min_composite_score_threshold": 68,
    }

    assert _format_runtime_composite_for_decision(trade) == "not computed (direction pending)"


def test_render_score_threshold_block_does_not_show_full_bar_below_threshold() -> None:
    with StringIO() as buffer, redirect_stdout(buffer):
        _render_score_threshold_block("Runtime Composite Threshold", current=59, required=60)
        output = buffer.getvalue()

    assert "59/60" in output
    assert "[███████████████████░]" in output


def test_should_render_provider_compact_diagnostics_for_dead_inactive_execution_block() -> None:
    trade = {
        "trade_status": "DEAD_INACTIVE",
        "execution_suggestion_usable": False,
        "provider_health": {"summary_status": "WEAK"},
    }

    assert _should_render_provider_compact_diagnostics(trade) is True


def test_summarize_confidence_guards_explains_execution_caps() -> None:
    note = _summarize_confidence_guards(
        [
            "status_watchlist_or_blocked",
            "provider_health_weak",
            "explicit_no_trade_reason",
        ]
    )

    assert note == (
        "capped by weak provider health; capped by explicit no-trade reason; "
        "execution-gated by blocked/watchlist status (setup may still be strong)"
    )


def test_format_trigger_for_display_applies_noise_buffer_for_tight_breakouts() -> None:
    trade = {"spot": 99.98}
    rendered = _format_trigger_for_display("decisive move above 100.00", trade)
    assert rendered.startswith("decisive move above 104.98 (noise-buffered from 100.00)")
    assert "[+5.0pts / +5.00%]" in rendered


def test_describe_effective_strength_gate_uses_readable_regime_separator() -> None:
    trade = {
        "min_trade_strength_threshold": 60,
        "data_quality_status": "CAUTION",
        "confirmation_status": "STRONG_CONFIRMATION",
        "regime_threshold_adjustments": [
            "Configured NEGATIVE_GAMMA threshold and sizing adjustment",
            "Adjusted for VOL_EXPANSION: composite +2, size 0.85x",
        ],
    }

    description = _describe_effective_strength_gate(trade)

    assert description == (
        "60 (base~60; conf:none; regime:Configured NEGATIVE_GAMMA threshold and sizing adjustment, "
        "Adjusted for VOL_EXPANSION: composite +2, size 0.85x)"
    )


def test_describe_effective_strength_gate_prefers_effective_threshold() -> None:
    trade = {
        "min_trade_strength_threshold": 60,
        "effective_min_trade_strength_threshold": 62,
        "data_quality_status": "STRONG",
        "confirmation_status": "STRONG_CONFIRMATION",
        "regime_threshold_adjustments": [
            "Configured POSITIVE_GAMMA threshold and sizing adjustment",
            "AT_FLIP: Tightened thresholds (squeeze risk)",
        ],
    }

    description = _describe_effective_strength_gate(trade)

    assert description == (
        "62 (base~60; conf:none; regime:Configured POSITIVE_GAMMA threshold and sizing adjustment, "
        "AT_FLIP: Tightened thresholds (squeeze risk))"
    )


def test_summarize_confidence_guards_uses_constrained_by_when_cap_not_applied() -> None:
    """When no cap was binding (score already below all thresholds), use 'constrained by'."""
    note = _summarize_confidence_guards(
        ["provider_health_weak", "data_quality_caution", "direction_unresolved"],
        cap_applied=False,
    )

    assert note == (
        "constrained by weak provider health; constrained by caution data quality; "
        "constrained by unresolved direction"
    )


def test_summarize_confidence_guards_direction_root_suppresses_downstream_with_cap_applied() -> None:
    """direction_unresolved suppresses downstream confirmation/no-trade guards."""
    note = _summarize_confidence_guards(
        [
            "direction_unresolved",
            "confirmation_no_direction",
            "explicit_no_trade_reason",
            "status_watchlist_or_blocked",
        ],
        cap_applied=True,
    )

    # Only the root cause should appear; downstream guards suppressed.
    assert note == "capped by unresolved direction"


def test_render_dealer_gamma_levels_flip_drift_mentions_previous_snapshot() -> None:
    trade = {
        "spot": 23944.7,
        "gamma_flip": 23933.1,
        "gamma_clusters": [24000, 24500],
        "dealer_flow_state": "HEDGING_NEUTRAL",
        "gamma_exposure_greeks": 74000.0,
        "gamma_flip_drift": {
            "drift": 1133.0,
            "drift_direction": "RISING",
            "prev_flip": 22800.1,
        },
    }

    with StringIO() as buffer, redirect_stdout(buffer):
        _render_dealer_gamma_levels(trade)
        output = buffer.getvalue()

    assert "flip_drift" in output
    assert "vs prev snapshot" in output


def test_render_dealer_gamma_levels_explains_bias_magnet_visual_mismatch() -> None:
    trade = {
        "spot": 23912.25,
        "gamma_flip": 23890.0,
        "gamma_clusters": [24000, 24200, 24100],
        "dealer_hedging_bias": "DOWNSIDE_ACCELERATION",
        "dealer_flow_state": "HEDGING_NEUTRAL",
    }

    with StringIO() as buffer, redirect_stdout(buffer):
        _render_dealer_gamma_levels(trade)
        output = buffer.getvalue()

    assert "dealer_bias_note" in output
    assert "hedge-flow pressure" in output
    assert "upside levels" in output


def test_compact_regime_rollout_hidden_when_baseline_authoritative_without_active_alert() -> None:
    result = {
        "shadow_mode_active": False,
        "regime_pack_evaluation": {
            "shadow_candidate_pack": "baseline_v1",
            "reason": "already_authoritative",
        },
        "shadow_validation_summary": {
            "policy_alert_count": 1,
            "latest_session_validation": {
                "session_date": "2026-04-17",
                "snapshot_count": 3438,
                "alert_level": "WATCH",
                "policy_alert": False,
            },
        },
    }

    with StringIO() as buffer, redirect_stdout(buffer):
        _render_regime_rollout_status(result, compact=True)
        output = buffer.getvalue()

    assert "REGIME ROLLOUT" not in output


def test_compact_regime_rollout_shown_for_active_policy_alert() -> None:
    result = {
        "shadow_mode_active": False,
        "regime_pack_evaluation": {
            "shadow_candidate_pack": "candidate_v1",
            "reason": "shadow_candidate_selected",
        },
        "shadow_validation_summary": {
            "latest_session_validation": {
                "session_date": "2026-04-17",
                "snapshot_count": 3438,
                "alert_level": "ALERT",
                "policy_alert": True,
            },
        },
    }

    with StringIO() as buffer, redirect_stdout(buffer):
        _render_regime_rollout_status(result, compact=True)
        output = buffer.getvalue()

    assert "REGIME ROLLOUT" in output
    assert "policy_alert" in output


def test_render_provider_health_compact_detail_uses_reason_when_no_unmet_reasons() -> None:
    trade = {
        "provider_health": {
            "summary_status": "WEAK",
            "source": "NSE",
        },
        "provider_health_override_diagnostics": {
            "eligible": False,
            "reason": "override_disabled",
            "fail_reasons": [],
        }
    }

    with StringIO() as buffer, redirect_stdout(buffer):
        _render_provider_health_compact_detail(trade)
        output = buffer.getvalue()

    assert "override  : eligible=False; unmet=override_disabled" in output


def test_render_data_usability_diagnostics_shows_usability_and_weights() -> None:
    trade = {
        "analytics_usable": True,
        "execution_suggestion_usable": False,
        "tradable_data": {
            "status": "ANALYTICS_ONLY",
            "score": 0.41,
            "reasons": ["crossed_quotes_high", "quote_outliers_high"],
            "crossed_or_locked_ratio": 0.18,
            "quote_outlier_ratio": 0.11,
        },
        "feature_reliability_weights": {
            "gamma": 0.95,
            "flow": 0.72,
            "surface": 0.31,
        },
        "provider_quality_mode": "ANALYTICS_ONLY_EXECUTION_BLOCKED",
        "provider_direction_trust": "TRUST_PROVIDER_ANALYTICS",
        "provider_execution_trust": "DO_NOT_TRADE_EXECUTION_QUOTES",
        "provider_quality_action": "OBSERVE_SIGNAL_DO_NOT_EXECUTE",
        "provider_quality_note": "Direction analytics are usable, but execution quotes/tradable data are not reliable enough to trade.",
    }

    with StringIO() as buffer, redirect_stdout(buffer):
        _render_data_usability_diagnostics(trade, verbose=True)
        output = buffer.getvalue()

    assert "DATA USABILITY" in output
    assert "analytics_usable" in output
    assert "execution_suggestion_usable" in output
    assert "ANALYTICS_ONLY_EXECUTION_BLOCKED" in output
    assert "TRUST_PROVIDER_ANALYTICS" in output
    assert "DO_NOT_TRADE_EXECUTION_QUOTES" in output
    assert "ANALYTICS_ONLY" in output
    assert "feature_weights" in output


def test_render_data_usability_diagnostics_does_not_treat_provider_pass_as_blocked() -> None:
    trade = {
        "analytics_usable": True,
        "execution_suggestion_usable": True,
        "provider_health": {
            "trade_blocking_status": "PASS",
        },
    }

    with StringIO() as buffer, redirect_stdout(buffer):
        _render_data_usability_diagnostics(trade, verbose=False)
        output = buffer.getvalue()

    assert "provider_exec_blocked" not in output


def test_render_data_usability_diagnostics_shows_provider_blocked_when_status_blocks() -> None:
    trade = {
        "analytics_usable": True,
        "execution_suggestion_usable": False,
        "provider_health": {
            "trade_blocking_status": "BLOCK",
        },
    }

    with StringIO() as buffer, redirect_stdout(buffer):
        _render_data_usability_diagnostics(trade, verbose=False)
        output = buffer.getvalue()

    assert "provider_exec_blocked" in output


def test_render_data_usability_diagnostics_shows_effective_execution_block_when_raw_quotes_pass() -> None:
    trade = {
        "analytics_usable": True,
        "execution_suggestion_usable": True,
        "provider_execution_status": "BLOCKED",
        "provider_quality_blocks_execution": True,
        "provider_execution_trust": "DO_NOT_TRADE_EXECUTION_QUOTES",
        "provider_health": {"trade_blocking_reasons": ["core_iv_weak"]},
    }

    with StringIO() as buffer, redirect_stdout(buffer):
        _render_data_usability_diagnostics(trade, verbose=False)
        output = buffer.getvalue()

    assert "execution_suggestion_usable" in output
    assert "effective_execution_usable" in output
    assert "False (provider block active)" in output
    assert "provider IV/surface health is blocking execution readiness" in output
    assert "provider_exec_blocked" in output

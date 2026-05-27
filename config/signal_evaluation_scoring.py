"""
Module: signal_evaluation_scoring.py

Purpose:
    Define configuration values used by signal evaluation scoring.

Role in the System:
    Part of the configuration layer that centralizes policy defaults, thresholds, and governance controls.

Key Outputs:
    Configuration objects and threshold bundles consumed by runtime and research workflows.

Downstream Usage:
    Consumed by analytics, signal generation, strategy, risk overlays, tuning, and backtests.
"""

SIGNAL_EVALUATION_SCORE_WEIGHTS = {
    "direction_score": 0.30,
    "magnitude_score": 0.25,
    "timing_score": 0.20,
    "tradeability_score": 0.25,
}

SIGNAL_EVALUATION_DIRECTION_WEIGHTS = {
    "correct_5m": 1.0,
    "correct_15m": 1.2,
    "correct_30m": 1.1,
    "correct_60m": 1.0,
    "correct_120m": 0.9,
    "correct_session_close": 1.0,
}

SIGNAL_EVALUATION_TIMING_WEIGHTS = {
    "realized_return_5m": 1.4,
    "realized_return_15m": 1.2,
    "realized_return_30m": 1.0,
    "realized_return_60m": 0.8,
    "realized_return_120m": 0.6,
}

SIGNAL_EVALUATION_THRESHOLDS = {
    "magnitude_vs_range_weak": 0.20,
    "magnitude_vs_range_good": 0.50,
    "magnitude_vs_range_strong": 1.00,
    "timing_positive_return_floor": 0.0005,
    "tradeability_ratio_floor": 0.75,
    "tradeability_ratio_good": 1.50,
    "tradeability_ratio_strong": 2.50,
}

SIGNAL_EVALUATION_SELECTION_POLICY = {
    "trade_strength_floor": 60.0,
    "composite_signal_score_floor": 75.0,
    "tradeability_score_floor": 65.0,
    "move_probability_floor": 0.60,
    "option_efficiency_score_floor": 40.0,
    "global_risk_score_cap": 75.0,
    "require_overnight_hold_allowed": False,
}

SIGNAL_EVALUATION_LABEL_QUALITY_POLICY = {
    "primary_label_horizon_minutes": 60,
    "base_score": 100.0,
    "direction_unresolved_score_cap": 15.0,
    "target_stop_ambiguous_score_cap": 25.0,
    "intraday_eval_disabled_score_cap": 20.0,
    "entry_spot_unavailable_score_cap": 20.0,
    "outcome_pending_score_cap": 10.0,
    "outcome_partial_score_cap": 85.0,
    "outcome_unknown_score_cap": 75.0,
    "outcome_other_score_cap": 60.0,
    "insufficient_observation_score_cap": 35.0,
    "primary_horizon_unavailable_score_cap": 35.0,
    "primary_return_unavailable_score_cap": 70.0,
    "calibration_unavailable_with_label_score_cap": 45.0,
}

SIGNAL_EVALUATION_REPORTING_POLICY = {
    "default_top_n": 10,
    "markdown_threshold_replay_rows": 10,
    "markdown_regime_threshold_rows": 10,
    "markdown_walk_forward_rows": 10,
    "daily_threshold_replay_rows": 8,
    "daily_threshold_summary_rows": 5,
    "daily_table_preview_rows": 8,
    "min_reliable_sample": 30,
    "strong_sample": 100,
    "information_coefficient_min_sample": 10,
    "score_bucket_cut_1": 35.0,
    "score_bucket_cut_2": 50.0,
    "score_bucket_cut_3": 65.0,
    "score_bucket_cut_4": 80.0,
    "premium_bucket_cut_1": 50.0,
    "premium_bucket_cut_2": 100.0,
    "premium_bucket_cut_3": 150.0,
    "premium_bucket_cut_4": 250.0,
    "probability_bucket_cut_1": 0.35,
    "probability_bucket_cut_2": 0.50,
    "probability_bucket_cut_3": 0.65,
    "probability_bucket_cut_4": 0.80,
    "probability_bucket_high_cap": 1.01,
    "daily_research_action_min_directional_rows": 20,
    "daily_research_action_regime_reliable_rows": 50,
    "daily_probability_miscalibration_gap": 0.15,
    "daily_probability_miscalibration_mild_gap": 0.05,
    "daily_information_coefficient_min_rows": 5,
    "daily_information_coefficient_moderate_threshold": 0.05,
    "daily_information_coefficient_strong_threshold": 0.15,
}


def get_signal_evaluation_score_weights():
    """
    Purpose:
        Return signal evaluation score weights for downstream use.
    
    Context:
        Public function within the configuration layer. It exposes a reusable step in this module's workflow.
    
    Inputs:
        None: This helper does not require caller-supplied inputs.
    
    Returns:
        Any: Result returned by the helper.
    
    Notes:
        Centralizing this contract keeps runtime, replay, and research workflows aligned on the same configuration semantics.
    """
    from config.policy_resolver import resolve_mapping

    return resolve_mapping("evaluation_thresholds.score_weights", SIGNAL_EVALUATION_SCORE_WEIGHTS)


def get_signal_evaluation_direction_weights():
    """
    Purpose:
        Return signal evaluation direction weights for downstream use.
    
    Context:
        Public function within the configuration layer. It exposes a reusable step in this module's workflow.
    
    Inputs:
        None: This helper does not require caller-supplied inputs.
    
    Returns:
        Any: Result returned by the helper.
    
    Notes:
        Centralizing this contract keeps runtime, replay, and research workflows aligned on the same configuration semantics.
    """
    from config.policy_resolver import resolve_mapping

    return resolve_mapping("evaluation_thresholds.direction_weights", SIGNAL_EVALUATION_DIRECTION_WEIGHTS)


def get_signal_evaluation_timing_weights():
    """
    Purpose:
        Return signal evaluation timing weights for downstream use.
    
    Context:
        Public function within the configuration layer. It exposes a reusable step in this module's workflow.
    
    Inputs:
        None: This helper does not require caller-supplied inputs.
    
    Returns:
        Any: Result returned by the helper.
    
    Notes:
        Centralizing this contract keeps runtime, replay, and research workflows aligned on the same configuration semantics.
    """
    from config.policy_resolver import resolve_mapping

    return resolve_mapping("evaluation_thresholds.timing_weights", SIGNAL_EVALUATION_TIMING_WEIGHTS)


def get_signal_evaluation_thresholds():
    """
    Purpose:
        Return signal evaluation thresholds for downstream use.
    
    Context:
        Public function within the configuration layer. It exposes a reusable step in this module's workflow.
    
    Inputs:
        None: This helper does not require caller-supplied inputs.
    
    Returns:
        Any: Result returned by the helper.
    
    Notes:
        Centralizing this contract keeps runtime, replay, and research workflows aligned on the same configuration semantics.
    """
    from config.policy_resolver import resolve_mapping

    return resolve_mapping("evaluation_thresholds.core", SIGNAL_EVALUATION_THRESHOLDS)


def get_signal_evaluation_selection_policy():
    """
    Purpose:
        Return signal evaluation selection policy for downstream use.
    
    Context:
        Public function within the configuration layer. It exposes a reusable step in this module's workflow.
    
    Inputs:
        None: This helper does not require caller-supplied inputs.
    
    Returns:
        Any: Result returned by the helper.
    
    Notes:
        Centralizing this contract keeps runtime, replay, and research workflows aligned on the same configuration semantics.
    """
    from config.policy_resolver import resolve_mapping

    return resolve_mapping("evaluation_thresholds.selection", SIGNAL_EVALUATION_SELECTION_POLICY)


def get_signal_evaluation_label_quality_policy():
    """
    Purpose:
        Return signal evaluation label-quality policy defaults for downstream use.

    Context:
        Label-quality gates decide whether a realized outcome is clean enough for
        calibration and promotion research. Keeping these caps parameterized makes
        label governance auditable without changing the signal engine.

    Inputs:
        None: This helper does not require caller-supplied inputs.

    Returns:
        dict: Resolved label-quality policy values.

    Notes:
        Defaults preserve the historical 60-minute calibration label and score caps.
    """
    from config.policy_resolver import resolve_mapping

    return resolve_mapping("evaluation_thresholds.label_quality", SIGNAL_EVALUATION_LABEL_QUALITY_POLICY)


def get_signal_evaluation_reporting_policy():
    """
    Purpose:
        Return signal-evaluation report presentation and evidence thresholds.

    Context:
        Reporting cutoffs are research governance controls, not live trade
        decisions. Centralizing them keeps daily, cumulative, and markdown
        reports aligned while preserving point-in-time evaluation semantics.

    Inputs:
        None: This helper does not require caller-supplied inputs.

    Returns:
        dict: Resolved reporting policy values.

    Notes:
        Defaults preserve historical score/probability/premium buckets and
        sample-size evidence labels.
    """
    from config.policy_resolver import resolve_mapping

    return resolve_mapping("evaluation_thresholds.reporting", SIGNAL_EVALUATION_REPORTING_POLICY)

"""
Module: historical_context.py

Purpose:
    Translate mined historical-data insights into live signal modifiers.

Role in the System:
    The engine is currently in testing mode, so these priors are allowed to
    adjust live score, probability, thresholds, and sizing while preserving a
    clear audit trail of every applied component.
"""

from __future__ import annotations

from math import isfinite

from config.historical_context_policy import (
    HISTORICAL_CONTEXT_POLICY,
    HISTORICAL_CONTEXT_POLICY_VERSION,
    get_historical_context_policy,
)
from utils.pcr import PCR_HIGH_CONTEXT_THRESHOLD, PCR_LOW_CONTEXT_THRESHOLD

from .historical_prior_artifact import load_historical_prior_artifact
from .statistical_market_context import build_statistical_market_context


HISTORICAL_CONTEXT_VERSION = "historical_context_v1"
HISTORICAL_CONTEXT_DECISION_MODE = "LIVE_APPLIED"


def _policy_value(policy, key, default=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    return policy.get(key, HISTORICAL_CONTEXT_POLICY.get(key, default))


def _vix_buckets_from_policy(policy):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    specs = [
        ("LOW", "vix_low"),
        ("LOW_MID", "vix_low_mid"),
        ("MID", "vix_mid"),
        ("HIGH_MID", "vix_high_mid"),
        ("HIGH", "vix_high"),
    ]
    return [
        {
            "bucket": label,
            "upper": _policy_value(policy, f"{prefix}_upper"),
            "expected_range_bps": _policy_value(policy, f"{prefix}_expected_range_bps"),
            "expected_abs_move_bps": _policy_value(policy, f"{prefix}_expected_abs_move_bps"),
            "sample_profile": _policy_value(policy, f"{prefix}_sample_profile"),
        }
        for label, prefix in specs
    ]


def _vol_adjustments_from_policy(policy):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    score_adjustments = {}
    probability_adjustments = {}
    for bucket, prefix in (
        ("LOW", "vol_bucket_low"),
        ("LOW_MID", "vol_bucket_low_mid"),
        ("MID", "vol_bucket_mid"),
        ("HIGH_MID", "vol_bucket_high_mid"),
        ("HIGH", "vol_bucket_high"),
    ):
        score_adjustments[bucket] = int(_policy_value(policy, f"{prefix}_score_adjustment", 0))
        probability_adjustments[bucket] = float(_policy_value(policy, f"{prefix}_probability_adjustment", 0.0))
    return score_adjustments, probability_adjustments


# Compatibility constants for callers/tests that inspect this module directly.
VIX_BUCKETS = _vix_buckets_from_policy(HISTORICAL_CONTEXT_POLICY)
BASELINE_EXPECTED_RANGE_BPS = HISTORICAL_CONTEXT_POLICY["baseline_expected_range_bps"]
BASELINE_EXPECTED_ABS_MOVE_BPS = HISTORICAL_CONTEXT_POLICY["baseline_expected_abs_move_bps"]
SP500_BOTTOM_QUINTILE_PCT = HISTORICAL_CONTEXT_POLICY["sp500_bottom_quintile_pct"]
SP500_TOP_QUINTILE_PCT = HISTORICAL_CONTEXT_POLICY["sp500_top_quintile_pct"]
NASDAQ_BOTTOM_QUINTILE_PCT = HISTORICAL_CONTEXT_POLICY["nasdaq_bottom_quintile_pct"]
NASDAQ_TOP_QUINTILE_PCT = HISTORICAL_CONTEXT_POLICY["nasdaq_top_quintile_pct"]
US_VIX_DROP_QUINTILE_PCT = HISTORICAL_CONTEXT_POLICY["us_vix_drop_quintile_pct"]
US_VIX_JUMP_QUINTILE_PCT = HISTORICAL_CONTEXT_POLICY["us_vix_jump_quintile_pct"]
NEAR_WALL_THRESHOLD_PCT = HISTORICAL_CONTEXT_POLICY["near_wall_threshold_pct"]
NEAR_MAX_PAIN_THRESHOLD_PCT = HISTORICAL_CONTEXT_POLICY["near_max_pain_threshold_pct"]
STRONG_PRIOR_OVERRIDE_SCORE = HISTORICAL_CONTEXT_POLICY["strong_prior_override_score"]
VOL_BUCKET_SCORE_ADJUSTMENTS, VOL_BUCKET_PROBABILITY_ADJUSTMENTS = _vol_adjustments_from_policy(
    HISTORICAL_CONTEXT_POLICY
)


def _safe_float(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not isfinite(number):
        return default
    return number


def _round(value, digits=4):
    value = _safe_float(value, None)
    return round(value, digits) if value is not None else None


def _distance_pct(level, spot):
    level = _safe_float(level, None)
    spot = _safe_float(spot, None)
    if level is None or spot in (None, 0.0):
        return None
    return abs((level - spot) / spot) * 100.0


def _classify_vix_bucket(india_vix_level, policy=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    vix = _safe_float(india_vix_level, None)
    if vix is None:
        return {
            "bucket": "UNAVAILABLE",
            "india_vix_level": None,
            "expected_range_bps": None,
            "expected_abs_move_bps": None,
            "range_multiplier": None,
            "abs_move_multiplier": None,
            "sample_profile": "india_vix_missing",
            "source": "missing_india_vix_level",
        }

    baseline_range = _safe_float(_policy_value(policy, "baseline_expected_range_bps"), BASELINE_EXPECTED_RANGE_BPS)
    baseline_abs_move = _safe_float(
        _policy_value(policy, "baseline_expected_abs_move_bps"),
        BASELINE_EXPECTED_ABS_MOVE_BPS,
    )
    for bucket in _vix_buckets_from_policy(policy):
        if bucket["upper"] is None or vix <= bucket["upper"]:
            expected_range = _safe_float(bucket["expected_range_bps"], None)
            expected_abs_move = _safe_float(bucket["expected_abs_move_bps"], None)
            return {
                "bucket": bucket["bucket"],
                "india_vix_level": round(vix, 4),
                "expected_range_bps": expected_range,
                "expected_abs_move_bps": expected_abs_move,
                "range_multiplier": (
                    round(expected_range / baseline_range, 4)
                    if expected_range is not None and baseline_range not in (None, 0.0)
                    else None
                ),
                "abs_move_multiplier": (
                    round(expected_abs_move / baseline_abs_move, 4)
                    if expected_abs_move is not None and baseline_abs_move not in (None, 0.0)
                    else None
                ),
                "sample_profile": bucket["sample_profile"],
                "source": "historical_india_vix_quintiles",
            }
    return {}


def _add_direction_evidence(items, *, feature, value, threshold, direction, note, comparison, weight=1.0):
    value = _safe_float(value, None)
    threshold = _safe_float(threshold, None)
    if value is None or threshold is None:
        return 0.0
    matched = value <= threshold if comparison == "lte" else value >= threshold
    if matched:
        items.append({"feature": feature, "value": round(value, 4), "threshold": threshold, "direction": direction, "note": note})
        return abs(weight) if direction == "CALL" else -abs(weight)
    return 0.0


def _build_global_directional_prior(global_risk_features, policy=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    features = global_risk_features if isinstance(global_risk_features, dict) else {}
    evidence = []
    score = 0.0
    score += _add_direction_evidence(
        evidence,
        feature="sp500_change_24h",
        value=features.get("sp500_change_24h"),
        threshold=_safe_float(_policy_value(policy, "sp500_bottom_quintile_pct"), SP500_BOTTOM_QUINTILE_PCT),
        direction="PUT",
        comparison="lte",
        note="S&P bottom historical quintile led weaker next-day NIFTY returns",
    )
    score += _add_direction_evidence(
        evidence,
        feature="sp500_change_24h",
        value=features.get("sp500_change_24h"),
        threshold=_safe_float(_policy_value(policy, "sp500_top_quintile_pct"), SP500_TOP_QUINTILE_PCT),
        direction="CALL",
        comparison="gte",
        note="S&P top historical quintile led stronger next-day NIFTY returns",
    )
    score += _add_direction_evidence(
        evidence,
        feature="nasdaq_change_24h",
        value=features.get("nasdaq_change_24h"),
        threshold=_safe_float(_policy_value(policy, "nasdaq_bottom_quintile_pct"), NASDAQ_BOTTOM_QUINTILE_PCT),
        direction="PUT",
        comparison="lte",
        note="Nasdaq bottom historical quintile reinforced risk-off direction",
        weight=_safe_float(_policy_value(policy, "nasdaq_direction_evidence_weight"), 0.75),
    )
    score += _add_direction_evidence(
        evidence,
        feature="nasdaq_change_24h",
        value=features.get("nasdaq_change_24h"),
        threshold=_safe_float(_policy_value(policy, "nasdaq_top_quintile_pct"), NASDAQ_TOP_QUINTILE_PCT),
        direction="CALL",
        comparison="gte",
        note="Nasdaq top historical quintile reinforced risk-on direction",
        weight=_safe_float(_policy_value(policy, "nasdaq_direction_evidence_weight"), 0.75),
    )
    score += _add_direction_evidence(
        evidence,
        feature="us_vix_change_24h",
        value=features.get("us_vix_change_24h", features.get("vix_change_24h")),
        threshold=_safe_float(_policy_value(policy, "us_vix_jump_quintile_pct"), US_VIX_JUMP_QUINTILE_PCT),
        direction="PUT",
        comparison="gte",
        note="US VIX jump historical quintile led weaker next-day NIFTY returns",
    )
    score += _add_direction_evidence(
        evidence,
        feature="us_vix_change_24h",
        value=features.get("us_vix_change_24h", features.get("vix_change_24h")),
        threshold=_safe_float(_policy_value(policy, "us_vix_drop_quintile_pct"), US_VIX_DROP_QUINTILE_PCT),
        direction="CALL",
        comparison="lte",
        note="US VIX drop historical quintile led stronger next-day NIFTY returns",
    )

    directional_threshold = _safe_float(_policy_value(policy, "global_prior_direction_threshold"), 1.0)
    if score >= directional_threshold:
        direction = "CALL"
    elif score <= -directional_threshold:
        direction = "PUT"
    else:
        direction = "NEUTRAL"
    preview_score_multiplier = _safe_float(_policy_value(policy, "global_prior_preview_score_multiplier"), 3.0)
    preview_probability_multiplier = _safe_float(
        _policy_value(policy, "global_prior_preview_probability_multiplier"),
        0.015,
    )
    preview_probability_cap = _safe_float(_policy_value(policy, "global_prior_preview_probability_cap"), 0.045)

    return {
        "prior_direction": direction,
        "prior_score": round(score, 4),
        "evidence_count": len(evidence),
        "evidence": evidence,
        "score_adjustment_preview": int(round(score * preview_score_multiplier)),
        "probability_adjustment_preview": round(
            max(min(score * preview_probability_multiplier, preview_probability_cap), -preview_probability_cap),
            4,
        ),
        "source": "historical_cross_asset_quintiles",
    }


def _build_pcr_context(volume_pcr, volume_pcr_atm, open_interest_pcr=None):
    oi_pcr_value = _safe_float(open_interest_pcr, None)
    volume_atm_value = _safe_float(volume_pcr_atm, None)
    volume_full_value = _safe_float(volume_pcr, None)
    pcr_value = oi_pcr_value if oi_pcr_value is not None else _safe_float(volume_atm_value, volume_full_value)
    basis = "OPEN_INTEREST" if oi_pcr_value is not None else ("VOLUME_ATM" if volume_atm_value is not None else "VOLUME")
    if pcr_value is None:
        return {
            "state": "UNAVAILABLE",
            "value": None,
            "open_interest_value": None,
            "volume_atm_value": _round(volume_atm_value, 4),
            "volume_value": _round(volume_full_value, 4),
            "basis": "UNAVAILABLE",
            "interpretation": "pcr_missing",
            "source_warning": "historical_finding_was_oi_pcr_live_value_may_be_volume_pcr",
        }
    if pcr_value >= PCR_HIGH_CONTEXT_THRESHOLD:
        state = "HIGH_PCR"
        interpretation = "support_or_pinning_context_not_automatic_bearish_signal"
    elif pcr_value <= PCR_LOW_CONTEXT_THRESHOLD:
        state = "LOW_PCR"
        interpretation = "call_dominant_context_needs_confirmation_from_flow"
    else:
        state = "MID_PCR"
        interpretation = "neutral_context"
    return {
        "state": state,
        "value": round(pcr_value, 4),
        "open_interest_value": _round(oi_pcr_value, 4),
        "volume_atm_value": _round(volume_atm_value, 4),
        "volume_value": _round(volume_full_value, 4),
        "basis": basis,
        "interpretation": interpretation,
        "source_warning": (
            None
            if basis == "OPEN_INTEREST"
            else "historical_finding_was_oi_pcr_live_value_may_be_volume_pcr"
        ),
    }


def _build_max_pain_context(max_pain_dist, spot, policy=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    dist = _safe_float(max_pain_dist, None)
    spot = _safe_float(spot, None)
    dist_pct = None
    if dist is not None and spot not in (None, 0.0):
        dist_pct = abs(dist / spot) * 100.0
    near_threshold = _safe_float(_policy_value(policy, "near_max_pain_threshold_pct"), NEAR_MAX_PAIN_THRESHOLD_PCT)
    near = dist_pct is not None and dist_pct <= near_threshold
    return {
        "state": "NEAR_MAX_PAIN" if near else ("FAR_FROM_MAX_PAIN" if dist_pct is not None else "UNAVAILABLE"),
        "distance_points": _round(dist, 2),
        "distance_pct": _round(dist_pct, 4),
        "interpretation": "pinning_or_friction_context_only",
        "directional_use": "disabled_recommended",
        "source": "historical_pull_toward_max_pain_hit_rate_below_edge_threshold",
    }


def _build_wall_context(market_state, spot, policy=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    market_state = market_state if isinstance(market_state, dict) else {}
    support = _safe_float(market_state.get("support_wall"), None)
    resistance = _safe_float(market_state.get("resistance_wall"), None)
    support_pct = _distance_pct(support, spot)
    resistance_pct = _distance_pct(resistance, spot)
    near_threshold = _safe_float(_policy_value(policy, "near_wall_threshold_pct"), NEAR_WALL_THRESHOLD_PCT)
    near_support = support_pct is not None and support_pct <= near_threshold
    near_resistance = resistance_pct is not None and resistance_pct <= near_threshold
    if near_support and near_resistance:
        state = "INSIDE_NEAR_TWO_SIDED_WALLS"
    elif near_support:
        state = "NEAR_SUPPORT_WALL"
    elif near_resistance:
        state = "NEAR_RESISTANCE_WALL"
    elif support_pct is None and resistance_pct is None:
        state = "UNAVAILABLE"
    else:
        state = "AWAY_FROM_NEAREST_WALL"
    return {
        "state": state,
        "support_wall": _round(support, 2),
        "resistance_wall": _round(resistance, 2),
        "support_distance_pct": _round(support_pct, 4),
        "resistance_distance_pct": _round(resistance_pct, 4),
        "interpretation": "walls_are_friction_and_breakout_context_not_hard_reversal_levels",
        "source": "historical_wall_proximity_profiles",
    }


def _clip(value, lower, upper):
    value = _safe_float(value, 0.0)
    return max(lower, min(upper, value))


def _bucket_from_thresholds(value, thresholds):
    value = _safe_float(value, None)
    if value is None or not isinstance(thresholds, list):
        return None
    for row in thresholds:
        if not isinstance(row, dict):
            continue
        label = row.get("label")
        upper = _safe_float(row.get("upper"), None)
        if upper is None or value <= upper:
            return str(label) if label not in (None, "") else None
    return None


def _artifact_vix_bucket(vol_bucket):
    return {
        "LOW": "low",
        "LOW_MID": "q2",
        "MID": "q3",
        "HIGH_MID": "q4",
        "HIGH": "high",
    }.get(str(vol_bucket or "").upper())


def _expiry_bucket(days_to_expiry, artifact, policy=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    thresholds = ((artifact.get("bucket_thresholds") or {}).get("expiry") or [])
    bucket = _bucket_from_thresholds(days_to_expiry, thresholds)
    if bucket:
        return bucket
    dte = _safe_float(days_to_expiry, None)
    if dte is None:
        return None
    if dte <= _safe_float(_policy_value(policy, "expiry_bucket_0_1d_upper"), 1.0):
        return "0-1d"
    if dte <= _safe_float(_policy_value(policy, "expiry_bucket_2_3d_upper"), 3.0):
        return "2-3d"
    if dte <= _safe_float(_policy_value(policy, "expiry_bucket_4_7d_upper"), 7.0):
        return "4-7d"
    if dte <= _safe_float(_policy_value(policy, "expiry_bucket_8_14d_upper"), 14.0):
        return "8-14d"
    return "15d+"


def _weekday_label(weekday=None, valuation_time=None):
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday_value = _safe_float(weekday, None)
    if weekday_value is None and valuation_time is not None:
        try:
            import pandas as _pd
            weekday_value = _pd.Timestamp(valuation_time).weekday()
        except Exception:
            weekday_value = None
    if weekday_value is None:
        return None
    idx = int(weekday_value)
    if idx < 0 or idx >= len(names):
        return None
    return names[idx]


def _extract_ret_20d_bps(market_state):
    ta_features = market_state.get("ta_features") if isinstance(market_state.get("ta_features"), dict) else {}
    indicators = ta_features.get("indicators") if isinstance(ta_features.get("indicators"), dict) else {}
    for value in (
        indicators.get("ret_20d_bps"),
        ta_features.get("ret_20d_bps"),
        market_state.get("ret_20d_bps"),
        market_state.get("nifty_ret_20d_bps"),
    ):
        parsed = _safe_float(value, None)
        if parsed is not None:
            return parsed
    return None


def _trend_20d_bucket(ret_20d_bps, artifact, policy=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    thresholds = ((artifact.get("bucket_thresholds") or {}).get("trend_20d") or [])
    bucket = _bucket_from_thresholds(ret_20d_bps, thresholds)
    if bucket:
        return bucket
    ret = _safe_float(ret_20d_bps, None)
    if ret is None:
        return None
    if ret <= _safe_float(_policy_value(policy, "trend_selloff_upper_bps"), -500.0):
        return "selloff"
    if ret <= _safe_float(_policy_value(policy, "trend_weak_upper_bps"), -150.0):
        return "weak"
    if ret <= _safe_float(_policy_value(policy, "trend_flat_upper_bps"), 150.0):
        return "flat"
    if ret <= _safe_float(_policy_value(policy, "trend_strong_upper_bps"), 500.0):
        return "strong"
    return "surge"


def _interaction_row(artifact, name, *key_parts):
    interactions = artifact.get("interactions") if isinstance(artifact.get("interactions"), dict) else {}
    section = interactions.get(name) if isinstance(interactions.get(name), dict) else {}
    rows = section.get("rows") if isinstance(section.get("rows"), dict) else {}
    key = "|".join(str(part) for part in key_parts if part not in (None, ""))
    row = rows.get(key)
    if not isinstance(row, dict):
        return None
    out = dict(row)
    out["interaction"] = name
    out["key"] = key
    out["target"] = section.get("target")
    return out


def _directional_bias_from_row(row, policy=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    mean_bps = _safe_float(row.get("mean_bps"), 0.0)
    hit_up = _safe_float(row.get("hit_up"), 0.5)
    mean_threshold = _safe_float(_policy_value(policy, "interaction_directional_mean_threshold_bps"), 5.0)
    call_hit_threshold = _safe_float(_policy_value(policy, "interaction_call_hit_up_threshold"), 0.58)
    put_hit_threshold = _safe_float(_policy_value(policy, "interaction_put_hit_up_threshold"), 0.45)
    if mean_bps >= mean_threshold or hit_up >= call_hit_threshold:
        return "CALL"
    if mean_bps <= -mean_threshold or hit_up <= put_hit_threshold:
        return "PUT"
    return "NEUTRAL"


def _directional_interaction_modifier(row, direction, policy=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    bias = _directional_bias_from_row(row, policy=policy)
    direction_upper = str(direction or "").upper().strip()
    mean_bps = _safe_float(row.get("mean_bps"), 0.0)
    hit_up = _safe_float(row.get("hit_up"), 0.5)
    n = _safe_float(row.get("n"), 0.0)
    if bias == "NEUTRAL" or direction_upper not in {"CALL", "PUT"}:
        sign = 0
    elif direction_upper == bias:
        sign = 1
    else:
        sign = -1

    mean_threshold = _safe_float(_policy_value(policy, "interaction_directional_mean_threshold_bps"), 5.0)
    edge_divisor = _safe_float(_policy_value(policy, "interaction_edge_mean_divisor_bps"), 7.0)
    edge_min = int(_safe_float(_policy_value(policy, "interaction_edge_min"), 1))
    edge_max = int(_safe_float(_policy_value(policy, "interaction_edge_max"), 4))
    strong_call_hit_threshold = _safe_float(_policy_value(policy, "interaction_strong_call_hit_up_threshold"), 0.62)
    strong_put_hit_threshold = _safe_float(_policy_value(policy, "interaction_strong_put_hit_up_threshold"), 0.46)
    full_edge_sample = _safe_float(_policy_value(policy, "interaction_min_sample_for_full_edge"), 80)
    edge_strength = (
        min(edge_max, max(edge_min, int(round(abs(mean_bps) / edge_divisor))))
        if abs(mean_bps) >= mean_threshold and edge_divisor not in (None, 0.0)
        else 0
    )
    if hit_up >= strong_call_hit_threshold or hit_up <= strong_put_hit_threshold:
        edge_strength = min(edge_max + 1, edge_strength + 1)
    if n < full_edge_sample:
        edge_strength = max(0, edge_strength - 1)

    score_adjustment = sign * edge_strength
    probability_cap = _safe_float(_policy_value(policy, "interaction_probability_cap"), 0.025)
    probability_divisor = _safe_float(_policy_value(policy, "interaction_probability_mean_divisor_bps"), 1200.0)
    probability_adjustment = (
        sign * min(probability_cap, abs(mean_bps) / probability_divisor)
        if edge_strength and probability_divisor not in (None, 0.0)
        else 0.0
    )
    threshold_adjustment = 0
    composite_adjustment = 0
    size_multiplier = 1.0
    if sign < 0 and edge_strength >= _safe_float(_policy_value(policy, "interaction_conflict_edge_threshold"), 2):
        threshold_adjustment = int(_safe_float(_policy_value(policy, "interaction_conflict_threshold_adjustment"), 1))
        composite_adjustment = int(_safe_float(_policy_value(policy, "interaction_conflict_composite_adjustment"), 1))
        size_multiplier = _safe_float(_policy_value(policy, "interaction_conflict_size_multiplier"), 0.90)
    elif sign > 0 and edge_strength >= _safe_float(_policy_value(policy, "interaction_aligned_edge_threshold"), 3):
        threshold_adjustment = int(_safe_float(_policy_value(policy, "interaction_aligned_threshold_adjustment"), -1))

    return {
        "interaction": row.get("interaction"),
        "key": row.get("key"),
        "bias": bias,
        "direction": direction_upper or None,
        "n": int(n),
        "mean_bps": round(mean_bps, 4),
        "hit_up": round(hit_up, 4),
        "score_adjustment": score_adjustment,
        "probability_adjustment": round(probability_adjustment, 4),
        "trade_strength_threshold_adjustment": threshold_adjustment,
        "composite_threshold_adjustment": composite_adjustment,
        "size_multiplier": size_multiplier,
    }


def _range_interaction_modifier(row, policy=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    mean_range = _safe_float(row.get("mean_bps"), None)
    if mean_range is None:
        return None
    baseline_range = _safe_float(_policy_value(policy, "baseline_expected_range_bps"), BASELINE_EXPECTED_RANGE_BPS)
    if baseline_range in (None, 0.0):
        return None
    multiplier = mean_range / baseline_range
    if multiplier >= _safe_float(_policy_value(policy, "range_interaction_high_multiplier"), 1.25):
        score_adjustment = int(_safe_float(_policy_value(policy, "range_interaction_high_score_adjustment"), 2))
        probability_adjustment = _safe_float(
            _policy_value(policy, "range_interaction_high_probability_adjustment"),
            0.015,
        )
        threshold_adjustment = int(_safe_float(_policy_value(policy, "range_interaction_high_threshold_adjustment"), -1))
        reason = "high_range_weekday_vix_interaction"
    elif multiplier <= _safe_float(_policy_value(policy, "range_interaction_low_multiplier"), 0.75):
        score_adjustment = int(_safe_float(_policy_value(policy, "range_interaction_low_score_adjustment"), -3))
        probability_adjustment = _safe_float(
            _policy_value(policy, "range_interaction_low_probability_adjustment"),
            -0.025,
        )
        threshold_adjustment = int(_safe_float(_policy_value(policy, "range_interaction_low_threshold_adjustment"), 1))
        reason = "low_range_weekday_vix_interaction"
    else:
        score_adjustment = 0
        probability_adjustment = 0.0
        threshold_adjustment = 0
        reason = "neutral_range_weekday_vix_interaction"
    low_size_multiplier = _safe_float(_policy_value(policy, "range_interaction_low_size_multiplier"), 0.92)
    return {
        "interaction": row.get("interaction"),
        "key": row.get("key"),
        "n": int(_safe_float(row.get("n"), 0.0)),
        "expected_range_bps": round(mean_range, 4),
        "range_multiplier": round(multiplier, 4),
        "score_adjustment": score_adjustment,
        "probability_adjustment": round(probability_adjustment, 4),
        "trade_strength_threshold_adjustment": threshold_adjustment,
        "composite_threshold_adjustment": 0,
        "size_multiplier": (
            1.0
            if multiplier > _safe_float(_policy_value(policy, "range_interaction_low_multiplier"), 0.75)
            else low_size_multiplier
        ),
        "reason": reason,
    }


def _build_interaction_context(
    *,
    artifact,
    market_state,
    vol_context,
    pcr_context,
    direction,
    valuation_time=None,
    weekday=None,
    policy=None,
):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    artifact = artifact if isinstance(artifact, dict) else {}
    thresholds = artifact.get("bucket_thresholds") if isinstance(artifact.get("bucket_thresholds"), dict) else {}

    pcr_value = pcr_context.get("value") if isinstance(pcr_context, dict) else None
    pcr_bucket = _bucket_from_thresholds(pcr_value, thresholds.get("pcr_oi")) or str(pcr_context.get("state") or "").lower().replace("_pcr", "")
    vix_bucket = _artifact_vix_bucket(vol_context.get("bucket") if isinstance(vol_context, dict) else None)
    expiry_bucket = _expiry_bucket(market_state.get("days_to_expiry"), artifact, policy=policy)
    ret_20d_bps = _extract_ret_20d_bps(market_state)
    trend_bucket = _trend_20d_bucket(ret_20d_bps, artifact, policy=policy)
    weekday_name = _weekday_label(weekday=weekday, valuation_time=valuation_time)

    matched = []
    directional_modifiers = []
    range_modifier = None

    row = _interaction_row(artifact, "expiry_x_pcr", expiry_bucket, pcr_bucket)
    if row:
        modifier = _directional_interaction_modifier(row, direction, policy=policy)
        matched.append(row)
        directional_modifiers.append(modifier)

    row = _interaction_row(artifact, "india_vix_x_trend", vix_bucket, trend_bucket)
    if row:
        modifier = _directional_interaction_modifier(row, direction, policy=policy)
        matched.append(row)
        directional_modifiers.append(modifier)

    row = _interaction_row(artifact, "weekday_x_vix", weekday_name, vix_bucket)
    if row:
        matched.append(row)
        range_modifier = _range_interaction_modifier(row, policy=policy)

    score_adjustment = sum(int(_safe_float(item.get("score_adjustment"), 0.0)) for item in directional_modifiers)
    probability_adjustment = sum(_safe_float(item.get("probability_adjustment"), 0.0) for item in directional_modifiers)
    threshold_adjustment = sum(int(_safe_float(item.get("trade_strength_threshold_adjustment"), 0.0)) for item in directional_modifiers)
    composite_adjustment = sum(int(_safe_float(item.get("composite_threshold_adjustment"), 0.0)) for item in directional_modifiers)
    size_multiplier = 1.0
    for item in directional_modifiers:
        size_multiplier = min(size_multiplier, _safe_float(item.get("size_multiplier"), 1.0))
    if range_modifier:
        score_adjustment += int(_safe_float(range_modifier.get("score_adjustment"), 0.0))
        probability_adjustment += _safe_float(range_modifier.get("probability_adjustment"), 0.0)
        threshold_adjustment += int(_safe_float(range_modifier.get("trade_strength_threshold_adjustment"), 0.0))
        composite_adjustment += int(_safe_float(range_modifier.get("composite_threshold_adjustment"), 0.0))
        size_multiplier = min(size_multiplier, _safe_float(range_modifier.get("size_multiplier"), 1.0))

    reasons = []
    for item in directional_modifiers:
        interaction = item.get("interaction")
        bias = item.get("bias")
        if item.get("score_adjustment", 0) > 0:
            reasons.append(f"{interaction}_aligned_{bias.lower()}")
        elif item.get("score_adjustment", 0) < 0:
            reasons.append(f"{interaction}_conflicts_{bias.lower()}")
    if range_modifier and range_modifier.get("reason"):
        reasons.append(range_modifier["reason"])

    return {
        "artifact_version": artifact.get("artifact_version"),
        "source_run_id": artifact.get("source_run_id"),
        "bucket_state": {
            "expiry_bucket": expiry_bucket,
            "pcr_oi_bucket": pcr_bucket,
            "pcr_basis": pcr_context.get("basis") if isinstance(pcr_context, dict) else None,
            "pcr_value": _round(pcr_value, 4),
            "india_vix_bucket": vix_bucket,
            "trend_20d_bucket": trend_bucket,
            "ret_20d_bps": _round(ret_20d_bps, 4),
            "weekday": weekday_name,
        },
        "matched_count": len(matched),
        "matched_interactions": matched,
        "directional_modifiers": directional_modifiers,
        "range_modifier": range_modifier,
        "score_adjustment": int(
            round(
                _clip(
                    score_adjustment,
                    _safe_float(_policy_value(policy, "interaction_score_clip_min"), -6),
                    _safe_float(_policy_value(policy, "interaction_score_clip_max"), 6),
                )
            )
        ),
        "probability_adjustment": round(
            _clip(
                probability_adjustment,
                _safe_float(_policy_value(policy, "interaction_probability_clip_min"), -0.040),
                _safe_float(_policy_value(policy, "interaction_probability_clip_max"), 0.040),
            ),
            4,
        ),
        "trade_strength_threshold_adjustment": int(
            round(
                _clip(
                    threshold_adjustment,
                    _safe_float(_policy_value(policy, "interaction_threshold_clip_min"), -2),
                    _safe_float(_policy_value(policy, "interaction_threshold_clip_max"), 3),
                )
            )
        ),
        "composite_threshold_adjustment": int(
            round(
                _clip(
                    composite_adjustment,
                    _safe_float(_policy_value(policy, "interaction_composite_clip_min"), -1),
                    _safe_float(_policy_value(policy, "interaction_composite_clip_max"), 2),
                )
            )
        ),
        "size_multiplier": round(
            _clip(
                size_multiplier,
                _safe_float(_policy_value(policy, "interaction_size_clip_min"), 0.75),
                _safe_float(_policy_value(policy, "interaction_size_clip_max"), 1.0),
            ),
            4,
        ),
        "reasons": reasons,
    }


def _build_live_modifiers(context, direction, policy=None):
    policy = policy if isinstance(policy, dict) else HISTORICAL_CONTEXT_POLICY
    direction_upper = str(direction or "").upper().strip()
    if direction_upper not in {"CALL", "PUT"}:
        direction_upper = None

    vol_ctx = context.get("volatility_context") if isinstance(context.get("volatility_context"), dict) else {}
    prior_ctx = context.get("global_directional_prior") if isinstance(context.get("global_directional_prior"), dict) else {}
    pcr_ctx = context.get("pcr_context") if isinstance(context.get("pcr_context"), dict) else {}
    max_pain_ctx = context.get("max_pain_context") if isinstance(context.get("max_pain_context"), dict) else {}
    wall_ctx = context.get("wall_context") if isinstance(context.get("wall_context"), dict) else {}
    interaction_ctx = context.get("interaction_context") if isinstance(context.get("interaction_context"), dict) else {}
    statistical_ctx = context.get("statistical_market_context") if isinstance(context.get("statistical_market_context"), dict) else {}

    components = {}
    reasons = []
    score_adjustment = 0
    probability_adjustment = 0.0
    trade_strength_threshold_adjustment = 0
    composite_threshold_adjustment = 0
    size_multiplier = 1.0
    direction_override = None

    bucket = str(vol_ctx.get("bucket") or "").upper()
    vol_bucket_score_adjustments, vol_bucket_probability_adjustments = _vol_adjustments_from_policy(policy)
    if bucket in vol_bucket_score_adjustments:
        vol_score = int(vol_bucket_score_adjustments[bucket])
        vol_probability = float(vol_bucket_probability_adjustments[bucket])
        score_adjustment += vol_score
        probability_adjustment += vol_probability
        components["volatility_bucket"] = {
            "bucket": bucket,
            "score_adjustment": vol_score,
            "probability_adjustment": round(vol_probability, 4),
        }
        reasons.append(f"historical_vol_bucket_{bucket.lower()}")

    prior_direction = str(prior_ctx.get("prior_direction") or "").upper().strip()
    prior_score = _safe_float(prior_ctx.get("prior_score"), 0.0)
    abs_prior = abs(prior_score)
    if prior_direction in {"CALL", "PUT"}:
        prior_score_adjustment = 0
        prior_probability_adjustment = 0.0
        if direction_upper is None and abs_prior >= _safe_float(
            _policy_value(policy, "strong_prior_override_score"),
            STRONG_PRIOR_OVERRIDE_SCORE,
        ):
            direction_override = prior_direction
            prior_score_adjustment = min(
                int(_safe_float(_policy_value(policy, "prior_override_score_cap"), 6)),
                int(round(abs_prior * _safe_float(_policy_value(policy, "prior_override_score_multiplier"), 2.0))),
            )
            prior_probability_adjustment = min(
                _safe_float(_policy_value(policy, "prior_override_probability_cap"), 0.035),
                abs_prior * _safe_float(_policy_value(policy, "prior_override_probability_multiplier"), 0.012),
            )
            score_adjustment += prior_score_adjustment
            probability_adjustment += prior_probability_adjustment
            trade_strength_threshold_adjustment += int(
                _safe_float(_policy_value(policy, "prior_override_threshold_adjustment"), -1)
            )
            reasons.append("historical_global_prior_direction_fallback")
        elif direction_upper == prior_direction:
            prior_score_adjustment = min(
                int(_safe_float(_policy_value(policy, "prior_aligned_score_cap"), 8)),
                int(round(abs_prior * _safe_float(_policy_value(policy, "prior_aligned_score_multiplier"), 3.0))),
            )
            prior_probability_adjustment = min(
                _safe_float(_policy_value(policy, "prior_aligned_probability_cap"), 0.045),
                abs_prior * _safe_float(_policy_value(policy, "prior_aligned_probability_multiplier"), 0.015),
            )
            score_adjustment += prior_score_adjustment
            probability_adjustment += prior_probability_adjustment
            strong_prior_score = _safe_float(_policy_value(policy, "prior_aligned_strong_score"), 2.0)
            trade_strength_threshold_adjustment += int(
                _safe_float(
                    _policy_value(
                        policy,
                        "prior_aligned_strong_threshold_adjustment"
                        if abs_prior >= strong_prior_score
                        else "prior_aligned_threshold_adjustment",
                    ),
                    -2 if abs_prior >= strong_prior_score else -1,
                )
            )
            composite_threshold_adjustment += (
                int(_safe_float(_policy_value(policy, "prior_aligned_strong_composite_adjustment"), -1))
                if abs_prior >= strong_prior_score
                else 0
            )
            reasons.append("historical_global_prior_aligned")
        elif direction_upper in {"CALL", "PUT"}:
            prior_score_adjustment = -min(
                int(_safe_float(_policy_value(policy, "prior_conflict_score_cap"), 10)),
                int(round(abs_prior * _safe_float(_policy_value(policy, "prior_conflict_score_multiplier"), 4.0))),
            )
            prior_probability_adjustment = -min(
                _safe_float(_policy_value(policy, "prior_conflict_probability_cap"), 0.050),
                abs_prior * _safe_float(_policy_value(policy, "prior_conflict_probability_multiplier"), 0.018),
            )
            score_adjustment += prior_score_adjustment
            probability_adjustment += prior_probability_adjustment
            trade_strength_threshold_adjustment += int(
                _safe_float(_policy_value(policy, "prior_conflict_threshold_adjustment"), 3)
            )
            composite_threshold_adjustment += int(
                _safe_float(_policy_value(policy, "prior_conflict_composite_adjustment"), 2)
            )
            size_multiplier = min(
                size_multiplier,
                _safe_float(_policy_value(policy, "prior_conflict_size_multiplier"), 0.75),
            )
            reasons.append("historical_global_prior_conflict")
        components["global_directional_prior"] = {
            "prior_direction": prior_direction,
            "prior_score": round(prior_score, 4),
            "direction": direction_upper,
            "direction_override": direction_override,
            "score_adjustment": prior_score_adjustment,
            "probability_adjustment": round(prior_probability_adjustment, 4),
        }

    effective_direction = direction_upper or direction_override
    pcr_state = str(pcr_ctx.get("state") or "").upper()
    if pcr_state == "HIGH_PCR":
        if effective_direction == "PUT":
            pcr_score_adjustment = int(_safe_float(_policy_value(policy, "pcr_high_put_score_adjustment"), -4))
            pcr_probability_adjustment = _safe_float(
                _policy_value(policy, "pcr_high_put_probability_adjustment"),
                -0.020,
            )
            trade_strength_threshold_adjustment += int(
                _safe_float(_policy_value(policy, "pcr_high_put_threshold_adjustment"), 2)
            )
            composite_threshold_adjustment += int(
                _safe_float(_policy_value(policy, "pcr_high_put_composite_adjustment"), 1)
            )
            size_multiplier = min(size_multiplier, _safe_float(_policy_value(policy, "pcr_high_put_size_multiplier"), 0.85))
            reasons.append("historical_high_pcr_dampens_put")
        elif effective_direction == "CALL":
            pcr_score_adjustment = int(_safe_float(_policy_value(policy, "pcr_high_call_score_adjustment"), 2))
            pcr_probability_adjustment = _safe_float(
                _policy_value(policy, "pcr_high_call_probability_adjustment"),
                0.010,
            )
            reasons.append("historical_high_pcr_supports_call")
        else:
            pcr_score_adjustment = int(_safe_float(_policy_value(policy, "pcr_high_neutral_score_adjustment"), -1))
            pcr_probability_adjustment = _safe_float(
                _policy_value(policy, "pcr_high_neutral_probability_adjustment"),
                -0.005,
            )
            reasons.append("historical_high_pcr_pinning")
        score_adjustment += pcr_score_adjustment
        probability_adjustment += pcr_probability_adjustment
        components["pcr_context"] = {
            "state": pcr_state,
            "score_adjustment": pcr_score_adjustment,
            "probability_adjustment": round(pcr_probability_adjustment, 4),
        }

    max_pain_state = str(max_pain_ctx.get("state") or "").upper()
    if max_pain_state == "NEAR_MAX_PAIN":
        max_pain_score_adjustment = int(_safe_float(_policy_value(policy, "near_max_pain_score_adjustment"), -2))
        max_pain_probability_adjustment = _safe_float(
            _policy_value(policy, "near_max_pain_probability_adjustment"),
            -0.010,
        )
        score_adjustment += max_pain_score_adjustment
        probability_adjustment += max_pain_probability_adjustment
        trade_strength_threshold_adjustment += int(
            _safe_float(_policy_value(policy, "near_max_pain_threshold_adjustment"), 1)
        )
        size_multiplier = min(
            size_multiplier,
            _safe_float(_policy_value(policy, "near_max_pain_size_multiplier"), 0.90),
        )
        components["max_pain_context"] = {
            "state": max_pain_state,
            "score_adjustment": max_pain_score_adjustment,
            "probability_adjustment": round(max_pain_probability_adjustment, 4),
        }
        reasons.append("historical_max_pain_friction")

    wall_state = str(wall_ctx.get("state") or "").upper()
    wall_score_adjustment = 0
    wall_probability_adjustment = 0.0
    if wall_state == "INSIDE_NEAR_TWO_SIDED_WALLS":
        wall_score_adjustment = int(_safe_float(_policy_value(policy, "wall_two_sided_score_adjustment"), -2))
        wall_probability_adjustment = _safe_float(
            _policy_value(policy, "wall_two_sided_probability_adjustment"),
            -0.010,
        )
        trade_strength_threshold_adjustment += int(
            _safe_float(_policy_value(policy, "wall_two_sided_threshold_adjustment"), 1)
        )
        size_multiplier = min(size_multiplier, _safe_float(_policy_value(policy, "wall_two_sided_size_multiplier"), 0.90))
        reasons.append("historical_two_sided_wall_friction")
    elif wall_state == "NEAR_RESISTANCE_WALL":
        if effective_direction == "CALL":
            wall_score_adjustment = int(_safe_float(_policy_value(policy, "wall_direction_friction_score_adjustment"), -3))
            wall_probability_adjustment = _safe_float(
                _policy_value(policy, "wall_direction_friction_probability_adjustment"),
                -0.015,
            )
            trade_strength_threshold_adjustment += int(
                _safe_float(_policy_value(policy, "wall_direction_friction_threshold_adjustment"), 1)
            )
            size_multiplier = min(
                size_multiplier,
                _safe_float(_policy_value(policy, "wall_direction_friction_size_multiplier"), 0.88),
            )
            reasons.append("historical_resistance_wall_call_friction")
        elif effective_direction == "PUT":
            wall_score_adjustment = int(_safe_float(_policy_value(policy, "wall_opposite_support_score_adjustment"), 1))
            wall_probability_adjustment = _safe_float(
                _policy_value(policy, "wall_opposite_support_probability_adjustment"),
                0.005,
            )
            reasons.append("historical_resistance_wall_supports_put")
    elif wall_state == "NEAR_SUPPORT_WALL":
        if effective_direction == "PUT":
            wall_score_adjustment = int(_safe_float(_policy_value(policy, "wall_direction_friction_score_adjustment"), -3))
            wall_probability_adjustment = _safe_float(
                _policy_value(policy, "wall_direction_friction_probability_adjustment"),
                -0.015,
            )
            trade_strength_threshold_adjustment += int(
                _safe_float(_policy_value(policy, "wall_direction_friction_threshold_adjustment"), 1)
            )
            size_multiplier = min(
                size_multiplier,
                _safe_float(_policy_value(policy, "wall_direction_friction_size_multiplier"), 0.88),
            )
            reasons.append("historical_support_wall_put_friction")
        elif effective_direction == "CALL":
            wall_score_adjustment = int(_safe_float(_policy_value(policy, "wall_opposite_support_score_adjustment"), 1))
            wall_probability_adjustment = _safe_float(
                _policy_value(policy, "wall_opposite_support_probability_adjustment"),
                0.005,
            )
            reasons.append("historical_support_wall_supports_call")
    if wall_score_adjustment or wall_probability_adjustment:
        score_adjustment += wall_score_adjustment
        probability_adjustment += wall_probability_adjustment
        components["wall_context"] = {
            "state": wall_state,
            "score_adjustment": wall_score_adjustment,
            "probability_adjustment": round(wall_probability_adjustment, 4),
        }

    interaction_score_adjustment = int(_safe_float(interaction_ctx.get("score_adjustment"), 0.0))
    interaction_probability_adjustment = _safe_float(interaction_ctx.get("probability_adjustment"), 0.0)
    if interaction_score_adjustment or interaction_probability_adjustment:
        score_adjustment += interaction_score_adjustment
        probability_adjustment += interaction_probability_adjustment
        trade_strength_threshold_adjustment += int(
            _safe_float(interaction_ctx.get("trade_strength_threshold_adjustment"), 0.0)
        )
        composite_threshold_adjustment += int(_safe_float(interaction_ctx.get("composite_threshold_adjustment"), 0.0))
        size_multiplier = min(size_multiplier, _safe_float(interaction_ctx.get("size_multiplier"), 1.0))
        components["interaction_context"] = {
            "matched_count": interaction_ctx.get("matched_count", 0),
            "score_adjustment": interaction_score_adjustment,
            "probability_adjustment": round(interaction_probability_adjustment, 4),
            "reasons": interaction_ctx.get("reasons", []),
        }
        reasons.extend(str(item) for item in interaction_ctx.get("reasons", []) if item)

    statistical_score_adjustment = int(_safe_float(statistical_ctx.get("score_adjustment"), 0.0))
    statistical_probability_adjustment = _safe_float(statistical_ctx.get("probability_adjustment"), 0.0)
    statistical_threshold_adjustment = int(_safe_float(statistical_ctx.get("trade_strength_threshold_adjustment"), 0.0))
    statistical_composite_adjustment = int(_safe_float(statistical_ctx.get("composite_threshold_adjustment"), 0.0))
    statistical_size_multiplier = _safe_float(statistical_ctx.get("size_multiplier"), 1.0)
    if statistical_ctx.get("applied") and (
        statistical_score_adjustment
        or statistical_probability_adjustment
        or statistical_threshold_adjustment
        or statistical_composite_adjustment
        or statistical_size_multiplier < 1.0
    ):
        score_adjustment += statistical_score_adjustment
        probability_adjustment += statistical_probability_adjustment
        trade_strength_threshold_adjustment += statistical_threshold_adjustment
        composite_threshold_adjustment += statistical_composite_adjustment
        size_multiplier = min(size_multiplier, statistical_size_multiplier)
        components["statistical_market_context"] = {
            "expected_range_prior": statistical_ctx.get("expected_range_prior"),
            "directional_followthrough_prior": statistical_ctx.get("directional_followthrough_prior"),
            "vol_stress_score": statistical_ctx.get("vol_stress_score"),
            "regime_confidence": statistical_ctx.get("regime_confidence"),
            "hold_time_hint": statistical_ctx.get("hold_time_hint"),
            "score_adjustment": statistical_score_adjustment,
            "probability_adjustment": round(statistical_probability_adjustment, 4),
            "trade_strength_threshold_adjustment": statistical_threshold_adjustment,
            "size_multiplier": statistical_size_multiplier,
            "reasons": statistical_ctx.get("reasons", []),
        }
        reasons.extend(str(item) for item in statistical_ctx.get("reasons", []) if item)

    score_adjustment = int(
        round(
            _clip(
                score_adjustment,
                _safe_float(_policy_value(policy, "live_score_clip_min"), -14),
                _safe_float(_policy_value(policy, "live_score_clip_max"), 12),
            )
        )
    )
    probability_adjustment = round(
        _clip(
            probability_adjustment,
            _safe_float(_policy_value(policy, "live_probability_clip_min"), -0.080),
            _safe_float(_policy_value(policy, "live_probability_clip_max"), 0.080),
        ),
        4,
    )
    trade_strength_threshold_adjustment = int(
        round(
            _clip(
                trade_strength_threshold_adjustment,
                _safe_float(_policy_value(policy, "live_trade_strength_threshold_clip_min"), -3),
                _safe_float(_policy_value(policy, "live_trade_strength_threshold_clip_max"), 6),
            )
        )
    )
    composite_threshold_adjustment = int(
        round(
            _clip(
                composite_threshold_adjustment,
                _safe_float(_policy_value(policy, "live_composite_threshold_clip_min"), -2),
                _safe_float(_policy_value(policy, "live_composite_threshold_clip_max"), 5),
            )
        )
    )
    size_multiplier = round(
        _clip(
            size_multiplier,
            _safe_float(_policy_value(policy, "live_size_clip_min"), 0.50),
            _safe_float(_policy_value(policy, "live_size_clip_max"), 1.0),
        ),
        4,
    )

    return {
        "applied": True,
        "score_adjustment": score_adjustment,
        "probability_adjustment": probability_adjustment,
        "trade_strength_threshold_adjustment": trade_strength_threshold_adjustment,
        "composite_threshold_adjustment": composite_threshold_adjustment,
        "size_multiplier": size_multiplier,
        "direction_override": direction_override,
        "components": components,
        "reasons": reasons,
    }


def build_historical_context(
    *,
    spot=None,
    market_state=None,
    global_risk_state=None,
    direction=None,
    valuation_time=None,
    weekday=None,
    artifact=None,
):
    """
    Return live-applied historical priors from the historical insight layer.
    """

    historical_policy = get_historical_context_policy()
    market_state = market_state if isinstance(market_state, dict) else {}
    global_risk_state = global_risk_state if isinstance(global_risk_state, dict) else {}
    global_risk_features = global_risk_state.get("global_risk_features")
    global_risk_features = global_risk_features if isinstance(global_risk_features, dict) else {}

    vix_level = global_risk_features.get("india_vix_level")
    if vix_level is None:
        vix_level = market_state.get("atm_iv")

    vol_context = _classify_vix_bucket(vix_level, policy=historical_policy)
    global_prior = _build_global_directional_prior(global_risk_features, policy=historical_policy)
    pcr_context = _build_pcr_context(
        market_state.get("volume_pcr"),
        market_state.get("volume_pcr_atm"),
        market_state.get("open_interest_pcr", market_state.get("oi_pcr")),
    )
    max_pain_context = _build_max_pain_context(market_state.get("max_pain_dist"), spot, policy=historical_policy)
    wall_context = _build_wall_context(market_state, spot, policy=historical_policy)
    prior_artifact = artifact if isinstance(artifact, dict) else load_historical_prior_artifact()
    interaction_context = _build_interaction_context(
        artifact=prior_artifact,
        market_state=market_state,
        vol_context=vol_context,
        pcr_context=pcr_context,
        direction=direction,
        valuation_time=valuation_time,
        weekday=weekday,
        policy=historical_policy,
    )
    statistical_market_context = build_statistical_market_context(
        spot=spot,
        market_state=market_state,
        global_risk_state=global_risk_state,
        direction=direction,
        valuation_time=valuation_time,
        weekday=weekday,
    )

    primary_notes = []
    if vol_context.get("bucket") not in {None, "UNAVAILABLE"}:
        primary_notes.append(f"vol_bucket={vol_context['bucket']}")
    if global_prior.get("prior_direction") != "NEUTRAL":
        primary_notes.append(f"global_prior={global_prior['prior_direction']}:{global_prior['prior_score']}")
    if pcr_context.get("state") == "HIGH_PCR":
        primary_notes.append("high_pcr_as_pinning_not_bearish")
    if max_pain_context.get("state") == "NEAR_MAX_PAIN":
        primary_notes.append("near_max_pain_friction")
    if wall_context.get("state") not in {"UNAVAILABLE", "AWAY_FROM_NEAREST_WALL"}:
        primary_notes.append(wall_context["state"].lower())
    if interaction_context.get("matched_count"):
        primary_notes.append(f"interactions={interaction_context['matched_count']}")
    if statistical_market_context.get("applied"):
        if statistical_market_context.get("expected_range_prior") not in {None, "UNAVAILABLE"}:
            primary_notes.append(f"stat_range={statistical_market_context['expected_range_prior']}")
        if statistical_market_context.get("directional_followthrough_prior") not in {None, "NEUTRAL"}:
            primary_notes.append(f"stat_direction={statistical_market_context['directional_followthrough_prior']}")

    context = {
        "version": HISTORICAL_CONTEXT_VERSION,
        "policy_version": historical_policy.get("policy_version", HISTORICAL_CONTEXT_POLICY_VERSION),
        "policy_source": "config.historical_context_policy",
        "decision_mode": HISTORICAL_CONTEXT_DECISION_MODE,
        "prior_artifact_version": prior_artifact.get("artifact_version"),
        "prior_artifact_source_run_id": prior_artifact.get("source_run_id"),
        "source_report": "research/ml_research/historical_insights/latest_historical_insight_report.md",
        "volatility_context": vol_context,
        "global_directional_prior": global_prior,
        "pcr_context": pcr_context,
        "max_pain_context": max_pain_context,
        "wall_context": wall_context,
        "interaction_context": interaction_context,
        "statistical_market_context": statistical_market_context,
        "primary_notes": primary_notes,
        "score_adjustment_preview": global_prior.get("score_adjustment_preview", 0),
        "probability_adjustment_preview": global_prior.get("probability_adjustment_preview", 0.0),
        "apply_to_live_decision": True,
    }
    live_modifiers = _build_live_modifiers(context, direction, policy=historical_policy)
    context["live_modifiers"] = live_modifiers
    context["score_adjustment"] = live_modifiers["score_adjustment"]
    context["probability_adjustment"] = live_modifiers["probability_adjustment"]
    context["trade_strength_threshold_adjustment"] = live_modifiers["trade_strength_threshold_adjustment"]
    context["composite_threshold_adjustment"] = live_modifiers["composite_threshold_adjustment"]
    context["size_multiplier"] = live_modifiers["size_multiplier"]
    context["direction_override"] = live_modifiers["direction_override"]
    return context

"""
Module: ta_indicators.py

Purpose:
    Compute technical analysis indicators from historical spot price data
    to generate trading signals for the options quant engine.

Role in the System:
    Part of the features layer that provides TA-based signals for signal aggregation.
    Computes indicators like RSI, MACD, moving averages from OHLC data.

Key Outputs:
    Dictionary with TA signals: direction, confidence, regime labels.

Downstream Usage:
    Consumed by signal evaluation for combining with quant signals.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config.analytics_feature_policy import (
    TechnicalAnalysisPolicyConfig,
    get_technical_analysis_policy_config,
)
from data.historical_spot_fetcher import get_recent_spot_history
from data.spot_history import load_spot_history

logger = logging.getLogger(__name__)


def _no_ta_signal(regime: str, *, warning: str | None = None) -> dict:
    payload = {
        "ta_direction": "NO_SIGNAL",
        "ta_confidence": 0.0,
        "ta_regime": regime,
        "indicators": {},
    }
    if warning:
        payload["ta_warning"] = warning
    return payload


def _empty_candle_features(status: str, *, warning: str | None = None) -> dict:
    payload = {
        "ta_candle_status": status,
        "ta_candle_direction": "NO_SIGNAL",
        "ta_candle_state": "CANDLE_UNAVAILABLE",
        "ta_candle_confidence": 0.0,
        "ta_entry_timing_state": "CANDLE_UNAVAILABLE",
        "ta_entry_timing_score": 0.0,
        "ta_entry_timing_reasons": "",
    }
    if warning:
        payload["ta_candle_warning"] = warning
    return payload


def _prepare_history_frame(hist_df: pd.DataFrame | None, *, as_of=None) -> pd.DataFrame:
    if hist_df is None or hist_df.empty:
        return pd.DataFrame()

    df = hist_df.copy()
    if "close" not in df.columns and "Close" in df.columns:
        df["close"] = df["Close"]

    if as_of is not None and "timestamp" in df.columns:
        try:
            history_ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
            as_of_ts = pd.Timestamp(as_of)
            if as_of_ts.tzinfo is None:
                as_of_ts = as_of_ts.tz_localize("Asia/Kolkata")
            else:
                as_of_ts = as_of_ts.tz_convert("Asia/Kolkata")
            df = df[history_ts <= as_of_ts.tz_convert("UTC")]
        except Exception as exc:
            logger.warning("Unable to filter TA history as_of=%r: %s", as_of, exc)

    return df.dropna(subset=["close"]) if "close" in df.columns else pd.DataFrame()


def build_ta_features(
    symbol: str,
    current_spot: float,
    days_history: int | None = None,
    *,
    history_df: pd.DataFrame | None = None,
    intraday_history_df: pd.DataFrame | None = None,
    as_of=None,
    allow_live_history: bool = True,
) -> dict:
    """
    Build technical analysis features for signal generation.

    Args:
        symbol: Underlying symbol (e.g., 'NIFTY')
        current_spot: Current spot price
        days_history: Days of historical data to use

    Returns:
        Dict with TA signals and metadata
    """
    try:
        cfg = get_technical_analysis_policy_config()
        lookback_days = int(days_history or cfg.default_history_days)
        candle_features = build_intraday_candle_features(
            symbol,
            current_spot,
            intraday_history_df=intraday_history_df,
            as_of=as_of,
            allow_live_history=allow_live_history,
            cfg=cfg,
        )
        if history_df is None:
            if not allow_live_history:
                payload = _no_ta_signal(
                    "point_in_time_unavailable",
                    warning="ta_history_not_supplied_for_historical_mode",
                )
                payload.update(candle_features)
                return payload
            history_df = get_recent_spot_history(symbol, lookback_days)

        hist_df = _prepare_history_frame(history_df, as_of=as_of)

        if hist_df.empty or len(hist_df) < cfg.minimum_history_rows:
            payload = _no_ta_signal("insufficient_data")
            payload.update(candle_features)
            return payload

        # Compute indicators
        indicators = _compute_ta_indicators(hist_df, current_spot, cfg)

        # Generate signals
        direction, confidence, regime = _generate_ta_signals(indicators, cfg)

        payload = {
            "ta_direction": direction,
            "ta_confidence": confidence,
            "ta_regime": regime,
            "indicators": indicators,
        }
        payload.update(candle_features)
        return payload

    except Exception as e:
        logger.error(f"Failed to build TA features for {symbol}: {e}")
        return _no_ta_signal("error")


def _valid_window(value: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, parsed)


def _close_price_series(hist_df: pd.DataFrame) -> pd.Series:
    """Return numeric close prices while preserving the original index."""
    if "close" not in hist_df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(hist_df["close"], errors="coerce").dropna()


def _return_bps(current_spot: float, base_price: float) -> float | None:
    try:
        spot = float(current_spot)
        base = float(base_price)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(spot) or not np.isfinite(base) or base == 0.0:
        return None
    return ((spot / base) - 1.0) * 10000.0


def _safe_float(value, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(parsed):
        return default
    return parsed


def _clip(value: float, lower: float, upper: float) -> float:
    return float(min(max(value, lower), upper))


def _as_ist_timestamp(value):
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("Asia/Kolkata")
    return ts.tz_convert("Asia/Kolkata")


def _prepare_intraday_spot_frame(
    intraday_df: pd.DataFrame | None,
    *,
    current_spot: float,
    as_of=None,
    cfg: TechnicalAnalysisPolicyConfig | None = None,
) -> pd.DataFrame:
    cfg = cfg or get_technical_analysis_policy_config()
    if intraday_df is None or intraday_df.empty:
        return pd.DataFrame(columns=["timestamp", "spot"])

    df = intraday_df.copy()
    price_col = "spot" if "spot" in df.columns else "close" if "close" in df.columns else None
    if "timestamp" not in df.columns or price_col is None:
        return pd.DataFrame(columns=["timestamp", "spot"])

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        errors="coerce",
        utc=True,
        format="mixed",
    ).dt.tz_convert("Asia/Kolkata")
    df["spot"] = pd.to_numeric(df[price_col], errors="coerce")
    df = df.dropna(subset=["timestamp", "spot"])

    as_of_ts = _as_ist_timestamp(as_of)
    if as_of_ts is not None:
        lower = as_of_ts - pd.Timedelta(minutes=max(_valid_window(cfg.intraday_candle_lookback_minutes), 1))
        df = df[(df["timestamp"] >= lower) & (df["timestamp"] <= as_of_ts)]
        spot = _safe_float(current_spot, None)
        if spot is not None and spot > 0:
            current_row = pd.DataFrame([{"timestamp": as_of_ts, "spot": spot}])
            df = pd.concat([df, current_row], ignore_index=True)

    if df.empty:
        return pd.DataFrame(columns=["timestamp", "spot"])

    return df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)


def _load_live_intraday_spot_history(
    symbol: str,
    *,
    as_of,
    cfg: TechnicalAnalysisPolicyConfig,
) -> pd.DataFrame:
    as_of_ts = _as_ist_timestamp(as_of)
    if as_of_ts is None:
        return pd.DataFrame(columns=["timestamp", "spot"])
    start_ts = as_of_ts - pd.Timedelta(minutes=max(_valid_window(cfg.intraday_candle_lookback_minutes), 1))
    try:
        return load_spot_history(symbol, start_ts=start_ts, end_ts=as_of_ts, dedupe=False)
    except Exception as exc:
        logger.warning("Unable to load local intraday spot history for TA candles: %s", exc)
        return pd.DataFrame(columns=["timestamp", "spot"])


def _resample_spot_candles(
    spot_frame: pd.DataFrame,
    *,
    interval_minutes: int,
) -> pd.DataFrame:
    if spot_frame.empty:
        return pd.DataFrame()
    interval = f"{max(_valid_window(interval_minutes), 1)}min"
    working = spot_frame.copy()
    working = working.set_index("timestamp")
    price = pd.to_numeric(working["spot"], errors="coerce").dropna()
    if price.empty:
        return pd.DataFrame()
    ohlc = price.resample(interval).ohlc()
    counts = price.resample(interval).count().rename("observation_count")
    candles = ohlc.join(counts).dropna(subset=["open", "high", "low", "close"])
    return candles.reset_index()


def _last_price_at_or_before(spot_frame: pd.DataFrame, timestamp) -> float | None:
    if spot_frame.empty or timestamp is None:
        return None
    ts = _as_ist_timestamp(timestamp)
    if ts is None:
        return None
    subset = spot_frame[spot_frame["timestamp"] <= ts]
    if subset.empty:
        return None
    return _safe_float(subset.iloc[-1]["spot"], None)


def _confidence_from_candle(
    *,
    body_bps: float,
    close_location: float,
    range_expansion_ratio: float | None,
    momentum_bps: float | None,
    direction: str,
) -> float:
    body_score = _clip(abs(body_bps) / 8.0, 0.0, 1.0)
    if direction == "CALL":
        close_score = _clip((close_location - 0.50) / 0.40, 0.0, 1.0)
        momentum_score = _clip((_safe_float(momentum_bps, 0.0) or 0.0) / 12.0, 0.0, 1.0)
    else:
        close_score = _clip((0.50 - close_location) / 0.40, 0.0, 1.0)
        momentum_score = _clip(-(_safe_float(momentum_bps, 0.0) or 0.0) / 12.0, 0.0, 1.0)
    expansion_score = _clip((_safe_float(range_expansion_ratio, 1.0) or 1.0) - 1.0, 0.0, 1.0)
    confidence = 0.42 + 0.18 * body_score + 0.18 * close_score + 0.14 * momentum_score + 0.08 * expansion_score
    return round(_clip(confidence, 0.0, 0.90), 4)


def build_intraday_candle_features(
    symbol: str,
    current_spot: float,
    *,
    intraday_history_df: pd.DataFrame | None = None,
    as_of=None,
    allow_live_history: bool = True,
    cfg: TechnicalAnalysisPolicyConfig | None = None,
) -> dict:
    """Build advisory intraday candle features for entry-timing research.

    This layer does not change the existing slow TA vote. It converts local
    spot observations into compact candle-state fields that can later be replayed
    against MAE/MFE and realized forward returns.
    """
    cfg = cfg or get_technical_analysis_policy_config()
    if not bool(cfg.intraday_candle_enabled):
        return _empty_candle_features("DISABLED")

    raw_intraday = intraday_history_df
    if raw_intraday is None and allow_live_history:
        raw_intraday = _load_live_intraday_spot_history(symbol, as_of=as_of, cfg=cfg)

    spot_frame = _prepare_intraday_spot_frame(
        raw_intraday,
        current_spot=current_spot,
        as_of=as_of,
        cfg=cfg,
    )
    min_obs = max(_valid_window(cfg.intraday_candle_min_observations), 1)
    if spot_frame.empty or len(spot_frame) < min_obs:
        payload = _empty_candle_features("INSUFFICIENT_INTRADAY_DATA")
        payload["ta_candle_observation_count"] = int(len(spot_frame))
        return payload

    interval_minutes = max(_valid_window(cfg.intraday_candle_interval_minutes), 1)
    candles = _resample_spot_candles(spot_frame, interval_minutes=interval_minutes)
    min_candles = max(_valid_window(cfg.intraday_candle_min_candles), 1)
    if candles.empty or len(candles) < min_candles:
        payload = _empty_candle_features("INSUFFICIENT_CANDLES")
        payload["ta_candle_observation_count"] = int(len(spot_frame))
        payload["ta_candle_count"] = int(len(candles))
        payload["ta_candle_interval_minutes"] = int(interval_minutes)
        return payload

    latest = candles.iloc[-1]
    open_price = _safe_float(latest.get("open"), None)
    high_price = _safe_float(latest.get("high"), None)
    low_price = _safe_float(latest.get("low"), None)
    close_price = _safe_float(latest.get("close"), None)
    if None in (open_price, high_price, low_price, close_price) or open_price == 0:
        return _empty_candle_features("INVALID_CANDLE")

    candle_range = max(high_price - low_price, 0.0)
    body = close_price - open_price
    body_bps = _return_bps(close_price, open_price) or 0.0
    range_bps = (candle_range / open_price) * 10000.0 if open_price else 0.0
    if candle_range > 0:
        close_location = (close_price - low_price) / candle_range
        upper_wick_share = (high_price - max(open_price, close_price)) / candle_range
        lower_wick_share = (min(open_price, close_price) - low_price) / candle_range
    else:
        close_location = 0.5
        upper_wick_share = 0.0
        lower_wick_share = 0.0

    previous_ranges = []
    if len(candles) > 1:
        for _, row in candles.iloc[:-1].tail(6).iterrows():
            row_open = _safe_float(row.get("open"), None)
            row_high = _safe_float(row.get("high"), None)
            row_low = _safe_float(row.get("low"), None)
            if row_open not in (None, 0.0) and row_high is not None and row_low is not None:
                previous_ranges.append(max(row_high - row_low, 0.0) / row_open * 10000.0)
    median_prev_range = float(pd.Series(previous_ranges).median()) if previous_ranges else None
    range_expansion_ratio = (range_bps / median_prev_range) if median_prev_range and median_prev_range > 0 else None

    closes = pd.to_numeric(candles["close"], errors="coerce").dropna()
    momentum_3_bps = _return_bps(closes.iloc[-1], closes.iloc[-4]) if len(closes) >= 4 else None
    momentum_5_bps = _return_bps(closes.iloc[-1], closes.iloc[-6]) if len(closes) >= 6 else None

    as_of_ts = _as_ist_timestamp(as_of) or _as_ist_timestamp(latest.get("timestamp"))
    prior_15 = _last_price_at_or_before(spot_frame, as_of_ts - pd.Timedelta(minutes=15) if as_of_ts is not None else None)
    prior_30 = _last_price_at_or_before(spot_frame, as_of_ts - pd.Timedelta(minutes=30) if as_of_ts is not None else None)
    prior_15_bps = _return_bps(close_price, prior_15) if prior_15 is not None else None
    prior_30_bps = _return_bps(close_price, prior_30) if prior_30 is not None else None

    min_body_bps = float(cfg.intraday_candle_min_body_bps)
    call_confirm = (
        body_bps >= min_body_bps
        and close_location >= float(cfg.intraday_candle_close_confirm_high)
        and upper_wick_share <= float(cfg.intraday_candle_max_counter_wick_share)
        and (_safe_float(momentum_3_bps, 0.0) or 0.0) >= -min_body_bps
    )
    put_confirm = (
        body_bps <= -min_body_bps
        and close_location <= float(cfg.intraday_candle_close_confirm_low)
        and lower_wick_share <= float(cfg.intraday_candle_max_counter_wick_share)
        and (_safe_float(momentum_3_bps, 0.0) or 0.0) <= min_body_bps
    )
    bearish_rejection = (
        upper_wick_share >= float(cfg.intraday_candle_rejection_wick_share)
        and close_location <= 0.45
    )
    bullish_rejection = (
        lower_wick_share >= float(cfg.intraday_candle_rejection_wick_share)
        and close_location >= 0.55
    )

    direction = "NO_SIGNAL"
    state = "CANDLE_FORMING"
    reasons: list[str] = []
    if bearish_rejection and not call_confirm:
        direction = "PUT"
        state = "CANDLE_REJECTION_BEARISH"
        reasons.append("dominant_upper_wick_rejection")
    elif bullish_rejection and not put_confirm:
        direction = "CALL"
        state = "CANDLE_REJECTION_BULLISH"
        reasons.append("dominant_lower_wick_rejection")
    elif call_confirm and not put_confirm:
        direction = "CALL"
        state = "CANDLE_CONFIRMED_CALL"
        reasons.append("bullish_body_close_location_confirmed")
    elif put_confirm and not call_confirm:
        direction = "PUT"
        state = "CANDLE_CONFIRMED_PUT"
        reasons.append("bearish_body_close_location_confirmed")
    elif abs(body_bps) < min_body_bps:
        reasons.append("small_body_forming")
    else:
        reasons.append("mixed_candle_structure")

    stretch_bps = float(cfg.intraday_candle_prior_stretch_bps)
    range_expanded = (_safe_float(range_expansion_ratio, 0.0) or 0.0) >= float(cfg.intraday_candle_range_expansion_threshold)
    late_chase = False
    if direction == "CALL":
        late_chase = (_safe_float(prior_15_bps, 0.0) or 0.0) >= stretch_bps and range_expanded
    elif direction == "PUT":
        late_chase = (_safe_float(prior_15_bps, 0.0) or 0.0) <= -stretch_bps and range_expanded
    if late_chase:
        state = f"CANDLE_LATE_CHASE_{direction}"
        reasons.append("prior_move_stretched_with_range_expansion")

    confidence = (
        _confidence_from_candle(
            body_bps=body_bps,
            close_location=close_location,
            range_expansion_ratio=range_expansion_ratio,
            momentum_bps=momentum_3_bps,
            direction=direction,
        )
        if direction in {"CALL", "PUT"}
        else 0.0
    )
    timing_score = round(confidence * 100.0, 2)

    return {
        "ta_candle_status": "OK",
        "ta_candle_interval_minutes": int(interval_minutes),
        "ta_candle_observation_count": int(len(spot_frame)),
        "ta_candle_count": int(len(candles)),
        "ta_candle_timestamp": _as_ist_timestamp(latest.get("timestamp")).isoformat()
        if _as_ist_timestamp(latest.get("timestamp")) is not None
        else None,
        "ta_candle_open": round(open_price, 4),
        "ta_candle_high": round(high_price, 4),
        "ta_candle_low": round(low_price, 4),
        "ta_candle_close": round(close_price, 4),
        "ta_candle_body_bps": round(float(body_bps), 4),
        "ta_candle_range_bps": round(float(range_bps), 4),
        "ta_candle_close_location": round(float(_clip(close_location, 0.0, 1.0)), 4),
        "ta_candle_upper_wick_share": round(float(_clip(upper_wick_share, 0.0, 1.0)), 4),
        "ta_candle_lower_wick_share": round(float(_clip(lower_wick_share, 0.0, 1.0)), 4),
        "ta_candle_range_expansion_ratio": round(float(range_expansion_ratio), 4)
        if range_expansion_ratio is not None and np.isfinite(range_expansion_ratio)
        else None,
        "ta_candle_momentum_3_bps": round(float(momentum_3_bps), 4)
        if momentum_3_bps is not None
        else None,
        "ta_candle_momentum_5_bps": round(float(momentum_5_bps), 4)
        if momentum_5_bps is not None
        else None,
        "ta_candle_prior_move_15m_bps": round(float(prior_15_bps), 4)
        if prior_15_bps is not None
        else None,
        "ta_candle_prior_move_30m_bps": round(float(prior_30_bps), 4)
        if prior_30_bps is not None
        else None,
        "ta_candle_direction": direction,
        "ta_candle_state": state,
        "ta_candle_confidence": confidence,
        "ta_candle_late_chase": bool(late_chase),
        "ta_candle_rejection": bool(bearish_rejection or bullish_rejection),
        "ta_candle_range_expanded": bool(range_expanded),
        "ta_entry_timing_state": state,
        "ta_entry_timing_score": timing_score,
        "ta_entry_timing_reasons": "|".join(reasons),
    }


def _compute_ta_indicator_series(
    hist_df: pd.DataFrame,
    cfg: TechnicalAnalysisPolicyConfig | None = None,
) -> dict[str, pd.Series]:
    """Compute technical indicator series for charts and latest-value extraction."""
    cfg = cfg or get_technical_analysis_policy_config()
    close_prices = _close_price_series(hist_df)
    if close_prices.empty:
        return {}

    series: dict[str, pd.Series] = {}
    sma_fast_window = _valid_window(cfg.sma_fast_window)
    sma_slow_window = _valid_window(cfg.sma_slow_window)
    ema_fast_span = _valid_window(cfg.ema_fast_span)
    ema_slow_span = _valid_window(cfg.ema_slow_span)
    macd_signal_span = _valid_window(cfg.macd_signal_span)
    rsi_window = _valid_window(cfg.rsi_window)
    bollinger_window = _valid_window(cfg.bollinger_window)

    if len(close_prices) >= sma_fast_window:
        series[f"sma_{sma_fast_window}"] = close_prices.rolling(window=sma_fast_window).mean()
    if len(close_prices) >= sma_slow_window:
        series[f"sma_{sma_slow_window}"] = close_prices.rolling(window=sma_slow_window).mean()

    if len(close_prices) >= ema_fast_span:
        series[f"ema_{ema_fast_span}"] = close_prices.ewm(span=ema_fast_span).mean()
    if len(close_prices) >= ema_slow_span:
        series[f"ema_{ema_slow_span}"] = close_prices.ewm(span=ema_slow_span).mean()

    if len(close_prices) >= max(ema_fast_span, ema_slow_span):
        ema_fast = close_prices.ewm(span=ema_fast_span).mean()
        ema_slow = close_prices.ewm(span=ema_slow_span).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=macd_signal_span).mean()
        series["macd_line"] = macd_line
        series["macd_signal"] = signal_line
        series["macd_histogram"] = macd_line - signal_line

    if len(close_prices) >= rsi_window:
        delta = close_prices.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=rsi_window).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=rsi_window).mean()
        rs = gain / loss.mask(loss == 0.0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi = rsi.mask((loss == 0.0) & (gain > 0.0), 100.0)
        rsi = rsi.mask((loss == 0.0) & (gain <= 0.0), 50.0)
        series["rsi"] = rsi

    if len(close_prices) >= bollinger_window:
        sma = close_prices.rolling(window=bollinger_window).mean()
        std = close_prices.rolling(window=bollinger_window).std()
        series["bb_lower"] = sma - cfg.bollinger_std_mult * std
        series["bb_upper"] = sma + cfg.bollinger_std_mult * std
        series["bb_sma"] = sma

    return series


def _compute_ta_indicators(
    hist_df: pd.DataFrame,
    current_spot: float,
    cfg: TechnicalAnalysisPolicyConfig | None = None,
) -> dict:
    """Compute technical indicators manually."""
    indicators = {}
    cfg = cfg or get_technical_analysis_policy_config()

    # Use close prices for indicators
    close_prices = _close_price_series(hist_df)
    if close_prices.empty:
        return indicators

    try:
        sma_fast_window = _valid_window(cfg.sma_fast_window)
        for key, values in _compute_ta_indicator_series(hist_df, cfg).items():
            latest = values.iloc[-1]
            if pd.notna(latest):
                indicators[key] = float(latest)

        if len(close_prices) >= 20:
            ret_20d = _return_bps(current_spot, close_prices.iloc[-20])
            if ret_20d is not None:
                indicators["ret_20d_bps"] = ret_20d
        if sma_fast_window != 20 and len(close_prices) >= sma_fast_window:
            ret_fast = _return_bps(current_spot, close_prices.iloc[-sma_fast_window])
            if ret_fast is not None:
                indicators[f"ret_{sma_fast_window}d_bps"] = ret_fast

    except Exception as e:
        logger.warning(f"Error computing TA indicators: {e}")

    return indicators


def _generate_ta_signals(
    indicators: dict,
    cfg: TechnicalAnalysisPolicyConfig | None = None,
) -> tuple[str, float, str]:
    """Generate trading signals from indicators."""
    cfg = cfg or get_technical_analysis_policy_config()
    direction = "NO_SIGNAL"
    confidence = 0.0
    regime = "neutral"

    signals = []
    sma_fast_key = f"sma_{_valid_window(cfg.sma_fast_window)}"
    sma_slow_key = f"sma_{_valid_window(cfg.sma_slow_window)}"

    # Moving Average signals
    if indicators.get(sma_fast_key) is not None and indicators.get(sma_slow_key) is not None:
        sma_fast = indicators[sma_fast_key]
        sma_slow = indicators[sma_slow_key]

        if sma_fast > sma_slow:
            signals.append(("CALL", cfg.trend_signal_confidence, "bullish_trend"))
        elif sma_fast < sma_slow:
            signals.append(("PUT", cfg.trend_signal_confidence, "bearish_trend"))

    # MACD signals
    if indicators.get('macd_histogram') is not None:
        macd_hist = indicators['macd_histogram']

        if macd_hist > 0:
            signals.append(("CALL", cfg.macd_signal_confidence, "macd_bullish"))
        elif macd_hist < 0:
            signals.append(("PUT", cfg.macd_signal_confidence, "macd_bearish"))

    # RSI signals
    if indicators.get('rsi') is not None:
        rsi = indicators['rsi']

        if rsi > cfg.rsi_overbought:
            signals.append(("PUT", cfg.rsi_signal_confidence, "overbought"))
        elif rsi < cfg.rsi_oversold:
            signals.append(("CALL", cfg.rsi_signal_confidence, "oversold"))

    # Aggregate signals
    if signals:
        # Simple majority vote with average confidence
        call_signals = [s for s in signals if s[0] == "CALL"]
        put_signals = [s for s in signals if s[0] == "PUT"]

        if len(call_signals) > len(put_signals):
            direction = "CALL"
            confidence = sum(s[1] for s in call_signals) / len(call_signals)
            regime = call_signals[0][2] if call_signals else "bullish"
        elif len(put_signals) > len(call_signals):
            direction = "PUT"
            confidence = sum(s[1] for s in put_signals) / len(put_signals)
            regime = put_signals[0][2] if put_signals else "bearish"
        else:
            direction = "NO_SIGNAL"
            confidence = 0.0
            regime = "mixed_signals"

    return direction, float(confidence), regime


# Helper function to get TA features for a trade
def get_ta_features_for_trade(
    symbol: str,
    spot_price: float,
    *,
    history_df: pd.DataFrame | None = None,
    intraday_history_df: pd.DataFrame | None = None,
    as_of=None,
    allow_live_history: bool = True,
) -> dict:
    """
    Convenience function to get TA features for integration with trade evaluation.

    Args:
        symbol: Underlying symbol
        spot_price: Current spot price

    Returns:
        TA features dict ready for trade evaluation
    """
    return build_ta_features(
        symbol,
        spot_price,
        history_df=history_df,
        intraday_history_df=intraday_history_df,
        as_of=as_of,
        allow_live_history=allow_live_history,
    )

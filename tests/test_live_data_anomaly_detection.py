"""
Tests for live data anomaly detection and fault tolerance mechanisms.

Covers:
- IV spike detection
- Spot price jump detection
- Retry logic for yfinance calls
- Fallback handling for macro/global_risk layers
"""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from data.option_chain_validation import _detect_iv_anomalies, _detect_spot_jump
from data.spot_downloader import get_spot_snapshot


class TestIVAnomalyDetection:
    """Test IV spike and variance detection."""
    
    def test_normal_iv_distribution_no_alerts(self):
        """Normal IV values should not trigger anomaly warnings."""
        iv_series = pd.Series([0.25, 0.26, 0.25, 0.27, 0.26, 0.25, 0.26])
        warnings = _detect_iv_anomalies(iv_series)
        assert len(warnings) == 0
    
    def test_iv_spike_detected(self):
        """Extreme IV spike should be detected."""
        # Normal IV around 0.25, one spike to 1.5 (6x)
        iv_series = pd.Series([0.25, 0.26, 0.25, 1.50, 0.25, 0.26])
        warnings = _detect_iv_anomalies(iv_series, {"max_iv_percent": 500.0})
        assert any("iv_extreme_spike_detected" in w for w in warnings)
    
    def test_empty_iv_series_no_crash(self):
        """Empty IV series should not crash."""
        iv_series = pd.Series([], dtype=float)
        warnings = _detect_iv_anomalies(iv_series)
        assert warnings == []
    
    def test_all_zero_iv_no_crash(self):
        """All-zero IV series should not crash."""
        iv_series = pd.Series([0.0, 0.0, 0.0])
        warnings = _detect_iv_anomalies(iv_series)
        assert len(warnings) == 0
    
    def test_high_variance_detected(self):
        """High variance in IV should be detected when spike is extreme."""
        # This should detect spike: most values 0.25, but one value 2.0
        iv_series = pd.Series([0.25, 0.26, 2.0, 0.25, 0.26])
        warnings = _detect_iv_anomalies(iv_series)
        assert any("iv_extreme_spike_detected" in w for w in warnings)
    
    def test_custom_thresholds(self):
        """Custom thresholds should be respected."""
        iv_series = pd.Series([0.25, 0.26, 2.0, 0.25])  # 2.0 = 8x median
        warnings = _detect_iv_anomalies(iv_series, {"max_iv_percent": 200.0})
        assert len(warnings) > 0  # Should detect at 2x threshold


class TestSpotPriceJumpDetection:
    """Test spot price anomaly detection."""
    
    def test_normal_spot_no_alerts(self):
        """Normal intraday spot movement should not trigger alerts."""
        warnings = _detect_spot_jump(
            current_spot=100.0,
            day_high=102.0,
            day_low=98.0,
            prev_close=99.5
        )
        assert len(warnings) == 0
    
    def test_gap_up_detected(self):
        """Large gap up from prev close should be detected."""
        warnings = _detect_spot_jump(
            current_spot=105.0,
            day_high=105.0,
            day_low=103.0,
            prev_close=100.0,
            thresholds={"max_normal_gap_percent": 3.0}
        )
        assert any("spot_gap_from_prev_close" in w for w in warnings)
    
    def test_abnormal_intraday_range(self):
        """Abnormally wide intraday range should be detected."""
        warnings = _detect_spot_jump(
            current_spot=100.0,
            day_high=150.0,  # 50% range
            day_low=50.0,
            prev_close=100.0,
            thresholds={"max_intraday_move_percent": 8.0}
        )
        assert any("abnormal_intraday_range" in w for w in warnings)
    
    def test_spot_above_day_high(self):
        """Spot above day high should be detected (2% threshold)."""
        warnings = _detect_spot_jump(
            current_spot=102.5,  # 2.5% above high (triggering >2%)
            day_high=100.0,
            day_low=98.0,
            prev_close=99.0
        )
        assert any("spot_above_day_high" in w for w in warnings)
    
    def test_spot_below_day_low(self):
        """Spot below day low should be detected (2% threshold)."""
        warnings = _detect_spot_jump(
            current_spot=97.0,   # 2% below low (triggering threshold)
            day_high=100.0,
            day_low=99.0,
            prev_close=99.0
        )
        assert any("spot_below_day_low" in w for w in warnings)
    
    def test_missing_prev_close_no_crash(self):
        """Missing prev_close should not crash."""
        warnings = _detect_spot_jump(
            current_spot=100.0,
            day_high=102.0,
            day_low=98.0,
            prev_close=0.0  # Using 0.0 as None equivalent for type compliance
        )
        assert len(warnings) == 0


class TestSpotSnapshotRetry:
    """Test retry logic in get_spot_snapshot."""
    
    @patch('yfinance.Ticker')
    def test_success_on_first_attempt(self, mock_ticker):
        """Should return immediately on first successful attempt."""
        # Setup mock
        mock_ticker_instance = MagicMock()
        mock_ticker.return_value = mock_ticker_instance
        
        intraday_df = pd.DataFrame({
            'Open': [100, 101],
            'High': [102, 103],
            'Low': [99, 100],
            'Close': [101, 102]
        }, index=pd.date_range('2026-03-20 10:00', periods=2, freq='5min', tz='Asia/Kolkata'))
        
        daily_df = pd.DataFrame({
            'Open': [100],
            'High': [102],
            'Low': [99],
            'Close': [101]
        }, index=pd.date_range('2026-03-20', periods=1, freq='D', tz='Asia/Kolkata'))
        
        mock_ticker_instance.history.side_effect = [intraday_df, daily_df]
        
        result = get_spot_snapshot('NIFTY')
        assert result['spot'] == 102.0
        assert mock_ticker.call_count == 1  # Only called once
    
    @patch('yfinance.Ticker')
    def test_exhausts_retries_and_raises(self, mock_ticker):
        """Should raise after exhausting retries."""
        mock_ticker_instance = MagicMock()
        mock_ticker.return_value = mock_ticker_instance
        
        # All attempts fail
        mock_ticker_instance.history.side_effect = Exception("Network error")
        
        with pytest.raises(ValueError, match="after 2 attempts"):
            get_spot_snapshot('NIFTY', max_retries=2)


class TestMacroNewsStateFallback:
    """Test fallback behavior when macro_news_state construction fails."""
    
    def test_macro_news_neutral_fallback_on_error(self):
        """When build_macro_news_state fails, should use neutral fallback."""
        from macro.macro_news_aggregator import _neutral_macro_news_state
        
        # Simulate error case - pass None for required field
        fallback = _neutral_macro_news_state(
            event_state=None,
            warnings=["construction_failed"]
        )
        
        assert fallback.macro_regime == "MACRO_NEUTRAL"
        assert fallback.volatility_shock_score == 0.0
        assert fallback.neutral_fallback is True
        assert "construction_failed" in fallback.warnings


class TestGlobalRiskStateFallback:
    """Test fallback behavior when global_risk_state construction fails."""
    
    def test_global_risk_neutral_fallback_on_error(self):
        """When build_global_risk_state fails, should use fallback."""
        from risk.global_risk_layer import _fallback_global_risk_state
        
        fallback = _fallback_global_risk_state(
            event_window_status="NO_EVENT_DATA",
            macro_event_risk_score=0,
            event_lockdown_flag=False,
            holding_profile="AUTO"
        )
        
        assert fallback["global_risk_state"] == "GLOBAL_NEUTRAL"
        assert fallback["neutral_fallback"] is True
        assert fallback["global_risk_score"] == 0


class TestLiveStreamIntegration:
    """Integration tests for live snapshot evaluation with fault tolerance."""
    
    @patch('data.spot_downloader.get_spot_snapshot')
    @patch('data.data_source_router.DataSourceRouter')
    def test_engine_snapshot_handles_spot_fetch_failure(self, mock_router, mock_spot):
        """Engine should handle spot fetch failures gracefully."""
        from app.engine_runner import run_engine_snapshot
        
        # Simulate spot fetch failure
        mock_spot.side_effect = Exception("yfinance timeout")
        
        result = run_engine_snapshot(
            symbol="NIFTY",
            mode="LIVE",
            source="ZERODHA",
            apply_budget_constraint=False,
            requested_lots=1,
            lot_size=75,
            max_capital=100000.0
        )
        
        # Should return error result, not raise
        assert result['ok'] is False
        assert 'error' in result

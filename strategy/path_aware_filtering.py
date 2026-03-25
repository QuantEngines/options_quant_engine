"""
Module: path_aware_filtering.py

Purpose:
    Implement path-aware entry filtering to reject signals with adverse
    intraday path geometry before entry.

Context:
    Cumulative analysis shows:
    - MFE/MAE ratio 0.87 (adverse paths—more adverse than favorable excursions)
    - Tradeability score 49.9 (marginal, edge case territory)
    - Many signals are directionally correct but hit adverse moves first
    
    This module uses historical path pattern matching to:
    1. Compute expected MFE/MAE profiles by signal characteristics
    2. Compare actual 5-15m path geometry to historical baseline
    3. Flag "HOSTILE_PATH" signals for reduced weighting or rejection
    4. Optionally implement delayed entry (wait for favorable move confirmation)

Key Outputs:
    path_check_result = {
        "path_status": str,          # "NORMAL", "HOSTILE", "FAVORABLE"
        "mfe_zscore": float,         # How adverse (negative) vs expected
        "mae_zscore": float,
        "score_penalty": int,        # Recommended score reduction
        "entry_veto": bool,          # Should reject this signal?
        "delayed_entry_recommended": bool,
        "reasons": list[str]
    }

Downstream Usage:
    Consumed by signal_engine.py and confirmation_filters.py for
    entry timing decisions and score adjustments.
"""

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


def _safe_float(value, default=None):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _clip(value, lo, hi):
    return max(lo, min(hi, value))


class PathPatternLibrary:
    """
    Maintain historical MFE/MAE statistics by signal characteristics.
    
    Structure:
        patterns[gamma_regime][direction] = {
            "5m": {"mfe_median": 15, "mae_median": -18, "mfe_std": 5, "mae_std": 8},
            "15m": {...},
            ...
        }
    """
    
    def __init__(self):
        self.patterns = {}
        self.is_initialized = False
    
    def initialize_default_patterns(self) -> None:
        """Initialize with default patterns derived from empirical observation."""
        self.patterns = {
            "POSITIVE_GAMMA": {
                "CALL": {
                    "5m": {
                        "mfe_median_bps": 18,
                        "mae_median_bps": -16,
                        "mfe_std_bps": 22,
                        "mae_std_bps": 20,
                        "n_samples": 450
                    },
                    "15m": {
                        "mfe_median_bps": 24,
                        "mae_median_bps": -19,
                        "mfe_std_bps": 28,
                        "mae_std_bps": 24,
                        "n_samples": 410
                    }
                },
                "PUT": {
                    "5m": {
                        "mfe_median_bps": 16,
                        "mae_median_bps": -17,
                        "mfe_std_bps": 20,
                        "mae_std_bps": 22,
                        "n_samples": 340
                    },
                    "15m": {
                        "mfe_median_bps": 22,
                        "mae_median_bps": -20,
                        "mfe_std_bps": 26,
                        "mae_std_bps": 25,
                        "n_samples": 305
                    }
                }
            },
            "NEGATIVE_GAMMA": {
                "CALL": {
                    "5m": {
                        "mfe_median_bps": 12,
                        "mae_median_bps": -25,
                        "mfe_std_bps": 18,
                        "mae_std_bps": 30,
                        "n_samples": 192
                    },
                    "15m": {
                        "mfe_median_bps": 8,
                        "mae_median_bps": -32,
                        "mfe_std_bps": 20,
                        "mae_std_bps": 35,
                        "n_samples": 180
                    }
                },
                "PUT": {
                    "5m": {
                        "mfe_median_bps": 14,
                        "mae_median_bps": -28,
                        "mfe_std_bps": 19,
                        "mae_std_bps": 32,
                        "n_samples": 160
                    },
                    "15m": {
                        "mfe_median_bps": 10,
                        "mae_median_bps": -35,
                        "mfe_std_bps": 22,
                        "mae_std_bps": 38,
                        "n_samples": 140
                    }
                }
            },
            "NEUTRAL_GAMMA": {
                "CALL": {
                    "5m": {
                        "mfe_median_bps": 15,
                        "mae_median_bps": -18,
                        "mfe_std_bps": 21,
                        "mae_std_bps": 23,
                        "n_samples": 211
                    },
                    "15m": {
                        "mfe_median_bps": 20,
                        "mae_median_bps": -22,
                        "mfe_std_bps": 25,
                        "mae_std_bps": 27,
                        "n_samples": 190
                    }
                },
                "PUT": {
                    "5m": {
                        "mfe_median_bps": 14,
                        "mae_median_bps": -19,
                        "mfe_std_bps": 20,
                        "mae_std_bps": 24,
                        "n_samples": 175
                    },
                    "15m": {
                        "mfe_median_bps": 18,
                        "mae_median_bps": -23,
                        "mfe_std_bps": 24,
                        "mae_std_bps": 28,
                        "n_samples": 158
                    }
                }
            }
        }
        self.is_initialized = True
    
    def get_expected_profile(
        self,
        gamma_regime: str,
        direction: str,
        window: str = "5m"
    ) -> Optional[Dict]:
        """Retrieve expected MFE/MAE profile for signal characteristics."""
        if not self.is_initialized:
            self.initialize_default_patterns()
        
        gamma = (gamma_regime or "NEUTRAL_GAMMA").upper()
        direction_upper = (direction or "CALL").upper()
        
        try:
            return self.patterns[gamma][direction_upper].get(window)
        except (KeyError, TypeError):
            logger.warning(
                f"No pattern found for gamma={gamma}, direction={direction_upper}, window={window}"
            )
            return None


class PathAwareFilter:
    """
    Filter signals based on path efficiency and adverse move patterns.
    
    Logic:
        1. Get historical MFE/MAE profile for signal characteristics
        2. Compute z-scores for observed path
        3. Flag if MAE > median + threshold * std (adverse path)
        4. Apply score penalty or veto entry
    """
    
    def __init__(self, pattern_library: Optional[PathPatternLibrary] = None):
        self.pattern_library = pattern_library or PathPatternLibrary()
        self.pattern_library.initialize_default_patterns()
    
    def check_path_geometry(
        self,
        gamma_regime: str,
        direction: str,
        mfe_observed_bps: Optional[float],
        mae_observed_bps: Optional[float],
        window: str = "5m",
        mae_zscore_threshold: float = 1.5,
        hostile_path_score_penalty: int = -15,
        allow_veto: bool = False
    ) -> Dict:
        """
        Evaluate path geometry for hostility.
        
        Args:
            gamma_regime: Market gamma regime
            direction: CALL or PUT
            mfe_observed_bps: Observed max favorable excursion (basis points)
            mae_observed_bps: Observed max adverse excursion (basis points)
            window: Time window ("5m", "15m")
            mae_zscore_threshold: Z-score threshold for flagging adverse paths
            hostile_path_score_penalty: Score reduction for hostile path
            allow_veto: If True, can veto entry entirely
        
        Returns:
            Dict with path_status, z-scores, penalties, recommendations
        """
        result = {
            "path_status": "UNKNOWN",
            "mfe_observed_bps": _safe_float(mfe_observed_bps),
            "mae_observed_bps": _safe_float(mae_observed_bps),
            "mfe_zscore": None,
            "mae_zscore": None,
            "score_penalty": 0,
            "entry_veto": False,
            "delayed_entry_recommended": False,
            "hostile_path": False,
            "favorable_path": False,
            "reasons": []
        }
        
        # Guard: missing data
        if mfe_observed_bps is None or mae_observed_bps is None:
            result["reasons"].append("missing_mfe_mae_data")
            return result
        
        mfe_obs = _safe_float(mfe_observed_bps, 0.0)
        mae_obs = _safe_float(mae_observed_bps, 0.0)
        
        # Get historical profile
        profile = self.pattern_library.get_expected_profile(
            gamma_regime, direction, window
        )
        
        if profile is None:
            result["path_status"] = "UNKNOWN_PROFILE"
            result["reasons"].append("no_historical_pattern")
            return result
        
        mfe_median = profile.get("mfe_median_bps", 15)
        mae_median = profile.get("mae_median_bps", -20)
        mfe_std = max(profile.get("mfe_std_bps", 20), 1.0)
        mae_std = max(profile.get("mae_std_bps", 25), 1.0)
        
        # Compute z-scores.
        # MAE is represented as a signed downside quantity (typically <= 0).
        # Hostility should increase when adverse excursion magnitude increases.
        mfe_zscore = (mfe_obs - mfe_median) / mfe_std
        adverse_obs = max(0.0, -mae_obs)
        adverse_exp = max(0.0, -mae_median)
        mae_zscore = (adverse_obs - adverse_exp) / mae_std
        
        result["mfe_zscore"] = float(mfe_zscore)
        result["mae_zscore"] = float(mae_zscore)
        
        # Classify path
        is_hostile = mae_zscore > mae_zscore_threshold
        is_favorable = (mfe_obs > mfe_median + mfe_std) and (mae_obs >= (mae_median + 0.5 * mae_std))
        
        if is_favorable:
            result["path_status"] = "FAVORABLE"
            result["favorable_path"] = True
            result["reasons"].append("favorable_mfe_mae_geometry")
            # Bonus for favorable paths
            result["score_penalty"] = +5
        
        elif is_hostile:
            result["path_status"] = "HOSTILE"
            result["hostile_path"] = True
            result["reasons"].append(f"adverse_mae_zscore={mae_zscore:.2f}")
            result["score_penalty"] = int(hostile_path_score_penalty)
            result["delayed_entry_recommended"] = True
            
            if allow_veto and mae_zscore > mae_zscore_threshold + 1.0:
                result["entry_veto"] = True
                result["reasons"].append("severe_adverse_path_veto")
        
        else:
            result["path_status"] = "NORMAL"
            result["reasons"].append("normal_path_geometry")
        
        return result
    
    def batch_check_paths(
        self,
        signals: List[Dict],
        **kwargs
    ) -> List[Dict]:
        """Apply path check to multiple signals."""
        return [
            self.check_path_geometry(
                gamma_regime=signal.get("gamma_regime"),
                direction=signal.get("direction"),
                mfe_observed_bps=signal.get("mfe_observed_bps"),
                mae_observed_bps=signal.get("mae_observed_bps"),
                **kwargs
            )
            for signal in signals
        ]


class DelayedEntryConfirmation:
    """
    Implement delayed entry strategy: wait for favorable move confirmation.
    
    Logic:
        Signal is flagged as "HOSTILE_PATH" at t=0
        At t=5m or t=15m window, re-evaluate:
        - If MFE > MAE (favorable move confirmed), enter with reduced size
        - If MAE still > MFE (adverse continues), skip entry
    """
    
    def __init__(self):
        self.pending_signals = {}  # signal_id -> pending entry state
    
    def register_hostile_signal(
        self,
        signal_id: str,
        original_score: float,
        gamma_regime: str,
        direction: str,
        generation_time: float
    ) -> None:
        """Register a hostile-path signal for delayed entry."""
        self.pending_signals[signal_id] = {
            "original_score": original_score,
            "gamma_regime": gamma_regime,
            "direction": direction,
            "generation_time": generation_time,
            "status": "PENDING_CONFIRMATION",
            "confirmation_time": None
        }
    
    def check_confirmation(
        self,
        signal_id: str,
        mfe_current_bps: float,
        mae_current_bps: float,
        current_time: float
    ) -> Dict:
        """
        Check if delayed entry conditions are met.
        
        Returns:
            {
                "confirmed": bool,
                "entry_allowed": bool,
                "size_multiplier": float,
                "reason": str,
                "elapsed_minutes": float
            }
        """
        if signal_id not in self.pending_signals:
            return {
                "confirmed": False,
                "entry_allowed": False,
                "reason": "signal_not_registered",
                "elapsed_minutes": None
            }
        
        pending = self.pending_signals[signal_id]
        elapsed_m = (current_time - pending["generation_time"]) / 60.0
        
        # Decision logic
        if mfe_current_bps > mae_current_bps:
            # Favorable move confirmed
            pending["status"] = "CONFIRMED_FAVORABLE"
            pending["confirmation_time"] = current_time
            
            # Entry allowed with size reduction based on elapsed time
            size_mult = 1.0 if elapsed_m < 10 else max(0.5, 1.0 - 0.05 * elapsed_m)
            
            return {
                "confirmed": True,
                "entry_allowed": True,
                "size_multiplier": float(size_mult),
                "reason": "favorable_move_confirmed",
                "elapsed_minutes": float(elapsed_m)
            }
        
        elif elapsed_m > 20:
            # Timeout: too long waiting, skip entry
            pending["status"] = "TIMEOUT_REJECTED"
            return {
                "confirmed": True,
                "entry_allowed": False,
                "size_multiplier": 0.0,
                "reason": "delayed_entry_timeout",
                "elapsed_minutes": float(elapsed_m)
            }
        
        else:
            # Still waiting for confirmation
            return {
                "confirmed": False,
                "entry_allowed": False,
                "reason": "awaiting_confirmation",
                "elapsed_minutes": float(elapsed_m)
            }
    
    def cleanup_confirmed(self, signal_id: str) -> None:
        """Remove confirmed signal from pending tracking."""
        if signal_id in self.pending_signals:
            del self.pending_signals[signal_id]


# ============================================================================
# Convenience Functions
# ============================================================================

_global_path_filter: Optional[PathAwareFilter] = None
_global_delayed_entry: Optional[DelayedEntryConfirmation] = None


def initialize_path_filtering():
    """Initialize global path filtering instances."""
    global _global_path_filter, _global_delayed_entry
    _global_path_filter = PathAwareFilter()
    _global_delayed_entry = DelayedEntryConfirmation()


def check_path_geometry(
    gamma_regime: str,
    direction: str,
    mfe_bps: float,
    mae_bps: float,
    window: str = "5m",
    mae_zscore_threshold: float = 1.5,
    **kwargs
) -> Dict:
    """Apply global path filter to check signal path geometry."""
    global _global_path_filter
    if _global_path_filter is None:
        initialize_path_filtering()
    
    return _global_path_filter.check_path_geometry(
        gamma_regime, direction, mfe_bps, mae_bps, window, mae_zscore_threshold, **kwargs
    )


def get_path_filter() -> Optional[PathAwareFilter]:
    """Get reference to global path filter."""
    return _global_path_filter


def get_delayed_entry_manager() -> Optional[DelayedEntryConfirmation]:
    """Get reference to global delayed entry manager."""
    return _global_delayed_entry

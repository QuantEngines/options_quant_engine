"""
Module: time_decay_model.py

Purpose:
    Model alpha decay over time with regime-aware depreciation curves.
    
Context:
    Cumulative analysis shows:
    - Alpha peaks at 120m (+4.6 bps) then reverses to -7.97 bps at close
    - Session close degradation of -8.6 bps (worst behavior)
    - Need to automatically reduce score confidence post-peak
    
    This module computes decay multiplier based on:
    - Minutes elapsed since signal generation
    - Current gamma regime
    - Volatility regime
    - Direction bias (CALL vs PUT)

Key Outputs:
    decay_factor(elapsed_minutes, gamma_regime, vol_regime) -> multiplier [0-1]
    decayed_score = raw_score * decay_factor

Downstream Usage:
    Consumed by signal_engine.py and confirmation_filters.py for
    dynamic score adjustment, optimal exit timing, and position sizing.
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


class TimeDecayModel:
    """
    Compute time-decay multiplier for signal scores.
    
    Decay Function:
        decay(t) = exp(-ln(2) * (t / t_half)^λ)
    
    where:
        t = time elapsed (minutes)
        t_half = half-life (regime-dependent)
        λ = steepness parameter (default 1.5)
    
    Properties:
        - decay(0) = 1.0 (no decay at t=0)
        - decay(t_half) = 0.5 (half-life definition)
        - decay(∞) → 0 (asymptotic decay)
    """
    
    def __init__(
        self,
        positive_gamma_half_life_m: float = 90.0,
        negative_gamma_half_life_m: float = 45.0,
        neutral_gamma_half_life_m: float = 70.0,
        high_vol_half_life_multiplier: float = 0.85,
        steepness: float = 1.5
    ):
        """
        Initialize decay model with regime-specific half-lives.
        
        Args:
            positive_gamma_half_life_m: Half-life in POSITIVE_GAMMA (minutes)
            negative_gamma_half_life_m: Half-life in NEGATIVE_GAMMA (minutes)
            neutral_gamma_half_life_m: Half-life in NEUTRAL_GAMMA (minutes)
            high_vol_half_life_multiplier: Accelerate decay in high-vol environments
            steepness: Exponent λ (higher = steeper decay)
        """
        self.half_lives = {
            "POSITIVE_GAMMA": float(positive_gamma_half_life_m),
            "NEGATIVE_GAMMA": float(negative_gamma_half_life_m),
            "NEUTRAL_GAMMA": float(neutral_gamma_half_life_m)
        }
        self.high_vol_multiplier = float(high_vol_half_life_multiplier)
        self.steepness = float(steepness)
    
    def _effective_half_life(
        self,
        gamma_regime: Optional[str],
        volatility_regime: Optional[str]
    ) -> float:
        """
        Compute effective half-life based on regimes.
        
        In volatile environments (VOL_EXPANSION), decay is faster.
        """
        regime = (gamma_regime or "NEUTRAL_GAMMA").upper()
        half_life = self.half_lives.get(regime, self.half_lives["NEUTRAL_GAMMA"])
        
        vol_regime = (volatility_regime or "NORMAL_VOL").upper()
        if vol_regime in {"VOL_EXPANSION", "HIGH_VOL", "SHOCK_VOL"}:
            half_life *= self.high_vol_multiplier
        
        return max(1.0, half_life)  # Minimum 1 minute half-life
    
    def compute_decay_factor(
        self,
        elapsed_minutes: float,
        gamma_regime: Optional[str] = "NEUTRAL_GAMMA",
        volatility_regime: Optional[str] = "NORMAL_VOL"
    ) -> float:
        """
        Compute decay multiplier for score.
        
        Args:
            elapsed_minutes: Time since signal generation
            gamma_regime: "POSITIVE_GAMMA", "NEGATIVE_GAMMA", or "NEUTRAL_GAMMA"
            volatility_regime: "NORMAL_VOL", "VOL_EXPANSION", etc.
        
        Returns:
            Multiplier factor ∈ [0, 1]
        """
        elapsed_minutes = max(0.0, float(elapsed_minutes))
        
        if elapsed_minutes == 0.0:
            return 1.0
        
        half_life = self._effective_half_life(gamma_regime, volatility_regime)
        
        # Half-life-consistent exponential family.
        # At t = half_life, factor = exp(-ln(2)) = 0.5.
        t_ratio = elapsed_minutes / max(half_life, 1.0)
        decay_factor = float(np.exp(-np.log(2.0) * (t_ratio ** self.steepness)))
        
        return _clip(decay_factor, 0.0, 1.0)
    
    def compute_decayed_score(
        self,
        raw_score: float,
        elapsed_minutes: float,
        gamma_regime: Optional[str] = "NEUTRAL_GAMMA",
        volatility_regime: Optional[str] = "NORMAL_VOL"
    ) -> float:
        """
        Compute decayed score: score * decay_factor
        
        Args:
            raw_score: Original composite score [0-100]
            elapsed_minutes: Time elapsed (minutes)
            gamma_regime: Market gamma regime
            volatility_regime: Market volatility regime
        
        Returns:
            Decayed score [0-100]
        """
        raw_score = _clip(float(raw_score), 0.0, 100.0)
        decay_factor = self.compute_decay_factor(
            elapsed_minutes, gamma_regime, volatility_regime
        )
        decayed = raw_score * decay_factor
        return _clip(decayed, 0.0, 100.0)
    
    def optimal_exit_time(
        self,
        gamma_regime: Optional[str] = "NEUTRAL_GAMMA",
        volatility_regime: Optional[str] = "NORMAL_VOL"
    ) -> float:
        """
        Estimate optimal exit time (when decay reaches 50%).
        
        This is the half-life, adjusted for volatility regime.
        """
        return self._effective_half_life(gamma_regime, volatility_regime)
    
    def decay_curve(
        self,
        time_points: List[float],
        gamma_regime: Optional[str] = "NEUTRAL_GAMMA",
        volatility_regime: Optional[str] = "NORMAL_VOL"
    ) -> List[float]:
        """
        Compute decay factors at multiple time points.
        
        Args:
            time_points: List of elapsed minutes
            gamma_regime: Market regime
            volatility_regime: Volatility regime
        
        Returns:
            List of decay factors [0-1]
        """
        return [
            self.compute_decay_factor(t, gamma_regime, volatility_regime)
            for t in time_points
        ]
    
    def decay_curve_dict(
        self,
        time_points: List[float],
        raw_score: float = 50.0,
        gamma_regime: Optional[str] = "NEUTRAL_GAMMA",
        volatility_regime: Optional[str] = "NORMAL_VOL"
    ) -> Dict:
        """
        Generate detailed decay curve with both decay factors and decayed scores.
        
        Returns dict with time_points, decay_factors, and decayed_scores.
        """
        decay_factors = self.decay_curve(time_points, gamma_regime, volatility_regime)
        decayed_scores = [raw_score * df for df in decay_factors]
        
        return {
            "gamma_regime": gamma_regime,
            "volatility_regime": volatility_regime,
            "raw_score": float(raw_score),
            "half_life_m": self._effective_half_life(gamma_regime, volatility_regime),
            "curve": [
                {
                    "elapsed_m": float(t),
                    "decay_factor": float(df),
                    "decayed_score": float(ds)
                }
                for t, df, ds in zip(time_points, decay_factors, decayed_scores)
            ]
        }


class RegimeAwareDecayManager:
    """
    Manager for applying time-decay across signal portfolio.
    
    Tracks signal generation timestamps and applies regime-aware decay
    when evaluating signal quality.
    """
    
    def __init__(self, decay_model: Optional[TimeDecayModel] = None):
        self.decay_model = decay_model or TimeDecayModel()
        self.signal_timestamps = {}  # Dict[signal_id] -> generation_time
    
    def register_signal(self, signal_id: str, generation_time: float) -> None:
        """Register signal generation time for future decay tracking."""
        self.signal_timestamps[signal_id] = float(generation_time)
    
    def get_elapsed_minutes(self, signal_id: str, current_time: float) -> float:
        """Compute elapsed time for a signal."""
        if signal_id not in self.signal_timestamps:
            logger.warning(f"Signal {signal_id} not registered; assuming 0 elapsed")
            return 0.0
        
        elapsed = float(current_time) - self.signal_timestamps[signal_id]
        return max(0.0, elapsed / 60.0)  # Convert seconds to minutes
    
    def apply_decay(
        self,
        raw_score: float,
        signal_id: str,
        current_time: float,
        gamma_regime: Optional[str] = None,
        volatility_regime: Optional[str] = None
    ) -> float:
        """
        Apply decay to a signal's score.
        
        Args:
            raw_score: Original composite score
            signal_id: Unique signal identifier
            current_time: Current evaluation time (seconds since epoch)
            gamma_regime: Market gamma regime
            volatility_regime: Market volatility regime
        
        Returns:
            Decayed score [0-100]
        """
        elapsed_m = self.get_elapsed_minutes(signal_id, current_time)
        return self.decay_model.compute_decayed_score(
            raw_score, elapsed_m, gamma_regime, volatility_regime
        )


# ============================================================================
# Convenience Functions
# ============================================================================

_global_time_decay_model: Optional[TimeDecayModel] = None
_global_decay_manager: Optional[RegimeAwareDecayManager] = None


def initialize_time_decay(
    positive_gamma_half_life_m: float = 90.0,
    negative_gamma_half_life_m: float = 45.0,
    neutral_gamma_half_life_m: float = 70.0,
    high_vol_multiplier: float = 0.85,
    steepness: float = 1.5
) -> TimeDecayModel:
    """Initialize global time-decay model."""
    global _global_time_decay_model, _global_decay_manager
    _global_time_decay_model = TimeDecayModel(
        positive_gamma_half_life_m=positive_gamma_half_life_m,
        negative_gamma_half_life_m=negative_gamma_half_life_m,
        neutral_gamma_half_life_m=neutral_gamma_half_life_m,
        high_vol_half_life_multiplier=high_vol_multiplier,
        steepness=steepness
    )
    _global_decay_manager = RegimeAwareDecayManager(_global_time_decay_model)
    return _global_time_decay_model


def get_time_decay_model() -> Optional[TimeDecayModel]:
    """Get reference to global time-decay model."""
    return _global_time_decay_model


def get_decay_manager() -> Optional[RegimeAwareDecayManager]:
    """Get reference to global decay manager."""
    return _global_decay_manager


def compute_decay_factor(
    elapsed_minutes: float,
    gamma_regime: str = "NEUTRAL_GAMMA",
    volatility_regime: str = "NORMAL_VOL"
) -> float:
    """Apply global time-decay model to compute decay factor."""
    global _global_time_decay_model
    if _global_time_decay_model is None:
        initialize_time_decay()
    return _global_time_decay_model.compute_decay_factor(
        elapsed_minutes, gamma_regime, volatility_regime
    )


def apply_time_decay_to_score(
    raw_score: float,
    elapsed_minutes: float,
    gamma_regime: str = "NEUTRAL_GAMMA",
    volatility_regime: str = "NORMAL_VOL"
) -> float:
    """Apply global time-decay model to compute decayed score."""
    global _global_time_decay_model
    if _global_time_decay_model is None:
        initialize_time_decay()
    return _global_time_decay_model.compute_decayed_score(
        raw_score, elapsed_minutes, gamma_regime, volatility_regime
    )


def apply_time_decay(
    minutes_elapsed: float,
    gamma_regime: str = "NEUTRAL_GAMMA",
    lambda_param: float = 1.5,
    volatility_regime: str = "NORMAL_VOL",
) -> float:
    """
    Apply time-decay model to compute decay factor (for runtime use).
    
    Purpose:
        Wrapper for runtime decay factor computation.
        
    Args:
        minutes_elapsed: Minutes since signal entry
        gamma_regime: Gamma market regime (POSITIVE/NEGATIVE/NEUTRAL)
        lambda_param: Decay shape parameter (ignored if model already initialized)
        volatility_regime: Volatility regime used for effective half-life adjustment
    
    Returns:
        Decay factor in (0, 1] representing score multiplier at elapsed time
    """
    global _global_time_decay_model
    if _global_time_decay_model is None:
        initialize_time_decay()
    return compute_decay_factor(minutes_elapsed, gamma_regime, volatility_regime)

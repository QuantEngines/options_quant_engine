"""
Module: score_calibration.py

Purpose:
    Implement score calibration using isotonic regression and temperature scaling
    to fix overconfidence in high-score predictions.

Context:
    Cumulative analysis shows:
    - 80-100% bucket: Expected 80% hit, achieved 1.0 hit (overconfident by +0.55)
    - 65-79% bucket: Expected 65% hit, achieved 92% hit (overconfident by +0.28)
    
    This module learns a mapping from raw scores to calibrated (true) scores
    that match realized hit rates.

Key Outputs:
    calibrate_score(raw_score, method='isotonic') -> calibrated_score [0-100]

Downstream Usage:
    Consumed by the signal engine for trade qualification thresholds and
    position sizing decisions.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Tuple
import numpy as np
from pathlib import Path

logger = logging.getLogger(__name__)


def _safe_float(value, default=None):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _clip(value, lo, hi):
    return max(lo, min(hi, value))


class IsotonicCalibrator:
    """
    Learn isotonic (monotonic non-decreasing) mapping from raw scores to calibrated scores.
    
    Algorithm:
        1. Bin signals by raw score percentile
        2. Compute actual hit rate for each bin
        3. Fit isotonic regression: predicted_score -> realized_hit_rate
        4. Invert: raw_score -> calibrated_score
    """
    
    def __init__(self, n_bins: int = 10):
        self.n_bins = n_bins
        self.bin_edges = None
        self.calibration_mapping = None  # Dict[score_quintile] -> actual_hit_rate
        self.is_fitted = False
    
    def fit(
        self,
        raw_scores: np.ndarray,
        hit_flags: np.ndarray,
        method: str = "rolling_average"
    ) -> Dict:
        """
        Learn calibration mapping from training data.
        
        Args:
            raw_scores: Array of raw composite scores [0-100]
            hit_flags: Binary array where 1 = hit at horizon, 0 = miss
            method: "rolling_average" (simple) or "isotonic_regression" (advanced)
        
        Returns:
            Calibration report with bin-level statistics
        """
        if len(raw_scores) == 0:
            logger.warning("Empty training set; skipping calibration")
            return {"status": "skipped", "reason": "empty_data"}
        
        raw_scores = np.asarray(raw_scores, dtype=float)
        hit_flags = np.asarray(hit_flags, dtype=float)
        
        # Create score bins
        self.bin_edges = np.linspace(0, 100, self.n_bins + 1)
        bin_indices = np.digitize(raw_scores, self.bin_edges) - 1
        bin_indices = np.clip(bin_indices, 0, self.n_bins - 1)
        
        # Compute bin-level hit rates then apply PAV for monotonic isotonic fit.
        self.calibration_mapping = {}
        report = {"bins": []}
        bin_centers = []
        bin_counts = []
        bin_actual_rates = []

        for bin_idx in range(self.n_bins):
            mask = bin_indices == bin_idx
            if np.sum(mask) == 0:
                continue
            
            bin_scores = raw_scores[mask]
            bin_hits = hit_flags[mask]
            
            bin_score_min = self.bin_edges[bin_idx]
            bin_score_max = self.bin_edges[bin_idx + 1]
            bin_center = (bin_score_min + bin_score_max) / 2.0
            
            actual_hit_rate = np.mean(bin_hits)
            count = len(bin_hits)
            expected_hit_rate = bin_center / 100.0
            bin_centers.append(float(bin_center))
            bin_counts.append(int(count))
            bin_actual_rates.append(float(actual_hit_rate))

        # Weighted pooled-adjacent-violators to enforce monotonicity.
        blocks = [
            {"start": i, "end": i, "weight": float(bin_counts[i]), "value": float(bin_actual_rates[i])}
            for i in range(len(bin_actual_rates))
        ]
        i = 0
        while i < len(blocks) - 1:
            if blocks[i]["value"] <= blocks[i + 1]["value"]:
                i += 1
                continue
            w = blocks[i]["weight"] + blocks[i + 1]["weight"]
            v = (
                (blocks[i]["weight"] * blocks[i]["value"])
                + (blocks[i + 1]["weight"] * blocks[i + 1]["value"])
            ) / max(w, 1.0)
            merged = {
                "start": blocks[i]["start"],
                "end": blocks[i + 1]["end"],
                "weight": w,
                "value": float(v),
            }
            blocks[i : i + 2] = [merged]
            if i > 0:
                i -= 1

        fitted_rates = [0.0] * len(bin_actual_rates)
        for block in blocks:
            for j in range(block["start"], block["end"] + 1):
                fitted_rates[j] = float(block["value"])

        for idx, bin_center in enumerate(bin_centers):
            expected_hit_rate = float(bin_center / 100.0)
            actual_hit_rate = float(bin_actual_rates[idx])
            fitted_hit_rate = float(fitted_rates[idx])
            calibration_gap = fitted_hit_rate - expected_hit_rate
            self.calibration_mapping[int(round(bin_center))] = fitted_hit_rate
            report["bins"].append({
                "bin_center": float(bin_center),
                "count": int(bin_counts[idx]),
                "expected_hit_rate": expected_hit_rate,
                "actual_hit_rate": actual_hit_rate,
                "fitted_hit_rate": fitted_hit_rate,
                "calibration_gap": float(calibration_gap),
                "overconfident": calibration_gap < 0,
            })

        # Compute weighted overall calibration gap.
        total_weight = max(float(sum(bin_counts)), 1.0)
        overall_gap = sum(
            float(report["bins"][k]["calibration_gap"]) * float(bin_counts[k])
            for k in range(len(report["bins"]))
        ) / total_weight
        report["overall_calibration_gap"] = float(overall_gap)
        report["method"] = method
        report["n_observations"] = int(len(raw_scores))
        report["n_bins_populated"] = len(report["bins"])
        
        self.is_fitted = True
        return report
    
    def calibrate(self, raw_score: float) -> float:
        """
        Transform raw score to calibrated score using learned mapping.
        
        If score is between bin centers, interpolate linearly.
        """
        if not self.is_fitted or self.calibration_mapping is None:
            logger.warning("Calibrator not yet fitted; returning raw score")
            return raw_score
        
        raw_score = _clip(float(raw_score), 0.0, 100.0)
        
        # Find nearest bin centers for interpolation
        bin_centers = sorted(self.calibration_mapping.keys())
        if len(bin_centers) == 0:
            return raw_score
        
        if raw_score <= bin_centers[0]:
            return self.calibration_mapping[bin_centers[0]] * 100.0
        if raw_score >= bin_centers[-1]:
            return self.calibration_mapping[bin_centers[-1]] * 100.0
        
        # Linear interpolation between bin centers
        for i in range(len(bin_centers) - 1):
            x0, x1 = bin_centers[i], bin_centers[i + 1]
            y0, y1 = self.calibration_mapping[x0], self.calibration_mapping[x1]
            
            if x0 <= raw_score <= x1:
                t = (raw_score - x0) / max(x1 - x0, 1.0)
                interpolated_hit_rate = y0 + t * (y1 - y0)
                return _clip(interpolated_hit_rate * 100.0, 0.0, 100.0)
        
        return raw_score


class TemperatureScaler:
    """
    Temperature scaling: scale logits/scores before softmax.
    
    Formula:
        calibrated_score = 50 + (raw_score - 50) / T
    
    where T is learned to minimize calibration error.
    """
    
    def __init__(self):
        self.temperature = 1.0
        self.is_fitted = False
    
    def fit(
        self,
        raw_scores: np.ndarray,
        hit_flags: np.ndarray,
        learning_rate: float = 0.01,
        max_iter: int = 100
    ) -> Dict:
        """
        Learn optimal temperature parameter via gradient descent.
        
        Objective: minimize calibration error (expected - actual)^2
        """
        if len(raw_scores) == 0:
            return {"status": "skipped", "reason": "empty_data"}
        
        raw_scores = np.asarray(raw_scores, dtype=float)
        hit_flags = np.asarray(hit_flags, dtype=float)
        
        best_temp = 1.0
        best_error = float('inf')
        losses = []
        
        # Grid search + refinement
        for temp in np.linspace(0.5, 2.0, 31):
            # Scale scores
            scaled = 50.0 + (raw_scores - 50.0) / max(temp, 0.1)
            scaled = np.clip(scaled, 0.0, 100.0)
            
            # Compute calibration bins
            expected_hit_rates = scaled / 100.0
            actual_hit_rates = hit_flags
            
            # MSE between expected and actual
            mse = np.mean((expected_hit_rates - actual_hit_rates) ** 2)
            losses.append(mse)
            
            if mse < best_error:
                best_error = mse
                best_temp = temp
        
        self.temperature = best_temp
        self.is_fitted = True
        
        return {
            "status": "fitted",
            "temperature": float(self.temperature),
            "best_calibration_mse": float(best_error),
            "temperature_search_range": [0.5, 2.0],
            "temperature_search_steps": 31,
            "losses": [float(l) for l in losses]
        }
    
    def calibrate(self, raw_score: float) -> float:
        """Transform raw score via temperature scaling."""
        if not self.is_fitted:
            return raw_score
        
        raw_score = float(raw_score)
        scaled = 50.0 + (raw_score - 50.0) / max(self.temperature, 0.1)
        return _clip(scaled, 0.0, 100.0)


class ScoreCalibrator:
    """
    High-level API for score calibration with multiple backends.
    
    Supports:
    - Isotonic regression (monotonic non-decreasing mapping)
    - Temperature scaling (linear scaling of logits)
    - No calibration (identity function)
    """
    
    def __init__(self, method: str = "isotonic", n_bins: int = 10):
        self.method = method.lower()
        self.n_bins = n_bins
        self.backend = None
        self.config = {"method": method, "n_bins": n_bins}
    
    def fit(self, raw_scores: List[float], hit_flags: List[float]) -> Dict:
        """
        Train calibrator on labeled data.
        
        Args:
            raw_scores: List of raw composite scores [0-100]
            hit_flags: List of binary hit flags (1 = hit at horizon)
        
        Returns:
            Training report with calibration statistics
        """
        if self.method == "isotonic":
            self.backend = IsotonicCalibrator(n_bins=self.n_bins)
            report = self.backend.fit(
                np.asarray(raw_scores),
                np.asarray(hit_flags),
                method="isotonic_regression"
            )
        elif self.method == "temperature":
            self.backend = TemperatureScaler()
            report = self.backend.fit(
                np.asarray(raw_scores),
                np.asarray(hit_flags)
            )
        else:
            report = {"status": "skipped", "reason": f"unknown_method: {self.method}"}
        
        report["config"] = self.config
        return report
    
    def calibrate(self, raw_score: float) -> float:
        """
        Calibrate a single score.
        
        Args:
            raw_score: Raw composite score [0-100]
        
        Returns:
            Calibrated score [0-100]
        """
        if self.backend is None:
            logger.warning(f"Calibrator not fitted (method={self.method}); returning raw score")
            return float(raw_score)
        
        return self.backend.calibrate(float(raw_score))
    
    def calibrate_batch(self, raw_scores: List[float]) -> List[float]:
        """Calibrate multiple scores."""
        return [self.calibrate(score) for score in raw_scores]
    
    def save_to_file(self, filepath: str) -> None:
        """Persist calibrator state to JSON."""
        state = {
            "method": self.method,
            "n_bins": self.n_bins,
            "config": self.config
        }
        
        if self.method == "isotonic" and self.backend:
            state["calibration_mapping"] = {
                str(k): float(v) 
                for k, v in (self.backend.calibration_mapping or {}).items()
            }
            if self.backend.bin_edges is not None:
                state["bin_edges"] = [float(x) for x in self.backend.bin_edges]
        
        elif self.method == "temperature" and self.backend:
            state["temperature"] = float(self.backend.temperature)
        
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
        
        logger.info(f"Calibrator saved to {filepath}")
    
    @classmethod
    def load_from_file(cls, filepath: str) -> 'ScoreCalibrator':
        """Restore calibrator state from JSON."""
        with open(filepath, 'r') as f:
            state = json.load(f)
        
        calibrator = cls(
            method=state.get("method", "isotonic"),
            n_bins=state.get("n_bins", 10)
        )
        
        if state.get("method") == "isotonic":
            backend = IsotonicCalibrator(n_bins=state.get("n_bins", 10))
            backend.calibration_mapping = {
                int(k): float(v) 
                for k, v in state.get("calibration_mapping", {}).items()
            }
            if "bin_edges" in state:
                backend.bin_edges = np.array(state["bin_edges"])
            backend.is_fitted = len(backend.calibration_mapping) > 0
            calibrator.backend = backend
        
        elif state.get("method") == "temperature":
            backend = TemperatureScaler()
            backend.temperature = float(state.get("temperature", 1.0))
            backend.is_fitted = True
            calibrator.backend = backend
        
        logger.info(f"Calibrator loaded from {filepath}")
        return calibrator


# ============================================================================
# Convenience Functions
# ============================================================================

_global_calibrator: Optional[ScoreCalibrator] = None
_calibration_autoload_attempted = False
_loaded_calibrator_path: Optional[Path] = None
_loaded_calibrator_mtime: Optional[float] = None
DEFAULT_CALIBRATOR_PATH = Path("models_store") / "runtime_score_calibrator.json"


def initialize_calibrator(method: str = "isotonic", n_bins: int = 10) -> ScoreCalibrator:
    """Initialize global calibrator instance."""
    global _global_calibrator
    _global_calibrator = ScoreCalibrator(method=method, n_bins=n_bins)
    return _global_calibrator


def fit_calibrator(raw_scores: List[float], hit_flags: List[float]) -> Dict:
    """Train global calibrator on data."""
    global _global_calibrator
    if _global_calibrator is None:
        _global_calibrator = initialize_calibrator()
    return _global_calibrator.fit(raw_scores, hit_flags)


def calibrate_score(raw_score: float) -> float:
    """Apply global calibration to a single score."""
    global _global_calibrator
    if _global_calibrator is None:
        logger.warning("Global calibrator not initialized; returning raw score")
        return float(raw_score)
    return _global_calibrator.calibrate(raw_score)


def calibrate_scores(raw_scores: List[float]) -> List[float]:
    """Apply global calibration to multiple scores."""
    global _global_calibrator
    if _global_calibrator is None:
        logger.warning("Global calibrator not initialized; returning raw scores")
        return list(raw_scores)
    return _global_calibrator.calibrate_batch(raw_scores)


def get_calibrator() -> Optional[ScoreCalibrator]:
    """Get reference to global calibrator instance."""
    return _global_calibrator


def get_calibrator_runtime_metadata(filepath: Optional[str] = None) -> Dict[str, object]:
    """Describe the currently loaded runtime calibrator state."""
    path = Path(filepath or os.getenv("RUNTIME_SCORE_CALIBRATOR_PATH") or DEFAULT_CALIBRATOR_PATH)
    active_method = _global_calibrator.method if _global_calibrator is not None else None
    return {
        "calibrator_loaded": _global_calibrator is not None,
        "active_method": active_method,
        "requested_artifact_path": str(path),
        "loaded_artifact_path": str(_loaded_calibrator_path) if _loaded_calibrator_path is not None else None,
    }


def try_load_calibrator(filepath: Optional[str] = None) -> bool:
    """Best-effort loader for runtime calibrator artifact."""
    global _global_calibrator, _loaded_calibrator_path, _loaded_calibrator_mtime
    path = Path(filepath or os.getenv("RUNTIME_SCORE_CALIBRATOR_PATH") or DEFAULT_CALIBRATOR_PATH)
    if not path.exists():
        return False
    try:
        _global_calibrator = ScoreCalibrator.load_from_file(str(path))
        _loaded_calibrator_path = path.resolve()
        _loaded_calibrator_mtime = float(path.stat().st_mtime)
        logger.info("Loaded runtime score calibrator from %s", path)
        return True
    except Exception as exc:
        logger.warning("Failed to load runtime score calibrator from %s: %s", path, exc)
        return False


def _needs_calibrator_reload(filepath: Optional[str]) -> bool:
    global _loaded_calibrator_path, _loaded_calibrator_mtime
    target = Path(filepath or os.getenv("RUNTIME_SCORE_CALIBRATOR_PATH") or DEFAULT_CALIBRATOR_PATH)
    if not target.exists():
        return False
    target_resolved = target.resolve()
    try:
        target_mtime = float(target.stat().st_mtime)
    except Exception:
        return False

    if _loaded_calibrator_path is None:
        return True
    if target_resolved != _loaded_calibrator_path:
        return True
    if _loaded_calibrator_mtime is None:
        return True
    return target_mtime > _loaded_calibrator_mtime + 1e-9


def apply_score_calibration(
    raw_composite_score: float,
    calibration_backend: str = "isotonic",
    calibrator_path: Optional[str] = None,
) -> int:
    """
    Apply score calibration to a raw composite score.
    
    Purpose:
        Wrapper for runtime score calibration application.
        
    Args:
        raw_composite_score: Raw composite score (0-100)
        calibration_backend: "isotonic" or "temperature" (ignored if using global calibrator)
        calibrator_path: Optional path to persisted calibrator artifact
    
    Returns:
        Calibrated score (0-100, integer)
    """
    global _global_calibrator, _calibration_autoload_attempted
    if _global_calibrator is None and not _calibration_autoload_attempted:
        _calibration_autoload_attempted = True
        try_load_calibrator(filepath=calibrator_path)
    elif _global_calibrator is not None and _needs_calibrator_reload(calibrator_path):
        try_load_calibrator(filepath=calibrator_path)

    if _global_calibrator is None:
        # Safe fallback: do not distort scores without a fitted calibrator.
        return int(max(0, min(100, round(float(raw_composite_score)))))

    calibrated = calibrate_score(float(raw_composite_score))
    return int(max(0, min(100, round(calibrated))))

"""
Shared TrainedMovePredictor wrapper used by both the model registry builder
and the production model loader.

This class is the canonical deserialization target for all registry .joblib
artifacts.  It implements `predict_probability(X)` which is the interface
expected by `models.ml_move_predictor.MLMovePredictor`.
"""
from __future__ import annotations

import numpy as np

# N_FEATURES is imported lazily below to avoid circular imports in rare
# edge cases; the fallback value 33 is correct for the current feature set.
_N_FEATURES = 33


class TrainedMovePredictor:
    """Wrapper that adapts a trained sklearn model to the MovePredictor interface.

    Stores feature_names and feature_mask so production code knows exactly
    which columns of the 33-feature vector to feed.
    """

    def __init__(self, model, feature_names, feature_mask=None):
        self.model = model
        self.feature_names = feature_names
        self.feature_mask = feature_mask  # boolean mask over 33 original features

    def predict_probability(self, X):
        arr = np.asarray(X, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)

        # If caller passes full 33-feature vector, apply mask automatically
        if (
            self.feature_mask is not None
            and arr.shape[1] == _N_FEATURES
            and len(self.feature_names) < _N_FEATURES
        ):
            arr = arr[:, self.feature_mask]

        if arr.shape[1] != len(self.feature_names):
            return None

        probs = self.model.predict_proba(arr)[:, 1]
        result = [round(float(p), 4) for p in probs]
        return result[0] if len(result) == 1 else result

#!/usr/bin/env python3
"""
Retrain regime-specific time-decay half-life parameters from signal_cumul in one pass.

Outputs:
  - documentation/improvement_reports/time_decay_retrain_signal_cumul_<date>.json
  - documentation/improvement_reports/time_decay_retrain_signal_cumul_<date>.csv
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH, load_signals_dataset


@dataclass
class RegimeFit:
    gamma_regime: str
    n: int
    hr_60m: float
    hr_120m: float
    hr_close: float
    fitted_half_life_m: int
    fit_mse: float


def _clip01(v: float) -> float:
    return float(max(0.0, min(1.0, v)))


def _decay_factor(elapsed_minutes: float, half_life: float, lam: float = 1.5) -> float:
    t_ratio = float(elapsed_minutes) / max(float(half_life), 1.0)
    return float(np.clip(np.exp(-np.log(2.0) * (t_ratio ** lam)), 0.0, 1.0))


def _target_decay_from_hits(hr60: float, hr120: float, hr_close: float) -> Dict[str, float]:
    """
    Convert hit rates into target decay factors using edge magnitude vs 50% baseline.
    """
    edge60 = abs(float(hr60) - 0.5)
    edge120 = abs(float(hr120) - 0.5)
    edge_close = abs(float(hr_close) - 0.5)

    # Fall back to direct HR ratio when 60m edge is tiny.
    if edge60 < 1e-3:
        base = max(abs(float(hr60)), 1e-3)
        d60 = 1.0
        d120 = _clip01(abs(float(hr120)) / base)
        dclose = _clip01(abs(float(hr_close)) / base)
    else:
        d60 = 1.0
        d120 = _clip01(edge120 / edge60)
        dclose = _clip01(edge_close / edge60)

    return {"60m": d60, "120m": d120, "session_close": dclose}


def _fit_half_life(target_decay: Dict[str, float], lam: float = 1.5) -> tuple[int, float]:
    # Approximate session-close as 360m horizon for fitting purposes.
    horizons = {"60m": 60.0, "120m": 120.0, "session_close": 360.0}

    best_hl = 70
    best_mse = 1e9
    for hl in range(25, 241):
        errs: List[float] = []
        for k, t in horizons.items():
            pred = _decay_factor(t, hl, lam=lam)
            obs = float(target_decay.get(k, 0.0))
            errs.append((pred - obs) ** 2)
        mse = float(np.mean(errs))
        if mse < best_mse:
            best_mse = mse
            best_hl = hl

    # Round to nearest 5 minutes for stable operational configs.
    rounded = int(round(best_hl / 5.0) * 5)
    return rounded, best_mse


def _canonical_regime(v: object) -> str:
    txt = str(v or "").upper().strip()
    if "POSITIVE" in txt:
        return "POSITIVE_GAMMA"
    if "NEGATIVE" in txt:
        return "NEGATIVE_GAMMA"
    return "NEUTRAL_GAMMA"


def main() -> int:
    if not CUMULATIVE_DATASET_PATH.exists():
        raise FileNotFoundError(f"Cumulative dataset not found: {CUMULATIVE_DATASET_PATH}")

    df = load_signals_dataset(CUMULATIVE_DATASET_PATH)
    if df.empty:
        raise RuntimeError("Cumulative dataset is empty")

    required_cols = ["gamma_regime", "correct_60m", "correct_120m", "correct_session_close"]
    for col in required_cols:
        if col not in df.columns:
            raise KeyError(f"Missing required column: {col}")

    work = df.copy()
    work["gamma_regime_norm"] = work["gamma_regime"].map(_canonical_regime)
    work["correct_60m"] = pd.to_numeric(work["correct_60m"], errors="coerce").fillna(0)
    work["correct_120m"] = pd.to_numeric(work["correct_120m"], errors="coerce").fillna(0)
    work["correct_session_close"] = pd.to_numeric(work["correct_session_close"], errors="coerce").fillna(0)

    fits: List[RegimeFit] = []
    for regime in ["POSITIVE_GAMMA", "NEGATIVE_GAMMA", "NEUTRAL_GAMMA"]:
        sub = work.loc[work["gamma_regime_norm"] == regime]
        if sub.empty:
            # Conservative fallback if a regime is absent.
            fallback_hl = 90 if regime == "POSITIVE_GAMMA" else (45 if regime == "NEGATIVE_GAMMA" else 70)
            fits.append(RegimeFit(regime, 0, 0.0, 0.0, 0.0, fallback_hl, 0.0))
            continue

        hr60 = float((sub["correct_60m"] > 0).mean())
        hr120 = float((sub["correct_120m"] > 0).mean())
        hr_close = float((sub["correct_session_close"] > 0).mean())

        target_decay = _target_decay_from_hits(hr60, hr120, hr_close)
        hl, mse = _fit_half_life(target_decay, lam=1.5)
        fits.append(
            RegimeFit(
                gamma_regime=regime,
                n=int(len(sub)),
                hr_60m=hr60,
                hr_120m=hr120,
                hr_close=hr_close,
                fitted_half_life_m=hl,
                fit_mse=mse,
            )
        )

    out_dir = Path("documentation") / "improvement_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    result = {
        "generated_at": datetime.now().isoformat(),
        "dataset_path": str(CUMULATIVE_DATASET_PATH),
        "dataset_rows": int(len(work)),
        "lambda": 1.5,
        "regime_fits": [f.__dict__ for f in fits],
        "recommended_config": {
            "time_decay_positive_gamma_half_life_m": int(next(f.fitted_half_life_m for f in fits if f.gamma_regime == "POSITIVE_GAMMA")),
            "time_decay_negative_gamma_half_life_m": int(next(f.fitted_half_life_m for f in fits if f.gamma_regime == "NEGATIVE_GAMMA")),
            "time_decay_neutral_gamma_half_life_m": int(next(f.fitted_half_life_m for f in fits if f.gamma_regime == "NEUTRAL_GAMMA")),
        },
    }

    json_path = out_dir / f"time_decay_retrain_signal_cumul_{stamp}.json"
    csv_path = out_dir / f"time_decay_retrain_signal_cumul_{stamp}.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    pd.DataFrame([f.__dict__ for f in fits]).to_csv(csv_path, index=False)

    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")
    print("Recommended half-lives:")
    for k, v in result["recommended_config"].items():
        print(f"  {k}={v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

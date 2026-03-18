"""
Combined EV + Regime-Switching Policy — Research Runner
=========================================================
Single entry-point that executes both research pipelines in sequence:

  1. EV-based sizing evaluation
  2. Regime-switching policy evaluation

Usage:
    python -m research.ml_evaluation.ev_and_regime_policy.runner

Author: Pramit Dutta
Organization: Quant Engines

RESEARCH ONLY — never imported by production engine paths.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
OUTPUT_DIR = Path(__file__).resolve().parent


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


def run_all() -> dict[str, Any]:
    """Execute both research pipelines and return a combined summary."""
    _configure_logging()
    logger.info("=" * 70)
    logger.info("  EV + Regime-Switching Policy — Combined Runner")
    logger.info("=" * 70)

    results: dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }

    # ── Phase 1: EV-sizing evaluation ────────────────────────────────
    logger.info("")
    logger.info("▸ Phase 1 / 2 — EV-Sizing Evaluation")
    logger.info("-" * 50)
    try:
        from research.ml_evaluation.ev_and_regime_policy.ev_evaluation import (
            run_ev_sizing_evaluation,
        )
        ev_summary = run_ev_sizing_evaluation()
        results["ev_sizing"] = {"status": "success", "summary": ev_summary}
        logger.info("✓ EV sizing evaluation complete")
    except Exception:
        logger.exception("✗ EV sizing evaluation FAILED")
        results["ev_sizing"] = {"status": "error", "error": _fmt_exc()}

    # ── Phase 2: Regime-switching policy evaluation ──────────────────
    logger.info("")
    logger.info("▸ Phase 2 / 2 — Regime-Switching Policy Evaluation")
    logger.info("-" * 50)
    try:
        from research.ml_evaluation.ev_and_regime_policy.regime_policy_evaluation import (
            run_regime_policy_evaluation,
        )
        regime_summary = run_regime_policy_evaluation()
        results["regime_switching"] = {"status": "success", "summary": regime_summary}
        logger.info("✓ Regime-switching evaluation complete")
    except Exception:
        logger.exception("✗ Regime-switching evaluation FAILED")
        results["regime_switching"] = {"status": "error", "error": _fmt_exc()}

    # ── Combined JSON ────────────────────────────────────────────────
    out_path = OUTPUT_DIR / "combined_research_report.json"
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    logger.info("")
    logger.info("Combined report → %s", out_path)
    logger.info("=" * 70)
    logger.info("  Done.")
    logger.info("=" * 70)
    return results


def _fmt_exc() -> str:
    import traceback
    return traceback.format_exc()


# ── __main__ support ─────────────────────────────────────────────────
if __name__ == "__main__":
    run_all()

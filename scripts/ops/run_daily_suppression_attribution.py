#!/usr/bin/env python3
"""Generate daily directional-suppression attribution diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.signal_evaluation_scoring import SIGNAL_EVALUATION_SELECTION_POLICY  # noqa: E402
from research.signal_evaluation.daily_suppression_attribution import (  # noqa: E402
    DEFAULT_DAILY_SUPPRESSION_ATTRIBUTION_DIR,
    write_daily_suppression_attribution_report,
)
from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=CUMULATIVE_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DAILY_SUPPRESSION_ATTRIBUTION_DIR)
    parser.add_argument("--date", default=None, help="Optional YYYY-MM-DD session date in Asia/Kolkata.")
    parser.add_argument(
        "--probability-floor",
        type=float,
        default=float(SIGNAL_EVALUATION_SELECTION_POLICY.get("move_probability_floor", 0.60)),
        help="Diagnostic move-probability floor used for attribution only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_daily_suppression_attribution_report(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        report_date=args.date,
        probability_floor=args.probability_floor,
    )
    report = result.get("report", {}) or {}
    payload = {
        "report_type": report.get("report_type"),
        "report_date": report.get("report_date"),
        "directional_count": report.get("directional_count"),
        "trade_qualified_count": report.get("trade_qualified_count"),
        "suppressed_directional_count": report.get("suppressed_directional_count"),
        "suppression_rate": report.get("suppression_rate"),
        "top_blocker": (report.get("blocker_counts") or [{}])[0],
        "suppressed_outcome": report.get("suppressed_outcome"),
        "near_miss_count": report.get("near_miss_count"),
        "latest_markdown_path": result.get("latest_markdown_path"),
        "latest_json_path": result.get("latest_json_path"),
        "latest_suppressed_rows_path": result.get("latest_suppressed_rows_path"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

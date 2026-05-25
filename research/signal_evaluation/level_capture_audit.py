"""Audit whether signal datasets capture raw market-structure levels.

ET-08 wall/retest diagnostics need raw levels, not only derived context labels.
This audit checks whether support/resistance, gamma flip, max pain, liquidity
levels, and dealer maps are present with enough coverage for replay work.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from research.signal_evaluation.dataset import CUMULATIVE_DATASET_PATH
from research.signal_evaluation.report_manifest import write_report_reproducibility_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEVEL_CAPTURE_AUDIT_DIR = (
    PROJECT_ROOT / "research" / "signal_evaluation" / "reports" / "level_capture_audit"
)

RAW_LEVEL_COLUMNS = (
    "support_wall",
    "support_wall_distance_pts",
    "support_wall_distance_pct",
    "resistance_wall",
    "resistance_wall_distance_pts",
    "resistance_wall_distance_pct",
    "gamma_flip",
    "gamma_flip_distance_pct",
    "gamma_flip_drift_points",
    "gamma_flip_drift_direction",
    "max_pain",
    "max_pain_dist",
    "max_pain_zone",
    "max_pain_distance_pct",
    "liquidity_levels_json",
    "gamma_clusters_json",
    "dealer_liquidity_map_json",
)

DERIVED_CONTEXT_COLUMNS = (
    "spot_vs_flip",
    "historical_wall_state",
    "historical_wall_interpretation",
    "historical_max_pain_state",
    "historical_max_pain_interpretation",
)

MIN_REPLAY_COVERAGE_PCT = 60.0
CORE_REPLAY_COLUMNS = (
    "support_wall",
    "resistance_wall",
    "gamma_flip",
    "max_pain",
)


def _round(value: Any, digits: int = 2) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(number):
        return None
    return round(number, digits)


def _column_coverage(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    present = column in frame.columns
    if not present:
        return {
            "column": column,
            "present": False,
            "non_null_rows": 0,
            "coverage_pct": 0.0,
        }
    non_null = int(frame[column].notna().sum())
    return {
        "column": column,
        "present": True,
        "non_null_rows": non_null,
        "coverage_pct": _round(non_null / len(frame) * 100.0 if len(frame) else 0.0),
    }


def build_level_capture_audit(frame: pd.DataFrame) -> dict[str, Any]:
    raw = [_column_coverage(frame, column) for column in RAW_LEVEL_COLUMNS]
    derived = [_column_coverage(frame, column) for column in DERIVED_CONTEXT_COLUMNS]
    raw_by_name = {row["column"]: row for row in raw}
    missing_raw = [column for column, row in raw_by_name.items() if not row["present"]]
    low_coverage_core = [
        column
        for column in CORE_REPLAY_COLUMNS
        if (raw_by_name.get(column) or {}).get("coverage_pct", 0.0) < MIN_REPLAY_COVERAGE_PCT
    ]
    missing_core = [column for column in CORE_REPLAY_COLUMNS if column in missing_raw]
    optional_missing = [column for column in missing_raw if column not in CORE_REPLAY_COLUMNS]
    core_ready = not missing_core and not low_coverage_core
    derived_available = any(row["present"] and row["non_null_rows"] > 0 for row in derived)
    if core_ready and not optional_missing:
        readiness = "REPLAY_READY"
    elif core_ready:
        readiness = "CORE_REPLAY_READY_OPTIONAL_FIELDS_MISSING"
    elif derived_available:
        readiness = "FORWARD_CAPTURE_REQUIRED_DERIVED_CONTEXT_ONLY"
    else:
        readiness = "FORWARD_CAPTURE_REQUIRED_NO_LEVEL_CONTEXT"

    return {
        "report_type": "level_capture_audit",
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "row_count": int(len(frame)),
        "readiness": readiness,
        "minimum_replay_coverage_pct": MIN_REPLAY_COVERAGE_PCT,
        "core_replay_columns": list(CORE_REPLAY_COLUMNS),
        "missing_raw_level_columns": missing_raw,
        "missing_core_level_columns": missing_core,
        "optional_missing_raw_level_columns": optional_missing,
        "low_coverage_core_columns": low_coverage_core,
        "raw_level_coverage": raw,
        "derived_context_coverage": derived,
        "interpretation": (
            "Core raw level fields are sufficiently captured for ET-08 support/resistance/gamma/max-pain replay."
            if core_ready
            else "ET-08 wall/retest replay needs forward-captured raw levels; derived wall/max-pain context alone is insufficient."
        ),
    }


def render_level_capture_audit_markdown(report: dict[str, Any]) -> str:
    def table(rows: list[dict[str, Any]]) -> list[str]:
        if not rows:
            return ["No rows available."]
        columns = ["column", "present", "non_null_rows", "coverage_pct"]
        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        for row in rows:
            lines.append("| " + " | ".join(str(row.get(column, "-")) for column in columns) + " |")
        return lines

    lines = [
        "# Level Capture Audit",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        "",
        "## Readiness",
        "",
        f"- Row count: `{report.get('row_count')}`",
        f"- Readiness: `{report.get('readiness')}`",
        f"- Interpretation: {report.get('interpretation')}",
        "",
        "## Missing / Low Coverage",
        "",
        f"- Missing raw level columns: `{report.get('missing_raw_level_columns')}`",
        f"- Missing core level columns: `{report.get('missing_core_level_columns')}`",
        f"- Optional missing raw level columns: `{report.get('optional_missing_raw_level_columns')}`",
        f"- Low-coverage core columns: `{report.get('low_coverage_core_columns')}`",
        "",
        "## Raw Level Coverage",
        "",
    ]
    lines.extend(table(report.get("raw_level_coverage") or []))
    lines.extend(["", "## Derived Context Coverage", ""])
    lines.extend(table(report.get("derived_context_coverage") or []))
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This audit does not alter live decisions.",
            "- ET-08 replay should wait for raw support/resistance/gamma/max-pain coverage, not rely only on historical context labels.",
            "",
        ]
    )
    return "\n".join(lines)


def write_level_capture_audit(
    *,
    dataset_path: str | Path = CUMULATIVE_DATASET_PATH,
    output_dir: str | Path = DEFAULT_LEVEL_CAPTURE_AUDIT_DIR,
) -> dict[str, Any]:
    dataset = Path(dataset_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(dataset, low_memory=False) if dataset.exists() else pd.DataFrame()
    report = build_level_capture_audit(frame)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output / f"level_capture_audit_{timestamp}.json"
    markdown_path = output / f"level_capture_audit_{timestamp}.md"
    latest_json_path = output / "latest_level_capture_audit.json"
    latest_markdown_path = output / "latest_level_capture_audit.md"
    json_text = json.dumps(report, indent=2, sort_keys=True, default=str)
    markdown_text = render_level_capture_audit_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    markdown_path.write_text(markdown_text, encoding="utf-8")
    latest_markdown_path.write_text(markdown_text, encoding="utf-8")
    manifest_path = write_report_reproducibility_manifest(
        report_path=markdown_path,
        dataset_path=dataset,
        frame=frame,
        report_kind="level_capture_audit",
        mode="research",
        run_evaluation=False,
        narrative=False,
    )
    return {
        "report": report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "latest_json_path": str(latest_json_path),
        "latest_markdown_path": str(latest_markdown_path),
        "manifest_path": str(manifest_path),
    }

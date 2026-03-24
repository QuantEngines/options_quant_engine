#!/usr/bin/env python3
"""
Guarded Macro Seed Sweep
========================

Purpose:
    Run a guarded multi-seed search on macro-news threshold/score parameters
    only, materialize candidate packs, and auto-select the best non-negative
    candidate if one exists.

Safety:
    Offline-only research workflow. This script does not promote packs or mutate
    live runtime state.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.signal_evaluation.dataset import SIGNAL_DATASET_PATH
from tuning.comparison import build_candidate_vs_production_report, write_candidate_vs_production_report
from tuning.experiments import run_parameter_experiment
from tuning.governance import materialize_candidate_parameter_pack
from tuning.packs import RESEARCH_PARAMETER_PACKS_DIR, resolve_parameter_pack
from tuning.registry import get_parameter_registry
from tuning.search import run_coordinate_descent_search, run_latin_hypercube_search


OUTPUT_ROOT = ROOT / "research" / "parameter_tuning" / "guarded_seed_sweeps"
REPORTS_ROOT = ROOT / "research" / "parameter_tuning" / "reports"


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _score_result(result: dict[str, Any]) -> float:
    validation = dict(result.get("validation_results", {}))
    robustness = dict(result.get("robustness_metrics", {}))
    out_of_sample_score = float(validation.get("aggregate_out_of_sample_score", result.get("objective_score", 0.0)))
    robustness_score = float(robustness.get("robustness_score", 0.0))
    comparison = dict(result.get("comparison_summary", {}))
    aggregate_delta = dict(comparison.get("aggregate_comparison", {}).get("metric_deltas", {}))
    direction_delta = float(aggregate_delta.get("direction_hit_rate", 0.0))
    return round(out_of_sample_score + (0.15 * robustness_score) + (0.10 * direction_delta), 6)


def _resolved_pack_values(pack_name: str) -> dict[str, Any]:
    registry = get_parameter_registry()
    resolved = resolve_parameter_pack(pack_name)
    values: dict[str, Any] = {}
    for key, definition in registry.items():
        values[key] = resolved.overrides.get(key, definition.default_value)
    return values


def _macro_threshold_score_keys() -> list[str]:
    registry = get_parameter_registry()
    keys: list[tuple[int, str]] = []
    for key, definition in registry.items():
        if definition.group != "macro_news" or not definition.tunable:
            continue
        if not key.startswith("macro_news.adjustment."):
            continue
        field_name = key.split(".")[-1]
        if ("threshold" in field_name) or ("score" in field_name):
            keys.append((definition.tuning_priority, key))
    return [k for _, k in sorted(keys)]


def _build_walk_forward_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "split_type": "rolling",
        "train_window_days": int(args.train_window_days),
        "validation_window_days": int(args.validation_window_days),
        "step_size_days": int(args.step_size_days),
        "minimum_train_rows": int(args.minimum_train_rows),
        "minimum_validation_rows": int(args.minimum_validation_rows),
    }


def _seed_candidates(args: argparse.Namespace) -> list[int]:
    if args.seeds:
        return [int(x) for x in args.seeds]
    # Default 12-seed sweep.
    return [11, 13, 17, 19, 23, 29, 31, 37, 41, 47, 59, 73]


def run_sweep(args: argparse.Namespace) -> dict[str, Any]:
    run_stamp = _run_id()
    out_dir = OUTPUT_ROOT / f"guarded_macro_threshold_score_sweep_{run_stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    parameter_keys = _macro_threshold_score_keys()
    if not parameter_keys:
        raise ValueError("No macro threshold/score parameter keys found in registry")

    seeds = _seed_candidates(args)
    walk_forward_config = _build_walk_forward_config(args)
    baseline_values = _resolved_pack_values(args.baseline_pack)

    summary_rows: list[dict[str, Any]] = []
    candidate_names: list[str] = []

    production_result_cache = run_parameter_experiment(
        args.baseline_pack,
        dataset_path=args.dataset_path,
        walk_forward_config=walk_forward_config,
        persist=True,
    ).to_dict()

    for seed in seeds:
        lhs_results = run_latin_hypercube_search(
            args.baseline_pack,
            parameter_keys=parameter_keys,
            dataset_path=args.dataset_path,
            iterations=max(int(args.lhs_iterations), 1),
            seed=int(seed),
            allow_live_unsafe=False,
            walk_forward_config=walk_forward_config,
            comparison_baseline_pack=args.baseline_pack,
            persist=True,
        )
        lhs_best = max(lhs_results, key=_score_result) if lhs_results else None
        coord_seed_overrides = dict(lhs_best.get("parameter_overrides", {})) if lhs_best else {}

        coord_results = run_coordinate_descent_search(
            args.baseline_pack,
            parameter_keys=parameter_keys,
            dataset_path=args.dataset_path,
            initial_overrides=coord_seed_overrides,
            passes=max(int(args.coordinate_passes), 1),
            allow_live_unsafe=False,
            walk_forward_config=walk_forward_config,
            comparison_baseline_pack=args.baseline_pack,
            persist=True,
        )

        combined = list(lhs_results) + list(coord_results)
        if not combined:
            summary_rows.append(
                {
                    "seed": int(seed),
                    "status": "no_results",
                }
            )
            continue

        best_result = max(combined, key=_score_result)
        effective_overrides = dict(best_result.get("parameter_overrides", {}))
        candidate_overrides = {
            key: value
            for key, value in effective_overrides.items()
            if baseline_values.get(key) != value
        }

        if not candidate_overrides:
            summary_rows.append(
                {
                    "seed": int(seed),
                    "status": "no_delta_vs_baseline",
                }
            )
            continue

        candidate_name = f"{args.candidate_prefix}_{run_stamp}_s{seed}"
        candidate_names.append(candidate_name)

        candidate_pack_path = materialize_candidate_parameter_pack(
            candidate_pack_name=candidate_name,
            parent_pack_name=args.baseline_pack,
            overrides=candidate_overrides,
            notes=(
                "Guarded seed sweep; macro threshold/score only; size fields frozen at baseline"
            ),
            metadata={
                "created_by": args.created_by,
                "seed": int(seed),
                "source_best_experiment_id": best_result.get("experiment_id"),
                "search_scope": "macro_news.adjustment threshold/score only",
                "size_fields_frozen": True,
                "run_id": run_stamp,
            },
            output_dir=RESEARCH_PARAMETER_PACKS_DIR,
            overwrite=False,
        )

        candidate_result = run_parameter_experiment(
            candidate_name,
            dataset_path=args.dataset_path,
            walk_forward_config=walk_forward_config,
            comparison_baseline_pack=args.baseline_pack,
            notes="Guarded seed sweep candidate evaluation",
            persist=True,
        ).to_dict()

        report = build_candidate_vs_production_report(
            production_pack_name=args.baseline_pack,
            candidate_pack_name=candidate_name,
            production_result=production_result_cache,
            candidate_result=candidate_result,
            parameter_evidence=None,
        )
        report_paths = write_candidate_vs_production_report(
            report,
            output_dir=REPORTS_ROOT / candidate_name,
        )

        expected = dict(report.get("expected_improvement_summary", {}))
        objective_delta = float(expected.get("objective_score_delta", 0.0) or 0.0)
        validation_delta = float(expected.get("validation_out_of_sample_score_delta", 0.0) or 0.0)

        summary_rows.append(
            {
                "seed": int(seed),
                "status": "completed",
                "candidate_pack_name": candidate_name,
                "candidate_pack_path": str(candidate_pack_path),
                "recommendation_report_json": report_paths.get("json_path"),
                "recommendation_report_markdown": report_paths.get("markdown_path"),
                "objective_score_delta": round(objective_delta, 6),
                "validation_out_of_sample_score_delta": round(validation_delta, 6),
                "non_negative_objective_delta": bool(objective_delta >= 0.0),
                "changed_parameter_count": int(len(candidate_overrides)),
                "best_experiment_id": best_result.get("experiment_id"),
                "composite_search_score": _score_result(best_result),
            }
        )

    summary_df = pd.DataFrame(summary_rows)
    csv_path = out_dir / "seed_sweep_summary.csv"
    json_path = out_dir / "seed_sweep_summary.json"
    summary_df.to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(summary_rows, indent=2, sort_keys=True), encoding="utf-8")

    non_negative = [
        row for row in summary_rows
        if row.get("status") == "completed" and bool(row.get("non_negative_objective_delta"))
    ]
    non_negative_sorted = sorted(
        non_negative,
        key=lambda row: (
            float(row.get("objective_score_delta", 0.0)),
            float(row.get("validation_out_of_sample_score_delta", 0.0)),
        ),
        reverse=True,
    )
    best_non_negative = non_negative_sorted[0] if non_negative_sorted else None

    best_path = out_dir / "best_non_negative_candidate.json"
    best_path.write_text(json.dumps(best_non_negative, indent=2, sort_keys=True), encoding="utf-8")

    manifest = {
        "generated_at": _utc_now(),
        "run_id": run_stamp,
        "baseline_pack": args.baseline_pack,
        "dataset_path": str(args.dataset_path),
        "parameter_keys": parameter_keys,
        "size_fields_frozen": True,
        "seeds": seeds,
        "lhs_iterations": int(args.lhs_iterations),
        "coordinate_passes": int(args.coordinate_passes),
        "created_by": args.created_by,
        "artifact_paths": {
            "summary_csv": str(csv_path),
            "summary_json": str(json_path),
            "best_non_negative_candidate_json": str(best_path),
        },
        "candidate_packs_created": candidate_names,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "run_id": run_stamp,
        "output_dir": str(out_dir),
        "baseline_pack": args.baseline_pack,
        "seed_count": len(seeds),
        "completed_candidates": len([r for r in summary_rows if r.get("status") == "completed"]),
        "non_negative_candidates": len(non_negative),
        "best_non_negative_candidate": best_non_negative,
        "summary_csv": str(csv_path),
        "summary_json": str(json_path),
        "best_non_negative_candidate_json": str(best_path),
        "candidate_packs": candidate_names,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run guarded macro threshold/score-only seed sweep and auto-select best non-negative candidate."
    )
    parser.add_argument("--baseline-pack", default="baseline_v1")
    parser.add_argument("--dataset-path", default=str(SIGNAL_DATASET_PATH))
    parser.add_argument("--seeds", nargs="+", type=int, default=None)
    parser.add_argument("--lhs-iterations", type=int, default=14)
    parser.add_argument("--coordinate-passes", type=int, default=1)
    parser.add_argument("--train-window-days", type=int, default=180)
    parser.add_argument("--validation-window-days", type=int, default=60)
    parser.add_argument("--step-size-days", type=int, default=30)
    parser.add_argument("--minimum-train-rows", type=int, default=50)
    parser.add_argument("--minimum-validation-rows", type=int, default=20)
    parser.add_argument("--candidate-prefix", default="macro_overlay_guarded_sweep")
    parser.add_argument("--created-by", default="research")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    payload = run_sweep(args)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

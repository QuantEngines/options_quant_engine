"""
Basic search strategies for safe parameter exploration.
"""

from __future__ import annotations

import itertools
import random
from typing import Any

from tuning.experiments import run_parameter_experiment
from tuning.registry import get_parameter_registry


def _allowed_key(key: str, *, allow_live_unsafe: bool) -> bool:
    definition = get_parameter_registry().get(key)
    if not definition.tunable:
        return False
    if not allow_live_unsafe and not definition.live_safe:
        return False
    return True


def run_grid_search(
    parameter_pack_name: str,
    *,
    grid: dict[str, list[Any]],
    allow_live_unsafe: bool = False,
    selection_thresholds: dict | None = None,
    objective_weights: dict | None = None,
    persist: bool = True,
) -> list[dict[str, Any]]:
    valid_grid = {
        key: list(values)
        for key, values in grid.items()
        if _allowed_key(key, allow_live_unsafe=allow_live_unsafe)
    }
    keys = list(valid_grid)
    if not keys:
        return []

    results = []
    for combination in itertools.product(*(valid_grid[key] for key in keys)):
        overrides = dict(zip(keys, combination))
        experiment = run_parameter_experiment(
            parameter_pack_name,
            pack_overrides=overrides,
            selection_thresholds=selection_thresholds,
            objective_weights=objective_weights,
            search_metadata={"strategy": "grid_search"},
            persist=persist,
        )
        results.append(experiment.to_dict())
    return results


def run_random_search(
    parameter_pack_name: str,
    *,
    parameter_keys: list[str],
    iterations: int = 10,
    seed: int = 7,
    allow_live_unsafe: bool = False,
    selection_thresholds: dict | None = None,
    objective_weights: dict | None = None,
    persist: bool = True,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    registry = get_parameter_registry()
    eligible = [
        registry.get(key)
        for key in parameter_keys
        if key in registry.keys() and _allowed_key(key, allow_live_unsafe=allow_live_unsafe)
    ]

    results = []
    for _ in range(max(iterations, 0)):
        overrides = {}
        for definition in eligible:
            if definition.allowed_values:
                overrides[definition.key] = rng.choice(list(definition.allowed_values))
            elif definition.value_type == "int" and definition.min_value is not None and definition.max_value is not None:
                overrides[definition.key] = rng.randint(int(definition.min_value), int(definition.max_value))
            elif definition.value_type == "float" and definition.min_value is not None and definition.max_value is not None:
                overrides[definition.key] = round(rng.uniform(float(definition.min_value), float(definition.max_value)), 6)
        experiment = run_parameter_experiment(
            parameter_pack_name,
            pack_overrides=overrides,
            selection_thresholds=selection_thresholds,
            objective_weights=objective_weights,
            search_metadata={"strategy": "random_search", "seed": seed},
            persist=persist,
        )
        results.append(experiment.to_dict())
    return results

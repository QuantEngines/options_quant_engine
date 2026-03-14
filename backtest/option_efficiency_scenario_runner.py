"""
Scenario runner for deterministic option efficiency validation.
"""

from __future__ import annotations

import json
from pathlib import Path

from risk.option_efficiency_layer import build_option_efficiency_state


def load_option_efficiency_scenarios(
    path: str | Path = "config/option_efficiency_scenarios.json",
) -> list[dict]:
    scenario_path = Path(path)
    with open(scenario_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("scenarios", []))


def run_option_efficiency_scenario(
    name: str,
    path: str | Path = "config/option_efficiency_scenarios.json",
) -> dict:
    scenarios = load_option_efficiency_scenarios(path)
    for scenario in scenarios:
        if scenario.get("name") == name:
            state = build_option_efficiency_state(**scenario.get("inputs", {}))
            return {
                "scenario": scenario.get("name"),
                "inputs": scenario.get("inputs", {}),
                "expected": scenario.get("expected", {}),
                "option_efficiency_state": state,
            }
    raise ValueError(f"Unknown option efficiency scenario: {name}")

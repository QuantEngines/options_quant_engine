"""
Scenario runner for deterministic dealer hedging pressure validation.
"""

from __future__ import annotations

import json
from pathlib import Path

from risk.dealer_hedging_pressure_layer import build_dealer_hedging_pressure_state


def load_dealer_pressure_scenarios(path: str | Path = "config/dealer_hedging_pressure_scenarios.json") -> list[dict]:
    scenario_path = Path(path)
    with open(scenario_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("scenarios", []))


def run_dealer_pressure_scenario(name: str, path: str | Path = "config/dealer_hedging_pressure_scenarios.json") -> dict:
    scenarios = load_dealer_pressure_scenarios(path)
    for scenario in scenarios:
        if scenario.get("name") == name:
            state = build_dealer_hedging_pressure_state(**scenario.get("inputs", {}))
            return {
                "scenario": scenario.get("name"),
                "inputs": scenario.get("inputs", {}),
                "expected": scenario.get("expected", {}),
                "dealer_pressure_state": state,
            }
    raise ValueError(f"Unknown dealer hedging pressure scenario: {name}")

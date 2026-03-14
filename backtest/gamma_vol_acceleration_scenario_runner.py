"""
Scenario runner for deterministic gamma-vol acceleration validation.
"""

from __future__ import annotations

import json
from pathlib import Path

from risk.gamma_vol_acceleration_layer import build_gamma_vol_acceleration_state


def load_gamma_vol_scenarios(path: str | Path = "config/gamma_vol_acceleration_scenarios.json") -> list[dict]:
    scenario_path = Path(path)
    with open(scenario_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("scenarios", []))


def run_gamma_vol_scenario(name: str, path: str | Path = "config/gamma_vol_acceleration_scenarios.json") -> dict:
    scenarios = load_gamma_vol_scenarios(path)
    for scenario in scenarios:
        if scenario.get("name") == name:
            state = build_gamma_vol_acceleration_state(**scenario.get("inputs", {}))
            return {
                "scenario": scenario.get("name"),
                "inputs": scenario.get("inputs", {}),
                "expected": scenario.get("expected", {}),
                "gamma_vol_state": state,
            }
    raise ValueError(f"Unknown gamma-vol acceleration scenario: {name}")

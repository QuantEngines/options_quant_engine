import json
import time
from pathlib import Path

from strategy import score_calibration as sc


def _write_isotonic_artifact(path: Path, mapping: dict[str, float]) -> None:
    payload = {
        "method": "isotonic",
        "n_bins": 10,
        "config": {"method": "isotonic", "n_bins": 10},
        "calibration_mapping": mapping,
        "bin_edges": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_runtime_calibrator_reloads_when_artifact_changes(tmp_path):
    calibrator_path = tmp_path / "runtime_score_calibrator.json"

    # Version 1: map score 55 (bin center 55) to 10.
    _write_isotonic_artifact(
        calibrator_path,
        {
            "5": 0.0,
            "15": 0.0,
            "25": 0.0,
            "35": 0.0,
            "45": 0.0,
            "55": 0.10,
            "65": 0.10,
            "75": 0.10,
            "85": 0.10,
            "95": 0.10,
        },
    )

    # Reset module globals to mimic runtime start.
    sc._global_calibrator = None
    sc._calibration_autoload_attempted = False
    sc._loaded_calibrator_path = None
    sc._loaded_calibrator_mtime = None

    score_v1 = sc.apply_score_calibration(55.0, calibrator_path=str(calibrator_path))
    assert score_v1 == 10

    # Version 2: emulate refresh overwriting same file with new mapping.
    time.sleep(0.02)
    _write_isotonic_artifact(
        calibrator_path,
        {
            "5": 0.0,
            "15": 0.0,
            "25": 0.0,
            "35": 0.0,
            "45": 0.0,
            "55": 0.90,
            "65": 0.90,
            "75": 0.90,
            "85": 0.90,
            "95": 0.90,
        },
    )

    score_v2 = sc.apply_score_calibration(55.0, calibrator_path=str(calibrator_path))
    assert score_v2 == 90


def test_isotonic_calibrator_mapping_is_monotonic_after_fit():
    calibrator = sc.ScoreCalibrator(method="isotonic", n_bins=5)
    # Intentionally non-monotonic raw bucket hit rates.
    raw_scores = [10, 20, 30, 40, 50, 60, 70, 80, 90]
    hit_flags = [0.1, 0.2, 0.9, 0.8, 0.2, 0.3, 0.6, 0.7, 0.9]
    calibrator.fit(raw_scores, hit_flags)

    mapping = calibrator.backend.calibration_mapping
    keys = sorted(mapping)
    for k0, k1 in zip(keys, keys[1:]):
        assert mapping[k1] >= mapping[k0]

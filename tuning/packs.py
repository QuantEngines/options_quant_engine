"""
Named parameter pack loading and resolution.
"""

from __future__ import annotations

import json
from pathlib import Path

from tuning.models import ParameterPack


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARAMETER_PACKS_DIR = PROJECT_ROOT / "config" / "parameter_packs"


def _coerce_pack(payload: dict) -> ParameterPack:
    return ParameterPack(
        name=str(payload.get("name") or "").strip(),
        version=str(payload.get("version") or "1.0.0").strip(),
        description=str(payload.get("description") or "").strip(),
        parent=(str(payload.get("parent")).strip() or None) if payload.get("parent") is not None else None,
        notes=payload.get("notes"),
        tags=tuple(payload.get("tags") or ()),
        metadata=dict(payload.get("metadata") or {}),
        overrides=dict(payload.get("overrides") or {}),
    )


def list_parameter_packs(packs_dir: str | Path = PARAMETER_PACKS_DIR) -> list[str]:
    path = Path(packs_dir)
    if not path.exists():
        return []
    return sorted(file.stem for file in path.glob("*.json"))


def load_parameter_pack(name: str, packs_dir: str | Path = PARAMETER_PACKS_DIR) -> ParameterPack:
    path = Path(packs_dir) / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Unknown parameter pack: {name}")
    payload = json.loads(path.read_text())
    pack = _coerce_pack(payload)
    if not pack.name:
        raise ValueError(f"Parameter pack {name} is missing a stable name")
    return pack


def resolve_parameter_pack(name: str, packs_dir: str | Path = PARAMETER_PACKS_DIR) -> ParameterPack:
    pack = load_parameter_pack(name, packs_dir=packs_dir)
    if not pack.parent:
        return pack

    parent = resolve_parameter_pack(pack.parent, packs_dir=packs_dir)
    overrides = dict(parent.overrides)
    overrides.update(pack.overrides)

    metadata = dict(parent.metadata)
    metadata.update(pack.metadata)

    tags = tuple(dict.fromkeys([*parent.tags, *pack.tags]).keys())
    return ParameterPack(
        name=pack.name,
        version=pack.version,
        description=pack.description or parent.description,
        parent=pack.parent,
        notes=pack.notes or parent.notes,
        tags=tags,
        metadata=metadata,
        overrides=overrides,
    )

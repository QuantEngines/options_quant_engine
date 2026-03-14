"""
Runtime access to active parameter packs and overrides.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
import os
from typing import Any

from tuning.packs import PARAMETER_PACKS_DIR, resolve_parameter_pack
from tuning.registry import get_parameter_registry


DEFAULT_PARAMETER_PACK = "baseline_v1"

_ACTIVE_PACK_NAME = os.getenv("OQE_PARAMETER_PACK", DEFAULT_PARAMETER_PACK)
_ACTIVE_PACK_OVERRIDES: dict[str, Any] | None = None


def _resolve_active_overrides() -> tuple[str, dict[str, Any]]:
    global _ACTIVE_PACK_NAME, _ACTIVE_PACK_OVERRIDES

    if _ACTIVE_PACK_OVERRIDES is not None:
        return _ACTIVE_PACK_NAME, dict(_ACTIVE_PACK_OVERRIDES)

    try:
        pack = resolve_parameter_pack(_ACTIVE_PACK_NAME, packs_dir=PARAMETER_PACKS_DIR)
        _ACTIVE_PACK_OVERRIDES = dict(pack.overrides)
    except Exception:
        _ACTIVE_PACK_NAME = DEFAULT_PARAMETER_PACK
        try:
            pack = resolve_parameter_pack(DEFAULT_PARAMETER_PACK, packs_dir=PARAMETER_PACKS_DIR)
            _ACTIVE_PACK_OVERRIDES = dict(pack.overrides)
        except Exception:
            _ACTIVE_PACK_OVERRIDES = {}

    return _ACTIVE_PACK_NAME, dict(_ACTIVE_PACK_OVERRIDES)


def get_active_parameter_pack() -> dict[str, Any]:
    pack_name, overrides = _resolve_active_overrides()
    return {
        "name": pack_name,
        "overrides": overrides,
    }


def set_active_parameter_pack(name: str = DEFAULT_PARAMETER_PACK, *, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    global _ACTIVE_PACK_NAME, _ACTIVE_PACK_OVERRIDES
    _ACTIVE_PACK_NAME = str(name or DEFAULT_PARAMETER_PACK).strip() or DEFAULT_PARAMETER_PACK
    base_overrides = resolve_parameter_pack(_ACTIVE_PACK_NAME, packs_dir=PARAMETER_PACKS_DIR).overrides
    merged = dict(base_overrides)
    if overrides:
        merged.update(overrides)
    _ACTIVE_PACK_OVERRIDES = merged
    return get_active_parameter_pack()


@contextmanager
def temporary_parameter_pack(name: str = DEFAULT_PARAMETER_PACK, *, overrides: dict[str, Any] | None = None):
    global _ACTIVE_PACK_NAME, _ACTIVE_PACK_OVERRIDES
    prior_name = _ACTIVE_PACK_NAME
    prior_overrides = None if _ACTIVE_PACK_OVERRIDES is None else dict(_ACTIVE_PACK_OVERRIDES)
    set_active_parameter_pack(name, overrides=overrides)
    try:
        yield get_active_parameter_pack()
    finally:
        _ACTIVE_PACK_NAME = prior_name
        _ACTIVE_PACK_OVERRIDES = prior_overrides


def get_parameter_value(key: str, default: Any | None = None) -> Any:
    registry = get_parameter_registry()
    definition = registry.get(key)
    _, overrides = _resolve_active_overrides()
    return overrides.get(key, definition.default_value if default is None else default)


def resolve_mapping(prefix: str, defaults: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(defaults)
    _, overrides = _resolve_active_overrides()
    prefix = f"{prefix}."
    for key, value in overrides.items():
        if key.startswith(prefix):
            resolved[key[len(prefix):]] = value
    return resolved


def resolve_dataclass_config(prefix: str, config_obj: Any):
    if not is_dataclass(config_obj):
        raise TypeError("resolve_dataclass_config expects a dataclass instance")
    payload = resolve_mapping(prefix, asdict(config_obj))
    return type(config_obj)(**payload)


def serialize_current_registry() -> dict[str, Any]:
    _, overrides = _resolve_active_overrides()
    current_values = {}
    for key, definition in get_parameter_registry().items():
        current_values[key] = overrides.get(key, definition.default_value)
    return get_parameter_registry().serialize(current_values=current_values)

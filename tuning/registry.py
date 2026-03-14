"""
Central parameter registry with metadata-rich definitions.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from config.dealer_hedging_pressure_policy import DealerHedgingPressurePolicyConfig
from config.gamma_vol_acceleration_policy import GammaVolAccelerationPolicyConfig
from config.global_risk_policy import GlobalRiskPolicyConfig
from config.option_efficiency_policy import OptionEfficiencyPolicyConfig
from config.signal_evaluation_scoring import (
    SIGNAL_EVALUATION_DIRECTION_WEIGHTS,
    SIGNAL_EVALUATION_SCORE_WEIGHTS,
    SIGNAL_EVALUATION_SELECTION_POLICY,
    SIGNAL_EVALUATION_THRESHOLDS,
    SIGNAL_EVALUATION_TIMING_WEIGHTS,
)
from config.signal_policy import (
    CONFIRMATION_FILTER_CONFIG,
    CONSENSUS_SCORE_CONFIG,
    DIRECTION_MIN_MARGIN,
    DIRECTION_MIN_SCORE,
    DIRECTION_VOTE_WEIGHTS,
    TRADE_RUNTIME_THRESHOLDS,
    TRADE_STRENGTH_WEIGHTS,
)
from macro.macro_news_config import (
    HeadlineClassificationConfig,
    MacroNewsAdjustmentConfig,
    MacroNewsAggregationConfig,
    MacroNewsRegimeConfig,
)
from tuning.models import ParameterDefinition


class ParameterRegistry:
    def __init__(self, definitions: list[ParameterDefinition]):
        self._definitions = {definition.key: definition for definition in definitions}

    def get(self, key: str) -> ParameterDefinition:
        return self._definitions[key]

    def items(self):
        return self._definitions.items()

    def keys(self):
        return self._definitions.keys()

    def defaults(self) -> dict[str, Any]:
        return {
            key: definition.default_value
            for key, definition in self._definitions.items()
        }

    def serialize(self, current_values: dict[str, Any] | None = None) -> dict[str, Any]:
        current_values = current_values or {}
        return {
            key: definition.to_dict(current_values.get(key))
            for key, definition in sorted(self._definitions.items())
        }


def _value_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _parameter_definition(
    *,
    key: str,
    module: str,
    group: str,
    category: str,
    default_value: Any,
    description: str,
    tunable: bool = True,
    live_safe: bool = True,
    min_value: float | int | None = None,
    max_value: float | int | None = None,
    allowed_values: tuple[Any, ...] | None = None,
) -> ParameterDefinition:
    return ParameterDefinition(
        key=key,
        name=key.split(".")[-1],
        module=module,
        group=group,
        category=category,
        default_value=default_value,
        value_type=_value_type_name(default_value),
        description=description,
        tunable=tunable,
        live_safe=live_safe,
        min_value=min_value,
        max_value=max_value,
        allowed_values=allowed_values,
    )


def _from_mapping(
    *,
    prefix: str,
    module: str,
    group: str,
    category: str,
    mapping: dict[str, Any],
    description_prefix: str,
    min_value: float | int | None = None,
    max_value: float | int | None = None,
    live_safe: bool = True,
) -> list[ParameterDefinition]:
    return [
        _parameter_definition(
            key=f"{prefix}.{name}",
            module=module,
            group=group,
            category=category,
            default_value=value,
            description=f"{description_prefix}: {name}",
            min_value=min_value,
            max_value=max_value,
            live_safe=live_safe,
        )
        for name, value in mapping.items()
    ]


def _from_dataclass(
    *,
    prefix: str,
    module: str,
    group: str,
    category: str,
    config_obj: Any,
    description_prefix: str,
    live_safe: bool = True,
) -> list[ParameterDefinition]:
    definitions = []
    for field in fields(config_obj):
        value = getattr(config_obj, field.name)
        definitions.append(
            _parameter_definition(
                key=f"{prefix}.{field.name}",
                module=module,
                group=group,
                category=category,
                default_value=value,
                description=f"{description_prefix}: {field.name}",
                live_safe=live_safe,
            )
        )
    return definitions


def build_default_parameter_registry() -> ParameterRegistry:
    definitions: list[ParameterDefinition] = []

    definitions.extend(
        _from_mapping(
            prefix="trade_strength.direction_vote",
            module="config.signal_policy",
            group="trade_strength",
            category="direction_vote",
            mapping=DIRECTION_VOTE_WEIGHTS,
            description_prefix="Direction vote weight",
            min_value=-5.0,
            max_value=5.0,
        )
    )
    definitions.extend(
        _from_mapping(
            prefix="trade_strength.scoring",
            module="config.signal_policy",
            group="trade_strength",
            category="scoring",
            mapping=TRADE_STRENGTH_WEIGHTS,
            description_prefix="Trade strength scoring weight",
            min_value=-30,
            max_value=30,
        )
    )
    definitions.extend(
        _from_mapping(
            prefix="trade_strength.consensus",
            module="config.signal_policy",
            group="trade_strength",
            category="consensus",
            mapping=CONSENSUS_SCORE_CONFIG,
            description_prefix="Directional consensus score",
            min_value=-20,
            max_value=20,
        )
    )
    definitions.extend(
        _from_mapping(
            prefix="trade_strength.runtime_thresholds",
            module="config.signal_policy",
            group="trade_strength",
            category="runtime_thresholds",
            mapping=TRADE_RUNTIME_THRESHOLDS,
            description_prefix="Trade runtime threshold",
            min_value=0,
            max_value=100,
        )
    )
    definitions.extend(
        _from_mapping(
            prefix="confirmation_filter.core",
            module="config.signal_policy",
            group="confirmation_filter",
            category="core",
            mapping=CONFIRMATION_FILTER_CONFIG,
            description_prefix="Confirmation filter parameter",
            min_value=-10,
            max_value=10,
        )
    )
    definitions.extend(
        [
            _parameter_definition(
                key="trade_strength.direction_thresholds.min_score",
                module="config.signal_policy",
                group="trade_strength",
                category="direction_thresholds",
                default_value=DIRECTION_MIN_SCORE,
                description="Minimum directional vote score required",
                min_value=0.0,
                max_value=10.0,
            ),
            _parameter_definition(
                key="trade_strength.direction_thresholds.min_margin",
                module="config.signal_policy",
                group="trade_strength",
                category="direction_thresholds",
                default_value=DIRECTION_MIN_MARGIN,
                description="Minimum directional vote margin required",
                min_value=0.0,
                max_value=10.0,
            ),
        ]
    )

    definitions.extend(
        _from_dataclass(
            prefix="macro_news.headline_classification",
            module="macro.macro_news_config",
            group="macro_news",
            category="headline_classification",
            config_obj=HeadlineClassificationConfig(),
            description_prefix="Headline classification parameter",
            live_safe=False,
        )
    )
    definitions.extend(
        _from_dataclass(
            prefix="macro_news.aggregation",
            module="macro.macro_news_config",
            group="macro_news",
            category="aggregation",
            config_obj=MacroNewsAggregationConfig(),
            description_prefix="Macro news aggregation parameter",
            live_safe=False,
        )
    )
    definitions.extend(
        _from_dataclass(
            prefix="macro_news.regime",
            module="macro.macro_news_config",
            group="macro_news",
            category="regime",
            config_obj=MacroNewsRegimeConfig(),
            description_prefix="Macro news regime parameter",
            live_safe=False,
        )
    )
    definitions.extend(
        _from_dataclass(
            prefix="macro_news.adjustment",
            module="macro.macro_news_config",
            group="macro_news",
            category="adjustment",
            config_obj=MacroNewsAdjustmentConfig(),
            description_prefix="Macro news engine adjustment parameter",
        )
    )

    definitions.extend(
        _from_dataclass(
            prefix="global_risk.core",
            module="config.global_risk_policy",
            group="global_risk",
            category="core",
            config_obj=GlobalRiskPolicyConfig(),
            description_prefix="Global risk policy parameter",
        )
    )
    definitions.extend(
        _from_dataclass(
            prefix="gamma_vol_acceleration.core",
            module="config.gamma_vol_acceleration_policy",
            group="gamma_vol_acceleration",
            category="core",
            config_obj=GammaVolAccelerationPolicyConfig(),
            description_prefix="Gamma-vol acceleration parameter",
        )
    )
    definitions.extend(
        _from_dataclass(
            prefix="dealer_pressure.core",
            module="config.dealer_hedging_pressure_policy",
            group="dealer_pressure",
            category="core",
            config_obj=DealerHedgingPressurePolicyConfig(),
            description_prefix="Dealer hedging pressure parameter",
        )
    )
    definitions.extend(
        _from_dataclass(
            prefix="option_efficiency.core",
            module="config.option_efficiency_policy",
            group="option_efficiency",
            category="core",
            config_obj=OptionEfficiencyPolicyConfig(),
            description_prefix="Option efficiency parameter",
        )
    )

    definitions.extend(
        _from_mapping(
            prefix="evaluation_thresholds.score_weights",
            module="config.signal_evaluation_scoring",
            group="evaluation_thresholds",
            category="score_weights",
            mapping=SIGNAL_EVALUATION_SCORE_WEIGHTS,
            description_prefix="Signal evaluation composite weight",
            min_value=0.0,
            max_value=1.0,
            live_safe=False,
        )
    )
    definitions.extend(
        _from_mapping(
            prefix="evaluation_thresholds.direction_weights",
            module="config.signal_evaluation_scoring",
            group="evaluation_thresholds",
            category="direction_weights",
            mapping=SIGNAL_EVALUATION_DIRECTION_WEIGHTS,
            description_prefix="Signal evaluation direction weight",
            min_value=0.0,
            max_value=5.0,
            live_safe=False,
        )
    )
    definitions.extend(
        _from_mapping(
            prefix="evaluation_thresholds.timing_weights",
            module="config.signal_evaluation_scoring",
            group="evaluation_thresholds",
            category="timing_weights",
            mapping=SIGNAL_EVALUATION_TIMING_WEIGHTS,
            description_prefix="Signal evaluation timing weight",
            min_value=0.0,
            max_value=5.0,
            live_safe=False,
        )
    )
    definitions.extend(
        _from_mapping(
            prefix="evaluation_thresholds.core",
            module="config.signal_evaluation_scoring",
            group="evaluation_thresholds",
            category="core",
            mapping=SIGNAL_EVALUATION_THRESHOLDS,
            description_prefix="Signal evaluation threshold",
            min_value=0.0,
            max_value=10.0,
            live_safe=False,
        )
    )
    definitions.extend(
        _from_mapping(
            prefix="evaluation_thresholds.selection",
            module="config.signal_evaluation_scoring",
            group="evaluation_thresholds",
            category="selection",
            mapping=SIGNAL_EVALUATION_SELECTION_POLICY,
            description_prefix="Dataset experiment selection threshold",
            min_value=0.0,
            max_value=100.0,
            live_safe=False,
        )
    )

    return ParameterRegistry(definitions)


_REGISTRY: ParameterRegistry | None = None


def get_parameter_registry() -> ParameterRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_default_parameter_registry()
    return _REGISTRY

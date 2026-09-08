from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Mapping

from .application_views import (
    CapabilityRequirementRow, OperationCapabilityDefinitionRow,
    RequirementConditionRow, SiteRequirementsDefinitionRow,
)
from .site import SiteRequirements


def definition_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, type):
        return getattr(value, "facet_key", value.__name__)
    if isinstance(value, Mapping):
        return tuple((str(k), definition_value(v)) for k, v in sorted(value.items(), key=lambda item: str(item[0])))
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((definition_value(v) for v in value), key=str))
    if isinstance(value, (tuple, list)):
        return tuple(definition_value(v) for v in value)
    if is_dataclass(value):
        return tuple((field.name, definition_value(getattr(value, field.name))) for field in fields(value))
    if isinstance(value, str):
        return str(value)
    return value


def condition_definition_row(condition: object) -> RequirementConditionRow:
    parameters: list[tuple[str, object]] = []
    if is_dataclass(condition):
        for field in fields(condition):
            if field.name in {"code", "description"}:
                continue
            parameters.append((field.name, definition_value(getattr(condition, field.name))))
    return RequirementConditionRow(
        type(condition).__name__,
        str(getattr(condition, "code", type(condition).__name__)),
        str(getattr(condition, "description", "")),
        tuple(parameters),
    )


def site_requirements_definition(requirements: SiteRequirements) -> SiteRequirementsDefinitionRow:
    return SiteRequirementsDefinitionRow(
        tuple(condition_definition_row(condition) for condition in requirements.environment),
        tuple(CapabilityRequirementRow(req.capability_id, req.minimum_capacity, req.mode) for req in requirements.capability_requirements),
    )


def operation_capability_definition(capability: object) -> OperationCapabilityDefinitionRow:
    parameters: list[tuple[str, object]] = []
    if is_dataclass(capability):
        for field in fields(capability):
            if field.name == "operation_type":
                continue
            parameters.append((field.name, definition_value(getattr(capability, field.name))))
    return OperationCapabilityDefinitionRow(str(getattr(capability, "operation_type")), tuple(parameters))

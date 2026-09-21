from __future__ import annotations

import re
from collections.abc import Iterable

from .app_contracts.ui_reports import DecisionConstraintRow, DecisionContextTarget

_RATIO_RE = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))/([+-]?(?:\d+(?:\.\d*)?|\.\d+))$")
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_INTERNAL_DETAIL_RE = re.compile(r"^[A-Za-z0-9_.:+/\-]+$")

_QUALIFIER_TOKENS = {
    "active", "enabled", "installed", "available", "allocation", "compatible",
    "positive", "present", "required", "selected",
}

_KIND_ALIASES = {
    "technology": "technology",
    "capability": "capability",
    "vehicle_capability": "vehicle_capability",
    "infrastructure": "infrastructure",
    "service": "service",
    "resource": "resource",
    "storage": "storage",
    "power": "power",
    "knowledge": "knowledge",
    "reach": "movement",
    "movement_path": "movement",
    "routing_constraint": "routing",
    "fleet_unfilled": "fleet",
    "fleet_units": "fleet",
    "source_units": "fleet",
    "source_capability": "capability",
    "input": "resource",
    "resource_allocation": "resource",
    "surface_infrastructure": "infrastructure",
    "provider_dependency": "service",
    "service_capacity": "service",
    "storage_power_limited": "power",
    "arrival_backpressure": "storage",
    "payload_capacity": "payload_capacity",
    "propellant_capacity": "propellant_capacity",
    "unmet_demand": "demand",
    "external_dependency": "external_dependency",
    "service_capacity_shortfall": "service",
    "no_local_service_capacity": "service",
    "no_organization_service_capacity": "service",
    "research_point_pool_headroom": "research_point_capacity",
}

_UNIT_BY_KIND = {
    "resource": "t",
    "payload_capacity": "t",
    "propellant_capacity": "t",
    "fleet": "units",
    "research_point_capacity": "RP",
}


def _number(value: str) -> float | str:
    if not _NUMBER_RE.match(value):
        return value
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _requirement_pair(value: str) -> tuple[float | str, float | str] | None:
    match = _RATIO_RE.match(value)
    if match:
        return _number(match.group(1)), _number(match.group(2))
    if "/" not in value:
        return None
    current, required = value.split("/", 1)
    if not current or not required:
        return None
    return _number(current), _number(required)


def _decode(code: str) -> tuple[str, str | None, str | None, float | str | None, float | str | None, str | None]:
    """Decode stable Domain blocker tokens into display-independent structure.

    This translation intentionally lives at the Application boundary. Domain code
    formats remain internal; Browser code never parses them.
    """

    raw = str(code)
    parts = raw.split(":")
    prefix = parts[0] if parts else raw
    kind = _KIND_ALIASES.get(prefix, prefix or "constraint")
    subject_kind: str | None = None
    subject_id: str | None = None
    current: float | str | None = None
    required: float | str | None = None
    unit = _UNIT_BY_KIND.get(kind)

    if prefix == "resource" and len(parts) >= 4:
        # resource:<node>:<resource>:<current>/<required>
        subject_kind = "resource"
        subject_id = parts[2]
        ratio = _requirement_pair(parts[-1])
        if ratio:
            current, required = ratio
    elif prefix in {"capability", "vehicle_capability"} and len(parts) >= 2:
        subject_kind = prefix
        candidate = parts[-1]
        subject_id = None if candidate in _QUALIFIER_TOKENS else candidate
    elif prefix in {"technology", "storage", "service", "infrastructure", "knowledge", "reach"} and len(parts) >= 2:
        subject_kind = prefix
        ratio = _requirement_pair(parts[-1])
        if ratio:
            candidate = parts[-2] if len(parts) >= 3 else None
            subject_id = None if candidate in _QUALIFIER_TOKENS else candidate
            current, required = ratio
        else:
            candidate = parts[-1]
            subject_id = None if candidate in _QUALIFIER_TOKENS else candidate
    elif prefix in {"payload_capacity", "propellant_capacity"} and len(parts) >= 2:
        subject_kind = prefix
        ratio = _requirement_pair(parts[-1])
        if ratio:
            current, required = ratio
    elif prefix == "fleet_unfilled" and len(parts) >= 2:
        subject_kind = "fleet"
        required = _number(parts[-1])
    elif prefix in {"fleet_units", "source_units"} and len(parts) >= 2:
        subject_kind = "fleet"
        ratio = _requirement_pair(parts[-1])
        if ratio:
            current, required = ratio
    elif prefix in {"input", "resource_allocation"} and len(parts) >= 2:
        subject_kind = "resource"
        subject_id = parts[-1]
    elif prefix == "source_capability" and len(parts) >= 2:
        subject_kind = "capability"
        subject_id = parts[-1]

    return kind, subject_kind, subject_id, current, required, unit


def constraint_from_code(
    code: str,
    *,
    affected_action: str | None = None,
    related_entity_kind: str | None = None,
    related_entity_id: str | None = None,
    severity: str = "blocking",
    message: str | None = None,
    navigation: DecisionContextTarget | None = None,
) -> DecisionConstraintRow:
    kind, subject_kind, subject_id, current, required, unit = _decode(code)
    return DecisionConstraintRow(
        code=str(code),
        kind=kind,
        subject_kind=subject_kind,
        subject_id=subject_id,
        current=current,
        required=required,
        unit=unit,
        severity=severity,
        affected_action=affected_action,
        related_entity_kind=related_entity_kind,
        related_entity_id=related_entity_id,
        message=message,
        navigation=navigation,
    )


def constraint_from_pair(
    blocker: tuple[str, str],
    *,
    affected_action: str | None = None,
    related_entity_kind: str | None = None,
    related_entity_id: str | None = None,
    severity: str = "blocking",
    navigation: DecisionContextTarget | None = None,
) -> DecisionConstraintRow:
    code, detail = blocker
    detail_text = str(detail) if detail else ""
    structured_detail = bool(detail_text and _INTERNAL_DETAIL_RE.fullmatch(detail_text))
    display_message = None if structured_detail else (detail_text or None)
    row = constraint_from_code(
        code,
        affected_action=affected_action,
        related_entity_kind=related_entity_kind,
        related_entity_id=related_entity_id,
        severity=severity,
        message=display_message,
        navigation=navigation,
    )
    # Pair-style blockers conventionally carry machine-readable subject data in
    # detail. Human-readable details remain an Application-authored message.
    if row.subject_id is None and structured_detail:
        detail_parts = detail_text.split(":")
        detail_ratio = _requirement_pair(detail_parts[-1]) if detail_parts else None
        detail_subject = detail_parts[0] if detail_parts else detail_text
        if detail_subject in _QUALIFIER_TOKENS:
            detail_subject = ""
        current = row.current
        required = row.required
        if detail_ratio:
            current, required = detail_ratio
        return DecisionConstraintRow(
            code=row.code,
            kind=row.kind,
            subject_kind=row.subject_kind or row.kind,
            subject_id=detail_subject or None,
            current=current,
            required=required,
            unit=row.unit,
            severity=row.severity,
            affected_action=row.affected_action,
            related_entity_kind=row.related_entity_kind,
            related_entity_id=row.related_entity_id,
            message=row.message,
            navigation=row.navigation,
        )
    return row


def constraints_from_codes(
    blockers: Iterable[str],
    **kwargs,
) -> tuple[DecisionConstraintRow, ...]:
    return tuple(constraint_from_code(value, **kwargs) for value in blockers)


def constraints_from_pairs(
    blockers: Iterable[tuple[str, str]],
    **kwargs,
) -> tuple[DecisionConstraintRow, ...]:
    return tuple(constraint_from_pair(value, **kwargs) for value in blockers)


def limiting_factors_from_codes(
    values: Iterable[str],
    **kwargs,
) -> tuple[DecisionConstraintRow, ...]:
    kwargs.setdefault("severity", "limiting")
    return constraints_from_codes(values, **kwargs)

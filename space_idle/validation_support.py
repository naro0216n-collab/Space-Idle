from __future__ import annotations

from dataclasses import dataclass

from .simulation import Simulation
from .construction.models import CONSTRUCTION_SERVICE_TYPE
from .site import FacetValueRange, RequiresFacet, SiteRequirements, SpatialClassificationRequirement

class ConfigurationError(ValueError):
    pass

def require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigurationError(message)

def validate_environment_condition(condition: object, owner: str) -> None:
    code = getattr(condition, "code", "")
    require(bool(code), f"site requirement has empty code: {owner}")
    if isinstance(condition, RequiresFacet):
        require(hasattr(condition.facet_type, "facet_key"), f"site requirement references invalid facet type: {owner}/{code}")
    elif isinstance(condition, FacetValueRange):
        require(hasattr(condition.facet_type, "facet_key"), f"site requirement references invalid facet type: {owner}/{code}")
        dataclass_fields = getattr(condition.facet_type, "__dataclass_fields__", {})
        require(condition.attribute in dataclass_fields, f"site requirement references unknown facet attribute: {owner}/{code}/{condition.attribute}")

def validate_site_requirements(
    requirements: SiteRequirements,
    known_capabilities: set[str],
    owner: str,
    known_service_types: set[str] | None = None,
) -> None:
    seen_codes: set[str] = set()
    for requirement in requirements.spatial_classification_requirements:
        require(isinstance(requirement, SpatialClassificationRequirement), f"invalid spatial classification requirement: {owner}")
        require(bool(requirement.code), f"site requirement has empty code: {owner}")
        require(requirement.code not in seen_codes, f"duplicate site requirement code: {owner}/{requirement.code}")
        seen_codes.add(requirement.code)
    for condition in requirements.environment:
        validate_environment_condition(condition, owner)
        code = getattr(condition, "code", "")
        require(code not in seen_codes, f"duplicate site requirement code: {owner}/{code}")
        seen_codes.add(code)
    seen_capabilities: set[tuple[str, str]] = set()
    for requirement in requirements.capability_requirements:
        require(requirement.capability_id in known_capabilities, f"site requirement references unknown capability: {owner}/{requirement.capability_id}")
        key = (requirement.capability_id, requirement.required_state.value)
        require(key not in seen_capabilities, f"duplicate capability requirement: {owner}/{requirement.capability_id}/{requirement.required_state.value}")
        seen_capabilities.add(key)
    seen_services: set[str] = set()
    for requirement in requirements.service_capacity_requirements:
        if known_service_types is None:
            require(False, f"service capacity requirement cannot be validated without known service types: {owner}/{requirement.service_type}")
        else:
            require(requirement.service_type in known_service_types, f"site requirement references unknown service type: {owner}/{requirement.service_type}")
        require(requirement.service_type not in seen_services, f"duplicate service capacity requirement: {owner}/{requirement.service_type}")
        seen_services.add(requirement.service_type)

@dataclass(frozen=True)
class ValidationContext:
    nodes: dict
    facility_defs: dict
    known_capabilities: set[str]
    known_service_types: set[str]
    known_technologies: set

    @classmethod
    def from_simulation(cls, sim: Simulation) -> "ValidationContext":
        technologies = set(sim.technology.completed)
        if sim.research is not None:
            technologies.update(sim.research.definitions)
        service_types = set(sim.facilities.service_types())
        service_types.add(CONSTRUCTION_SERVICE_TYPE)
        service_types.add(sim.power.SERVICE_TYPE)
        service_types.update(
            sim.industry.process_service_type(process.id)
            for process in sim.industry.processes.values()
        )
        if sim.extraction is not None:
            service_types.update(
                sim.extraction.service_type(spec.resource_id)
                for spec in sim.extraction.specs.values()
            )
        if sim.survey is not None:
            service_types.add(sim.survey.SERVICE_TYPE)
        return cls(
            sim.graph.operational_node_map(),
            sim.facilities.definitions,
            sim.facilities.capability_ids(),
            service_types,
            technologies,
        )

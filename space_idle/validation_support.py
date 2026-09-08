from __future__ import annotations

from dataclasses import dataclass

from .simulation import Simulation
from .site import FacetValueRange, RequiresFacet, SiteRequirements

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

def validate_site_requirements(requirements: SiteRequirements, known_capabilities: set[str], owner: str) -> None:
    seen_codes: set[str] = set()
    for condition in requirements.environment:
        validate_environment_condition(condition, owner)
        code = getattr(condition, "code", "")
        require(code not in seen_codes, f"duplicate site requirement code: {owner}/{code}")
        seen_codes.add(code)
    seen_capabilities: set[tuple[str, str]] = set()
    for requirement in requirements.capability_requirements:
        require(requirement.capability_id in known_capabilities, f"site requirement references unknown capability: {owner}/{requirement.capability_id}")
        key = (requirement.capability_id, requirement.mode)
        require(key not in seen_capabilities, f"duplicate capability requirement: {owner}/{requirement.capability_id}/{requirement.mode}")
        seen_capabilities.add(key)

@dataclass(frozen=True)
class ValidationContext:
    nodes: dict
    facility_defs: dict
    known_capabilities: set[str]
    known_technologies: set

    @classmethod
    def from_simulation(cls, sim: Simulation) -> "ValidationContext":
        technologies = set(sim.technology.completed)
        if sim.research is not None:
            technologies.update(sim.research.definitions)
        return cls(sim.graph.nodes, sim.facilities.definitions, sim.facilities.capability_ids(), technologies)

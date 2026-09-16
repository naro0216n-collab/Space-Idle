from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .facilities import FacilityBook
    from .power import PowerSnapshot
from .shared import SpatialNodeId
from .spatial import EnvironmentResolver, SpatialContextId, SpatialFacet, SpatialNodeKind




class SpatialClassification(str, Enum):
    SURFACE = "SURFACE"
    ORBITAL = "ORBITAL"
    NON_SURFACE = "NON_SURFACE"


@dataclass(frozen=True)
class SpatialClassificationRequirement:
    classification: SpatialClassification
    code: str
    description: str

    def matches(self, environment: EnvironmentResolver, context_id: SpatialContextId) -> bool:
        graph = environment.graph
        if context_id in graph.locations or context_id in graph.surface_cells:
            actual = SpatialClassification.SURFACE
        elif context_id in graph.nodes:
            actual = (
                SpatialClassification.ORBITAL
                if graph.nodes[context_id].kind is SpatialNodeKind.ORBITAL
                else SpatialClassification.NON_SURFACE
            )
        else:
            raise KeyError(context_id)
        return actual is self.classification


class EnvironmentCondition(Protocol):
    code: str
    description: str

    def matches(self, environment: EnvironmentResolver, context_id: SpatialContextId, day: int) -> bool: ...


@dataclass(frozen=True)
class RequiresFacet:
    facet_type: type[SpatialFacet]
    code: str
    description: str

    def matches(self, environment: EnvironmentResolver, context_id: SpatialContextId, day: int) -> bool:
        return environment.get(context_id, self.facet_type, day) is not None


@dataclass(frozen=True)
class FacetValueRange:
    facet_type: type[SpatialFacet]
    attribute: str
    code: str
    description: str
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("facet minimum cannot exceed maximum")

    def matches(self, environment: EnvironmentResolver, context_id: SpatialContextId, day: int) -> bool:
        facet = environment.get(context_id, self.facet_type, day)
        if facet is None:
            return False
        value = getattr(facet, self.attribute)
        if self.minimum is not None and value < self.minimum - 1e-12:
            return False
        if self.maximum is not None and value > self.maximum + 1e-12:
            return False
        return True


class CapabilityRequirementState(str, Enum):
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"


@dataclass(frozen=True)
class CapabilityRequirement:
    capability_id: str
    required_state: CapabilityRequirementState = CapabilityRequirementState.INSTALLED

    def __post_init__(self) -> None:
        if not self.capability_id:
            raise ValueError("capability id must not be empty")
        if not isinstance(self.required_state, CapabilityRequirementState):
            raise ValueError("capability required state must be INSTALLED or ACTIVE")


@dataclass(frozen=True)
class ServiceCapacityRequirement:
    service_type: str
    minimum_rate: float

    def __post_init__(self) -> None:
        if not self.service_type:
            raise ValueError("service capacity requirement type must not be empty")
        if self.minimum_rate < 0:
            raise ValueError("service capacity requirement minimum must be non-negative")


@dataclass(frozen=True)
class SiteRequirements:
    environment: tuple[EnvironmentCondition, ...] = ()
    capability_requirements: tuple[CapabilityRequirement, ...] = ()
    service_capacity_requirements: tuple[ServiceCapacityRequirement, ...] = ()
    spatial_classification_requirements: tuple[SpatialClassificationRequirement, ...] = ()


@dataclass(frozen=True)
class SiteRequirementFailure:
    code: str
    detail: str


def evaluate_physical_site_requirements(
    requirements: SiteRequirements,
    context_id: SpatialContextId,
    day: int,
    environment: EnvironmentResolver,
) -> tuple[SiteRequirementFailure, ...]:
    failures = [
        SiteRequirementFailure(requirement.code, requirement.description)
        for requirement in requirements.spatial_classification_requirements
        if not requirement.matches(environment, context_id)
    ]
    failures.extend(
        SiteRequirementFailure(condition.code, condition.description)
        for condition in requirements.environment
        if not condition.matches(environment, context_id, day)
    )
    return tuple(failures)


def evaluate_site_requirements(
    requirements: SiteRequirements,
    location_id: SpatialNodeId,
    day: int,
    environment: EnvironmentResolver,
    facilities: "FacilityBook",
    power: "PowerSnapshot | None" = None,
    *,
    environment_context_id: SpatialContextId | None = None,
    service_capacity_available: Mapping[str, float] | None = None,
) -> tuple[SiteRequirementFailure, ...]:
    context_id = location_id if environment_context_id is None else environment_context_id
    failures = list(evaluate_physical_site_requirements(requirements, context_id, day, environment))

    for requirement in requirements.capability_requirements:
        if requirement.required_state is CapabilityRequirementState.INSTALLED:
            satisfied = facilities.installed_capability_at(location_id, requirement.capability_id)
        else:
            satisfied = facilities.active_capability_at(location_id, requirement.capability_id, day)
        if not satisfied:
            failures.append(SiteRequirementFailure(
                f"capability:{requirement.required_state.value.lower()}",
                requirement.capability_id,
            ))
    for requirement in requirements.service_capacity_requirements:
        if service_capacity_available is not None:
            available = service_capacity_available.get(requirement.service_type, 0.0)
        elif power is not None:
            available = facilities.enabled_service_capacity_at(
                location_id, requirement.service_type, power, day
            )
        else:
            available = facilities.nominal_service_capacity_at(
                location_id, requirement.service_type, day
            )
        if available + 1e-9 < requirement.minimum_rate:
            failures.append(SiteRequirementFailure(
                "service_capacity:available",
                f"{requirement.service_type}:{available:g}/{requirement.minimum_rate:g}",
            ))
    return tuple(failures)

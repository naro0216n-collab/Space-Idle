from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .facilities import FacilityBook
from .shared import SpatialNodeId
from .shared import DefinitionId
from .spatial import AtmosphereField, EnvironmentFieldScope, EnvironmentResolver, SpatialContextId, SpatialFacet, SpatialNodeKind




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


@dataclass(frozen=True)
class AtmosphericPartialPressureRange:
    """An environmental gas requirement, not a planet or Location exception.

    Atmosphere composition contains mole fractions of environmental species,
    while pressure is the total ambient pressure. Missing species have zero
    partial pressure.
    """

    species_id: DefinitionId
    code: str
    description: str
    minimum_pa: float | None = None
    maximum_pa: float | None = None

    def __post_init__(self) -> None:
        if self.minimum_pa is not None and self.minimum_pa < 0:
            raise ValueError('minimum partial pressure cannot be negative')
        if self.maximum_pa is not None and self.maximum_pa < 0:
            raise ValueError('maximum partial pressure cannot be negative')
        if self.minimum_pa is not None and self.maximum_pa is not None and self.minimum_pa > self.maximum_pa:
            raise ValueError('invalid partial-pressure bounds')

    def matches(self, environment: EnvironmentResolver, context_id: SpatialContextId, day: int) -> bool:
        atmosphere = environment.get(context_id, AtmosphereField, day)
        if atmosphere is None:
            return False
        partial_pressure = atmosphere.pressure_pa * atmosphere.composition.get(self.species_id, 0.0)
        if self.minimum_pa is not None and partial_pressure < self.minimum_pa:
            return False
        if self.maximum_pa is not None and partial_pressure > self.maximum_pa:
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
class SiteRequirements:
    environment: tuple[EnvironmentCondition, ...] = ()
    capability_requirements: tuple[CapabilityRequirement, ...] = ()
    spatial_classification_requirements: tuple[SpatialClassificationRequirement, ...] = ()


def requires_surface_cell_context(requirements: SiteRequirements) -> bool:
    """Whether a surface execution site must name a concrete developed Cell.

    Body-global fields do not choose a Cell. Cell-local fields and fields with
    Cell overlays do, because evaluating them at the Location would discard the
    local component that gives the placement its meaning.
    """

    for condition in requirements.environment:
        facet_type = getattr(condition, "facet_type", None)
        scope = getattr(facet_type, "environment_scope", None)
        if scope in {
            EnvironmentFieldScope.SURFACE_CELL_LOCAL,
            EnvironmentFieldScope.BODY_WITH_CELL_OVERLAY,
        }:
            return True
    return False


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
    *,
    environment_context_id: SpatialContextId | None = None,
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
    return tuple(failures)

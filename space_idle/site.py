from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .facilities import FacilityBook
    from .power import PowerSnapshot
from .shared import SpatialNodeId
from .spatial import EnvironmentResolver, SpatialContextId, SpatialFacet


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


CapabilityMode = Literal["infrastructure", "available"]


@dataclass(frozen=True)
class CapabilityRequirement:
    capability_id: str
    minimum_capacity: float = 1.0
    mode: CapabilityMode = "infrastructure"

    def __post_init__(self) -> None:
        if not self.capability_id:
            raise ValueError("capability id must not be empty")
        if self.minimum_capacity <= 0:
            raise ValueError("minimum capability capacity must be positive")
        if self.mode not in {"infrastructure", "available"}:
            raise ValueError(f"unknown capability requirement mode: {self.mode}")


@dataclass(frozen=True)
class SiteRequirements:
    environment: tuple[EnvironmentCondition, ...] = ()
    capability_requirements: tuple[CapabilityRequirement, ...] = ()


@dataclass(frozen=True)
class SiteRequirementFailure:
    code: str
    detail: str


def evaluate_site_requirements(
    requirements: SiteRequirements,
    location_id: SpatialNodeId,
    day: int,
    environment: EnvironmentResolver,
    facilities: "FacilityBook",
    power: "PowerSnapshot | None" = None,
    *,
    environment_context_id: SpatialContextId | None = None,
) -> tuple[SiteRequirementFailure, ...]:
    failures: list[SiteRequirementFailure] = []
    context_id = location_id if environment_context_id is None else environment_context_id
    for condition in requirements.environment:
        if not condition.matches(environment, context_id, day):
            failures.append(SiteRequirementFailure(condition.code, condition.description))

    for requirement in requirements.capability_requirements:
        if requirement.mode == "infrastructure":
            actual = facilities.infrastructure_capability_capacity_at(location_id, requirement.capability_id, day)
        else:
            actual = 0.0 if power is None else facilities.available_capability_capacity_at(
                location_id, requirement.capability_id, power, day
            )
        if actual + 1e-9 < requirement.minimum_capacity:
            failures.append(SiteRequirementFailure(
                f"capability:{requirement.mode}",
                f"{requirement.capability_id}:{actual:g}/{requirement.minimum_capacity:g}",
            ))
    return tuple(failures)

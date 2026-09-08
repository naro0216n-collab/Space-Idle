from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .shared import DefinitionId, SpatialNodeId
from .site import SiteRequirements

@dataclass(frozen=True)
class ResearchDefinition:
    id: DefinitionId
    display_name: str
    theory_points: float
    prerequisites: frozenset[DefinitionId] = frozenset()
    theory_site_requirements: SiteRequirements = SiteRequirements()
    prototype_resources: dict[DefinitionId, float] = field(default_factory=dict)
    prototype_site_requirements: SiteRequirements = SiteRequirements()
    demonstration_days: int = 0
    demonstration_site_requirements: SiteRequirements = SiteRequirements()

    def __post_init__(self) -> None:
        if self.theory_points < 0:
            raise ValueError("research theory points must be non-negative")
        if self.demonstration_days < 0:
            raise ValueError("research demonstration days must be non-negative")
        if any(amount < 0 for amount in self.prototype_resources.values()):
            raise ValueError("prototype resource amounts must be non-negative")

@dataclass(frozen=True)
class ResearchProviderSpec:
    facility_def_id: DefinitionId
    points_per_day: float

    def __post_init__(self) -> None:
        if self.points_per_day < 0:
            raise ValueError("research provider rate must be non-negative")

class ResearchPhase(str, Enum):
    THEORY = "theory"
    PROTOTYPE = "prototype"
    DEMONSTRATION = "demonstration"
    COMPLETE = "complete"

@dataclass
class ResearchState:
    definition_id: DefinitionId
    status: ResearchPhase = ResearchPhase.THEORY
    theory_done: float = 0.0
    demonstration_done_days: int = 0
    allocation_weight: float = 1.0
    paused: bool = False
    prototype_location_id: SpatialNodeId | None = None
    demonstration_location_id: SpatialNodeId | None = None

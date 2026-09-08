from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

SourcingPolicyValue = Literal["import_now", "mixed", "local_priority"]


@dataclass(frozen=True)
class PlanBuild:
    location_id: str
    facility_id: str
    priority: int = 50
    sourcing_policy: SourcingPolicyValue = "mixed"
    import_source_id: str | None = None


@dataclass(frozen=True)
class PlanFacilityUpgrade:
    facility_id: str
    priority: int = 50
    sourcing_policy: SourcingPolicyValue = "mixed"
    import_source_id: str | None = None


@dataclass(frozen=True)
class CancelBuild:
    project_id: str


@dataclass(frozen=True)
class PauseBuild:
    project_id: str


@dataclass(frozen=True)
class ResumeBuild:
    project_id: str


@dataclass(frozen=True)
class SetProjectPriority:
    project_id: str
    priority: int


@dataclass(frozen=True)
class SetProjectSourcingPolicy:
    project_id: str
    sourcing_policy: SourcingPolicyValue


@dataclass(frozen=True)
class SetConstructionWeight:
    project_id: str
    weight: float


@dataclass(frozen=True)
class SetProjectImportSource:
    project_id: str
    location_id: str | None


@dataclass(frozen=True)
class SetProjectImportTransport:
    project_id: str
    path: tuple[str, ...] | None = None
    route_modes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SetProjectLocalFraction:
    project_id: str
    component_id: str
    fraction: float


@dataclass(frozen=True)
class SetProjectLocalMaterial:
    project_id: str
    component_id: str
    resource_id: str | None

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
    site_cell_id: str | None = None


@dataclass(frozen=True)
class PlanFacilityUpgrade:
    facility_id: str
    priority: int = 50
    sourcing_policy: SourcingPolicyValue = "mixed"
    import_source_id: str | None = None


@dataclass(frozen=True)
class FoundLocation:
    provider_location_id: str
    new_location_id: str
    display_name: str
    body_id: str
    core_cell_id: str
    priority: int = 50
    sourcing_policy: SourcingPolicyValue = "mixed"
    import_source_id: str | None = None


@dataclass(frozen=True)
class DevelopSurfaceCell:
    location_id: str
    cell_id: str
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

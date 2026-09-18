from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from ..priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY

ProcurementTimingPolicyValue = Literal["immediate", "standard_wait", "extended_wait"]


@dataclass(frozen=True)
class PlanBuild:
    operational_node_id: str
    facility_id: str
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    procurement_policy: ProcurementTimingPolicyValue = "standard_wait"
    logistics_policy_id: str | None = None
    site_cell_id: str | None = None


@dataclass(frozen=True)
class PlanFacilityUpgrade:
    facility_id: str
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    procurement_policy: ProcurementTimingPolicyValue = "standard_wait"
    logistics_policy_id: str | None = None


@dataclass(frozen=True)
class PlanFacilityDecommission:
    facility_id: str
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    procurement_policy: ProcurementTimingPolicyValue = "standard_wait"
    logistics_policy_id: str | None = None


@dataclass(frozen=True)
class SurfaceLocationFoundingTarget:
    target_type: Literal["surface_location"]
    body_id: str
    core_cell_id: str


@dataclass(frozen=True)
class NonSurfaceOperationalNodeFoundingTarget:
    target_type: Literal["non_surface_operational_node"]
    spatial_node_id: str


FoundingTargetInput = SurfaceLocationFoundingTarget | NonSurfaceOperationalNodeFoundingTarget


@dataclass(frozen=True)
class PlanOperationalNodeFounding:
    staging_node_id: str
    display_name: str
    target_spec: FoundingTargetInput
    deployment_recipe_id: str
    vehicle_definition_id: str
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    logistics_policy_id: str | None = None


@dataclass(frozen=True)
class CancelFounding:
    project_id: str


@dataclass(frozen=True)
class PauseFounding:
    project_id: str


@dataclass(frozen=True)
class ResumeFounding:
    project_id: str


@dataclass(frozen=True)
class SetFoundingPriority:
    project_id: str
    priority: ActivityPriority


@dataclass(frozen=True)
class DevelopSurfaceCell:
    location_id: str
    cell_id: str
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    procurement_policy: ProcurementTimingPolicyValue = "standard_wait"
    logistics_policy_id: str | None = None


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
    priority: ActivityPriority


@dataclass(frozen=True)
class SetProjectProcurementPolicy:
    project_id: str
    procurement_policy: ProcurementTimingPolicyValue

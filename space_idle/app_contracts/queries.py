from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class GetCatalog: pass
@dataclass(frozen=True)
class GetWorld: pass
@dataclass(frozen=True)
class GetSurfaceMap: body_id: str
@dataclass(frozen=True)
class GetOperationalNode: operational_node_id: str
@dataclass(frozen=True)
class GetFlowReport: operational_node_id: str
@dataclass(frozen=True)
class GetDependencyAnalytics:
    scope_kind: str = "player"
    scope_id: str | None = None
    node_ids: tuple[str, ...] = ()
    time_basis: str = "CURRENT"
@dataclass(frozen=True)
class GetBottlenecks: operational_node_id: str | None = None
@dataclass(frozen=True)
class GetProjects: operational_node_id: str | None = None
@dataclass(frozen=True)
class GetBuildOptions: operational_node_id: str
@dataclass(frozen=True)
class GetLogistics: pass
@dataclass(frozen=True)
class GetLogisticsSummary: pass
@dataclass(frozen=True)
class GetMovementPlans:
    origin_id: str | None = None
    destination_id: str | None = None
    movement_plan_id: str | None = None
    include_modes: bool = True
@dataclass(frozen=True)
class GetFleet:
    operational_node_id: str | None = None
    vehicle_definition_id: str | None = None
@dataclass(frozen=True)
class GetFleetRelocationPreview:
    vehicle_definition_id: str
    units: int
    source_id: str
    destination_id: str
    movement_hard_constraint: tuple[str, ...] | None = None
@dataclass(frozen=True)
class GetTransportAllocations: pass
@dataclass(frozen=True)
class GetCargoFlows: pass
@dataclass(frozen=True)
class GetTransportAllocationOptions:
    source_id: str
    destination_id: str
@dataclass(frozen=True)
class GetResearch: pass
@dataclass(frozen=True)
class GetScientificExplorations: pass
@dataclass(frozen=True)
class GetSurveys: provider_operational_node_id: str | None = None
@dataclass(frozen=True)
class GetContracts: pass
@dataclass(frozen=True)
class GetMarket: pass

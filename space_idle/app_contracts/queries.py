from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class GetCatalog: pass
@dataclass(frozen=True)
class GetWorld: pass
@dataclass(frozen=True)
class GetLocation: location_id: str
@dataclass(frozen=True)
class GetFlowReport: location_id: str
@dataclass(frozen=True)
class GetBottlenecks: location_id: str | None = None
@dataclass(frozen=True)
class GetProjects: location_id: str | None = None
@dataclass(frozen=True)
class GetBuildOptions: location_id: str
@dataclass(frozen=True)
class GetLogistics: pass
@dataclass(frozen=True)
class GetLogisticsSummary: pass
@dataclass(frozen=True)
class GetRoutes:
    origin_id: str | None = None
    destination_id: str | None = None
    route_id: str | None = None
    include_modes: bool = True
@dataclass(frozen=True)
class GetFleet:
    location_id: str | None = None
    vehicle_definition_id: str | None = None
@dataclass(frozen=True)
class GetTransportAllocations: pass
@dataclass(frozen=True)
class GetCargoFlows: pass
@dataclass(frozen=True)
class GetLogisticsLanes: pass
@dataclass(frozen=True)
class GetTransportAllocationOptions:
    source_id: str
    destination_id: str
@dataclass(frozen=True)
class GetResearch: pass
@dataclass(frozen=True)
class GetScientificExplorations: pass
@dataclass(frozen=True)
class GetSurveys: location_id: str | None = None
@dataclass(frozen=True)
class GetContracts: pass

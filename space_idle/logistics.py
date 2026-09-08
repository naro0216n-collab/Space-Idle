from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService
from .shared import AccountState, CargoOrderId, DefinitionId, EntityId, RouteId, SpatialNodeId
from .technology import TechnologyState
from .transport.compatibility import TransportCompatibilityMixin
from .transport.execution import TransportExecutionMixin
from .transport.fleet import FleetManagementMixin
from .transport.models import (
    ATMOSPHERIC_ENTRY,
    LANDING,
    POWERED_ASCENT,
    SPACEFLIGHT,
    AtmosphericEntryCapability,
    CargoOrder,
    ExternalTransportServiceDef,
    LandingCapability,
    LogisticsLane,
    MissionStatus,
    OperationSupportLocation,
    OperationSupportRequirement,
    PathPolicy,
    PoweredAscentCapability,
    RouteDef,
    SpaceflightCapability,
    TransportMissionState,
    TransportMode,
    TransportOperationKind,
    TransportOperationRequirement,
    TransportPerformanceProfile,
    VehicleDef,
    VehicleDisposition,
    VehicleEconomicsSpec,
    VehicleMaintenanceSpec,
    VehicleProductionSpec,
    VehicleState,
    VehicleStatus,
    VehicleTransit,
)
from .transport.operations import OperationEvaluatorRegistry, build_default_operation_registry
from .transport.orders import TransportOrderMixin
from .transport.planning import TransportPlanningMixin


@dataclass
class LogisticsService(
    TransportCompatibilityMixin,
    FleetManagementMixin,
    TransportPlanningMixin,
    TransportOrderMixin,
    TransportExecutionMixin,
):
    routes: dict[RouteId, RouteDef]
    inventory: InventoryBook
    account: AccountState
    facilities: FacilityBook
    power: PowerService
    vehicle_defs: dict[DefinitionId, VehicleDef] = field(default_factory=dict)
    external_services: dict[DefinitionId, ExternalTransportServiceDef] = field(default_factory=dict)
    operation_registry: OperationEvaluatorRegistry = field(default_factory=build_default_operation_registry)
    vehicles: dict[EntityId, VehicleState] = field(default_factory=dict)
    technology_state: TechnologyState = field(default_factory=TechnologyState)
    orders: dict[CargoOrderId, CargoOrder] = field(default_factory=dict)
    waiting: dict[tuple[CargoOrderId, int], float] = field(default_factory=dict)
    missions: dict[EntityId, TransportMissionState] = field(default_factory=dict)
    vehicle_transit: list[VehicleTransit] = field(default_factory=list)
    lanes: dict[EntityId, LogisticsLane] = field(default_factory=dict)
    _counter: int = 0
    _lane_counter: int = 0
    _vehicle_counter: int = 0
    _mission_counter: int = 0

    @property
    def unlocked_technologies(self) -> set[DefinitionId]:
        return self.technology_state.completed

    def _waiting_owner(self, order_id: CargoOrderId, leg_index: int) -> EntityId:
        return EntityId(f"logistics.waiting:{order_id}:{leg_index}")


__all__ = [
    "ATMOSPHERIC_ENTRY", "LANDING", "POWERED_ASCENT", "SPACEFLIGHT",
    "AtmosphericEntryCapability", "CargoOrder", "ExternalTransportServiceDef",
    "LandingCapability", "LogisticsLane", "LogisticsService", "MissionStatus",
    "OperationSupportLocation", "OperationSupportRequirement", "PathPolicy",
    "PoweredAscentCapability", "RouteDef", "SpaceflightCapability",
    "TransportMissionState", "TransportMode", "TransportOperationKind",
    "TransportOperationRequirement", "TransportPerformanceProfile", "VehicleDef",
    "VehicleDisposition", "VehicleEconomicsSpec", "VehicleMaintenanceSpec",
    "VehicleProductionSpec", "VehicleState", "VehicleStatus", "VehicleTransit",
]

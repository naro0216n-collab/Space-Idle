from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService
from .shared import AccountState, DefinitionId, EntityId, SpatialNodeId
from .technology import TechnologyState
from .transport.compatibility import TransportCompatibilityMixin
from .transport.fleet_allocations import FleetAllocationMixin
from .transport.lanes import LaneRuntimeMetrics, LogisticsLaneSnapshot, TransportLaneMixin
from .transport.models import (
    ATMOSPHERIC_ENTRY,
    LANDING,
    POWERED_ASCENT,
    SPACEFLIGHT,
    AtmosphericEntryCapability,
    CargoFlowBatch,
    DirectionalCapacity,
    ExternalTransportServiceDef,
    FleetPool,
    FleetPoolSnapshot,
    FleetRelocation,
    FleetRelease,
    FleetReservation,
    FleetReservationKind,
    LandingCapability,
    LogisticsLane,
    OperationAssetDisposition,
    OperationSupportLocation,
    OperationSupportRequirement,
    ResourceSupportRequirement,
    PathPolicy,
    PoweredAscentCapability,
    RouteDef,
    SpaceflightCapability,
    TransportAllocation,
    TransportCapacitySnapshot,
    TransportControlMode,
    TransportOperationKind,
    TransportOperationRequirement,
    TransportPerformanceProfile,
    TransportServicePlan,
    VehicleDef,
    VehicleEconomicsSpec,
    VehicleMaintenanceSpec,
    VehicleProductionSpec,
)
from .transport.operations import OperationEvaluatorRegistry, build_default_operation_registry
from .transport.production import VehicleProductionMixin, VehicleProductionState
from .transport.steady_logistics import SteadyLogisticsMixin


@dataclass
class LogisticsService(
    TransportCompatibilityMixin,
    FleetAllocationMixin,
    TransportLaneMixin,
    SteadyLogisticsMixin,
    VehicleProductionMixin,
):
    routes: dict
    inventory: InventoryBook
    account: AccountState
    facilities: FacilityBook
    power: PowerService
    vehicle_defs: dict[DefinitionId, VehicleDef] = field(default_factory=dict)
    external_services: dict[DefinitionId, ExternalTransportServiceDef] = field(default_factory=dict)
    operation_registry: OperationEvaluatorRegistry = field(default_factory=build_default_operation_registry)
    fleet_pools: dict[tuple[DefinitionId, SpatialNodeId], FleetPool] = field(default_factory=dict)
    fleet_reservations: dict[EntityId, FleetReservation] = field(default_factory=dict)
    transport_allocations: dict[EntityId, TransportAllocation] = field(default_factory=dict)
    fleet_relocations: dict[EntityId, FleetRelocation] = field(default_factory=dict)
    fleet_releases: dict[EntityId, FleetRelease] = field(default_factory=dict)
    cargo_flows: dict[EntityId, CargoFlowBatch] = field(default_factory=dict)
    technology_state: TechnologyState = field(default_factory=TechnologyState)
    lanes: dict[EntityId, LogisticsLane] = field(default_factory=dict)
    vehicle_production_projects: dict[EntityId, VehicleProductionState] = field(default_factory=dict)
    _lane_counter: int = 0
    _transport_allocation_counter: int = 0
    _cargo_flow_counter: int = 0
    _fleet_relocation_counter: int = 0
    _fleet_release_counter: int = 0
    _vehicle_production_counter: int = 0

    @property
    def unlocked_technologies(self) -> set[DefinitionId]:
        return self.technology_state.completed


__all__ = [
    "ATMOSPHERIC_ENTRY", "LANDING", "POWERED_ASCENT", "SPACEFLIGHT",
    "AtmosphericEntryCapability", "CargoFlowBatch", "DirectionalCapacity",
    "ExternalTransportServiceDef", "FleetPool", "FleetPoolSnapshot", "FleetRelocation",
    "FleetRelease", "FleetReservation", "FleetReservationKind", "LandingCapability",
    "LaneRuntimeMetrics", "LogisticsLane", "LogisticsLaneSnapshot", "LogisticsService",
    "OperationAssetDisposition", "OperationSupportLocation", "OperationSupportRequirement",
    "ResourceSupportRequirement",
    "PathPolicy", "PoweredAscentCapability", "RouteDef", "SpaceflightCapability",
    "TransportAllocation", "TransportCapacitySnapshot", "TransportControlMode",
    "TransportOperationKind", "TransportOperationRequirement", "TransportPerformanceProfile",
    "TransportServicePlan", "VehicleDef", "VehicleEconomicsSpec", "VehicleMaintenanceSpec",
    "VehicleProductionSpec",
]

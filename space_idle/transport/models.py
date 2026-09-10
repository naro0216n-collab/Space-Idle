from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from ..shared import CargoOrderId, DefinitionId, EntityId, RouteId, SpatialNodeId
from ..site import SiteRequirements

POWERED_ASCENT = "powered_ascent"
SPACEFLIGHT = "spaceflight"
LANDING = "landing"
ATMOSPHERIC_ENTRY = "atmospheric_entry"


class TransportOperationKind:
    POWERED_ASCENT = POWERED_ASCENT
    SPACEFLIGHT = SPACEFLIGHT
    LANDING = LANDING
    ATMOSPHERIC_ENTRY = ATMOSPHERIC_ENTRY


class VehicleDisposition(str, Enum):
    DESTINATION = "destination"
    RETURN_TO_ORIGIN = "return_to_origin"


class PathPolicy(str, Enum):
    FASTEST = "fastest"
    LOWEST_COST = "lowest_cost"
    LOWEST_PROPELLANT = "lowest_propellant"


class VehicleStatus(str, Enum):
    AVAILABLE = "available"
    TURNAROUND = "turnaround"
    MAINTENANCE_WAIT = "maintenance_wait"
    TRANSIT = "transit"
    TRANSIT_RETURN = "transit_return"
    UNLOADING = "unloading"
    WAYPOINT_WAIT = "waypoint_wait"
    ASSIGNED = "assigned"


class MissionStatus(str, Enum):
    IN_TRANSIT = "in_transit"
    ARRIVAL_WAITING = "arrival_waiting"
    WAYPOINT_WAIT = "waypoint_wait"


class OperationSupportLocation(str, Enum):
    ORIGIN = "origin"
    DESTINATION = "destination"


@runtime_checkable
class OperationCapability(Protocol):
    operation_type: str


@dataclass(frozen=True)
class OperationSupportRequirement:
    operation_type: str
    location: OperationSupportLocation
    capability_id: str

    @property
    def kind(self) -> str:
        return self.operation_type


@dataclass(frozen=True)
class TransportOperationRequirement:
    operation_type: str
    delta_v_km_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.operation_type:
            raise ValueError("operation type must be non-empty")
        if self.delta_v_km_s < 0:
            raise ValueError("operation delta-v must be non-negative")

    @property
    def kind(self) -> str:
        return self.operation_type


@dataclass(frozen=True)
class RouteDef:
    id: RouteId
    origin_id: SpatialNodeId
    destination_id: SpatialNodeId
    transit_days: int
    operations: tuple[TransportOperationRequirement, ...]
    display_name: str | None = None
    origin_requirements: SiteRequirements = SiteRequirements()
    destination_requirements: SiteRequirements = SiteRequirements()

    @property
    def delta_v_km_s(self) -> float:
        return sum(operation.delta_v_km_s for operation in self.operations)


@dataclass(frozen=True)
class PoweredAscentCapability:
    max_delta_v_km_s: float
    max_surface_gravity_m_s2: float
    max_surface_pressure_pa: float
    operation_type: str = field(init=False, default=POWERED_ASCENT)


@dataclass(frozen=True)
class SpaceflightCapability:
    max_delta_v_km_s: float
    max_mission_days: int
    operation_type: str = field(init=False, default=SPACEFLIGHT)


@dataclass(frozen=True)
class LandingCapability:
    max_delta_v_km_s: float
    max_surface_gravity_m_s2: float
    max_surface_pressure_pa: float
    operation_type: str = field(init=False, default=LANDING)


@dataclass(frozen=True)
class AtmosphericEntryCapability:
    max_surface_pressure_pa: float
    operation_type: str = field(init=False, default=ATMOSPHERIC_ENTRY)


@dataclass(frozen=True)
class TransportPerformanceProfile:
    dry_mass_t: float
    payload_t: float
    transit_time_multiplier: float = 1.0
    propellant_resource_id: DefinitionId | None = None
    propellant_capacity_t: float = 0.0
    propellant_t_per_total_t_per_km_s: float = 0.0
    operation_capabilities: tuple[OperationCapability, ...] = ()
    operation_support_requirements: tuple[OperationSupportRequirement, ...] = ()
    default_disposition: VehicleDisposition = VehicleDisposition.DESTINATION

    def capability_for(self, operation_type: str) -> OperationCapability | None:
        for capability in self.operation_capabilities:
            if capability.operation_type == operation_type:
                return capability
        return None

    def propellant_t(self, route: RouteDef, cargo_t: float) -> float:
        return self.propellant_t_per_total_t_per_km_s * (self.dry_mass_t + cargo_t) * route.delta_v_km_s

    def max_cargo_for_route(self, route: RouteDef) -> float:
        if self.propellant_t_per_total_t_per_km_s <= 1e-12 or route.delta_v_km_s <= 1e-12:
            return self.payload_t
        mass_budget = self.propellant_capacity_t / (
            self.propellant_t_per_total_t_per_km_s * route.delta_v_km_s
        )
        return max(0.0, min(self.payload_t, mass_budget - self.dry_mass_t))


@dataclass(frozen=True)
class VehicleEconomicsSpec:
    operating_cost_musd_per_mission: float = 0.0
    operating_cost_musd_per_cargo_t: float = 0.0


@dataclass(frozen=True)
class VehicleProductionSpec:
    capability_id: str | None = None
    days: float = 0.0
    cost_musd: float = 0.0
    resources: tuple[tuple[DefinitionId, float], ...] = ()
    site_requirements: SiteRequirements = SiteRequirements()


@dataclass(frozen=True)
class VehicleMaintenanceSpec:
    capability_id: str | None = None
    turnaround_days: float = 0.0
    cost_musd: float = 0.0
    resources: tuple[tuple[DefinitionId, float], ...] = ()


@dataclass(frozen=True)
class VehicleDef:
    id: DefinitionId
    display_name: str
    performance: TransportPerformanceProfile
    economics: VehicleEconomicsSpec = VehicleEconomicsSpec()
    production: VehicleProductionSpec = VehicleProductionSpec()
    maintenance: VehicleMaintenanceSpec = VehicleMaintenanceSpec()

    @property
    def dry_mass_t(self) -> float: return self.performance.dry_mass_t
    @property
    def payload_t(self) -> float: return self.performance.payload_t
    @property
    def transit_time_multiplier(self) -> float: return self.performance.transit_time_multiplier
    @property
    def propellant_resource_id(self) -> DefinitionId | None: return self.performance.propellant_resource_id
    @property
    def propellant_capacity_t(self) -> float: return self.performance.propellant_capacity_t
    @property
    def propellant_t_per_total_t_per_km_s(self) -> float: return self.performance.propellant_t_per_total_t_per_km_s
    @property
    def operation_support_requirements(self) -> tuple[OperationSupportRequirement, ...]: return self.performance.operation_support_requirements
    @property
    def default_disposition(self) -> VehicleDisposition: return self.performance.default_disposition
    @property
    def operating_cost_musd_per_mission(self) -> float: return self.economics.operating_cost_musd_per_mission
    @property
    def operating_cost_musd_per_cargo_t(self) -> float: return self.economics.operating_cost_musd_per_cargo_t
    @property
    def production_capability_id(self) -> str | None: return self.production.capability_id
    @property
    def production_days(self) -> float: return self.production.days
    @property
    def production_cost_musd(self) -> float: return self.production.cost_musd
    @property
    def production_resources(self) -> tuple[tuple[DefinitionId, float], ...]: return self.production.resources
    @property
    def turnaround_capability_id(self) -> str | None: return self.maintenance.capability_id
    @property
    def turnaround_days(self) -> float: return self.maintenance.turnaround_days
    @property
    def turnaround_cost_musd(self) -> float: return self.maintenance.cost_musd
    @property
    def turnaround_resources(self) -> tuple[tuple[DefinitionId, float], ...]: return self.maintenance.resources

    def capability_for(self, operation_type: str) -> OperationCapability | None:
        return self.performance.capability_for(operation_type)

    def propellant_t(self, route: RouteDef, cargo_t: float) -> float:
        return self.performance.propellant_t(route, cargo_t)

    def max_cargo_for_route(self, route: RouteDef) -> float:
        return self.performance.max_cargo_for_route(route)

    @property
    def powered_ascent(self): return self.capability_for(POWERED_ASCENT)
    @property
    def spaceflight(self): return self.capability_for(SPACEFLIGHT)
    @property
    def landing(self): return self.capability_for(LANDING)
    @property
    def atmospheric_entry(self): return self.capability_for(ATMOSPHERIC_ENTRY)


@dataclass(frozen=True)
class ExternalTransportServiceDef:
    id: DefinitionId
    display_name: str
    capacity_t_per_day: float
    cost_musd_per_t: float
    performance: TransportPerformanceProfile
    transit_time_multiplier: float = 1.0
    origin_requirements: SiteRequirements = SiteRequirements()
    destination_requirements: SiteRequirements = SiteRequirements()


@dataclass
class VehicleState:
    id: EntityId
    definition_id: DefinitionId
    location_id: SpatialNodeId | None
    status: VehicleStatus = VehicleStatus.AVAILABLE
    available_day: int = 0
    transit_destination_id: SpatialNodeId | None = None
    propellant_t: float = 0.0
    assignment_id: EntityId | None = None
    assignment_kind: str | None = None


@dataclass
class TransportMissionState:
    id: EntityId
    order_id: CargoOrderId
    leg_index: int
    amount_t: float
    mode_id: str
    departure_day: int
    arrival_day: int
    vehicle_id: EntityId | None = None
    vehicle_disposition: VehicleDisposition = VehicleDisposition.DESTINATION
    status: MissionStatus = MissionStatus.IN_TRANSIT
    onboard: bool = True
    handoff_vehicle_id: EntityId | None = None


@dataclass
class CargoOrder:
    id: CargoOrderId
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    resource_id: DefinitionId
    amount_t: float
    priority: int
    owner_kind: str
    owner_id: EntityId
    path: tuple[RouteId, ...]
    mode_by_route: dict[RouteId, str] = field(default_factory=dict)
    path_policy: PathPolicy = PathPolicy.FASTEST
    delivered_t: float = 0.0
    created_day: int = 0
    lane_id: EntityId | None = None
    demand_id: EntityId | None = None


@dataclass
class LogisticsLane:
    id: EntityId
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    requested_capacity_t_per_day: float
    priority: int
    path: tuple[RouteId, ...] | None = None
    mode_by_route: dict[RouteId, str] = field(default_factory=dict)
    path_policy: PathPolicy = PathPolicy.FASTEST
    paused: bool = False

    def __post_init__(self) -> None:
        if self.source_id == self.destination_id:
            raise ValueError("logistics lane endpoints must differ")
        if self.requested_capacity_t_per_day <= 0:
            raise ValueError("logistics lane requested capacity must be positive")


@dataclass(frozen=True)
class TransportMode:
    mode_id: str
    vehicle_definition_id: DefinitionId | None
    dispatch_capacity_t: float
    cost_musd_per_t: float
    available_vehicle_ids: tuple[EntityId, ...] = ()


@dataclass(frozen=True)
class VehicleTransit:
    vehicle_id: EntityId
    route_id: RouteId
    arrival_day: int
    used_for_mission: bool = True

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from ..shared import DefinitionId, EntityId, RouteId, SpatialNodeId
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


class OperationAssetDisposition(str, Enum):
    """Where the operated vehicle ends after completing one Transport Operation."""

    DESTINATION = "destination"
    ORIGIN = "origin"


class PathPolicy(str, Enum):
    FASTEST = "fastest"
    LOWEST_COST = "lowest_cost"
    LOWEST_PROPELLANT = "lowest_propellant"


class TransportControlMode(str, Enum):
    UNITS = "units"
    CAPACITY = "capacity"


class FleetReservationKind(str, Enum):
    SCIENTIFIC_EXPLORATION = "scientific_exploration"
    SPECIAL_MISSION = "special_mission"
    OTHER = "other"


@dataclass(frozen=True)
class DirectionalCapacity:
    forward_t_per_day: float = 0.0
    reverse_t_per_day: float = 0.0

    def __post_init__(self) -> None:
        if self.forward_t_per_day < 0 or self.reverse_t_per_day < 0:
            raise ValueError("directional transport capacity must be non-negative")


@dataclass
class FleetPool:
    vehicle_definition_id: DefinitionId
    location_id: SpatialNodeId
    total_units: int = 0

    def __post_init__(self) -> None:
        if self.total_units < 0:
            raise ValueError("fleet total units must be non-negative")


@dataclass(frozen=True)
class FleetPoolSnapshot:
    vehicle_definition_id: DefinitionId
    location_id: SpatialNodeId
    total_units: int
    free_units: int
    transport_units: int
    exploration_units: int
    other_reserved_units: int
    relocating_units: int
    releasing_units: int


@dataclass
class FleetReservation:
    id: EntityId
    owner_id: EntityId
    kind: FleetReservationKind
    vehicle_definition_id: DefinitionId
    location_id: SpatialNodeId
    units: int

    def __post_init__(self) -> None:
        if self.units <= 0:
            raise ValueError("fleet reservation units must be positive")


@dataclass
class FleetRelocation:
    id: EntityId
    vehicle_definition_id: DefinitionId
    units: int
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    departure_day: int
    arrival_day: int

    def __post_init__(self) -> None:
        if self.units <= 0:
            raise ValueError("fleet relocation units must be positive")
        if self.source_id == self.destination_id:
            raise ValueError("fleet relocation endpoints must differ")
        if self.arrival_day <= self.departure_day:
            raise ValueError("fleet relocation arrival must follow departure")


@dataclass
class FleetRelease:
    id: EntityId
    allocation_id: EntityId
    vehicle_definition_id: DefinitionId
    location_id: SpatialNodeId
    units: int
    release_day: int

    def __post_init__(self) -> None:
        if self.units <= 0:
            raise ValueError("fleet releasing units must be positive")


@dataclass
class TransportAllocation:
    id: EntityId
    vehicle_definition_id: DefinitionId
    anchor_location_id: SpatialNodeId
    destination_id: SpatialNodeId
    priority: int
    control_mode: TransportControlMode
    target_units: int | None = None
    target_capacity: DirectionalCapacity | None = None
    path: tuple[RouteId, ...] | None = None
    path_policy: PathPolicy = PathPolicy.FASTEST
    paused: bool = False
    active_units: int = 0
    last_operated_day: int | None = None

    def __post_init__(self) -> None:
        if self.anchor_location_id == self.destination_id:
            raise ValueError("transport allocation endpoints must differ")
        if self.active_units < 0:
            raise ValueError("transport allocation active units must be non-negative")
        if self.control_mode is TransportControlMode.UNITS:
            if self.target_units is None or self.target_units < 0 or self.target_capacity is not None:
                raise ValueError("UNITS allocation requires only target_units")
        elif self.control_mode is TransportControlMode.CAPACITY:
            if self.target_capacity is None or self.target_units is not None:
                raise ValueError("CAPACITY allocation requires only target_capacity")
        else:
            raise ValueError(f"unsupported transport control mode: {self.control_mode}")


@dataclass(frozen=True)
class TransportServiceLeg:
    route_id: RouteId
    direction: str
    cargo_capable: bool
    payload_t: float
    transit_days: float
    propellant_t_at_full_payload: float


@dataclass(frozen=True)
class TransportServicePlan:
    allocation_id: EntityId
    vehicle_definition_id: DefinitionId
    anchor_location_id: SpatialNodeId
    destination_id: SpatialNodeId
    forward_path: tuple[RouteId, ...]
    reverse_path: tuple[RouteId, ...]
    legs: tuple[TransportServiceLeg, ...]
    cycle_days: float
    turnaround_days: float
    forward_payload_t: float
    reverse_payload_t: float
    forward_latency_days: int
    reverse_latency_days: int | None
    nominal_per_unit: DirectionalCapacity
    resource_t_per_full_utilization_day: tuple[tuple[SpatialNodeId, DefinitionId, float], ...] = ()
    servicing_units_per_full_utilization_day: float = 0.0
    blockers: tuple[str, ...] = ()
    resource_t_per_empty_cycle_day: tuple[tuple[SpatialNodeId, DefinitionId, float], ...] = ()
    resource_t_per_forward_payload_increment_day: tuple[tuple[SpatialNodeId, DefinitionId, float], ...] = ()
    resource_t_per_reverse_payload_increment_day: tuple[tuple[SpatialNodeId, DefinitionId, float], ...] = ()

    @property
    def feasible(self) -> bool:
        return not self.blockers and self.cycle_days > 0 and self.forward_payload_t > 0


@dataclass(frozen=True)
class TransportCapacitySnapshot:
    allocation_id: EntityId
    target: DirectionalCapacity | None
    required_units: int
    active_units: int
    unfilled_units: int
    nominal: DirectionalCapacity
    available: DirectionalCapacity
    used: DirectionalCapacity
    spare: DirectionalCapacity
    utilization: float
    operational_resource_demand: tuple[tuple[SpatialNodeId, DefinitionId, float], ...]
    blockers: tuple[str, ...] = ()
    limiting_factors: tuple[str, ...] = ()


class CargoFlowStatus(str, Enum):
    IN_TRANSIT = "in_transit"
    HANDOFF_WAITING = "handoff_waiting"
    ARRIVAL_WAITING = "arrival_waiting"


@dataclass
class CargoFlowBatch:
    id: EntityId
    resource_id: DefinitionId
    amount_t: float
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    lane_id: EntityId | None
    demand_id: EntityId | None
    owner_kind: str
    owner_id: EntityId
    priority: int
    service_ids: tuple[str, ...]
    service_destinations: tuple[SpatialNodeId, ...]
    departure_day: int
    ready_day: int
    leg_index: int = 0
    status: CargoFlowStatus = CargoFlowStatus.IN_TRANSIT

    def __post_init__(self) -> None:
        if self.amount_t <= 0:
            raise ValueError("cargo flow amount must be positive")
        if not self.service_ids or len(self.service_ids) != len(self.service_destinations):
            raise ValueError("cargo flow requires aligned service path")
        if self.leg_index < 0 or self.leg_index >= len(self.service_ids):
            raise ValueError("cargo flow leg index out of range")


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
class ResourceSupportRequirement:
    """Infrastructure/interface needed to replenish an operational resource.

    The Core does not attach semantics to a particular resource or capability
    id.  Content defines which infrastructure can replenish the resource and,
    when needed, which interface the vehicle itself must expose.
    """

    resource_id: DefinitionId
    infrastructure_capability_id: str
    vehicle_capability_id: str | None = None


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
    asset_disposition: OperationAssetDisposition = OperationAssetDisposition.DESTINATION
    operation_type: str = field(init=False, default=POWERED_ASCENT)


@dataclass(frozen=True)
class SpaceflightCapability:
    max_delta_v_km_s: float
    asset_disposition: OperationAssetDisposition = OperationAssetDisposition.DESTINATION
    operation_type: str = field(init=False, default=SPACEFLIGHT)


@dataclass(frozen=True)
class LandingCapability:
    max_delta_v_km_s: float
    max_surface_gravity_m_s2: float
    max_surface_pressure_pa: float
    asset_disposition: OperationAssetDisposition = OperationAssetDisposition.DESTINATION
    operation_type: str = field(init=False, default=LANDING)


@dataclass(frozen=True)
class AtmosphericEntryCapability:
    max_surface_pressure_pa: float
    asset_disposition: OperationAssetDisposition = OperationAssetDisposition.DESTINATION
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
    resource_support_requirements: tuple[ResourceSupportRequirement, ...] = ()
    endurance_days: float | None = None
    generic_capabilities: tuple[str, ...] = ()

    def capability_for(self, operation_type: str) -> OperationCapability | None:
        for capability in self.operation_capabilities:
            if capability.operation_type == operation_type:
                return capability
        return None

    def operation_asset_disposition(self, operation_type: str) -> OperationAssetDisposition | None:
        capability = self.capability_for(operation_type)
        if capability is None:
            return None
        return getattr(capability, "asset_disposition", OperationAssetDisposition.DESTINATION)

    def support_requirements_for_resource(
        self, resource_id: DefinitionId
    ) -> tuple[ResourceSupportRequirement, ...]:
        return tuple(
            requirement
            for requirement in self.resource_support_requirements
            if requirement.resource_id == resource_id
        )

    def route_asset_disposition(self, route: RouteDef) -> OperationAssetDisposition:
        disposition = OperationAssetDisposition.DESTINATION
        for operation in route.operations:
            current = self.operation_asset_disposition(operation.operation_type)
            if current is None:
                continue
            disposition = current
            if current is OperationAssetDisposition.ORIGIN:
                break
        return disposition

    def endurance_failures(self, operating_days: float) -> tuple[str, ...]:
        if self.endurance_days is None or operating_days <= self.endurance_days + 1e-9:
            return ()
        return (f"endurance:{operating_days:g}/{self.endurance_days:g}",)

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
    operating_cost_musd_per_cycle: float = 0.0
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
    def resource_support_requirements(self) -> tuple[ResourceSupportRequirement, ...]: return self.performance.resource_support_requirements
    @property
    def endurance_days(self) -> float | None: return self.performance.endurance_days
    @property
    def generic_capabilities(self) -> tuple[str, ...]: return self.performance.generic_capabilities
    @property
    def operating_cost_musd_per_cycle(self) -> float: return self.economics.operating_cost_musd_per_cycle
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

    def route_asset_disposition(self, route: RouteDef) -> OperationAssetDisposition:
        return self.performance.route_asset_disposition(route)

    def endurance_failures(self, operating_days: float) -> tuple[str, ...]:
        return self.performance.endurance_failures(operating_days)

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
class LogisticsLane:
    id: EntityId
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    requested_capacity_t_per_day: float
    priority: int
    path: tuple[RouteId, ...] | None = None
    path_policy: PathPolicy = PathPolicy.FASTEST
    paused: bool = False

    def __post_init__(self) -> None:
        if self.source_id == self.destination_id:
            raise ValueError("logistics lane endpoints must differ")
        if self.requested_capacity_t_per_day <= 0:
            raise ValueError("logistics lane requested capacity must be positive")

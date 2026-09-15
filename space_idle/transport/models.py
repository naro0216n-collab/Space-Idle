from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from ..priority import (
    ActivityPriority, DEFAULT_ACTIVITY_PRIORITY, DEFAULT_PROVISIONING_PRIORITY, ProvisioningPriority,
)
from ..shared import DefinitionId, EntityId, RouteId, SpatialNodeId, SurfaceCellId
from ..site import SiteRequirements

POWERED_ASCENT = "powered_ascent"
SPACEFLIGHT = "spaceflight"
LANDING = "landing"
ATMOSPHERIC_ENTRY = "atmospheric_entry"
SURFACE_TRANSPORT = "surface_transport"


class TransportOperationKind:
    POWERED_ASCENT = POWERED_ASCENT
    SPACEFLIGHT = SPACEFLIGHT
    LANDING = LANDING
    ATMOSPHERIC_ENTRY = ATMOSPHERIC_ENTRY
    SURFACE_TRANSPORT = SURFACE_TRANSPORT


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
    TRANSPORT = "transport"
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
    operational_node_id: SpatialNodeId
    total_units: int = 0

    def __post_init__(self) -> None:
        if self.total_units < 0:
            raise ValueError("fleet total units must be non-negative")


@dataclass(frozen=True)
class FleetPoolSnapshot:
    vehicle_definition_id: DefinitionId
    operational_node_id: SpatialNodeId
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
    operational_node_id: SpatialNodeId
    units: int

    def __post_init__(self) -> None:
        if self.units <= 0:
            raise ValueError("fleet reservation units must be positive")


@dataclass(frozen=True)
class FleetReservationSnapshot:
    id: EntityId
    owner_id: EntityId
    kind: FleetReservationKind
    vehicle_definition_id: DefinitionId
    operational_node_id: SpatialNodeId
    units: int


@dataclass(frozen=True)
class FleetRelocationResourceNeed:
    operational_node_id: SpatialNodeId
    resource_id: DefinitionId
    required_t: float

    def __post_init__(self) -> None:
        if self.required_t < -1e-9:
            raise ValueError("fleet relocation resource need must be non-negative")


@dataclass
class FleetRelocation:
    id: EntityId
    vehicle_definition_id: DefinitionId
    units: int
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    requested_day: int
    travel_days: int
    path: tuple[RouteId, ...]
    resource_needs: tuple[FleetRelocationResourceNeed, ...] = ()
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    departure_day: int | None = None
    arrival_day: int | None = None

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)
        if self.units <= 0:
            raise ValueError("fleet relocation units must be positive")
        if self.source_id == self.destination_id:
            raise ValueError("fleet relocation endpoints must differ")
        if self.travel_days <= 0:
            raise ValueError("fleet relocation travel days must be positive")
        if (self.departure_day is None) != (self.arrival_day is None):
            raise ValueError("fleet relocation timing must be both pending or both active")
        if self.departure_day is not None and self.arrival_day <= self.departure_day:
            raise ValueError("fleet relocation arrival must follow departure")

    @property
    def started(self) -> bool:
        return self.departure_day is not None


@dataclass(frozen=True)
class FleetRelocationResourceRequirement:
    operational_node_id: SpatialNodeId
    resource_id: DefinitionId
    required_t: float
    available_t: float


@dataclass(frozen=True)
class FleetRelocationPlan:
    vehicle_definition_id: DefinitionId
    units: int
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    path: tuple[RouteId, ...]
    travel_days: int
    departure_day: int
    arrival_day: int | None
    resource_requirements: tuple[FleetRelocationResourceRequirement, ...] = ()
    infrastructure_requirements: tuple[tuple[SpatialNodeId, str, str], ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def feasible(self) -> bool:
        return self.arrival_day is not None and not self.blockers


@dataclass
class FleetRelease:
    id: EntityId
    allocation_id: EntityId
    vehicle_definition_id: DefinitionId
    operational_node_id: SpatialNodeId
    units: int
    release_day: int

    def __post_init__(self) -> None:
        if self.units <= 0:
            raise ValueError("fleet releasing units must be positive")


@dataclass
class TransportAllocation:
    id: EntityId
    vehicle_definition_id: DefinitionId
    anchor_node_id: SpatialNodeId
    destination_id: SpatialNodeId
    provisioning_priority: ProvisioningPriority
    control_mode: TransportControlMode
    target_units: int | None = None
    target_capacity: DirectionalCapacity | None = None
    path: tuple[RouteId, ...] | None = None
    path_policy: PathPolicy = PathPolicy.FASTEST
    paused: bool = False
    last_operated_day: int | None = None

    def __post_init__(self) -> None:
        self.provisioning_priority = ProvisioningPriority(self.provisioning_priority)
        if self.anchor_node_id == self.destination_id:
            raise ValueError("transport allocation endpoints must differ")
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
    anchor_node_id: SpatialNodeId
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
    infrastructure_requirements: tuple[tuple[SpatialNodeId, str, str], ...] = ()
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


@dataclass(frozen=True)
class TransportServiceSupply:
    """Transport-owned projection of one directional service offered to Logistics."""

    key: str
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    capacity_t_per_day: float
    latency_days: int
    route_path: tuple[RouteId, ...]
    allocation_id: EntityId | None = None
    direction: str | None = None
    external_service_id: DefinitionId | None = None
    cost_musd_per_t: float = 0.0
    propellant_t_per_t: float = 0.0

    def __post_init__(self) -> None:
        if self.capacity_t_per_day < 0:
            raise ValueError("transport service supply capacity must be non-negative")
        if self.latency_days <= 0:
            raise ValueError("transport service supply latency must be positive")
        if self.source_id == self.destination_id:
            raise ValueError("transport service supply endpoints must differ")
        if (self.allocation_id is None) != (self.direction is None):
            raise ValueError("owned transport supply requires allocation and direction together")
        if self.direction not in (None, "forward", "reverse"):
            raise ValueError("transport service supply direction must be forward or reverse")
        if self.cost_musd_per_t < 0 or self.propellant_t_per_t < 0:
            raise ValueError("transport service supply costs must be non-negative")


@dataclass(frozen=True)
class TransportOperationDependencyProjection:
    """Transport-owned dependencies Logistics must submit to shared allocators."""

    allocation_id: EntityId
    priority: ActivityPriority
    anchor_node_id: SpatialNodeId
    turnaround_service_type: str | None
    turnaround_request_id: EntityId | None
    surface_service_locations: tuple[SpatialNodeId, ...] = ()


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
class RouteEndpoint:
    """Physical locator for one end of a Location-to-Location route.

    The Location remains the economic/logistics node.  The locator only selects
    the physical interface used to derive environment and geometry.
    """

    node_id: SpatialNodeId
    surface_interface_id: EntityId | None = None
    access_cell_id: SurfaceCellId | None = None
    non_surface_interface: str | None = None

    def __post_init__(self) -> None:
        locators = (
            self.surface_interface_id is not None,
            self.access_cell_id is not None,
            self.non_surface_interface is not None,
        )
        if sum(locators) != 1:
            raise ValueError("route endpoint requires exactly one physical locator")
        if self.non_surface_interface is not None and not self.non_surface_interface:
            raise ValueError("non-surface route interface must not be empty")

    @property
    def locator_kind(self) -> str:
        if self.surface_interface_id is not None:
            return "surface_interface"
        if self.access_cell_id is not None:
            return "access_cell"
        return "non_surface_interface"

    @property
    def locator_id(self) -> str:
        if self.surface_interface_id is not None:
            return str(self.surface_interface_id)
        if self.access_cell_id is not None:
            return str(self.access_cell_id)
        assert self.non_surface_interface is not None
        return self.non_surface_interface


@dataclass(frozen=True)
class RouteDef:
    id: RouteId
    origin: RouteEndpoint
    destination: RouteEndpoint
    transit_days: int
    operations: tuple[TransportOperationRequirement, ...]
    display_name: str | None = None
    origin_requirements: SiteRequirements = SiteRequirements()
    destination_requirements: SiteRequirements = SiteRequirements()

    @property
    def origin_id(self) -> SpatialNodeId:
        return self.origin.node_id

    @property
    def destination_id(self) -> SpatialNodeId:
        return self.destination.node_id

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
class SurfaceTransportCapability:
    speed_km_per_day: float
    max_distance_km: float | None = None
    asset_disposition: OperationAssetDisposition = OperationAssetDisposition.DESTINATION
    operation_type: str = field(init=False, default=SURFACE_TRANSPORT)

    def __post_init__(self) -> None:
        if self.speed_km_per_day <= 0:
            raise ValueError("surface transport speed must be positive")
        if self.max_distance_km is not None and self.max_distance_km <= 0:
            raise ValueError("surface transport maximum distance must be positive")


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
    service_type: str | None = None
    days: float = 0.0
    cost_musd: float = 0.0
    resources: tuple[tuple[DefinitionId, float], ...] = ()
    site_requirements: SiteRequirements = SiteRequirements()


@dataclass(frozen=True)
class VehicleMaintenanceSpec:
    service_type: str | None = None
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
    def production_service_type(self) -> str | None: return self.production.service_type
    @property
    def production_days(self) -> float: return self.production.days
    @property
    def production_cost_musd(self) -> float: return self.production.cost_musd
    @property
    def production_resources(self) -> tuple[tuple[DefinitionId, float], ...]: return self.production.resources
    @property
    def turnaround_service_type(self) -> str | None: return self.maintenance.service_type
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

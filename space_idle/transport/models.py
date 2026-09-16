from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from ..priority import (
    ActivityPriority, DEFAULT_ACTIVITY_PRIORITY, DEFAULT_PROVISIONING_PRIORITY, ProvisioningPriority,
)
from ..shared import DefinitionId, EntityId, MovementPlanId, SpatialNodeId, SurfaceCellId
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
    LOWEST_PROPELLANT = "lowest_propellant"


class TransportControlMode(str, Enum):
    UNITS = "units"
    CAPACITY = "capacity"


class FleetReservationKind(str, Enum):
    TRANSPORT = "transport"
    SCIENTIFIC_EXPLORATION = "scientific_exploration"
    SPECIAL_MISSION = "special_mission"
    RETIREMENT = "retirement"
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
    retirement_units: int
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
    path: tuple[MovementPlanId, ...]
    resource_needs: tuple[FleetRelocationResourceNeed, ...] = ()
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    movement_execution_id: EntityId | None = None

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)
        if self.units <= 0:
            raise ValueError("fleet relocation units must be positive")
        if self.source_id == self.destination_id:
            raise ValueError("fleet relocation endpoints must differ")
        if not self.path:
            raise ValueError("fleet relocation requires a movement path")

    @property
    def started(self) -> bool:
        return self.movement_execution_id is not None


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
    path: tuple[MovementPlanId, ...]
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
    path: tuple[MovementPlanId, ...] | None = None
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
    movement_plan_id: MovementPlanId
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
    forward_path: tuple[MovementPlanId, ...]
    reverse_path: tuple[MovementPlanId, ...]
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
    operational_supply: tuple[tuple[SpatialNodeId, DefinitionId, float], ...]
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
    cycle_days: float
    movement_plan_path: tuple[MovementPlanId, ...]
    allocation_id: EntityId
    direction: str
    propellant_t_per_t: float = 0.0

    def __post_init__(self) -> None:
        if self.capacity_t_per_day < 0:
            raise ValueError("transport service supply capacity must be non-negative")
        if self.latency_days <= 0:
            raise ValueError("transport service supply latency must be positive")
        if self.cycle_days <= 0:
            raise ValueError("transport service supply cycle must be positive")
        if self.source_id == self.destination_id:
            raise ValueError("transport service supply endpoints must differ")
        if self.direction not in ("forward", "reverse"):
            raise ValueError("transport service supply direction must be forward or reverse")
        if self.propellant_t_per_t < 0:
            raise ValueError("transport service supply propellant must be non-negative")


@dataclass(frozen=True)
class TransportOperationDependencyProjection:
    """Transport-owned dependencies Logistics must submit to shared allocators."""

    allocation_id: EntityId
    priority: ActivityPriority
    anchor_node_id: SpatialNodeId
    turnaround_service_type: str | None
    turnaround_request_id: EntityId | None
    surface_service_locations: tuple[SpatialNodeId, ...] = ()


@dataclass(frozen=True)
class TransportOperationUsageRequirements:
    """Per-tonne operation inputs derived from one Fleet service-cycle state.

    Direction-specific payload increments are linear. Shared empty-cycle and
    turnaround loads are attributed between directions from a reference usage
    mix so their aggregate remains equal to the service plan's max-utilization
    semantics.
    """

    allocation_id: EntityId
    forward_resource_per_t: tuple[tuple[SpatialNodeId, DefinitionId, float], ...]
    reverse_resource_per_t: tuple[tuple[SpatialNodeId, DefinitionId, float], ...]
    turnaround_service_type: str | None
    turnaround_node_id: SpatialNodeId
    forward_turnaround_per_t: float = 0.0
    reverse_turnaround_per_t: float = 0.0


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
class MovementEndpoint:
    """Physical endpoint used by the Movement Resolver.

    Normal logistics endpoints belong to an established Operational Node.
    ``physical_target_cell_id`` is reserved for one-shot movement to a surface
    target that is not yet an Operational Node (for example Founding).
    """

    operational_node_id: SpatialNodeId | None = None
    surface_interface_id: EntityId | None = None
    access_cell_id: SurfaceCellId | None = None
    non_surface_interface: str | None = None
    physical_target_cell_id: SurfaceCellId | None = None

    def __post_init__(self) -> None:
        locators = (
            self.surface_interface_id is not None,
            self.access_cell_id is not None,
            self.non_surface_interface is not None,
            self.physical_target_cell_id is not None,
        )
        if sum(locators) != 1:
            raise ValueError("movement endpoint requires exactly one physical locator")
        if self.physical_target_cell_id is not None:
            if self.operational_node_id is not None:
                raise ValueError("physical target must not claim an Operational Node")
        elif self.operational_node_id is None:
            raise ValueError("normal movement endpoint requires an Operational Node")
        if self.non_surface_interface is not None and not self.non_surface_interface:
            raise ValueError("non-surface movement interface must not be empty")

    @property
    def node_id(self) -> SpatialNodeId:
        if self.operational_node_id is None:
            raise ValueError("physical target has no Operational Node")
        return self.operational_node_id

    @property
    def locator_kind(self) -> str:
        if self.surface_interface_id is not None:
            return "surface_interface"
        if self.access_cell_id is not None:
            return "access_cell"
        if self.physical_target_cell_id is not None:
            return "physical_target"
        return "non_surface_interface"

    @property
    def locator_id(self) -> str:
        if self.surface_interface_id is not None:
            return str(self.surface_interface_id)
        if self.access_cell_id is not None:
            return str(self.access_cell_id)
        if self.physical_target_cell_id is not None:
            return str(self.physical_target_cell_id)
        assert self.non_surface_interface is not None
        return self.non_surface_interface


@dataclass(frozen=True)
class SpatialRelation:
    origin_context_id: SpatialNodeId | SurfaceCellId
    destination_context_id: SpatialNodeId | SurfaceCellId
    movement_context: str
    characteristic_distance_km: float | None = None
    characteristic_delta_v_km_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.movement_context:
            raise ValueError("movement context must not be empty")
        if self.characteristic_distance_km is not None and self.characteristic_distance_km < 0:
            raise ValueError("movement relation distance must be non-negative")
        if self.characteristic_delta_v_km_s < 0:
            raise ValueError("movement relation delta-v must be non-negative")


@dataclass(frozen=True)
class MovementPlan:
    """Derived, non-persisted physical plan for one direct Movement leg."""

    id: MovementPlanId
    origin: MovementEndpoint
    destination: MovementEndpoint
    relation: SpatialRelation
    transit_days: int
    operations: tuple[TransportOperationRequirement, ...]
    display_name: str | None = None
    origin_requirements: SiteRequirements = SiteRequirements()
    destination_requirements: SiteRequirements = SiteRequirements()

    def __post_init__(self) -> None:
        if self.origin.operational_node_id is not None and self.destination.operational_node_id is not None:
            if self.origin.operational_node_id == self.destination.operational_node_id:
                raise ValueError("movement plan endpoints must differ")
        if self.transit_days <= 0:
            raise ValueError("movement plan transit days must be positive")
        if not self.operations:
            raise ValueError("movement plan requires at least one operation")

    @property
    def origin_id(self) -> SpatialNodeId | None:
        return self.origin.operational_node_id

    @property
    def destination_id(self) -> SpatialNodeId | None:
        return self.destination.operational_node_id

    @property
    def delta_v_km_s(self) -> float:
        return sum(operation.delta_v_km_s for operation in self.operations)


class MovementExecutionKind(str, Enum):
    FLEET_RELOCATION = "fleet_relocation"
    FOUNDING_DEPLOYMENT = "founding_deployment"
    SCIENTIFIC_EXPLORATION = "scientific_exploration"


@dataclass(frozen=True)
class MovementExecutionResourceRequirement:
    """Frozen physical resource requirement for one started Movement leg."""

    operational_node_id: SpatialNodeId
    resource_id: DefinitionId
    required_t: float

    def __post_init__(self) -> None:
        if self.required_t < -1e-9:
            raise ValueError("movement execution resource requirement must be non-negative")


@dataclass(frozen=True)
class MovementExecutionPayloadResource:
    """Physical Resource cargo owned by a started finite Movement."""

    resource_id: DefinitionId
    amount_t: float

    def __post_init__(self) -> None:
        if self.amount_t <= 0:
            raise ValueError("movement execution payload resource must be positive")


@dataclass(frozen=True)
class MovementExecutionLeg:
    """Frozen movement conditions captured when a one-shot execution starts."""

    movement_plan_id: MovementPlanId
    origin: MovementEndpoint
    destination: MovementEndpoint
    operations: tuple[TransportOperationRequirement, ...]
    latency_days: int
    payload_capacity_t: float
    propellant_t_per_unit: float
    asset_disposition: OperationAssetDisposition
    resource_requirements: tuple[MovementExecutionResourceRequirement, ...] = ()

    def __post_init__(self) -> None:
        if self.latency_days <= 0:
            raise ValueError("movement execution leg latency must be positive")
        if self.payload_capacity_t < -1e-9:
            raise ValueError("movement execution payload capacity must be non-negative")
        if self.propellant_t_per_unit < -1e-9:
            raise ValueError("movement execution propellant must be non-negative")
        if not self.operations:
            raise ValueError("movement execution leg requires operations")


@dataclass
class MovementExecution:
    """Authoritative snapshot of a started finite Movement.

    MovementPlan candidates remain derived. Once dispatch starts, this state owns
    the conditions that must not change retroactively when Spatial, Infrastructure,
    Technology, or current Vehicle definitions change.
    """

    id: EntityId
    owner_id: EntityId
    kind: MovementExecutionKind
    vehicle_definition_id: DefinitionId
    units: int
    legs: tuple[MovementExecutionLeg, ...]
    payload_t_per_unit: float
    started_day: int
    completion_day: int
    payload_resources: tuple[MovementExecutionPayloadResource, ...] = ()

    def __post_init__(self) -> None:
        if self.units <= 0:
            raise ValueError("movement execution units must be positive")
        if not self.legs:
            raise ValueError("movement execution requires at least one leg")
        if self.payload_t_per_unit < -1e-9:
            raise ValueError("movement execution payload must be non-negative")
        if self.completion_day <= self.started_day:
            raise ValueError("movement execution completion must follow start")
        if self.payload_t_per_unit > min(leg.payload_capacity_t for leg in self.legs) + 1e-9:
            raise ValueError("movement execution payload exceeds frozen capacity")
        payload_resource_ids = [row.resource_id for row in self.payload_resources]
        if len(set(payload_resource_ids)) != len(payload_resource_ids):
            raise ValueError("movement execution payload resources must be unique")
        resource_payload_t = sum(row.amount_t for row in self.payload_resources)
        if resource_payload_t > self.payload_t_per_unit * self.units + 1e-9:
            raise ValueError("movement execution resource payload exceeds total payload")

    @property
    def latency_days(self) -> int:
        return sum(leg.latency_days for leg in self.legs)

    @property
    def origin(self) -> MovementEndpoint:
        return self.legs[0].origin

    @property
    def destination(self) -> MovementEndpoint:
        return self.legs[-1].destination

    @property
    def final_asset_disposition(self) -> OperationAssetDisposition:
        return self.legs[-1].asset_disposition

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

    def movement_asset_disposition(self, plan: MovementPlan) -> OperationAssetDisposition:
        disposition = OperationAssetDisposition.DESTINATION
        for operation in plan.operations:
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

    def propellant_t(self, plan: MovementPlan, cargo_t: float) -> float:
        return self.propellant_t_per_total_t_per_km_s * (self.dry_mass_t + cargo_t) * plan.delta_v_km_s

    def max_cargo_for_movement(self, plan: MovementPlan) -> float:
        if self.propellant_t_per_total_t_per_km_s <= 1e-12 or plan.delta_v_km_s <= 1e-12:
            return self.payload_t
        mass_budget = self.propellant_capacity_t / (
            self.propellant_t_per_total_t_per_km_s * plan.delta_v_km_s
        )
        return max(0.0, min(self.payload_t, mass_budget - self.dry_mass_t))


@dataclass(frozen=True)
class VehicleProductionSpec:
    service_type: str | None = None
    days: float = 0.0
    resources: tuple[tuple[DefinitionId, float], ...] = ()
    site_requirements: SiteRequirements = SiteRequirements()


class FleetRetirementPhase(str, Enum):
    COMMITTED = "committed"
    DISMANTLING = "dismantling"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class VehicleRetirementSpec:
    service_type: str | None = None
    work_days_per_unit: float = 0.0
    resources_per_unit: tuple[tuple[DefinitionId, float], ...] = ()
    recovery_resources_per_unit: tuple[tuple[DefinitionId, float], ...] = ()
    site_requirements: SiteRequirements = SiteRequirements()

    @property
    def enabled(self) -> bool:
        return self.work_days_per_unit > 0.0

    def __post_init__(self) -> None:
        if self.work_days_per_unit < 0:
            raise ValueError("retirement work must be non-negative")
        if any(amount < 0 for _resource_id, amount in self.resources_per_unit):
            raise ValueError("retirement resource requirements must be non-negative")
        if any(amount < 0 for _resource_id, amount in self.recovery_resources_per_unit):
            raise ValueError("retirement recovery resources must be non-negative")


@dataclass
class FleetRetirementState:
    id: EntityId
    vehicle_definition_id: DefinitionId
    operational_node_id: SpatialNodeId
    units: int
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    progress_work: float = 0.0
    phase: FleetRetirementPhase = FleetRetirementPhase.COMMITTED
    irreversible_started: bool = False
    created_day: int = 0
    salvage_wait_started_day: int | None = None

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)
        if self.units <= 0:
            raise ValueError("retirement units must be positive")
        if self.progress_work < 0:
            raise ValueError("retirement progress must be non-negative")


@dataclass(frozen=True)
class VehicleMaintenanceSpec:
    service_type: str | None = None
    turnaround_days: float = 0.0
    resources: tuple[tuple[DefinitionId, float], ...] = ()


@dataclass(frozen=True)
class VehicleDef:
    id: DefinitionId
    display_name: str
    performance: TransportPerformanceProfile
    production: VehicleProductionSpec = VehicleProductionSpec()
    retirement: VehicleRetirementSpec = VehicleRetirementSpec()
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
    def production_service_type(self) -> str | None: return self.production.service_type
    @property
    def production_days(self) -> float: return self.production.days
    @property
    def production_resources(self) -> tuple[tuple[DefinitionId, float], ...]: return self.production.resources
    @property
    def turnaround_service_type(self) -> str | None: return self.maintenance.service_type
    @property
    def turnaround_days(self) -> float: return self.maintenance.turnaround_days
    @property
    def turnaround_resources(self) -> tuple[tuple[DefinitionId, float], ...]: return self.maintenance.resources

    def capability_for(self, operation_type: str) -> OperationCapability | None:
        return self.performance.capability_for(operation_type)

    def propellant_t(self, plan: MovementPlan, cargo_t: float) -> float:
        return self.performance.propellant_t(plan, cargo_t)

    def max_cargo_for_movement(self, plan: MovementPlan) -> float:
        return self.performance.max_cargo_for_movement(plan)

    def movement_asset_disposition(self, plan: MovementPlan) -> OperationAssetDisposition:
        return self.performance.movement_asset_disposition(plan)

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

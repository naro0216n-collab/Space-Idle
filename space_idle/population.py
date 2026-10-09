from __future__ import annotations

from dataclasses import dataclass, field
import math

from .execution_requirements import (
    AllocationConstraintKey, ExecutionAllocationPlan, ExecutionRequirementBundle,
    PoolRequirement, ResourceRequirement, ServiceCapacityRequirement, pool_constraint,
    resource_constraint, service_constraint, allocate_execution_requirements,
)
from .facilities import FacilityBook
from .facility_lifecycle import FacilityLifecycleBlocker
from .inventory import InventoryBook
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .shared import DefinitionId, EntityId, SpatialNodeId, MovementPlanId
from .spatial import SpatialGraph
from .supply import SupplyRequirement
from .service_capacity import ServiceCapacityScope



@dataclass(frozen=True)
class PopulationRules:
    recovery_rate: float
    mortality_rate: float
    lethal_threshold: float
    incapacitation_threshold: float

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) or value <= 0 for value in (
            self.recovery_rate, self.mortality_rate, self.lethal_threshold,
            self.incapacitation_threshold,
        )):
            raise ValueError('population rules must be positive and finite')


@dataclass(frozen=True)
class PopulationPosition:
    kind: str
    ref: str

    def __post_init__(self) -> None:
        if self.kind not in {'operational_node', 'physical_target', 'transport_execution'} or not self.ref:
            raise ValueError('invalid population position')


@dataclass
class PopulationGroup:
    id: EntityId
    count: int
    position: PopulationPosition
    activity_commitment_ref: str | None = None
    deprivation: float = 0.0
    mortality_remainder: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1:
            raise ValueError('population count must be a positive integer')
        if not math.isfinite(self.deprivation) or self.deprivation < 0:
            raise ValueError('invalid deprivation')
        if not math.isfinite(self.mortality_remainder) or not 0 <= self.mortality_remainder < 1:
            raise ValueError('invalid mortality remainder')


@dataclass(frozen=True)
class ExternalPopulationSourceDefinition:
    id: str
    operational_node_id: SpatialNodeId
    initial_people: int
    max_acquisition_per_day: int

    def __post_init__(self) -> None:
        for value in (self.initial_people, self.max_acquisition_per_day):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('external population quantities must be nonnegative integers')
        if not self.id:
            raise ValueError('external population source id required')


@dataclass(frozen=True)
class PassengerCapacitySource:
    """One player-selected transport capability; no implied Allocation creation."""

    transport_allocation_ids: tuple[EntityId, ...] | None = None
    dedicated_vehicle_definition_id: DefinitionId | None = None
    dedicated_units: int | None = None
    movement_hard_constraint: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        service = self.transport_allocation_ids is not None
        dedicated = self.dedicated_vehicle_definition_id is not None
        if service == dedicated:
            raise ValueError('select either a transport service path or dedicated free Fleet')
        if service and (not self.transport_allocation_ids or self.dedicated_units is not None
                        or self.movement_hard_constraint is not None):
            raise ValueError('invalid selected transport service path')
        if dedicated and (isinstance(self.dedicated_units, bool) or not isinstance(self.dedicated_units, int)
                          or self.dedicated_units < 1):
            raise ValueError('dedicated Fleet requires positive integer units')
        if self.movement_hard_constraint is not None and not self.movement_hard_constraint:
            raise ValueError('explicit movement path must not be empty')


@dataclass
class PassengerTransferOrder:
    id: EntityId
    origin_node_id: SpatialNodeId
    destination_node_id: SpatialNodeId
    requested_count: int
    activity_priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    source_external_provider_id: str | None = None
    capacity_source_constraint: PassengerCapacitySource | None = None
    delivered_count: int = 0
    cancelled_count: int = 0
    # Historical fatalities in transit are neither arrivals nor cancellation
    # of an unshipped intent; they must not recreate pending passengers.
    deceased_count: int = 0
    in_transit_group_refs: list[EntityId] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.activity_priority = ActivityPriority(self.activity_priority)
        if self.origin_node_id == self.destination_node_id:
            raise ValueError('passenger transfer must connect different Operational Nodes')
        if isinstance(self.requested_count, bool) or not isinstance(self.requested_count, int) or self.requested_count < 1:
            raise ValueError('passenger transfer must request positive integer people')
        for count in (self.delivered_count, self.cancelled_count, self.deceased_count):
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError('passenger settlement counts must be nonnegative integers')
        if self.delivered_count + self.cancelled_count + self.deceased_count > self.requested_count:
            raise ValueError('passenger settlements exceed requested count')
        if len(set(self.in_transit_group_refs)) != len(self.in_transit_group_refs):
            raise ValueError('duplicate passenger transit group reference')

    def transit_count(self, groups: dict[EntityId, PopulationGroup]) -> int:
        return sum(groups[identifier].count for identifier in self.in_transit_group_refs)

    def pending_count(self, groups: dict[EntityId, PopulationGroup]) -> int:
        return self.requested_count - self.delivered_count - self.cancelled_count - self.deceased_count - self.transit_count(groups)

    def status(self, groups: dict[EntityId, PopulationGroup]) -> str:
        if self.cancelled_count:
            return 'cancelled'
        if self.pending_count(groups) == 0 and not self.in_transit_group_refs:
            return 'completed'
        if self.in_transit_group_refs:
            return 'active'
        return 'pending'


@dataclass(frozen=True)
class PassengerDispatchOption:
    """A snapshot of physical movement eligibility, not an accepted booking."""

    mode: str
    vehicle_definition_id: DefinitionId
    allocation_ids: tuple[EntityId, ...]
    movement_path: tuple[MovementPlanId, ...]
    units: int
    latency_days: int
    possible_people: int
    payload_per_person_t: float
    resources_for_dispatch: tuple[tuple[SpatialNodeId, DefinitionId, float], ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.mode not in {'service', 'dedicated'}:
            raise ValueError('invalid passenger dispatch mode')
        if self.possible_people < 0:
            raise ValueError('invalid passenger dispatch quantity')


@dataclass(frozen=True)
class PassengerDispatchDemand:
    """Ephemeral common dispatch candidate; only manual intent is an Order."""

    id: EntityId
    origin_node_id: SpatialNodeId
    destination_node_id: SpatialNodeId
    requested_count: int
    activity_priority: ActivityPriority
    source_external_provider_id: str | None
    order_id: EntityId | None
    transport_allocation_ids: frozenset[EntityId] | None = None


@dataclass
class PopulationService:
    facilities: FacilityBook
    inventory: InventoryBook
    graph: SpatialGraph
    rules: PopulationRules
    external_definitions: dict[str, ExternalPopulationSourceDefinition]
    groups: dict[EntityId, PopulationGroup] = field(default_factory=dict)
    targets: dict[SpatialNodeId, int] = field(default_factory=dict)
    transfer_orders: dict[EntityId, PassengerTransferOrder] = field(default_factory=dict)
    external_remaining: dict[str, int] = field(default_factory=dict)
    # Daily quota accounting, not another people Stock.  A completed boundary
    # and subsequent dispatches must draw from the same finite source quota.
    external_acquisition_day: int = -1
    external_acquired_today: dict[str, int] = field(default_factory=dict)
    _next_group_id: int = 0
    _next_transfer_order_id: int = 0
    _day_fulfillment: dict[SpatialNodeId, float] = field(default_factory=dict, repr=False)
    transport: object | None = field(default=None, repr=False, compare=False)
    logistics: object | None = field(default=None, repr=False, compare=False)
    _service_dispatch_choices: dict[EntityId, tuple] = field(default_factory=dict, repr=False, compare=False)
    _dispatch_options: dict[EntityId, PassengerDispatchOption] = field(default_factory=dict, repr=False, compare=False)

    def service_capacity_types(self) -> tuple[str, ...]:
        return ('life_support', 'crew')

    def service_capacity_scope(self, service_type: str) -> ServiceCapacityScope:
        if service_type not in self.service_capacity_types():
            raise ValueError('unknown Population service type')
        return ServiceCapacityScope.OPERATIONAL_NODE

    def service_capacity_provider_definition_ids(self, service_type: str) -> frozenset[DefinitionId]:
        if service_type == 'life_support':
            return frozenset(identifier for identifier, definition in self.facilities.definitions.items()
                             if definition.life_support is not None)
        if service_type == 'crew':
            return frozenset()
        raise ValueError('unknown Population service type')

    def service_capacity_upstream_services(self, service_type: str) -> frozenset[str]:
        self.service_capacity_scope(service_type)
        return frozenset()

    def service_capacity_supply_at(self, operational_node_id, service_type, facilities, power,
                                   day=0, *, provider_factors=None) -> tuple[float, float]:
        self.service_capacity_scope(service_type)
        if service_type == 'crew':
            rate = sum(group.count * self.crew_factor(group) for group in self.groups_at(operational_node_id)
                       if group.activity_commitment_ref is None)
            return (rate, rate)
        nominal = 0.0
        enabled = 0.0
        for facility in facilities.all_at(operational_node_id):
            definition = facilities.definitions[facility.definition_id]
            if definition.life_support is None:
                continue
            amount = definition.life_support.person_days_per_day * facility.level
            nominal += amount
            if not facilities.is_active_and_compatible(facility, day):
                continue
            factor = (1.0 if provider_factors is None else provider_factors.get(facility.id, 1.0))
            if power is not None:
                factor *= power.utilization_by_facility.get(facility.id, 1.0)
            enabled += amount * max(0.0, min(1.0, factor))
        return nominal, enabled

    def initialize(self, node_id: SpatialNodeId, count: int) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError('initial population count must be positive')
        if not self.graph.has_operational_node(node_id):
            raise ValueError('population source must be an existing operational node')
        self._next_group_id += 1
        group = PopulationGroup(
            EntityId(f'population.group:{self._next_group_id}'), count,
            PopulationPosition('operational_node', str(node_id)),
        )
        self.groups[group.id] = group

    def initialize_external_sources(self) -> None:
        if self.external_remaining:
            raise ValueError('external population already initialized')
        self.external_remaining = {
            identifier: definition.initial_people
            for identifier, definition in sorted(self.external_definitions.items())
        }

    def external_available(self, source_id: str, day: int) -> int:
        definition = self.external_definitions[source_id]
        used = (self.external_acquired_today.get(source_id, 0)
                if self.external_acquisition_day == day else 0)
        return max(0, min(self.external_remaining[source_id],
                          definition.max_acquisition_per_day - used))

    def _acquire_external(self, source_id: str, count: int, day: int) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError('acquisition must be a positive integer')
        if count > self.external_available(source_id, day):
            raise ValueError('external supply quota or remaining people exhausted')
        if self.external_acquisition_day != day:
            self.external_acquisition_day = day
            self.external_acquired_today.clear()
        self.external_remaining[source_id] -= count
        self.external_acquired_today[source_id] = self.external_acquired_today.get(source_id, 0) + count

    def _supportable_admission(self, node_id: SpatialNodeId, requested: int, day: int) -> int:
        """Estimate immediately supportable integer arrivals using the common allocator.

        This evaluates the same Life Support bundles as execution against the
        currently available Inventory. Other activities still compete with them
        during the authoritative daily Allocation; this is not an extra solver or
        a reservation of future Resource.
        """
        existing = self.count_at(node_id)
        housing = self.housing_capacity(node_id, day)
        providers = [
            (facility, definition.life_support)
            for facility, definition in self._facilities_at(node_id, day)
            if definition.life_support is not None
        ]
        provider_capacity = sum(spec.person_days_per_day * facility.level for facility, spec in providers)
        upper = min(requested, max(0, housing - existing),
                    max(0, math.floor(provider_capacity + 1e-9) - existing))
        if upper == 0:
            return 0

        def feasible(additional: int) -> bool:
            people = existing + additional
            bundles = self._life_support_bundles_at(node_id, people, day)
            capacities = {
                pool_constraint('life_support_need', scope_id=str(node_id)): float(people),
                pool_constraint('housing', scope_id=str(node_id)): float(housing),
                service_constraint(node_id, 'life_support'): provider_capacity,
            }
            for facility, spec in providers:
                capacities[pool_constraint('life_support_provider', scope_id=str(facility.id))] = (
                    spec.person_days_per_day * facility.level
                )
                for resource, _ in spec.net_resources:
                    capacities[resource_constraint(node_id, resource)] = self.inventory.amount(node_id, resource)
            allocated = allocate_execution_requirements(bundles, capacities)
            return sum(allocated.allocated(row.id) for row in bundles) + 1e-7 >= people

        low, high = 0, upper
        while low < high:
            candidate = (low + high + 1) // 2
            if feasible(candidate):
                low = candidate
            else:
                high = candidate - 1
        return low

    def local_target_preview(self, node_id: SpatialNodeId, day: int) -> tuple[int, int, tuple[str, ...]]:
        target = self.targets.get(node_id)
        if target is None:
            return 0, 0, ()
        unmet = max(0, target - self.count_at(node_id))
        if not unmet:
            return 0, 0, ()
        sources = tuple(source_id for source_id, source in sorted(self.external_definitions.items())
                        if source.operational_node_id == node_id)
        available = sum(self.external_available(source_id, day) for source_id in sources)
        receivable = self._supportable_admission(node_id, min(unmet, available), day)
        blockers: list[str] = []
        if not sources:
            blockers.append('transport_required')
        elif available == 0:
            blockers.append('external_supply_limit')
        if self.housing_capacity(node_id, day) <= self.count_at(node_id):
            blockers.append('housing_full')
        if receivable < min(unmet, available) and self.housing_capacity(node_id, day) > self.count_at(node_id):
            blockers.append('life_support_or_resource_limit')
        return unmet, receivable, tuple(blockers)

    def acquire_for_local_targets(self, day: int) -> None:
        """Accept finite external people only at their existing source Node.

        A target at another Node creates transport demand, never direct
        population insertion. Local arrivals use the same finite daily quota as
        later manual dispatches and are constrained by current living capacity.
        """
        for node_id, desired in sorted(self.targets.items(), key=lambda row: str(row[0])):
            missing = desired - self.count_at(node_id)
            if missing <= 0:
                continue
            sources = [identifier for identifier, source in sorted(self.external_definitions.items())
                       if source.operational_node_id == node_id]
            available = sum(self.external_available(identifier, day) for identifier in sources)
            headroom = self._supportable_admission(node_id, min(missing, available), day)
            for source_id in sources:
                count = min(headroom, self.external_available(source_id, day))
                if count == 0:
                    continue
                self._acquire_external(source_id, count, day)
                self._add_uncommitted_at(node_id, count)
                headroom -= count
                if headroom == 0:
                    break

    def _add_uncommitted_at(self, node_id: SpatialNodeId, count: int) -> None:
        """Merge only with an identical group; preserve accumulated deprivation."""
        for group in self.groups_at(node_id):
            if (group.activity_commitment_ref is None and group.deprivation == 0
                    and group.mortality_remainder == 0):
                group.count += count
                return
        self.initialize(node_id, count)

    def _split_group(self, group: PopulationGroup, count: int) -> PopulationGroup:
        """Split a real stock, retaining exact total mortality credit."""
        if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > group.count:
            raise ValueError('invalid population split size')
        if count == group.count:
            return group
        original = group.count
        credit = group.mortality_remainder * count / original
        group.count -= count
        group.mortality_remainder -= credit
        self._next_group_id += 1
        child = PopulationGroup(
            EntityId(f'population.group:{self._next_group_id}'), count, group.position,
            group.activity_commitment_ref, group.deprivation, credit,
        )
        self.groups[child.id] = child
        return child

    def free_count_at(self, node_id: SpatialNodeId) -> int:
        return sum(group.count for group in self.groups_at(node_id)
                   if group.activity_commitment_ref is None)

    def commit_activity(self, node_id: SpatialNodeId, count: int, activity_ref: str) -> tuple[EntityId, ...]:
        if not activity_ref or isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError('invalid exclusive population activity')
        if self.free_count_at(node_id) < count:
            raise ValueError('not enough uncommitted people')
        remaining = count
        selected: list[EntityId] = []
        for group in self.groups_at(node_id):
            if group.activity_commitment_ref is not None:
                continue
            selected_group = self._split_group(group, min(remaining, group.count))
            selected_group.activity_commitment_ref = activity_ref
            selected.append(selected_group.id)
            remaining -= selected_group.count
            if remaining == 0:
                break
        return tuple(selected)

    def activity_groups(self, activity_ref: str) -> tuple[PopulationGroup, ...]:
        """Return the sole authoritative crew for an exclusive Activity."""
        return tuple(group for group in sorted(self.groups.values(), key=lambda row: str(row.id))
                     if group.activity_commitment_ref == activity_ref)

    def activity_count(self, activity_ref: str) -> int:
        return sum(group.count for group in self.activity_groups(activity_ref))

    def activity_work_fraction(self, activity_ref: str, required_people: int) -> float:
        """Common effective Crew fulfillment for exclusive finite Activities."""
        if required_people < 0:
            raise ValueError('invalid Activity crew requirement')
        if required_people == 0:
            return 1.0
        return min(1.0, sum(group.count * self.crew_factor(group)
                            for group in self.activity_groups(activity_ref)) / required_people)

    def move_activity_to_execution(self, activity_ref: str, execution_id: EntityId) -> None:
        """Board all committed survivors, whether at a Node or a physical target."""
        selected = self.activity_groups(activity_ref)
        for group in selected:
            if group.position.kind not in {'operational_node', 'physical_target'}:
                raise ValueError('Activity crew is not at a departure site')
        for group in selected:
            group.position = PopulationPosition('transport_execution', str(execution_id))

    def settle_activity_at_target(self, activity_ref: str, *,
                                  node_id: SpatialNodeId | None = None,
                                  physical_ref: str | None = None) -> None:
        if (node_id is None) == (physical_ref is None):
            raise ValueError('Activity arrival needs exactly one physical destination')
        position = (PopulationPosition('operational_node', str(node_id)) if node_id is not None
                    else PopulationPosition('physical_target', physical_ref))
        if node_id is not None and not self.graph.has_operational_node(node_id):
            raise ValueError('Activity destination is not established')
        selected = self.activity_groups(activity_ref)
        if any(group.position.kind != 'transport_execution' for group in selected):
            raise ValueError('Activity crew is not in Movement')
        for group in selected:
            group.position = position

    def settle_activity_life_support(self, activity_ref: str, fulfillment: float) -> int:
        """Apply the same mortality rule to committed crews in their actual cabin."""
        deaths = 0
        for group in self.activity_groups(activity_ref):
            if group.position.kind == 'operational_node':
                continue  # Normal Node Life Support owns this Group today.
            deaths += self._settle_group_deprivation(group, fulfillment)
            if group.count == 0:
                del self.groups[group.id]
        return deaths

    def settle_fleet_activity_life_support(self, activity_ref: str, fleet_commitment_id: EntityId) -> int:
        """Settle an Activity's physical cabin without Activity-specific mortality rules."""
        aboard = sum(group.count for group in self.activity_groups(activity_ref)
                     if group.position.kind != 'operational_node')
        if not aboard:
            return 0
        if self.transport is None:
            raise RuntimeError('Fleet life support requires Transport')
        fulfillment = self.transport.consume_fleet_life_support(fleet_commitment_id, aboard)
        return self.settle_activity_life_support(activity_ref, fulfillment)

    def admission_capacity(self, node_id: SpatialNodeId, count: int, day: int) -> int:
        return self._supportable_admission(node_id, count, day)

    def release_activity(self, activity_ref: str) -> None:
        if not activity_ref:
            raise ValueError('activity reference required')
        for group in self.groups.values():
            if group.activity_commitment_ref == activity_ref:
                group.activity_commitment_ref = None

    def request_transfer(
        self, origin_node_id: SpatialNodeId, destination_node_id: SpatialNodeId,
        count: int, *, source_external_provider_id: str | None = None,
        activity_priority: int = 3,
        capacity_source_constraint: PassengerCapacitySource | None = None,
    ) -> PassengerTransferOrder:
        if not self.graph.has_operational_node(origin_node_id) or not self.graph.has_operational_node(destination_node_id):
            raise ValueError('passenger transfer endpoints must be established Operational Nodes')
        order = PassengerTransferOrder(
            EntityId(f'population.transfer:{self._next_transfer_order_id + 1}'),
            origin_node_id, destination_node_id, count,
            ActivityPriority(activity_priority), source_external_provider_id,
            capacity_source_constraint,
        )
        if source_external_provider_id is not None:
            source = self.external_definitions.get(source_external_provider_id)
            if source is None or source.operational_node_id != origin_node_id:
                raise ValueError('external provider must belong to the selected origin')
            available = self.external_remaining[source_external_provider_id]
        else:
            available = self.free_count_at(origin_node_id)
        if count > available:
            raise ValueError('requested passengers exceed available source population')
        self._next_transfer_order_id += 1
        self.transfer_orders[order.id] = order
        return order

    def cancel_transfer(self, order_id: EntityId) -> PassengerTransferOrder:
        order = self.transfer_orders[order_id]
        pending = order.pending_count(self.groups)
        if pending < 0:
            raise RuntimeError('passenger transfer accounting is inconsistent')
        order.cancelled_count += pending
        return order

    def move_group_to_execution(self, group_id: EntityId, execution_id: EntityId) -> None:
        group = self.groups[group_id]
        if group.position.kind != 'operational_node':
            raise ValueError('only people at source node can board')
        group.position = PopulationPosition('transport_execution', str(execution_id))

    def settle_arrival(self, group_id: EntityId, node_id: SpatialNodeId) -> None:
        group = self.groups[group_id]
        if group.position.kind != 'transport_execution' or not self.graph.has_operational_node(node_id):
            raise ValueError('passenger arrival requires active transit and an established destination')
        group.position = PopulationPosition('operational_node', str(node_id))

    def dedicated_dispatch_option(self, transport, origin_id: SpatialNodeId, destination_id: SpatialNodeId,
                                  requested: int, vehicle_definition_id: DefinitionId, units: int, day: int,
                                  movement_hard_constraint: tuple[str, ...] | None = None) -> PassengerDispatchOption:
        """Evaluate exactly the Fleet/Movement and payload which would be committed."""
        vehicle = transport.vehicle_definition(vehicle_definition_id)
        if vehicle is None:
            raise ValueError('unknown dedicated passenger vehicle')
        accommodation = vehicle.passengers
        blockers: list[str] = []
        if not accommodation.seats:
            blockers.append('no_passenger_seats')
        if units <= 0:
            blockers.append('dedicated_units_required')
        result = transport.fleet_relocation_plan(
            vehicle_definition_id, units, origin_id, destination_id,
            movement_hard_constraint=None if movement_hard_constraint is None else tuple(MovementPlanId(value) for value in movement_hard_constraint),
            day=day, require_destination_disposition=False,
        ) if units > 0 else None
        if result is not None:
            blockers.extend(code for code in result.blockers if not code.startswith('resource:'))
        path = () if result is None else result.path
        latency = 0 if result is None else result.travel_days
        max_seats = accommodation.supportable_seats(units)
        days = max(1, latency)
        passenger_mass = accommodation.person_mass_t + sum(amount * days for _, amount in accommodation.net_resources_per_person_day)
        path_plans = tuple(transport.require_movement_plan(value) for value in path)
        max_mass = min((vehicle.max_cargo_for_movement(row) for row in path_plans), default=0.0) * max(0, units)
        max_people = min(requested, max_seats, int((max_mass + 1e-9) // passenger_mass)) if passenger_mass > 0 else 0
        if max_people == 0 and requested > 0:
            blockers.append('seats_or_payload_limit')

        def resources_for(people: int) -> dict[tuple[SpatialNodeId, DefinitionId], float]:
            needs: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
            for resource, rate in accommodation.net_resources_per_person_day:
                needs[(origin_id, resource)] = needs.get((origin_id, resource), 0.0) + rate * people * days
            if path:
                propellant = transport.movement_resource_requirements_for_plans(
                    vehicle_definition_id, units, path_plans,
                    payload_t_per_unit=people * passenger_mass / units,
                )
                for item in propellant:
                    key = (item.operational_node_id, item.resource_id)
                    needs[key] = needs.get(key, 0.0) + item.required_t
            return needs

        if blockers:
            max_people = 0
        else:
            # Binary search integer physical dispatch size, including real
            # propellant and initial onboard Resource in the same payload.
            low, high = 0, max_people
            while low < high:
                candidate = (low + high + 1) // 2
                needs = resources_for(candidate)
                if all(self.inventory.available(node, resource) + 1e-9 >= amount
                       for (node, resource), amount in needs.items()):
                    low = candidate
                else:
                    high = candidate - 1
            max_people = low
            if max_people == 0:
                blockers.append('operation_or_onboard_resources')
        return PassengerDispatchOption(
            'dedicated', vehicle_definition_id, (), tuple(path), units, latency,
            max_people, passenger_mass,
            tuple((node, resource, amount) for (node, resource), amount in sorted(resources_for(max_people).items(), key=lambda row: (str(row[0][0]), str(row[0][1])))),
            tuple(dict.fromkeys(blockers)),
        )

    @staticmethod
    def _passenger_bundle_id(order_id: EntityId) -> EntityId:
        return EntityId(f'execution.passenger:{order_id}')

    @staticmethod
    def _passenger_execution_id(order_id: EntityId) -> EntityId:
        return EntityId(f'movement.passenger:{order_id}')

    @staticmethod
    def _passenger_commitment_id(order_id: EntityId) -> EntityId:
        return EntityId(f'fleet.commitment.passenger:{order_id}')

    def transfer_preview(self, origin_id: SpatialNodeId, destination_id: SpatialNodeId,
                         requested_count: int, day: int) -> tuple[PassengerDispatchOption, ...]:
        if not self.graph.has_operational_node(origin_id) or not self.graph.has_operational_node(destination_id):
            raise ValueError('passenger transfer requires established endpoints')
        if requested_count < 1:
            raise ValueError('passenger count must be positive')
        transport = self.transport
        if transport is None:
            raise RuntimeError('population transport capability is not composed')
        rows: list[PassengerDispatchOption] = []
        try:
            option, _, _ = self._service_route_option(origin_id, destination_id, requested_count, day)
            rows.append(option)
        except ValueError:
            pass
        for vehicle in transport.vehicle_definitions():
            if vehicle.passengers.seats <= 0:
                continue
            # Scope fleet queries to the selected origin, not the whole world.
            available = transport.fleet_free_units(vehicle.id, origin_id)
            for units in (1, available) if available > 1 else (max(1, available),):
                rows.append(self.dedicated_dispatch_option(
                    transport, origin_id, destination_id, requested_count,
                    vehicle.id, units, day,
                ))
        return tuple(rows)

    def _service_route_option(
        self, origin: SpatialNodeId, destination: SpatialNodeId, requested: int, day: int,
        allowed_allocations: frozenset[EntityId] | None = None,
    ) -> tuple[PassengerDispatchOption, tuple, dict[DefinitionId, float]]:
        """Evaluate a physical Service path, its seats, payload and provisions."""
        from .transport.models import PassengerAccommodation
        if self.logistics is None or self.transport is None:
            raise RuntimeError('passenger Service is not composed')
        route = self.logistics.passenger_service_path(origin, destination, day, allowed_allocations)
        if not route:
            raise ValueError('no passenger transport service route')
        total_days = sum(edge.latency_days for edge in route)
        onboard: dict[DefinitionId, float] = {}
        seats = requested
        for edge in route:
            accommodation = self.transport.service_vehicle(edge.allocation_id).passengers
            seats = min(seats, accommodation.supportable_seats(
                self.transport.transport_active_units(edge.allocation_id)))
            for resource, rate in accommodation.net_resources_per_person_day:
                onboard[resource] = onboard.get(resource, 0.0) + rate * edge.latency_days
        # Provisions are physically carried between legs, not regenerated at stops.
        food_mass = sum(onboard.values())
        mass = max(self.transport.service_vehicle(edge.allocation_id).passengers.person_mass_t
                   for edge in route) + food_mass
        for edge in route:
            seats = min(seats, math.floor((edge.capacity_t_per_day + 1e-9) / mass))
        blockers = () if seats else ('passenger_seat_or_mass_capacity',)
        return (PassengerDispatchOption(
            'service', self.transport.service_vehicle(route[0].allocation_id).id,
            tuple(edge.allocation_id for edge in route),
            tuple(plan for edge in route for plan in edge.movement_plan_path),
            self.transport.transport_active_units(route[0].allocation_id), total_days,
            max(0, seats), mass,
            tuple((origin, resource, rate * max(0, seats))
                  for resource, rate in sorted(onboard.items(), key=lambda row: str(row[0]))),
            blockers,
        ), route, onboard)

    def service_seat_pool_capacities(self, day: int) -> dict[AllocationConstraintKey, float]:
        """Seat supply is derived from precisely the same Fleet as mass supply."""
        if self.transport is None or self.logistics is None:
            return {}
        occupied = {}
        for transit in self.transport.passenger_service_transits.values():
            # A physical seat occupied during an ongoing leg is not a second
            # vacant seat in the same Fleet service cycle. At an arrival hold,
            # the last vehicle also remains occupied until settlement.
            leg = transit.active_leg(day)
            count = sum(self.groups[group_id].count for group_id in transit.passenger_group_refs)
            occupied[leg.service_key] = occupied.get(leg.service_key, 0) + count
        capacities = {}
        for edge in self.logistics._service_edges(day):
            accommodation = self.transport.service_vehicle(edge.allocation_id).passengers
            supply = accommodation.supportable_seats(self.transport.transport_active_units(edge.allocation_id))
            capacities[pool_constraint(edge.key, scope_id='passenger_service_seats')] = float(
                max(0, supply - occupied.get(edge.key, 0)))
        return capacities

    @staticmethod
    def _service_bundle_id(order_id: EntityId, ordinal: int) -> EntityId:
        return EntityId(f'execution.passenger.service:{order_id}:{ordinal}')

    def _inbound_by_node(self) -> dict[SpatialNodeId, int]:
        inbound: dict[SpatialNodeId, int] = {}
        if self.transport is not None:
            for transit in self.transport.passenger_service_transits.values():
                node = transit.legs[-1].destination_id
                inbound[node] = inbound.get(node, 0) + sum(
                    self.groups[group_id].count for group_id in transit.passenger_group_refs
                )
        for order in self.transfer_orders.values():
            if order.capacity_source_constraint is None or order.capacity_source_constraint.dedicated_vehicle_definition_id is None:
                continue
            inbound[order.destination_node_id] = inbound.get(order.destination_node_id, 0) + order.transit_count(self.groups)
        return inbound

    def _automatic_passenger_demands(self, day: int) -> tuple[PassengerDispatchDemand, ...]:
        """Derived unmet target movements through already owned Service capacity."""
        if self.logistics is None:
            return ()
        inbound = self._inbound_by_node()
        candidates: list[PassengerDispatchDemand] = []
        for destination, target in sorted(self.targets.items(), key=lambda item: str(item[0])):
            accepted_manual = sum(
                order.pending_count(self.groups)
                for order in self.transfer_orders.values()
                if order.destination_node_id == destination
            )
            deficit = max(0, target - self.count_at(destination)
                          - inbound.get(destination, 0) - accepted_manual)
            if not deficit:
                continue
            headroom = min(deficit, self._supportable_admission(destination, deficit, day))
            if not headroom:
                continue
            options = []
            for origin, own_target in sorted(self.targets.items(), key=lambda item: str(item[0])):
                if origin == destination:
                    continue
                accepted_outbound = sum(
                    order.pending_count(self.groups) for order in self.transfer_orders.values()
                    if order.origin_node_id == origin and order.source_external_provider_id is None
                )
                surplus = min(self.free_count_at(origin), max(0, self.count_at(origin) - own_target
                                                             - accepted_outbound))
                if surplus:
                    options.append((origin, surplus, None))
            # Owned surplus has absolute source precedence. Only an unmet
            # remainder is eligible for finite external acquisition; no route
            # through owned surplus must not suppress reachable external supply.
            external_options = [
                (source.operational_node_id, self.external_available(source_id, day), source_id)
                for source_id, source in sorted(self.external_definitions.items())
                if source.operational_node_id != destination and self.external_available(source_id, day)
            ]
            remaining = headroom
            for sources in (options, external_options):
                ranked = []
                for origin, available, source_id in sources:
                    try:
                        option, _, _ = self._service_route_option(
                            origin, destination, min(available, remaining), day,
                        )
                    except ValueError:
                        continue
                    if option.possible_people:
                        ranked.append((option.latency_days, option.payload_per_person_t,
                                       str(origin), source_id or '', origin, available, source_id))
                for _, _, _, _, origin, available, source_id in sorted(ranked):
                    amount = min(remaining, available)
                    if not amount:
                        continue
                    candidates.append(PassengerDispatchDemand(
                        EntityId(f'population.auto:{"0-owned" if source_id is None else "1-external"}:{destination}:{origin}:{source_id or "owned"}'),
                        origin, destination, amount, ActivityPriority(3), source_id, None,
                    ))
                    remaining -= amount
                    if not remaining:
                        break
                if not remaining:
                    break
        return tuple(candidates)

    def passenger_service_bundles(self, day: int, reference_usage: dict) -> tuple[ExecutionRequirementBundle, ...]:
        """Finite integer passenger demands use Cargo's common mass/operation pools."""
        from .transport.models import DirectionalCapacity
        self._service_dispatch_choices.clear()
        if self.transport is None or self.logistics is None:
            return ()
        bundles = []
        demands = list(self._automatic_passenger_demands(day))
        for order in self.transfer_orders.values():
            pending = order.pending_count(self.groups)
            choice = order.capacity_source_constraint
            if pending <= 0 or (choice is not None and choice.dedicated_vehicle_definition_id is not None):
                continue
            demands.append(PassengerDispatchDemand(
                order.id, order.origin_node_id, order.destination_node_id, pending,
                order.activity_priority, order.source_external_provider_id, order.id,
                None if choice is None else frozenset(choice.transport_allocation_ids),
            ))
        inbound_by_node = self._inbound_by_node()
        for demand in sorted(demands, key=lambda item: str(item.id)):
            try:
                option, route, onboard = self._service_route_option(
                    demand.origin_node_id, demand.destination_node_id, demand.requested_count,
                    day, demand.transport_allocation_ids,
                )
            except ValueError:
                continue
            source_people = (self.free_count_at(demand.origin_node_id)
                             if demand.source_external_provider_id is None
                             else self.external_available(demand.source_external_provider_id, day))
            inbound = inbound_by_node.get(demand.destination_node_id, 0)
            count = self._supportable_admission(
                demand.destination_node_id, min(option.possible_people, source_people,
                                                max(0, self.housing_capacity(demand.destination_node_id, day)
                                                    - self.count_at(demand.destination_node_id) - inbound)), day)
            if not count:
                continue
            resources = {(demand.origin_node_id, resource): rate for resource, rate in onboard.items()}
            services: dict[tuple[SpatialNodeId, str], float] = {}
            pool_amounts: dict[str, float] = {}
            for edge in route:
                pool_amounts[edge.key] = pool_amounts.get(edge.key, 0.0) + option.payload_per_person_t
                baseline = reference_usage.get(edge.allocation_id, DirectionalCapacity())
                operation = self.transport.transport_operation_usage_requirements(edge.allocation_id, day, baseline)
                op_resources = (operation.forward_resource_per_t if edge.direction == 'forward'
                                else operation.reverse_resource_per_t)
                turnaround = (operation.forward_turnaround_per_t if edge.direction == 'forward'
                              else operation.reverse_turnaround_per_t)
                for node, resource, amount in op_resources:
                    key = (node, resource)
                    resources[key] = resources.get(key, 0.0) + option.payload_per_person_t * amount
                if operation.turnaround_service_type and turnaround > 1e-12:
                    key = (operation.turnaround_node_id, operation.turnaround_service_type)
                    services[key] = services.get(key, 0.0) + option.payload_per_person_t * turnaround
            requirements = [
                *(ResourceRequirement(resource, amount, constraint_node_id=node)
                  for (node, resource), amount in sorted(resources.items(), key=lambda item: (str(item[0][0]), str(item[0][1])))
                  if amount > 1e-12),
                *(ServiceCapacityRequirement(service, amount, constraint_node_id=node)
                  for (node, service), amount in sorted(services.items(), key=lambda item: (str(item[0][0]), item[0][1]))
                  if amount > 1e-12),
                *(PoolRequirement(key, mass, scope_id='transport_capacity')
                  for key, mass in sorted(pool_amounts.items())),
                *(PoolRequirement(edge.key, 1, scope_id='passenger_service_seats') for edge in route),
                PoolRequirement('passenger_arrival_housing', 1, scope_id=str(demand.destination_node_id)),
                PoolRequirement(('passenger_people' if demand.source_external_provider_id is None
                                 else 'passenger_external:' + demand.source_external_provider_id), 1,
                                scope_id=(str(demand.origin_node_id) if demand.source_external_provider_id is None
                                          else demand.source_external_provider_id)),
            ]
            if demand.order_id is None:
                requirements.append(PoolRequirement('passenger_target_gap', 1,
                                                    scope_id=str(demand.destination_node_id)))
            # Binary-size atomic roots bound solver cost without silently dropping
            # integer people.  1/2/4/... plus remainder is exactly the demand.
            sizes = []
            remaining, size = count, 1
            while remaining:
                amount = min(size, remaining)
                sizes.append(amount)
                remaining -= amount
                size *= 2
            for ordinal, amount in enumerate(sizes):
                bundle_id = self._service_bundle_id(demand.id, ordinal)
                scaled_requirements = tuple(
                    ResourceRequirement(row.resource_id, row.amount_per_execution * amount, row.constraint_node_id)
                    if isinstance(row, ResourceRequirement) else
                    ServiceCapacityRequirement(row.service_type, row.amount_per_execution * amount, row.constraint_node_id,
                                               row.scope, row.scope_id)
                    if isinstance(row, ServiceCapacityRequirement) else
                    PoolRequirement(row.pool_id, row.amount_per_execution * amount, row.scope_id)
                    for row in requirements
                )
                bundles.append(ExecutionRequirementBundle(
                    id=bundle_id, owner_kind='population', owner_id=demand.id,
                    purpose='passenger_transport_service', operational_node_id=demand.origin_node_id,
                    requested_execution=1, priority=demand.activity_priority,
                    requirements=scaled_requirements, atomic=True, wait_started_day=0,
                ))
                self._service_dispatch_choices[bundle_id] = (demand, route, amount, dict(onboard), resources,
                                                               option.payload_per_person_t)
        return tuple(bundles)

    def passenger_service_usage(self, execution: ExecutionAllocationPlan) -> dict:
        """Allocated passenger payload contributes to the same Fleet utilization."""
        from .transport.models import DirectionalCapacity
        rows = {}
        for bundle_id, (_, route, amount, _, _, mass) in self._service_dispatch_choices.items():
            if execution.allocated(bundle_id) < 1 - 1e-9:
                continue
            for edge in route:
                before = rows.get(edge.allocation_id, DirectionalCapacity())
                weight = amount * mass
                rows[edge.allocation_id] = DirectionalCapacity(
                    before.forward_t_per_day + (weight if edge.direction == 'forward' else 0),
                    before.reverse_t_per_day + (weight if edge.direction == 'reverse' else 0),
                )
        return rows

    def dispatch_allocated_service_passengers(self, execution: ExecutionAllocationPlan, day: int) -> None:
        """Settle real allocated departures, keeping people owned by Population."""
        from .transport.models import PassengerServiceLeg, PassengerServiceTransit
        if self.transport is None:
            return
        grouped: dict[EntityId, list[tuple]] = {}
        for bundle_id, row in sorted(self._service_dispatch_choices.items(), key=lambda item: str(item[0])):
            if execution.allocated(bundle_id) >= 1 - 1e-9:
                grouped.setdefault(row[0].id, []).append(row)
        for demand_id, rows in sorted(grouped.items(), key=lambda item: str(item[0])):
            demand: PassengerDispatchDemand = rows[0][0]
            order = self.transfer_orders[demand.order_id] if demand.order_id is not None else None
            count = sum(row[2] for row in rows)
            route, per_person_onboard, mass = rows[0][1], rows[0][3], rows[0][5]
            if count > (order.pending_count(self.groups) if order is not None else demand.requested_count):
                raise RuntimeError('overallocated passenger order')
            transit_id = EntityId(f'transport.passenger:{demand_id}:{day}')
            if transit_id in self.transport.passenger_service_transits:
                raise RuntimeError('duplicate passenger service dispatch')
            if demand.source_external_provider_id is not None:
                self._acquire_external(demand.source_external_provider_id, count, day)
                self._add_uncommitted_at(demand.origin_node_id, count)
            for resource, rate in per_person_onboard.items():
                self.inventory.consume_allocated(demand.origin_node_id, resource, count * rate)
            operational_use: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
            for _, _, size, _, resources, _ in rows:
                for key, per_person in resources.items():
                    operational_use[key] = operational_use.get(key, 0.0) + size * per_person
            for (node, resource), amount in operational_use.items():
                if node == demand.origin_node_id and resource in per_person_onboard:
                    amount -= count * per_person_onboard[resource]
                if amount > 1e-12:
                    self.inventory.consume_allocated(node, resource, amount)
            remaining = count
            manifest = []
            for group in self.groups_at(demand.origin_node_id):
                if group.activity_commitment_ref is not None:
                    continue
                boarding = self._split_group(group, min(group.count, remaining))
                self.move_group_to_execution(boarding.id, transit_id)
                if order is not None:
                    order.in_transit_group_refs.append(boarding.id)
                manifest.append(boarding.id)
                remaining -= boarding.count
                if remaining == 0:
                    break
            if remaining:
                raise RuntimeError('passenger departure lost allocated people')
            legs = tuple(PassengerServiceLeg(
                edge.key, edge.allocation_id, edge.source_id, edge.destination_id,
                edge.latency_days, self.transport.service_vehicle(edge.allocation_id).passengers, count * mass)
                for edge in route)
            self.transport.passenger_service_transits[transit_id] = PassengerServiceTransit(
                transit_id, demand.order_id, tuple(manifest), legs, day, day,
                {resource: rate * count for resource, rate in per_person_onboard.items()},
            )
        self._service_dispatch_choices.clear()

    def passenger_dispatch_bundles(self, day: int) -> tuple[ExecutionRequirementBundle, ...]:
        """One finite Movement demand per Order, arbitrated by the common allocator."""
        transport = self.transport
        if transport is None:
            return ()
        self._dispatch_options.clear()
        bundles: list[ExecutionRequirementBundle] = []
        for order in sorted(self.transfer_orders.values(), key=lambda row: str(row.id)):
            pending = order.pending_count(self.groups)
            if pending <= 0 or self._passenger_execution_id(order.id) in transport.movement_executions:
                continue
            choice = order.capacity_source_constraint
            # Unconstrained Orders intentionally use Transport Service only;
            # free Fleet is never implicitly claimed on the player's behalf.
            if choice is None or choice.dedicated_vehicle_definition_id is None:
                continue
            source_people = (self.free_count_at(order.origin_node_id)
                             if order.source_external_provider_id is None
                             else self.external_available(order.source_external_provider_id, day))
            inbound = sum(existing.transit_count(self.groups)
                          for existing in self.transfer_orders.values()
                          if existing.destination_node_id == order.destination_node_id)
            receive = self._supportable_admission(
                order.destination_node_id,
                min(pending, max(0, source_people),
                    max(0, self.housing_capacity(order.destination_node_id, day)
                        - self.count_at(order.destination_node_id) - inbound)), day,
            )
            if receive <= 0:
                continue
            option = self.dedicated_dispatch_option(
                transport, order.origin_node_id, order.destination_node_id, receive,
                choice.dedicated_vehicle_definition_id, choice.dedicated_units, day,
                choice.movement_hard_constraint,
            )
            if not option.possible_people or option.blockers:
                continue
            self._dispatch_options[order.id] = option
            needs = []
            for node, resource, amount in option.resources_for_dispatch:
                needs.append(ResourceRequirement(resource, amount, constraint_node_id=node))
            source_pool = ('passenger_external:' + order.source_external_provider_id
                           if order.source_external_provider_id is not None else 'passenger_people')
            source_scope = (str(order.origin_node_id) if order.source_external_provider_id is None
                            else order.source_external_provider_id)
            needs.append(PoolRequirement(source_pool, option.possible_people, scope_id=source_scope))
            needs.append(PoolRequirement('passenger_fleet', option.units,
                                         scope_id=f'{option.vehicle_definition_id}@{order.origin_node_id}'))
            needs.append(PoolRequirement('passenger_arrival_housing', option.possible_people,
                                         scope_id=str(order.destination_node_id)))
            bundles.append(ExecutionRequirementBundle(
                id=self._passenger_bundle_id(order.id), owner_kind='population',
                owner_id=order.id, purpose='passenger_transfer',
                operational_node_id=order.origin_node_id,
                requested_execution=1.0, priority=order.activity_priority,
                requirements=tuple(needs), atomic=True, wait_started_day=0,
            ))
        return tuple(bundles)

    def dispatch_allocated_passengers(self, allocation: ExecutionAllocationPlan, day: int) -> None:
        """Commit only flights authorized by the same Resource/Fleet allocation."""
        from .transport.models import FleetActivityRef, MovementExecutionKind, MovementExecutionPayloadResource
        transport = self.transport
        if transport is None:
            return
        for order_id, option in sorted(self._dispatch_options.items(), key=lambda row: str(row[0])):
            if allocation.allocated(self._passenger_bundle_id(order_id)) < 1 - 1e-9:
                continue
            order = self.transfer_orders[order_id]
            count = option.possible_people
            # Validation before any committed physical transfer.
            if (order.pending_count(self.groups) < count
                    or self._passenger_execution_id(order.id) in transport.movement_executions):
                raise RuntimeError('allocated passenger order changed before execution')
            if order.source_external_provider_id is not None:
                if count > self.external_available(order.source_external_provider_id, day):
                    raise RuntimeError('allocated external population quota changed')
            elif count > self.free_count_at(order.origin_node_id):
                raise RuntimeError('allocated passenger source changed')
            execution_id = self._passenger_execution_id(order_id)
            commitment_id = self._passenger_commitment_id(order_id)
            transport.commit_fleet_units(
                commitment_id, FleetActivityRef('passenger_transfer', order_id),
                option.vehicle_definition_id, order.origin_node_id, option.units,
            )
            vehicle = transport.vehicle_definition(option.vehicle_definition_id)
            days = max(1, option.latency_days)
            payload = tuple(MovementExecutionPayloadResource(resource, rate * count * days)
                            for resource, rate in vehicle.passengers.net_resources_per_person_day
                            if rate > 0)
            # The payload snapshot freezes boarding mass and onboard provisions.
            transport.start_movement_execution_for_path(
                execution_id, order_id, MovementExecutionKind.PASSENGER_TRANSFER,
                commitment_id, option.movement_path,
                payload_t_per_unit=option.payload_per_person_t * count / option.units,
                payload_resources=payload, day=day,
            )
            transport.dispatch_fleet_commitment(commitment_id, execution_id, day=day)
            for node, resource, amount in option.resources_for_dispatch:
                self.inventory.consume_allocated(node, resource, amount)
            if order.source_external_provider_id is not None:
                self._acquire_external(order.source_external_provider_id, count, day)
                self._add_uncommitted_at(order.origin_node_id, count)
            remaining = count
            for group in self.groups_at(order.origin_node_id):
                if group.activity_commitment_ref is not None:
                    continue
                boarding = self._split_group(group, min(group.count, remaining))
                self.move_group_to_execution(boarding.id, execution_id)
                order.in_transit_group_refs.append(boarding.id)
                remaining -= boarding.count
                if remaining == 0:
                    break
            if remaining:
                raise RuntimeError('committed departure lost people')
        self._dispatch_options.clear()

    def settle_transit_arrivals(self, day: int) -> None:
        """Deliver arrived people before the new day; hold aboard when full."""
        transport = self.transport
        if transport is None:
            return
        from .transport.models import MovementExecutionPayloadResource, consume_onboard_life_support
        for transit_id, transit in sorted(tuple(transport.passenger_service_transits.items()), key=lambda item: str(item[0])):
            order = self.transfer_orders[transit.order_id] if transit.order_id is not None else None
            if transit.last_settled_day < day:
                for elapsed_day in range(transit.last_settled_day + 1, day + 1):
                    passengers = sum(self.groups[group_id].count for group_id in transit.passenger_group_refs)
                    accommodation = transit.active_leg(elapsed_day).passenger_accommodation
                    fulfillment = consume_onboard_life_support(
                        accommodation, transit.onboard_resources, passengers,
                    )
                    for group_id in transit.passenger_group_refs:
                        if group_id not in self.groups:
                            continue
                        group = self.groups[group_id]
                        deaths = self._settle_group_deprivation(group, fulfillment)
                        if order is not None:
                            order.deceased_count += deaths
                        if not group.count:
                            del self.groups[group_id]
                            if order is not None:
                                order.in_transit_group_refs.remove(group_id)
                    transit.passenger_group_refs = tuple(
                        group_id for group_id in transit.passenger_group_refs if group_id in self.groups
                    )
                    transit.last_settled_day = elapsed_day
            # A vessel and its unused provisions do not disappear when the
            # last passenger dies in flight. Continue the fixed physical leg
            # until arrival; then settle the remaining onboard Resource through
            # the usual finite Inventory admission.
            if transit.arrival_day > day:
                continue
            survivors = tuple(group_id for group_id in transit.passenger_group_refs if group_id in self.groups)
            count = sum(self.groups[group_id].count for group_id in survivors)
            destination = transit.legs[-1].destination_id
            if count and self._supportable_admission(destination, count, day) < count:
                continue
            if not self.inventory.can_admit_resources(destination, transit.onboard_resources):
                continue
            for group_id in survivors:
                self.settle_arrival(group_id, destination)
                if order is not None:
                    order.in_transit_group_refs.remove(group_id)
            if order is not None:
                order.delivered_count += count
            for resource, amount in transit.onboard_resources.items():
                if amount > 1e-12:
                    self.inventory.add(destination, resource, amount)
            del transport.passenger_service_transits[transit_id]
        for order in sorted(self.transfer_orders.values(), key=lambda row: str(row.id)):
            if (order.capacity_source_constraint is None or
                    order.capacity_source_constraint.dedicated_vehicle_definition_id is None):
                continue
            execution_id = self._passenger_execution_id(order.id)
            movement = transport.movement_executions.get(execution_id)
            if movement is None:
                if order.in_transit_group_refs:
                    raise RuntimeError('in-transit people have no physical Movement')
                continue
            # Each elapsed game day is settled exactly once at its boundary.
            # Provisions are already onboard Movement-owned stock; Inventory
            # was debited once at departure and is not debited again here.
            onboard = {row.resource_id: row.amount_t for row in movement.payload_resources}
            spec = movement.passenger_accommodation
            if spec is None:
                raise RuntimeError('passenger Movement lacks frozen accommodation')
            passengers = order.transit_count(self.groups)
            ratio = consume_onboard_life_support(spec, onboard, passengers)
            movement.payload_resources = tuple(MovementExecutionPayloadResource(resource, amount)
                                               for resource, amount in sorted(onboard.items(), key=lambda row: str(row[0]))
                                               if amount > 1e-12)
            for group_id in tuple(order.in_transit_group_refs):
                group = self.groups[group_id]
                deaths = self._settle_group_deprivation(group, ratio)
                order.deceased_count += deaths
                if group.count == 0:
                    del self.groups[group_id]
                    order.in_transit_group_refs.remove(group_id)
            if movement.completion_day > day:
                continue
            count = order.transit_count(self.groups)
            if count and self._supportable_admission(order.destination_node_id, count, day) < count:
                continue  # onboard hold is real: Fleet remains unavailable
            recovery_node = (order.origin_node_id if movement.final_asset_disposition.value == 'origin'
                             else order.destination_node_id)
            if not self.inventory.can_admit_resources(recovery_node, onboard):
                continue
            for group_id in order.in_transit_group_refs:
                self.settle_arrival(group_id, order.destination_node_id)
            order.delivered_count += count
            order.in_transit_group_refs.clear()
            for resource, amount in onboard.items():
                if amount > 1e-12:
                    self.inventory.add(recovery_node, resource, amount)
            transport.receive_fleet_commitment(
                movement.fleet_commitment_id,
                order.origin_node_id if movement.final_asset_disposition.value == 'origin'
                else order.destination_node_id,
                execution_id=execution_id, day=day,
            )
            transport.finish_movement_execution(execution_id)
            transport.release_fleet_commitment(movement.fleet_commitment_id, day=day)

    def set_target(self, node_id: SpatialNodeId, count: int) -> None:
        if not self.graph.has_operational_node(node_id):
            raise ValueError('unknown population target node')
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError('population target must be a nonnegative integer')
        self.targets[node_id] = count

    def clear_target(self, node_id: SpatialNodeId) -> None:
        self.targets.pop(node_id, None)

    def groups_at(self, node_id: SpatialNodeId) -> tuple[PopulationGroup, ...]:
        return tuple(sorted((group for group in self.groups.values()
                             if group.position == PopulationPosition('operational_node', str(node_id))),
                            key=lambda group: str(group.id)))

    def count_at(self, node_id: SpatialNodeId) -> int:
        return sum(group.count for group in self.groups_at(node_id))

    def _facilities_at(self, node_id: SpatialNodeId, day: int, *, active: bool = True):
        for facility in sorted(self.facilities.all_at(node_id), key=lambda row: str(row.id)):
            if active and not self.facilities.is_active_and_compatible(facility, day):
                continue
            yield facility, self.facilities.definitions[facility.definition_id]

    def housing_capacity(self, node_id: SpatialNodeId, day: int, *, active: bool = True) -> int:
        return sum(definition.housing_capacity * facility.level
                   for facility, definition in self._facilities_at(node_id, day, active=active))

    def facility_decommission_blockers(self, facility_id: EntityId) -> tuple[FacilityLifecycleBlocker, ...]:
        facility = self.facilities.facilities.get(facility_id)
        if facility is None:
            return ()
        removed = self.facilities.definitions[facility.definition_id].housing_capacity * facility.level
        if removed == 0:
            return ()
        node_id = facility.operational_node_id
        occupied = self.count_at(node_id) + self._inbound_by_node().get(node_id, 0)
        remaining = self.housing_capacity(node_id, 0, active=False) - removed
        if occupied <= remaining:
            return ()
        return (FacilityLifecycleBlocker(
            'population_housing',
            f'occupied_people={occupied}, remaining_physical_housing={remaining}, required_extra={occupied - remaining}',
        ),)

    @staticmethod
    def _provider_bundle_id(facility_id: EntityId) -> EntityId:
        return EntityId(f'execution.life_support:{facility_id}')

    def allocation_pool_capacities(self, day: int) -> dict[AllocationConstraintKey, float]:
        capacities: dict[AllocationConstraintKey, float] = {}
        transport = self.transport
        if transport is not None:
            for node_id in sorted(self.graph.operational_node_ids(), key=str):
                capacities[pool_constraint('passenger_people', scope_id=str(node_id))] = self.free_count_at(node_id)
            for source_id in sorted(self.external_definitions):
                capacities[pool_constraint('passenger_external:' + source_id, scope_id=source_id)] = (
                    self.external_available(source_id, day)
                    if source_id in self.external_remaining else 0
                )
            inbound = self._inbound_by_node()
            for node_id in sorted(self.graph.operational_node_ids(), key=str):
                # This is one allocation's shared admission constraint, not a
                # persisted reservation against future Housing capacity.
                capacities[pool_constraint('passenger_arrival_housing', scope_id=str(node_id))] = max(
                    0, self.housing_capacity(node_id, day)
                    - self.count_at(node_id) - inbound.get(node_id, 0)
                )
                if node_id in self.targets:
                    manual_pending = sum(
                        order.pending_count(self.groups) for order in self.transfer_orders.values()
                        if order.destination_node_id == node_id
                    )
                    capacities[pool_constraint('passenger_target_gap', scope_id=str(node_id))] = max(
                        0, self.targets[node_id] - self.count_at(node_id)
                        - inbound.get(node_id, 0) - manual_pending
                    )
            for vehicle in transport.vehicle_definitions():
                for node_id in sorted(self.graph.operational_node_ids(), key=str):
                    capacities[pool_constraint('passenger_fleet', scope_id=f'{vehicle.id}@{node_id}')] = transport.fleet_free_units(vehicle.id, node_id)
        capacities.update(self.service_seat_pool_capacities(day))
        for node_id in sorted(self.graph.operational_node_ids(), key=str):
            people = self.count_at(node_id)
            capacities[pool_constraint('life_support_need', scope_id=str(node_id))] = people
            capacities[pool_constraint('housing', scope_id=str(node_id))] = self.housing_capacity(node_id, day)
            for facility, definition in self._facilities_at(node_id, day):
                if definition.life_support is not None:
                    capacities[pool_constraint('life_support_provider', scope_id=str(facility.id))] = (
                        definition.life_support.person_days_per_day * facility.level
                    )
        return capacities

    def _life_support_bundles_at(
        self, node_id: SpatialNodeId, people: int, day: int,
    ) -> tuple[ExecutionRequirementBundle, ...]:
        if not people:
            return ()
        rows: list[ExecutionRequirementBundle] = []
        for facility, definition in self._facilities_at(node_id, day):
            spec = definition.life_support
            if spec is None:
                continue
            requirements = (
                ServiceCapacityRequirement('life_support', 1),
                PoolRequirement('life_support_need', 1, scope_id=str(node_id)),
                PoolRequirement('housing', 1, scope_id=str(node_id)),
                PoolRequirement('life_support_provider', 1, scope_id=str(facility.id)),
            ) + tuple(ResourceRequirement(resource, rate) for resource, rate in spec.net_resources)
            rows.append(ExecutionRequirementBundle(
                id=self._provider_bundle_id(facility.id),
                owner_kind='population', owner_id=facility.id,
                purpose='life_support', operational_node_id=node_id,
                requested_execution=min(people, spec.person_days_per_day * facility.level),
                priority=ActivityPriority(5), requirements=requirements,
            ))
        return tuple(rows)

    def execution_requirement_bundles(self, day: int) -> tuple[ExecutionRequirementBundle, ...]:
        return tuple(
            bundle
            for node_id in sorted(self.graph.operational_node_ids(), key=str)
            for bundle in self._life_support_bundles_at(node_id, self.count_at(node_id), day)
        )

    def supplys(self, day: int, *, node_id: SpatialNodeId | None = None) -> tuple[SupplyRequirement, ...]:
        rows: list[SupplyRequirement] = []
        nodes = (node_id,) if node_id is not None else sorted(self.graph.operational_node_ids(), key=str)
        for current_id in nodes:
            people = self.count_at(current_id)
            if not people:
                continue
            providers = [
                (facility, definition.life_support)
                for facility, definition in self._facilities_at(current_id, day)
                if definition.life_support is not None
            ]
            total_capacity = sum(spec.person_days_per_day * facility.level for facility, spec in providers)
            if not total_capacity:
                continue
            # One need pool is shared across all providers. Forecast its total
            # instead of counting each provider as another full population.
            ratio = min(1.0, people / total_capacity)
            for facility, spec in providers:
                demand = spec.person_days_per_day * facility.level * ratio
                for resource, rate in spec.net_resources:
                    rows.append(SupplyRequirement(
                        id=EntityId(f'supply.population:{facility.id}:{resource}'),
                        owner_kind='population', owner_id=facility.id,
                        destination_id=current_id, resource_id=resource,
                        amount_t=demand * rate, priority=ActivityPriority(5),
                        recurring_rate_t_per_day=demand * rate,
                    ))
        return tuple(rows)

    def consume_allocated(self, execution: ExecutionAllocationPlan, day: int) -> None:
        by_node: dict[SpatialNodeId, float] = {}
        for node_id in sorted(self.graph.operational_node_ids(), key=str):
            for facility, definition in self._facilities_at(node_id, day):
                spec = definition.life_support
                if spec is None:
                    continue
                try:
                    amount = execution.allocated(self._provider_bundle_id(facility.id))
                except KeyError:
                    amount = 0.0
                by_node[node_id] = by_node.get(node_id, 0.0) + amount
                for resource, rate in spec.net_resources:
                    self.inventory.consume_allocated(node_id, resource, amount * rate)
        self._day_fulfillment = by_node

    def settle_deprivation(self) -> None:
        for node_id in sorted(self.graph.operational_node_ids(), key=str):
            count = self.count_at(node_id)
            if not count:
                continue
            ratio = max(0.0, min(1.0, self._day_fulfillment.get(node_id, 0.0) / count))
            for group in self.groups_at(node_id):
                self._settle_group_deprivation(group, ratio)
                if not group.count:
                    del self.groups[group.id]
        self._day_fulfillment.clear()

    def _settle_group_deprivation(self, group: PopulationGroup, ratio: float) -> int:
        group.deprivation = max(0.0, group.deprivation + 1 - ratio - self.rules.recovery_rate * ratio)
        credit = group.mortality_remainder + group.count * self.rules.mortality_rate * max(
            0.0, group.deprivation - self.rules.lethal_threshold
        )
        deaths = min(group.count, math.floor(credit))
        group.count -= deaths
        if group.count:
            group.mortality_remainder = credit - math.floor(credit)
        return deaths

    def crew_factor(self, group: PopulationGroup) -> float:
        return max(0.0, min(1.0, 1 - group.deprivation / self.rules.incapacitation_threshold))

    def validate(self) -> None:
        if set(self.external_remaining) != set(self.external_definitions):
            raise ValueError('population external provider state does not match definitions')
        for identifier, remaining in self.external_remaining.items():
            if isinstance(remaining, bool) or not isinstance(remaining, int) or not 0 <= remaining <= self.external_definitions[identifier].initial_people:
                raise ValueError('invalid external population remaining')
        if isinstance(self.external_acquisition_day, bool) or not isinstance(self.external_acquisition_day, int) or self.external_acquisition_day < -1:
            raise ValueError('invalid external acquisition day')
        for identifier, acquired in self.external_acquired_today.items():
            if identifier not in self.external_definitions or isinstance(acquired, bool) or not isinstance(acquired, int) or acquired < 0:
                raise ValueError('invalid daily external acquisition')
            if acquired > self.external_definitions[identifier].max_acquisition_per_day:
                raise ValueError('external acquisition exceeds daily quota')
        if self.external_acquisition_day == -1 and self.external_acquired_today:
            raise ValueError('external acquisition counts without a day')
        for source in self.external_definitions.values():
            if not self.graph.has_operational_node(source.operational_node_id):
                raise ValueError('external provider location missing')
        for group in self.groups.values():
            group.__post_init__()
            if group.position.kind == 'operational_node' and not self.graph.has_operational_node(SpatialNodeId(group.position.ref)):
                raise ValueError('population node missing')
        for node_id, count in self.targets.items():
            if not self.graph.has_operational_node(node_id) or isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError('invalid population target')
        if self._next_transfer_order_id < 0:
            raise ValueError('invalid transfer order counter')
        seen: set[EntityId] = set()
        for order in self.transfer_orders.values():
            order.__post_init__()
            if not self.graph.has_operational_node(order.origin_node_id) or not self.graph.has_operational_node(order.destination_node_id):
                raise ValueError('passenger transfer node missing')
            if order.source_external_provider_id is not None:
                source = self.external_definitions.get(order.source_external_provider_id)
                if source is None or source.operational_node_id != order.origin_node_id:
                    raise ValueError('passenger transfer provider mismatch')
            for group_id in order.in_transit_group_refs:
                if group_id in seen or group_id not in self.groups:
                    raise ValueError('invalid or duplicate passenger group ownership')
                seen.add(group_id)
                if self.groups[group_id].position.kind != 'transport_execution':
                    raise ValueError('passenger transit group has no transport position')
            if order.pending_count(self.groups) < 0:
                raise ValueError('passenger transfer exceeds requested count')

from __future__ import annotations

from dataclasses import dataclass, field
import math

from .execution_requirements import (
    AllocationConstraintKey, ExecutionAllocationPlan, ExecutionRequirementBundle,
    PoolRequirement, ResourceRequirement, ServiceCapacityRequirement, pool_constraint,
)
from .facilities import FacilityBook
from .facility_lifecycle import FacilityLifecycleBlocker
from .inventory import InventoryBook
from .priority import ActivityPriority
from .shared import DefinitionId, EntityId, SpatialNodeId
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


@dataclass
class PopulationService:
    facilities: FacilityBook
    inventory: InventoryBook
    graph: SpatialGraph
    rules: PopulationRules
    external_definitions: dict[str, ExternalPopulationSourceDefinition]
    groups: dict[EntityId, PopulationGroup] = field(default_factory=dict)
    targets: dict[SpatialNodeId, int] = field(default_factory=dict)
    external_remaining: dict[str, int] = field(default_factory=dict)
    _next_group_id: int = 0
    _day_fulfillment: dict[SpatialNodeId, float] = field(default_factory=dict, repr=False)

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
        occupied = self.count_at(node_id)
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

    def execution_requirement_bundles(self, day: int) -> tuple[ExecutionRequirementBundle, ...]:
        rows: list[ExecutionRequirementBundle] = []
        for node_id in sorted(self.graph.operational_node_ids(), key=str):
            people = self.count_at(node_id)
            if not people:
                continue
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
                group.deprivation = max(0.0, group.deprivation + 1 - ratio - self.rules.recovery_rate * ratio)
                credit = group.mortality_remainder + group.count * self.rules.mortality_rate * max(
                    0.0, group.deprivation - self.rules.lethal_threshold
                )
                deaths = min(group.count, math.floor(credit))
                group.count -= deaths
                if group.count:
                    group.mortality_remainder = credit - math.floor(credit)
                else:
                    del self.groups[group.id]
        self._day_fulfillment.clear()

    def crew_factor(self, group: PopulationGroup) -> float:
        return max(0.0, min(1.0, 1 - group.deprivation / self.rules.incapacitation_threshold))

    def validate(self) -> None:
        if set(self.external_remaining) != set(self.external_definitions):
            raise ValueError('population external provider state does not match definitions')
        for identifier, remaining in self.external_remaining.items():
            if isinstance(remaining, bool) or not isinstance(remaining, int) or not 0 <= remaining <= self.external_definitions[identifier].initial_people:
                raise ValueError('invalid external population remaining')
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

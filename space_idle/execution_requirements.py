from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, TypeAlias

from .priority import ActivityPriority
from .shared import DefinitionId, EntityId, SpatialNodeId
from .service_capacity import ServiceCapacityScope

_EPS = 1e-12


@dataclass(frozen=True, order=True)
class AllocationConstraintKey:
    """Identity of one finite allocation constraint.

    ``scope_id`` deliberately does not assume an Operational Node. Physical
    Resource / Service / Admission constraints use ``node:<id>`` while shared
    organization or owner pools use their owning scope.
    """

    kind: str
    scope_id: str
    name: str

    def __post_init__(self) -> None:
        if not self.kind or not self.scope_id or not self.name:
            raise ValueError("allocation constraint key fields must not be empty")


@dataclass(frozen=True)
class ResourceRequirement:
    resource_id: DefinitionId
    amount_per_execution: float
    constraint_node_id: SpatialNodeId | None = None

    def __post_init__(self) -> None:
        if self.amount_per_execution < -_EPS:
            raise ValueError("resource requirement must be non-negative")

    def constraint_node(self, operational_node_id: SpatialNodeId | None) -> SpatialNodeId:
        node_id = operational_node_id if self.constraint_node_id is None else self.constraint_node_id
        if node_id is None:
            raise ValueError("resource requirement requires an Operational Node scope")
        return node_id

    def constraint_key(self, operational_node_id: SpatialNodeId | None) -> AllocationConstraintKey:
        return resource_constraint(self.constraint_node(operational_node_id), self.resource_id)


@dataclass(frozen=True)
class ServiceCapacityRequirement:
    service_type: str
    amount_per_execution: float
    constraint_node_id: SpatialNodeId | None = None
    scope: ServiceCapacityScope = ServiceCapacityScope.OPERATIONAL_NODE
    scope_id: str = "organization"

    def __post_init__(self) -> None:
        if not self.service_type or not self.scope_id:
            raise ValueError("service type and scope id must not be empty")
        if self.amount_per_execution < -_EPS:
            raise ValueError("service requirement must be non-negative")
        if not isinstance(self.scope, ServiceCapacityScope):
            raise ValueError("service requirement scope must be a ServiceCapacityScope")
        if self.scope is ServiceCapacityScope.ORGANIZATION and self.constraint_node_id is not None:
            raise ValueError("organization service requirement cannot pin a provider node")

    def constraint_node(self, operational_node_id: SpatialNodeId | None) -> SpatialNodeId:
        if self.scope is ServiceCapacityScope.ORGANIZATION:
            raise ValueError("organization service requirement has no Operational Node constraint")
        node_id = operational_node_id if self.constraint_node_id is None else self.constraint_node_id
        if node_id is None:
            raise ValueError("node-scoped service requirement requires an Operational Node")
        return node_id

    def constraint_key(self, operational_node_id: SpatialNodeId | None) -> AllocationConstraintKey:
        if self.scope is ServiceCapacityScope.ORGANIZATION:
            return service_pool_constraint(self.service_type, self.scope_id)
        return service_constraint(self.constraint_node(operational_node_id), self.service_type)

    def constraint_keys(self, operational_node_id: SpatialNodeId | None) -> tuple[AllocationConstraintKey, ...]:
        if self.scope is ServiceCapacityScope.ORGANIZATION:
            return (service_pool_constraint(self.service_type, self.scope_id),)
        return (service_constraint(self.constraint_node(operational_node_id), self.service_type),)


@dataclass(frozen=True)
class PoolRequirement:
    pool_id: str
    amount_per_execution: float
    scope_id: str = "organization"

    def __post_init__(self) -> None:
        if not self.pool_id or not self.scope_id:
            raise ValueError("pool identity must not be empty")
        if self.amount_per_execution < -_EPS:
            raise ValueError("pool requirement must be non-negative")

    def constraint_key(self, operational_node_id: SpatialNodeId | None) -> AllocationConstraintKey:
        del operational_node_id
        return pool_constraint(self.pool_id, scope_id=self.scope_id)




@dataclass(frozen=True)
class PoolAdmissionRequirement:
    pool_id: str
    amount_per_execution: float
    scope_id: str = "organization"

    def __post_init__(self) -> None:
        if not self.pool_id or not self.scope_id:
            raise ValueError("pool admission identity must not be empty")
        if self.amount_per_execution < -_EPS:
            raise ValueError("pool admission requirement must be non-negative")

    def constraint_key(self, operational_node_id: SpatialNodeId | None) -> AllocationConstraintKey:
        del operational_node_id
        return pool_admission_constraint(self.pool_id, scope_id=self.scope_id)


@dataclass(frozen=True)
class StockOrPoolAdmissionRequirement:
    pool_id: str
    amount_per_execution: float

    def __post_init__(self) -> None:
        if not self.pool_id:
            raise ValueError("admission pool id must not be empty")
        if self.amount_per_execution < -_EPS:
            raise ValueError("admission requirement must be non-negative")

    def constraint_key(self, operational_node_id: SpatialNodeId | None) -> AllocationConstraintKey:
        if operational_node_id is None:
            raise ValueError("stock/admission requirement requires an Operational Node scope")
        return admission_constraint(operational_node_id, self.pool_id)


ExecutionRequirement: TypeAlias = (
    ResourceRequirement
    | ServiceCapacityRequirement
    | PoolRequirement
    | PoolAdmissionRequirement
    | StockOrPoolAdmissionRequirement
)


@dataclass(frozen=True)
class ExecutionRequirementBundle:
    id: EntityId
    owner_kind: str
    owner_id: EntityId
    purpose: str
    operational_node_id: SpatialNodeId | None
    requested_execution: float
    priority: ActivityPriority
    requirements: tuple[ExecutionRequirement, ...] = ()
    minimum_execution: float = 0.0
    atomic: bool = False
    wait_started_day: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "priority", ActivityPriority(self.priority))
        object.__setattr__(self, "requirements", tuple(self.requirements))
        if not self.owner_kind or not self.purpose:
            raise ValueError("bundle owner kind and purpose must not be empty")
        if self.requested_execution < -_EPS:
            raise ValueError("requested execution must be non-negative")
        if self.minimum_execution < -_EPS:
            raise ValueError("minimum execution must be non-negative")
        if self.minimum_execution > self.requested_execution + _EPS:
            raise ValueError("minimum execution cannot exceed requested execution")
        if self.atomic and self.minimum_execution not in (0.0, self.requested_execution):
            raise ValueError("atomic bundle minimum must be zero or full request")
        if self.effective_minimum_execution > _EPS and self.wait_started_day is None:
            raise ValueError("minimum/atomic bundle requires persistent wait_started_day")
        if self.wait_started_day is not None and self.wait_started_day < 0:
            raise ValueError("wait_started_day must be non-negative")
        seen: set[AllocationConstraintKey] = set()
        for requirement in self.requirements:
            keys = (
                requirement.constraint_keys(self.operational_node_id)
                if isinstance(requirement, ServiceCapacityRequirement)
                else (requirement.constraint_key(self.operational_node_id),)
            )
            for key in keys:
                if key in seen:
                    raise ValueError(f"duplicate requirement constraint in bundle: {key}")
                seen.add(key)

    @property
    def effective_minimum_execution(self) -> float:
        return self.requested_execution if self.atomic else self.minimum_execution

    def coefficients(self) -> tuple[tuple[AllocationConstraintKey, float], ...]:
        rows: list[tuple[AllocationConstraintKey, float]] = []
        for requirement in self.requirements:
            if requirement.amount_per_execution <= _EPS:
                continue
            keys = (
                requirement.constraint_keys(self.operational_node_id)
                if isinstance(requirement, ServiceCapacityRequirement)
                else (requirement.constraint_key(self.operational_node_id),)
            )
            rows.extend((key, requirement.amount_per_execution) for key in keys)
        return tuple(rows)


@dataclass(frozen=True)
class ReservationAcquisitionRequirement:
    id: EntityId
    owner_id: EntityId
    operational_node_id: SpatialNodeId
    resource_id: DefinitionId
    requested_amount: float
    priority: ActivityPriority
    purpose: str = "reservation_acquisition"

    def __post_init__(self) -> None:
        object.__setattr__(self, "priority", ActivityPriority(self.priority))
        if self.requested_amount < -_EPS:
            raise ValueError("reservation acquisition amount must be non-negative")
        if not self.purpose:
            raise ValueError("reservation acquisition purpose must not be empty")

    def as_bundle(self) -> ExecutionRequirementBundle:
        return ExecutionRequirementBundle(
            id=self.id,
            owner_kind="reservation",
            owner_id=self.owner_id,
            purpose=self.purpose,
            operational_node_id=self.operational_node_id,
            requested_execution=self.requested_amount,
            priority=self.priority,
            requirements=(ResourceRequirement(self.resource_id, 1.0),),
        )


AllocationIntent: TypeAlias = ExecutionRequirementBundle | ReservationAcquisitionRequirement


def with_service_capacity_conservation(
    bundle: ExecutionRequirementBundle,
    service_scopes: Mapping[str, ServiceCapacityScope],
) -> ExecutionRequirementBundle:
    """Add shared supply conservation constraints without changing consumer scope.

    A node-scoped consumer of an organization-scoped service still consumes the
    physically local provider flow and the organization aggregate formed from
    that same finite supply.  The extra organization constraint therefore
    conserves supply across local and organization consumers; it does not change
    the consumer's execution site.
    """
    requirements = list(bundle.requirements)
    existing_organization_services = {
        requirement.service_type
        for requirement in requirements
        if isinstance(requirement, ServiceCapacityRequirement)
        and requirement.scope is ServiceCapacityScope.ORGANIZATION
    }
    for requirement in tuple(requirements):
        if not isinstance(requirement, ServiceCapacityRequirement):
            continue
        if requirement.scope is not ServiceCapacityScope.OPERATIONAL_NODE:
            continue
        if requirement.service_type in existing_organization_services:
            continue
        if service_scopes.get(requirement.service_type) is not ServiceCapacityScope.ORGANIZATION:
            continue
        requirements.append(
            ServiceCapacityRequirement(
                requirement.service_type,
                requirement.amount_per_execution,
                scope=ServiceCapacityScope.ORGANIZATION,
            )
        )
        existing_organization_services.add(requirement.service_type)
    if tuple(requirements) == bundle.requirements:
        return bundle
    return ExecutionRequirementBundle(
        bundle.id,
        bundle.owner_kind,
        bundle.owner_id,
        bundle.purpose,
        bundle.operational_node_id,
        bundle.requested_execution,
        bundle.priority,
        tuple(requirements),
        minimum_execution=bundle.minimum_execution,
        atomic=bundle.atomic,
        wait_started_day=bundle.wait_started_day,
    )


@dataclass(frozen=True)
class ExecutionAllocation:
    bundle_id: EntityId
    requested_execution: float
    allocated_execution: float
    limiting_constraints: tuple[AllocationConstraintKey, ...] = ()

    def __post_init__(self) -> None:
        if self.requested_execution < -_EPS or self.allocated_execution < -_EPS:
            raise ValueError("execution allocation must be non-negative")
        if self.allocated_execution > self.requested_execution + 1e-8:
            raise ValueError("allocated execution cannot exceed requested execution")

    @property
    def unmet_execution(self) -> float:
        return max(0.0, self.requested_execution - self.allocated_execution)

    @property
    def fulfillment(self) -> float:
        if self.requested_execution <= _EPS:
            return 1.0
        return min(1.0, max(0.0, self.allocated_execution / self.requested_execution))


@dataclass(frozen=True)
class ExecutionAllocationPlan:
    bundles: tuple[ExecutionRequirementBundle, ...]
    allocations: tuple[ExecutionAllocation, ...]
    capacity_by_constraint: Mapping[AllocationConstraintKey, float]
    used_by_constraint: Mapping[AllocationConstraintKey, float]

    def __post_init__(self) -> None:
        bundle_ids = [bundle.id for bundle in self.bundles]
        allocation_ids = [allocation.bundle_id for allocation in self.allocations]
        if len(set(bundle_ids)) != len(bundle_ids):
            raise ValueError("duplicate execution bundle id")
        if set(bundle_ids) != set(allocation_ids) or len(bundle_ids) != len(allocation_ids):
            raise ValueError("execution plan must contain exactly one allocation per bundle")
        for key, capacity in self.capacity_by_constraint.items():
            if capacity < -_EPS:
                raise ValueError(f"negative allocation capacity: {key}")
            used = self.used_by_constraint.get(key, 0.0)
            if used < -_EPS or used > capacity + 1e-7:
                raise ValueError(f"allocation usage exceeds capacity: {key}")

    @classmethod
    def empty(cls) -> "ExecutionAllocationPlan":
        return cls((), (), {}, {})

    def bundle(self, bundle_id: EntityId) -> ExecutionRequirementBundle:
        for bundle in self.bundles:
            if bundle.id == bundle_id:
                return bundle
        raise KeyError(bundle_id)

    def allocation(self, bundle_id: EntityId) -> ExecutionAllocation:
        for allocation in self.allocations:
            if allocation.bundle_id == bundle_id:
                return allocation
        raise KeyError(bundle_id)

    def allocated(self, bundle_id: EntityId) -> float:
        return self.allocation(bundle_id).allocated_execution

    def fulfillment(self, bundle_id: EntityId) -> float:
        return self.allocation(bundle_id).fulfillment

    def allocations_for_owner(self, owner_kind: str, owner_id: EntityId) -> tuple[ExecutionAllocation, ...]:
        ids = {
            bundle.id
            for bundle in self.bundles
            if bundle.owner_kind == owner_kind and bundle.owner_id == owner_id
        }
        return tuple(row for row in self.allocations if row.bundle_id in ids)


def resource_constraint(node_id: SpatialNodeId, resource_id: DefinitionId) -> AllocationConstraintKey:
    return AllocationConstraintKey("resource", f"node:{node_id}", str(resource_id))


def service_constraint(node_id: SpatialNodeId, service_type: str) -> AllocationConstraintKey:
    return AllocationConstraintKey("service", f"node:{node_id}", service_type)


def service_pool_constraint(service_type: str, scope_id: str = "organization") -> AllocationConstraintKey:
    return AllocationConstraintKey("service_pool", scope_id, service_type)


def pool_admission_constraint(pool_id: str, *, scope_id: str = "organization") -> AllocationConstraintKey:
    return AllocationConstraintKey("pool_admission", scope_id, pool_id)


def admission_constraint(node_id: SpatialNodeId, pool_id: str) -> AllocationConstraintKey:
    return AllocationConstraintKey("admission", f"node:{node_id}", pool_id)


def pool_constraint(pool_id: str, scope_id: str = "organization") -> AllocationConstraintKey:
    return AllocationConstraintKey("pool", scope_id, pool_id)


def _bundle_order_key(bundle: ExecutionRequirementBundle) -> tuple[str, str, str, str, str]:
    return (
        bundle.owner_kind,
        str(bundle.owner_id),
        bundle.purpose,
        str(bundle.operational_node_id),
        str(bundle.id),
    )


def _fairness_key(bundle: ExecutionRequirementBundle) -> tuple[int, tuple[str, str, str, str, str]]:
    # Required for every threshold bundle by validation above.
    return (bundle.wait_started_day if bundle.wait_started_day is not None else 2**63 - 1, _bundle_order_key(bundle))


def _fits(
    bundle: ExecutionRequirementBundle,
    execution: float,
    remaining: Mapping[AllocationConstraintKey, float],
) -> bool:
    for key, coefficient in bundle.coefficients():
        if coefficient * execution > remaining.get(key, 0.0) + _EPS:
            return False
    return True


def _consume(
    bundle: ExecutionRequirementBundle,
    execution: float,
    remaining: dict[AllocationConstraintKey, float],
    used: dict[AllocationConstraintKey, float],
) -> None:
    if execution <= _EPS:
        return
    for key, coefficient in bundle.coefficients():
        amount = coefficient * execution
        remaining[key] = max(0.0, remaining.get(key, 0.0) - amount)
        used[key] = used.get(key, 0.0) + amount


def _progressive_allocate_band(
    bundles: tuple[ExecutionRequirementBundle, ...],
    remaining: dict[AllocationConstraintKey, float],
    used: dict[AllocationConstraintKey, float],
) -> tuple[dict[EntityId, float], dict[EntityId, set[AllocationConstraintKey]]]:
    allocated = {bundle.id: 0.0 for bundle in bundles}
    limiting: dict[EntityId, set[AllocationConstraintKey]] = {bundle.id: set() for bundle in bundles}

    # minimum / atomic admission uses persistent fairness age + stable semantic key.
    threshold = tuple(
        sorted(
            (bundle for bundle in bundles if bundle.effective_minimum_execution > _EPS),
            key=_fairness_key,
        )
    )
    rejected: set[EntityId] = set()
    for bundle in threshold:
        amount = bundle.effective_minimum_execution
        if _fits(bundle, amount, remaining):
            allocated[bundle.id] = amount
            _consume(bundle, amount, remaining, used)
        else:
            rejected.add(bundle.id)
            for key, coefficient in bundle.coefficients():
                if coefficient * amount > remaining.get(key, 0.0) + _EPS:
                    limiting[bundle.id].add(key)

    continuous = tuple(
        bundle
        for bundle in bundles
        if not bundle.atomic and bundle.id not in rejected and bundle.requested_execution > _EPS
    )
    frozen: set[EntityId] = set()

    while True:
        candidates = [
            bundle
            for bundle in continuous
            if bundle.id not in frozen
            and allocated[bundle.id] < bundle.requested_execution - _EPS
        ]
        if not candidates:
            break

        min_fulfillment = min(allocated[b.id] / b.requested_execution for b in candidates)
        active = [
            b
            for b in candidates
            if allocated[b.id] / b.requested_execution <= min_fulfillment + 1e-11
        ]
        higher_levels = [
            allocated[b.id] / b.requested_execution
            for b in candidates
            if allocated[b.id] / b.requested_execution > min_fulfillment + 1e-11
        ]
        delta = 1.0 - min_fulfillment
        if higher_levels:
            delta = min(delta, min(higher_levels) - min_fulfillment)

        usage_rate: dict[AllocationConstraintKey, float] = {}
        for bundle in active:
            for key, coefficient in bundle.coefficients():
                usage_rate[key] = usage_rate.get(key, 0.0) + coefficient * bundle.requested_execution
        saturated_now: set[AllocationConstraintKey] = set()
        for key, rate in usage_rate.items():
            if rate <= _EPS:
                continue
            cap_delta = remaining.get(key, 0.0) / rate
            if cap_delta < delta:
                delta = max(0.0, cap_delta)
        if delta <= _EPS:
            for key, rate in usage_rate.items():
                if rate > _EPS and remaining.get(key, 0.0) <= 1e-10:
                    saturated_now.add(key)
            if not saturated_now:
                # Numeric dead-end: freeze the current lowest layer rather than loop.
                frozen.update(bundle.id for bundle in active)
            else:
                for bundle in active:
                    bundle_keys = {key for key, _ in bundle.coefficients()}
                    hits = bundle_keys & saturated_now
                    if hits:
                        limiting[bundle.id].update(hits)
                        frozen.add(bundle.id)
            continue

        for bundle in active:
            increment = bundle.requested_execution * delta
            allocated[bundle.id] += increment
            _consume(bundle, increment, remaining, used)

        # Any constraint exhausted by this increment freezes only bundles that
        # depend on it. Other bundles continue with residual capacities.
        for key, rate in usage_rate.items():
            if rate > _EPS and remaining.get(key, 0.0) <= 1e-10:
                saturated_now.add(key)
        if saturated_now:
            for bundle in active:
                hits = {key for key, _ in bundle.coefficients()} & saturated_now
                if hits and allocated[bundle.id] < bundle.requested_execution - _EPS:
                    limiting[bundle.id].update(hits)
                    frozen.add(bundle.id)

    return allocated, limiting


def allocate_execution_requirements(
    intents: Iterable[AllocationIntent],
    capacity_by_constraint: Mapping[AllocationConstraintKey, float],
) -> ExecutionAllocationPlan:
    bundles = tuple(
        intent.as_bundle() if isinstance(intent, ReservationAcquisitionRequirement) else intent
        for intent in intents
    )
    ids = [bundle.id for bundle in bundles]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate execution bundle id")

    capacities = {key: float(value) for key, value in capacity_by_constraint.items()}
    if any(value < -_EPS for value in capacities.values()):
        raise ValueError("allocation capacities must be non-negative")
    required_keys = {key for bundle in bundles for key, _ in bundle.coefficients()}
    missing = required_keys - capacities.keys()
    if missing:
        raise KeyError(f"missing allocation capacities: {sorted(missing)}")

    remaining = {key: max(0.0, value) for key, value in capacities.items()}
    used: dict[AllocationConstraintKey, float] = {key: 0.0 for key in capacities}
    amounts: dict[EntityId, float] = {bundle.id: 0.0 for bundle in bundles}
    limiting: dict[EntityId, set[AllocationConstraintKey]] = {bundle.id: set() for bundle in bundles}

    by_priority: dict[int, list[ExecutionRequirementBundle]] = {}
    for bundle in bundles:
        by_priority.setdefault(int(bundle.priority), []).append(bundle)
    for priority in sorted(by_priority, reverse=True):
        band = tuple(sorted(by_priority[priority], key=_bundle_order_key))
        band_amounts, band_limiting = _progressive_allocate_band(band, remaining, used)
        amounts.update(band_amounts)
        for bundle_id, keys in band_limiting.items():
            limiting[bundle_id].update(keys)

    ordered = tuple(sorted(bundles, key=lambda b: (-int(b.priority), _bundle_order_key(b))))
    allocations = tuple(
        ExecutionAllocation(
            bundle.id,
            bundle.requested_execution,
            min(bundle.requested_execution, max(0.0, amounts[bundle.id])),
            tuple(sorted(limiting[bundle.id])),
        )
        for bundle in ordered
    )
    return ExecutionAllocationPlan(ordered, allocations, capacities, used)

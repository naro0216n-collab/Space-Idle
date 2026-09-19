from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from .priority import ActivityPriority
from .shared import DefinitionId, EntityId, MovementPlanId, SpatialNodeId
from .supply import (
    SupplyRequirement,
    SupplyRoutingConstraintScope,
    SupplyRoutingConstraintState,
    TargetStockPolicy,
)


@dataclass(frozen=True)
class SupplyPlanningOptions:
    """Derived sourcing/path options for one Supply Requirement."""

    candidate_source_ids: tuple[SpatialNodeId, ...]
    operational_source_ids: tuple[SpatialNodeId, ...]
    stocked_source_ids: tuple[SpatialNodeId, ...]
    path_candidates: tuple[tuple[SpatialNodeId, tuple[MovementPlanId, ...]], ...]
    blockers: tuple[str, ...]
    earliest_confirmed_arrival_day: int | None
    selected_source_id: SpatialNodeId | None = None
    selected_service_ids: tuple[str, ...] = ()
    selected_movement_plan_ids: tuple[MovementPlanId, ...] = ()
    projected_arrival_day: int | None = None
    selected_latency_days: float | None = None
    selected_propellant_t_per_t: float | None = None
    selected_handoff_count: int | None = None
    selected_bottleneck_capacity_t_per_day: float | None = None
    physical_movement_plan_ids: tuple[MovementPlanId, ...] = ()


class SupplyPlanningMixin:
    """Target Stock intent and sparse hard routing constraints."""

    @staticmethod
    def _target_stock_id(
        destination_id: SpatialNodeId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"target_stock:{destination_id}:{resource_id}")

    def set_target_stock(
        self,
        destination_id: SpatialNodeId,
        resource_id: DefinitionId,
        target_quantity_t: float,
        priority: ActivityPriority,
    ) -> EntityId:
        if not self.facilities.environment.graph.has_operational_node(destination_id):
            raise KeyError(destination_id)
        if resource_id not in self.inventory.resource_definitions:
            raise KeyError(resource_id)
        target_stock_id = self._target_stock_id(destination_id, resource_id)
        self.target_stocks[target_stock_id] = TargetStockPolicy(
            target_stock_id,
            destination_id,
            resource_id,
            target_quantity_t,
            priority,
        )
        return target_stock_id

    def delete_target_stock(
        self, destination_id: SpatialNodeId, resource_id: DefinitionId
    ) -> None:
        target_stock_id = self._target_stock_id(destination_id, resource_id)
        if target_stock_id not in self.target_stocks:
            raise KeyError(target_stock_id)
        del self.target_stocks[target_stock_id]
        self.routing_constraints = {
            scope: row
            for scope, row in self.routing_constraints.items()
            if not (
                scope.owner_kind == "target_stock" and scope.owner_id == target_stock_id
            )
        }

    def target_stock_policies(self) -> tuple[TargetStockPolicy, ...]:
        return tuple(
            replace(row)
            for row in sorted(self.target_stocks.values(), key=lambda row: str(row.id))
        )

    def target_stock_requirements(self, day: int) -> tuple[SupplyRequirement, ...]:
        return tuple(
            policy.requirement(day)
            for policy in sorted(self.target_stocks.values(), key=lambda row: str(row.id))
            if policy.target_quantity_t > 1e-12
        )

    def register_supply_owner_resolver(
        self, owner_kind: str, resolver: Callable[[EntityId], bool]
    ) -> None:
        if not owner_kind:
            raise ValueError("supply owner kind must be non-empty")
        if owner_kind in self._supply_owner_resolvers:
            raise ValueError(f"supply owner resolver already registered: {owner_kind}")
        self._supply_owner_resolvers[owner_kind] = resolver

    def supply_owner_exists(self, owner_kind: str, owner_id: EntityId) -> bool:
        resolver = self._supply_owner_resolvers.get(owner_kind)
        return False if resolver is None else bool(resolver(owner_id))

    @staticmethod
    def _scopes_overlap(
        left: SupplyRoutingConstraintScope, right: SupplyRoutingConstraintScope
    ) -> bool:
        if left.destination_id != right.destination_id:
            return False
        if (
            left.resource_id is not None
            and right.resource_id is not None
            and left.resource_id != right.resource_id
        ):
            return False
        if left.owner_kind is None or right.owner_kind is None:
            return True
        return left.owner_kind == right.owner_kind and left.owner_id == right.owner_id

    @staticmethod
    def _constraint_sort_key(row: SupplyRoutingConstraintState) -> tuple[str, ...]:
        scope = row.scope
        return (
            str(scope.destination_id),
            "" if scope.owner_kind is None else scope.owner_kind,
            "" if scope.owner_id is None else str(scope.owner_id),
            "" if scope.resource_id is None else str(scope.resource_id),
        )

    def _validate_routing_constraint_references(
        self, constraint: SupplyRoutingConstraintState
    ) -> None:
        scope = constraint.scope
        graph = self.facilities.environment.graph
        if not graph.has_operational_node(scope.destination_id):
            raise KeyError(scope.destination_id)
        if scope.resource_id is not None and scope.resource_id not in self.inventory.resource_definitions:
            raise KeyError(scope.resource_id)
        if scope.owner_kind is not None and not self.supply_owner_exists(
            scope.owner_kind, scope.owner_id
        ):
            raise KeyError(f"unknown supply owner: {scope.owner_kind}:{scope.owner_id}")
        if constraint.source_node_id is not None and not graph.has_operational_node(
            constraint.source_node_id
        ):
            raise KeyError(constraint.source_node_id)
        for node_id in constraint.required_via_node_ids:
            if not graph.has_operational_node(node_id):
                raise KeyError(node_id)
            if node_id == scope.destination_id:
                raise ValueError("routing constraint destination cannot also be a required via node")
        for allocation_id in constraint.required_transport_allocation_ids:
            if self.transport.transport_allocation_snapshot(allocation_id) is None:
                raise KeyError(allocation_id)

    def set_supply_routing_constraint(
        self,
        scope: SupplyRoutingConstraintScope,
        *,
        source_node_id: SpatialNodeId | None = None,
        required_via_node_ids: tuple[SpatialNodeId, ...] = (),
        required_transport_allocation_ids: tuple[EntityId, ...] = (),
    ) -> None:
        constraint = SupplyRoutingConstraintState(
            scope=scope,
            source_node_id=source_node_id,
            required_via_node_ids=required_via_node_ids,
            required_transport_allocation_ids=required_transport_allocation_ids,
        )
        self._validate_routing_constraint_references(constraint)
        for existing_scope, existing in self.routing_constraints.items():
            if existing_scope == scope or not self._scopes_overlap(existing_scope, scope):
                continue
            if (
                existing.source_node_id is not None
                and constraint.source_node_id is not None
                and existing.source_node_id != constraint.source_node_id
            ):
                raise ValueError("overlapping routing constraints require conflicting source nodes")
        self.routing_constraints[scope] = constraint

    def clear_supply_routing_constraint(self, scope: SupplyRoutingConstraintScope) -> None:
        self.routing_constraints.pop(scope, None)

    def routing_constraint_rows(self) -> tuple[SupplyRoutingConstraintState, ...]:
        return tuple(
            replace(row)
            for row in sorted(self.routing_constraints.values(), key=self._constraint_sort_key)
        )

    def exact_routing_constraint_for(
        self, scope: SupplyRoutingConstraintScope
    ) -> SupplyRoutingConstraintState | None:
        row = self.routing_constraints.get(scope)
        return None if row is None else replace(row)

    def routing_constraint_for(
        self, requirement: SupplyRequirement
    ) -> SupplyRoutingConstraintState | None:
        rows = tuple(
            row
            for row in self.routing_constraints.values()
            if row.scope.matches(requirement)
        )
        if not rows:
            return None
        sources = {row.source_node_id for row in rows if row.source_node_id is not None}
        if len(sources) > 1:
            raise ValueError("overlapping routing constraints require conflicting source nodes")
        via_nodes = tuple(
            dict.fromkeys(
                node_id
                for row in sorted(rows, key=self._constraint_sort_key)
                for node_id in row.required_via_node_ids
            )
        )
        allocation_ids = tuple(
            dict.fromkeys(
                allocation_id
                for row in sorted(rows, key=self._constraint_sort_key)
                for allocation_id in row.required_transport_allocation_ids
            )
        )
        return SupplyRoutingConstraintState(
            scope=SupplyRoutingConstraintScope(
                destination_id=requirement.destination_id,
                owner_kind=requirement.owner_kind,
                owner_id=requirement.owner_id,
                resource_id=requirement.resource_id,
            ),
            source_node_id=next(iter(sources), None),
            required_via_node_ids=via_nodes,
            required_transport_allocation_ids=allocation_ids,
        )

    def prune_orphan_routing_constraints(self) -> None:
        orphan_scopes = [
            scope
            for scope in self.routing_constraints
            if scope.owner_kind is not None
            and not self.supply_owner_exists(scope.owner_kind, scope.owner_id)
        ]
        for scope in orphan_scopes:
            self.routing_constraints.pop(scope, None)

    def requirement_remaining_t(self, requirement: SupplyRequirement) -> float:
        return max(0.0, requirement.amount_t - self.cargo_flow_pipeline_t(requirement.id))

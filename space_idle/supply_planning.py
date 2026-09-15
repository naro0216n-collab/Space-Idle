from __future__ import annotations

from dataclasses import dataclass, replace

from .priority import ActivityPriority
from .shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .supply import SupplyPolicy, SupplyRequirement, TargetStockPolicy
from .transport.models import PathPolicy


@dataclass(frozen=True)
class SupplyPlanningOptions:
    """Derived sourcing/path options for one Supply Requirement."""

    candidate_source_ids: tuple[SpatialNodeId, ...]
    operational_source_ids: tuple[SpatialNodeId, ...]
    stocked_source_ids: tuple[SpatialNodeId, ...]
    blockers: tuple[str, ...]
    earliest_confirmed_arrival_day: int | None


class SupplyPlanningMixin:
    """Player policy state used by Logistics planning.

    Target Stock and sourcing/path choices are authoritative player intent.
    Concrete paths, current Transport Capacity and dispatches are derived from
    those policies plus current Domain Supply Requirements and physical state.
    """

    @staticmethod
    def _target_stock_id(
        destination_id: SpatialNodeId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"target_stock:{destination_id}:{resource_id}")

    @staticmethod
    def _supply_policy_id(
        destination_id: SpatialNodeId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"supply.policy:{destination_id}:{resource_id}")

    def set_target_stock(
        self,
        destination_id: SpatialNodeId,
        resource_id: DefinitionId,
        target_quantity_t: float,
        priority: ActivityPriority,
    ) -> EntityId:
        if not self.facilities.environment.graph.has_operational_node(destination_id):
            raise KeyError(destination_id)
        policy_id = self._target_stock_id(destination_id, resource_id)
        self.target_stocks[policy_id] = TargetStockPolicy(
            policy_id,
            destination_id,
            resource_id,
            target_quantity_t,
            priority,
        )
        return policy_id

    def delete_target_stock(
        self, destination_id: SpatialNodeId, resource_id: DefinitionId
    ) -> None:
        policy_id = self._target_stock_id(destination_id, resource_id)
        if policy_id not in self.target_stocks:
            raise KeyError(policy_id)
        del self.target_stocks[policy_id]

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

    def set_supply_policy(
        self,
        destination_id: SpatialNodeId,
        resource_id: DefinitionId,
        *,
        preferred_source_id: SpatialNodeId | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
        explicit_path: tuple[RouteId, ...] | None = None,
    ) -> EntityId:
        graph = self.facilities.environment.graph
        if not graph.has_operational_node(destination_id):
            raise KeyError(destination_id)
        if preferred_source_id is not None:
            if not graph.has_operational_node(preferred_source_id):
                raise KeyError(preferred_source_id)
            if preferred_source_id == destination_id:
                raise ValueError("supply source and destination must differ")
        if explicit_path is not None:
            if preferred_source_id is None:
                raise ValueError("explicit supply path requires a preferred source")
            self.transport.validate_movement_path_structure(
                preferred_source_id, destination_id, explicit_path
            )
        policy_id = self._supply_policy_id(destination_id, resource_id)
        self.supply_policies[policy_id] = SupplyPolicy(
            policy_id,
            destination_id,
            resource_id,
            preferred_source_id,
            path_policy,
            explicit_path,
        )
        return policy_id

    def delete_supply_policy(
        self, destination_id: SpatialNodeId, resource_id: DefinitionId
    ) -> None:
        policy_id = self._supply_policy_id(destination_id, resource_id)
        if policy_id not in self.supply_policies:
            raise KeyError(policy_id)
        del self.supply_policies[policy_id]

    def supply_policy_rows(self) -> tuple[SupplyPolicy, ...]:
        return tuple(
            replace(row)
            for row in sorted(self.supply_policies.values(), key=lambda row: str(row.id))
        )


    def demand_remaining_t(self, demand: SupplyRequirement) -> float:
        return max(0.0, demand.amount_t - self.cargo_flow_pipeline_t(demand.id))

    def supply_policy_for(self, demand: SupplyRequirement) -> SupplyPolicy | None:
        return self.supply_policies.get(
            self._supply_policy_id(demand.destination_id, demand.resource_id)
        )

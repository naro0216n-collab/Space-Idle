from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Callable

from .priority import ActivityPriority
from .shared import DefinitionId, EntityId, MovementPlanId, SpatialNodeId
from .supply import (
    LogisticsPolicyAssignmentState,
    LogisticsPolicyState,
    PathSelectionMode,
    SourceSelectionMode,
    SupplyRequirement,
    TargetStockPolicy,
)
from .transport.models import PathPolicy


@dataclass(frozen=True)
class SupplyPlanningOptions:
    """Derived sourcing/path options for one Supply Requirement."""

    candidate_source_ids: tuple[SpatialNodeId, ...]
    operational_source_ids: tuple[SpatialNodeId, ...]
    stocked_source_ids: tuple[SpatialNodeId, ...]
    path_candidates: tuple[tuple[SpatialNodeId, tuple[MovementPlanId, ...]], ...]
    blockers: tuple[str, ...]
    earliest_confirmed_arrival_day: int | None


class SupplyPlanningMixin:
    """Authoritative Logistics Policy state plus Target Stock player intent."""

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
        self.policy_assignments.pop(("target_stock", policy_id), None)
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

    def register_policy_owner_resolver(
        self, owner_kind: str, resolver: Callable[[EntityId], bool]
    ) -> None:
        if not owner_kind:
            raise ValueError("logistics policy owner kind must be non-empty")
        if owner_kind in self._policy_owner_resolvers:
            raise ValueError(f"logistics policy owner resolver already registered: {owner_kind}")
        self._policy_owner_resolvers[owner_kind] = resolver

    def policy_owner_exists(self, owner_kind: str, owner_id: EntityId) -> bool:
        resolver = self._policy_owner_resolvers.get(owner_kind)
        return False if resolver is None else bool(resolver(owner_id))

    def create_logistics_policy(
        self,
        policy_id: EntityId,
        *,
        source_mode: SourceSelectionMode = SourceSelectionMode.ALLOW_ANY,
        allowed_source_ids: tuple[SpatialNodeId, ...] | None = None,
        preferred_source_id: SpatialNodeId | None = None,
        path_mode: PathSelectionMode = PathSelectionMode.ALLOW_ANY,
        explicit_path: tuple[MovementPlanId, ...] | None = None,
        allowed_handoff_ids: tuple[SpatialNodeId, ...] | None = None,
        allowed_service_ids: tuple[str, ...] | None = None,
        path_preference: PathPolicy = PathPolicy.BALANCED,
    ) -> EntityId:
        if policy_id in self.logistics_policies:
            raise ValueError(f"logistics policy already exists: {policy_id}")
        policy = LogisticsPolicyState(
            id=policy_id,
            source_mode=source_mode,
            allowed_source_ids=allowed_source_ids,
            preferred_source_id=preferred_source_id,
            path_mode=path_mode,
            explicit_path=explicit_path,
            allowed_handoff_ids=allowed_handoff_ids,
            allowed_service_ids=allowed_service_ids,
            path_preference=path_preference,
        )
        self._validate_policy_references(policy)
        self.logistics_policies[policy_id] = policy
        return policy_id

    def update_logistics_policy(
        self,
        policy_id: EntityId,
        *,
        source_mode: SourceSelectionMode | None = None,
        allowed_source_ids: tuple[SpatialNodeId, ...] | None | object = ...,
        preferred_source_id: SpatialNodeId | None | object = ...,
        path_mode: PathSelectionMode | None = None,
        explicit_path: tuple[MovementPlanId, ...] | None | object = ...,
        allowed_handoff_ids: tuple[SpatialNodeId, ...] | None | object = ...,
        allowed_service_ids: tuple[str, ...] | None | object = ...,
        path_preference: PathPolicy | None = None,
    ) -> None:
        current = self.logistics_policies[policy_id]
        updated = LogisticsPolicyState(
            id=current.id,
            source_mode=current.source_mode if source_mode is None else source_mode,
            allowed_source_ids=(
                current.allowed_source_ids if allowed_source_ids is ... else allowed_source_ids
            ),
            preferred_source_id=(
                current.preferred_source_id
                if preferred_source_id is ...
                else preferred_source_id
            ),
            path_mode=current.path_mode if path_mode is None else path_mode,
            explicit_path=current.explicit_path if explicit_path is ... else explicit_path,
            allowed_handoff_ids=(
                current.allowed_handoff_ids
                if allowed_handoff_ids is ...
                else allowed_handoff_ids
            ),
            allowed_service_ids=(
                current.allowed_service_ids
                if allowed_service_ids is ...
                else allowed_service_ids
            ),
            path_preference=(
                current.path_preference if path_preference is None else path_preference
            ),
        )
        self._validate_policy_references(updated)
        self.logistics_policies[policy_id] = updated

    def _validate_policy_references(self, policy: LogisticsPolicyState) -> None:
        graph = self.facilities.environment.graph
        for source_id in policy.allowed_source_ids or ():
            if not graph.has_operational_node(source_id):
                raise KeyError(source_id)
        if (
            policy.preferred_source_id is not None
            and not graph.has_operational_node(policy.preferred_source_id)
        ):
            raise KeyError(policy.preferred_source_id)
        for handoff_id in policy.allowed_handoff_ids or ():
            if not graph.has_operational_node(handoff_id):
                raise KeyError(handoff_id)
        if policy.path_mode is PathSelectionMode.PINNED and policy.explicit_path:
            # Source and path are independent policy dimensions.  Validate the
            # pinned Movement Plan sequence against its own endpoints here; a
            # Supply Requirement source that cannot enter that path is rejected
            # later by path resolution rather than forcing source_mode=PINNED.
            first = self.transport.require_movement_plan(policy.explicit_path[0])
            last = self.transport.require_movement_plan(policy.explicit_path[-1])
            self.transport.validate_movement_path_structure(
                first.origin_id, last.destination_id, policy.explicit_path
            )

    def delete_logistics_policy(self, policy_id: EntityId) -> None:
        if policy_id not in self.logistics_policies:
            raise KeyError(policy_id)
        if self.global_policy_id == policy_id:
            raise ValueError("logistics policy is the active global policy")
        refs = [
            assignment
            for assignment in self.policy_assignments.values()
            if assignment.policy_id == policy_id
        ]
        if refs:
            raise ValueError("logistics policy is still assigned")
        del self.logistics_policies[policy_id]

    def logistics_policy_rows(self) -> tuple[LogisticsPolicyState, ...]:
        return tuple(
            replace(row)
            for row in sorted(self.logistics_policies.values(), key=lambda row: str(row.id))
        )

    def require_logistics_policy(self, policy_id: EntityId) -> LogisticsPolicyState:
        return replace(self.logistics_policies[policy_id])

    def prune_orphan_policy_assignments(self) -> None:
        orphan_keys = [
            key
            for key, assignment in self.policy_assignments.items()
            if not self.policy_owner_exists(assignment.owner_kind, assignment.owner_id)
        ]
        for key in orphan_keys:
            self.policy_assignments.pop(key, None)

    def assign_logistics_policy(
        self, owner_kind: str, owner_id: EntityId, policy_id: EntityId
    ) -> None:
        if policy_id not in self.logistics_policies:
            raise KeyError(policy_id)
        if not self.policy_owner_exists(owner_kind, owner_id):
            raise KeyError(f"unknown logistics policy owner: {owner_kind}:{owner_id}")
        self.policy_assignments[(owner_kind, owner_id)] = LogisticsPolicyAssignmentState(
            owner_kind, owner_id, policy_id
        )

    def unassign_logistics_policy(self, owner_kind: str, owner_id: EntityId) -> None:
        self.policy_assignments.pop((owner_kind, owner_id), None)

    def logistics_policy_assignments(self) -> tuple[LogisticsPolicyAssignmentState, ...]:
        return tuple(
            replace(row)
            for row in sorted(
                self.policy_assignments.values(),
                key=lambda row: (row.owner_kind, str(row.owner_id)),
            )
        )

    def assigned_policy_id_for(self, owner_kind: str, owner_id: EntityId) -> EntityId | None:
        assignment = self.policy_assignments.get((owner_kind, owner_id))
        return None if assignment is None else assignment.policy_id

    def global_logistics_policy_id(self) -> EntityId | None:
        return self.global_policy_id

    def set_global_logistics_policy(self, policy_id: EntityId | None) -> None:
        if policy_id is not None and policy_id not in self.logistics_policies:
            raise KeyError(policy_id)
        self.global_policy_id = policy_id

    def resolved_policy_for(
        self, owner_kind: str, owner_id: EntityId
    ) -> LogisticsPolicyState | None:
        assignment = self.policy_assignments.get((owner_kind, owner_id))
        if assignment is not None:
            return self.logistics_policies.get(assignment.policy_id)
        if self.global_policy_id is None:
            return None
        return self.logistics_policies.get(self.global_policy_id)

    def requirement_remaining_t(self, requirement: SupplyRequirement) -> float:
        return max(0.0, requirement.amount_t - self.cargo_flow_pipeline_t(requirement.id))

    def logistics_policy_for(
        self, requirement: SupplyRequirement
    ) -> LogisticsPolicyState | None:
        return self.resolved_policy_for(requirement.owner_kind, requirement.owner_id)

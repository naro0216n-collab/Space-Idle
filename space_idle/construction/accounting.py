from __future__ import annotations

from ..execution_requirements import ExecutionAllocationPlan
from ..shared import EntityId
from .models import ConstructionProject


class ConstructionAccountingMixin:
    """Own authoritative project material reservations and commitment."""

    @staticmethod
    def _supply_id(project_id, resource_id) -> EntityId:
        return EntityId(f"requirement.project:{project_id}:{resource_id}")

    @staticmethod
    def _resource_reservation_owner_id(project_id) -> EntityId:
        return EntityId(f"project.materials:{project_id}")

    @staticmethod
    def _reservation_acquisition_id(project_id, resource_id) -> EntityId:
        return EntityId(f"reservation.project:{project_id}:{resource_id}")

    def _reserved_resource_t(self, project: ConstructionProject, resource_id) -> float:
        return self.inventory.reserved_for(
            self._resource_reservation_owner_id(project.id),
            project.operational_node_id,
            resource_id,
        )

    def reserved_resource_t(self, project: ConstructionProject, resource_id) -> float:
        return self._reserved_resource_t(project, resource_id)

    def _committed_resources(self, project: ConstructionProject) -> dict:
        return {
            resource_id: state.committed_t
            for resource_id, state in project.resources.items()
            if state.committed_t > 1e-12
        }

    def _acquire_project_reservations(
        self, project: ConstructionProject, allocations: ExecutionAllocationPlan
    ) -> None:
        if project.materials_committed:
            return
        recipe = self._recipe_for_project(project)
        owner_id = self._resource_reservation_owner_id(project.id)
        for requirement in recipe.resources:
            resource_id = requirement.resource_id
            reserved = self._reserved_resource_t(project, resource_id)
            missing = max(0.0, requirement.amount_t - reserved)
            if missing <= 1e-12:
                continue
            try:
                allocated = allocations.allocated(
                    self._reservation_acquisition_id(project.id, resource_id)
                )
            except KeyError:
                allocated = 0.0
            amount = min(missing, max(0.0, allocated))
            if amount <= 1e-12:
                continue
            taken = self.inventory.reserve(
                owner_id, project.operational_node_id, resource_id, amount
            )
            if taken + 1e-9 < amount:
                raise RuntimeError("allocated reservation stock changed before execution")

    def _release_material_reservations(self, project: ConstructionProject) -> None:
        self.inventory.release_reservation(self._resource_reservation_owner_id(project.id))

    def _commit_materials(self, project: ConstructionProject) -> None:
        if project.materials_committed:
            return
        recipe = self._recipe_for_project(project)
        owner_id = self._resource_reservation_owner_id(project.id)
        for requirement in recipe.resources:
            state = project.resources[requirement.resource_id]
            reserved = self._reserved_resource_t(project, requirement.resource_id)
            if reserved + 1e-9 < requirement.amount_t:
                raise RuntimeError("construction materials are not fully reserved")
            if requirement.amount_t > 1e-12:
                self.inventory.consume_reserved(
                    owner_id,
                    project.operational_node_id,
                    requirement.resource_id,
                    requirement.amount_t,
                )
            state.committed_t = requirement.amount_t
        project.materials_committed = True

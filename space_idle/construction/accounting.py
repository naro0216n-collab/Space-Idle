from __future__ import annotations

from ..resource_claim import ResourceAllocationPlan
from ..shared import EntityId
from .models import ConstructionProject


class ConstructionAccountingMixin:
    """Owns construction material staging/commit accounting.

    Procurement decides when a project is fully supplied; execution consumes
    committed work. Both use this lower-level accounting service so neither
    implementation layer depends on the other.
    """

    @staticmethod
    def _resource_demand_id(project_id, resource_id) -> EntityId:
        return EntityId(f"demand.project:{project_id}:{resource_id}")

    @staticmethod
    def _resource_staging_owner_id(project_id) -> EntityId:
        return EntityId(f"project.materials:{project_id}")

    def _staged_resource_t(self, project: ConstructionProject, resource_id) -> float:
        return self.inventory.staged_for(
            self._resource_staging_owner_id(project.id),
            project.operational_node_id,
            resource_id,
        )

    def _committed_resources(self, project: ConstructionProject) -> dict:
        return {
            resource_id: state.committed_t
            for resource_id, state in project.resources.items()
            if state.committed_t > 1e-12
        }

    def staged_resource_t(self, project: ConstructionProject, resource_id) -> float:
        """Durable material already staged for this project."""
        return self._staged_resource_t(project, resource_id)

    @staticmethod
    def _resource_claim_id(project_id, resource_id) -> EntityId:
        return EntityId(f"claim.project:{project_id}:{resource_id}")

    def _stage_project_allocations(
        self, project: ConstructionProject, allocations: ResourceAllocationPlan
    ) -> None:
        """Move this tick's allocated material into durable project staging."""
        if project.materials_committed:
            return
        recipe = self._recipe_for_project(project)
        owner_id = self._resource_staging_owner_id(project.id)
        for requirement in recipe.resources:
            resource_id = requirement.resource_id
            staged = self._staged_resource_t(project, resource_id)
            missing = max(0.0, requirement.amount_t - staged)
            if missing <= 1e-12:
                continue
            try:
                allocated = allocations.allocated(
                    self._resource_claim_id(project.id, resource_id)
                )
            except KeyError:
                allocated = 0.0
            amount = min(missing, max(0.0, allocated))
            if amount <= 1e-12:
                continue
            self.inventory.stage_allocated(
                owner_id, project.operational_node_id, resource_id, amount
            )

    def _restore_staged_resources(self, project: ConstructionProject) -> None:
        owner_id = self._resource_staging_owner_id(project.id)
        for resource_id in project.resources:
            staged = self._staged_resource_t(project, resource_id)
            if staged > 1e-12:
                self.inventory.unstage_to_stock(
                    owner_id, project.operational_node_id, resource_id, staged
                )

    def _commit_materials(self, project: ConstructionProject) -> None:
        if project.materials_committed:
            return
        recipe = self._recipe_for_project(project)
        owner_id = self._resource_staging_owner_id(project.id)
        for requirement in recipe.resources:
            state = project.resources[requirement.resource_id]
            staged = self._staged_resource_t(project, requirement.resource_id)
            if staged + 1e-9 < requirement.amount_t:
                raise RuntimeError("construction materials are not fully allocated")
            if staged > 1e-12:
                self.inventory.release_storage_occupancy(
                    owner_id, project.operational_node_id, requirement.resource_id, staged
                )
            state.committed_t = requirement.amount_t
        project.materials_committed = True

from __future__ import annotations

from ..shared import EntityId
from .models import ConstructionProject


class ConstructionAccountingMixin:
    """Owns construction material reservation/commit accounting.

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
            project.location_id,
            resource_id,
        )

    def _committed_resources(self, project: ConstructionProject) -> dict:
        return {
            resource_id: state.committed_t
            for resource_id, state in project.resources.items()
            if state.committed_t > 1e-12
        }

    def reserved_resource_t(self, project: ConstructionProject, resource_id) -> float:
        return (
            self.inventory.reserved_for(
                self._resource_demand_id(project.id, resource_id),
                project.location_id,
                resource_id,
            )
            + self._staged_resource_t(project, resource_id)
        )

    def _reserved_resource_t(self, project: ConstructionProject, resource_id) -> float:
        return self.reserved_resource_t(project, resource_id)

    def _release_project_resource_reservations(self, project: ConstructionProject) -> None:
        for resource_id in project.resources:
            self.inventory.release_reservation(
                self._resource_demand_id(project.id, resource_id)
            )

    def _stage_project_reservations(self, project: ConstructionProject) -> None:
        """Turn transient allocation into durable project-owned procurement state.

        Construction is a finite demand.  Material already allocated to it must
        remain committed to that project across later daily demand resolutions,
        while continuing to occupy the same physical storage until construction
        actually consumes it.
        """
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
            demand_id = self._resource_demand_id(project.id, resource_id)
            reserved = self.inventory.reserved_for(
                demand_id, project.location_id, resource_id
            )
            amount = min(missing, reserved)
            if amount <= 1e-12:
                continue
            self.inventory.stage_reserved(
                demand_id, owner_id, project.location_id, resource_id, amount
            )

    def _restore_staged_resources(self, project: ConstructionProject) -> None:
        owner_id = self._resource_staging_owner_id(project.id)
        for resource_id in project.resources:
            staged = self._staged_resource_t(project, resource_id)
            if staged > 1e-12:
                self.inventory.unstage_to_stock(
                    owner_id, project.location_id, resource_id, staged
                )

    def _commit_materials(self, project: ConstructionProject) -> None:
        if project.materials_committed:
            return
        self._stage_project_reservations(project)
        recipe = self._recipe_for_project(project)
        owner_id = self._resource_staging_owner_id(project.id)
        for requirement in recipe.resources:
            state = project.resources[requirement.resource_id]
            staged = self._staged_resource_t(project, requirement.resource_id)
            if staged + 1e-9 < requirement.amount_t:
                raise RuntimeError("construction materials are not fully allocated")
            if staged > 1e-12:
                self.inventory.release_storage_occupancy(
                    owner_id, project.location_id, requirement.resource_id, staged
                )
            state.committed_t = requirement.amount_t
        project.materials_committed = True

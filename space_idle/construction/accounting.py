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

    def _committed_resources(self, project: ConstructionProject) -> dict:
        return {
            resource_id: state.committed_t
            for resource_id, state in project.resources.items()
            if state.committed_t > 1e-12
        }

    def reserved_resource_t(self, project: ConstructionProject, resource_id) -> float:
        return self.inventory.reserved_for(
            self._resource_demand_id(project.id, resource_id),
            project.location_id,
            resource_id,
        )

    def _reserved_resource_t(self, project: ConstructionProject, resource_id) -> float:
        return self.reserved_resource_t(project, resource_id)

    def _release_project_resource_reservations(self, project: ConstructionProject) -> None:
        for resource_id in project.resources:
            self.inventory.release_reservation(
                self._resource_demand_id(project.id, resource_id)
            )

    def _commit_materials(self, project: ConstructionProject) -> None:
        if project.materials_committed:
            return
        recipe = self._recipe_for_project(project)
        for requirement in recipe.resources:
            state = project.resources[requirement.resource_id]
            demand_id = self._resource_demand_id(project.id, requirement.resource_id)
            held = self._reserved_resource_t(project, requirement.resource_id)
            if held + 1e-9 < requirement.amount_t:
                raise RuntimeError("construction materials are not fully allocated")
            if requirement.amount_t > 1e-12:
                self.inventory.consume_reserved(
                    demand_id,
                    project.location_id,
                    requirement.resource_id,
                    requirement.amount_t,
                )
            state.committed_t = requirement.amount_t
        project.materials_committed = True

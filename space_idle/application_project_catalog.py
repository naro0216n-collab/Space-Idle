from __future__ import annotations

from .application_catalog_core_sections import (
    project_celestial_bodies,
    project_facilities,
    project_operational_nodes,
    project_processes,
    project_research,
    project_resources,
)
from .application_catalog_transport_sections import (
    project_movement_plans,
    project_vehicles,
)
from .application_views import CatalogView, OperationalNodeSummary, WorldView
from .shared import DefinitionId


class CatalogWorldProjectorMixin:
    def _catalog_view(self) -> CatalogView:
        return CatalogView(
            project_resources(self),
            project_facilities(self),
            project_vehicles(self),
            project_celestial_bodies(self),
            project_operational_nodes(self),
            project_processes(self),
            project_research(self),
            project_movement_plans(self),
        )

    def _world_view(self) -> WorldView:
        sim = self._simulation
        operational_nodes = []
        for node in sim.graph.operational_nodes():
            facility_count = sum(1 for facility in sim.facilities.facilities.values() if facility.operational_node_id == node.id)
            active_projects = sum(
                1 for project in sim.projects.projects.values()
                if project.operational_node_id == node.id and project.status not in {"complete", "cancelled"}
            )
            active_foundings = (
                0 if sim.founding is None else sum(
                    1 for project in sim.founding.projects.values()
                    if project.staging_node_id == node.id and project.status.value not in {"complete", "cancelled"}
                )
            )
            operational_nodes.append(OperationalNodeSummary(
                str(node.id), node.display_name,
                None if node.parent_id is None else str(node.parent_id),
                None if node.body_id is None else str(node.body_id),
                node.kind.value, facility_count, active_projects, active_foundings,
            ))
        return WorldView(
            sim.content_id,
            sim.day,
            sim.market.funds.balance,
            tuple(operational_nodes),
        )

    def _resource_name(self, resource_id: DefinitionId) -> str:
        definition = self._catalog.resources.get(resource_id)
        return definition.display_name if definition is not None else str(resource_id)

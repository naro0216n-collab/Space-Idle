from __future__ import annotations

from .application_catalog_core_sections import (
    project_celestial_bodies,
    project_facilities,
    project_locations,
    project_processes,
    project_research,
    project_resources,
)
from .application_catalog_transport_sections import (
    project_routes,
    project_transport_services,
    project_vehicles,
)
from .application_views import CatalogView, LocationSummary, WorldView
from .shared import DefinitionId


class CatalogWorldProjectorMixin:
    def _catalog_view(self) -> CatalogView:
        return CatalogView(
            project_resources(self),
            project_facilities(self),
            project_vehicles(self),
            project_celestial_bodies(self),
            project_locations(self),
            project_processes(self),
            project_research(self),
            project_routes(self),
            project_transport_services(self),
        )

    def _world_view(self) -> WorldView:
        sim = self._simulation
        locations = []
        for node in sim.graph.operational_nodes():
            facility_count = sum(1 for facility in sim.facilities.facilities.values() if facility.location_id == node.id)
            active_projects = sum(
                1 for project in sim.projects.projects.values()
                if project.location_id == node.id and project.status not in {"complete", "cancelled"}
            )
            locations.append(LocationSummary(
                str(node.id), node.display_name,
                None if node.parent_id is None else str(node.parent_id),
                None if node.body_id is None else str(node.body_id),
                node.kind.value, facility_count, active_projects,
            ))
        return WorldView(sim.content_id, sim.day, sim.account.funds_musd, tuple(locations))

    def _resource_name(self, resource_id: DefinitionId) -> str:
        definition = self._catalog.resources.get(resource_id)
        return definition.display_name if definition is not None else str(resource_id)

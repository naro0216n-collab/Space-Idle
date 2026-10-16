from __future__ import annotations

from .application_catalog_core_sections import (
    project_celestial_bodies,
    project_extraction_methods,
    project_facilities,
    project_operational_nodes,
    project_processes,
    project_research,
    project_resources,
    project_survey_service_capacities,
)
from .application_catalog_transport_sections import (
    project_movement_plans,
    project_vehicles,
)
from .application_views import CatalogView, OperationalNodeSummary, WorldView, DevelopmentWorldReferenceView
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
            project_survey_service_capacities(self),
            project_extraction_methods(self),
        )

    def _development_world_reference(self) -> DevelopmentWorldReferenceView:
        """Physical design metadata; never return this to a Player-facing UI route."""
        world_summary = {}
        for cell in sorted(self._simulation.graph.surface_cells.values(), key=lambda row: str(row.id)):
            body = world_summary.setdefault(str(cell.body_id), {
                "cells": 0, "area_km2": 0.0, "terrain_profiles": {}, "resources": {},
            })
            body["cells"] += 1
            body["area_km2"] += cell.area_km2
            profile = cell.terrain.profile_id
            body["terrain_profiles"][profile] = body["terrain_profiles"].get(profile, 0) + 1
            for rid, potential in cell.resource_potential_by_resource.items():
                resource = body["resources"].setdefault(str(rid), {
                    "covered_cells": 0, "covered_area_km2": 0.0,
                    "area_weighted_potential": 0.0,
                    "min_potential": potential, "max_potential": potential,
                })
                resource["covered_cells"] += 1
                resource["covered_area_km2"] += cell.area_km2
                resource["area_weighted_potential"] += cell.area_km2 * potential
                resource["min_potential"] = min(resource["min_potential"], potential)
                resource["max_potential"] = max(resource["max_potential"], potential)
        for body in world_summary.values():
            body["terrain_profiles"] = dict(sorted(body["terrain_profiles"].items()))
            for resource in body["resources"].values():
                resource["area_weighted_mean_potential"] = (
                    resource.pop("area_weighted_potential") / resource["covered_area_km2"]
                )
            body["resources"] = dict(sorted(body["resources"].items()))
        return DevelopmentWorldReferenceView(dict(sorted(world_summary.items())))

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

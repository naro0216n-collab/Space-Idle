from __future__ import annotations

from .application_views import (
    SurfaceCellDevelopmentOption, SurfaceCellFoundationOption, SurfaceCellRow, SurfaceFacilityPlacementOption,
    SurfaceLocationTerritoryRow,
    SurfaceMapView,
    SurfaceResourceKnowledgeRow,
)
from .facilities import FacilityPlacementScope
from .shared import CelestialBodyId


class SurfaceProjectorMixin:
    def _surface_map_view(self, body_id: CelestialBodyId) -> SurfaceMapView:
        sim = self._simulation
        body = sim.graph.bodies[body_id]
        locations = tuple(
            SurfaceLocationTerritoryRow(
                str(location.id),
                location.display_name,
                str(location.body_id),
                str(location.core_cell_id),
                tuple(sorted((str(cell_id) for cell_id in location.developed_cell_ids))),
            )
            for location in sorted(
                (row for row in sim.graph.locations.values() if row.body_id == body_id),
                key=lambda row: str(row.id),
            )
        )
        rows: list[SurfaceCellRow] = []
        for cell in sim.graph.cells_for_body(body_id):
            owner = sim.graph.owner_of_cell(cell.id)
            owner_state = None if owner is None else sim.graph.locations[owner]
            development_options_list = []
            development_recipe = (
                None if sim.projects.surface_cell_development_recipe_id is None
                else sim.projects.spatial_recipes.get(sim.projects.surface_cell_development_recipe_id)
            )
            active_spatial_project = sim.projects.active_spatial_project_for_cell(cell.id)
            for location in sorted(
                (row for row in sim.graph.locations.values() if row.body_id == body_id),
                key=lambda row: str(row.id),
            ):
                location_power = sim.power.snapshot(location.id, sim.facilities, sim.day)
                failures = sim.projects.surface_cell_development_failures(
                    location.id, cell.id, sim.day, location_power
                )
                blockers = tuple((failure.code, failure.detail) for failure in failures)
                projected_demand = None
                projected_fulfillment = None
                limiting_factors: tuple[str, ...] = ()
                graph_blockers = sim.graph.surface_cell_development_failures(location.id, cell.id)
                if not graph_blockers and sim.surface_infrastructure is not None:
                    projected = sim.surface_infrastructure.prospective_development_snapshot(
                        location.id, cell.id, sim.facilities, location_power, sim.day
                    )
                    projected_demand = projected.demand
                    projected_fulfillment = projected.fulfillment
                    limiting_factors = projected.limiting_factors
                development_options_list.append(
                    SurfaceCellDevelopmentOption(
                        str(location.id), blockers, projected_demand, projected_fulfillment, limiting_factors,
                        None if development_recipe is None else development_recipe.construction_work,
                        () if development_recipe is None else tuple(
                            (str(req.resource_id), req.amount_t) for req in development_recipe.resources
                        ),
                        () if development_recipe is None else tuple(sorted(
                            str(technology) for technology in development_recipe.prerequisite_technologies - sim.projects.unlocked_technologies
                        )),
                        None if active_spatial_project is None else str(active_spatial_project.id),
                    )
                )
            development_options = tuple(development_options_list)
            resources = ()
            if sim.survey is not None:
                resources = tuple(
                    SurfaceResourceKnowledgeRow(
                        str(resource_id),
                        self._resource_name(resource_id),
                        sim.survey.knowledge_level(cell.id, resource_id),
                        sim.survey.visible_presence_probability(cell.id, resource_id),
                        sim.survey.visible_potential(cell.id, resource_id),
                        sim.survey.visible_potential_precision_fraction(cell.id, resource_id),
                    )
                    for (target_cell_id, resource_id) in sorted(
                        (
                            key
                            for key in sim.survey.targets
                            if key[0] == cell.id
                        ),
                        key=lambda key: str(key[1]),
                    )
                )
            facility_placement_options = ()
            if owner is not None:
                power = sim.power.snapshot(owner, sim.facilities, sim.day)
                facility_placement_options = tuple(
                    SurfaceFacilityPlacementOption(
                        str(recipe.facility_def_id),
                        sim.facilities.definitions[recipe.facility_def_id].display_name,
                        str(owner),
                        recipe.construction_work,
                        recipe.self_deploying,
                        tuple((str(req.resource_id), req.amount_t) for req in recipe.resources),
                        tuple(sorted(str(technology) for technology in recipe.prerequisite_technologies - sim.projects.unlocked_technologies)),
                        tuple(
                            (failure.code, failure.detail)
                            for failure in sim.projects.site_failures(
                                recipe.facility_def_id, owner, sim.day, power, site_cell_id=cell.id
                            )
                        ),
                    )
                    for recipe in sorted(sim.projects.recipes.values(), key=lambda row: str(row.facility_def_id))
                    if sim.facilities.definitions[recipe.facility_def_id].placement_scope is FacilityPlacementScope.SURFACE_CELL
                )
            foundation_recipe = (
                None if sim.projects.location_founding_recipe_id is None
                else sim.projects.spatial_recipes.get(sim.projects.location_founding_recipe_id)
            )
            foundation_options = ()
            if foundation_recipe is not None:
                foundation_rows = []
                for provider_id in sorted(sim.graph.operational_node_ids(), key=str):
                    provider = sim.graph.operational_node(provider_id)
                    if provider.body_id != body_id:
                        continue
                    provider_power = sim.power.snapshot(provider_id, sim.facilities, sim.day)
                    failures = sim.projects.location_founding_failures(
                        provider_id, body_id, cell.id, sim.day, provider_power
                    )
                    foundation_rows.append(SurfaceCellFoundationOption(
                        str(provider_id),
                        foundation_recipe.construction_work,
                        tuple((str(req.resource_id), req.amount_t) for req in foundation_recipe.resources),
                        tuple(sorted(
                            str(technology) for technology in foundation_recipe.prerequisite_technologies - sim.projects.unlocked_technologies
                        )),
                        tuple((failure.code, failure.detail) for failure in failures),
                        None if active_spatial_project is None else str(active_spatial_project.id),
                    ))
                foundation_options = tuple(foundation_rows)

            rows.append(
                SurfaceCellRow(
                    str(cell.id),
                    str(cell.body_id),
                    cell.area_km2,
                    cell.centroid.latitude_deg,
                    cell.centroid.longitude_deg,
                    tuple(sorted(map(str, cell.neighbor_ids))),
                    (
                        ("terrain_factor", cell.terrain.terrain_factor),
                        ("bearing_capacity_factor", cell.terrain.bearing_capacity_factor),
                        ("dust_factor", cell.terrain.dust_factor),
                        ("slope_factor", cell.terrain.slope_factor),
                    ),
                    resources,
                    owner is not None,
                    None if owner is None else str(owner),
                    owner_state is not None and owner_state.core_cell_id == cell.id,
                    sim.graph.location_foundation_failures(body_id, cell.id),
                    development_options,
                    facility_placement_options,
                    foundation_options,
                )
            )
        return SurfaceMapView(str(body.id), body.display_name, tuple(rows), locations)

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
        decision = sim.tick_decision_projection()
        powers = decision.allocations.power_by_location
        body = sim.graph.bodies[body_id]
        locations = tuple(
            SurfaceLocationTerritoryRow(
                str(location.operational_node_id),
                location.display_name,
                str(location.body_id),
                str(location.core_cell_id),
                tuple(sorted((str(cell_id) for cell_id in location.developed_cell_ids))),
            )
            for location in sorted(
                (row for row in sim.graph.locations.values() if row.body_id == body_id),
                key=lambda row: str(row.operational_node_id),
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
                key=lambda row: str(row.operational_node_id),
            ):
                location_power = powers[location.operational_node_id]
                failures = sim.projects.surface_cell_development_failures(
                    location.operational_node_id, cell.id, sim.day, location_power
                )
                blockers = tuple((failure.code, failure.detail) for failure in failures)
                if development_recipe is not None:
                    blockers += tuple(
                        ("technology", str(technology))
                        for technology in sorted(
                            development_recipe.prerequisite_technologies - sim.projects.unlocked_technologies,
                            key=str,
                        )
                    )
                projected_demand = None
                projected_fulfillment = None
                limiting_factors: tuple[str, ...] = ()
                graph_blockers = sim.graph.surface_cell_development_failures(location.operational_node_id, cell.id)
                if not graph_blockers and sim.surface_infrastructure is not None:
                    development_request_id = (
                        sim.projects.surface_development_service_request_id(active_spatial_project.id)
                        if active_spatial_project is not None
                        and active_spatial_project.operational_node_id == location.operational_node_id
                        else None
                    )
                    projected = sim.surface_infrastructure.prospective_development_snapshot(
                        location.operational_node_id, cell.id, decision.allocations.services,
                        development_request_id=development_request_id,
                    )
                    projected_demand = projected.demand
                    projected_fulfillment = projected.fulfillment
                    limiting_factors = projected.limiting_factors
                development_options_list.append(
                    SurfaceCellDevelopmentOption(
                        location_id=str(location.operational_node_id),
                        blockers=blockers,
                        can_plan=not failures,
                        projected_surface_infrastructure_demand=projected_demand,
                        projected_surface_infrastructure_fulfillment=projected_fulfillment,
                        limiting_factors=limiting_factors,
                        construction_required=None if development_recipe is None else development_recipe.construction_work,
                        resources=() if development_recipe is None else tuple(
                            (str(req.resource_id), req.amount_t) for req in development_recipe.resources
                        ),
                        active_project_id=None if active_spatial_project is None else str(active_spatial_project.id),
                        sourcing_policy_options=tuple(sim.projects.sourcing_policy_options()),
                        import_source_options=tuple(str(source_id) for source_id in sim.projects.import_source_options_for_location(location.operational_node_id)),
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
                power = powers[owner]
                facility_placement_options = tuple(
                    SurfaceFacilityPlacementOption(
                        facility_definition_id=str(recipe.facility_def_id),
                        display_name=sim.facilities.definitions[recipe.facility_def_id].display_name,
                        location_id=str(owner),
                        construction_required=recipe.construction_work,
                        self_deploying=recipe.self_deploying,
                        resources=tuple((str(req.resource_id), req.amount_t) for req in recipe.resources),
                        blockers=(
                            tuple(
                                ("technology", str(technology))
                                for technology in sorted(
                                    recipe.prerequisite_technologies - sim.projects.unlocked_technologies,
                                    key=str,
                                )
                            )
                            + tuple(
                                (failure.code, failure.detail)
                                for failure in sim.projects.site_failures(
                                    recipe.facility_def_id, owner, sim.day, power, site_cell_id=cell.id
                                )
                            )
                        ),
                        can_plan=not sim.projects.build_plan_failures(
                            recipe.facility_def_id, owner, site_cell_id=cell.id
                        ),
                        sourcing_policy_options=tuple(sim.projects.sourcing_policy_options()),
                        import_source_options=tuple(str(source_id) for source_id in sim.projects.import_source_options_for_location(owner)),
                    )
                    for recipe in sorted(sim.projects.recipes.values(), key=lambda row: str(row.facility_def_id))
                    if sim.facilities.definitions[recipe.facility_def_id].placement_scope is FacilityPlacementScope.SURFACE_CELL
                )
            foundation_options = ()
            if sim.founding is not None:
                foundation_rows = []
                active_founding = sim.founding.active_project_for_cell(cell.id)
                for staging_id in sorted(sim.graph.operational_node_ids(), key=str):
                    for package in sorted(sim.founding.packages.values(), key=lambda row: str(row.id)):
                        for vehicle in sim.transport.vehicle_definitions():
                            failures = sim.founding.planning_failures(
                                staging_id, body_id, cell.id, package.id, vehicle.id, sim.day
                            )
                            try:
                                movement_plan = sim.transport.movement_plan_to_physical_target_for_vehicle(
                                    staging_id,
                                    cell.id,
                                    vehicle.id,
                                    payload_t_per_unit=package.payload_t_per_unit,
                                    day=sim.day,
                                )
                                transit_days = sim.transport.performance_movement_transit_days(
                                    movement_plan, vehicle.performance
                                )
                                founding_resources = sim.founding.resource_requirements_for(
                                    package.id, vehicle.id, staging_id, cell.id, day=sim.day
                                )
                            except (KeyError, ValueError):
                                transit_days = 0
                                founding_resources = package.payload_resources
                            foundation_rows.append(SurfaceCellFoundationOption(
                                staging_node_id=str(staging_id),
                                founding_package_id=str(package.id),
                                package_display_name=package.display_name,
                                vehicle_definition_id=str(vehicle.id),
                                vehicle_display_name=vehicle.display_name,
                                preparation_work=package.preparation_work,
                                transit_days=transit_days,
                                payload_t=package.payload_t,
                                payload_t_per_unit=package.payload_t_per_unit,
                                required_units=package.required_units,
                                resources=tuple(
                                    (str(req.resource_id), req.amount_t)
                                    for req in founding_resources
                                ),
                                blockers=tuple((failure.code, failure.detail) for failure in failures),
                                can_plan=not failures,
                                active_project_id=None if active_founding is None else str(active_founding.id),
                                preferred_source_options=tuple(str(source_id) for source_id in sim.projects.import_source_options_for_location(staging_id)),
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
                    self._environment_rows(cell.id),
                    resources,
                    owner is not None,
                    None if owner is None else str(owner),
                    owner_state is not None and owner_state.core_cell_id == cell.id,
                    sim.graph.location_foundation_failures(body_id, cell.id),
                    development_options,
                    facility_placement_options,
                    foundation_options,
                    cell.display_name or str(cell.id),
                )
            )
        return SurfaceMapView(str(body.id), body.display_name, tuple(rows), locations)

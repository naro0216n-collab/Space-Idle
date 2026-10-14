from __future__ import annotations

from .application_comparison import project_comparison_axes
from .application_constraints import constraints_from_pairs, limiting_factors_from_codes
from .app_contracts.ui_reports import ComparisonValueRow
from .app_contracts.surface_views import FoundingDeployedFacilityRow
from .application_views import (
    SurfaceCellDevelopmentOption, FoundingOption, SurfaceCellRow, SurfaceFacilityPlacementOption,
    SurfaceLocationTerritoryRow, NonSurfaceFoundingContextRow, NonSurfaceFoundingView,
    SurfaceMapView,
    SurfaceResourceKnowledgeRow,
)
from .founding import NonSurfaceOperationalNodeTargetSpec
from .construction.models import SurfaceCellDevelopmentTarget
from .facilities import FacilityPlacementScope
from .shared import CelestialBodyId


class SurfaceProjectorMixin:
    def _founding_deployed_facility_rows(self, recipe, context_id, *, environment_known: bool = True) -> tuple[FoundingDeployedFacilityRow, ...]:
        """Show the actual paid physical assets and finite nominal capacities.

        This is a definition projection, not an outcome forecast or an extra
        power/storage allocator. Operating conditions still apply at settlement.
        """
        sim = self._simulation
        rows = []
        for deployment in recipe.deployed_facilities:
            facility_id = deployment.facility_def_id
            definition = sim.facilities.definitions[facility_id]
            generation, load = sim.power.nominal_for_definition_at_context(
                facility_id, context_id,
            )
            storage = sim.storage.providers.get(facility_id)
            provider = sim.projects.construction_providers.get(facility_id)
            rows.append(FoundingDeployedFacilityRow(
                str(facility_id), definition.display_name,
                generation if environment_known else None,
                load if environment_known else None,
                () if storage is None else tuple(sorted(storage.capacity_t_by_pool.items())),
                tuple(sorted((row.service_type, row.nominal_rate)
                             for row in definition.service_capacity_supplies)),
                0.0 if provider is None else provider.work_per_day,
                definition.maintenance_fraction_per_year,
                nominal_power_standby_load_mw=(
                    sim.power.specs[facility_id].standby_load_mw
                    if facility_id in sim.power.specs else 0.0
                ),
            ))
        return tuple(rows)


    def _surface_facility_public_effects(self, recipe, cell_id, site_known: bool) -> dict:
        effects = self._prospective_facility_effects(recipe, cell_id)
        if not site_known:
            effects["power_nominal_generation_mw"] = None
            effects["power_nominal_load_mw"] = None
        return effects

    def _non_surface_founding_view(self, body_id: CelestialBodyId, *, founding_context_id: str = "") -> NonSurfaceFoundingView:
        """Scoped physical orbital targets; economic state exists only after founding."""
        sim = self._simulation
        contexts = []
        for node in sorted(
            (row for row in sim.graph.nodes.values() if row.body_id == body_id),
            key=lambda row: str(row.id),
        ):
            operational = sim.graph.has_operational_node(node.id)
            candidates = []
            if (not operational and sim.founding is not None
                and founding_context_id == str(node.id)):
                target = NonSurfaceOperationalNodeTargetSpec(node.id)
                active = sim.founding.active_project_for_target_node(node.id)
                for staging_id in sorted(sim.graph.operational_node_ids(), key=str):
                    for recipe in sorted(sim.founding.deployment_recipes.values(), key=lambda row: str(row.id)):
                        for vehicle in sim.transport.vehicle_definitions():
                            failures = sim.founding.planning_failures(
                                staging_id, target, recipe.id, vehicle.id, sim.day,
                            )
                            try:
                                movement = sim.founding.movement_plan_for_target(
                                    staging_id, target, vehicle.id, recipe.payload_t_per_unit, sim.day,
                                )
                                transit = sim.transport.performance_movement_transit_days(
                                    movement, vehicle.performance,
                                )
                                required = sim.founding.resource_requirements_for(
                                    recipe.id, vehicle.id, staging_id, target, day=sim.day,
                                )
                            except (KeyError, ValueError):
                                transit = None
                                required = recipe.payload_resources
                            candidates.append(FoundingOption(
                                staging_node_id=str(staging_id),
                                deployment_recipe_id=str(recipe.id),
                                recipe_display_name=recipe.display_name,
                                deployed_facilities=self._founding_deployed_facility_rows(recipe, node.id),
                                vehicle_definition_id=str(vehicle.id),
                                vehicle_display_name=vehicle.display_name,
                                preparation_work=recipe.preparation_work,
                                transit_days=transit,
                                payload_t=recipe.payload_t,
                                payload_t_per_unit=recipe.payload_t_per_unit,
                                required_units=recipe.required_units,
                                resources=tuple((str(req.resource_id), req.amount_t) for req in required),
                                blockers=constraints_from_pairs(
                                    tuple((failure.code, failure.detail) for failure in failures),
                                    affected_action="plan_founding",
                                    related_entity_kind="non_surface_spatial_node",
                                    related_entity_id=str(node.id),
                                ),
                                can_plan=not failures,
                                active_project_id=None if active is None else str(active.id),
                                comparison_key=f"{node.id}|{staging_id}|{recipe.id}|{vehicle.id}",
                            ))
            contexts.append(NonSurfaceFoundingContextRow(
                str(node.id), node.display_name, node.kind.value, operational,
                tuple(candidates),
            ))
        return NonSurfaceFoundingView(str(body_id), tuple(contexts))

    def _surface_map_view(self, body_id: CelestialBodyId, *, founding_cell_ids: tuple[str, ...] = ()) -> SurfaceMapView:
        sim = self._simulation
        body = sim.graph.bodies[body_id]
        cells = sim.graph.cells_for_body(body_id)
        if not cells:
            # An absent physical surface and an unregistered Cell topology are
            # distinct states. Neither warrants an all-world decision snapshot.
            return SurfaceMapView(
                str(body.id), body.display_name, (), (), physical_surface=body.physical_surface.value,
            )
        decision = self._tick_decision_projection()
        powers = decision.allocations.power_by_location
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
        founding_comparison_values: list[tuple[ComparisonValueRow, ...]] = []
        # Survey targets are static; index only once for this map projection.
        # Per-Cell scans of all World targets make geographic resolution an
        # accidental UI cost and risk encouraging unrealistically few Cells.
        survey_resources_by_cell = {}
        if sim.survey is not None:
            for cell_id, resource_id in sim.survey.targets:
                if sim.graph.surface_cells[cell_id].body_id == body_id:
                    survey_resources_by_cell.setdefault(cell_id, []).append(resource_id)
        # Materials belong to the Operational Node, not each Surface Cell.
        # Several Cell candidates at the same owner share one preview; local
        # physical effects and site blockers still use the selected Cell.
        placement_materials = {}
        engineering_recipes = sim.projects.terrain_engineering_recipes()
        for cell in cells:
            owner = sim.graph.owner_of_cell(cell.id)
            terrain_quality = sim.surface_knowledge.attribute_level(cell.id, "terrain")
            environment_quality = sim.surface_knowledge.attribute_level(cell.id, "environment")
            # Published geography is intentionally distinct from the physical
            # World used for executable eligibility and resource settlement.
            terrain_profile = sim.graph.terrain_profile(cell.id)
            public_terrain = (
                (("terrain_profile", terrain_profile.display_name),
                 ("development_work_factor", terrain_profile.development_work_factor),
                 ("excavation_accessibility", terrain_profile.excavation_accessibility),
                 ("engineered", float(cell.id in sim.graph.engineered_terrain)))
                if terrain_quality >= 2 else sim.surface_knowledge.terrain_overview(cell.id)
            )
            public_environment = self._environment_rows(cell.id) if environment_quality >= 2 else ()

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
                unpublished = (
                    sim.surface_knowledge.unpublished_site_condition_codes(
                        cell.id, development_recipe.site_requirements
                    ) if development_recipe is not None else frozenset()
                )
                public_failures = tuple(f for f in failures if f.code not in unpublished)
                blockers = tuple((failure.code, failure.detail) for failure in public_failures)
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
                    active_development_capacity = 0.0
                    if (active_spatial_project is not None
                            and active_spatial_project.operational_node_id == location.operational_node_id
                            and isinstance(active_spatial_project.target, SurfaceCellDevelopmentTarget)
                            and active_spatial_project.target.cell_id == cell.id):
                        bundle_id = sim.projects.construction_execution_bundle_id(active_spatial_project.id)
                        try:
                            fulfillment = decision.allocations.execution.fulfillment(bundle_id)
                        except KeyError:
                            fulfillment = 0.0
                        active_development_capacity = fulfillment * next(
                            (amount for service_type, amount in
                             sim.projects.project_service_requirement_forecast(active_spatial_project)
                             if service_type == sim.surface_infrastructure.service_type), 0.0,
                        )
                    projected = sim.surface_infrastructure.prospective_development_snapshot(
                        location.operational_node_id, cell.id, decision.allocations.services,
                        active_development_capacity=active_development_capacity,
                        day=sim.day,
                    )
                    projected_demand = projected.demand
                    projected_fulfillment = projected.fulfillment
                    limiting_factors = projected.limiting_factors
                development_options_list.append(
                    SurfaceCellDevelopmentOption(
                        location_id=str(location.operational_node_id),
                        blockers=constraints_from_pairs(
                            blockers,
                            affected_action="develop_surface_cell",
                            related_entity_kind="surface_cell",
                            related_entity_id=str(cell.id),
                        ),
                        can_plan=not sim.projects.surface_cell_development_plan_failures(
                            location.operational_node_id, cell.id, sim.day, location_power
                        ),
                        site_knowledge_unverified=bool(unpublished),
                        projected_surface_infrastructure_demand=projected_demand,
                        projected_surface_infrastructure_fulfillment=projected_fulfillment,
                        limiting_factors=limiting_factors_from_codes(
                            limiting_factors,
                            affected_action="develop_surface_cell",
                            related_entity_kind="surface_cell",
                            related_entity_id=str(cell.id),
                        ),
                        construction_required=(
                            None if development_recipe is None or terrain_quality < 2
                            else sim.projects.development_work_required(development_recipe.id, cell.id)
                        ),
                        resources=() if development_recipe is None else tuple(
                            (str(req.resource_id), req.amount_t) for req in development_recipe.resources
                        ),
                        active_project_id=None if active_spatial_project is None else str(active_spatial_project.id),
                        procurement_policy_options=tuple(sim.projects.procurement_policy_options()),
                    )
                )
            development_options = tuple(development_options_list)
            engineering_options_list = []
            if owner is not None:
                active = sim.projects.active_spatial_project_for_cell(cell.id)
                for engineering_recipe in engineering_recipes:
                    # All authored landform outcomes share one Project and
                    # Domain eligibility path; UI never derives terrain rules.
                    failures = sim.projects.surface_cell_engineering_failures(
                        owner, cell.id, engineering_recipe.id, sim.day
                    )
                    unpublished = sim.surface_knowledge.unpublished_site_condition_codes(
                        cell.id, engineering_recipe.site_requirements
                    )
                    public_failures = tuple(
                        row for row in failures
                        if row.code not in unpublished
                        and not (terrain_quality < 2 and row.code == "already_engineered")
                    )
                    engineering_options_list.append(SurfaceCellDevelopmentOption(
                        location_id=str(owner),
                        blockers=constraints_from_pairs(
                            tuple((row.code, row.detail) for row in public_failures), affected_action="engineer_surface_cell",
                            related_entity_kind="surface_cell", related_entity_id=str(cell.id),
                        ),
                        can_plan=not sim.projects.surface_cell_engineering_plan_failures(
                            owner, cell.id, engineering_recipe.id, sim.day
                        ),
                        site_knowledge_unverified=bool(unpublished) or terrain_quality < 2,
                        construction_required=(None if terrain_quality < 2 else
                            sim.projects.development_work_required(engineering_recipe.id, cell.id)),
                        resources=tuple((str(r.resource_id), r.amount_t) for r in engineering_recipe.resources),
                        active_project_id=None if active is None else str(active.id),
                        procurement_policy_options=tuple(sim.projects.procurement_policy_options()),
                        recipe_id=str(engineering_recipe.id),
                        recipe_display_name=engineering_recipe.display_name,
                        target_profile_display_name=sim.graph.terrain_profiles[
                            engineering_recipe.target_terrain_profile_id
                        ].display_name,
                    ))
            engineering_options = tuple(engineering_options_list)
            resources = ()
            if sim.survey is not None:
                resources = tuple(
                    SurfaceResourceKnowledgeRow(
                        str(resource_id),
                        self._resource_name(resource_id),
                        sim.surface_knowledge.knowledge_level(cell.id, resource_id),
                        sim.surface_knowledge.visible_presence_probability(cell.id, resource_id),
                        sim.surface_knowledge.visible_potential(cell.id, resource_id),
                        sim.surface_knowledge.visible_potential_precision_fraction(cell.id, resource_id),
                    )
                    for resource_id in sorted(survey_resources_by_cell.get(cell.id, ()), key=str)
                )
            facility_placement_options = ()
            if owner is not None:
                power = powers[owner]
                candidates = []
                for recipe in sorted(sim.projects.recipes.values(), key=lambda row: str(row.facility_def_id)):
                    if sim.facilities.definitions[recipe.facility_def_id].placement_scope is not FacilityPlacementScope.SURFACE_CELL:
                        continue
                    material_key = (owner, recipe.facility_def_id)
                    if material_key not in placement_materials:
                        placement_materials[material_key] = self._construction_resource_options(
                            recipe, owner, decision.allocations.transport
                        )
                    materials, readiness_day = placement_materials[material_key]
                    definition = sim.facilities.definitions[recipe.facility_def_id]
                    unpublished = sim.surface_knowledge.unpublished_site_condition_codes(
                        cell.id, definition.installation_requirements, recipe.site_requirements,
                    )
                    blockers = tuple(
                        ("technology", str(technology))
                        for technology in sorted(
                            recipe.prerequisite_technologies - sim.projects.unlocked_technologies,
                            key=str,
                        )
                    ) + tuple(
                        (failure.code, failure.detail)
                        for failure in sim.projects.site_failures(
                            recipe.facility_def_id, owner, sim.day, power, site_cell_id=cell.id
                        ) if failure.code not in unpublished
                    )
                    candidates.append(SurfaceFacilityPlacementOption(
                        facility_definition_id=str(recipe.facility_def_id),
                        display_name=sim.facilities.definitions[recipe.facility_def_id].display_name,
                        location_id=str(owner),
                        construction_required=recipe.construction_work,
                        self_deploying=recipe.self_deploying,
                        resources=materials,
                        blockers=constraints_from_pairs(
                            blockers,
                            affected_action="plan_surface_facility",
                            related_entity_kind="facility_definition",
                            related_entity_id=str(recipe.facility_def_id),
                        ),
                        can_plan=not sim.projects.build_plan_failures(
                            recipe.facility_def_id, owner, site_cell_id=cell.id
                        ),
                        site_knowledge_unverified=bool(unpublished),
                        procurement_policy_options=tuple(sim.projects.procurement_policy_options()),
                        projected_material_readiness_day=readiness_day,
                        **self._surface_facility_public_effects(
                            recipe, cell.id, terrain_quality >= 2 and environment_quality >= 2
                        ),
                    ))
                facility_placement_options = tuple(candidates)
            foundation_options = ()
            movement_accessible = None
            minimum_transit_days = None
            if (sim.founding is not None and str(cell.id) in founding_cell_ids):
                movement_accessible = False
                foundation_rows = []
                active_founding = sim.founding.active_project_for_cell(cell.id)
                for staging_id in sorted(sim.graph.operational_node_ids(), key=str):
                    target_spec = sim.founding.surface_target_spec(body_id, cell.id)
                    for recipe in sorted(sim.founding.deployment_recipes.values(), key=lambda row: str(row.id)):
                        for vehicle in sim.transport.vehicle_definitions():
                            failures = sim.founding.planning_failures(
                                staging_id, target_spec, recipe.id, vehicle.id, sim.day
                            )
                            unpublished = sim.surface_knowledge.unpublished_site_condition_codes(
                                cell.id, recipe.target_requirements,
                            )
                            unverified_facility = (environment_quality < 2 and any(
                                sim.facilities.definitions[deployment.facility_def_id].installation_requirements.environment
                                for deployment in recipe.deployed_facilities
                            ))
                            # Intent eligibility cannot depend on hidden physical
                            # conditions. Known runtime Site incompatibility is
                            # still visible, but can_plan describes only planning.
                            runtime_failures = sim.founding.target_settlement_failures(
                                target_spec, recipe, "Founding preview", sim.day,
                            )
                            public_failures = tuple(failure for failure in (*failures, *runtime_failures)
                                if failure.code not in {f"target:{code}" for code in unpublished}
                                and (environment_quality >= 2 or failure.code != "facility_environment"))
                            public_failures = tuple(dict.fromkeys(public_failures))
                            try:
                                movement_plan = sim.founding.movement_plan_for_target(
                                    staging_id, target_spec, vehicle.id, recipe.payload_t_per_unit, sim.day
                                )
                                transit_days = sim.transport.performance_movement_transit_days(
                                    movement_plan, vehicle.performance
                                )
                                movement_accessible = True
                                minimum_transit_days = (
                                    transit_days
                                    if minimum_transit_days is None
                                    else min(minimum_transit_days, transit_days)
                                )
                                founding_resources = sim.founding.resource_requirements_for(
                                    recipe.id, vehicle.id, staging_id, target_spec, day=sim.day
                                )
                            except (KeyError, ValueError):
                                transit_days = None
                                founding_resources = recipe.payload_resources
                            comparison_values = (
                                ComparisonValueRow(
                                    axis_key="transit_days",
                                    number_value=None if transit_days is None else float(transit_days),
                                ),
                                ComparisonValueRow(
                                    axis_key="preparation_work", number_value=recipe.preparation_work
                                ),
                                ComparisonValueRow(axis_key="payload_t", number_value=recipe.payload_t),
                                ComparisonValueRow(
                                    axis_key="development_work_factor",
                                    number_value=terrain_profile.development_work_factor if terrain_quality >= 2 else None,
                                ),
                                ComparisonValueRow(
                                    axis_key="excavation_accessibility",
                                    number_value=terrain_profile.excavation_accessibility if terrain_quality >= 2 else None,
                                ),
                            )
                            foundation_rows.append(FoundingOption(
                                staging_node_id=str(staging_id),
                                deployment_recipe_id=str(recipe.id),
                                recipe_display_name=recipe.display_name,
                                deployed_facilities=self._founding_deployed_facility_rows(
                                    recipe, cell.id, environment_known=environment_quality >= 2
                                ),
                                vehicle_definition_id=str(vehicle.id),
                                vehicle_display_name=vehicle.display_name,
                                preparation_work=recipe.preparation_work,
                                transit_days=transit_days,
                                payload_t=recipe.payload_t,
                                payload_t_per_unit=recipe.payload_t_per_unit,
                                required_units=recipe.required_units,
                                resources=tuple(
                                    (str(req.resource_id), req.amount_t) for req in founding_resources
                                ),
                                blockers=constraints_from_pairs(
                                    tuple((failure.code, failure.detail) for failure in public_failures),
                                    affected_action="plan_founding",
                                    related_entity_kind="surface_cell",
                                    related_entity_id=str(cell.id),
                                ),
                                can_plan=not failures,
                                site_knowledge_unverified=bool(unpublished) or unverified_facility,
                                active_project_id=None if active_founding is None else str(active_founding.id),
                                comparison_key=(
                                    f"{cell.id}|{staging_id}|{recipe.id}|{vehicle.id}"
                                ),
                                comparison_values=comparison_values,
                            ))
                            if owner is None:
                                founding_comparison_values.append(comparison_values)
                foundation_options = tuple(foundation_rows)


            rows.append(
                SurfaceCellRow(
                    str(cell.id),
                    str(cell.body_id),
                    cell.area_km2,
                    cell.centroid.latitude_deg,
                    cell.centroid.longitude_deg,
                    tuple(sorted(map(str, cell.neighbor_ids))),
                    public_terrain,
                    public_environment,
                    resources,
                    owner is not None,
                    None if owner is None else str(owner),
                    owner_state is not None and owner_state.core_cell_id == cell.id,
                    constraints_from_pairs(
                        sim.graph.location_foundation_failures(body_id, cell.id),
                        affected_action="plan_founding",
                        related_entity_kind="surface_cell",
                        related_entity_id=str(cell.id),
                    ),
                    development_options,
                    engineering_options,
                    facility_placement_options,
                    foundation_options,
                    cell.display_name or str(cell.id),
                    terrain_knowledge_level=terrain_quality,
                    environment_knowledge_level=environment_quality,
                    geology_knowledge_level=sim.surface_knowledge.attribute_level(cell.id, "geology"),
                    geology=sim.surface_knowledge.visible_geology(cell.id),
                    movement_accessible=movement_accessible,
                    minimum_transit_days=minimum_transit_days,
                )
            )
        founding_comparison_axes = project_comparison_axes(
            (
                ("transit_days", "移動時間", "integer", "日"),
                ("preparation_work", "準備工数", "number", None),
                ("payload_t", "搭載量", "number", "t"),
                ("development_work_factor", "地表施工負担", "number", None),
                ("excavation_accessibility", "掘削アクセス", "number", None),
            ),
            founding_comparison_values,
        )
        return SurfaceMapView(
            str(body.id), body.display_name, tuple(rows), locations, founding_comparison_axes,
            body.physical_surface.value,
        )

from __future__ import annotations

from stock_support import service_target_for_test_units

import pytest

from space_idle import (
    AdvanceTime,
    DevelopSurfaceCell,
    GetLogistics,
    GetSurfaceMap,
    GetOperationalNode,
    GetProjects,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.surface_infrastructure import SURFACE_DISTRIBUTION_SERVICE
from space_idle.service_capacity import allocate_service_capacity


def _ensure_project_materials_on_hand(sim, *project_ids: str) -> None:
    required = {}
    for project_id in project_ids:
        project = next(
            row for row in sim.projects.projects.values()
            if str(row.id) == project_id
        )
        recipe = sim.projects.recipe_for_project(project)
        for requirement in recipe.resources:
            key = (project.operational_node_id, requirement.resource_id)
            required[key] = required.get(key, 0.0) + requirement.amount_t
    for (node_id, resource_id), amount_t in required.items():
        sim.inventory.stock[(node_id, resource_id)] = max(
            sim.inventory.amount(node_id, resource_id), amount_t
        )


def _snapshot(sim, maintenance_factors=None):
    physical = sim.power.physical_snapshot(ids.EARTH, sim.facilities, sim.day)
    power = sim.power.resolve_snapshot(physical, maintenance_factors)
    request = sim.surface_infrastructure.service_request(ids.EARTH)
    key = (ids.EARTH, sim.surface_infrastructure.service_type)
    nominal, enabled = sim.service_capacity_registry.supply_at(
        ids.EARTH, key[1], sim.facilities, power, sim.day
    )
    plan = allocate_service_capacity(
        (request,), nominal_supply={key: nominal}, enabled_supply={key: enabled}
    )
    return sim.surface_infrastructure.snapshot(
        ids.EARTH, sim.facilities, power, sim.day, allocation_plan=plan
    )


def test_surface_infrastructure_load_and_supply_scale_with_territory_and_provider_health():
    sim = build_game_application()._simulation
    initial = _snapshot(sim)
    assert initial.demand == 0.0
    assert initial.fulfillment == 1.0

    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    one_remote = _snapshot(sim)
    assert one_remote.demand > initial.demand
    assert one_remote.nominal_capacity == pytest.approx(0.0)
    assert one_remote.available_capacity == pytest.approx(0.0)
    assert one_remote.fulfillment == pytest.approx(0.0)
    assert one_remote.limiting_factors == ("surface_infrastructure",)
    assert any(row.code == "activity_distance" for row in one_remote.load_sources)
    assert ids.EARTH_CELL_COASTAL not in sim.graph.operational_node_ids()
    assert all(
        location_id != ids.EARTH_CELL_COASTAL
        for location_id, _resource_id in sim.inventory.stock
    )
    assert SURFACE_DISTRIBUTION_SERVICE in sim.facilities.service_types()

    facility_id = sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    supplied = _snapshot(sim)
    assert supplied.nominal_capacity > 0.0
    assert supplied.available_capacity == pytest.approx(supplied.nominal_capacity)
    assert supplied.fulfillment == pytest.approx(
        min(1.0, supplied.available_capacity / supplied.demand)
    )

    degraded = _snapshot(sim, {facility_id: 0.5})
    assert degraded.nominal_capacity == pytest.approx(supplied.nominal_capacity)
    assert degraded.available_capacity == pytest.approx(supplied.available_capacity * 0.5)
    assert degraded.fulfillment == pytest.approx(
        min(1.0, degraded.available_capacity / degraded.demand)
    )
    assert degraded.fulfillment < supplied.fulfillment
    assert degraded.limiting_factors == ("surface_infrastructure",)

    # Territory grows by actual shared boundaries, not by the labels of
    # sparse geographic references in an earlier incomplete map.
    frontier = sorted(
        {neighbor for developed_id in sim.graph.locations[ids.EARTH].developed_cell_ids
         for neighbor in sim.graph.surface_cells[developed_id].neighbor_ids
         if neighbor not in sim.graph.locations[ids.EARTH].developed_cell_ids}
    )
    assert frontier
    sim.graph.develop_surface_cell(ids.EARTH, frontier[0])
    two_remote = _snapshot(sim)
    # Unused territory itself has no ongoing distribution Activity.
    assert two_remote.demand == pytest.approx(supplied.demand)
    remote_facility_id = sim.facilities.install(
        ids.SURFACE_POWER_GRID, ids.EARTH, site_cell_id=frontier[0],
    )
    expanded = _snapshot(sim)
    assert expanded.demand > two_remote.demand
    assert expanded.nominal_capacity == pytest.approx(supplied.nominal_capacity)
    # Additional installed units increase real remote Activity, not cell count.
    sim.facilities.upgrade_to(remote_facility_id, 2)
    doubled = _snapshot(sim)
    assert doubled.demand == pytest.approx(expanded.demand + (expanded.demand - two_remote.demand))
    sim.facilities.pause(remote_facility_id)
    assert _snapshot(sim).demand == pytest.approx(two_remote.demand)
    sim.facilities.resume(remote_facility_id)
    assert _snapshot(sim).demand == pytest.approx(doubled.demand)


def test_cell_physical_opportunity_is_independent_of_surface_infrastructure_and_execution_is_limited_once():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]

    core = sim.graph.surface_cells[ids.EARTH_CELL_INDUSTRIAL].resource_potential_by_resource[ids.METAL_ORE]
    remote = sim.graph.surface_cells[ids.EARTH_CELL_COASTAL].resource_potential_by_resource[ids.METAL_ORE]
    opportunity = sim.extraction.effective_opportunity(
        ids.EARTH, ids.METAL_ORE, sim.facilities, power, sim.day,
        decision.allocations.services,
    )
    core_access = sim.graph.terrain_profile(ids.EARTH_CELL_INDUSTRIAL).excavation_accessibility
    remote_access = sim.graph.terrain_profile(ids.EARTH_CELL_COASTAL).excavation_accessibility
    physical_opportunity = core * core_access + remote * remote_access
    assert opportunity == pytest.approx(physical_opportunity)
    constrained = next(
        row for row in sim.extraction.snapshots(
            ids.EARTH, sim.facilities, sim.inventory, power, sim.day,
            decision.allocations.execution,
        )
        if row.facility_def_id == ids.METAL_ORE_MINE
    )
    assert constrained.scale == 0.0
    assert constrained.effective_opportunity == pytest.approx(physical_opportunity)
    assert "service_capacity" in constrained.limiting_factors

    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    supplied = next(
        row for row in sim.extraction.snapshots(
            ids.EARTH, sim.facilities, sim.inventory, power, sim.day,
            decision.allocations.execution,
        )
        if row.facility_def_id == ids.METAL_ORE_MINE
    )
    assert supplied.effective_opportunity == pytest.approx(physical_opportunity)
    infrastructure = sim.surface_infrastructure.snapshot(
        ids.EARTH, sim.facilities, power, sim.day,
        allocation_plan=decision.allocations.services,
    )
    assert supplied.scale == pytest.approx(infrastructure.fulfillment)
    assert 0 < supplied.scale <= 1.0
    assert supplied.limiting_factors == (() if infrastructure.fulfillment == 1.0 else ("service_capacity",))


def test_location_query_exposes_surface_infrastructure_decision_state_and_improvement():
    app = build_game_application()
    sim = app._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)

    view = app.query(GetOperationalNode(str(ids.EARTH)))
    row = view.surface_infrastructure
    assert row is not None
    assert row.requested_capacity > 0.0
    assert row.fulfillment == 0.0
    assert tuple(factor.code for factor in row.limiting_factors) == ("surface_infrastructure",)
    assert str(ids.SURFACE_DISTRIBUTION_HUB) in row.improvement_facility_definition_ids

    spatial = view.surface_location
    assert spatial is not None
    assert spatial.core_cell_id == str(ids.EARTH_CELL_INDUSTRIAL)
    assert spatial.developed_cell_ids == (
        str(ids.EARTH_CELL_COASTAL),
        str(ids.EARTH_CELL_INDUSTRIAL),
    )
    assert any(anchor.cell_id == str(ids.EARTH_CELL_INDUSTRIAL) for anchor in spatial.active_access_anchors)
    illumination = next(summary for summary in spatial.environment_summary if summary.key == "illumination")
    assert illumination.location_values == ()
    assert {cell_id for cell_id, _values in illumination.cell_values} == {
        str(ids.EARTH_CELL_COASTAL),
        str(ids.EARTH_CELL_INDUSTRIAL),
    }
    # The same Location projection must not expose a newly developed Cell's
    # physical values until the Knowledge owner records a real observation.
    occupied = sim.graph.locations[ids.EARTH].developed_cell_ids
    frontier = next(
        candidate for owner in sorted(occupied, key=str)
        for candidate in sorted(sim.graph.surface_cells[owner].neighbor_ids, key=str)
        if candidate not in occupied
        and sim.surface_knowledge.attribute_level(candidate, "environment") == 0
    )
    sim.graph.develop_surface_cell(ids.EARTH, frontier)
    unknown = app.query(GetOperationalNode(str(ids.EARTH)))
    unknown_illumination = next(summary for summary in unknown.surface_location.environment_summary
                                if summary.key == "illumination")
    assert dict(unknown_illumination.cell_values)[str(frontier)] == ()
    assert unknown.environment == ()
    sim.surface_knowledge.observe_attribute(frontier, "environment", 2)
    disclosed = app.query(GetOperationalNode(str(ids.EARTH)))
    fresh = next(summary for summary in disclosed.surface_location.environment_summary
                 if summary.key == "illumination")
    assert dict(fresh.cell_values)[str(frontier)]


def test_surface_infrastructure_limits_remote_service_execution_without_disabling_capability():
    sim = build_game_application()._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    station_id = sim.facilities.install(
        ids.ROBOTIC_GEOLOGY_STATION,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_COASTAL,
    )

    provider = sim.survey.providers[ids.ROBOTIC_GEOLOGY_STATION]
    service_type = sim.survey.service_type_for_provider(provider.id, ids.ROBOTIC_GEOLOGY_STATION)
    expected_rate = provider.capacity_units_per_source_per_day
    assert sim.facilities.installed_capability_at(ids.EARTH, "surface_survey")
    assert sim.facilities.active_capability_at(ids.EARTH, "surface_survey", sim.day)
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    assert sim.surface_infrastructure.snapshot(
        ids.EARTH, sim.facilities, power, sim.day,
        allocation_plan=decision.allocations.services,
    ).fulfillment == 0.0
    constrained = decision.allocations.services.summary(ids.EARTH, service_type)
    cargo_constrained = decision.allocations.services.summary(ids.EARTH, "cargo_transfer")
    assert constrained.nominal_rate == pytest.approx(expected_rate)
    assert constrained.enabled_rate == 0.0
    assert constrained.limiting_factors == ("provider_dependency",)
    assert cargo_constrained.nominal_rate > 0.0
    assert cargo_constrained.enabled_rate == 0.0
    assert sim.facilities.active_capability_at(ids.EARTH, "cargo_transfer", sim.day)

    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    assert sim.surface_infrastructure.snapshot(
        ids.EARTH, sim.facilities, power, sim.day,
        allocation_plan=decision.allocations.services,
    ).fulfillment > 0.0
    supplied = decision.allocations.services.summary(ids.EARTH, service_type)
    cargo_supplied = decision.allocations.services.summary(ids.EARTH, "cargo_transfer")
    assert supplied.nominal_rate == pytest.approx(expected_rate)
    infra = sim.surface_infrastructure.snapshot(
        ids.EARTH, sim.facilities, power, sim.day,
        allocation_plan=decision.allocations.services,
    )
    assert supplied.enabled_rate == pytest.approx(expected_rate * infra.fulfillment)
    assert supplied.limiting_factors == (() if infra.fulfillment == 1.0 else ("provider_dependency",))
    assert cargo_supplied.enabled_rate > 0.0
    assert sim.facilities.active_capability_at(ids.EARTH, "surface_survey", sim.day)
    assert sim.facilities.active_capability_at(ids.EARTH, "cargo_transfer", sim.day)
    assert station_id in sim.facilities.facilities

def test_surface_cell_development_projection_execution_and_completion_share_one_infrastructure_contract():
    app = build_game_application()
    sim = app._simulation

    surface = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
    coastal = next(cell for cell in surface.cells if cell.id == str(ids.EARTH_CELL_COASTAL))
    option = next(row for row in coastal.development_options if row.location_id == str(ids.EARTH))
    assert option.blockers == ()
    assert option.can_plan
    assert option.projected_surface_infrastructure_demand is not None
    assert option.projected_surface_infrastructure_demand > 0.0
    assert option.projected_surface_infrastructure_fulfillment == 0.0
    assert tuple(factor.code for factor in option.limiting_factors) == ("surface_infrastructure",)
    # Geography has operational meaning beyond map decoration: two adjacent
    # development choices with different landforms require different
    # real Construction work. Unobserved work remains hidden in Map preview.
    frontier = tuple(sorted(
        candidate for candidate in sim.graph.surface_cells[ids.EARTH_CELL_INDUSTRIAL].neighbor_ids
        if candidate != ids.EARTH_CELL_COASTAL
    ))
    other = frontier[0]
    # Vary the physical input in this isolated Game State, rather than
    # freezing a particular authored regional value as a Core test contract.
    from dataclasses import replace
    original_cell = sim.graph.surface_cells[other]
    from space_idle.spatial import SurfaceTerrain
    coast_work_factor = sim.graph.terrain_profile(ids.EARTH_CELL_COASTAL).development_work_factor
    new_profile_id = next(
        key for key, profile in sim.graph.terrain_profiles.items()
        if profile.development_work_factor != coast_work_factor
    )
    sim.graph.surface_cells[other] = replace(
        original_cell, terrain=SurfaceTerrain(new_profile_id),
    )
    unknown = next(cell for cell in surface.cells if cell.id == str(other))
    assert next(row for row in unknown.development_options
                if row.location_id == str(ids.EARTH)).construction_required is None
    sim.surface_knowledge.observe_attribute(other, "terrain", 2)
    known_surface = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
    known = next(cell for cell in known_surface.cells if cell.id == str(other))
    known_option = next(row for row in known.development_options
                        if row.location_id == str(ids.EARTH))
    assert known_option.construction_required != option.construction_required
    assert known_option.construction_required == pytest.approx(
        sim.projects.development_work_required(sim.projects.surface_cell_development_recipe_id, other)
    )

    project_id = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), procurement_policy="extended_wait"
    )).created_id
    assert project_id is not None
    project_state = next(row for row in sim.projects.projects.values() if str(row.id) == project_id)
    assert sim.projects.recipe_for_project(project_state).construction_work == pytest.approx(
        option.construction_required
    )
    _ensure_project_materials_on_hand(sim, project_id)
    assert ids.EARTH_CELL_COASTAL not in sim.graph.locations[ids.EARTH].developed_cell_ids

    app.execute(AdvanceTime(1))
    project = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert project.construction_done == 0.0
    assert project.construction_required == pytest.approx(option.construction_required)
    assert project.construction_fulfillment == 0.0
    assert tuple(factor.code for factor in project.limiting_factors) == ("surface_infrastructure",)
    assert ids.EARTH_CELL_COASTAL not in sim.graph.locations[ids.EARTH].developed_cell_ids

    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    decision = sim.tick_decision_projection()
    bundle_id = sim.projects.construction_execution_bundle_id(project_id)
    bundle = next(
        row for row in decision.allocations.execution.bundles if row.id == bundle_id
    )
    assert any(
        key.kind == "service" and key.name == sim.surface_infrastructure.service_type
        for key, _coefficient in bundle.coefficients()
    )
    projected = decision.allocations.execution.fulfillment(bundle_id)
    assert projected > 0.0
    # An already-running Project draws the incremental Surface Service from
    # its Execution Bundle. Preview must neither invent a removed service
    # request nor hide that capacity as if it were unavailable.
    active_cell = next(row for row in app.query(GetSurfaceMap(str(ids.EARTH_BODY))).cells
                       if row.id == str(ids.EARTH_CELL_COASTAL))
    active_option = next(row for row in active_cell.development_options
                         if row.location_id == str(ids.EARTH))
    assert active_option.projected_surface_infrastructure_fulfillment > 0.0

    app.execute(AdvanceTime(1))
    project_view = next(row for row in app.query(GetProjects()).items if row.id == project_id)
    assert project_view.construction_done > 0.0
    assert project_view.construction_fulfillment > 0.0
    assert all(factor.code != "surface_infrastructure" for factor in project_view.limiting_factors)
    assert ids.EARTH_CELL_COASTAL not in sim.graph.locations[ids.EARTH].developed_cell_ids

    project_state = next(row for row in sim.projects.projects.values() if str(row.id) == project_id)
    while project_state.status.value != "complete":
        before = (
            project_state.status,
            project_state.construction_done,
            project_state.materials_committed,
        )
        app.execute(AdvanceTime(1))
        after = (
            project_state.status,
            project_state.construction_done,
            project_state.materials_committed,
        )
        assert after != before, "ready surface development made no canonical-tick progress"

    assert ids.EARTH_CELL_COASTAL in sim.graph.locations[ids.EARTH].developed_cell_ids


def test_remote_surface_movement_capacity_uses_location_surface_infrastructure():
    from space_idle.shared import SpatialNodeId
    app = build_game_application()
    sim = app._simulation
    a = SpatialNodeId("test.location.infrastructure.a")
    b = SpatialNodeId("test.location.infrastructure.b")
    sim.graph.found_location(a, "A", ids.MOON, ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    sim.graph.found_location(b, "B", ids.MOON, ids.MOON_CELL_NEARSIDE_MARE)
    sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, a)
    sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, b)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, a, site_cell_id=ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, b, site_cell_id=ids.MOON_CELL_NEARSIDE_MARE)
    sim.transport.add_fleet_units(ids.SURFACE_CARGO_HAULER, 1, a)
    sim.transport.invalidate_movement_plans()
    allocation_id = sim.transport.create_transport_allocation(
        ids.SURFACE_CARGO_HAULER, a, b,
        target_capacity=service_target_for_test_units(
            sim.transport,
            ids.SURFACE_CARGO_HAULER, a, b, 1, day=sim.day
        ),
        day=sim.day,
    )
    initial = sim.transport.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert initial.nominal.forward_t_per_day > 0.0
    assert initial.available.forward_t_per_day == pytest.approx(initial.nominal.forward_t_per_day)

    sim.graph.develop_surface_cell(a, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    # The registered geography is a complete global partition: a distant
    # equatorial named region is not assumed adjacent to the polar plain.
    polar_neighbors = sim.graph.surface_cells[ids.MOON_CELL_SOUTH_POLAR_PLAIN].neighbor_ids
    next_cell = next(cell for cell in sorted(polar_neighbors)
                     if cell not in sim.graph.locations[a].developed_cell_ids
                     and sim.graph.owner_of_cell(cell) is None)
    sim.graph.develop_surface_cell(a, next_cell)
    # Merely declaring an unoccupied territory does not consume distribution.
    assert sim.surface_infrastructure.demand(a) == 0.0
    # Actual active equipment in a remote Cell creates finite local distribution
    # work, regardless of whether the Cell hosts extraction or a site facility.
    sim.facilities.install(ids.SURFACE_POWER_GRID, a, site_cell_id=next_cell)
    # A provider-constrained scenario must remain constrained independent of
    # Content's current hub rate and the selected body's physical cell area.
    from dataclasses import replace
    from space_idle.facilities import ServiceCapacitySupply
    hub = sim.facilities.definitions[ids.SURFACE_DISTRIBUTION_HUB]
    expected_load = sim.surface_infrastructure.demand(a)
    assert expected_load > 0
    sim.facilities.definitions[ids.SURFACE_DISTRIBUTION_HUB] = replace(
        hub, service_capacity_supplies=tuple(
            ServiceCapacitySupply(row.service_type, expected_load / 2)
            if row.service_type == 'surface_distribution' else row
            for row in hub.service_capacity_supplies
        ),
    )
    sim.transport.invalidate_movement_plans()
    physical = sim.transport.transport_capacity_snapshot(allocation_id, day=sim.day)
    assert physical.available.forward_t_per_day == pytest.approx(physical.nominal.forward_t_per_day)
    decision = sim.tick_decision_projection()
    constrained = sim.logistics.current_transport_capacity_snapshot(
        allocation_id, day=sim.day,
        execution_allocation=decision.allocations.transport,
    )
    assert 0.0 < constrained.available.forward_t_per_day < constrained.nominal.forward_t_per_day
    assert any(factor.startswith("surface_infrastructure:") for factor in constrained.limiting_factors)

    allocation = next(
        row for row in app.query(GetLogistics()).allocations if row.id == str(allocation_id)
    )
    assert allocation.available.forward_t_per_day == pytest.approx(
        constrained.available.forward_t_per_day
    )


def test_surface_spatial_intents_wait_for_real_environment_without_disclosing_unmeasured_truth():
    """Development and engineering select a place, then obey its physical Site constraints."""
    from dataclasses import replace
    from space_idle import EngineerSurfaceCell
    from space_idle.site import FacetValueRange, SiteRequirements
    from space_idle.spatial import ThermalField

    app = build_game_application()
    sim = app._simulation
    site_condition = FacetValueRange(
        ThermalField, "nominal_temperature_k", "test:unfavorable_temperature",
        "actual Site temperature outside permitted range", maximum=0.0,
    )
    development_id = sim.projects.surface_cell_development_recipe_id
    engineering_id = ids.SURFACE_TERRAIN_ENGINEERING_PROJECT
    assert development_id is not None
    for recipe_id in (development_id, engineering_id):
        recipe = sim.projects.spatial_recipes[recipe_id]
        sim.projects.spatial_recipes[recipe_id] = replace(
            recipe, site_requirements=replace(
                recipe.site_requirements,
                environment=recipe.site_requirements.environment + (site_condition,),
            ),
        )

    cases = (
        (ids.EARTH_CELL_COASTAL, development_id,
         lambda: app.execute(DevelopSurfaceCell(str(ids.EARTH), str(ids.EARTH_CELL_COASTAL)))),
        (ids.EARTH_CELL_INDUSTRIAL, engineering_id,
         lambda: app.execute(EngineerSurfaceCell(str(ids.EARTH), str(ids.EARTH_CELL_INDUSTRIAL), str(engineering_id)))),
    )
    for cell, recipe_id, command in cases:
        sim.surface_knowledge.cell_attribute_levels[(cell, "environment")] = 0
        sim.surface_knowledge.environment_observation_fingerprints.pop(cell, None)
        surface = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
        cell_view = next(row for row in surface.cells if row.id == str(cell))
        options = cell_view.development_options if recipe_id == development_id else cell_view.engineering_options
        option = next(row for row in options if row.location_id == str(ids.EARTH)
                      and (recipe_id == development_id or row.recipe_id == str(engineering_id)))
        assert option.can_plan and option.site_knowledge_unverified
        assert not any(row.code == site_condition.code for row in option.blockers)
        project_id = command().created_id
        assert project_id
        queued = next(row for row in app.query(GetProjects()).items if row.id == project_id)
        assert not any(row.code == site_condition.code for row in queued.blockers)
        assert any(row.code == "site_knowledge_unverified" for row in queued.blockers)
        app.execute(AdvanceTime(1))
        assert sim.projects.projects[next(key for key in sim.projects.projects if str(key) == project_id)].construction_done == 0
        sim.surface_knowledge.observe_attribute(cell, "environment", 2)
        revealed = next(row for row in app.query(GetProjects()).items if row.id == project_id)
        assert any(row.code == site_condition.code for row in revealed.blockers)


def test_surface_engineering_is_paid_physical_change_with_knowledge_and_save_continuity(tmp_path):
    """Player-initiated landform change crosses Construction, Spatial, Knowledge and Save."""
    from space_idle import EngineerSurfaceCell
    from space_idle.bootstrap import build_game_application_for_load
    from space_idle.persistence import load_game, save_game
    from space_idle.simulation import OfflineProgressPolicy

    app = build_game_application()
    sim = app._simulation
    core = ids.EARTH_CELL_INDUSTRIAL
    natural = sim.graph.surface_cells[core].terrain.profile_id
    target_recipe = sim.projects.spatial_recipes[ids.SURFACE_TERRAIN_ENGINEERING_PROJECT]
    target_profile = target_recipe.target_terrain_profile_id
    assert natural != target_profile  # Authored starter region offers a real terrain decision.
    from space_idle.api.codec import decode_command
    decoded = decode_command({
        "type": "EngineerSurfaceCell",
        "payload": {"location_id": str(ids.EARTH), "cell_id": str(core), "recipe_id": str(target_recipe.id)},
    })
    assert isinstance(decoded, EngineerSurfaceCell)
    initial_profile = sim.graph.terrain_profile(core)
    original_resource_potential = dict(sim.graph.surface_cells[core].resource_potential_by_resource)
    # The real Extraction calculation must consume the current Terrain Profile,
    # not just expose it through a Map label or a separate forecast formula.
    extraction_methods = tuple(method for method in sim.extraction.specs.values()
                               if method.resource_id == ids.METAL_ORE and method.requires_excavation_access)
    assert extraction_methods
    def physical_ore_access(game):
        return game._simulation.extraction.opportunity_for_cells(
            ids.METAL_ORE, extraction_methods, (core,), eligible=lambda _method, _cell: True,
        )
    initial_ore_access = physical_ore_access(app)
    baseline_map = next(row for row in app.query(GetSurfaceMap(str(ids.EARTH_BODY))).cells if row.id == str(core))
    choices = {option.recipe_id: option for option in baseline_map.engineering_options}
    assert len(choices) >= 2
    plan = choices[str(target_recipe.id)]
    assert plan.can_plan and not plan.blockers
    assert plan.construction_required == pytest.approx(
        target_recipe.construction_work * initial_profile.development_work_factor
    )
    project_id = app.execute(EngineerSurfaceCell(
        str(ids.EARTH), str(core), str(target_recipe.id), procurement_policy="immediate"
    )).created_id
    assert project_id is not None
    project = next(row for row in sim.projects.projects.values() if str(row.id) == project_id)
    assert sim.graph.terrain_profile(core) == initial_profile

    app.execute(AdvanceTime(4))
    assert project.status.value != "complete"
    assert sim.graph.terrain_profile(core) == initial_profile
    save_path = tmp_path / "engineer.json"
    save_game(app, save_path)
    loaded, _ = load_game(save_path, build_game_application_for_load)
    loaded_sim = loaded._simulation
    assert loaded_sim.graph.terrain_profile(core) == initial_profile
    assert loaded_sim.projects.projects[project.id].construction_done == pytest.approx(project.construction_done)

    app.execute(AdvanceTime(12))
    offline_result = loaded.advance_offline(12.0, OfflineProgressPolicy(1.0))
    assert offline_result.advanced_days == 12
    for game in (app, loaded):
        world = game._simulation.graph
        assert world.terrain_profile(core).id == target_profile
        assert world.surface_cells[core].terrain.profile_id == natural
        assert world.surface_cells[core].resource_potential_by_resource == original_resource_potential
        assert world.terrain_profile(core).excavation_accessibility > initial_profile.excavation_accessibility
        assert physical_ore_access(game) > initial_ore_access
        finished = game._simulation.projects.projects[project.id]
        assert finished.status.value == "complete"
        assert finished.construction_done == pytest.approx(plan.construction_required)
        assert finished.materials_committed
        assert game._simulation.surface_knowledge.attribute_level(core, "terrain") == 2

    # Once at the Application boundary is sufficient: both execution modes
    # already agree on authoritative terrain, Project and Knowledge state.
    cell_view = next(row for row in app.query(GetSurfaceMap(str(ids.EARTH_BODY))).cells if row.id == str(core))
    assert dict(cell_view.terrain)["terrain_profile"] == sim.graph.terrain_profile(core).display_name
    assert not {option.recipe_id: option for option in cell_view.engineering_options}[str(target_recipe.id)].can_plan
    assert len(loaded_sim.graph.locations) == len(sim.graph.locations)
    assert loaded_sim.graph.engineered_terrain == sim.graph.engineered_terrain
    save_game(loaded, save_path)
    reloaded, _ = load_game(save_path, build_game_application_for_load)
    assert reloaded._simulation.graph.terrain_profile(core).id == target_profile
    assert reloaded._simulation.surface_knowledge.attribute_level(core, "terrain") == 2

    # Two distinct authored outcomes on the SAME Cell must not corrupt prior
    # completed projects. The later Project snapshots the current, rather than
    # the original natural, landform's construction work.
    grading = reloaded._simulation.projects.spatial_recipes[ids.SURFACE_TERRAIN_GRADING_PROJECT]
    graded_work = grading.construction_work * reloaded._simulation.graph.terrain_profile(core).development_work_factor
    second_view = next(row for row in reloaded.query(GetSurfaceMap(str(ids.EARTH_BODY))).cells if row.id == str(core))
    grading_option = next(row for row in second_view.engineering_options if row.recipe_id == str(grading.id))
    assert grading_option.can_plan
    assert grading_option.recipe_display_name == grading.display_name
    assert grading_option.target_profile_display_name == reloaded._simulation.graph.terrain_profiles[
        grading.target_terrain_profile_id
    ].display_name
    assert grading_option.construction_required == pytest.approx(graded_work)
    from space_idle.app_contracts.common import ApplicationError
    with pytest.raises(ApplicationError, match="unknown terrain engineering recipe"):
        reloaded.execute(EngineerSurfaceCell(
            str(ids.EARTH), str(core), str(ids.SURFACE_CELL_DEVELOPMENT_PROJECT),
            procurement_policy="immediate",
        ))
    second_id = reloaded.execute(EngineerSurfaceCell(
        str(ids.EARTH), str(core), str(grading.id), procurement_policy="immediate"
    )).created_id
    assert second_id is not None
    second = next(p for p in reloaded._simulation.projects.projects.values() if str(p.id) == second_id)
    assert second.planned_spatial_work == pytest.approx(graded_work)
    reloaded.execute(AdvanceTime(4))
    save_game(reloaded, save_path)
    resumed, _ = load_game(save_path, build_game_application_for_load)
    resumed_second = resumed._simulation.projects.projects[second.id]
    assert resumed_second.planned_spatial_work == pytest.approx(graded_work)
    assert resumed_second.construction_done == pytest.approx(second.construction_done)
    resumed.execute(AdvanceTime(20))
    assert resumed._simulation.graph.terrain_profile(core).id == grading.target_terrain_profile_id
    assert physical_ore_access(resumed) == pytest.approx(initial_ore_access)
    assert resumed._simulation.graph.surface_cells[core].terrain.profile_id == natural
    if grading.target_terrain_profile_id == natural:
        assert core not in resumed._simulation.graph.engineered_terrain
    assert resumed._simulation.projects.projects[project.id].construction_done == pytest.approx(plan.construction_required)
    assert resumed._simulation.projects.projects[second.id].construction_done == pytest.approx(graded_work)
    assert resumed._simulation.surface_knowledge.attribute_level(core, "terrain") == 2
    save_game(resumed, save_path)
    final_loaded, _ = load_game(save_path, build_game_application_for_load)
    assert final_loaded._simulation.graph.terrain_profile(core).id == grading.target_terrain_profile_id

    # A subsequent return to the first authored outcome is legitimate, with
    # an independent new investment and no overwrite of historical progress.
    third_id = final_loaded.execute(EngineerSurfaceCell(
        str(ids.EARTH), str(core), str(target_recipe.id), procurement_policy="immediate"
    )).created_id
    assert third_id is not None
    third = next(p for p in final_loaded._simulation.projects.projects.values() if str(p.id) == third_id)
    assert third.planned_spatial_work == pytest.approx(target_recipe.construction_work *
        final_loaded._simulation.graph.terrain_profile(core).development_work_factor)
    final_loaded.execute(AdvanceTime(30))
    assert final_loaded._simulation.graph.terrain_profile(core).id == target_profile
    assert final_loaded._simulation.graph.surface_cells[core].resource_potential_by_resource == original_resource_potential


def test_surface_distribution_uses_physical_area_and_distance_not_cell_count():
    """Subdivision changes approximation resolution, not the amount of geography.

    A missing anchor must report the same physical coverage for coarse and fine
    partitions. With valid anchors, more supply locations cannot increase the
    minimum transport burden for the same physical territory.
    """
    from math import pi
    from space_idle.shared import CelestialBodyId, StarSystemId, SurfaceCellId
    from space_idle.spatial import (
        SpatialGraph, StarSystemDef, CelestialBodyDef,
        CharacteristicTransportGeometry, SurfaceCellDef, SurfaceTerrain,
        EnvironmentResolver, StaticFacetStore,
    )
    from space_idle.surface_partition import ring_partition, surface_partition_adjacency
    from space_idle.surface_infrastructure import SurfaceInfrastructureService
    from space_idle.facilities import FacilityBook
    from space_idle.service_capacity import ServiceCapacityRegistry

    def partition(ring_sizes):
        graph = SpatialGraph()
        geometry = CharacteristicTransportGeometry((0.0,), (0.0,))
        system_id = StarSystemId('test.infra.system')
        body_id = CelestialBodyId('test.infra.body')
        radius = 1000.0
        graph.add_star_system(StarSystemDef(system_id, 'System', geometry))
        graph.add_body(CelestialBodyDef(body_id, 'Body', radius, system_id, geometry))
        cells = tuple(
            SurfaceCellDef(
                SurfaceCellId(f'test.infra.cell.{ring}.{index}'), body_id,
                bounds.area_km2(radius), bounds.center(), frozenset(),
                SurfaceTerrain(), display_name=f"Region {ring}-{index}", spherical_bounds=bounds,
            )
            for ring, row in enumerate(ring_partition(ring_sizes))
            for index, bounds in enumerate(row)
        )
        neighbors = surface_partition_adjacency(cells)
        from dataclasses import replace
        graph.surface_cells = {cell.id: replace(cell, neighbor_ids=neighbors[cell.id])
                               for cell in cells}
        service = SurfaceInfrastructureService(
            graph, FacilityBook({}, EnvironmentResolver(graph, StaticFacetStore())),
            ServiceCapacityRegistry(),
        )
        return service, body_id, tuple(graph.surface_cells)

    expected = None
    for rings in ((4, 4), (8, 8), (8, 16, 8)):
        service, body_id, cells = partition(rings)
        loads = service.physical_load_sources_for_cells(body_id, cells, ())
        assert len(loads) == 1 and loads[0].code == 'access_anchor_missing'
        assert loads[0].demand == pytest.approx(
            4 * pi * service.graph.bodies[body_id].mean_radius_km**2 / service.area_reference_km2
        )
        if expected is None:
            expected = loads[0].demand
        assert loads[0].demand == pytest.approx(expected)
        single = sum(x.demand for x in service.physical_load_sources_for_cells(body_id, cells, cells[:1]))
        two = sum(x.demand for x in service.physical_load_sources_for_cells(body_id, cells, cells[:2]))
        assert 0 <= two <= single

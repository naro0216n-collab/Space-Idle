"""Physical bodies remain distinct from player-operated sites and logistics."""

from __future__ import annotations

from dataclasses import replace

import pytest

from space_idle import GetCatalog, GetSurfaceMap, GetWorld, GetNonSurfaceFoundingOptions, build_game_application
from space_idle.content import base_ids as ids
from space_idle.shared import CelestialBodyId, SpatialNodeId, SurfaceCellId, StarSystemId
from space_idle.spatial import (
    CelestialBodyDef, CharacteristicTransportGeometry, PhysicalSurface,
    SpatialGraph, StarSystemDef, SurfaceCellDef, SurfacePoint,
)


def test_solar_system_contains_physical_planets_and_satellites_without_owned_asset_creation():
    app = build_game_application()
    graph = app._simulation.graph
    bodies = tuple(graph.bodies.values())
    assert bodies
    assert any(body.parent_body_id is None for body in bodies)
    assert any(body.parent_body_id is not None for body in bodies)
    assert all(
        body.parent_body_id is None
        or body.star_system_id == graph.bodies[body.parent_body_id].star_system_id
        for body in bodies
    )
    assert all(body.representative_gravity_m_s2 is not None for body in bodies)
    assert all(graph.body_lineage(body.id)[0] == body.id for body in bodies)
    assert any(body.physical_surface is PhysicalSurface.NO_SOLID_SURFACE for body in bodies)

    catalog = app.query(GetCatalog())
    assert {row.id for row in catalog.celestial_bodies} == {str(body.id) for body in bodies}
    catalog_by_id = {row.id: row for row in catalog.celestial_bodies}
    for body in bodies:
        entry = catalog_by_id[str(body.id)]
        assert entry.parent_body_id == (str(body.parent_body_id) if body.parent_body_id else None)
        surface_map = app.query(GetSurfaceMap(entry.id))
        assert surface_map.physical_surface == entry.physical_surface
        assert len(surface_map.cells) == entry.surface_cell_count
        if body.physical_surface is PhysicalSurface.NO_SOLID_SURFACE:
            assert entry.surface_cell_count == 0

    world = app.query(GetWorld())
    assert {row.id for row in world.operational_nodes} == {str(id_) for id_ in graph.operational_node_ids()}
    assert not {row.id for row in world.operational_nodes} & {str(body.id) for body in bodies}
    assert not {str(body.id) for body in bodies} & {str(x) for x in app._simulation.inventory.stock}


def test_body_parent_validation_and_surface_capability_have_distinct_semantics():
    graph = SpatialGraph()
    one, two = StarSystemId("one"), StarSystemId("two")
    zero = CharacteristicTransportGeometry((0.0,))
    graph.add_star_system(StarSystemDef(one, "one", zero))
    graph.add_star_system(StarSystemDef(two, "two", zero))
    giant_id, moon_id = CelestialBodyId("giant"), CelestialBodyId("moon")
    giant = CelestialBodyDef(giant_id, "giant", 1000, one, None,
                            physical_surface=PhysicalSurface.NO_SOLID_SURFACE)
    moon = CelestialBodyDef(moon_id, "moon", 100, one, None, parent_body_id=giant_id)
    with pytest.raises(ValueError, match="unknown celestial parent"):
        graph.add_body(moon)
    graph.add_body(giant)
    graph.add_body(moon)
    assert graph.body_lineage(moon_id) == (moon_id, giant_id)
    assert graph.cells_for_body(moon_id) == ()  # no registered Cells != no surface
    with pytest.raises(ValueError, match="no solid surface"):
        graph.add_surface_cell(SurfaceCellDef(
            SurfaceCellId("giant.cell"), giant_id, 1, SurfacePoint(0, 0), display_name="bad"))
    assert graph.location_foundation_failures(giant_id, SurfaceCellId("missing"))[0][0] == "no_solid_surface"
    graph.add_surface_cell(SurfaceCellDef(
        SurfaceCellId("moon.cell"), moon_id, 1, SurfacePoint(0, 0), display_name="valid"))
    graph.found_location(SpatialNodeId("moon.outpost"), "Outpost", moon_id, SurfaceCellId("moon.cell"))
    assert graph.has_operational_node(SpatialNodeId("moon.outpost"))
    with pytest.raises(ValueError, match="another star system"):
        graph.add_body(replace(moon, id=CelestialBodyId("wrong.system"), star_system_id=two))
    with pytest.raises(ValueError, match="hierarchy cycle"):
        graph.bodies[giant_id] = replace(giant, parent_body_id=moon_id)
        graph.body_lineage(giant_id)


def test_representative_transfer_uses_orbital_physics_and_existing_movement_execution_contract():
    app = build_game_application()
    sim = app._simulation
    graph = sim.graph

    assert ids.MARS_ORBIT in graph.nodes
    assert not graph.has_operational_node(ids.MARS_ORBIT)
    assert ids.MARS_ORBIT not in graph.operational_node_ids()

    plans = sim.transport.movement_plans_to_non_surface_physical_target(ids.LEO, ids.MARS_ORBIT)
    assert len(plans) == 1
    plan = plans[0]
    assert plan.destination.physical_target_node_id == ids.MARS_ORBIT
    assert plan.relation.movement_context == "interplanetary_transfer"
    assert plan.relation.characteristic_delta_v_km_s > 0
    assert plan.transit_days > 1  # Interplanetary movement cannot be instantaneous.
    assert plan.operations[0].delta_v_km_s == plan.relation.characteristic_delta_v_km_s
    assert plan.operations[0].operation_type == "spaceflight"
    # Earth/Moon and outer satellites share the same physical transfer model;
    # no separate pairwise transit definitions or instant orbital shortcut.
    earth, moon = graph.bodies[ids.EARTH_BODY], graph.bodies[ids.MOON]
    assert moon.parent_body_id == earth.id
    assert moon.parent_orbit_semimajor_axis_km is not None
    lunar_transfer = graph.characteristic_transport_separation(
        ids.EARTH_CELL_INDUSTRIAL, ids.MOON_CELL_SOUTH_POLAR_RIDGE,
    )
    assert lunar_transfer.scope == "planetary_system_transfer"
    assert 0 < lunar_transfer.delta_v_km_s < plan.relation.characteristic_delta_v_km_s
    assert 0 < lunar_transfer.representative_transit_days < plan.transit_days
    assert all(body.system_local_transport_geometry is None for body in graph.bodies.values())

    # Performance eligibility and Resource requirements follow the same Plan
    # for remote founding and ordinary long-haul cargo.
    freight = sim.transport.vehicle_defs[ids.DEEP_SPACE_FREIGHTER].performance
    tug = sim.transport.vehicle_defs[ids.REUSABLE_ORBITAL_CARGO_TUG].performance
    assert not sim.transport.vehicle_movement_physical_failures(
        plan.id, ids.DEEP_SPACE_FREIGHTER, sim.day,
    )
    assert freight.endurance_days is not None and freight.propellant_capacity_t > 0
    assert 0 < freight.max_cargo_for_movement(plan) <= freight.payload_t
    assert 0 < freight.propellant_t(plan, 2.3) <= freight.propellant_capacity_t
    assert tug.endurance_failures(plan.transit_days)
    assert "endurance:" in " ".join(sim.transport.vehicle_movement_physical_failures(
        plan.id, ids.REUSABLE_ORBITAL_CARGO_TUG, sim.day,
    ))
    assert not sim.transport.vehicle_movement_physical_failures(
        plan.id, ids.DEEP_SPACE_PROBE, sim.day,
    )

    # The sole physical subject did not create an allocation endpoint.
    assert all(ids.MARS_ORBIT not in (p.origin_id, p.destination_id)
               for p in sim.transport.movement_resolver().all_direct_plans())

    # There is one symmetric physical definition for both directions.
    mars = CelestialBodyId("base.body.mars")
    phobos = CelestialBodyId("base.body.phobos")
    deimos = CelestialBodyId("base.body.deimos")
    for body_id, node_id in ((phobos, "test.phobos.orbit"), (deimos, "test.deimos.orbit")):
        from space_idle.spatial import SpatialNodeDef, SpatialNodeKind
        graph.add(SpatialNodeDef(SpatialNodeId(node_id), node_id, ids.SOL_SYSTEM, None,
                                 body_id=body_id, kind=SpatialNodeKind.ORBITAL))
    p2d = graph.characteristic_transport_separation(SpatialNodeId("test.phobos.orbit"), SpatialNodeId("test.deimos.orbit"))
    d2p = graph.characteristic_transport_separation(SpatialNodeId("test.deimos.orbit"), SpatialNodeId("test.phobos.orbit"))
    assert p2d == d2p
    assert p2d.scope == "planetary_system_transfer"
    assert p2d.representative_transit_days is not None and p2d.representative_transit_days > 0
    assert graph.bodies[mars].parent_body_id is None

    # Same-orbit contexts require only the minimum maneuver duration, without
    # a fictitious half-period transfer and without new Operational Nodes.
    same = SpatialNodeId("test.same.mars.orbit")
    from space_idle.spatial import SpatialNodeDef, SpatialNodeKind
    graph.add(SpatialNodeDef(same, "Same Martian orbit", ids.SOL_SYSTEM, None,
                             body_id=mars, kind=SpatialNodeKind.ORBITAL,
                             body_center_orbit_radius_km=graph.nodes[ids.MARS_ORBIT].body_center_orbit_radius_km))
    local = graph.characteristic_transport_separation(ids.MARS_ORBIT, same)
    assert local.scope == "local_orbit_transfer"
    assert local.delta_v_km_s == 0.0 and local.representative_transit_days == 0.0


def test_environment_power_and_knowledge_are_derived_from_distinct_world_facts():
    """Surface potential, sensing and energy have different owners and clocks."""
    from space_idle.spatial import (
        AtmosphereField, GravityField, IlluminationField, RadiationField, ThermalField,
    )
    from space_idle.facilities import FacilityBook
    from space_idle.site import SiteRequirements, FacetValueRange, evaluate_physical_site_requirements

    app = build_game_application()
    sim = app._simulation
    graph = sim.graph
    env = sim.environment
    # Cell-local climate is resolved for unowned physical targets as well as
    # operational locations; geometry validation belongs to the Spatial suite.
    assert graph.owner_of_cell(ids.MARS_CELL_EQUATORIAL_PLAIN) is None
    assert env.require(ids.MARS_CELL_EQUATORIAL_PLAIN, AtmosphereField).pressure_pa > 0
    assert env.require(ids.MARS_CELL_EQUATORIAL_PLAIN, GravityField).local_acceleration_m_s2 > 0
    equatorial_illumination = env.require(ids.MARS_CELL_EQUATORIAL_PLAIN, IlluminationField)
    polar_illumination = env.require(ids.MARS_CELL_POLAR_HIGHLANDS, IlluminationField)
    assert equatorial_illumination.solar_flux_w_m2 == pytest.approx(polar_illumination.solar_flux_w_m2)
    assert equatorial_illumination.availability > polar_illumination.availability
    assert env.require(ids.MARS_CELL_POLAR_HIGHLANDS, ThermalField).nominal_temperature_k < (
        env.require(ids.MARS_CELL_EQUATORIAL_PLAIN, ThermalField).nominal_temperature_k
    )
    assert env.require(ids.MARS_ORBIT, AtmosphereField).pressure_pa == 0
    solid = [body for body in graph.bodies.values() if body.physical_surface is PhysicalSurface.SOLID]
    assert all(graph.cells_for_body(body.id) for body in solid)
    assert all(not graph.cells_for_body(body.id) for body in graph.bodies.values()
               if body.physical_surface is PhysicalSurface.NO_SOLID_SURFACE)

    for cell_id, cell in graph.surface_cells.items():
        assert env.require(cell_id, GravityField).local_acceleration_m_s2 > 0
        assert env.require(cell_id, IlluminationField).solar_flux_w_m2 == pytest.approx(
            graph.representative_solar_flux_w_m2(cell.body_id)
        )
        for resource in cell.resource_potential_by_resource:
            assert (cell_id, resource) in sim.survey.targets

    # Site eligibility follows resolved radiation fields rather than the IDs or
    # balance values of particular moons.
    radiation = {
        cell_id: env.require(cell_id, RadiationField).dose_equivalent_msv_per_day
        for cell_id in graph.surface_cells
    }
    low = min(radiation, key=radiation.get)
    high = max(radiation, key=radiation.get)
    assert radiation[high] > radiation[low]
    tolerance = (radiation[high] + radiation[low]) / 2
    condition = SiteRequirements(environment=(FacetValueRange(
        RadiationField, "dose_equivalent_msv_per_day", "environment:radiation_tolerance",
        "radiation limit", maximum=tolerance,
    ),))
    assert evaluate_physical_site_requirements(condition, high, sim.day, env)[0].code == "environment:radiation_tolerance"
    assert not evaluate_physical_site_requirements(condition, low, sim.day, env)

    # Same solar Facility in different Cells receives exactly the flux and
    # availability resolved from each Cell; no second AU attenuation is applied.
    generation = {}
    candidate_by_body = {}
    for cell_id, cell in graph.surface_cells.items():
        if graph.owner_of_cell(cell_id) is None:
            candidate_by_body.setdefault(cell.body_id, cell_id)
    candidate_cells = tuple(candidate_by_body.values())[:3]
    assert len(candidate_cells) == 3
    for cell_id in candidate_cells:
        node_id = SpatialNodeId(f"test.power.{cell_id}")
        graph.found_location(node_id, "Power test", graph.surface_cells[cell_id].body_id, cell_id)
        facilities = FacilityBook(sim.facilities.definitions, env)
        facility_id = facilities.install(ids.SURFACE_POWER_GRID, node_id, site_cell_id=cell_id)
        generation[cell_id] = sim.power.physical_snapshot(node_id, facilities, sim.day).generation_mw_by_facility[facility_id]
        illum = env.require(cell_id, IlluminationField)
        spec = sim.power.specs[ids.SURFACE_POWER_GRID].generation
        assert generation[cell_id] == pytest.approx(
            spec.rated_mw_at_reference_flux * illum.solar_flux_w_m2 / spec.reference_flux_w_m2 * illum.availability
        )


def test_surface_access_transfer_reuses_world_physics_and_vehicle_operations():
    """World Content can add landings without creating an OD table or player nodes."""
    app = build_game_application()
    sim = app._simulation
    graph = sim.graph
    owner_ids = frozenset(graph.operational_node_ids())
    resolver = sim.transport.movement_resolver()
    eligible = {rule.body_id for rule in resolver.surface_access_rules}
    solid = {body.id for body in graph.bodies.values() if body.physical_surface is PhysicalSurface.SOLID}
    assert eligible == solid
    assert len(resolver.surface_access_rules) == len(solid)
    assert all(not graph.cells_for_body(body.id) for body in graph.bodies.values()
               if body.physical_surface is PhysicalSurface.NO_SOLID_SURFACE)

    mars = sim.transport.movement_plans_to_physical_target(ids.LEO, ids.MARS_CELL_EQUATORIAL_PLAIN)
    assert len(mars) == 1
    assert mars[0].destination.physical_target_cell_id == ids.MARS_CELL_EQUATORIAL_PLAIN
    assert mars[0].relation.movement_context == "interplanetary_transfer_surface_access"
    assert {op.operation_type for op in mars[0].operations} == {"spaceflight", "landing"}
    assert not sim.transport.vehicle_movement_physical_failures(
        mars[0].id, ids.INTERPLANETARY_LANDER, sim.day,
    )
    assert sim.transport.vehicle_movement_physical_failures(
        mars[0].id, ids.REUSABLE_ORBITAL_CARGO_TUG, sim.day,
    )
    assert sim.transport.vehicle_movement_physical_failures(
        mars[0].id, ids.DEEP_SPACE_FREIGHTER, sim.day,
    )  # Freight has no Landing capability.

    venus = sim.transport.movement_plans_to_physical_target(
        ids.LEO, SurfaceCellId("base.cell.venus.highland"),
    )
    assert len(venus) == 1
    assert venus[0].operations[-1].operation_type == "atmospheric_entry"
    assert any("pressure" in reason for reason in sim.transport.vehicle_movement_physical_failures(
        venus[0].id, ids.INTERPLANETARY_LANDER, sim.day,
    ))
    # An established atmospheric location must own an actual launch gateway;
    # installing a surface-distribution hub alone cannot provide a launch pad.
    assert frozenset(graph.operational_node_ids()) == owner_ids
    venus_cell = SurfaceCellId("base.cell.venus.highland")
    venus_node = SpatialNodeId("test.venus.surface_base")
    graph.found_location(venus_node, "Venus base", graph.surface_cells[venus_cell].body_id, venus_cell)
    sim.facilities.install(ids.SURFACE_DISTRIBUTION_HUB, venus_node, site_cell_id=venus_cell)
    assert not sim.transport.movement_resolver().direct_plans(venus_node, ids.LEO)
    sim.facilities.install(ids.SURFACE_LAUNCH_SUPPORT, venus_node, site_cell_id=venus_cell)
    assert sim.transport.movement_resolver().direct_plans(venus_node, ids.LEO)
    assert next(rule.gateway_capability_id for rule in resolver.surface_access_rules
                if rule.body_id == CelestialBodyId("base.body.venus")) == "launch_operations"
    assert next(rule.gateway_capability_id for rule in resolver.surface_access_rules
                if rule.body_id == CelestialBodyId("base.body.mars")) == "surface_distribution"
    assert all(plan.origin_id in graph.operational_node_ids() and plan.destination_id in graph.operational_node_ids()
               for plan in resolver.all_direct_plans())

    # Body IDs with equal terminal names remain separate physical contexts.
    # A Content extension does not require an authored case or a new evaluator.
    from space_idle.content.base_transport import build_surface_access_movement_rules
    from space_idle.spatial import AtmosphereField
    venus_body = graph.bodies[CelestialBodyId("base.body.venus")]
    environment = sim.facilities.environment
    for namespace in ("test.outer", "test.inner"):
        new_body_id = CelestialBodyId(f"{namespace}.venus")
        graph.add_body(replace(venus_body, id=new_body_id))
        environment.static.body_facets[(new_body_id, AtmosphereField)] = (
            environment.static.body_facets[(venus_body.id, AtmosphereField)]
        )
    all_profiles = build_surface_access_movement_rules(graph, environment)
    assert len({profile.id for profile in all_profiles}) == len(all_profiles)
    for namespace in ("test.outer", "test.inner"):
        new_body_id = CelestialBodyId(f"{namespace}.venus")
        generated = next(profile for profile in all_profiles if profile.body_id == new_body_id)
        assert generated.gateway_capability_id == "launch_operations"
        assert generated.descent_operations[0].operation_type == "atmospheric_entry"


def test_non_surface_founding_enables_long_cycle_cargo_without_free_assets_or_duplicate_settlement(short_interplanetary_transit):
    """A physical orbit is not a logistics endpoint until founded and supplied."""
    from space_idle import (
        AdvanceTime, CreateTransportAllocation, NonSurfaceOperationalNodeFoundingTarget,
        PlanBuild, PlanOperationalNodeFounding, SetTargetStock,
    )

    app = build_game_application()
    sim = app._simulation
    origin, target = ids.LUNAR_ORBIT, ids.MARS_ORBIT
    recipe = sim.founding.deployment_recipes[ids.ORBITAL_OUTPOST_FOUNDING_PACKAGE]
    assert target not in sim.graph.operational_node_ids()
    assert all(target not in (p.origin_id, p.destination_id)
               for p in sim.transport.movement_resolver().all_direct_plans())
    assert sim.inventory.amount(target, ids.PROPELLANT) == 0

    for requirement in recipe.payload_resources:
        sim.inventory.add(origin, requirement.resource_id, requirement.amount_t + 5.0)
    sim.inventory.add(origin, ids.PROPELLANT, 60.0)
    sim.transport.add_fleet_units(ids.DEEP_SPACE_FREIGHTER, 2, origin, day=sim.day)
    before_fuel = sim.inventory.amount(origin, ids.PROPELLANT)
    before_machinery = sim.inventory.amount(origin, ids.MACHINERY)
    project_id = app.execute(PlanOperationalNodeFounding(
        str(origin), "Mars orbital logistics",
        NonSurfaceOperationalNodeFoundingTarget("non_surface_operational_node", str(target)),
        str(recipe.id), str(ids.DEEP_SPACE_FREIGHTER),
    )).created_id
    project = next(row for row in sim.founding.projects.values() if str(row.id) == project_id)
    for _ in range(10):
        app.execute(AdvanceTime(1))
        if project.movement_execution_id:
            break
    assert project.movement_execution_id is not None
    assert target not in sim.graph.operational_node_ids()
    assert sim.inventory.amount(target, ids.PROPELLANT) == 0
    execution = sim.transport.movement_executions[project.movement_execution_id]
    app.execute(AdvanceTime(execution.completion_day - sim.day))
    assert project.status.value == "complete"
    assert target in sim.graph.operational_node_ids()
    assert sim.inventory.amount(origin, ids.PROPELLANT) < before_fuel
    deployed_propellant = sum(
        requirement.amount_t for requirement in recipe.initial_inventory
        if requirement.resource_id == ids.PROPELLANT
    )
    assert sim.inventory.amount(target, ids.PROPELLANT) == pytest.approx(deployed_propellant)
    assert sim.inventory.amount(target, ids.MACHINERY) < before_machinery
    assert len(sim.facilities.all_at(target)) == len(recipe.deployed_facilities)
    assert sim.inventory.admission_state(target, ids.MACHINERY).admission_capacity_t > 0

    capacity = sim.transport.transport_capacity_for_units(
        ids.DEEP_SPACE_FREIGHTER, origin, target, 1, day=sim.day,
    )
    assert capacity.forward_t_per_day > 0 and capacity.reverse_t_per_day > 0
    app.execute(CreateTransportAllocation(
        str(ids.DEEP_SPACE_FREIGHTER), str(origin), str(target),
        capacity.forward_t_per_day, capacity.reverse_t_per_day,
    ))
    app.execute(SetTargetStock(str(target), str(ids.MACHINERY), 1.1, priority=5))
    app.execute(AdvanceTime(2))
    pending = tuple(sim.logistics.cargo_flows.values())
    assert pending
    assert all(flow.source_id == origin and flow.final_destination_id == target for flow in pending)
    machinery_before_delivery = sim.inventory.amount(target, ids.MACHINERY)
    assert machinery_before_delivery < 1.1
    first_arrival = min(flow.first_arrival_day for flow in pending)
    assert first_arrival > sim.day

    days = first_arrival - sim.day + 1
    app.execute(AdvanceTime(days))
    assert sim.inventory.amount(target, ids.MACHINERY) > machinery_before_delivery
    # The compact founding outpost has finite receiving throughput. Waiting
    # cargo is expected at the first arrival, and must remain owned by
    # Logistics until it is admitted by the normal Storage/handling contract.
    app.execute(AdvanceTime(25))
    assert not sim.logistics.arrival_waiting
    assert sim.inventory.amount(target, ids.MACHINERY) >= machinery_before_delivery

    # A founding outpost must allow the first ordinary orbital investment.
    # Reservation holds materials in the finite pool until construction; a
    # nominally small storage number that cannot hold the first required
    # recipe would strand the player indefinitely at the founding stage.
    platform = sim.projects.recipes[ids.ORBITAL_CONSTRUCTION_PLATFORM]
    assert sim.inventory.admission_state(target, ids.MACHINERY).blockers == ()
    for requirement in platform.resources:
        deficit = max(0.0, requirement.amount_t + 0.15 - sim.inventory.amount(target, requirement.resource_id))
        if deficit:
            sim.inventory.add(target, requirement.resource_id, deficit)
    assert sim.inventory.admission_state(target, ids.MACHINERY).blockers == ()
    sim.technology.completed.update(platform.prerequisite_technologies)
    result = app.execute(PlanBuild(str(target), str(ids.ORBITAL_CONSTRUCTION_PLATFORM), procurement_policy="immediate"))
    assert result.created_id is not None
    app.execute(AdvanceTime(2))
    assert ids.ORBITAL_CONSTRUCTION_PLATFORM in {
        facility.definition_id for facility in sim.facilities.all_at(target)
    }
    assert sim.inventory.admission_state(target, ids.MACHINERY).blockers == ()
    from space_idle.validation import validate_runtime_state
    validate_runtime_state(sim)


def test_founding_projections_are_scoped_to_explicit_targets_without_losing_other_cell_geography(monkeypatch):
    app = build_game_application()
    sim = app._simulation
    assert sim.founding is not None
    original = sim.founding.planning_failures
    visited = []

    def tracked(staging_id, target, recipe_id, vehicle_id, day=0, power=None):
        visited.append(sim.founding.target_context_id(target))
        return original(staging_id, target, recipe_id, vehicle_id, day, power)

    monkeypatch.setattr(sim.founding, "planning_failures", tracked)
    moon = str(ids.MOON)
    unselected = app.query(GetSurfaceMap(moon, ()))
    assert len(unselected.cells) == len(sim.graph.cells_for_body(ids.MOON))
    assert not visited
    assert all(not row.foundation_options for row in unselected.cells)
    cells = [str(row.id) for row in sim.graph.cells_for_body(ids.MOON)]
    selected = app.query(GetSurfaceMap(moon, (cells[0],)))
    assert visited and {str(value) for value in visited} == {cells[0]}
    assert next(row for row in selected.cells if row.id == cells[0]).foundation_options
    assert all(not row.foundation_options for row in selected.cells if row.id != cells[0])
    visited.clear()
    pinned = app.query(GetSurfaceMap(moon, (cells[0], cells[1])))
    assert {str(value) for value in visited} == set(cells[:2])
    assert all(next(row for row in pinned.cells if row.id == cell).foundation_options for cell in cells[:2])
    from space_idle.app_contracts.common import ApplicationError
    with pytest.raises(ApplicationError, match="selected body"):
        app.query(GetSurfaceMap(moon, ("base.cell.venus.highland",)))

    visited.clear()
    jupiter = "base.body.jupiter"
    listed = app.query(GetNonSurfaceFoundingOptions(jupiter, ""))
    assert len(listed.contexts) == 1 and not listed.contexts[0].foundation_options
    assert not visited
    context_id = listed.contexts[0].spatial_node_id
    detailed = app.query(GetNonSurfaceFoundingOptions(jupiter, context_id))
    assert detailed.contexts[0].foundation_options
    assert {str(value) for value in visited} == {context_id}

    # Physical non-surface targets use the same projection and remain read-only.
    owned = set(sim.graph.operational_node_ids())
    fleet = dict(sim.transport.fleet_pools)
    stock = dict(sim.inventory.stock)
    non_surface_bodies = (
        body for body in sim.graph.bodies.values()
        if body.physical_surface is PhysicalSurface.NO_SOLID_SURFACE
    )
    for body in non_surface_bodies:
        contexts = app.query(GetNonSurfaceFoundingOptions(str(body.id), "")).contexts
        assert contexts
        context_id = contexts[0].spatial_node_id
        context = app.query(GetNonSurfaceFoundingOptions(str(body.id), context_id)).contexts[0]
        assert context.spatial_node_id in sim.graph.nodes
        assert context.spatial_node_id not in {str(node) for node in owned}
        assert not context.operational
        assert context.foundation_options
        assert all(option.blockers or option.can_plan for option in context.foundation_options)
        assert any(option.deployment_recipe_id == str(ids.ORBITAL_OUTPOST_FOUNDING_PACKAGE)
                   for option in context.foundation_options)
    assert set(sim.graph.operational_node_ids()) == owned
    assert sim.transport.fleet_pools == fleet
    assert sim.inventory.stock == stock
    with pytest.raises(ApplicationError, match="selected body"):
        app.query(GetNonSurfaceFoundingOptions(jupiter, str(ids.LUNAR_ORBIT)))

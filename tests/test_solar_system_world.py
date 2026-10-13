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


def test_registered_physical_bodies_project_without_creating_player_owned_nodes():
    app = build_game_application()
    graph = app._simulation.graph
    bodies = tuple(graph.bodies.values())
    assert bodies
    assert all(
        body.parent_body_id is None
        or body.star_system_id == graph.bodies[body.parent_body_id].star_system_id
        for body in bodies
    )

    catalog = app.query(GetCatalog())
    assert {row.id for row in catalog.celestial_bodies} == {str(body.id) for body in bodies}
    catalog_by_id = {row.id: row for row in catalog.celestial_bodies}
    for body in bodies:
        entry = catalog_by_id[str(body.id)]
        assert entry.parent_body_id == (str(body.parent_body_id) if body.parent_body_id else None)
        if body.physical_surface is PhysicalSurface.NO_SOLID_SURFACE:
            assert entry.surface_cell_count == 0
    for physical_surface in {body.physical_surface for body in bodies}:
        representative = next(body for body in bodies if body.physical_surface is physical_surface)
        entry = catalog_by_id[str(representative.id)]
        surface_map = app.query(GetSurfaceMap(entry.id))
        assert surface_map.physical_surface == entry.physical_surface
        assert len(surface_map.cells) == entry.surface_cell_count

    world = app.query(GetWorld())
    assert {row.id for row in world.operational_nodes} == {str(id_) for id_ in graph.operational_node_ids()}
    assert not {row.id for row in world.operational_nodes} & {str(body.id) for body in bodies}


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



def test_environment_power_and_knowledge_are_derived_from_distinct_world_facts():
    """Surface potential, sensing and energy have different owners and clocks."""
    from space_idle.spatial import (
        GravityField, IlluminationField,
    )
    from space_idle.facilities import FacilityBook, FacilityDef, FacilityPlacementScope
    from space_idle.power import PowerSpec, SolarGeneration
    from space_idle.shared import DefinitionId

    app = build_game_application()
    sim = app._simulation
    graph = sim.graph
    env = sim.environment
    # Cell-local climate is resolved for unowned physical targets as well as
    # operational locations; geometry validation belongs to the Spatial suite.
    # World-specific atmospheric values are Content choices, not a fixed
    # requirement of the generic Environment projection.
    # A solid physical body may legitimately have no authored Surface Cells.
    # The projection must use exactly the Cells that actually exist.
    assert all(graph.bodies[cell.body_id].physical_surface is PhysicalSurface.SOLID
               for cell in graph.surface_cells.values())

    for cell_id, cell in graph.surface_cells.items():
        assert env.require(cell_id, GravityField).local_acceleration_m_s2 > 0
        assert env.require(cell_id, IlluminationField).solar_flux_w_m2 == pytest.approx(
            graph.representative_solar_flux_w_m2(cell.body_id)
        )
        for resource in cell.resource_potential_by_resource:
            assert (cell_id, resource) in sim.survey.targets

    # Same solar Facility in different Cells receives exactly the flux and
    # availability resolved from each Cell; no second AU attenuation is applied.
    candidate_by_body = {}
    for cell_id, cell in graph.surface_cells.items():
        candidate_by_body.setdefault(cell.body_id, cell_id)
    candidate_cells = tuple(candidate_by_body.values())
    assert candidate_cells  # A present surface Cell, not an arbitrary unowned one.
    # Use a purpose-built solar Definition rather than requiring any named
    # Content Facility to remain in the catalogue.
    generator_id = DefinitionId("test.facility.solar_probe")
    solar = SolarGeneration(2.5, 1361.0)
    sim.power.specs[generator_id] = PowerSpec(solar, 0.0)
    facilities = FacilityBook({generator_id: FacilityDef(
        generator_id, "Solar probe", placement_scope=FacilityPlacementScope.SURFACE_CELL,
    )}, env)
    for cell_id in candidate_cells:
        node_id = graph.owner_of_cell(cell_id)
        if node_id is None:
            node_id = SpatialNodeId(f"test.power.{cell_id}")
            graph.found_location(node_id, "Power test", graph.surface_cells[cell_id].body_id, cell_id)
        facility_id = facilities.install(generator_id, node_id, site_cell_id=cell_id)
        generation = sim.power.physical_snapshot(node_id, facilities, sim.day).generation_mw_by_facility[facility_id]
        illum = env.require(cell_id, IlluminationField)
        assert generation == pytest.approx(
            solar.rated_mw_at_reference_flux * illum.solar_flux_w_m2 / solar.reference_flux_w_m2
            * illum.availability
        )


def test_surface_access_rules_follow_body_identity_and_physical_surface():
    """World Content can add landings without creating an OD table or player nodes."""
    app = build_game_application()
    sim = app._simulation
    graph = sim.graph
    resolver = sim.transport.movement_resolver()
    # Solid surfaces can be inaccessible; merely being a solid body does not
    # require authored descent/launch operations for every possible target.
    eligible = [rule.body_id for rule in resolver.surface_access_rules]
    # A body may admit multiple authored access methods with different operating
    # requirements; the physical-surface rule applies to each method independently.
    assert all(graph.bodies[body_id].physical_surface is PhysicalSurface.SOLID
               for body_id in eligible)

    # Synthetic bodies avoid making the continued existence of a particular
    # authored atmospheric planet a prerequisite for testing the generic rule.
    # Equal terminal names remain distinct physical contexts; atmosphere and
    # gravity, not names, determine the movement requirements.
    from space_idle.content.base_transport import build_surface_access_movement_rules
    from space_idle.spatial import AtmosphereField, EnvironmentResolver, StaticFacetStore
    from space_idle.transport import TransportOperationKind

    world = SpatialGraph()
    system = StarSystemId("test.system.access")
    geometry = CharacteristicTransportGeometry((0.0,))
    world.add_star_system(StarSystemDef(system, "Test access system", geometry))
    facets = StaticFacetStore()
    for name, pressure in (("test.outer.same", 100_000.0),
                           ("test.inner.same", 100_000.0),
                           ("test.vacuum.same", 0.0),
                           ("test.unknown.same", None)):
        body_id = CelestialBodyId(name)
        world.add_body(CelestialBodyDef(
            body_id, name, 2_000.0, system, geometry, reference_gravity_m_s2=4.0,
        ))
        if pressure is not None:
            facets.set_body(body_id, AtmosphereField(pressure, 0.0, {}))
    generated = build_surface_access_movement_rules(world, EnvironmentResolver(world, facets))
    by_body = {str(rule.body_id): rule for rule in generated}
    assert set(by_body) == {"test.outer.same", "test.inner.same", "test.vacuum.same"}
    outer, inner = by_body["test.outer.same"], by_body["test.inner.same"]
    assert outer.id != inner.id
    assert outer.gateway_capability_id == inner.gateway_capability_id == "launch_operations"
    assert outer.descent_operations == inner.descent_operations
    assert outer.descent_operations[0].operation_type == TransportOperationKind.ATMOSPHERIC_ENTRY
    vacuum = by_body["test.vacuum.same"]
    assert vacuum.gateway_capability_id == "surface_distribution"
    assert vacuum.descent_operations[0].operation_type == TransportOperationKind.LANDING


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
    # Test multi-target query scoping against an available physical body,
    # rather than fixing the number or names of Moon Surface Cells.
    candidate = next(
        ((body.id, sim.graph.cells_for_body(body.id)) for body in sim.graph.bodies.values()
         if len(sim.graph.cells_for_body(body.id)) >= 2), None
    )
    assert candidate is not None  # At least one map must support multi-target selection.
    body_id, physical_cells = candidate
    body = str(body_id)
    unselected = app.query(GetSurfaceMap(body, ()))
    assert len(unselected.cells) == len(physical_cells)
    assert not visited
    assert all(not row.foundation_options for row in unselected.cells)
    cells = [str(row.id) for row in physical_cells]
    selected = app.query(GetSurfaceMap(body, (cells[0],)))
    assert visited and {str(value) for value in visited} == {cells[0]}
    assert next(row for row in selected.cells if row.id == cells[0]).foundation_options
    assert all(not row.foundation_options for row in selected.cells if row.id != cells[0])
    visited.clear()
    pinned = app.query(GetSurfaceMap(body, (cells[0], cells[1])))
    assert {str(value) for value in visited} == set(cells[:2])
    assert all(next(row for row in pinned.cells if row.id == cell).foundation_options for cell in cells[:2])
    from space_idle.app_contracts.common import ApplicationError
    foreign_cell = next(
        cell.id for cell in sim.graph.surface_cells.values() if cell.body_id != body_id
    )
    with pytest.raises(ApplicationError, match="selected body"):
        app.query(GetSurfaceMap(body, (str(foreign_cell),)))

    visited.clear()
    # Context presence and the set of admissible Deployment recipes are
    # Content decisions. Verify projection and ownership for every registered
    # non-surface target without requiring a specific body, number of contexts,
    # or named founding package.
    owned = set(sim.graph.operational_node_ids())
    fleet = dict(sim.transport.fleet_pools)
    stock = dict(sim.inventory.stock)
    first_context = None
    for body in sim.graph.bodies.values():
        if body.physical_surface is not PhysicalSurface.NO_SOLID_SURFACE:
            continue
        contexts = app.query(GetNonSurfaceFoundingOptions(str(body.id), "")).contexts
        assert not visited  # Listing should not evaluate detailed founding plans.
        for item in contexts:
            context_id = item.spatial_node_id
            detailed = app.query(GetNonSurfaceFoundingOptions(str(body.id), context_id))
            assert any(row.spatial_node_id == context_id for row in detailed.contexts)
            projected = next(row for row in detailed.contexts if row.spatial_node_id == context_id)
            assert projected.spatial_node_id in sim.graph.nodes
            assert projected.spatial_node_id not in {str(node) for node in owned}
            assert not projected.operational
            assert all(option.blockers or option.can_plan for option in projected.foundation_options)
            assert {str(value) for value in visited} == {context_id}
            visited.clear()
            if first_context is None:
                first_context = body.id, context_id
    if first_context is not None:
        original_body, context_id = first_context
        other_body = next(body.id for body in sim.graph.bodies.values() if body.id != original_body)
        from space_idle.app_contracts.common import ApplicationError
        with pytest.raises(ApplicationError, match="selected body"):
            app.query(GetNonSurfaceFoundingOptions(str(other_body), context_id))
    assert set(sim.graph.operational_node_ids()) == owned
    assert sim.transport.fleet_pools == fleet
    assert sim.inventory.stock == stock

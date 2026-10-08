"""Physical bodies remain distinct from player-operated sites and logistics."""

from __future__ import annotations

from dataclasses import replace

import pytest

from space_idle import GetCatalog, GetSurfaceMap, GetWorld, build_game_application
from space_idle.content import base_ids as ids
from space_idle.shared import CelestialBodyId, SpatialNodeId, SurfaceCellId, StarSystemId
from space_idle.spatial import (
    CelestialBodyDef, CharacteristicTransportGeometry, PhysicalSurface,
    SpatialGraph, StarSystemDef, SurfaceCellDef, SurfacePoint,
)
from space_idle.content.base_spatial import build_world_definition


def test_solar_system_contains_physical_planets_and_satellites_without_owned_asset_creation():
    app = build_game_application()
    graph = app._simulation.graph
    bodies = tuple(graph.bodies.values())
    assert len(bodies) == 29
    assert len([body for body in bodies if body.parent_body_id is None]) == 8
    assert len([body for body in bodies if body.parent_body_id is not None]) == 21
    assert graph.bodies[ids.MOON].parent_body_id == ids.EARTH_BODY
    assert graph.body_lineage(CelestialBodyId("base.body.europa")) == (
        CelestialBodyId("base.body.europa"), CelestialBodyId("base.body.jupiter"),
    )
    assert graph.body_lineage(CelestialBodyId("base.body.triton"))[-1] == CelestialBodyId("base.body.neptune")
    assert sum(body.physical_surface is PhysicalSurface.NO_SOLID_SURFACE for body in bodies) == 4
    assert all(body.parent_body_id is None or body.star_system_id == graph.bodies[body.parent_body_id].star_system_id for body in bodies)
    assert all(body.representative_gravity_m_s2 is not None for body in bodies)
    assert graph.representative_solar_flux_w_m2(ids.MOON) == 1361.0
    assert graph.representative_solar_flux_w_m2(CelestialBodyId("base.body.europa")) < 60
    assert graph.representative_solar_flux_w_m2(CelestialBodyId("base.body.triton")) < 2

    catalog = app.query(GetCatalog())
    assert len(catalog.celestial_bodies) == len(bodies)
    jupiter = next(row for row in catalog.celestial_bodies if row.id == "base.body.jupiter")
    europa = next(row for row in catalog.celestial_bodies if row.id == "base.body.europa")
    assert jupiter.physical_surface == "no_solid_surface"
    assert europa.physical_surface == "solid" and europa.parent_body_id == jupiter.id
    assert europa.surface_cell_count == 0
    assert app.query(GetSurfaceMap(jupiter.id)).physical_surface == "no_solid_surface"
    assert app.query(GetSurfaceMap(europa.id)).physical_surface == "solid"
    assert app.query(GetSurfaceMap(europa.id)).cells == ()

    world = app.query(GetWorld())
    assert {row.id for row in world.operational_nodes} == {str(id_) for id_ in graph.operational_node_ids()}
    assert not {row.id for row in world.operational_nodes} & {str(body.id) for body in bodies}
    assert all(location.body_id in {ids.EARTH_BODY, ids.MOON} for location in graph.locations.values())
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


def test_earth_moon_transfer_uses_same_physical_orbit_inputs_as_other_satellites():
    graph, _ = build_world_definition()
    earth = graph.bodies[ids.EARTH_BODY]
    moon = graph.bodies[ids.MOON]
    assert earth.system_local_transport_geometry is moon.system_local_transport_geometry is None
    assert moon.parent_orbit_semimajor_axis_km == 384_400.0
    transfer = graph.characteristic_transport_separation(ids.EARTH_CELL_INDUSTRIAL, ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    assert transfer.scope == "planetary_system_transfer"
    assert 3.8 < transfer.delta_v_km_s < 4.2
    assert 4.5 < transfer.representative_transit_days < 5.5
    assert all(body.system_local_transport_geometry is None for body in graph.bodies.values())


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
    assert 200 < plan.transit_days < 400  # Hohmann-scale, not instantaneous separation / tug speed
    assert plan.operations[0].delta_v_km_s == plan.relation.characteristic_delta_v_km_s
    assert plan.operations[0].operation_type == "spaceflight"
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
                             body_center_orbit_radius_km=3_789.5))
    local = graph.characteristic_transport_separation(ids.MARS_ORBIT, same)
    assert local.scope == "local_orbit_transfer"
    assert local.delta_v_km_s == 0.0 and local.representative_transit_days == 0.0

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


def test_base_earth_moon_characteristic_transport_is_unchanged_by_new_physical_subjects():
    graph, _ = build_world_definition()
    earth = graph.bodies[ids.EARTH_BODY]
    moon = graph.bodies[ids.MOON]
    assert earth.system_local_transport_geometry.separation_to(moon.system_local_transport_geometry) == (384400.0, 4.1)
    assert graph.characteristic_transport_separation(ids.EARTH_CELL_INDUSTRIAL, ids.MOON_CELL_SOUTH_POLAR_RIDGE).distance_km == 384400.0
    assert all(body.system_local_transport_geometry is None for body in graph.bodies.values() if body.id not in {ids.EARTH_BODY, ids.MOON})

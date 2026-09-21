from __future__ import annotations

from space_idle import build_game_application
from space_idle.shared import CelestialBodyId, DefinitionId, SpatialNodeId, StarSystemId, SurfaceCellId
from space_idle.spatial import (
    AtmosphereField,
    CelestialBodyDef,
    CharacteristicTransportGeometry,
    EnvironmentResolver,
    IlluminationField,
    SpatialGraph,
    SpatialNodeDef,
    SpatialNodeKind,
    StarSystemDef,
    StaticFacetStore,
    SurfaceCellDef,
    SurfaceTerrain,
    SurfacePoint,
    ThermalField,
)
from space_idle.terraforming import PlanetaryClimateState, TerraformingEnvironmentOverlay, TerraformingService


def test_terraforming_body_state_projects_to_surface_locations_but_not_orbit_and_is_stateful():
    mars_body = CelestialBodyId("test.body.mars")
    cell_a = SurfaceCellId("test.mars.cell_a")
    cell_b = SurfaceCellId("test.mars.cell_b")
    site_a = SpatialNodeId("test.mars.site_a")
    site_b = SpatialNodeId("test.mars.site_b")
    orbit = SpatialNodeId("test.mars.orbit")
    graph = SpatialGraph()
    system = StarSystemId("test.system.mars")
    geometry = CharacteristicTransportGeometry((0.0,), (0.0,))
    graph.add_star_system(StarSystemDef(system, "Mars Test System", geometry))
    graph.add_body(CelestialBodyDef(mars_body, "火星", 1000.0, system, geometry))
    graph.add_surface_cell(SurfaceCellDef(
        cell_a, mars_body, 100.0, SurfacePoint(5.0, 10.0), frozenset({cell_b}), SurfaceTerrain(),
        display_name="Stress Cell A",
    ))
    graph.add_surface_cell(SurfaceCellDef(
        cell_b, mars_body, 120.0, SurfacePoint(8.0, 12.0), frozenset({cell_a}), SurfaceTerrain(),
        display_name="Stress Cell B",
    ))
    graph.found_location(site_a, "火星A", mars_body, cell_a)
    graph.found_location(site_b, "火星B", mars_body, cell_b)
    graph.add(SpatialNodeDef(
        orbit, "火星周回軌道", system, geometry, body_id=mars_body, kind=SpatialNodeKind.ORBITAL,
        inherits_parent_environment=False,
    ))
    static = StaticFacetStore()
    static.set_body(mars_body, AtmosphereField(610.0, 0.020, {DefinitionId("co2"): 0.95}))
    static.set_body(mars_body, ThermalField(210.0))
    static.set(cell_a, IlluminationField(590.0, 0.65))
    static.set(cell_b, IlluminationField(590.0, 0.40))
    static.set(orbit, AtmosphereField(0.0, 0.0, {}))
    static.set(orbit, ThermalField(245.0))

    climate = PlanetaryClimateState(
        mars_body, 610.0, 0.020, 210.0,
        {DefinitionId("co2"): 0.95, DefinitionId("n2"): 0.05},
    )
    service = TerraformingService({mars_body: climate})
    env = EnvironmentResolver(graph, static, [TerraformingEnvironmentOverlay(service)])

    assert env.require(site_a, AtmosphereField).pressure_pa == 610.0
    assert env.require(site_b, AtmosphereField).pressure_pa == 610.0
    saved_overlay = env.capture_overlay_state()
    service.add_atmosphere(mars_body, 390.0, 0.015, DefinitionId("n2"), 0.10, 5.0)
    assert env.require(site_a, AtmosphereField).pressure_pa == 1000.0
    assert env.require(site_b, AtmosphereField).pressure_pa == 1000.0
    assert env.require(site_a, ThermalField).nominal_temperature_k == 215.0
    assert env.require(cell_a, ThermalField).nominal_temperature_k == 215.0
    assert env.require(cell_a, IlluminationField).availability == 0.65
    assert env.require(cell_b, IlluminationField).availability == 0.40
    assert env.get(site_a, IlluminationField) is None
    assert env.require(orbit, AtmosphereField).pressure_pa == 0.0
    assert env.require(orbit, ThermalField).nominal_temperature_k == 245.0

    env.restore_overlay_state(saved_overlay)
    assert env.require(site_a, AtmosphereField).pressure_pa == 610.0

from __future__ import annotations

from dataclasses import dataclass

from space_idle.content import base_ids
from space_idle.shared import CelestialBodyId, DefinitionId, SpatialNodeId, StarSystemId, SurfaceCellId
from space_idle.spatial import (
    AtmosphereField,
    CelestialBodyDef,
    CharacteristicTransportGeometry,
    EnvironmentResolver,
    IlluminationField,
    SpatialFacet,
    SpatialGraph,
    SpatialNodeDef,
    SpatialNodeKind,
    StarSystemDef,
    StaticFacetStore,
    SurfaceCellDef,
    SurfaceField,
    SurfacePoint,
    ThermalField,
)
from space_idle.terraforming import PlanetaryClimateState, TerraformingEnvironmentOverlay, TerraformingService


def test_environment_facets_accept_peer_extensions_without_core_registration():
    @dataclass(frozen=True)
    class TestEnvironmentField(SpatialFacet):
        facet_key = "test_environment_field"
        value: float

    graph = SpatialGraph()
    system = StarSystemId("test.system.facets")
    geometry = CharacteristicTransportGeometry((0.0,), (0.0,))
    graph.add_star_system(StarSystemDef(system, "Facet System", geometry))
    node = SpatialNodeId("test.node")
    graph.add(SpatialNodeDef(node, "Test Node", system, geometry))
    store = StaticFacetStore()
    store.set(node, TestEnvironmentField(9.2))
    env = EnvironmentResolver(graph, store)

    assert env.require(node, TestEnvironmentField).value == 9.2


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
        cell_a, mars_body, 100.0, SurfacePoint(5.0, 10.0), frozenset({cell_b}), SurfaceField(),
        display_name="Stress Cell A",
    ))
    graph.add_surface_cell(SurfaceCellDef(
        cell_b, mars_body, 120.0, SurfacePoint(8.0, 12.0), frozenset({cell_a}), SurfaceField(),
        display_name="Stress Cell B",
    ))
    graph.found_location(site_a, "火星A", mars_body, cell_a)
    graph.found_location(site_b, "火星B", mars_body, cell_b)
    graph.add(SpatialNodeDef(
        orbit, "火星周回軌道", system, geometry, body_id=mars_body, kind=SpatialNodeKind.ORBITAL,
        inherits_parent_environment=False,
    ))
    static = StaticFacetStore()
    static.set(cell_a, AtmosphereField(610.0, 0.020, {DefinitionId("co2"): 0.95}))
    static.set(cell_b, AtmosphereField(610.0, 0.020, {DefinitionId("co2"): 0.95}))
    static.set(cell_a, ThermalField(210.0))
    static.set(cell_b, ThermalField(210.0))
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
    assert env.require(site_a, IlluminationField).availability == 0.65
    assert env.require(site_b, IlluminationField).availability == 0.40
    assert env.require(orbit, AtmosphereField).pressure_pa == 0.0
    assert env.require(orbit, ThermalField).nominal_temperature_k == 245.0

    env.restore_overlay_state(saved_overlay)
    assert env.require(site_a, AtmosphereField).pressure_pa == 610.0


def test_generic_core_does_not_embed_current_content_ids():
    import ast
    from pathlib import Path

    package = Path(__file__).parents[1] / "space_idle"
    outer_layers = {"content", "composition", "app_contracts"}
    files = [
        path for path in package.rglob("*.py")
        if path.name != "__init__.py"
        and not any(part in outer_layers for part in path.parts)
        and path.name not in {"bootstrap.py", "persistence.py"}
        and not path.name.startswith("application")
    ]
    current_content_ids = {
        value
        for name, value in vars(base_ids).items()
        if name.isupper() and isinstance(value, str) and value.startswith("base.")
    }
    assert current_content_ids

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        embedded = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in current_content_ids
        }
        assert not embedded, (
            f"{path.relative_to(package)} embeds concrete Content IDs: "
            f"{sorted(embedded)}"
        )

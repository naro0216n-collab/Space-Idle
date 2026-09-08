from __future__ import annotations

from dataclasses import dataclass
import inspect

from space_idle import build_game_application
from space_idle.market import MarketState
from space_idle.mission_stress import MissionPlanner, TransferOption, VehicleCapability
from space_idle.shared import CelestialBodyId, DefinitionId, EntityId, SpatialNodeId
from space_idle.spatial import (
    AtmosphereField,
    CelestialBodyDef,
    EnvironmentResolver,
    GravityField,
    IlluminationField,
    SpatialFacet,
    SpatialGraph,
    SpatialNodeDef,
    SpatialNodeKind,
    StaticFacetStore,
    ThermalField,
)
from space_idle.terraforming import PlanetaryClimateState, TerraformingEnvironmentOverlay, TerraformingService


def test_mars_first_mission_requires_no_lunar_progression():
    earth = SpatialNodeId("test.earth")
    mars = SpatialNodeId("test.mars")
    vehicle = VehicleCapability(DefinitionId("test.vehicle"), 5.0, 12.0, 400)
    option = TransferOption(earth, mars, 100, 210, 10.0)
    plan = MissionPlanner().plan(vehicle, option, 2.0)
    assert plan.destination_id == mars
    assert plan.arrival_day == 310
    source = inspect.getsource(MissionPlanner).lower()
    assert "moon" not in source and "lunar" not in source


def test_artificial_gravity_can_be_added_as_peer_facet_without_spatial_core_change():
    @dataclass(frozen=True)
    class ArtificialGravityField(SpatialFacet):
        facet_key = "artificial_gravity"
        acceleration_m_s2: float

    graph = SpatialGraph()
    station = SpatialNodeId("test.station")
    graph.add(SpatialNodeDef(station, "回転式ステーション"))
    store = StaticFacetStore()
    store.set(station, ArtificialGravityField(9.2))
    env = EnvironmentResolver(graph, store)
    assert env.require(station, ArtificialGravityField).acceleration_m_s2 == 9.2


def test_market_spans_locations_without_becoming_spatial_facet():
    earth = SpatialNodeId("test.earth")
    leo = SpatialNodeId("test.leo")
    moon = SpatialNodeId("test.moon")
    resource = DefinitionId("test.resource")
    market = MarketState(
        EntityId("market.cislunar"),
        participant_organization_ids={EntityId("org.a"), EntityId("org.b")},
        accessible_location_ids={earth, leo, moon},
        reference_prices={resource: 100.0},
        demand={resource: 5.0},
        supply={resource: 10.0},
    )
    assert 0 < market.clear_price(resource) < 100.0
    assert len(market.accessible_location_ids) == 3


def test_terraforming_body_state_projects_to_surface_nodes_but_not_orbit_and_is_stateful():
    mars_body = CelestialBodyId("test.body.mars")
    site_a = SpatialNodeId("test.mars.site_a")
    site_b = SpatialNodeId("test.mars.site_b")
    orbit = SpatialNodeId("test.mars.orbit")
    graph = SpatialGraph()
    graph.add_body(CelestialBodyDef(mars_body, "火星"))
    graph.add(SpatialNodeDef(site_a, "火星A", body_id=mars_body, kind=SpatialNodeKind.SURFACE))
    graph.add(SpatialNodeDef(site_b, "火星B", body_id=mars_body, kind=SpatialNodeKind.SURFACE))
    graph.add(SpatialNodeDef(orbit, "火星周回軌道", body_id=mars_body, kind=SpatialNodeKind.ORBITAL, inherits_parent_environment=False))
    static = StaticFacetStore()
    static.set(site_a, AtmosphereField(610.0, 0.020, {DefinitionId("co2"): 0.95}))
    static.set(site_b, AtmosphereField(610.0, 0.020, {DefinitionId("co2"): 0.95}))
    static.set(site_a, ThermalField(210.0))
    static.set(site_b, ThermalField(210.0))
    static.set(site_a, IlluminationField(590.0, 0.65))
    static.set(site_b, IlluminationField(590.0, 0.40))
    static.set(orbit, AtmosphereField(0.0, 0.0, {}))
    static.set(orbit, ThermalField(245.0))

    climate = PlanetaryClimateState(mars_body, 610.0, 0.020, 210.0, {DefinitionId("co2"): 0.95, DefinitionId("n2"): 0.05})
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


def test_generic_core_contains_no_current_destination_specific_branches_or_location_allowlists():
    from pathlib import Path
    package = Path(__file__).parents[1] / "space_idle"
    outer_layers = {"content", "composition", "app_contracts"}
    files = [
        path for path in package.rglob("*.py")
        if path.name != "__init__.py"
        and not any(part in outer_layers for part in path.parts)
        and path.name != "bootstrap.py"
        and path.name != "persistence.py"
        and not path.name.startswith("application")
    ]
    forbidden = (
        "moon", "lunar", "mars", "martian",
        "allowed_location_ids", "default_import_source_id",
    )
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text, f"{path.name} contains destination-specific shortcut {token}"


def test_lunar_prospecting_is_not_forced_through_orbital_infrastructure_track():
    from space_idle.content.base_game import TECH_LUNAR_PROSPECTING, TECH_ORBITAL_OPERATIONS

    app = build_game_application()
    definitions = app._simulation.research.definitions
    assert TECH_ORBITAL_OPERATIONS not in definitions[TECH_LUNAR_PROSPECTING].prerequisites


def test_catalog_exposes_vehicle_definitions_even_when_no_instance_is_owned():
    from space_idle import GetCatalog
    from space_idle.content.base_game import REUSABLE_ORBITAL_CARGO_TUG

    app = build_game_application()
    app._simulation.logistics.vehicles = {
        vid: state for vid, state in app._simulation.logistics.vehicles.items()
        if state.definition_id != REUSABLE_ORBITAL_CARGO_TUG
    }
    catalog = app.query(GetCatalog())
    row = next(vehicle for vehicle in catalog.vehicles if vehicle.id == str(REUSABLE_ORBITAL_CARGO_TUG))
    assert row.production_capability_id == "vehicle_assembly"
    assert row.production_days > 0

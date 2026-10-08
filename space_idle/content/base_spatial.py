from __future__ import annotations

from ..shared import CelestialBodyId, DefinitionId
from ..spatial import (
    AtmosphereField,
    CelestialBodyDef,
    CharacteristicTransportGeometry,
    CommunicationField,
    EnvironmentResolver,
    GravityField,
    IlluminationField,
    OrbitalField,
    PhysicalSurface,
    RadiationField,
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
from . import base_ids as ids
from .solar_system_bodies import register_solar_system_bodies, register_solar_system_environment, register_solar_system_regions, register_giant_orbital_contexts


def _earth_cell(
    cell_id, display_name: str, latitude: float, longitude: float, neighbors, terrain: SurfaceTerrain,
    resource_potential_by_resource,
) -> SurfaceCellDef:
    return SurfaceCellDef(
        cell_id,
        ids.EARTH_BODY,
        area_km2=5_000_000.0,
        centroid=SurfacePoint(latitude, longitude),
        neighbor_ids=frozenset(neighbors),
        terrain=terrain,
        static_geology={"crust_accessibility": 1.0},
        resource_potential_by_resource=resource_potential_by_resource,
        display_name=display_name,
    )


def _moon_cell(
    cell_id, display_name: str, latitude: float, longitude: float, neighbors, terrain: SurfaceTerrain,
    resource_potential_by_resource,
) -> SurfaceCellDef:
    return SurfaceCellDef(
        cell_id,
        ids.MOON,
        area_km2=6_000_000.0,
        centroid=SurfacePoint(latitude, longitude),
        neighbor_ids=frozenset(neighbors),
        terrain=terrain,
        static_geology={"regolith_accessibility": 1.0},
        resource_potential_by_resource=resource_potential_by_resource,
        display_name=display_name,
    )


BASE_WORLD_DEFINITION_ID = "base.world.sol"


def build_world_definition() -> tuple[SpatialGraph, EnvironmentResolver]:
    graph = SpatialGraph()
    graph.add_star_system(StarSystemDef(
        ids.SOL_SYSTEM,
        "太陽系",
        CharacteristicTransportGeometry((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        central_gravitational_parameter_km3_s2=132_712_440_018.0,
    ))
    graph.add_body(CelestialBodyDef(
        ids.EARTH_BODY, "地球", 6371.0, ids.SOL_SYSTEM, None,
        heliocentric_semimajor_axis_au=1.0,
        reference_gravity_m_s2=9.80,
    ))
    graph.add_body(CelestialBodyDef(
        ids.MOON, "月", 1737.4, ids.SOL_SYSTEM, None,
        parent_body_id=ids.EARTH_BODY,
        parent_orbit_semimajor_axis_km=384_400.0,
        standard_gravitational_parameter_km3_s2=4902.800,
    ))
    register_solar_system_bodies(graph)
    register_giant_orbital_contexts(graph)

    # Baseline orbital contexts inherit their physical body's transfer scale;
    # they do not duplicate an independent Cartesian transport baseline.
    graph.add(
        SpatialNodeDef(
            ids.LEO,
            "地球低軌道",
            ids.SOL_SYSTEM,
            None,
            body_id=ids.EARTH_BODY,
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
            body_center_orbit_radius_km=6_771.0,
        )
    )
    graph.add(
        SpatialNodeDef(
            ids.LUNAR_ORBIT,
            "月周回軌道",
            ids.SOL_SYSTEM,
            None,
            body_id=ids.MOON,
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
            body_center_orbit_radius_km=1_837.4,
        )
    )
    # Mars encounter is a physical target, not an owned transport/logistics node.
    graph.add(SpatialNodeDef(
        ids.MARS_ORBIT, "火星周回軌道", ids.SOL_SYSTEM, None,
        body_id=ids.MARS_BODY,
        kind=SpatialNodeKind.ORBITAL,
        inherits_parent_environment=False,
        body_center_orbit_radius_km=3_789.5,
    ))

    earth_cells = (
        _earth_cell(
            ids.EARTH_CELL_INDUSTRIAL,
            "産業中核地域",
            35.0,
            139.0,
            (ids.EARTH_CELL_COASTAL, ids.EARTH_CELL_INLAND),
            SurfaceTerrain(1.0, 1.0, 0.05, 0.02),
            {ids.MINERAL_FEEDSTOCK: 60.0, ids.METAL_ORE: 35.0, ids.WATER: 120.0},
        ),
        _earth_cell(
            ids.EARTH_CELL_COASTAL,
            "沿岸地域",
            20.0,
            150.0,
            (ids.EARTH_CELL_INDUSTRIAL,),
            SurfaceTerrain(0.95, 0.95, 0.07, 0.03),
            {ids.MINERAL_FEEDSTOCK: 45.0, ids.METAL_ORE: 24.0, ids.WATER: 180.0},
        ),
        _earth_cell(
            ids.EARTH_CELL_INLAND,
            "内陸地域",
            45.0,
            110.0,
            (ids.EARTH_CELL_INDUSTRIAL,),
            SurfaceTerrain(0.92, 0.96, 0.06, 0.05),
            {ids.MINERAL_FEEDSTOCK: 72.0, ids.METAL_ORE: 52.0, ids.WATER: 75.0},
        ),
    )
    moon_cells = (
        _moon_cell(
            ids.MOON_CELL_SOUTH_POLAR_RIDGE,
            "南極高地縁辺",
            -88.0,
            30.0,
            (ids.MOON_CELL_POLAR_COLD_TRAP, ids.MOON_CELL_SOUTH_POLAR_PLAIN),
            SurfaceTerrain(0.90, 0.90, 0.55, 0.10),
            {ids.VOLATILE_BEARING_MATERIAL: 0.45, ids.MINERAL_FEEDSTOCK: 22.0, ids.METAL_ORE: 5.5},
        ),
        _moon_cell(
            ids.MOON_CELL_POLAR_COLD_TRAP,
            "極域永久影クレーター",
            -89.0,
            50.0,
            (ids.MOON_CELL_SOUTH_POLAR_RIDGE, ids.MOON_CELL_SOUTH_POLAR_PLAIN),
            SurfaceTerrain(0.62, 0.75, 0.60, 0.28),
            {ids.VOLATILE_BEARING_MATERIAL: 4.5, ids.MINERAL_FEEDSTOCK: 16.0, ids.METAL_ORE: 3.8},
        ),
        _moon_cell(
            ids.MOON_CELL_SOUTH_POLAR_PLAIN,
            "南極平原",
            -82.0,
            40.0,
            (
                ids.MOON_CELL_SOUTH_POLAR_RIDGE,
                ids.MOON_CELL_POLAR_COLD_TRAP,
                ids.MOON_CELL_EQUATORIAL_HIGHLANDS,
            ),
            SurfaceTerrain(0.84, 0.86, 0.60, 0.12),
            {ids.VOLATILE_BEARING_MATERIAL: 0.18, ids.MINERAL_FEEDSTOCK: 25.0, ids.METAL_ORE: 6.2},
        ),
        _moon_cell(
            ids.MOON_CELL_NEARSIDE_MARE,
            "表側海地域",
            0.0,
            20.0,
            (ids.MOON_CELL_EQUATORIAL_HIGHLANDS,),
            SurfaceTerrain(0.95, 0.95, 0.60, 0.05),
            {ids.VOLATILE_BEARING_MATERIAL: 0.02, ids.MINERAL_FEEDSTOCK: 38.0, ids.METAL_ORE: 9.0},
        ),
        _moon_cell(
            ids.MOON_CELL_EQUATORIAL_HIGHLANDS,
            "赤道高地",
            5.0,
            90.0,
            (
                ids.MOON_CELL_SOUTH_POLAR_PLAIN,
                ids.MOON_CELL_NEARSIDE_MARE,
                ids.MOON_CELL_FARSIDE_HIGHLANDS,
            ),
            SurfaceTerrain(0.78, 0.82, 0.65, 0.18),
            {ids.VOLATILE_BEARING_MATERIAL: 0.06, ids.MINERAL_FEEDSTOCK: 30.0, ids.METAL_ORE: 7.5},
        ),
        _moon_cell(
            ids.MOON_CELL_FARSIDE_HIGHLANDS,
            "裏側高地",
            5.0,
            170.0,
            (ids.MOON_CELL_EQUATORIAL_HIGHLANDS,),
            SurfaceTerrain(0.75, 0.80, 0.67, 0.20),
            {ids.VOLATILE_BEARING_MATERIAL: 0.08, ids.MINERAL_FEEDSTOCK: 28.0, ids.METAL_ORE: 6.8},
        ),
    )
    mars_cells = (
        SurfaceCellDef(
            ids.MARS_CELL_EQUATORIAL_PLAIN, ids.MARS_BODY, 4_000_000.0,
            SurfacePoint(2.0, 135.0),
            frozenset((ids.MARS_CELL_NORTHERN_BASIN, ids.MARS_CELL_POLAR_HIGHLANDS)),
            SurfaceTerrain(0.86, 0.82, 0.48, 0.13),
            {"crust_accessibility": 1.0, "regolith_accessibility": 0.85},
            {ids.MINERAL_FEEDSTOCK: 40.0, ids.METAL_ORE: 16.0, ids.VOLATILE_BEARING_MATERIAL: 0.35},
            "赤道平原",
        ),
        SurfaceCellDef(
            ids.MARS_CELL_NORTHERN_BASIN, ids.MARS_BODY, 5_000_000.0,
            SurfacePoint(42.0, 50.0),
            frozenset((ids.MARS_CELL_EQUATORIAL_PLAIN,)),
            SurfaceTerrain(0.92, 0.90, 0.46, 0.08),
            {"crust_accessibility": 0.9, "regolith_accessibility": 0.95},
            {ids.MINERAL_FEEDSTOCK: 34.0, ids.METAL_ORE: 10.0, ids.VOLATILE_BEARING_MATERIAL: 0.55},
            "北部低地",
        ),
        SurfaceCellDef(
            ids.MARS_CELL_POLAR_HIGHLANDS, ids.MARS_BODY, 3_000_000.0,
            SurfacePoint(-78.0, 110.0),
            frozenset((ids.MARS_CELL_EQUATORIAL_PLAIN,)),
            SurfaceTerrain(0.65, 0.72, 0.61, 0.30),
            {"crust_accessibility": 0.75, "regolith_accessibility": 0.75},
            {ids.MINERAL_FEEDSTOCK: 18.0, ids.METAL_ORE: 7.0, ids.VOLATILE_BEARING_MATERIAL: 2.8},
            "南極高地",
        ),
    )
    for cell in earth_cells + moon_cells + mars_cells:
        graph.add_surface_cell(cell)


    facets = StaticFacetStore()
    register_solar_system_environment(graph, facets)
    register_solar_system_regions(graph, facets)

    # Body-global Physical Environment is defined once per body.  Surface Cell
    # local fields/overlays remain explicit below; Surface Locations never copy
    # values from their founding/core Cell.
    facets.set_body(ids.EARTH_BODY, GravityField(9.80665, 11186.0))
    facets.set_body(
        ids.EARTH_BODY,
        AtmosphereField(
            101325.0,
            1.225,
            {
                DefinitionId("base.species.n2"): 0.78,
                DefinitionId("base.species.o2"): 0.21,
            },
        ),
    )
    facets.set_body(ids.EARTH_BODY, ThermalField(288.0))
    facets.set_body(ids.EARTH_BODY, RadiationField(0.003))
    facets.set_body(ids.EARTH_BODY, CommunicationField(0.02, 1.0))
    for cell_id in (
        ids.EARTH_CELL_INDUSTRIAL,
        ids.EARTH_CELL_COASTAL,
        ids.EARTH_CELL_INLAND,
    ):
        facets.set(cell_id, IlluminationField(graph.representative_solar_flux_w_m2(ids.EARTH_BODY), 0.50))

    facets.set(ids.LEO, OrbitalField(5400.0))
    facets.set(ids.LEO, GravityField(8.7, 10800.0))
    facets.set(ids.LEO, AtmosphereField(0.0, 0.0, {}))
    facets.set(ids.LEO, IlluminationField(graph.representative_solar_flux_w_m2(ids.EARTH_BODY), 0.62))
    facets.set(ids.LEO, ThermalField(270.0))
    facets.set(ids.LEO, RadiationField(0.5))
    facets.set(ids.LEO, CommunicationField(0.02, 0.98))

    facets.set(ids.LUNAR_ORBIT, OrbitalField(7200.0))
    facets.set(ids.LUNAR_ORBIT, GravityField(1.4, 2300.0))
    facets.set(ids.LUNAR_ORBIT, AtmosphereField(0.0, 0.0, {}))
    facets.set(ids.LUNAR_ORBIT, ThermalField(250.0))
    facets.set(ids.LUNAR_ORBIT, RadiationField(0.8))
    facets.set(ids.LUNAR_ORBIT, IlluminationField(graph.representative_solar_flux_w_m2(ids.EARTH_BODY), 0.70))
    facets.set(ids.LUNAR_ORBIT, CommunicationField(1.3, 0.95))

    facets.set_body(ids.MOON, GravityField(1.62, 2380.0))
    facets.set_body(ids.MOON, AtmosphereField(0.0, 0.0, {}))
    facets.set_body(ids.MOON, ThermalField(220.0, 90.0, 390.0))
    facets.set_body(ids.MOON, RadiationField(0.8))
    facets.set_body(ids.MOON, CommunicationField(1.3, 0.75))
    lunar_surface_ids = tuple(cell.id for cell in moon_cells)
    for cell_id in lunar_surface_ids:
        facets.set(cell_id, IlluminationField(graph.representative_solar_flux_w_m2(ids.EARTH_BODY), 0.45))

    facets.set(ids.MOON_CELL_SOUTH_POLAR_RIDGE, IlluminationField(graph.representative_solar_flux_w_m2(ids.EARTH_BODY), 0.78))
    facets.set(ids.MOON_CELL_SOUTH_POLAR_RIDGE, CommunicationField(1.3, 0.85))
    facets.set(ids.MOON_CELL_POLAR_COLD_TRAP, IlluminationField(graph.representative_solar_flux_w_m2(ids.EARTH_BODY), 0.05))
    facets.set(ids.MOON_CELL_POLAR_COLD_TRAP, ThermalField(80.0, 40.0, 120.0))
    facets.set(ids.MOON_CELL_POLAR_COLD_TRAP, CommunicationField(1.3, 0.15))
    facets.set(ids.MOON_CELL_NEARSIDE_MARE, IlluminationField(graph.representative_solar_flux_w_m2(ids.EARTH_BODY), 0.52))
    facets.set(ids.MOON_CELL_NEARSIDE_MARE, CommunicationField(1.3, 1.0))

    facets.set_body(ids.MARS_BODY, GravityField(3.71, 5030.0))
    facets.set_body(ids.MARS_BODY, AtmosphereField(
        610.0, 0.020, {DefinitionId("base.species.co2"): 0.953},
    ))
    facets.set_body(ids.MARS_BODY, ThermalField(210.0, 145.0, 290.0))
    facets.set_body(ids.MARS_BODY, RadiationField(0.65))
    facets.set_body(ids.MARS_BODY, CommunicationField(750.0, 0.80))
    solar_flux = graph.representative_solar_flux_w_m2(ids.MARS_BODY)
    assert solar_flux is not None
    for cell in mars_cells:
        facets.set(cell.id, IlluminationField(solar_flux, 0.48))
    facets.set(ids.MARS_CELL_POLAR_HIGHLANDS, IlluminationField(solar_flux, 0.23))
    facets.set(ids.MARS_CELL_POLAR_HIGHLANDS, ThermalField(168.0, 125.0, 230.0))
    facets.set(ids.MARS_CELL_POLAR_HIGHLANDS, RadiationField(0.45))
    facets.set(ids.MARS_ORBIT, OrbitalField(7500.0))
    facets.set(ids.MARS_ORBIT, GravityField(2.95, 4500.0))
    facets.set(ids.MARS_ORBIT, AtmosphereField(0.0, 0.0, {}))
    facets.set(ids.MARS_ORBIT, ThermalField(235.0))
    facets.set(ids.MARS_ORBIT, RadiationField(0.8))
    facets.set(ids.MARS_ORBIT, IlluminationField(solar_flux, 0.69))
    facets.set(ids.MARS_ORBIT, CommunicationField(750.0, 0.90))

    return graph, EnvironmentResolver(graph, facets)

from __future__ import annotations

from ..shared import DefinitionId
from ..spatial import (
    AtmosphereField,
    CelestialBodyDef,
    CharacteristicTransportGeometry,
    CommunicationField,
    EnvironmentResolver,
    GravityField,
    IlluminationField,
    OperationalNodeState,
    OrbitalField,
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


def build_spatial_model() -> tuple[SpatialGraph, EnvironmentResolver]:
    graph = SpatialGraph()
    graph.add_star_system(StarSystemDef(
        ids.SOL_SYSTEM,
        "太陽系",
        CharacteristicTransportGeometry((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    ))
    earth_geometry = CharacteristicTransportGeometry(
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    )
    moon_geometry = CharacteristicTransportGeometry(
        (384_400.0, 0.0, 0.0),
        (4.1, 0.0, 0.0),
    )
    graph.add_body(CelestialBodyDef(
        ids.EARTH_BODY, "地球", 6371.0, ids.SOL_SYSTEM, earth_geometry
    ))
    graph.add_body(CelestialBodyDef(
        ids.MOON, "月", 1737.4, ids.SOL_SYSTEM, moon_geometry
    ))

    # Non-surface nodes provide their own stable transport anchors.  Current
    # baseline orbits use their parent body's characteristic system position;
    # local surface-access effort is represented by Movement operations.
    graph.add(
        SpatialNodeDef(
            ids.LEO,
            "地球低軌道",
            ids.SOL_SYSTEM,
            earth_geometry,
            body_id=ids.EARTH_BODY,
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
        )
    )
    graph.add(
        SpatialNodeDef(
            ids.LUNAR_ORBIT,
            "月周回軌道",
            ids.SOL_SYSTEM,
            moon_geometry,
            body_id=ids.MOON,
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
        )
    )

    earth_cells = (
        _earth_cell(
            ids.EARTH_CELL_INDUSTRIAL,
            "産業中核地域",
            35.0,
            139.0,
            (ids.EARTH_CELL_COASTAL, ids.EARTH_CELL_INLAND),
            SurfaceTerrain(1.0, 1.0, 0.05, 0.02),
            {ids.AGGREGATE: 60.0, ids.METAL_ORE: 35.0, ids.WATER: 120.0},
        ),
        _earth_cell(
            ids.EARTH_CELL_COASTAL,
            "沿岸地域",
            20.0,
            150.0,
            (ids.EARTH_CELL_INDUSTRIAL,),
            SurfaceTerrain(0.95, 0.95, 0.07, 0.03),
            {ids.AGGREGATE: 45.0, ids.METAL_ORE: 24.0, ids.WATER: 180.0},
        ),
        _earth_cell(
            ids.EARTH_CELL_INLAND,
            "内陸地域",
            45.0,
            110.0,
            (ids.EARTH_CELL_INDUSTRIAL,),
            SurfaceTerrain(0.92, 0.96, 0.06, 0.05),
            {ids.AGGREGATE: 72.0, ids.METAL_ORE: 52.0, ids.WATER: 75.0},
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
            {ids.WATER: 0.45, ids.REGOLITH: 22.0},
        ),
        _moon_cell(
            ids.MOON_CELL_POLAR_COLD_TRAP,
            "極域永久影クレーター",
            -89.0,
            50.0,
            (ids.MOON_CELL_SOUTH_POLAR_RIDGE, ids.MOON_CELL_SOUTH_POLAR_PLAIN),
            SurfaceTerrain(0.62, 0.75, 0.60, 0.28),
            {ids.WATER: 4.5, ids.REGOLITH: 16.0},
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
            {ids.WATER: 0.18, ids.REGOLITH: 25.0},
        ),
        _moon_cell(
            ids.MOON_CELL_NEARSIDE_MARE,
            "表側海地域",
            0.0,
            20.0,
            (ids.MOON_CELL_EQUATORIAL_HIGHLANDS,),
            SurfaceTerrain(0.95, 0.95, 0.60, 0.05),
            {ids.WATER: 0.02, ids.REGOLITH: 38.0},
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
            {ids.WATER: 0.06, ids.REGOLITH: 30.0},
        ),
        _moon_cell(
            ids.MOON_CELL_FARSIDE_HIGHLANDS,
            "裏側高地",
            5.0,
            170.0,
            (ids.MOON_CELL_EQUATORIAL_HIGHLANDS,),
            SurfaceTerrain(0.75, 0.80, 0.67, 0.20),
            {ids.WATER: 0.08, ids.REGOLITH: 28.0},
        ),
    )
    for cell in earth_cells + moon_cells:
        graph.add_surface_cell(cell)

    # Operational existence is explicit and separate from spatial context.
    graph.add_operational_node(OperationalNodeState(ids.LEO))
    graph.add_operational_node(OperationalNodeState(ids.LUNAR_ORBIT))

    # Initial scenario Surface Location is mutable geography with a corresponding Operational Node.
    graph.found_location(
        ids.EARTH, "地球産業拠点", ids.EARTH_BODY, ids.EARTH_CELL_INDUSTRIAL
    )

    facets = StaticFacetStore()

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
    facets.set_body(ids.EARTH_BODY, CommunicationField(0.02, 1.0))
    for cell_id in (
        ids.EARTH_CELL_INDUSTRIAL,
        ids.EARTH_CELL_COASTAL,
        ids.EARTH_CELL_INLAND,
    ):
        facets.set(cell_id, IlluminationField(1361.0, 0.50))

    facets.set(ids.LEO, OrbitalField(5400.0))
    facets.set(ids.LEO, GravityField(8.7, 10800.0))
    facets.set(ids.LEO, AtmosphereField(0.0, 0.0, {}))
    facets.set(ids.LEO, IlluminationField(1361.0, 0.62))
    facets.set(ids.LEO, ThermalField(270.0))
    facets.set(ids.LEO, CommunicationField(0.02, 0.98))

    facets.set(ids.LUNAR_ORBIT, OrbitalField(7200.0))
    facets.set(ids.LUNAR_ORBIT, GravityField(1.4, 2300.0))
    facets.set(ids.LUNAR_ORBIT, AtmosphereField(0.0, 0.0, {}))
    facets.set(ids.LUNAR_ORBIT, ThermalField(250.0))
    facets.set(ids.LUNAR_ORBIT, IlluminationField(1361.0, 0.70))
    facets.set(ids.LUNAR_ORBIT, CommunicationField(1.3, 0.95))

    facets.set_body(ids.MOON, GravityField(1.62, 2380.0))
    facets.set_body(ids.MOON, AtmosphereField(0.0, 0.0, {}))
    facets.set_body(ids.MOON, ThermalField(220.0, 90.0, 390.0))
    facets.set_body(ids.MOON, CommunicationField(1.3, 0.75))
    lunar_surface_ids = tuple(cell.id for cell in moon_cells)
    for cell_id in lunar_surface_ids:
        facets.set(cell_id, IlluminationField(1361.0, 0.45))

    facets.set(ids.MOON_CELL_SOUTH_POLAR_RIDGE, IlluminationField(1361.0, 0.78))
    facets.set(ids.MOON_CELL_SOUTH_POLAR_RIDGE, CommunicationField(1.3, 0.85))
    facets.set(ids.MOON_CELL_POLAR_COLD_TRAP, IlluminationField(1361.0, 0.05))
    facets.set(ids.MOON_CELL_POLAR_COLD_TRAP, ThermalField(80.0, 40.0, 120.0))
    facets.set(ids.MOON_CELL_POLAR_COLD_TRAP, CommunicationField(1.3, 0.15))
    facets.set(ids.MOON_CELL_NEARSIDE_MARE, IlluminationField(1361.0, 0.52))
    facets.set(ids.MOON_CELL_NEARSIDE_MARE, CommunicationField(1.3, 1.0))

    return graph, EnvironmentResolver(graph, facets)

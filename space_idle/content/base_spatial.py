from __future__ import annotations

from ..shared import DefinitionId
from ..spatial import (
    AtmosphereField,
    CelestialBodyDef,
    CommunicationField,
    EnvironmentResolver,
    GravityField,
    IlluminationField,
    LocationState,
    OrbitalField,
    SpatialGraph,
    SpatialNodeDef,
    SpatialNodeKind,
    StaticFacetStore,
    SurfaceCellDef,
    SurfaceField,
    SurfacePoint,
    ThermalField,
)
from . import base_ids as ids


def _earth_cell(cell_id, latitude: float, longitude: float, neighbors, terrain: SurfaceField) -> SurfaceCellDef:
    return SurfaceCellDef(
        cell_id,
        ids.EARTH_BODY,
        area_km2=5_000_000.0,
        centroid=SurfacePoint(latitude, longitude),
        neighbor_ids=frozenset(neighbors),
        terrain=terrain,
        static_geology={"crust_accessibility": 1.0},
    )


def _moon_cell(cell_id, latitude: float, longitude: float, neighbors, terrain: SurfaceField) -> SurfaceCellDef:
    return SurfaceCellDef(
        cell_id,
        ids.MOON,
        area_km2=6_000_000.0,
        centroid=SurfacePoint(latitude, longitude),
        neighbor_ids=frozenset(neighbors),
        terrain=terrain,
        static_geology={"regolith_accessibility": 1.0},
    )


def build_spatial_model() -> tuple[SpatialGraph, EnvironmentResolver]:
    graph = SpatialGraph()
    graph.add_body(CelestialBodyDef(ids.EARTH_BODY, "地球"))
    graph.add_body(CelestialBodyDef(ids.MOON, "月"))

    # Non-surface spatial nodes remain static definitions.
    graph.add(
        SpatialNodeDef(
            ids.LEO,
            "地球低軌道",
            body_id=ids.EARTH_BODY,
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
        )
    )
    graph.add(
        SpatialNodeDef(
            ids.LUNAR_ORBIT,
            "月周回軌道",
            body_id=ids.MOON,
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
        )
    )

    earth_cells = (
        _earth_cell(
            ids.EARTH_CELL_INDUSTRIAL,
            35.0,
            139.0,
            (ids.EARTH_CELL_COASTAL, ids.EARTH_CELL_INLAND),
            SurfaceField(1.0, 1.0, 0.05, 0.02),
        ),
        _earth_cell(
            ids.EARTH_CELL_COASTAL,
            20.0,
            150.0,
            (ids.EARTH_CELL_INDUSTRIAL,),
            SurfaceField(0.95, 0.95, 0.07, 0.03),
        ),
        _earth_cell(
            ids.EARTH_CELL_INLAND,
            45.0,
            110.0,
            (ids.EARTH_CELL_INDUSTRIAL,),
            SurfaceField(0.92, 0.96, 0.06, 0.05),
        ),
    )
    moon_cells = (
        _moon_cell(
            ids.MOON_CELL_SOUTH_POLAR_RIDGE,
            -88.0,
            30.0,
            (ids.MOON_CELL_POLAR_COLD_TRAP, ids.MOON_CELL_SOUTH_POLAR_PLAIN),
            SurfaceField(0.90, 0.90, 0.55, 0.10),
        ),
        _moon_cell(
            ids.MOON_CELL_POLAR_COLD_TRAP,
            -89.0,
            50.0,
            (ids.MOON_CELL_SOUTH_POLAR_RIDGE, ids.MOON_CELL_SOUTH_POLAR_PLAIN),
            SurfaceField(0.62, 0.75, 0.60, 0.28),
        ),
        _moon_cell(
            ids.MOON_CELL_SOUTH_POLAR_PLAIN,
            -82.0,
            40.0,
            (
                ids.MOON_CELL_SOUTH_POLAR_RIDGE,
                ids.MOON_CELL_POLAR_COLD_TRAP,
                ids.MOON_CELL_EQUATORIAL_HIGHLANDS,
            ),
            SurfaceField(0.84, 0.86, 0.60, 0.12),
        ),
        _moon_cell(
            ids.MOON_CELL_NEARSIDE_MARE,
            0.0,
            20.0,
            (ids.MOON_CELL_EQUATORIAL_HIGHLANDS,),
            SurfaceField(0.95, 0.95, 0.60, 0.05),
        ),
        _moon_cell(
            ids.MOON_CELL_EQUATORIAL_HIGHLANDS,
            5.0,
            90.0,
            (
                ids.MOON_CELL_SOUTH_POLAR_PLAIN,
                ids.MOON_CELL_NEARSIDE_MARE,
                ids.MOON_CELL_FARSIDE_HIGHLANDS,
            ),
            SurfaceField(0.78, 0.82, 0.65, 0.18),
        ),
        _moon_cell(
            ids.MOON_CELL_FARSIDE_HIGHLANDS,
            5.0,
            170.0,
            (ids.MOON_CELL_EQUATORIAL_HIGHLANDS,),
            SurfaceField(0.75, 0.80, 0.67, 0.20),
        ),
    )
    for cell in earth_cells + moon_cells:
        graph.add_surface_cell(cell)

    # Initial scenario Locations are mutable state over the static surface map.
    graph.add_location(
        LocationState(ids.EARTH, "地球産業拠点", ids.EARTH_BODY, ids.EARTH_CELL_INDUSTRIAL)
    )
    graph.add_location(
        LocationState(
            ids.SOUTH_POLAR_RIDGE,
            "月南極高地縁辺拠点",
            ids.MOON,
            ids.MOON_CELL_SOUTH_POLAR_RIDGE,
        )
    )
    graph.add_location(
        LocationState(
            ids.POLAR_COLD_TRAP,
            "月極域永久影クレーター拠点",
            ids.MOON,
            ids.MOON_CELL_POLAR_COLD_TRAP,
        )
    )
    graph.add_location(
        LocationState(
            ids.NEARSIDE_MARE,
            "月表側海地域拠点",
            ids.MOON,
            ids.MOON_CELL_NEARSIDE_MARE,
        )
    )

    facets = StaticFacetStore()

    for cell_id in (
        ids.EARTH_CELL_INDUSTRIAL,
        ids.EARTH_CELL_COASTAL,
        ids.EARTH_CELL_INLAND,
    ):
        facets.set(cell_id, GravityField(9.80665, 11186.0))
        facets.set(
            cell_id,
            AtmosphereField(
                101325.0,
                1.225,
                {
                    DefinitionId("base.species.n2"): 0.78,
                    DefinitionId("base.species.o2"): 0.21,
                },
            ),
        )
        facets.set(cell_id, ThermalField(288.0))
        facets.set(cell_id, IlluminationField(1361.0, 0.50))
        facets.set(cell_id, CommunicationField(0.02, 1.0))

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

    lunar_surface_ids = tuple(cell.id for cell in moon_cells)
    for cell_id in lunar_surface_ids:
        facets.set(cell_id, GravityField(1.62, 2380.0))
        facets.set(cell_id, AtmosphereField(0.0, 0.0, {}))
        facets.set(cell_id, ThermalField(220.0, 90.0, 390.0))
        facets.set(cell_id, CommunicationField(1.3, 0.75))
        facets.set(cell_id, IlluminationField(1361.0, 0.45))

    facets.set(ids.MOON_CELL_SOUTH_POLAR_RIDGE, IlluminationField(1361.0, 0.78))
    facets.set(ids.MOON_CELL_SOUTH_POLAR_RIDGE, CommunicationField(1.3, 0.85))
    facets.set(ids.MOON_CELL_POLAR_COLD_TRAP, IlluminationField(1361.0, 0.05))
    facets.set(ids.MOON_CELL_POLAR_COLD_TRAP, ThermalField(80.0, 40.0, 120.0))
    facets.set(ids.MOON_CELL_POLAR_COLD_TRAP, CommunicationField(1.3, 0.15))
    facets.set(ids.MOON_CELL_NEARSIDE_MARE, IlluminationField(1361.0, 0.52))
    facets.set(ids.MOON_CELL_NEARSIDE_MARE, CommunicationField(1.3, 1.0))

    return graph, EnvironmentResolver(graph, facets)

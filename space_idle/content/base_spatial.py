from __future__ import annotations

from ..shared import DefinitionId
from ..spatial import AtmosphereField, CommunicationField, EnvironmentResolver, GravityField, IlluminationField, OrbitalField, CelestialBodyDef, SpatialGraph, SpatialNodeDef, SpatialNodeKind, StaticFacetStore, SurfaceField, ThermalField
from .base_ids import EARTH_BODY, EARTH, LEO, MOON, LUNAR_ORBIT, SOUTH_POLAR_RIDGE, POLAR_COLD_TRAP, NEARSIDE_MARE

def build_spatial_model() -> tuple[SpatialGraph, EnvironmentResolver]:
    graph = SpatialGraph()
    graph.add_body(CelestialBodyDef(EARTH_BODY, "地球"))
    graph.add_body(CelestialBodyDef(MOON, "月"))
    for node in (
        SpatialNodeDef(EARTH, "地球地表", body_id=EARTH_BODY, kind=SpatialNodeKind.SURFACE),
        SpatialNodeDef(LEO, "地球低軌道", body_id=EARTH_BODY, kind=SpatialNodeKind.ORBITAL, inherits_parent_environment=False),
        SpatialNodeDef(LUNAR_ORBIT, "月周回軌道", body_id=MOON, kind=SpatialNodeKind.ORBITAL, inherits_parent_environment=False),
        SpatialNodeDef(SOUTH_POLAR_RIDGE, "月南極高地縁辺", body_id=MOON, kind=SpatialNodeKind.SURFACE),
        SpatialNodeDef(POLAR_COLD_TRAP, "月極域永久影クレーター", body_id=MOON, kind=SpatialNodeKind.SURFACE),
        SpatialNodeDef(NEARSIDE_MARE, "月表側海地域", body_id=MOON, kind=SpatialNodeKind.SURFACE),
    ):
        graph.add(node)

    facets = StaticFacetStore()
    facets.set(EARTH, GravityField(9.80665, 11186.0))
    facets.set(EARTH, AtmosphereField(101325.0, 1.225, {DefinitionId("base.species.n2"): 0.78, DefinitionId("base.species.o2"): 0.21}))
    facets.set(EARTH, ThermalField(288.0))
    facets.set(EARTH, IlluminationField(1361.0, 0.50))
    facets.set(EARTH, SurfaceField(1.0, 1.0, 0.05, 0.02))
    facets.set(EARTH, CommunicationField(0.02, 1.0))

    facets.set(LEO, OrbitalField(5400.0))
    facets.set(LEO, GravityField(8.7, 10800.0))
    facets.set(LEO, AtmosphereField(0.0, 0.0, {}))
    facets.set(LEO, IlluminationField(1361.0, 0.62))
    facets.set(LEO, ThermalField(270.0))
    facets.set(LEO, CommunicationField(0.02, 0.98))

    facets.set(LUNAR_ORBIT, OrbitalField(7200.0))
    facets.set(LUNAR_ORBIT, GravityField(1.4, 2300.0))
    facets.set(LUNAR_ORBIT, AtmosphereField(0.0, 0.0, {}))
    facets.set(LUNAR_ORBIT, ThermalField(250.0))
    facets.set(LUNAR_ORBIT, IlluminationField(1361.0, 0.70))
    facets.set(LUNAR_ORBIT, CommunicationField(1.3, 0.95))

    for node in (SOUTH_POLAR_RIDGE, POLAR_COLD_TRAP, NEARSIDE_MARE):
        facets.set(node, GravityField(1.62, 2380.0))
        facets.set(node, AtmosphereField(0.0, 0.0, {}))
        facets.set(node, ThermalField(220.0, 90.0, 390.0))
    facets.set(SOUTH_POLAR_RIDGE, IlluminationField(1361.0, 0.78))
    facets.set(SOUTH_POLAR_RIDGE, SurfaceField(0.90, 0.90, 0.55, 0.10))
    facets.set(SOUTH_POLAR_RIDGE, CommunicationField(1.3, 0.85))
    facets.set(POLAR_COLD_TRAP, IlluminationField(1361.0, 0.05))
    facets.set(POLAR_COLD_TRAP, ThermalField(80.0, 40.0, 120.0))
    facets.set(POLAR_COLD_TRAP, SurfaceField(0.62, 0.75, 0.60, 0.28))
    facets.set(POLAR_COLD_TRAP, CommunicationField(1.3, 0.15))
    facets.set(NEARSIDE_MARE, IlluminationField(1361.0, 0.52))
    facets.set(NEARSIDE_MARE, SurfaceField(0.95, 0.95, 0.60, 0.05))
    facets.set(NEARSIDE_MARE, CommunicationField(1.3, 1.0))
    return graph, EnvironmentResolver(graph, facets)

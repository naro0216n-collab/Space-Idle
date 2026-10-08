"""Static solar system physical baseline; no Operational Node or player State.

Representative mean radii, GM and orbital scales: JPL planetary/satellite
physical parameters and satellite mean elements (2026-10-08 reference).
https://ssd.jpl.nasa.gov/planets/phys_par.html
https://ssd.jpl.nasa.gov/sats/phys_par/sep.html
https://ssd.jpl.nasa.gov/sats/elem/sep.html

Orbital scale is not instantaneous separation. Movement derives characteristic
transfers from the shared physical orbital inputs, without an independent
Cartesian baseline or per-origin/destination route table.
"""

from __future__ import annotations

from ..shared import CelestialBodyId, SpatialNodeId
from ..spatial import (
    AtmosphereField, CelestialBodyDef, GravityField, PhysicalSurface,
    RadiationField, SpatialGraph, SpatialNodeDef, SpatialNodeKind, StaticFacetStore, ThermalField,
)
from . import base_ids as ids


# slug, display, radius_km, heliocentric semimajor axis AU, reference gravity m/s², physical surface
_PLANETS = (
    ("mercury", "水星", 2439.4, 0.387, 3.70, True),
    ("venus", "金星", 6051.8, 0.723, 8.87, True),
    ("mars", "火星", 3389.5, 1.524, 3.71, True),
    ("jupiter", "木星", 69911.0, 5.203, 24.79, False),
    ("saturn", "土星", 58232.0, 9.580, 10.44, False),
    ("uranus", "天王星", 25362.0, 19.20, 8.87, False),
    ("neptune", "海王星", 24622.0, 30.10, 11.15, False),
)

# Parent, slug, name, radius km, GM km³/s², mean orbital semimajor axis km
_SATELLITES = (
    ("mars", "phobos", "フォボス", 11.08, 0.0007087, 9375.0),
    ("mars", "deimos", "ダイモス", 6.2, 0.0000962, 23457.0),
    ("jupiter", "io", "イオ", 1821.49, 5959.91547, 421800.0),
    ("jupiter", "europa", "エウロパ", 1560.80, 3202.71210, 671100.0),
    ("jupiter", "ganymede", "ガニメデ", 2631.20, 9887.83275, 1070400.0),
    ("jupiter", "callisto", "カリスト", 2410.30, 7179.28340, 1882700.0),
    ("saturn", "mimas", "ミマス", 198.20, 2.50349, 186000.0),
    ("saturn", "enceladus", "エンケラドゥス", 252.10, 7.21037, 238400.0),
    ("saturn", "tethys", "テティス", 531.10, 41.21353, 295000.0),
    ("saturn", "dione", "ディオネ", 561.40, 73.11607, 377700.0),
    ("saturn", "rhea", "レア", 763.50, 153.94175, 527200.0),
    ("saturn", "titan", "タイタン", 2574.76, 8978.13710, 1221900.0),
    ("saturn", "iapetus", "イアペトゥス", 734.30, 120.51511, 3560000.0),
    ("uranus", "miranda", "ミランダ", 235.80, 4.3, 129846.0),
    ("uranus", "ariel", "アリエル", 578.90, 83.5, 190929.0),
    ("uranus", "umbriel", "ウンブリエル", 584.70, 85.1, 265986.0),
    ("uranus", "titania", "チタニア", 788.90, 226.9, 436298.0),
    ("uranus", "oberon", "オベロン", 761.40, 205.3, 583511.0),
    ("neptune", "triton", "トリトン", 1352.60, 1428.49546, 354800.0),
    ("neptune", "proteus", "プロテウス", 208.00, 2.58342, 117600.0),
)


def register_solar_system_bodies(graph: SpatialGraph) -> None:
    """Register physical subjects only; does not create logistics endpoints."""
    for slug, name, radius, axis_au, gravity, solid in _PLANETS:
        graph.add_body(CelestialBodyDef(
            id=CelestialBodyId(f"base.body.{slug}"),
            display_name=name,
            mean_radius_km=radius,
            star_system_id=ids.SOL_SYSTEM,
            system_local_transport_geometry=None,
            physical_surface=PhysicalSurface.SOLID if solid else PhysicalSurface.NO_SOLID_SURFACE,
            heliocentric_semimajor_axis_au=axis_au,
            reference_gravity_m_s2=gravity,
        ))
    for parent, slug, name, radius, gm, axis_km in _SATELLITES:
        graph.add_body(CelestialBodyDef(
            id=CelestialBodyId(f"base.body.{slug}"),
            display_name=name,
            mean_radius_km=radius,
            star_system_id=ids.SOL_SYSTEM,
            system_local_transport_geometry=None,
            parent_body_id=CelestialBodyId(f"base.body.{parent}"),
            parent_orbit_semimajor_axis_km=axis_km,
            standard_gravitational_parameter_km3_s2=gm,
        ))


def register_giant_orbital_contexts(graph: SpatialGraph) -> None:
    """Explicit physical orbital destinations for gas giant science and founding.

    These contexts own no Fleet, Inventory, or Transport Allocation. Their
    representative orbital radius is Content, not a fabricated solid surface.
    """
    for slug, name, radius, _axis, _gravity, solid in _PLANETS:
        if solid:
            continue
        graph.add(SpatialNodeDef(
            SpatialNodeId(f"base.spatial.{slug}.orbit"), f"{name}周回軌道",
            ids.SOL_SYSTEM, None,
            body_id=CelestialBodyId(f"base.body.{slug}"),
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
            body_center_orbit_radius_km=radius+5000.0,
        ))


# Static Environmental reference conditions, not newly discovered player knowledge.
# Values are coarse Content baselines (K, Pa, kg/m³, mSv/day), not instantaneous
# weather, launch conditions, measured local dosimetry or rated facility output.
# Radiation rates especially are indicative estimates for design comparison:
# Jovian trapped-particle flux varies strongly across position and time.
# Missing fields are left unknown, not silently replaced by zero.
# Environmental reference: NASA Solar System Exploration / planetary fact sheets.
# Physical gravity and solar distance remain owned by CelestialBodyDef.
# Gas giant reference surfaces deliberately do not receive Site Environment.
_SURFACE_ENV = {
    # body: nominal temperature K, atmospheric pressure Pa, density kg/m³, ambient radiation mSv/day
    "mercury": (440.0, 0.0, 0.0, 0.6),
    "venus": (737.0, 9_200_000.0, 65.0, 0.02),
    "phobos": (233.0, 0.0, 0.0, 0.6),
    "deimos": (233.0, 0.0, 0.0, 0.6),
    "io": (130.0, 0.001, 0.0, 36_000.0),
    "europa": (102.0, 0.0, 0.0, 5_400.0),
    "ganymede": (110.0, 0.0, 0.0, 80.0),
    "callisto": (134.0, 0.0, 0.0, 0.1),
    "mimas": (64.0, 0.0, 0.0, 0.5),
    "enceladus": (75.0, 0.0, 0.0, 0.5),
    "tethys": (86.0, 0.0, 0.0, 0.5),
    "dione": (87.0, 0.0, 0.0, 0.5),
    "rhea": (99.0, 0.0, 0.0, 0.5),
    "titan": (94.0, 146_700.0, 5.3, 0.1),
    "iapetus": (130.0, 0.0, 0.0, 0.5),
    "miranda": (60.0, 0.0, 0.0, 0.4),
    "ariel": (65.0, 0.0, 0.0, 0.4),
    "umbriel": (75.0, 0.0, 0.0, 0.4),
    "titania": (70.0, 0.0, 0.0, 0.4),
    "oberon": (70.0, 0.0, 0.0, 0.4),
    "triton": (38.0, 1.5, 0.0, 0.4),
    "proteus": (51.0, 0.0, 0.0, 0.4),
}


def register_solar_system_environment(graph: SpatialGraph, facets: StaticFacetStore) -> None:
    """Resolve Body-local baselines, without parent Environment inheritance."""
    for slug, (temperature, pressure, density, dose) in _SURFACE_ENV.items():
        body_id = CelestialBodyId(f"base.body.{slug}")
        body = graph.bodies[body_id]
        if body.physical_surface is not PhysicalSurface.SOLID:
            raise ValueError("surface reference field assigned to a body without solid surface")
        gravity = body.representative_gravity_m_s2
        if gravity is not None:
            facets.set_body(body_id, GravityField(gravity))
        facets.set_body(body_id, AtmosphereField(pressure, density, {}))
        facets.set_body(body_id, ThermalField(temperature))
        facets.set_body(body_id, RadiationField(dose))


# Selected geological regions, not an exhaustive partition of a planetary globe.
# Potential represents static opportunity, not discovered inventory or survey knowledge.
# Each region is independently selectable for Founding/Survey when its requirements
# are met. Sparse topology can be extended without changing Core.
# body, region key, label, latitude, longitude, illumination availability,
# mineral potential, metal potential, volatile-bearing potential
_SURFACE_REGIONS = (
    ("mercury", "polar", "北極陰影縁", 86.0, 20.0, 0.12, 26.0, 9.0, 0.6),
    ("mercury", "equator", "赤道高地", 2.0, 145.0, 0.68, 42.0, 14.0, 0.0),
    ("venus", "highland", "高地岩盤域", 20.0, 95.0, 0.24, 30.0, 13.0, 0.0),
    ("venus", "lowland", "低地平原", -12.0, -95.0, 0.12, 38.0, 11.0, 0.0),
    ("phobos", "equator", "赤道岩塊域", 3.0, 70.0, 0.55, 16.0, 5.0, 0.02),
    ("deimos", "ridge", "低起伏尾根域", 18.0, 105.0, 0.54, 12.0, 3.0, 0.02),
    ("io", "plain", "火山性平原", 2.0, 40.0, 0.46, 42.0, 12.0, 0.0),
    ("europa", "ridge", "氷殻リッジ", 12.0, 100.0, 0.40, 11.0, 3.0, 12.0),
    ("ganymede", "plain", "明色溝状地形", 6.0, 80.0, 0.42, 17.0, 5.0, 9.0),
    ("callisto", "crater", "古期クレーター域", 25.0, 125.0, 0.43, 17.0, 4.0, 8.0),
    ("mimas", "crater", "大規模衝突盆地縁", 3.0, 15.0, 0.44, 5.0, 1.0, 8.0),
    ("enceladus", "plain", "氷殻平原", -16.0, 70.0, 0.42, 5.0, 1.0, 12.0),
    ("tethys", "trench", "断裂谷縁", 7.0, 60.0, 0.45, 5.0, 1.0, 8.0),
    ("dione", "ridge", "氷質崖面域", 10.0, 85.0, 0.42, 6.0, 1.0, 9.0),
    ("rhea", "plain", "衝突クレーター平原", -3.0, 120.0, 0.45, 8.0, 2.0, 8.0),
    ("titan", "highland", "水氷高地", 24.0, 110.0, 0.09, 10.0, 2.0, 10.0),
    ("iapetus", "ridge", "赤道山稜域", 1.0, 55.0, 0.40, 12.0, 2.0, 6.0),
    ("miranda", "cliff", "断崖高地", 16.0, 100.0, 0.42, 5.0, 1.0, 6.0),
    ("ariel", "valley", "峡谷地域", 9.0, 80.0, 0.43, 7.0, 1.0, 8.0),
    ("umbriel", "crater", "クレーター平原", 12.0, 40.0, 0.44, 7.0, 1.0, 8.0),
    ("titania", "plain", "氷質断層平原", 15.0, 150.0, 0.44, 9.0, 2.0, 9.0),
    ("oberon", "crater", "衝突盆地", 7.0, 95.0, 0.43, 8.0, 1.0, 8.0),
    ("triton", "plain", "窒素氷平原", -15.0, 40.0, 0.40, 5.0, 1.0, 10.0),
    ("proteus", "crater", "不整形岩塊域", 7.0, 80.0, 0.40, 6.0, 1.0, 5.0),
)


def register_solar_system_regions(graph: SpatialGraph, facets: StaticFacetStore) -> None:
    """Register candidate physical regions, without owning Stock or Survey State."""
    from math import pi

    from ..shared import SurfaceCellId
    from ..spatial import IlluminationField, SurfaceCellDef, SurfacePoint, SurfaceTerrain

    for slug, region, label, lat, lon, availability, mineral, metal, volatile in _SURFACE_REGIONS:
        body_id = CelestialBodyId(f"base.body.{slug}")
        body = graph.bodies[body_id]
        cell_id = SurfaceCellId(f"base.cell.{slug}.{region}")
        # A meaningful local region, never the entire unpartitioned globe.
        area = 4.0 * pi * body.mean_radius_km**2 * 0.01
        potentials = {
            ids.MINERAL_FEEDSTOCK: mineral,
            ids.METAL_ORE: metal,
            ids.VOLATILE_BEARING_MATERIAL: volatile,
        }
        graph.add_surface_cell(SurfaceCellDef(
            cell_id, body_id, area, SurfacePoint(lat, lon), frozenset(),
            SurfaceTerrain(0.8, 0.8, 0.2, 0.1),
            {"crust_accessibility": 0.8, "regolith_accessibility": 0.8},
            {resource: amount for resource, amount in potentials.items() if amount > 0},
            label,
        ))
        flux = graph.representative_solar_flux_w_m2(body_id)
        if flux is not None:
            facets.set(cell_id, IlluminationField(flux, availability))

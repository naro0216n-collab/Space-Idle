"""Static solar system physical baseline; no Operational Node or player State.

Representative mean radii, GM and orbital scales: JPL planetary/satellite
physical parameters and satellite mean elements (2026-10-08 reference).
https://ssd.jpl.nasa.gov/planets/phys_par.html
https://ssd.jpl.nasa.gov/sats/phys_par/sep.html
https://ssd.jpl.nasa.gov/sats/elem/sep.html

Orbital scale is not instantaneous separation.  Movement geometry is deliberately
absent for newly introduced bodies until the shared transfer model can derive it;
providing fabricated Cartesian positions here would silently authorize invalid trips.
"""

from __future__ import annotations

from ..shared import CelestialBodyId
from ..spatial import CelestialBodyDef, PhysicalSurface, SpatialGraph
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

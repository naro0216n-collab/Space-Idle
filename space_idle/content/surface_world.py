"""Physical global surface registration for all solid Solar System bodies.

This is Content geometry, not development progression. Representative geologic
regions supply per-square-kilometre reference parameters. New cells inherit a
regional distribution rather than copying each reference opportunity. Physical
surface area, not the number of seed regions, sets body-wide opportunity.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from math import cos, pi, radians, sin, sqrt, ceil

from ..shared import SurfaceCellId
from ..spatial import (
    IlluminationField, ThermalField, PhysicalSurface, SpatialGraph, StaticFacetStore,
    SurfaceCellDef, SurfaceTerrain, great_circle_distance_km,
)
from ..surface_partition import adjacent_bounds, ring_partition, surface_partition_adjacency


def _ring_count(radius_km: float) -> int:
    # Geographic resolution is a World-design decision, not a performance
    # fallback or something that changes with development. Broad continental
    # provinces remain individually selectable on larger worlds; smaller
    # bodies still support several independent founding/expansion corridors.
    return ceil(7 + 13 * min(1.0, radius_km / 6371.0) ** 0.7)


def _spherical_rings(radius_km: float):
    count = _ring_count(radius_km)
    # Keep a bounded polar ring and provide substantial latitude/longitude
    # choices elsewhere. Different ring shapes have identical metric area.
    columns = tuple(max(4, round(2 * count * sin(pi * (row + 0.5) / count)))
                    for row in range(count))
    return ring_partition(columns)


def _regional_phase(body_id: str, subject: str) -> float:
    return int.from_bytes(sha256(f'{body_id}/{subject}'.encode()).digest()[:4], 'big') / 2**32 * 2 * pi


def _regional_field(latitude: float, longitude: float, phase: float) -> float:
    """Continuous basin/ridge-scale geography, not independent per-Cell noise."""
    lat, lon = radians(latitude), radians(longitude)
    return (0.45 * sin(2 * lat + phase) +
            0.35 * cos(2 * lon - 0.6 * lat + phase * 0.7) +
            0.20 * sin(3 * lon + lat - phase * 0.4))


def _resource_distribution(body_id: str, resource_id: str, latitude: float,
                           longitude: float, distance_to_positive_site: float,
                           radius_km: float) -> float:
    """Resource-dependent deposit continuity and concentration per geographic province.

    Mineral feedstock is widespread. Metal ore forms coherent selected provinces;
    water/volatile opportunities are more localized. Named reference sites retain
    their authored presence/absence; the free regions get varied, connected
    fields rather than a tiny perturbation to an everywhere-present average.
    These are World Content distribution rules, never generic Extraction rules.
    """
    from . import base_ids as ids

    phase = _regional_phase(body_id, str(resource_id))
    field = _regional_field(latitude, longitude, phase)
    near_site = 1 / (1 + (distance_to_positive_site / max(radius_km * 0.8, 1))**4)
    if resource_id == ids.MINERAL_FEEDSTOCK:
        return (0.25 + 0.75 * near_site) * (0.85 + 0.5 * field)
    if resource_id == ids.METAL_ORE:
        if field < -0.23 and near_site < 0.5:
            return 0.0
        return (0.08 + 1.8 * near_site) * max(0.0, field + 0.38)
    # Localized volatile-bearing material, water, and any later Resource type.
    if field < 0.12 and near_site < 0.64:
        return 0.0
    return (0.04 + 2.5 * near_site) * max(0.0, field + 0.18)


def _terrain_variation(baseline: SurfaceTerrain, latitude: float, longitude: float,
                       body_id: str) -> SurfaceTerrain:
    # Region-scale slopes and load-bearing differences make a mineral-rich cell
    # potentially a poor construction site; separate fields need not correlate.
    relief = _regional_field(latitude, longitude, _regional_phase(body_id, 'relief'))
    regolith = _regional_field(latitude, longitude, _regional_phase(body_id, 'regolith'))
    return SurfaceTerrain(
        baseline.terrain_factor * (0.72 + 0.42 * (1 - relief)),
        baseline.bearing_capacity_factor * (0.72 + 0.35 * (1 - relief)),
        baseline.dust_factor * (0.75 + 0.75 * (1 + regolith)),
        baseline.slope_factor * (0.5 + 2.4 * (1 + relief)),
    )


def register_complete_surface_world(graph: SpatialGraph, facets: StaticFacetStore) -> None:
    """Replace sparse reference regions with physical equal-area full coverage.

    Reference IDs are preserved as named geographic cells, so founding and
    Scenario references remain valid. Authored reference regions are sparse
    geological *samples*, not a sum of the entire world's opportunity. Body
    area times reference density establishes a physical Resource budget;
    derived Cell opportunities sum to that budget at any partition resolution.
    """
    reference_by_body = {}
    for cell in graph.surface_cells.values():
        reference_by_body.setdefault(cell.body_id, []).append(cell)
    rebuilt: dict[SurfaceCellId, SurfaceCellDef] = {}
    illumination: dict[SurfaceCellId, IlluminationField] = {}
    climate: dict[SurfaceCellId, ThermalField] = {}
    for body_id, body in sorted(graph.bodies.items(), key=lambda row: str(row[0])):
        if body.physical_surface is PhysicalSurface.NO_SOLID_SURFACE:
            continue
        originals = sorted(reference_by_body.get(body_id, ()), key=lambda cell: str(cell.id))
        if not originals:
            raise ValueError(f'solid body lacks geologic reference geography: {body_id}')
        rings = _spherical_rings(body.mean_radius_km)
        positions = [(ring_idx, column, bounds) for ring_idx, ring in enumerate(rings)
                     for column, bounds in enumerate(ring)]
        # Stable nearest-unoccupied matching preserves all named references,
        # including two reference sites near the same pole.
        reserved: dict[tuple[int, int], SurfaceCellDef] = {}
        available = {(ring_idx, column) for ring_idx, column, _ in positions}
        chosen_reference_positions: dict[SurfaceCellId, tuple[int, int]] = {}
        for original in sorted(originals, key=lambda row: (-len(row.neighbor_ids), str(row.id))):
            local_neighbors = tuple(
                chosen_reference_positions[neighbor] for neighbor in original.neighbor_ids
                if neighbor in chosen_reference_positions
                and great_circle_distance_km(
                    original.centroid, graph.surface_cells[neighbor].centroid, body.mean_radius_km,
                ) < 2.5 * sqrt(4 * pi * body.mean_radius_km**2 / len(positions))
            )
            nearby = (
                {slot for slot in available if any(adjacent_bounds(
                    rings[slot[0]][slot[1]], rings[neighbor[0]][neighbor[1]],
                ) for neighbor in local_neighbors)} if local_neighbors else set()
            )
            options = nearby if nearby else available
            choice = min(options, key=lambda slot: (
                great_circle_distance_km(original.centroid, rings[slot[0]][slot[1]].center(), body.mean_radius_km),
                slot,
            ))
            reserved[choice] = original
            chosen_reference_positions[original.id] = choice
            available.remove(choice)
        rows = []
        flux = graph.representative_solar_flux_w_m2(body_id)
        for ring_idx, column, bounds in positions:
            center = bounds.center()
            site = reserved.get((ring_idx, column))
            id = site.id if site is not None else SurfaceCellId(
                f'base.cell.{str(body_id).rsplit(".", 1)[-1]}.grid.{ring_idx:02d}.{column:03d}'
            )
            nearest = min(originals, key=lambda original: (
                great_circle_distance_km(center, original.centroid, body.mean_radius_km), str(original.id)
            ))
            distances = [(original, great_circle_distance_km(center, original.centroid, body.mean_radius_km))
                         for original in originals]
            # The distance kernel represents region-scale geology. Area and
            # per-area quantities remain explicit in the World definition.
            weights = [(origin, 1 / (1 + (distance / max(1.0, body.mean_radius_km * 0.7))**4))
                       for origin, distance in distances]
            weight_total = sum(weight for _, weight in weights)
            area = bounds.area_km2(body.mean_radius_km)
            potential = {}
            for resource in sorted({resource for original in originals for resource in original.resource_potential_by_resource}):
                density = sum(weight * original.resource_potential_by_resource.get(resource, 0.0) / original.area_km2
                              for original, weight in weights) / weight_total
                positive_distances = [distance for original, distance in distances
                                      if original.resource_potential_by_resource.get(resource, 0.0) > 0]
                variation = _resource_distribution(
                    str(body_id), str(resource), center.latitude_deg, center.longitude_deg,
                    min(positive_distances), body.mean_radius_km,
                )
                # Reference sites encode physical observed presence/absence.
                # Never erase a named deposit, or invent one at a named barren site.
                if site is not None:
                    variation = max(variation, 0.5) if site.resource_potential_by_resource.get(resource, 0) > 0 else 0.0
                value = area * density * variation
                if value > 1e-10:
                    potential[resource] = value
            lat = radians(center.latitude_deg)
            lon = radians(center.longitude_deg)
            terrain = site.terrain if site is not None else _terrain_variation(
                nearest.terrain, center.latitude_deg, center.longitude_deg, str(body_id),
            )
            geology = (dict(site.static_geology) if site is not None else {
                attribute: value * (0.7 + 0.35 * (
                    1 + _regional_field(center.latitude_deg, center.longitude_deg,
                                        _regional_phase(str(body_id), attribute))))
                for attribute, value in nearest.static_geology.items()
            })
            row = SurfaceCellDef(
                id, body_id, area, center, frozenset(), terrain,
                geology, potential,
                site.display_name if site is not None else f'{body.display_name} {ring_idx + 1}-{column + 1}',
                bounds,
            )
            rows.append(row)
            if flux is not None and site is None:
                # A representative local illumination profile, not daily weather.
                baseline = next((facet for (c, kind), facet in facets.facets.items()
                                 if c == nearest.id and kind is IlluminationField), None)
                availability = baseline.availability if baseline is not None else 0.50
                # Representative geography, not date-driven weather. Latitude
                # and topography determine long-run exposure and site tradeoffs.
                exposure = (0.22 + 0.78 * max(0.0, cos(lat)) ** 0.6)
                horizon = 0.80 + 0.20 * max(0.0, terrain.bearing_capacity_factor)
                illumination[id] = IlluminationField(
                    flux, max(0.0, min(1.0, availability * exposure * horizon)),
                )
            if site is None:
                reference_climate = facets.body_facets.get((body_id, ThermalField))
                if reference_climate is not None:
                    # Long-term thermal geography: latitude and continental/
                    # basin structure, never a date-dependent climate tick.
                    province = _regional_field(
                        center.latitude_deg, center.longitude_deg,
                        _regional_phase(str(body_id), 'thermal'),
                    )
                    nominal = reference_climate.nominal_temperature_k * max(
                        0.05, 1.0 - 0.13 * sin(lat)**2 + 0.035 * province,
                    )
                    climate[id] = ThermalField(nominal)
        # Sparse reference regions describe physical resource *density*, not
        # the sum of all deposits on a previously unregistered globe. The
        # global budget is area × sample density; generating more Cells does
        # not multiply it. Geographic contrasts redistribute the same budget.
        reference_area = sum(origin.area_km2 for origin in originals)
        resource_totals = {
            resource: (4 * pi * body.mean_radius_km**2 / reference_area) * sum(
                source.resource_potential_by_resource.get(resource, 0.0) for source in originals
            )
            for resource in {rid for source in originals for rid in source.resource_potential_by_resource}
        }
        generated_totals = {
            resource: sum(row.resource_potential_by_resource.get(resource, 0.0) for row in rows)
            for resource in resource_totals
        }
        normalized = []
        for row in rows:
            normalized.append(replace(row, resource_potential_by_resource={
                resource: value * resource_totals[resource] / generated_totals[resource]
                for resource, value in row.resource_potential_by_resource.items()
                if generated_totals[resource] > 0
            }))
        rows = normalized
        # The same geometric topology is used for World registration and
        # validation; distant named reference regions never create shortcuts.
        topology = surface_partition_adjacency(rows)
        for row in rows:
            rebuilt[row.id] = replace(row, neighbor_ids=topology[row.id])
    graph.surface_cells = rebuilt
    for cell_id, field in illumination.items():
        facets.set(cell_id, field)
    for cell_id, field in climate.items():
        facets.set(cell_id, field)
    # Spatial configuration validation checks full area coverage and topology.
    # Do not validate the unchanged partition again during Content registration.

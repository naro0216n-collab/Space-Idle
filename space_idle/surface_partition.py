"""Spherical equal-area surface registration and physical partition validation.

Cells use explicit latitude/longitude bounds. Each latitude ring has a constant
longitude width; its sine-latitude height is proportional to the number of
Cells in that ring. Thus every cell has the same physical area, regardless of
ring size. The topology is static World data, never derived from development.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, degrees, isclose, isfinite, pi, radians, sin

from .shared import CelestialBodyId, SurfaceCellId
from .spatial import PhysicalSurface, SpatialGraph, SurfacePoint


@dataclass(frozen=True)
class SphericalCellBounds:
    south_deg: float
    north_deg: float
    west_deg: float
    east_deg: float

    def __post_init__(self) -> None:
        if not all(isfinite(x) for x in (self.south_deg, self.north_deg, self.west_deg, self.east_deg)):
            raise ValueError('surface boundary must be finite')
        if not (-90 <= self.south_deg < self.north_deg <= 90
                and -180 <= self.west_deg < self.east_deg <= 180):
            raise ValueError('invalid spherical surface boundary')

    def area_km2(self, radius_km: float) -> float:
        return radius_km ** 2 * (sin(radians(self.north_deg)) - sin(radians(self.south_deg))) * radians(self.east_deg - self.west_deg)

    def center(self) -> SurfacePoint:
        return SurfacePoint(
            degrees(asin((sin(radians(self.south_deg)) + sin(radians(self.north_deg))) / 2)),
            (self.west_deg + self.east_deg) / 2,
        )


def ring_partition(ring_sizes: tuple[int, ...]) -> tuple[tuple[SphericalCellBounds, ...], ...]:
    """Cover a sphere with disjoint equal-area longitude sectors and variable rings."""
    if not ring_sizes or any(type(size) is not int or size < 1 for size in ring_sizes):
        raise ValueError('each spherical ring must contain a positive integer number of cells')
    total = sum(ring_sizes)
    offset = 0
    rings: list[tuple[SphericalCellBounds, ...]] = []
    for count in ring_sizes:
        south = degrees(asin(max(-1.0, min(1.0, 2 * offset / total - 1))))
        north = degrees(asin(max(-1.0, min(1.0, 2 * (offset + count) / total - 1))))
        rings.append(tuple(SphericalCellBounds(
            south, north, -180 + 360 * column / count, -180 + 360 * (column + 1) / count,
        ) for column in range(count)))
        offset += count
    return tuple(rings)


def adjacent_bounds(a: SphericalCellBounds, b: SphericalCellBounds, tolerance: float = 1e-7) -> bool:
    latitude_overlap = min(a.north_deg, b.north_deg) - max(a.south_deg, b.south_deg)
    longitude_overlap = min(a.east_deg, b.east_deg) - max(a.west_deg, b.west_deg)
    return ((latitude_overlap > tolerance and
             (abs(a.east_deg - b.west_deg) <= tolerance or abs(b.east_deg - a.west_deg) <= tolerance or
              (a.west_deg == -180 and b.east_deg == 180) or
              (b.west_deg == -180 and a.east_deg == 180)))
            or (longitude_overlap > tolerance and
                (abs(a.north_deg - b.south_deg) <= tolerance or abs(b.north_deg - a.south_deg) <= tolerance)))


def surface_partition_adjacency(cells) -> dict[SurfaceCellId, frozenset[SurfaceCellId]]:
    """Derive complete shared-edge topology in O(cells log cells), not all pairs.

    Latitude bands are non-overlapping; only sectors of the same or adjacent
    band can share a physical edge. Matching longitudes use one linear sweep.
    """
    rows: dict[tuple[float, float], list] = {}
    for cell in cells:
        bounds = cell.spherical_bounds
        if bounds is None:
            raise ValueError(f'missing spherical bounds: {cell.id}')
        rows.setdefault((round(bounds.south_deg, 10), round(bounds.north_deg, 10)), []).append(cell)
    ordered_bands = sorted(rows)
    neighbors: dict[SurfaceCellId, set[SurfaceCellId]] = {cell.id: set() for cell in cells}

    def connect(a, b) -> None:
        if a.id != b.id and adjacent_bounds(a.spherical_bounds, b.spherical_bounds):
            neighbors[a.id].add(b.id)
            neighbors[b.id].add(a.id)

    for band in ordered_bands:
        row = sorted(rows[band], key=lambda cell: cell.spherical_bounds.west_deg)
        for left, right in zip(row, row[1:]):
            connect(left, right)
        if len(row) > 1:
            connect(row[-1], row[0])  # The ±180° meridian is shared.

    for low, high in zip(ordered_bands, ordered_bands[1:]):
        southern = sorted(rows[low], key=lambda cell: cell.spherical_bounds.west_deg)
        northern = sorted(rows[high], key=lambda cell: cell.spherical_bounds.west_deg)
        left = right = 0
        while left < len(southern) and right < len(northern):
            a = southern[left]
            b = northern[right]
            connect(a, b)
            a_end = a.spherical_bounds.east_deg
            b_end = b.spherical_bounds.east_deg
            if a_end <= b_end + 1e-9:
                left += 1
            if b_end <= a_end + 1e-9:
                right += 1
    return {cell_id: frozenset(ids) for cell_id, ids in neighbors.items()}


def validate_surface_partitions(graph: SpatialGraph, *, require_all_solid: bool = False) -> None:
    """Validate exact global coverage, disjointness, metric area and topology.

    Partial synthetic Worlds remain legal when they have no authored bounds.
    Every real-world body registered with bounds must instead cover all 360°.
    """
    by_body: dict[CelestialBodyId, list] = {}
    for cell in graph.surface_cells.values():
        by_body.setdefault(cell.body_id, []).append(cell)
    for body_id, body in graph.bodies.items():
        cells = by_body.get(body_id, [])
        if body.physical_surface is PhysicalSurface.NO_SOLID_SURFACE:
            if cells:
                raise ValueError(f'non-solid body has surface cells: {body_id}')
            continue
        if not require_all_solid and not any(cell.spherical_bounds is not None for cell in cells):
            continue
        if not cells or any(cell.spherical_bounds is None for cell in cells):
            raise ValueError(f'incomplete physical spherical partition: {body_id}')
        area_expected = 4 * pi * body.mean_radius_km ** 2 / len(cells)
        for cell in cells:
            bounds = cell.spherical_bounds
            if not isclose(bounds.area_km2(body.mean_radius_km), area_expected, rel_tol=1e-10):
                raise ValueError(f'spherical cell area does not match equal-area partition: {cell.id}')
            if not isclose(cell.area_km2, area_expected, rel_tol=1e-10):
                raise ValueError(f'surface cell physical area differs from spherical geometry: {cell.id}')
            if not isclose(cell.centroid.latitude_deg, bounds.center().latitude_deg, abs_tol=1e-8) or not isclose(
                cell.centroid.longitude_deg, bounds.center().longitude_deg, abs_tol=1e-8,
            ):
                raise ValueError(f'surface cell centroid differs from geometry: {cell.id}')
        rings: dict[tuple[float, float], list] = {}
        for cell in cells:
            b = cell.spherical_bounds
            rings.setdefault((round(b.south_deg, 10), round(b.north_deg, 10)), []).append(cell)
        bands = sorted(rings)
        if abs(bands[0][0] + 90) > 1e-8 or abs(bands[-1][1] - 90) > 1e-8:
            raise ValueError(f'surface partition does not cover both poles: {body_id}')
        for lower, upper in zip(bands, bands[1:]):
            if abs(lower[1] - upper[0]) > 1e-8:
                raise ValueError(f'spherical partition has a latitude gap/overlap: {body_id}')
        for band in bands:
            ordered = sorted(rings[band], key=lambda cell: cell.spherical_bounds.west_deg)
            if abs(ordered[0].spherical_bounds.west_deg + 180) > 1e-8 or abs(
                ordered[-1].spherical_bounds.east_deg - 180,
            ) > 1e-8:
                raise ValueError(f'spherical partition has a longitude gap: {body_id}')
            for left, right in zip(ordered, ordered[1:]):
                if abs(left.spherical_bounds.east_deg - right.spherical_bounds.west_deg) > 1e-8:
                    raise ValueError(f'spherical partition has a longitude gap/overlap: {body_id}')
        expected = surface_partition_adjacency(cells)
        for cell in cells:
            if expected[cell.id] != cell.neighbor_ids:
                raise ValueError(f'spherical partition adjacency differs from physical edges: {cell.id}')

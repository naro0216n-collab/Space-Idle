from __future__ import annotations

from dataclasses import dataclass
import heapq
import math

from .facilities import FacilityBook
from .power import PowerSnapshot
from .shared import SpatialNodeId, SurfaceCellId
from .spatial import SpatialGraph

SURFACE_DISTRIBUTION_CAPABILITY = "surface_distribution"


@dataclass(frozen=True)
class SurfaceInfrastructureLoad:
    code: str
    demand: float


@dataclass(frozen=True)
class SurfaceInfrastructureSnapshot:
    location_id: SpatialNodeId
    nominal_capacity: float
    available_capacity: float
    demand: float
    fulfillment: float
    load_sources: tuple[SurfaceInfrastructureLoad, ...]
    limiting_factors: tuple[str, ...]


@dataclass
class SurfaceInfrastructureService:
    """Aggregate intra-Location surface distribution constraint.

    Surface Cells remain physical geography only.  This service turns the
    extent and spread of one Location's developed territory into a Location-
    scoped service load and compares that load with Facility-supplied surface
    distribution capability.  No Cell Inventory or Cell-to-Cell cargo routes
    are created.
    """

    graph: SpatialGraph
    capability_id: str = SURFACE_DISTRIBUTION_CAPABILITY
    network_dependent_capability_ids: frozenset[str] = frozenset({"cargo_transfer"})

    def _characteristic_width(self, cell_id: SurfaceCellId) -> float:
        return math.sqrt(self.graph.surface_cells[cell_id].area_km2)

    def _distance_units(
        self,
        location_id: SpatialNodeId,
        cell_ids: set[SurfaceCellId] | frozenset[SurfaceCellId],
    ) -> dict[SurfaceCellId, float]:
        location = self.graph.locations[location_id]
        core = location.core_cell_id
        if core not in cell_ids:
            raise ValueError("surface infrastructure territory must contain the core cell")
        core_width = self._characteristic_width(core)
        if core_width <= 1e-12:
            raise ValueError("surface cell characteristic width must be positive")

        distances: dict[SurfaceCellId, float] = {core: 0.0}
        pending: list[tuple[float, str, SurfaceCellId]] = [(0.0, str(core), core)]
        while pending:
            distance, _sort_key, current = heapq.heappop(pending)
            if distance > distances[current] + 1e-12:
                continue
            current_width = self._characteristic_width(current)
            for neighbor in sorted(self.graph.surface_cells[current].neighbor_ids, key=str):
                if neighbor not in cell_ids:
                    continue
                neighbor_width = self._characteristic_width(neighbor)
                edge = 0.5 * (current_width + neighbor_width) / core_width
                candidate = distance + edge
                if candidate + 1e-12 < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    heapq.heappush(pending, (candidate, str(neighbor), neighbor))
        if set(distances) != set(cell_ids):
            raise ValueError("surface infrastructure territory must be connected")
        return distances

    def load_sources_for_cells(
        self,
        location_id: SpatialNodeId,
        cell_ids: set[SurfaceCellId] | frozenset[SurfaceCellId],
    ) -> tuple[SurfaceInfrastructureLoad, ...]:
        location = self.graph.locations[location_id]
        core = location.core_cell_id
        core_area = self.graph.surface_cells[core].area_km2
        distances = self._distance_units(location_id, cell_ids)

        territory_area = math.fsum(
            self.graph.surface_cells[cell_id].area_km2 / core_area
            for cell_id in sorted(cell_ids, key=str)
            if cell_id != core
        )
        territory_spread = math.fsum(
            (self.graph.surface_cells[cell_id].area_km2 / core_area)
            * max(0.0, distances[cell_id] - 1.0)
            for cell_id in sorted(cell_ids, key=str)
            if cell_id != core
        )
        rows = []
        if territory_area > 1e-12:
            rows.append(SurfaceInfrastructureLoad("territory_area", territory_area))
        if territory_spread > 1e-12:
            rows.append(SurfaceInfrastructureLoad("territory_spread", territory_spread))
        return tuple(rows)

    def load_sources(self, location_id: SpatialNodeId) -> tuple[SurfaceInfrastructureLoad, ...]:
        location = self.graph.locations[location_id]
        return self.load_sources_for_cells(location_id, location.developed_cell_ids)

    def demand(self, location_id: SpatialNodeId) -> float:
        return math.fsum(row.demand for row in self.load_sources(location_id))

    def snapshot(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
        *,
        cell_ids: set[SurfaceCellId] | frozenset[SurfaceCellId] | None = None,
        additional_loads: tuple[SurfaceInfrastructureLoad, ...] = (),
    ) -> SurfaceInfrastructureSnapshot:
        if location_id not in self.graph.locations:
            raise KeyError(location_id)
        loads = list(
            self.load_sources(location_id)
            if cell_ids is None
            else self.load_sources_for_cells(location_id, cell_ids)
        )
        loads.extend(additional_loads)
        if any(load.demand < 0 for load in loads):
            raise ValueError("surface infrastructure load must be non-negative")
        demand = math.fsum(load.demand for load in loads)
        nominal = facilities.infrastructure_capability_capacity_at(
            location_id, self.capability_id, day
        )
        available = self._available_distribution_capacity(
            location_id, facilities, power, day
        )
        fulfillment = 1.0 if demand <= 1e-12 else min(1.0, available / demand)
        limiting = () if fulfillment >= 1.0 - 1e-9 else ("surface_infrastructure",)
        return SurfaceInfrastructureSnapshot(
            location_id,
            nominal,
            available,
            demand,
            fulfillment,
            tuple(loads),
            limiting,
        )

    def _available_distribution_capacity(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int,
    ) -> float:
        """Available network supply before applying the network to consumers.

        This deliberately does not call FacilityBook.available_capability_capacity_at,
        because remote Facility availability itself may depend on this service.
        """
        contributions: list[float] = []
        for facility in sorted(
            facilities.active_compatible_at(location_id, day), key=lambda row: str(row.id)
        ):
            definition = facilities.definitions[facility.definition_id]
            utilization = max(
                0.0, min(1.0, power.utilization_by_facility.get(facility.id, 1.0))
            )
            maintenance = max(
                0.0,
                min(
                    1.0,
                    power.maintenance_factor_by_facility.get(
                        facility.id, facilities.maintenance_factor(facility.id)
                    ),
                ),
            )
            for supply in definition.capability_supplies:
                if supply.id == self.capability_id:
                    contributions.append(
                        supply.rated_capacity * utilization * maintenance
                    )
        return math.fsum(contributions)

    def facility_availability_factors(
        self,
        location_id: SpatialNodeId,
        capability_id: str,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> dict[object, float]:
        if location_id not in self.graph.locations:
            return {}
        location = self.graph.locations[location_id]
        snapshot = self.snapshot(location_id, facilities, power, day)
        factors: dict[object, float] = {}
        for facility in facilities.all_at(location_id):
            if capability_id in self.network_dependent_capability_ids:
                factors[facility.id] = snapshot.fulfillment
            elif facility.site_cell_id is None or facility.site_cell_id == location.core_cell_id:
                factors[facility.id] = 1.0
            elif facility.site_cell_id in location.developed_cell_ids:
                factors[facility.id] = snapshot.fulfillment
            else:
                factors[facility.id] = 0.0
        return factors

    def cell_access_factor(
        self,
        location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> float:
        location = self.graph.locations[location_id]
        if cell_id not in location.developed_cell_ids:
            return 0.0
        if cell_id == location.core_cell_id:
            return 1.0
        return self.snapshot(location_id, facilities, power, day).fulfillment

    def prospective_development_snapshot(
        self,
        location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> SurfaceInfrastructureSnapshot:
        failures = self.graph.surface_cell_development_failures(location_id, cell_id)
        if failures:
            raise ValueError("; ".join(detail for _code, detail in failures))
        cells = set(self.graph.locations[location_id].developed_cell_ids)
        cells.add(cell_id)
        return self.snapshot(location_id, facilities, power, day, cell_ids=cells)

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math

from .facilities import FacilityBook
from .power import PowerSnapshot
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .service_capacity import ServiceCapacityAllocationPlan, ServiceCapacityRequest
from .shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .spatial import SpatialGraph, great_circle_distance_km

SURFACE_DISTRIBUTION_SERVICE = "surface_distribution"
SURFACE_ACCESS_ANCHOR_CAPABILITY = "surface_access_anchor"


@dataclass(frozen=True)
class SurfaceInfrastructureLoad:
    code: str
    demand: float


@dataclass(frozen=True)
class SurfaceAccessAnchor:
    facility_id: EntityId
    facility_definition_id: DefinitionId
    cell_id: SurfaceCellId


@dataclass(frozen=True)
class SurfaceInfrastructureSnapshot:
    location_id: SpatialNodeId
    nominal_capacity: float
    available_capacity: float
    demand: float
    fulfillment: float
    load_sources: tuple[SurfaceInfrastructureLoad, ...]
    limiting_factors: tuple[str, ...]
    allocated_capacity: float = 0.0
    spare_capacity: float = 0.0


@dataclass
class SurfaceInfrastructureService:
    """Aggregate intra-Location surface distribution constraint.

    Surface Cells remain physical geography only.  This service turns the
    extent and spread of one Location's developed territory into a Location-
    scoped service load and compares that load with Facility-supplied surface
    distribution service capacity.  No Cell Inventory or direct Cell-to-Cell cargo links
    are created.
    """

    graph: SpatialGraph
    facilities: FacilityBook
    service_type: str = SURFACE_DISTRIBUTION_SERVICE
    access_anchor_capability_id: str = SURFACE_ACCESS_ANCHOR_CAPABILITY
    network_dependent_service_types: frozenset[str] = frozenset({"cargo_transfer"})

    def active_access_anchors(
        self, location_id: SpatialNodeId, day: int = 0
    ) -> tuple[SurfaceAccessAnchor, ...]:
        location = self.graph.locations[location_id]
        rows: list[SurfaceAccessAnchor] = []
        for facility in sorted(
            self.facilities.active_compatible_at(location_id, day), key=lambda row: str(row.id)
        ):
            if facility.site_cell_id is None or facility.site_cell_id not in location.developed_cell_ids:
                continue
            definition = self.facilities.definitions[facility.definition_id]
            if any(
                supply.id == self.access_anchor_capability_id
                for supply in definition.capability_supplies
            ):
                rows.append(
                    SurfaceAccessAnchor(
                        facility.id,
                        facility.definition_id,
                        facility.site_cell_id,
                    )
                )
        return tuple(rows)

    def active_access_anchor_cells(
        self, location_id: SpatialNodeId, day: int = 0
    ) -> tuple[SurfaceCellId, ...]:
        return tuple(
            sorted(
                {anchor.cell_id for anchor in self.active_access_anchors(location_id, day)},
                key=str,
            )
        )

    def _anchor_distances(
        self,
        location_id: SpatialNodeId,
        cell_ids: set[SurfaceCellId] | frozenset[SurfaceCellId],
        anchor_cells: tuple[SurfaceCellId, ...],
    ) -> dict[SurfaceCellId, tuple[float, SurfaceCellId]]:
        if not anchor_cells:
            return {}
        body = self.graph.bodies[self.graph.locations[location_id].body_id]
        distances: dict[SurfaceCellId, tuple[float, SurfaceCellId]] = {
            anchor: (0.0, anchor) for anchor in anchor_cells if anchor in cell_ids
        }
        pending: list[tuple[float, str, str, SurfaceCellId, SurfaceCellId]] = [
            (0.0, str(anchor), str(anchor), anchor, anchor)
            for anchor in anchor_cells if anchor in cell_ids
        ]
        heapq.heapify(pending)
        while pending:
            distance, _source_key, _cell_key, source, current = heapq.heappop(pending)
            best = distances.get(current)
            if best is None or distance > best[0] + 1e-12 or source != best[1]:
                continue
            current_cell = self.graph.surface_cells[current]
            for neighbor in sorted(current_cell.neighbor_ids, key=str):
                if neighbor not in cell_ids:
                    continue
                neighbor_cell = self.graph.surface_cells[neighbor]
                edge = great_circle_distance_km(
                    current_cell.centroid, neighbor_cell.centroid, body.mean_radius_km
                )
                candidate = distance + edge
                existing = distances.get(neighbor)
                if (
                    existing is None
                    or candidate < existing[0] - 1e-12
                    or (abs(candidate - existing[0]) <= 1e-12 and str(source) < str(existing[1]))
                ):
                    distances[neighbor] = (candidate, source)
                    heapq.heappush(
                        pending, (candidate, str(source), str(neighbor), source, neighbor)
                    )
        if set(distances) != set(cell_ids):
            raise ValueError("surface infrastructure territory must be connected to an active access anchor")
        return distances

    def load_sources_for_cells(
        self,
        location_id: SpatialNodeId,
        cell_ids: set[SurfaceCellId] | frozenset[SurfaceCellId],
        day: int = 0,
    ) -> tuple[SurfaceInfrastructureLoad, ...]:
        if not cell_ids:
            return ()
        anchors = tuple(
            anchor for anchor in self.active_access_anchor_cells(location_id, day)
            if anchor in cell_ids
        )
        if not anchors:
            return (SurfaceInfrastructureLoad("access_anchor_missing", float(len(cell_ids))),)
        distances = self._anchor_distances(location_id, cell_ids, anchors)
        anchor_set = set(anchors)
        territory_area = 0.0
        territory_spread = 0.0
        for cell_id in sorted(cell_ids, key=str):
            if cell_id in anchor_set:
                continue
            distance_km, anchor_id = distances[cell_id]
            cell = self.graph.surface_cells[cell_id]
            anchor = self.graph.surface_cells[anchor_id]
            area_ratio = cell.area_km2 / anchor.area_km2
            distance_units = distance_km / math.sqrt(anchor.area_km2)
            territory_area += area_ratio
            territory_spread += area_ratio * max(0.0, distance_units - 1.0)
        rows: list[SurfaceInfrastructureLoad] = []
        if territory_area > 1e-12:
            rows.append(SurfaceInfrastructureLoad("territory_area", territory_area))
        if territory_spread > 1e-12:
            rows.append(SurfaceInfrastructureLoad("territory_spread", territory_spread))
        return tuple(rows)

    def load_sources(self, location_id: SpatialNodeId, day: int = 0) -> tuple[SurfaceInfrastructureLoad, ...]:
        location = self.graph.locations[location_id]
        return self.load_sources_for_cells(location_id, location.developed_cell_ids, day)

    def demand(self, location_id: SpatialNodeId, day: int = 0) -> float:
        return math.fsum(row.demand for row in self.load_sources(location_id, day))

    @staticmethod
    def service_request_id(location_id: SpatialNodeId) -> EntityId:
        return EntityId(f"service.surface_distribution:{location_id}")

    def service_request(
        self,
        location_id: SpatialNodeId,
        *,
        requested_rate: float | None = None,
        priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY,
        day: int = 0,
    ) -> ServiceCapacityRequest:
        demand = self.demand(location_id, day) if requested_rate is None else requested_rate
        return ServiceCapacityRequest(
            self.service_request_id(location_id),
            location_id,
            self.service_type,
            max(0.0, demand),
            priority,
            "surface_infrastructure",
            EntityId(f"surface_infrastructure:{location_id}"),
            "territory_distribution",
        )

    def snapshot(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
        *,
        allocation_plan: ServiceCapacityAllocationPlan | None = None,
    ) -> SurfaceInfrastructureSnapshot:
        if location_id not in self.graph.locations:
            raise KeyError(location_id)
        loads = self.load_sources(location_id, day)
        demand = math.fsum(load.demand for load in loads)
        if allocation_plan is None:
            if demand > 1e-12:
                raise ValueError(
                    f"shared surface infrastructure allocation required for {location_id}"
                )
            nominal = facilities.nominal_service_capacity_at(
                location_id, self.service_type, day
            )
            available = self.provider_available_capacity(
                location_id, facilities, power, day
            )
            return SurfaceInfrastructureSnapshot(
                location_id, nominal, available, 0.0, 1.0, loads, (), 0.0, available
            )
        summary = allocation_plan.summary(location_id, self.service_type)
        request_id = self.service_request_id(location_id)
        try:
            allocated = allocation_plan.allocated(request_id)
        except KeyError as exc:
            raise ValueError(
                f"shared surface infrastructure allocation missing for {location_id}"
            ) from exc
        fulfillment = 1.0 if demand <= 1e-12 else min(1.0, allocated / demand)
        limiting = () if fulfillment >= 1.0 - 1e-9 else ("surface_infrastructure",)
        return SurfaceInfrastructureSnapshot(
            location_id,
            summary.nominal_rate,
            summary.enabled_rate,
            demand,
            fulfillment,
            loads,
            limiting,
            allocated,
            summary.spare_rate,
        )

    def provider_available_capacity(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int,
    ) -> float:
        """Resolve only physical provider dependencies for this upstream service."""
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
                    power.maintenance_factor_by_facility.get(facility.id, 1.0),
                ),
            )
            for supply in definition.service_capacity_supplies:
                if supply.service_type == self.service_type:
                    contributions.append(
                        supply.nominal_rate * utilization * maintenance
                    )
        return math.fsum(contributions)

    def fulfillment_from_plan(
        self, location_id: SpatialNodeId, allocation_plan: ServiceCapacityAllocationPlan, day: int = 0
    ) -> float:
        demand = self.demand(location_id, day)
        if demand <= 1e-12:
            return 1.0
        try:
            allocated = allocation_plan.allocated(self.service_request_id(location_id))
        except KeyError as exc:
            raise ValueError(
                f"shared surface infrastructure allocation missing for {location_id}"
            ) from exc
        return max(0.0, min(1.0, allocated / demand))

    def facility_availability_factors(
        self,
        location_id: SpatialNodeId,
        service_type: str,
        facilities: FacilityBook,
        allocation_plan: ServiceCapacityAllocationPlan,
        day: int = 0,
    ) -> dict[EntityId, float]:
        if location_id not in self.graph.locations:
            return {}
        location = self.graph.locations[location_id]
        fulfillment = self.fulfillment_from_plan(location_id, allocation_plan, day)
        factors: dict[EntityId, float] = {}
        for facility in facilities.all_at(location_id):
            if service_type in self.network_dependent_service_types:
                factors[facility.id] = fulfillment
            elif facility.site_cell_id is None:
                factors[facility.id] = 1.0
            elif facility.site_cell_id in location.developed_cell_ids:
                factors[facility.id] = fulfillment
            else:
                factors[facility.id] = 0.0
        return factors

    def cell_access_factor(
        self,
        location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        allocation_plan: ServiceCapacityAllocationPlan,
        day: int = 0,
    ) -> float:
        location = self.graph.locations[location_id]
        if cell_id not in location.developed_cell_ids:
            return 0.0
        return self.fulfillment_from_plan(location_id, allocation_plan, day)

    def prospective_development_snapshot(
        self,
        location_id: SpatialNodeId,
        cell_id: SurfaceCellId,
        allocation_plan: ServiceCapacityAllocationPlan,
        *,
        development_request_id: EntityId | None = None,
        day: int = 0,
    ) -> SurfaceInfrastructureSnapshot:
        failures = self.graph.surface_cell_development_failures(location_id, cell_id)
        if failures:
            raise ValueError("; ".join(detail for _code, detail in failures))
        cells = set(self.graph.locations[location_id].developed_cell_ids)
        cells.add(cell_id)
        loads = self.load_sources_for_cells(location_id, cells, day)
        demand = math.fsum(load.demand for load in loads)
        summary = allocation_plan.summary(location_id, self.service_type)
        try:
            base_allocated = allocation_plan.allocated(self.service_request_id(location_id))
        except KeyError as exc:
            raise ValueError(
                f"shared surface infrastructure allocation missing for {location_id}"
            ) from exc
        if development_request_id is None:
            support = base_allocated + summary.spare_rate
        else:
            try:
                support = base_allocated + allocation_plan.allocated(development_request_id)
            except KeyError as exc:
                raise ValueError(
                    f"surface development allocation missing: {development_request_id}"
                ) from exc
        allocated = min(demand, support)
        fulfillment = 1.0 if demand <= 1e-12 else min(1.0, allocated / demand)
        limiting = () if fulfillment >= 1.0 - 1e-9 else ("surface_infrastructure",)
        return SurfaceInfrastructureSnapshot(
            location_id,
            summary.nominal_rate,
            summary.enabled_rate,
            demand,
            fulfillment,
            loads,
            limiting,
            allocated,
            max(0.0, summary.enabled_rate - allocated),
        )

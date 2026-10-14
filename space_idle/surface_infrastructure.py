from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
import heapq
import math

from .facilities import FacilityBook, FacilityPlacementScope
from .power import PowerSnapshot
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .service_capacity import (
    ServiceCapacityAllocationPlan, ServiceCapacityDependency, ServiceCapacityProvider,
    ServiceCapacityRegistry, ServiceCapacityRequest,
)
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


class SurfaceDistributionWorkProvider(Protocol):
    """Physical work location supplied by an owning Activity Domain."""

    def surface_distribution_activities(
        self, location_id: SpatialNodeId, facilities: FacilityBook, day: int,
    ) -> tuple[tuple[SurfaceCellId, float], ...]: ...


@dataclass
class SurfaceInfrastructureService:
    """Aggregate finite Local Distribution Service for actual geographic work.

    World owns physical geometry, Activity Domains own their work quantities,
    and this service owns only the derived Location-scoped distribution demand.
    Unused developed Cells consume no recurring Service; expanding the physical
    footprint can still consume finite Construction Service during its Project.
    No Cell Inventory or direct Cell-to-Cell cargo routing is introduced.
    """

    graph: SpatialGraph
    facilities: FacilityBook
    service_capacity_registry: ServiceCapacityRegistry
    service_type: str = SURFACE_DISTRIBUTION_SERVICE
    access_anchor_capability_id: str = SURFACE_ACCESS_ANCHOR_CAPABILITY
    # Physical service-volume units, independent of the registered Cell grid.
    # These coefficients are Content-adjustable, not grid-resolution limits.
    area_reference_km2: float = 1_000_000.0
    distance_reference_km: float = 1_000.0
    # Derived Composition wiring; not a second activity or demand State.
    extraction_activity_source: SurfaceDistributionWorkProvider | None = field(default=None, repr=False, compare=False)
    site_facility_units_per_day: float = 1.0
    extraction_t_per_service_unit: float = 1.0

    def __post_init__(self) -> None:
        if (not math.isfinite(self.area_reference_km2) or self.area_reference_km2 <= 0
                or not math.isfinite(self.distance_reference_km) or self.distance_reference_km <= 0
                or not math.isfinite(self.site_facility_units_per_day) or self.site_facility_units_per_day < 0
                or not math.isfinite(self.extraction_t_per_service_unit) or self.extraction_t_per_service_unit <= 0):
            raise ValueError("surface distribution physical units must be finite and positive")

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
        body_id,
        cell_ids: set[SurfaceCellId] | frozenset[SurfaceCellId],
        anchor_cells: tuple[SurfaceCellId, ...],
    ) -> dict[SurfaceCellId, tuple[float, SurfaceCellId]]:
        if not anchor_cells:
            return {}
        body = self.graph.bodies[body_id]
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

    def physical_load_sources_for_cells(
        self, body_id, cell_ids, anchor_cells,
    ) -> tuple[SurfaceInfrastructureLoad, ...]:
        """World-only geography load for stated territory and stated access anchors.

        Does not install or activate an anchor, found a Location, or infer
        Service fulfillment. Construction uses this geometric workload to
        evaluate new territory; operation uses only actual Activity workload.
        """
        cells = frozenset(cell_ids)
        anchors = tuple(sorted(set(anchor_cells), key=str))
        if not cells:
            raise ValueError("physical territory must contain a cell")
        if body_id not in self.graph.bodies:
            raise KeyError(body_id)
        if any(cell not in self.graph.surface_cells or
               self.graph.surface_cells[cell].body_id != body_id for cell in cells):
            raise ValueError("physical territory must contain known cells on one body")
        if not self.graph.cells_connected(cells):
            raise ValueError('physical territory must form a connected Cell region')
        if any(anchor not in cells for anchor in anchors):
            raise ValueError("access anchors must belong to the stated territory")
        if not anchors:
            return (SurfaceInfrastructureLoad(
                "access_anchor_missing",
                math.fsum(self.graph.surface_cells[cell_id].area_km2 for cell_id in cells)
                / self.area_reference_km2,
            ),)
        distances = self._anchor_distances(body_id, cells, anchors)
        territory_area = 0.0
        territory_spread = 0.0
        for cell_id in sorted(cells, key=str):
            distance_km, _anchor_id = distances[cell_id]
            cell = self.graph.surface_cells[cell_id]
            area_units = cell.area_km2 / self.area_reference_km2
            distance_units = distance_km / self.distance_reference_km
            # A site's own access anchor has zero distance, but an entire
            # Cell never becomes an implicit free distribution zone. Finer
            # partitions approximate the same physical area-distance integral.
            territory_area += area_units * min(1.0, distance_units)
            territory_spread += area_units * max(0.0, distance_units - 1.0)
        rows: list[SurfaceInfrastructureLoad] = []
        if territory_area > 1e-12:
            rows.append(SurfaceInfrastructureLoad("territory_area", territory_area))
        if territory_spread > 1e-12:
            rows.append(SurfaceInfrastructureLoad("territory_spread", territory_spread))
        return tuple(rows)

    def load_sources_for_cells(
        self,
        location_id: SpatialNodeId,
        cell_ids: set[SurfaceCellId] | frozenset[SurfaceCellId],
        day: int = 0,
    ) -> tuple[SurfaceInfrastructureLoad, ...]:
        location = self.graph.locations[location_id]
        anchors = self.active_access_anchor_cells(location_id, day)
        return self.physical_load_sources_for_cells(
            location.body_id, cell_ids, (anchor for anchor in anchors if anchor in cell_ids)
        )

    def _active_workload_by_cell(
        self, location_id: SpatialNodeId, day: int,
    ) -> dict[SurfaceCellId, float]:
        """Activity ownership is external; only geographic Service demand lives here."""
        location = self.graph.locations[location_id]
        workloads: dict[SurfaceCellId, float] = {}
        for facility in self.facilities.active_compatible_at(location_id, day):
            if facility.site_cell_id not in location.developed_cell_ids:
                continue
            workloads[facility.site_cell_id] = (
                workloads.get(facility.site_cell_id, 0.0)
                + facility.level * self.site_facility_units_per_day
            )
        source = self.extraction_activity_source
        if source is not None:
            for cell_id, throughput in source.surface_distribution_activities(
                location_id, self.facilities, day,
            ):
                workloads[cell_id] = (workloads.get(cell_id, 0.0)
                                      + throughput / self.extraction_t_per_service_unit)
        return workloads

    def load_sources(self, location_id: SpatialNodeId, day: int = 0) -> tuple[SurfaceInfrastructureLoad, ...]:
        """Only active geographical work consumes finite Local Distribution Service."""
        location = self.graph.locations[location_id]
        workloads = self._active_workload_by_cell(location_id, day)
        if not workloads:
            return ()
        anchors = self.active_access_anchor_cells(location_id, day)
        if not anchors:
            return (SurfaceInfrastructureLoad("access_anchor_missing", math.fsum(workloads.values())),)
        distances = self._anchor_distances(location.body_id, location.developed_cell_ids, anchors)
        rate = math.fsum(
            quantity * distance_km / self.distance_reference_km
            for cell_id, quantity in sorted(workloads.items(), key=lambda row: str(row[0]))
            for distance_km, _anchor_id in (distances[cell_id],)
        )
        return () if rate <= 1e-12 else (SurfaceInfrastructureLoad("activity_distance", rate),)

    def demand(self, location_id: SpatialNodeId, day: int = 0) -> float:
        return math.fsum(row.demand for row in self.load_sources(location_id, day))

    @staticmethod
    def service_request_id(location_id: SpatialNodeId) -> EntityId:
        return EntityId(f"service.surface_distribution:{location_id}")

    def service_capacity_requests(self, day: int) -> tuple[ServiceCapacityRequest, ...]:
        """Declare the Location-wide distribution load as root Service demand."""
        return tuple(
            self.service_request(location_id, day=day)
            for location_id in sorted(self.graph.locations, key=str)
        )

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
            "active_surface_distribution",
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
            nominal, available = self.service_capacity_registry.supply_at(
                location_id,
                self.service_type,
                facilities,
                power,
                day,
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

    def provider_dependencies(
        self, providers: tuple[ServiceCapacityProvider, ...], facilities: FacilityBook
    ) -> tuple[ServiceCapacityDependency, ...]:
        """Derive upstream service edges from provider contracts and physical placement.

        A provider can declare an intrinsic upstream service dependency.  In
        addition, supply emitted by a SURFACE_CELL Facility depends on this
        Location's surface-distribution service.  The derivation is independent
        of the Domain that owns the provider.
        """
        edges: set[tuple[str, str]] = set()
        for provider in providers:
            for service_type in provider.service_capacity_types():
                for upstream_service_type in provider.service_capacity_upstream_services(
                    service_type
                ):
                    edges.add((service_type, upstream_service_type))
                if service_type == self.service_type:
                    continue
                definition_ids = provider.service_capacity_provider_definition_ids(service_type)
                if any(
                    facilities.definitions[definition_id].placement_scope
                    is FacilityPlacementScope.SURFACE_CELL
                    for definition_id in definition_ids
                    if definition_id in facilities.definitions
                ):
                    edges.add((service_type, self.service_type))
        return tuple(
            ServiceCapacityDependency(service_type, upstream_service_type)
            for service_type, upstream_service_type in sorted(edges)
        )

    def provider_availability_factors(
        self,
        location_id: SpatialNodeId,
        service_type: str,
        provider: ServiceCapacityProvider,
        facilities: FacilityBook,
        allocation_plan: ServiceCapacityAllocationPlan,
        day: int = 0,
    ) -> dict[EntityId, float] | None:
        """Return per-provider factors imposed by surface distribution."""
        if location_id not in self.graph.locations or service_type == self.service_type:
            return None
        definition_ids = provider.service_capacity_provider_definition_ids(service_type)
        intrinsic = self.service_type in provider.service_capacity_upstream_services(service_type)
        placement_dependent_ids = {
            definition_id
            for definition_id in definition_ids
            if definition_id in facilities.definitions
            and facilities.definitions[definition_id].placement_scope
            is FacilityPlacementScope.SURFACE_CELL
        }
        if not intrinsic and not placement_dependent_ids:
            return None
        try:
            fulfillment = self.fulfillment_from_plan(location_id, allocation_plan, day)
        except ValueError:
            fulfillment = 1.0 if self.demand(location_id, day) <= 1e-12 else 0.0
        location = self.graph.locations[location_id]
        factors: dict[EntityId, float] = {}
        for facility in facilities.all_at(location_id):
            if facility.definition_id not in definition_ids:
                continue
            if intrinsic or facility.definition_id in placement_dependent_ids:
                if (
                    facility.site_cell_id is not None
                    and facility.site_cell_id not in location.developed_cell_ids
                ):
                    factors[facility.id] = 0.0
                else:
                    factors[facility.id] = fulfillment
            else:
                factors[facility.id] = 1.0
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
        active_development_capacity: float = 0.0,
        day: int = 0,
    ) -> SurfaceInfrastructureSnapshot:
        failures = self.graph.surface_cell_development_failures(location_id, cell_id)
        if failures:
            raise ValueError("; ".join(detail for _code, detail in failures))
        cells = set(self.graph.locations[location_id].developed_cell_ids)
        cells.add(cell_id)
        loads = self.load_sources_for_cells(location_id, cells, day)
        # Development demand is an incremental construction Activity, rather
        # than a standing cost of the prospective territory. Existing
        # production activities retain their actual workload and allocation.
        previous = math.fsum(row.demand for row in self.load_sources_for_cells(
            location_id, self.graph.locations[location_id].developed_cell_ids, day,
        ))
        incremental = max(0.0, math.fsum(load.demand for load in loads) - previous)
        demand = self.demand(location_id, day) + incremental
        summary = allocation_plan.summary(location_id, self.service_type)
        try:
            base_allocated = allocation_plan.allocated(self.service_request_id(location_id))
        except KeyError as exc:
            raise ValueError(
                f"shared surface infrastructure allocation missing for {location_id}"
            ) from exc
        # Surface-development work consumes this same Service through its
        # Construction Execution Bundle, not an independent Service Request.
        # A selected Project may already own part of the finite supply; include
        # only that settled allocation instead of assuming it remains spare.
        support = base_allocated + summary.spare_rate + active_development_capacity
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

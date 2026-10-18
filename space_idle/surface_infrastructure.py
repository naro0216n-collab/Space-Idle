from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
import heapq
import math

from .facilities import FacilityBook, FacilityPlacementScope
from .power import PowerSnapshot
from .priority import ActivityPriority
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
    ) -> tuple[tuple[EntityId, SurfaceCellId, float, ActivityPriority], ...]: ...


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
    _distances_cache: dict[tuple, dict] = field(default_factory=dict, init=False, repr=False, compare=False)

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
        # Geometry is static within a World; the key contains the complete
        # territory and active-anchor identity, so changing either rebuilds
        # the derived routes without persisting another owner of World state.
        cache_key = (body_id, frozenset(cell_ids), anchor_cells)
        cached = self._distances_cache.get(cache_key)
        if cached is not None:
            return cached
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
        if len(self._distances_cache) >= 24:
            self._distances_cache.clear()
        self._distances_cache[cache_key] = distances
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

    def _activity_loads(self, location_id: SpatialNodeId, day: int) -> tuple[tuple[EntityId, ActivityPriority, float], ...]:
        """Allocate geographical flow to its owning Activity, not a Location pool.

        The provider of each Activity owns its physical quantity and priority;
        the Local Distribution domain owns the geographic conversion only.
        Requests are transient and follow the same priority semantics as all
        other Service Capacity consumers.
        """
        location = self.graph.locations[location_id]
        by_facility: dict[EntityId, list[tuple[SurfaceCellId, float]]] = {}
        priorities: dict[EntityId, ActivityPriority] = {}
        for facility in self.facilities.active_compatible_at(location_id, day):
            if facility.site_cell_id not in location.developed_cell_ids:
                continue
            by_facility.setdefault(facility.id, []).append((
                facility.site_cell_id, facility.level * self.site_facility_units_per_day,
            ))
            priorities[facility.id] = facility.activity_priority
        source = self.extraction_activity_source
        if source is not None:
            for owner_id, cell_id, throughput, priority in source.surface_distribution_activities(
                location_id, self.facilities, day,
            ):
                if cell_id not in location.developed_cell_ids:
                    raise ValueError('extraction activity is outside its owned territory')
                by_facility.setdefault(owner_id, []).append((
                    cell_id, throughput / self.extraction_t_per_service_unit,
                ))
                if owner_id in priorities and priorities[owner_id] != priority:
                    raise ValueError('one Activity cannot have conflicting Priority')
                priorities[owner_id] = priority
        if not by_facility:
            return ()
        anchors = self.active_access_anchor_cells(location_id, day)
        distances = (self._anchor_distances(location.body_id, location.developed_cell_ids, anchors)
                     if anchors else {})
        rows = []
        for owner_id, workloads in sorted(by_facility.items(), key=lambda pair: str(pair[0])):
            # A locally situated Activity still needs finite handling capacity;
            # geographic transit adds burden but cannot erase that base work.
            demand = math.fsum(quantity * (1.0 + distances[cell_id][0] / self.distance_reference_km)
                               for cell_id, quantity in workloads) if anchors else math.fsum(
                                   quantity for _, quantity in workloads)
            if demand > 1e-12:
                rows.append((owner_id, priorities[owner_id], demand))
        return tuple(rows)

    def load_sources(self, location_id: SpatialNodeId, day: int = 0) -> tuple[SurfaceInfrastructureLoad, ...]:
        if location_id not in self.graph.locations:
            return ()
        return tuple(SurfaceInfrastructureLoad(f'activity:{owner_id}', demand)
                     for owner_id, _priority, demand in self._activity_loads(location_id, day))

    def demand(self, location_id: SpatialNodeId, day: int = 0) -> float:
        return math.fsum(row.demand for row in self.load_sources(location_id, day))

    @staticmethod
    def service_request_id(location_id: SpatialNodeId, facility_id: EntityId) -> EntityId:
        return EntityId(f'service.surface_distribution:{location_id}:{facility_id}')

    def service_capacity_requests(self, day: int) -> tuple[ServiceCapacityRequest, ...]:
        return tuple(
            ServiceCapacityRequest(
                self.service_request_id(location_id, facility_id), location_id,
                self.service_type, demand, priority, 'surface_activity', facility_id,
                'active_surface_distribution',
            )
            for location_id in sorted(self.graph.locations, key=str)
            for facility_id, priority, demand in self._activity_loads(location_id, day)
        )

    def _allocated_by_activity(
        self, location_id: SpatialNodeId, allocation_plan: ServiceCapacityAllocationPlan,
        day: int,
    ) -> tuple[float, float]:
        requests = self._activity_loads(location_id, day)
        allocated = 0.0
        requested = 0.0
        for owner_id, _priority, demand in requests:
            request_id = self.service_request_id(location_id, owner_id)
            try:
                allocated += allocation_plan.allocated(request_id)
            except KeyError as exc:
                raise ValueError(f'shared surface distribution allocation missing for {owner_id}') from exc
            requested += demand
        return requested, allocated

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
        _requested, allocated = self._allocated_by_activity(location_id, allocation_plan, day)
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
        demand, allocated = self._allocated_by_activity(location_id, allocation_plan, day)
        return 1.0 if demand <= 1e-12 else max(0.0, min(1.0, allocated / demand))

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
                    request_id = self.service_request_id(location_id, facility.id)
                    try:
                        request = allocation_plan.request(request_id)
                        factors[facility.id] = (
                            1.0 if request.requested_rate <= 1e-12 else
                            allocation_plan.allocated(request_id) / request.requested_rate
                        )
                    except KeyError:
                        # An activity with no geographic work consumes no
                        # geographic Service, not the shortage of unrelated work.
                        factors[facility.id] = 1.0
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
        _requested, base_allocated = self._allocated_by_activity(location_id, allocation_plan, day)
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

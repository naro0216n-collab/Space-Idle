from __future__ import annotations

import math

from ..facilities import FacilityBook, FacilityState
from ..inventory import InventoryBook
from ..power import PowerSnapshot
from ..resource_claim import ResourceAllocationPlan
from ..service_capacity import ServiceCapacityAllocationPlan
from ..shared import EntityId, SpatialNodeId
from .models import ProcessSpec, ProcessSnapshot


class IndustryPlanningMixin:
    @staticmethod
    def _storage_delta_per_scale(process: ProcessSpec, inventory: InventoryBook) -> dict[str, float]:
        deltas: dict[str, float] = {}
        for resource_id, output in process.outputs_per_day.items():
            storage_class = inventory.resource_storage_class.get(resource_id)
            if storage_class is not None:
                deltas[storage_class] = deltas.get(storage_class, 0.0) + output
        for resource_id, need in process.inputs_per_day.items():
            storage_class = inventory.resource_storage_class.get(resource_id)
            if storage_class is not None:
                deltas[storage_class] = deltas.get(storage_class, 0.0) - need
        return deltas

    @staticmethod
    def _apply_storage_limits(
        rows: list[tuple[FacilityState, ProcessSpec]],
        location_id: SpatialNodeId,
        inventory: InventoryBook,
        upper_limits: dict[EntityId, float],
    ) -> dict[EntityId, float]:
        """Apply stock-capacity constraints without reallocating input inventory.

        Resource scarcity has already been resolved by ResourceAllocation. Storage
        remains a physical feasibility constraint here; it may lower a process but
        never give another process additional current-tick resource allocation.
        """
        scales = dict(upper_limits)
        storage_delta = {
            facility.id: IndustryPlanningMixin._storage_delta_per_scale(process, inventory)
            for facility, process in rows
        }
        classes = sorted({c for deltas in storage_delta.values() for c in deltas})
        for _ in range(32):
            previous = dict(scales)
            for storage_class in classes:
                free = max(
                    0.0,
                    inventory.usable_storage_capacity_t.get((location_id, storage_class), 0.0)
                    - inventory.stored_in_class(location_id, storage_class),
                )
                consumed = math.fsum(
                    -storage_delta[facility.id].get(storage_class, 0.0) * scales[facility.id]
                    for facility, _process in rows
                    if storage_delta[facility.id].get(storage_class, 0.0) < -1e-12
                )
                producers = [
                    facility.id
                    for facility, _process in rows
                    if storage_delta[facility.id].get(storage_class, 0.0) > 1e-12
                ]
                if not producers:
                    continue
                allowed = free + consumed
                produced = math.fsum(
                    storage_delta[facility_id][storage_class] * scales[facility_id]
                    for facility_id in producers
                )
                if produced <= allowed + 1e-9 or produced <= 1e-12:
                    continue
                ratio = max(0.0, allowed / produced)
                for facility_id in producers:
                    scales[facility_id] *= ratio
            if all(abs(scales[key] - previous[key]) <= 1e-9 for key in scales):
                break
        return scales

    def _plan_site(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int,
        resource_allocations: ResourceAllocationPlan | None = None,
        service_allocations: ServiceCapacityAllocationPlan | None = None,
    ) -> tuple[ProcessSnapshot, ...]:
        rows: list[tuple[FacilityState, ProcessSpec]] = []
        for facility in facilities.active_compatible_at(location_id, day):
            process = self.process_for(facility)
            if process is not None:
                rows.append((facility, process))
        if not rows:
            return ()
        if resource_allocations is None:
            raise ValueError("industry planning requires the shared ResourceAllocationPlan")
        if service_allocations is None:
            raise ValueError("industry planning requires the shared ServiceCapacityAllocationPlan")

        power_factors = {
            facility.id: max(0.0, min(1.0, power.utilization_by_facility.get(facility.id, 1.0)))
            for facility, _process in rows
        }
        maintenance_factors = {
            facility.id: power.maintenance_factor_by_facility.get(facility.id, 1.0)
            for facility, _process in rows
        }
        physical_limits = {
            facility.id: power_factors[facility.id] * maintenance_factors[facility.id]
            for facility, _process in rows
        }
        service_limits: dict[EntityId, float] = {}
        for facility, _process in rows:
            request_id = self._service_request_id(facility.id)
            try:
                allocation = service_allocations.allocation(request_id)
            except KeyError:
                service_limits[facility.id] = 0.0
            else:
                service_limits[facility.id] = (
                    1.0
                    if allocation.requested_rate <= 1e-12
                    else max(0.0, min(1.0, allocation.allocated_rate / allocation.requested_rate))
                )
        resource_limits: dict[EntityId, float] = {}
        allocation_by_resource: dict[tuple[EntityId, object], float] = {}
        for facility, process in rows:
            ratios: list[float] = []
            for resource_id, need in process.inputs_per_day.items():
                if need <= 1e-12:
                    continue
                claim_id = self._resource_claim_id(facility.id, resource_id)
                try:
                    allocated = resource_allocations.allocated(claim_id)
                except KeyError:
                    allocated = 0.0
                allocation_by_resource[(facility.id, resource_id)] = allocated
                ratios.append(max(0.0, allocated) / need)
            resource_limits[facility.id] = min(1.0, min(ratios)) if ratios else 1.0

        upper_limits = {
            facility.id: min(
                physical_limits[facility.id],
                resource_limits[facility.id],
                service_limits[facility.id],
            )
            for facility, _process in rows
        }
        scales = self._apply_storage_limits(rows, location_id, inventory, upper_limits)
        storage_delta = {
            facility.id: self._storage_delta_per_scale(process, inventory)
            for facility, process in rows
        }

        snapshots: list[ProcessSnapshot] = []
        for facility, process in sorted(rows, key=lambda row: str(row[0].id)):
            scale = max(0.0, min(1.0, scales[facility.id]))
            reasons: list[str] = []
            if scale < 1.0 - 1e-9:
                if power_factors[facility.id] < 1.0 - 1e-9 and scale + 1e-9 >= physical_limits[facility.id]:
                    reasons.append("power")
                if maintenance_factors[facility.id] < 1.0 - 1e-9 and scale + 1e-9 >= physical_limits[facility.id]:
                    reasons.append("maintenance")
                if service_limits[facility.id] < 1.0 - 1e-9 and scale + 1e-9 >= service_limits[facility.id]:
                    reasons.append("service_capacity")
                if scale + 1e-9 >= resource_limits[facility.id]:
                    for resource_id, need in process.inputs_per_day.items():
                        if need <= 1e-12:
                            continue
                        allocated = allocation_by_resource.get((facility.id, resource_id), 0.0)
                        if allocated + 1e-9 < need * physical_limits[facility.id]:
                            reasons.append(f"input:{resource_id}")
                if scale + 1e-9 < upper_limits[facility.id]:
                    for storage_class, delta in storage_delta[facility.id].items():
                        if delta > 1e-12:
                            reasons.append(f"storage:{storage_class}")
                if not reasons:
                    reasons.append("allocation")

            snapshots.append(ProcessSnapshot(
                facility.id,
                facility.definition_id,
                process.id,
                scale,
                tuple(dict.fromkeys(reasons)),
                {resource_id: amount * scale for resource_id, amount in process.inputs_per_day.items()},
                {resource_id: amount * scale for resource_id, amount in process.outputs_per_day.items()},
            ))
        return tuple(snapshots)

    def snapshots(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int = 0,
        resource_allocations: ResourceAllocationPlan | None = None,
        service_allocations: ServiceCapacityAllocationPlan | None = None,
    ) -> tuple[ProcessSnapshot, ...]:
        return self._plan_site(
            location_id, facilities, inventory, power, day, resource_allocations,
            service_allocations,
        )

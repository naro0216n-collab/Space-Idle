from __future__ import annotations

from ..facilities import FacilityBook, FacilityState
from ..inventory import InventoryBook
from ..power import PowerSnapshot
from ..shared import DefinitionId, EntityId, SpatialNodeId
from .models import ProcessSpec, ProcessSnapshot


class IndustryPlanningMixin:
    @staticmethod
    def _allocate_inputs(
        rows: list[tuple[FacilityState, ProcessSpec]],
        location_id: SpatialNodeId,
        inventory: InventoryBook,
        upper_limits: dict[EntityId, float],
    ) -> dict[EntityId, float]:
        """Allocate simultaneously available input stock without row-order bias.

        Scales use proportional max-min filling relative to each facility's
        current upper limit. Processes blocked by one input stop claiming other
        shared inputs, so remaining processes can continue to increase.
        """
        scales = {facility.id: 0.0 for facility, _process in rows}
        process_by_id = {facility.id: process for facility, process in rows}
        active = {facility.id for facility, _process in rows if upper_limits[facility.id] > 1e-12}
        remaining = {
            resource_id: inventory.available(location_id, resource_id)
            for _facility, process in rows
            for resource_id, need in process.inputs_per_day.items()
            if need > 1e-12
        }

        while active:
            upper_step = min(
                (upper_limits[facility_id] - scales[facility_id]) / upper_limits[facility_id]
                for facility_id in active
            )
            constraint_steps: list[float] = []
            for resource_id, available in remaining.items():
                rate = sum(
                    process_by_id[facility_id].inputs_per_day.get(resource_id, 0.0) * upper_limits[facility_id]
                    for facility_id in active
                )
                if rate > 1e-12:
                    constraint_steps.append(max(0.0, available) / rate)
            step = max(0.0, min([upper_step, *constraint_steps]) if constraint_steps else upper_step)

            if step > 1e-12:
                for facility_id in active:
                    scales[facility_id] += upper_limits[facility_id] * step
                for resource_id in remaining:
                    used = sum(
                        process_by_id[facility_id].inputs_per_day.get(resource_id, 0.0)
                        * upper_limits[facility_id] * step
                        for facility_id in active
                    )
                    remaining[resource_id] = max(0.0, remaining[resource_id] - used)

            reached_upper = {
                facility_id for facility_id in active
                if scales[facility_id] + 1e-10 >= upper_limits[facility_id]
            }
            blocked = {
                facility_id
                for facility_id in active
                if any(
                    remaining.get(resource_id, 0.0) <= 1e-10 and need > 1e-12
                    for resource_id, need in process_by_id[facility_id].inputs_per_day.items()
                )
            }
            removed = reached_upper | blocked
            if not removed:
                break
            active -= removed
        return scales

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

    def _plan_site(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int,
    ) -> tuple[ProcessSnapshot, ...]:
        rows: list[tuple[FacilityState, ProcessSpec]] = []
        for facility in facilities.active_compatible_at(location_id, day):
            process = self.process_for(facility)
            if process is not None:
                rows.append((facility, process))
        if not rows:
            return ()

        power_limits = {
            facility.id: max(0.0, min(1.0, power.utilization_by_facility.get(facility.id, 1.0)))
            for facility, _process in rows
        }
        process_by_id = {facility.id: process for facility, process in rows}
        storage_delta = {
            facility.id: self._storage_delta_per_scale(process, inventory)
            for facility, process in rows
        }

        # Inputs and shared storage are coupled: storage-limited processes may
        # release common inputs for other processes, while consumers can free
        # storage for producers. Iterate the two physical constraint sets to a
        # stable set of per-facility upper bounds rather than applying storage as
        # an irreversible post-processing clamp.
        storage_limits = dict(power_limits)
        scales = self._allocate_inputs(rows, location_id, inventory, storage_limits)
        for _ in range(32):
            next_storage_limits = dict(power_limits)
            storage_classes = {
                storage_class
                for deltas in storage_delta.values()
                for storage_class, delta in deltas.items()
                if delta > 1e-12
            }
            for storage_class in storage_classes:
                capacity = inventory.storage_service_capacity_t.get((location_id, storage_class), 0.0)
                free = max(0.0, capacity - inventory.stored_in_class(location_id, storage_class))
                consumers = sum(
                    -storage_delta[facility.id].get(storage_class, 0.0) * scales[facility.id]
                    for facility, _process in rows
                    if storage_delta[facility.id].get(storage_class, 0.0) < -1e-12
                )
                allowed_positive = free + consumers
                producers = [
                    facility.id for facility, _process in rows
                    if storage_delta[facility.id].get(storage_class, 0.0) > 1e-12
                ]
                if not producers:
                    continue

                # A producer already held below its current storage bound is
                # constrained elsewhere (typically an input or another storage
                # class). Reserve only what it can currently use, then share the
                # remaining class capacity among unconstrained producers.
                fixed = {
                    facility_id for facility_id in producers
                    if scales[facility_id] + 1e-9 < storage_limits[facility_id]
                }
                fixed_positive = sum(
                    storage_delta[facility_id][storage_class] * scales[facility_id]
                    for facility_id in fixed
                )
                flexible = [facility_id for facility_id in producers if facility_id not in fixed]
                remainder = max(0.0, allowed_positive - fixed_positive)
                denominator = sum(
                    storage_delta[facility_id][storage_class] * power_limits[facility_id]
                    for facility_id in flexible
                )
                ratio = 1.0 if denominator <= remainder + 1e-9 else max(0.0, remainder / denominator)

                for facility_id in fixed:
                    next_storage_limits[facility_id] = min(next_storage_limits[facility_id], scales[facility_id])
                for facility_id in flexible:
                    next_storage_limits[facility_id] = min(
                        next_storage_limits[facility_id], power_limits[facility_id] * ratio
                    )

            next_scales = self._allocate_inputs(rows, location_id, inventory, next_storage_limits)
            if all(
                abs(next_scales[facility.id] - scales[facility.id]) <= 1e-9
                and abs(next_storage_limits[facility.id] - storage_limits[facility.id]) <= 1e-9
                for facility, _process in rows
            ):
                scales = next_scales
                storage_limits = next_storage_limits
                break
            scales = next_scales
            storage_limits = next_storage_limits

        # Derive blocker labels from the final feasible allocation. They explain
        # the physical limiting constraint without prescribing a solution.
        total_input = {
            resource_id: sum(
                process.inputs_per_day.get(resource_id, 0.0) * scales[facility.id]
                for facility, process in rows
            )
            for _facility, process in rows
            for resource_id in process.inputs_per_day
        }
        class_net = {
            storage_class: sum(
                storage_delta[facility.id].get(storage_class, 0.0) * scales[facility.id]
                for facility, _process in rows
            )
            for storage_class in {c for deltas in storage_delta.values() for c in deltas}
        }

        snapshots: list[ProcessSnapshot] = []
        for facility, process in rows:
            scale = max(0.0, min(1.0, scales[facility.id]))
            reasons: list[str] = []
            power_limit = power_limits[facility.id]
            if power_limit < 1.0 - 1e-9 and scale + 1e-9 >= power_limit:
                reasons.append("power")
            if scale < power_limit - 1e-9:
                for resource_id, need in process.inputs_per_day.items():
                    if need <= 1e-12:
                        continue
                    available = inventory.available(location_id, resource_id)
                    if total_input.get(resource_id, 0.0) + 1e-9 >= available:
                        reasons.append(f"input:{resource_id}")
                for storage_class, delta in storage_delta[facility.id].items():
                    if delta <= 1e-12:
                        continue
                    capacity = inventory.storage_service_capacity_t.get((location_id, storage_class), 0.0)
                    free = max(0.0, capacity - inventory.stored_in_class(location_id, storage_class))
                    if class_net.get(storage_class, 0.0) + 1e-9 >= free:
                        reasons.append(f"storage:{storage_class}")
            if scale < 1.0 - 1e-9 and not reasons:
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
    ) -> tuple[ProcessSnapshot, ...]:
        return self._plan_site(location_id, facilities, inventory, power, day)

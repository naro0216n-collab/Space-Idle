from __future__ import annotations

from ..execution_requirements import ExecutionAllocationPlan
from ..facilities import FacilityBook
from ..inventory import InventoryBook
from ..shared import SpatialNodeId
from .models import ProcessSnapshot


class IndustryPlanningMixin:
    @staticmethod
    def _storage_delta_per_scale(process, inventory: InventoryBook) -> dict[str, float]:
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
        day: int,
        execution_allocations: ExecutionAllocationPlan | None = None,
    ) -> tuple[ProcessSnapshot, ...]:
        rows = []
        for facility in facilities.active_compatible_at(location_id, day):
            process = self.process_for(facility)
            if process is not None:
                rows.append((facility, process))
        if not rows:
            return ()
        if execution_allocations is None:
            raise ValueError("industry planning requires the shared ExecutionAllocationPlan")

        snapshots: list[ProcessSnapshot] = []
        for facility, process in sorted(rows, key=lambda row: str(row[0].id)):
            bundle_id = self.execution_bundle_id(facility.id)
            try:
                allocation = execution_allocations.allocation(bundle_id)
            except KeyError:
                scale = 0.0
                limiting = ()
            else:
                scale = allocation.fulfillment
                limiting = allocation.limiting_constraints
            reasons: list[str] = []
            if scale < 1.0 - 1e-9:
                for key in limiting:
                    if key.kind == "resource":
                        reasons.append(f"input:{key.name}")
                    elif key.kind == "service":
                        reasons.append("service_capacity")
                    elif key.kind == "admission":
                        reasons.append(f"storage:{key.name}")
                    else:
                        reasons.append(f"{key.kind}:{key.name}")
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
        day: int = 0,
        execution_allocations: ExecutionAllocationPlan | None = None,
    ) -> tuple[ProcessSnapshot, ...]:
        return self._plan_site(
            location_id, facilities, inventory, day, execution_allocations,
        )

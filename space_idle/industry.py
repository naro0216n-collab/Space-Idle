from __future__ import annotations

from dataclasses import dataclass, field

from .execution_requirements import (
    ExecutionRequirementBundle,
    ResourceRequirement,
    ServiceCapacityRequirement,
    StockOrPoolAdmissionRequirement,
)
from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerSnapshot
from .resource_demand import ResourceDemand
from .shared import DefinitionId, EntityId, SpatialNodeId
from .production import (
    ProcessSpec, ProcessSnapshot, ProcessSelectionMixin,
    IndustryPlanningMixin, IndustryExecutionMixin,
)


@dataclass
class IndustryService(ProcessSelectionMixin, IndustryPlanningMixin, IndustryExecutionMixin):
    processes: dict[DefinitionId, ProcessSpec]
    selected_process_by_facility: dict[EntityId, DefinitionId] = field(default_factory=dict)

    SERVICE_TYPE_PREFIX = "process:"

    @classmethod
    def process_service_type(cls, process_id: DefinitionId) -> str:
        return f"{cls.SERVICE_TYPE_PREFIX}{process_id}"

    @staticmethod
    def execution_bundle_id(facility_id: EntityId) -> EntityId:
        return EntityId(f"execution.industry:{facility_id}")

    def execution_requirement_bundles(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        day: int = 0,
    ) -> tuple[ExecutionRequirementBundle, ...]:
        rows: list[ExecutionRequirementBundle] = []
        for facility in sorted(
            facilities.active_compatible_at(location_id, day), key=lambda row: str(row.id)
        ):
            process = self.process_for(facility)
            if process is None:
                continue
            requirements = [
                ResourceRequirement(resource_id, amount)
                for resource_id, amount in sorted(process.inputs_per_day.items(), key=lambda row: str(row[0]))
                if amount > 1e-12
            ]
            requirements.append(
                ServiceCapacityRequirement(self.process_service_type(process.id), 1.0)
            )
            for storage_class, delta in sorted(
                self._storage_delta_per_scale(process, inventory).items()
            ):
                if delta > 1e-12:
                    requirements.append(
                        StockOrPoolAdmissionRequirement(storage_class, delta)
                    )
            rows.append(ExecutionRequirementBundle(
                id=self.execution_bundle_id(facility.id),
                owner_kind="industry_process",
                owner_id=facility.id,
                purpose=f"process:{process.id}",
                operational_node_id=location_id,
                requested_execution=1.0,
                priority=facility.activity_priority,
                requirements=tuple(requirements),
            ))
        return tuple(rows)

    def service_supply(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
        *,
        provider_factors: dict[EntityId, float] | None = None,
    ) -> tuple[dict[tuple[SpatialNodeId, str], float], dict[tuple[SpatialNodeId, str], float]]:
        nominal: dict[tuple[SpatialNodeId, str], float] = {}
        enabled: dict[tuple[SpatialNodeId, str], float] = {}
        for facility in sorted(
            facilities.active_compatible_at(location_id, day), key=lambda row: str(row.id)
        ):
            process = self.process_for(facility)
            if process is None:
                continue
            key = (location_id, self.process_service_type(process.id))
            nominal[key] = nominal.get(key, 0.0) + 1.0
            upstream = (provider_factors or {}).get(facility.id, 1.0)
            factor = max(
                0.0,
                min(
                    1.0,
                    power.utilization_by_facility.get(facility.id, 1.0)
                    * power.maintenance_factor_by_facility.get(facility.id, 1.0)
                    * upstream,
                ),
            )
            enabled[key] = enabled.get(key, 0.0) + factor
        return nominal, enabled

    def resource_demands(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        day: int = 0,
    ) -> tuple[ResourceDemand, ...]:
        del inventory
        required: dict[tuple[DefinitionId, int], float] = {}
        for facility in facilities.active_compatible_at(location_id, day):
            process = self.process_for(facility)
            if process is None:
                continue
            for resource_id, amount_t in process.inputs_per_day.items():
                if amount_t > 1e-12:
                    key = (resource_id, int(facility.activity_priority))
                    required[key] = required.get(key, 0.0) + amount_t

        owner_id = EntityId(f"industry.site:{location_id}")
        demands: list[ResourceDemand] = []
        for (resource_id, priority), target_t in sorted(
            required.items(), key=lambda row: (str(row[0][0]), -row[0][1])
        ):
            if target_t <= 1e-9:
                continue
            demand_id = EntityId(
                f"demand.industry:{location_id}:{resource_id}:priority-{priority}"
            )
            demands.append(ResourceDemand(
                demand_id,
                "industry",
                owner_id,
                location_id,
                resource_id,
                target_t,
                priority,
                None,
                target_t,
            ))
        return tuple(demands)


__all__ = ["ProcessSpec", "ProcessSnapshot", "IndustryService"]

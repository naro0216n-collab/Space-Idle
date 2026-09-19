from __future__ import annotations

from dataclasses import dataclass

from .execution_requirements import (
    ExecutionRequirementBundle,
    ResourceRequirement,
    ServiceCapacityRequirement,
    StockOrPoolAdmissionRequirement,
)
from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerSnapshot
from .service_capacity import ServiceCapacityScope
from .supply import SupplyRequirement
from .shared import DefinitionId, EntityId, SpatialNodeId
from .production import (
    ProcessSpec, ProcessSnapshot, ProcessSelectionMixin,
    IndustryPlanningMixin, IndustryExecutionMixin,
)


@dataclass
class IndustryService(ProcessSelectionMixin, IndustryPlanningMixin, IndustryExecutionMixin):
    processes: dict[DefinitionId, ProcessSpec]

    SERVICE_TYPE_PREFIX = "process:"

    @classmethod
    def process_service_type(cls, process_id: DefinitionId) -> str:
        return f"{cls.SERVICE_TYPE_PREFIX}{process_id}"

    @staticmethod
    def execution_bundle_id(facility_id: EntityId) -> EntityId:
        return EntityId(f"execution.industry:{facility_id}")

    def execution_requirements_for_process(
        self, process: ProcessSpec, inventory: InventoryBook
    ) -> tuple[ResourceRequirement | ServiceCapacityRequirement | StockOrPoolAdmissionRequirement, ...]:
        """Return the canonical one-unit requirements for a compatible Process.

        Application candidate projections use the same requirement construction as
        live execution, so Process comparison never duplicates Resource or Storage
        semantics in Presentation.
        """
        requirements: list[
            ResourceRequirement | ServiceCapacityRequirement | StockOrPoolAdmissionRequirement
        ] = [
            ResourceRequirement(resource_id, amount)
            for resource_id, amount in sorted(process.inputs_per_day.items(), key=lambda row: str(row[0]))
            if amount > 1e-12
        ]
        requirements.append(
            ServiceCapacityRequirement(self.process_service_type(process.id), 1.0)
        )
        for storage_pool_key, delta in sorted(
            self._storage_delta_per_scale(process, inventory).items()
        ):
            if delta > 1e-12:
                requirements.append(
                    StockOrPoolAdmissionRequirement(storage_pool_key, delta)
                )
        return tuple(requirements)

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
            rows.append(ExecutionRequirementBundle(
                id=self.execution_bundle_id(facility.id),
                owner_kind="industry_process",
                owner_id=facility.id,
                purpose=f"process:{process.id}",
                operational_node_id=location_id,
                requested_execution=1.0,
                priority=facility.activity_priority,
                requirements=self.execution_requirements_for_process(process, inventory),
            ))
        return tuple(rows)


    def service_capacity_types(self) -> tuple[str, ...]:
        return tuple(sorted(
            self.process_service_type(process.id) for process in self.processes.values()
        ))

    def service_capacity_scope(self, service_type: str) -> ServiceCapacityScope:
        if service_type not in self.service_capacity_types():
            raise KeyError(service_type)
        return ServiceCapacityScope.OPERATIONAL_NODE

    def service_capacity_provider_definition_ids(
        self, service_type: str
    ) -> frozenset[DefinitionId]:
        if service_type not in self.service_capacity_types():
            raise KeyError(service_type)
        return frozenset(
            process.facility_def_id
            for process in self.processes.values()
            if self.process_service_type(process.id) == service_type
        )

    def service_capacity_upstream_services(
        self, service_type: str
    ) -> frozenset[str]:
        if service_type not in self.service_capacity_types():
            raise KeyError(service_type)
        return frozenset()

    def service_capacity_supply_at(
        self,
        location_id: SpatialNodeId,
        service_type: str,
        facilities: FacilityBook,
        power: PowerSnapshot | None,
        day: int = 0,
        *,
        provider_factors: dict[EntityId, float] | None = None,
    ) -> tuple[float, float]:
        if power is None:
            nominal = sum(
                1.0
                for facility in facilities.active_compatible_at(location_id, day)
                for process in (self.process_for(facility),)
                if process is not None and self.process_service_type(process.id) == service_type
            )
            return (nominal, nominal)
        nominal, enabled = self.service_supply(
            location_id, facilities, power, day, provider_factors=provider_factors
        )
        key = (location_id, service_type)
        return nominal.get(key, 0.0), enabled.get(key, 0.0)

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

    def supplys(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        day: int = 0,
    ) -> tuple[SupplyRequirement, ...]:
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
        requirements: list[SupplyRequirement] = []
        for (resource_id, priority), target_t in sorted(
            required.items(), key=lambda row: (str(row[0][0]), -row[0][1])
        ):
            if target_t <= 1e-9:
                continue
            requirement_id = EntityId(
                f"requirement.industry:{location_id}:{resource_id}:priority-{priority}"
            )
            requirements.append(SupplyRequirement(
                id=requirement_id,
                owner_kind="industry",
                owner_id=owner_id,
                destination_id=location_id,
                resource_id=resource_id,
                amount_t=target_t,
                priority=priority,
                recurring_rate_t_per_day=target_t,
            ))
        return tuple(requirements)


__all__ = ["ProcessSpec", "ProcessSnapshot", "IndustryService"]

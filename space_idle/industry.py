from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerSnapshot
from .resource_claim import ResourceAllocationPlan, ResourceClaim
from .resource_demand import ResourceDemand
from .service_capacity import ServiceCapacityAllocationPlan, ServiceCapacityRequest
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
    def _service_request_id(facility_id: EntityId) -> EntityId:
        return EntityId(f"service.industry:{facility_id}")

    def service_requests(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        day: int = 0,
    ) -> tuple[ServiceCapacityRequest, ...]:
        """Request one unit of selected Process Capacity per active facility.

        Process input/output rates are defined at full-scale operation.  A
        facility therefore requests one unit of its selected process service;
        the shared allocation determines the executable fraction for the tick.
        """
        requests: list[ServiceCapacityRequest] = []
        for facility in sorted(
            facilities.active_compatible_at(location_id, day), key=lambda row: str(row.id)
        ):
            process = self.process_for(facility)
            if process is None:
                continue
            requests.append(ServiceCapacityRequest(
                self._service_request_id(facility.id),
                location_id,
                self.process_service_type(process.id),
                1.0,
                facility.activity_priority,
                "industry_process",
                facility.id,
                f"process:{process.id}",
            ))
        return tuple(requests)

    def service_supply(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
        *,
        provider_factors: dict[EntityId, float] | None = None,
    ) -> tuple[dict[tuple[SpatialNodeId, str], float], dict[tuple[SpatialNodeId, str], float]]:
        """Return nominal and dependency-enabled Process Capacity supply."""
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
        """Declare one-day input replenishment needs for active processes.

        Demand aggregation preserves the root Activity Priority.  Facilities in
        different bands therefore never collapse into one logistics intent.
        """
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

    @staticmethod
    def _resource_claim_id(facility_id: EntityId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"claim.industry:{facility_id}:{resource_id}")

    def resource_claims(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        day: int = 0,
    ) -> tuple[ResourceClaim, ...]:
        claims: list[ResourceClaim] = []
        for facility in sorted(
            facilities.active_compatible_at(location_id, day), key=lambda row: str(row.id)
        ):
            process = self.process_for(facility)
            if process is None:
                continue
            for resource_id, requested in sorted(
                process.inputs_per_day.items(), key=lambda row: str(row[0])
            ):
                if requested <= 1e-12:
                    continue
                claims.append(ResourceClaim(
                    self._resource_claim_id(facility.id, resource_id),
                    location_id,
                    resource_id,
                    requested,
                    facility.activity_priority,
                    "industry_process",
                    facility.id,
                    f"process:{process.id}",
                    demand_id=EntityId(
                        f"demand.industry:{location_id}:{resource_id}:priority-{int(facility.activity_priority)}"
                    ),
                ))

        return tuple(claims)


__all__ = ["ProcessSpec", "ProcessSnapshot", "IndustryService"]

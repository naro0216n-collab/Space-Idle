from __future__ import annotations

from dataclasses import dataclass

from .facilities import FacilityBook
from .inventory import InventoryBook
from .execution_requirements import ExecutionAllocationPlan, ExecutionRequirementBundle, ResourceRequirement
from .supply import SupplyRequirement
from .shared import DefinitionId, EntityId, SpatialNodeId


@dataclass
class FacilityMaintenanceService:
    """Turns facility investment history into an ordinary physical Supply Requirement.

    Maintenance is not a safety guarantee. Each facility publishes its own requirement
    with a player-visible priority. The shared resource allocator may therefore
    starve a lower-priority facility when local stock and transport capacity are
    insufficient. ``target_stock_days`` and ``reorder_point_days`` are planning
    targets for replenishment only; one day's current consumption is settled as
    one facility-level Execution Requirement Bundle.
    """

    facilities: FacilityBook
    inventory: InventoryBook
    target_stock_days: float = 30.0
    reorder_point_days: float = 15.0

    def __post_init__(self) -> None:
        if self.target_stock_days <= 0:
            raise ValueError("maintenance target stock days must be positive")
        if self.reorder_point_days < 0:
            raise ValueError("maintenance reorder point days must be non-negative")
        if self.reorder_point_days >= self.target_stock_days:
            raise ValueError("maintenance reorder point must be below target stock")

    @staticmethod
    def _requirement_id(facility_id: EntityId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"requirement.maintenance:{facility_id}:{resource_id}")

    def _site_refill_required(
        self,
        totals: dict[tuple[SpatialNodeId, DefinitionId], float],
    ) -> set[tuple[SpatialNodeId, DefinitionId]]:
        refill: set[tuple[SpatialNodeId, DefinitionId]] = set()
        for key, daily_required in totals.items():
            if daily_required <= 1e-12:
                continue
            location_id, resource_id = key
            # Replenishment planning depends on physical site stock, not on
            # current-tick execution allocation, which is transient.
            site_stock = self.inventory.amount(location_id, resource_id)
            if site_stock <= daily_required * self.reorder_point_days + 1e-9:
                refill.add(key)
        return refill

    def supplys(self, day: int = 0) -> tuple[SupplyRequirement, ...]:
        per_facility: dict[EntityId, dict[DefinitionId, float]] = {}
        totals: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        for facility in self.facilities.facilities.values():
            requirements = self.facilities.maintenance_requirements_per_day(facility.id)
            per_facility[facility.id] = requirements
            for resource_id, amount in requirements.items():
                key = (facility.operational_node_id, resource_id)
                totals[key] = totals.get(key, 0.0) + amount

        refill_keys = self._site_refill_required(totals)
        rows: list[SupplyRequirement] = []
        for facility in sorted(self.facilities.facilities.values(), key=lambda row: str(row.id)):
            for resource_id, required in sorted(
                per_facility[facility.id].items(), key=lambda row: str(row[0])
            ):
                if required <= 1e-12:
                    continue
                key = (facility.operational_node_id, resource_id)
                planning_amount = (
                    required * self.target_stock_days if key in refill_keys else required
                )
                rows.append(SupplyRequirement(
                    self._requirement_id(facility.id, resource_id),
                    "facility_maintenance",
                    facility.id,
                    facility.operational_node_id,
                    resource_id,
                    planning_amount,
                    facility.maintenance_priority,
                    None,
                    required,
                ))
        return tuple(rows)

    @staticmethod
    def _execution_bundle_id(facility_id: EntityId) -> EntityId:
        return EntityId(f"execution.maintenance:{facility_id}")

    def execution_requirement_bundles(self, day: int = 0) -> tuple[ExecutionRequirementBundle, ...]:
        del day
        rows: list[ExecutionRequirementBundle] = []
        for facility in sorted(self.facilities.facilities.values(), key=lambda row: str(row.id)):
            requirements = tuple(
                ResourceRequirement(resource_id, required)
                for resource_id, required in sorted(
                    self.facilities.maintenance_requirements_per_day(facility.id).items(),
                    key=lambda row: str(row[0]),
                )
                if required > 1e-12
            )
            if not requirements:
                continue
            rows.append(ExecutionRequirementBundle(
                id=self._execution_bundle_id(facility.id),
                owner_kind="facility_maintenance",
                owner_id=facility.id,
                purpose="daily_maintenance",
                operational_node_id=facility.operational_node_id,
                requested_execution=1.0,
                priority=facility.maintenance_priority,
                requirements=requirements,
            ))
        return tuple(rows)

    def satisfaction_projection(
        self, allocations: ExecutionAllocationPlan
    ) -> dict[EntityId, float]:
        """Project facility maintenance fulfillment from one common bundle."""
        satisfaction: dict[EntityId, float] = {}
        for facility in sorted(self.facilities.facilities.values(), key=lambda row: str(row.id)):
            if not self.facilities.maintenance_requirements_per_day(facility.id):
                satisfaction[facility.id] = 1.0
                continue
            try:
                satisfaction[facility.id] = allocations.fulfillment(
                    self._execution_bundle_id(facility.id)
                )
            except KeyError:
                satisfaction[facility.id] = 0.0
        return satisfaction

    def resource_consumption_projection(
        self, allocations: ExecutionAllocationPlan
    ) -> tuple[tuple[SpatialNodeId, DefinitionId, float], ...]:
        """Project actual recurring maintenance resource consumption.

        Co-inputs share the facility-level fulfillment factor, matching
        ``advance_day``. Allocated material that cannot participate because a
        co-input is short remains stock and is not reported as consumption.
        """
        satisfaction = self.satisfaction_projection(allocations)
        totals: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        for facility in sorted(
            self.facilities.facilities.values(), key=lambda row: str(row.id)
        ):
            factor = satisfaction[facility.id]
            for resource_id, required in sorted(
                self.facilities.maintenance_requirements_per_day(facility.id).items(),
                key=lambda row: str(row[0]),
            ):
                amount = required * factor
                if amount <= 1e-12:
                    continue
                key = (facility.operational_node_id, resource_id)
                totals[key] = totals.get(key, 0.0) + amount
        return tuple(
            (node_id, resource_id, amount)
            for (node_id, resource_id), amount in sorted(
                totals.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
            )
        )

    def advance_day(
        self, allocations: ExecutionAllocationPlan, day: int = 0
    ) -> None:
        for node_id, resource_id, amount in self.resource_consumption_projection(allocations):
            self.inventory.consume_allocated(node_id, resource_id, amount)

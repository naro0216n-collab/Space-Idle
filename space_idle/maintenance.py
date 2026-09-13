from __future__ import annotations

from dataclasses import dataclass

from .facilities import FacilityBook
from .inventory import InventoryBook
from .resource_demand import ResourceDemand
from .shared import DefinitionId, EntityId, SpatialNodeId


@dataclass
class FacilityMaintenanceService:
    """Turns facility investment history into ordinary physical Resource Demand.

    Maintenance is not a safety guarantee. Each facility publishes its own demand
    with a player-visible priority. The shared resource allocator may therefore
    starve a lower-priority facility when local stock and transport capacity are
    insufficient. ``target_stock_days`` and ``reorder_point_days`` are planning
    targets for replenishment only; only one day's requirement is reserved for
    immediate consumption.
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
    def _demand_id(facility_id: EntityId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"demand.maintenance:{facility_id}:{resource_id}")

    def _site_refill_required(
        self,
        totals: dict[tuple[SpatialNodeId, DefinitionId], float],
    ) -> set[tuple[SpatialNodeId, DefinitionId]]:
        refill: set[tuple[SpatialNodeId, DefinitionId]] = set()
        for key, daily_required in totals.items():
            if daily_required <= 1e-12:
                continue
            location_id, resource_id = key
            # Replenishment planning must depend on physical site stock, not
            # transient ResourceDemand reservations. Reservations are derived
            # allocation state and are deliberately absent from Save data.
            site_stock = self.inventory.amount(location_id, resource_id)
            if site_stock <= daily_required * self.reorder_point_days + 1e-9:
                refill.add(key)
        return refill

    def resource_demands(self, day: int = 0) -> tuple[ResourceDemand, ...]:
        per_facility: dict[EntityId, dict[DefinitionId, float]] = {}
        totals: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        for facility in self.facilities.facilities.values():
            requirements = self.facilities.maintenance_requirements_per_day(facility.id)
            per_facility[facility.id] = requirements
            for resource_id, amount in requirements.items():
                key = (facility.location_id, resource_id)
                totals[key] = totals.get(key, 0.0) + amount

        refill_keys = self._site_refill_required(totals)
        rows: list[ResourceDemand] = []
        for facility in sorted(self.facilities.facilities.values(), key=lambda row: str(row.id)):
            for resource_id, required in sorted(
                per_facility[facility.id].items(), key=lambda row: str(row[0])
            ):
                if required <= 1e-12:
                    continue
                key = (facility.location_id, resource_id)
                planning_amount = (
                    required * self.target_stock_days if key in refill_keys else required
                )
                rows.append(ResourceDemand(
                    self._demand_id(facility.id, resource_id),
                    "facility_maintenance",
                    facility.id,
                    facility.location_id,
                    resource_id,
                    planning_amount,
                    facility.maintenance_priority,
                    None,
                    required,
                    True,
                    required,
                ))
        return tuple(rows)

    def advance_day(self, day: int = 0) -> None:
        satisfaction: dict[EntityId, float] = {}
        requirements_by_facility: dict[EntityId, dict[DefinitionId, float]] = {}

        for facility in sorted(self.facilities.facilities.values(), key=lambda row: str(row.id)):
            requirements = self.facilities.maintenance_requirements_per_day(facility.id)
            requirements_by_facility[facility.id] = requirements
            ratios: list[float] = []
            for resource_id, required in sorted(requirements.items(), key=lambda row: str(row[0])):
                if required <= 1e-12:
                    continue
                held = self.inventory.reserved_for(
                    self._demand_id(facility.id, resource_id),
                    facility.location_id,
                    resource_id,
                )
                ratios.append(min(1.0, max(0.0, held) / required))
            satisfaction[facility.id] = min(ratios) if ratios else 1.0

        # Consume all maintenance inputs with the same facility-level factor so
        # a missing co-input is the visible limiter rather than wasting another
        # maintenance material. This does not protect the facility from shortage.
        for facility in sorted(self.facilities.facilities.values(), key=lambda row: str(row.id)):
            factor = satisfaction[facility.id]
            for resource_id, required in sorted(
                requirements_by_facility[facility.id].items(), key=lambda row: str(row[0])
            ):
                amount = required * factor
                if amount <= 1e-12:
                    continue
                self.inventory.consume_reserved(
                    self._demand_id(facility.id, resource_id),
                    facility.location_id,
                    resource_id,
                    amount,
                )

        for facility in self.facilities.facilities.values():
            for resource_id in requirements_by_facility[facility.id]:
                self.inventory.release_reservation(self._demand_id(facility.id, resource_id))
            facility.maintenance_satisfaction = max(
                0.0, min(1.0, satisfaction[facility.id])
            )

from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerSnapshot
from .shared import DefinitionId, SpatialNodeId
from .exploration_models import ExtractionSpec, ExtractionSnapshot
from .survey_service import SurveyService

@dataclass
class ExtractionService:
    specs: dict[DefinitionId, ExtractionSpec]
    survey: SurveyService
    remaining_reserve_t: dict[tuple[SpatialNodeId, DefinitionId], float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key, target in self.survey.targets.items():
            self.remaining_reserve_t.setdefault(key, target.reserve_t)

    def snapshots(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> tuple[ExtractionSnapshot, ...]:
        rows = []
        raw_output: dict[object, float] = {}
        reasons: dict[object, list[str]] = {}
        key_by_facility: dict[object, tuple[SpatialNodeId, DefinitionId] | None] = {}
        spec_by_facility: dict[object, ExtractionSpec] = {}

        for facility in facilities.all_at(location_id):
            spec = self.specs.get(facility.definition_id)
            if spec is None:
                continue
            spec_by_facility[facility.id] = spec
            failures = facilities.activation_failures(facility, day)
            if failures:
                raw_output[facility.id] = 0.0
                reasons[facility.id] = [f"facility:{code}" for code, _ in failures]
                key_by_facility[facility.id] = None
                continue
            key = (location_id, spec.deposit_resource_id)
            key_by_facility[facility.id] = key
            if key not in self.survey.targets:
                raw_output[facility.id] = 0.0
                reasons[facility.id] = [f"deposit:{spec.deposit_resource_id}"]
                continue
            if self.survey.knowledge_level(location_id, spec.deposit_resource_id) < spec.min_knowledge_level:
                raw_output[facility.id] = 0.0
                reasons[facility.id] = [f"survey:{spec.deposit_resource_id}"]
                continue
            target = self.survey.targets[key]
            power_factor = max(0.0, min(1.0, power.utilization_by_facility.get(facility.id, 1.0)))
            maintenance_factor = power.maintenance_factor_by_facility.get(
                facility.id, facilities.maintenance_factor(facility.id)
            )
            utilization = power_factor * maintenance_factor
            raw_output[facility.id] = spec.excavated_t_per_day * target.actual_concentration * utilization
            reasons[facility.id] = []
            if power_factor < 1.0 - 1e-9:
                reasons[facility.id].append("power")
            if maintenance_factor < 1.0 - 1e-9:
                reasons[facility.id].append("maintenance")

        # Shared deposits are depleted proportionally rather than by facility order.
        demand_by_deposit: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        for facility_id, amount in raw_output.items():
            key = key_by_facility.get(facility_id)
            if key is not None and amount > 1e-12:
                demand_by_deposit[key] = demand_by_deposit.get(key, 0.0) + amount
        deposit_ratio = {
            key: min(1.0, self.remaining_reserve_t.get(key, 0.0) / demand)
            for key, demand in demand_by_deposit.items() if demand > 1e-12
        }

        after_deposit: dict[object, float] = {}
        for facility_id, amount in raw_output.items():
            key = key_by_facility.get(facility_id)
            ratio = 1.0 if key is None else deposit_ratio.get(key, 1.0)
            after_deposit[facility_id] = amount * ratio
            if ratio < 1.0 - 1e-9:
                reasons.setdefault(facility_id, []).append("reserve")

        # Storage capacity is also shared site-wide.
        demand_by_class: dict[str, float] = {}
        for facility_id, amount in after_deposit.items():
            if amount <= 1e-12:
                continue
            spec = spec_by_facility[facility_id]
            storage_class = inventory.resource_storage_class.get(spec.output_resource_id)
            if storage_class is not None:
                demand_by_class[storage_class] = demand_by_class.get(storage_class, 0.0) + amount
        class_ratio: dict[str, float] = {}
        for storage_class, demand in demand_by_class.items():
            capacity = inventory.storage_service_capacity_t.get((location_id, storage_class), 0.0)
            free = max(0.0, capacity - inventory.stored_in_class(location_id, storage_class))
            class_ratio[storage_class] = min(1.0, free / demand) if demand > 1e-12 else 1.0

        for facility in facilities.all_at(location_id):
            spec = self.specs.get(facility.definition_id)
            if spec is None:
                continue
            amount = after_deposit.get(facility.id, 0.0)
            base = raw_output.get(facility.id, 0.0)
            storage_class = inventory.resource_storage_class.get(spec.output_resource_id)
            ratio = 1.0 if storage_class is None else class_ratio.get(storage_class, 1.0)
            output = amount * ratio
            if ratio < 1.0 - 1e-9:
                reasons.setdefault(facility.id, []).append(f"storage:{storage_class}")
            scale = 0.0 if base <= 1e-12 else max(0.0, min(1.0, output / base))
            rows.append(ExtractionSnapshot(
                facility.id, facility.definition_id, spec.output_resource_id, scale, output,
                tuple(dict.fromkeys(reasons.get(facility.id, []))),
            ))
        return tuple(rows)

    def advance_day(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> None:
        plan = self.snapshots(location_id, facilities, inventory, power, day)
        extracted_by_deposit: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        for snapshot in plan:
            if snapshot.output_t_per_day <= 1e-12:
                continue
            spec = self.specs[snapshot.facility_def_id]
            key = (location_id, spec.deposit_resource_id)
            extracted_by_deposit[key] = extracted_by_deposit.get(key, 0.0) + snapshot.output_t_per_day
            inventory.add(location_id, snapshot.output_resource_id, snapshot.output_t_per_day)
        for key, amount in extracted_by_deposit.items():
            remaining = self.remaining_reserve_t.get(key, 0.0)
            self.remaining_reserve_t[key] = max(0.0, remaining - amount)

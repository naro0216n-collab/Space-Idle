from __future__ import annotations

from dataclasses import dataclass
import math

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerSnapshot
from .shared import DefinitionId, SpatialNodeId
from .spatial import SpatialGraph
from .exploration_models import ExtractionResourceSnapshot, ExtractionSpec, ExtractionSnapshot


@dataclass
class ExtractionService:
    specs: dict[DefinitionId, ExtractionSpec]
    graph: SpatialGraph

    @staticmethod
    def diminishing_response(installed_capacity: float, effective_opportunity: float) -> float:
        """Generic soft-saturation response with no hard throughput ceiling.

        Opportunity defines the capacity scale over which marginal productivity declines.
        Throughput remains monotonic and unbounded as installed capacity grows.
        """
        capacity = max(0.0, installed_capacity)
        opportunity = max(0.0, effective_opportunity)
        if capacity <= 1e-12 or opportunity <= 1e-12:
            return 0.0
        return opportunity * math.log1p(capacity / opportunity)

    @staticmethod
    def marginal_response(installed_capacity: float, effective_opportunity: float) -> float:
        capacity = max(0.0, installed_capacity)
        opportunity = max(0.0, effective_opportunity)
        if opportunity <= 1e-12:
            return 0.0
        return 1.0 / (1.0 + capacity / opportunity)

    def effective_opportunity(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        location = self.graph.locations.get(location_id)
        if location is None:
            return 0.0
        return math.fsum(
            self.graph.surface_cells[cell_id].resource_potential_by_resource.get(resource_id, 0.0)
            for cell_id in sorted(location.developed_cell_ids, key=str)
        )

    def _facility_inputs(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int,
    ) -> tuple[
        dict[object, ExtractionSpec],
        dict[object, float],
        dict[object, float],
        dict[object, list[str]],
    ]:
        spec_by: dict[object, ExtractionSpec] = {}
        nominal_by: dict[object, float] = {}
        fulfillment_by: dict[object, float] = {}
        reasons: dict[object, list[str]] = {}
        for facility in sorted(facilities.all_at(location_id), key=lambda item: str(item.id)):
            spec = self.specs.get(facility.definition_id)
            if spec is None:
                continue
            spec_by[facility.id] = spec
            nominal = spec.nominal_capacity_t_per_day * facility.level
            nominal_by[facility.id] = nominal
            failures = facilities.activation_failures(facility, day)
            if failures:
                fulfillment_by[facility.id] = 0.0
                reasons[facility.id] = [f"facility:{code}" for code, _ in failures]
                continue
            power_factor = max(0.0, min(1.0, power.utilization_by_facility.get(facility.id, 1.0)))
            maintenance_factor = max(
                0.0,
                min(
                    1.0,
                    power.maintenance_factor_by_facility.get(
                        facility.id, facilities.maintenance_factor(facility.id)
                    ),
                ),
            )
            fulfillment_by[facility.id] = power_factor * maintenance_factor
            reasons[facility.id] = []
            if power_factor < 1.0 - 1e-9:
                reasons[facility.id].append("power")
            if maintenance_factor < 1.0 - 1e-9:
                reasons[facility.id].append("maintenance")
        return spec_by, nominal_by, fulfillment_by, reasons

    def resource_snapshots(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> tuple[ExtractionResourceSnapshot, ...]:
        spec_by, nominal_by, fulfillment_by, _reasons = self._facility_inputs(
            location_id, facilities, power, day
        )
        resource_ids = {
            spec.resource_id for spec in spec_by.values()
        }
        location = self.graph.locations.get(location_id)
        if location is not None:
            for cell_id in location.developed_cell_ids:
                resource_ids.update(
                    self.graph.surface_cells[cell_id].resource_potential_by_resource
                )
        rows: list[ExtractionResourceSnapshot] = []
        for resource_id in sorted(resource_ids, key=str):
            facility_ids = [
                facility_id
                for facility_id, spec in spec_by.items()
                if spec.resource_id == resource_id
            ]
            active_ids = [
                facility_id
                for facility_id in facility_ids
                if not any(reason.startswith("facility:") for reason in _reasons.get(facility_id, ()))
            ]
            ordered_active_ids = sorted(active_ids, key=str)
            installed = math.fsum(nominal_by[facility_id] for facility_id in ordered_active_ids)
            fulfilled_nominal = math.fsum(
                nominal_by[facility_id] * fulfillment_by.get(facility_id, 0.0)
                for facility_id in ordered_active_ids
            )
            operational = 0.0 if installed <= 1e-12 else fulfilled_nominal / installed
            opportunity = self.effective_opportunity(location_id, resource_id)
            response = self.diminishing_response(installed, opportunity)
            output = response * operational
            diminishing_efficiency = 0.0 if installed <= 1e-12 else response / installed
            rows.append(
                ExtractionResourceSnapshot(
                    resource_id,
                    opportunity,
                    installed,
                    operational,
                    diminishing_efficiency,
                    self.marginal_response(installed, opportunity) * operational,
                    output,
                )
            )
        return tuple(rows)

    def snapshots(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> tuple[ExtractionSnapshot, ...]:
        spec_by, nominal_by, fulfillment_by, reasons = self._facility_inputs(
            location_id, facilities, power, day
        )
        resource_summary = {
            row.resource_id: row
            for row in self.resource_snapshots(location_id, facilities, power, day)
        }

        pre_storage: dict[object, float] = {}
        for resource_id, summary in resource_summary.items():
            ids = [
                facility_id
                for facility_id, spec in spec_by.items()
                if spec.resource_id == resource_id
                and not any(reason.startswith("facility:") for reason in reasons.get(facility_id, ()))
            ]
            ordered_ids = sorted(ids, key=str)
            weighted = math.fsum(
                nominal_by[facility_id] * fulfillment_by.get(facility_id, 0.0)
                for facility_id in ordered_ids
            )
            if summary.effective_opportunity <= 1e-12 and any(
                nominal_by[facility_id] > 1e-12 for facility_id in ids
            ):
                for facility_id in ordered_ids:
                    reasons.setdefault(facility_id, []).append(f"resource_opportunity:{resource_id}")
            for facility_id in ordered_ids:
                contribution = nominal_by[facility_id] * fulfillment_by.get(facility_id, 0.0)
                pre_storage[facility_id] = (
                    0.0 if weighted <= 1e-12 else summary.output_t_per_day * contribution / weighted
                )

        storage_classes = sorted({
            storage_class
            for facility_id, amount in pre_storage.items()
            if amount > 1e-12
            for storage_class in (inventory.resource_storage_class.get(spec_by[facility_id].output_resource_id),)
            if storage_class is not None
        })
        demand_by_class = {
            storage_class: math.fsum(
                amount
                for facility_id, amount in pre_storage.items()
                if amount > 1e-12
                and inventory.resource_storage_class.get(spec_by[facility_id].output_resource_id) == storage_class
            )
            for storage_class in storage_classes
        }
        class_ratio: dict[str, float] = {}
        for storage_class in storage_classes:
            demand = demand_by_class[storage_class]
            capacity = inventory.storage_service_capacity_t.get((location_id, storage_class), 0.0)
            free = max(0.0, capacity - inventory.stored_in_class(location_id, storage_class))
            class_ratio[storage_class] = min(1.0, free / demand) if demand > 1e-12 else 1.0

        rows: list[ExtractionSnapshot] = []
        for facility in sorted(facilities.all_at(location_id), key=lambda item: str(item.id)):
            spec = self.specs.get(facility.definition_id)
            if spec is None:
                continue
            nominal = nominal_by.get(facility.id, spec.nominal_capacity_t_per_day * facility.level)
            amount = pre_storage.get(facility.id, 0.0)
            storage_class = inventory.resource_storage_class.get(spec.output_resource_id)
            storage_ratio = 1.0 if storage_class is None else class_ratio.get(storage_class, 1.0)
            output = amount * storage_ratio
            if storage_ratio < 1.0 - 1e-9:
                reasons.setdefault(facility.id, []).append(f"storage:{storage_class}")
            summary = resource_summary.get(spec.resource_id)
            opportunity = 0.0 if summary is None else summary.effective_opportunity
            marginal = 0.0 if summary is None else summary.marginal_efficiency
            scale = 0.0 if nominal <= 1e-12 else max(0.0, min(1.0, output / nominal))
            rows.append(
                ExtractionSnapshot(
                    facility.id,
                    facility.definition_id,
                    spec.resource_id,
                    spec.output_resource_id,
                    nominal,
                    opportunity,
                    marginal,
                    scale,
                    output,
                    tuple(dict.fromkeys(reasons.get(facility.id, []))),
                )
            )
        return tuple(rows)

    def advance_day(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int = 0,
    ) -> None:
        snapshots = self.snapshots(location_id, facilities, inventory, power, day)
        resource_ids = sorted(
            {snapshot.output_resource_id for snapshot in snapshots},
            key=str,
        )
        for resource_id in resource_ids:
            output = math.fsum(
                snapshot.output_t_per_day
                for snapshot in snapshots
                if snapshot.output_resource_id == resource_id
            )
            if output > 1e-12:
                inventory.add(location_id, resource_id, output)

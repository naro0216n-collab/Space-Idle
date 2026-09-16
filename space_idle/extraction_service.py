from __future__ import annotations

from dataclasses import dataclass
import math

from .execution_requirements import (
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    ServiceCapacityRequirement,
    StockOrPoolAdmissionRequirement,
)
from .facilities import FacilityBook
from .inventory import InventoryBook
from .knowledge import DomainActivity
from .power import PowerSnapshot
from .shared import DefinitionId, EntityId, SpatialNodeId
from .site import evaluate_physical_site_requirements
from .spatial import EnvironmentResolver, SpatialGraph
from .surface_infrastructure import SurfaceInfrastructureService
from .exploration_models import ExtractionResourceSnapshot, ExtractionSpec, ExtractionSnapshot


@dataclass
class ExtractionService:
    SERVICE_TYPE_PREFIX = "extraction:"

    specs: dict[DefinitionId, ExtractionSpec]
    graph: SpatialGraph
    environment: EnvironmentResolver
    surface_infrastructure: SurfaceInfrastructureService

    @classmethod
    def service_type(cls, resource_id: DefinitionId) -> str:
        return f"{cls.SERVICE_TYPE_PREFIX}{resource_id}"

    @staticmethod
    def execution_bundle_id(facility_id: EntityId) -> EntityId:
        return EntityId(f"execution.extraction:{facility_id}")

    @staticmethod
    def diminishing_response(installed_capacity: float, effective_opportunity: float) -> float:
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

    def static_opportunity(self, location_id: SpatialNodeId, resource_id: DefinitionId) -> float:
        location = self.graph.locations.get(location_id)
        if location is None:
            return 0.0
        return math.fsum(
            self.graph.surface_cells[cell_id].resource_potential_by_resource.get(resource_id, 0.0)
            for cell_id in sorted(location.developed_cell_ids, key=str)
        )

    def _cell_accessibility(self, spec: ExtractionSpec, cell_id, day: int) -> float:
        if evaluate_physical_site_requirements(
            spec.opportunity_requirements, cell_id, day, self.environment
        ):
            return 0.0
        cell = self.graph.surface_cells[cell_id]
        geology = 1.0
        if spec.geology_accessibility_key is not None:
            geology = cell.static_geology.get(spec.geology_accessibility_key, 0.0)
        terrain = 1.0
        if spec.terrain_accessibility_attribute is not None:
            terrain = getattr(cell.terrain, spec.terrain_accessibility_attribute)
        return max(0.0, geology) * max(0.0, terrain)

    def effective_opportunity(
        self,
        location_id: SpatialNodeId,
        resource_id: DefinitionId,
        facilities: FacilityBook,
        power: PowerSnapshot | None = None,
        day: int = 0,
        service_allocations=None,
    ) -> float:
        del power, service_allocations
        location = self.graph.locations.get(location_id)
        if location is None:
            return 0.0
        # Opportunity is physical/geological state. Surface Infrastructure is
        # deliberately absent here and constrains extraction service execution
        # once, through the shared service-capacity dependency graph.
        active_specs = {
            facility.definition_id: self.specs[facility.definition_id]
            for facility in facilities.active_compatible_at(location_id, day)
            if facility.definition_id in self.specs
            and self.specs[facility.definition_id].resource_id == resource_id
        }
        if not active_specs:
            return 0.0
        total = 0.0
        for cell_id in sorted(location.developed_cell_ids, key=str):
            cell = self.graph.surface_cells[cell_id]
            potential = cell.resource_potential_by_resource.get(resource_id, 0.0)
            if potential <= 1e-12:
                continue
            accessibility = max(
                (self._cell_accessibility(spec, cell_id, day) for spec in active_specs.values()),
                default=0.0,
            )
            total += potential * accessibility
        return total

    def _facility_inputs(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int,
    ):
        spec_by = {}
        nominal_by = {}
        fulfillment_by = {}
        reasons = {}
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
            maintenance_factor = max(0.0, min(1.0, power.maintenance_factor_by_facility.get(facility.id, 1.0)))
            fulfillment_by[facility.id] = power_factor * maintenance_factor
            reasons[facility.id] = []
            if power_factor < 1.0 - 1e-9:
                reasons[facility.id].append("power")
            if maintenance_factor < 1.0 - 1e-9:
                reasons[facility.id].append("maintenance")
        return spec_by, nominal_by, fulfillment_by, reasons

    def service_supply(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
        *,
        provider_factors: dict[EntityId, float] | None = None,
    ):
        spec_by, nominal_by, fulfillment_by, _ = self._facility_inputs(
            location_id, facilities, power, day
        )
        nominal = {}
        enabled = {}
        for facility_id, spec in spec_by.items():
            key = (location_id, self.service_type(spec.resource_id))
            amount = nominal_by.get(facility_id, 0.0)
            nominal[key] = nominal.get(key, 0.0) + amount
            upstream = (provider_factors or {}).get(facility_id, 1.0)
            enabled[key] = enabled.get(key, 0.0) + amount * fulfillment_by.get(facility_id, 0.0) * upstream
        return nominal, enabled

    def _full_output_by_facility(
        self, location_id: SpatialNodeId, facilities: FacilityBook, day: int
    ) -> dict[EntityId, float]:
        active = [
            facility
            for facility in facilities.active_compatible_at(location_id, day)
            if facility.definition_id in self.specs
        ]
        result: dict[EntityId, float] = {}
        resources = sorted({self.specs[f.definition_id].resource_id for f in active}, key=str)
        for resource_id in resources:
            rows = [f for f in active if self.specs[f.definition_id].resource_id == resource_id]
            installed = math.fsum(
                self.specs[f.definition_id].nominal_capacity_t_per_day * f.level for f in rows
            )
            response = self.diminishing_response(
                installed,
                self.effective_opportunity(location_id, resource_id, facilities, day=day),
            )
            for facility in rows:
                nominal = self.specs[facility.definition_id].nominal_capacity_t_per_day * facility.level
                result[facility.id] = 0.0 if installed <= 1e-12 else response * nominal / installed
        return result

    def execution_requirement_bundles(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        day: int = 0,
    ) -> tuple[ExecutionRequirementBundle, ...]:
        full_output = self._full_output_by_facility(location_id, facilities, day)
        rows = []
        for facility in sorted(facilities.active_compatible_at(location_id, day), key=lambda row: str(row.id)):
            spec = self.specs.get(facility.definition_id)
            if spec is None:
                continue
            nominal = spec.nominal_capacity_t_per_day * facility.level
            if nominal <= 1e-12:
                continue
            requirements = [ServiceCapacityRequirement(self.service_type(spec.resource_id), nominal)]
            output = full_output.get(facility.id, 0.0)
            storage_class = inventory.resource_storage_class.get(spec.output_resource_id)
            if storage_class is not None and output > 1e-12:
                requirements.append(StockOrPoolAdmissionRequirement(storage_class, output))
            rows.append(ExecutionRequirementBundle(
                id=self.execution_bundle_id(facility.id),
                owner_kind="extraction",
                owner_id=facility.id,
                purpose=f"resource:{spec.resource_id}",
                operational_node_id=location_id,
                requested_execution=1.0,
                priority=facility.activity_priority,
                requirements=tuple(requirements),
            ))
        return tuple(rows)

    def resource_snapshots(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        power: PowerSnapshot,
        day: int = 0,
        execution_allocations: ExecutionAllocationPlan | None = None,
    ) -> tuple[ExtractionResourceSnapshot, ...]:
        if execution_allocations is None:
            raise ValueError("extraction planning requires the shared ExecutionAllocationPlan")
        full_output = self._full_output_by_facility(location_id, facilities, day)
        resource_ids = set()
        location = self.graph.locations.get(location_id)
        if location is not None:
            for cell_id in location.developed_cell_ids:
                resource_ids.update(self.graph.surface_cells[cell_id].resource_potential_by_resource)
        for facility in facilities.all_at(location_id):
            spec = self.specs.get(facility.definition_id)
            if spec is not None:
                resource_ids.add(spec.resource_id)
        rows = []
        for resource_id in sorted(resource_ids, key=str):
            active = [
                f for f in facilities.active_compatible_at(location_id, day)
                if (spec := self.specs.get(f.definition_id)) is not None and spec.resource_id == resource_id
            ]
            installed = math.fsum(self.specs[f.definition_id].nominal_capacity_t_per_day * f.level for f in active)
            output = 0.0
            weighted_scale = 0.0
            for facility in active:
                try:
                    scale = execution_allocations.fulfillment(self.execution_bundle_id(facility.id))
                except KeyError:
                    scale = 0.0
                nominal = self.specs[facility.definition_id].nominal_capacity_t_per_day * facility.level
                weighted_scale += nominal * scale
                output += full_output.get(facility.id, 0.0) * scale
            operational = 0.0 if installed <= 1e-12 else weighted_scale / installed
            opportunity = self.effective_opportunity(
                location_id, resource_id, facilities, power, day
            )
            response = self.diminishing_response(installed, opportunity)
            rows.append(ExtractionResourceSnapshot(
                resource_id,
                opportunity,
                installed,
                operational,
                0.0 if installed <= 1e-12 else response / installed,
                self.marginal_response(installed, opportunity) * operational,
                output,
            ))
        return tuple(rows)

    def snapshots(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int = 0,
        execution_allocations: ExecutionAllocationPlan | None = None,
    ) -> tuple[ExtractionSnapshot, ...]:
        del inventory
        if execution_allocations is None:
            raise ValueError("extraction planning requires the shared ExecutionAllocationPlan")
        full_output = self._full_output_by_facility(location_id, facilities, day)
        resource_summary = {
            row.resource_id: row
            for row in self.resource_snapshots(location_id, facilities, power, day, execution_allocations)
        }
        rows = []
        for facility in sorted(facilities.all_at(location_id), key=lambda item: str(item.id)):
            spec = self.specs.get(facility.definition_id)
            if spec is None:
                continue
            nominal = spec.nominal_capacity_t_per_day * facility.level
            reasons = [f"facility:{code}" for code, _ in facilities.activation_failures(facility, day)]
            try:
                allocation = execution_allocations.allocation(self.execution_bundle_id(facility.id))
                scale = allocation.fulfillment
                for key in allocation.limiting_constraints:
                    if key.kind == "service":
                        reasons.append("service_capacity")
                    elif key.kind == "admission":
                        reasons.append(f"storage:{key.name}")
            except KeyError:
                scale = 0.0
            summary = resource_summary.get(spec.resource_id)
            opportunity = self.effective_opportunity(
                location_id, spec.resource_id, facilities, power, day
            )
            if opportunity <= 1e-12 and nominal > 1e-12:
                reasons.append(f"resource_opportunity:{spec.resource_id}")
            rows.append(ExtractionSnapshot(
                facility.id,
                facility.definition_id,
                spec.resource_id,
                spec.output_resource_id,
                nominal,
                opportunity,
                0.0 if summary is None else summary.marginal_efficiency,
                scale,
                full_output.get(facility.id, 0.0) * scale,
                tuple(dict.fromkeys(reasons)),
            ))
        return tuple(rows)

    def advance_day(
        self,
        location_id: SpatialNodeId,
        facilities: FacilityBook,
        inventory: InventoryBook,
        power: PowerSnapshot,
        day: int = 0,
        execution_allocations: ExecutionAllocationPlan | None = None,
    ) -> tuple[DomainActivity, ...]:
        snapshots = self.snapshots(
            location_id, facilities, inventory, power, day, execution_allocations
        )
        for resource_id in sorted({snapshot.output_resource_id for snapshot in snapshots}, key=str):
            output = math.fsum(
                snapshot.output_t_per_day for snapshot in snapshots
                if snapshot.output_resource_id == resource_id
            )
            if output > 1e-12:
                admission = inventory.admit(location_id, resource_id, output)
                if not admission.fully_admitted:
                    raise RuntimeError("allocated extraction output exceeded Inventory Admission")
        return tuple(
            DomainActivity(
                "extraction", snapshot.output_t_per_day, "extraction_facility",
                snapshot.facility_id, location_id
            )
            for snapshot in snapshots if snapshot.output_t_per_day > 1e-12
        )

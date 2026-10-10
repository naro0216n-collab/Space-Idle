from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping
import math

from .execution_requirements import (
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    ServiceCapacityRequirement,
    StockOrPoolAdmissionRequirement,
)
from .facilities import FacilityBook, FacilityDef, FacilityState
from .inventory import InventoryBook
from .knowledge import DomainActivity
from .power import PowerSnapshot
from .service_capacity import ServiceCapacityScope
from .shared import DefinitionId, EntityId, SpatialNodeId
from .site import evaluate_physical_site_requirements
from .spatial import EnvironmentResolver, SpatialGraph
from .surface_infrastructure import SurfaceInfrastructureService
from .exploration_models import ExtractionResourceSnapshot, ExtractionSpec, ExtractionSnapshot
from .survey_service import SurveyService
from .technology import TechnologyState


@dataclass
class ExtractionService:
    SERVICE_TYPE_PREFIX = "extraction:"

    specs: dict[DefinitionId, ExtractionSpec]
    graph: SpatialGraph
    environment: EnvironmentResolver
    surface_infrastructure: SurfaceInfrastructureService
    survey: SurveyService | None = None
    facility_definitions: Mapping[DefinitionId, FacilityDef] = field(default_factory=dict)
    technology_state: TechnologyState | None = None
    _methods_by_facility: dict[DefinitionId, tuple[ExtractionSpec, ...]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.refresh_definition_compatibility()

    def refresh_definition_compatibility(self) -> None:
        """Index physical interfaces; Content variants recompose this index before play.

        Installed capacity is shared by all compatible methods, never added once
        per method. A Facility's selected method determines its Resource stream.
        """
        if any(key != method.id for key, method in self.specs.items()):
            raise ValueError("extraction method definition key mismatch")
        methods: dict[DefinitionId, tuple[ExtractionSpec, ...]] = {}
        for definition_id, definition in self.facility_definitions.items():
            if definition.extraction_capacity_t_per_day <= 0:
                continue
            supplied = frozenset(capability.id for capability in definition.capability_supplies)
            compatible = tuple(sorted((
                method for method in self.specs.values()
                if method.required_capabilities <= supplied
            ), key=lambda method: str(method.id)))
            if not compatible:
                raise ValueError(f"facility {definition_id} has no compatible extraction method")
            methods[definition_id] = compatible
        self._methods_by_facility = methods

    def compatible_methods(self, definition_id: DefinitionId) -> tuple[ExtractionSpec, ...]:
        return self._methods_by_facility.get(definition_id, ())

    def method_for_facility(self, facility: FacilityState) -> ExtractionSpec | None:
        methods = self.compatible_methods(facility.definition_id)
        if facility.selected_extraction_method_id is not None:
            for method in methods:
                if method.id == facility.selected_extraction_method_id:
                    return method
            raise RuntimeError("selected extraction method incompatible with facility")
        return methods[0] if len(methods) == 1 else None

    def missing_method_technologies(self, method: ExtractionSpec) -> tuple[DefinitionId, ...]:
        if self.technology_state is None:
            if method.prerequisite_technologies:
                raise RuntimeError("extraction technology eligibility is not composed")
            return ()
        return self.technology_state.missing(method.prerequisite_technologies)

    def set_method(self, facility: FacilityState, method_id: DefinitionId) -> None:
        candidate = next((method for method in self.compatible_methods(facility.definition_id)
                          if method.id == method_id), None)
        if candidate is None:
            raise ValueError("extraction method incompatible with facility")
        missing = self.missing_method_technologies(candidate)
        if missing:
            raise ValueError("extraction method technology requirements not met: " + ", ".join(map(str, missing)))
        facility.selected_extraction_method_id = method_id

    def method_opportunity(self, location_id: SpatialNodeId, method: ExtractionSpec, day: int) -> float:
        """Actual developed-Cell physics/Knowledge for a single candidate method."""
        location = self.graph.locations.get(location_id)
        if location is None:
            return 0.0
        return math.fsum(
            self.graph.surface_cells[cell_id].resource_potential_by_resource.get(method.resource_id, 0.0)
            * self._cell_accessibility(method, cell_id, day)
            for cell_id in sorted(location.developed_cell_ids, key=str)
            if self._knowledge_cell_eligible(method, cell_id, method.resource_id)
        )

    def method_opportunity_blockers(
        self, location_id: SpatialNodeId, method: ExtractionSpec, day: int,
    ) -> tuple[str, ...]:
        """Explain unavailable physical opportunity without duplicating Site rules in UI."""
        location = self.graph.locations.get(location_id)
        if location is None:
            return (f"site:{location_id}",)
        cells = [
            cell_id for cell_id in sorted(location.developed_cell_ids, key=str)
            if self.graph.surface_cells[cell_id].resource_potential_by_resource.get(
                method.resource_id, 0.0
            ) > 1e-12
        ]
        if not cells:
            return (f"resource_opportunity:{method.resource_id}",)
        eligible = [cell_id for cell_id in cells if self._knowledge_cell_eligible(
            method, cell_id, method.resource_id
        )]
        if not eligible:
            return (f"knowledge:{method.resource_id}",)
        if not any(self._cell_accessibility(method, cell_id, day) > 1e-12
                   for cell_id in eligible):
            return (f"site:{method.id}",)
        return ()

    def nominal_capacity(self, facility: FacilityState) -> float:
        return self.facility_definitions[facility.definition_id].extraction_capacity_t_per_day * facility.level

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

    def _knowledge_cell_eligible(
        self, spec: ExtractionSpec, cell_id, resource_id: DefinitionId
    ) -> bool:
        if spec.minimum_knowledge_level is None:
            return True
        return (
            self.survey is not None
            and self.survey.knowledge_level(cell_id, resource_id) >= spec.minimum_knowledge_level
        )

    def knowledge_eligibility_counts(
        self, location_id: SpatialNodeId, resource_id: DefinitionId, facilities: FacilityBook
    ) -> tuple[int, int]:
        location = self.graph.locations.get(location_id)
        if location is None:
            return (0, 0)
        specs = [
            self.method_for_facility(facility)
            for facility in facilities.all_at(location_id)
            if self.method_for_facility(facility) is not None
            and self.method_for_facility(facility).resource_id == resource_id
        ]
        eligible = blocked = 0
        for cell_id in location.developed_cell_ids:
            if self.graph.surface_cells[cell_id].resource_potential_by_resource.get(resource_id, 0.0) <= 1e-12:
                continue
            if specs and any(self._knowledge_cell_eligible(spec, cell_id, resource_id) for spec in specs):
                eligible += 1
            elif specs:
                blocked += 1
        return eligible, blocked

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
        active_specs = (
            self.method_for_facility(facility)
            for facility in facilities.active_compatible_at(location_id, day)
        )
        active_specs = tuple(spec for spec in active_specs if spec is not None
                             and spec.resource_id == resource_id
                             and not self.missing_method_technologies(spec))
        if not active_specs:
            return 0.0
        total = 0.0
        for cell_id in sorted(location.developed_cell_ids, key=str):
            cell = self.graph.surface_cells[cell_id]
            potential = cell.resource_potential_by_resource.get(resource_id, 0.0)
            if potential <= 1e-12:
                continue
            eligible_specs = [
                spec for spec in active_specs
                if self._knowledge_cell_eligible(spec, cell_id, resource_id)
            ]
            if not eligible_specs:
                continue
            accessibility = max(
                (self._cell_accessibility(spec, cell_id, day) for spec in eligible_specs),
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
            spec = self.method_for_facility(facility)
            if spec is None:
                continue
            spec_by[facility.id] = spec
            nominal = self.nominal_capacity(facility)
            nominal_by[facility.id] = nominal
            failures = facilities.activation_failures(facility, day)
            failures = list(failures) + [
                (f"technology:{tech}", "research prerequisite is incomplete")
                for tech in self.missing_method_technologies(spec)
            ]
            if failures:
                fulfillment_by[facility.id] = 0.0
                reasons[facility.id] = [
                    code if code.startswith("technology:") else f"facility:{code}"
                    for code, _ in failures
                ]
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

    def service_capacity_types(self) -> tuple[str, ...]:
        return tuple(sorted({
            self.service_type(spec.resource_id) for spec in self.specs.values()
        }))

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
            definition_id
            for definition_id, specs in self._methods_by_facility.items()
            if any(self.service_type(spec.resource_id) == service_type for spec in specs)
        )

    def service_capacity_upstream_services(
        self, service_type: str
    ) -> frozenset[str]:
        if service_type not in self.service_capacity_types():
            raise KeyError(service_type)
        return frozenset({self.surface_infrastructure.service_type})

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
            compatible = [
                (facility, spec)
                for facility in facilities.active_compatible_at(location_id, day)
                for spec in (self.method_for_facility(facility),)
                if spec is not None and self.service_type(spec.resource_id) == service_type
            ]
            nominal = math.fsum(self.nominal_capacity(facility)
                                for facility, _method in compatible)
            available = math.fsum(self.nominal_capacity(facility)
                                  for facility, method in compatible
                                  if not self.missing_method_technologies(method))
            return nominal, available
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

    def _opportunity_adjusted_installed_capacity(
        self, location_id: SpatialNodeId, facilities: list[FacilityState],
        opportunity: float, day: int,
    ) -> dict[EntityId, float]:
        """Each selected method accesses only the developed cells it can exploit.

        Common Resource Opportunity is never multiplied by the number of
        compatible extraction methods, or by the number of active Facilities.
        """
        return {
            facility.id: (
                self.nominal_capacity(facility) * min(
                    1.0, self.method_opportunity(
                        location_id, self.method_for_facility(facility), day,
                    ) / opportunity,
                ) if opportunity > 1e-12 else 0.0
            )
            for facility in facilities
        }

    def _full_output_by_facility(
        self, location_id: SpatialNodeId, facilities: FacilityBook, day: int
    ) -> dict[EntityId, float]:
        active = [
            facility
            for facility in facilities.active_compatible_at(location_id, day)
            if self.method_for_facility(facility) is not None
            and not self.missing_method_technologies(self.method_for_facility(facility))
        ]
        result: dict[EntityId, float] = {}
        resources = sorted({self.method_for_facility(f).resource_id for f in active}, key=str)
        for resource_id in resources:
            rows = [f for f in active if self.method_for_facility(f).resource_id == resource_id]
            opportunity = self.effective_opportunity(location_id, resource_id, facilities, day=day)
            effective_capacity = self._opportunity_adjusted_installed_capacity(
                location_id, rows, opportunity, day,
            )
            installed = math.fsum(effective_capacity.values())
            response = self.diminishing_response(installed, opportunity)
            for facility in rows:
                result[facility.id] = (
                    0.0 if installed <= 1e-12 else
                    response * effective_capacity[facility.id] / installed
                )
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
            spec = self.method_for_facility(facility)
            if spec is None or self.missing_method_technologies(spec):
                continue
            nominal = self.nominal_capacity(facility)
            if nominal <= 1e-12:
                continue
            requirements = [ServiceCapacityRequirement(self.service_type(spec.resource_id), nominal)]
            output = full_output.get(facility.id, 0.0)
            pool_key = inventory.storage_pool_for_resource(spec.output_resource_id)
            if output > 1e-12:
                requirements.append(StockOrPoolAdmissionRequirement(pool_key, output))
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
            spec = self.method_for_facility(facility)
            if spec is not None:
                resource_ids.add(spec.resource_id)
        rows = []
        for resource_id in sorted(resource_ids, key=str):
            active = [
                f for f in facilities.active_compatible_at(location_id, day)
                if (spec := self.method_for_facility(f)) is not None and spec.resource_id == resource_id
            ]
            installed = math.fsum(self.nominal_capacity(f) for f in active)
            output = 0.0
            weighted_scale = 0.0
            for facility in active:
                try:
                    scale = execution_allocations.fulfillment(self.execution_bundle_id(facility.id))
                except KeyError:
                    scale = 0.0
                nominal = self.nominal_capacity(facility)
                weighted_scale += nominal * scale
                output += full_output.get(facility.id, 0.0) * scale
            operational = 0.0 if installed <= 1e-12 else weighted_scale / installed
            opportunity = self.effective_opportunity(
                location_id, resource_id, facilities, power, day
            )
            # A method's inaccessible cells reduce its effective throughput,
            # not the installed physical Capacity shown in the UI. Indicators
            # use the same opportunity-adjusted installation as settlement.
            usable = [f for f in active if not self.missing_method_technologies(
                self.method_for_facility(f)
            )]
            effective_installed = math.fsum(
                self._opportunity_adjusted_installed_capacity(
                    location_id, usable, opportunity, day,
                ).values()
            )
            response = self.diminishing_response(effective_installed, opportunity)
            eligible_cells, blocked_cells = self.knowledge_eligibility_counts(
                location_id, resource_id, facilities
            )
            rows.append(ExtractionResourceSnapshot(
                resource_id,
                self.static_opportunity(location_id, resource_id),
                opportunity,
                eligible_cells,
                blocked_cells,
                installed,
                operational,
                0.0 if installed <= 1e-12 else response / installed,
                self.marginal_response(effective_installed, opportunity) * operational,
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
            spec = self.method_for_facility(facility)
            if spec is None:
                continue
            nominal = self.nominal_capacity(facility)
            reasons = [f"facility:{code}" for code, _ in facilities.activation_failures(facility, day)]
            reasons.extend(f"technology:{tech}" for tech in self.missing_method_technologies(spec))
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
            # The Facility view describes its own selected method, not a
            # different method's accessible cells at the same Location.
            opportunity = self.method_opportunity(location_id, spec, day)
            if opportunity <= 1e-12 and nominal > 1e-12:
                reasons.extend(self.method_opportunity_blockers(location_id, spec, day))
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
                spec.id,
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
        # Each settled extraction quantity originates from the actual installed
        # Facility and its canonical allocated execution, not a Graph estimate.
        for snapshot in snapshots:
            if snapshot.output_t_per_day > 1e-12:
                admission = inventory.admit(
                    location_id, snapshot.output_resource_id, snapshot.output_t_per_day,
                    source_owner=f"extraction_facility:{snapshot.facility_id}",
                    activity_id=f"extraction:{snapshot.facility_id}:{snapshot.resource_id}:{snapshot.method_id}",
                )
                if not admission.fully_admitted:
                    raise RuntimeError("allocated extraction output exceeded Inventory Admission")
        return tuple(
            DomainActivity(
                "extraction", snapshot.output_t_per_day, "extraction_facility",
                snapshot.facility_id, location_id
            )
            for snapshot in snapshots if snapshot.output_t_per_day > 1e-12
        )

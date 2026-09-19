from __future__ import annotations

from dataclasses import fields, is_dataclass

from .application_constraints import constraints_from_codes, constraints_from_pairs, limiting_factors_from_codes
from .application_views import (
    CapabilityRow,
    ServiceCapacityRow,
    EnvironmentFacetRow,
    LocationEnvironmentSummaryRow,
    ExtractionRow,
    ExtractionResourceRow,
    FacilityRow,
    IndustryRow,
    InventoryRow,
    ResourceAllocationRow,
    OperationalNodeView,
    SurfaceInfrastructureLoadRow,
    SurfaceInfrastructureRow,
    SurfaceAccessAnchorRow,
    SurfaceLocationDecisionRow,
    StorageRow,
)
from .shared import SpatialNodeId
from .disposal import project_salvage_recovery
from .construction.models import FacilityDecommissionTarget, ProjectStatus
from .spatial import EnvironmentFieldScope, SpatialContextId


class LocationProjectorMixin:
    def _environment_values(self, facet) -> tuple[tuple[str, object], ...]:
        if is_dataclass(facet):
            return tuple(
                (field.name, self._transport_value(getattr(facet, field.name)))
                for field in fields(facet)
            )
        return tuple(
            (key, self._transport_value(value))
            for key, value in sorted(vars(facet).items())
            if not key.startswith("_")
        )

    def _inventory_rows(self, location_id: SpatialNodeId) -> tuple[InventoryRow, ...]:
        sim = self._simulation
        resource_ids = set(self._catalog.resources)
        resource_ids.update(res for (loc, res) in sim.inventory.stock if loc == location_id)
        rows = []
        for resource_id in sorted(resource_ids, key=str):
            amount = sim.inventory.amount(location_id, resource_id)
            reserved = sim.inventory.reserved_total(location_id, resource_id)
            admission = sim.inventory.admission_state(location_id, resource_id)
            storage_pool_key = admission.storage_pool_key
            physical_capacity = admission.physical_capacity_t
            usable_capacity = admission.usable_capacity_t
            free = admission.admission_capacity_t
            if amount <= 1e-12 and reserved <= 1e-12 and physical_capacity in (None, 0.0):
                continue
            definition = self._catalog.resources.get(resource_id)
            rows.append(
                InventoryRow(
                    str(resource_id),
                    self._resource_name(resource_id),
                    "t" if definition is None else definition.unit,
                    amount,
                    reserved,
                    sim.inventory.available(location_id, resource_id),
                    storage_pool_key,
                    physical_capacity,
                    usable_capacity,
                    free,
                    admission.admission_capacity_t,
                    admission.over_capacity_t,
                    constraints_from_codes(
                        admission.blockers,
                        affected_action="admit_storage",
                        related_entity_kind="storage_pool",
                        related_entity_id=storage_pool_key,
                    ),
                    limiting_factors_from_codes(
                        admission.limiting_factors,
                        affected_action="admit_storage",
                        related_entity_kind="storage_pool",
                        related_entity_id=storage_pool_key,
                    ),
                )
            )
        return tuple(rows)

    def _storage_rows(self, location_id: SpatialNodeId) -> tuple[StorageRow, ...]:
        sim = self._simulation
        rows = []
        keys = {
            key for key in sim.inventory.physical_storage_capacity_t if key[0] == location_id
        } | {
            key for key in sim.inventory.usable_storage_capacity_t if key[0] == location_id
        }
        for loc, storage_pool_key in sorted(keys, key=lambda row: (str(row[0]), row[1])):
            physical = sim.inventory.physical_storage_capacity_t.get((loc, storage_pool_key), 0.0)
            usable = sim.inventory.usable_storage_capacity_t.get((loc, storage_pool_key), 0.0)
            stock = sum(
                amount
                for (stock_loc, resource_id), amount in sim.inventory.stock.items()
                if stock_loc == location_id
                and sim.inventory.storage_pool_for_resource(resource_id) == storage_pool_key
            )
            staging = sum(
                amount
                for (_owner, occ_loc, resource_id), amount in sim.inventory.external_occupancy.items()
                if occ_loc == location_id
                and sim.inventory.storage_pool_for_resource(resource_id) == storage_pool_key
            )
            admission = sim.inventory.admission_state_for_pool(location_id, storage_pool_key)
            rows.append(
                StorageRow(
                    storage_pool_key,
                    stock,
                    staging,
                    physical,
                    usable,
                    0.0 if admission.admission_capacity_t is None else admission.admission_capacity_t,
                    admission.over_capacity_t,
                    constraints_from_codes(
                        admission.blockers,
                        affected_action="admit_storage",
                        related_entity_kind="storage_pool",
                        related_entity_id=storage_pool_key,
                    ),
                    limiting_factors_from_codes(
                        admission.limiting_factors,
                        affected_action="admit_storage",
                        related_entity_kind="storage_pool",
                        related_entity_id=storage_pool_key,
                    ),
                )
            )
        return tuple(rows)

    def _environment_rows(self, location_id: SpatialContextId) -> tuple[EnvironmentFacetRow, ...]:
        sim = self._simulation
        facet_types = sim.environment.static.facet_types()
        rows: list[EnvironmentFacetRow] = []
        for facet_type in sorted(
            facet_types, key=lambda value: getattr(value, "facet_key", value.__name__)
        ):
            facet = sim.environment.get(location_id, facet_type, sim.day)
            if facet is None:
                continue
            rows.append(
                EnvironmentFacetRow(
                    getattr(facet_type, "facet_key", facet_type.__name__),
                    self._environment_values(facet),
                )
            )
        return tuple(rows)

    def _surface_location_decision_row(
        self, location_id: SpatialNodeId
    ) -> SurfaceLocationDecisionRow | None:
        sim = self._simulation
        location = sim.graph.locations.get(location_id)
        if location is None:
            return None

        facet_types = sim.environment.static.facet_types()
        environment_summary: list[LocationEnvironmentSummaryRow] = []
        for facet_type in sorted(
            facet_types, key=lambda value: getattr(value, "facet_key", value.__name__)
        ):
            scope = getattr(facet_type, "environment_scope", None)
            if not isinstance(scope, EnvironmentFieldScope):
                continue
            location_facet = sim.environment.get(location_id, facet_type, sim.day)
            location_values = (
                () if location_facet is None else self._environment_values(location_facet)
            )
            cell_values: list[tuple[str, tuple[tuple[str, object], ...]]] = []
            if scope is not EnvironmentFieldScope.BODY_GLOBAL:
                for cell_id in sorted(location.developed_cell_ids, key=str):
                    facet = sim.environment.get(cell_id, facet_type, sim.day)
                    if facet is not None:
                        cell_values.append((str(cell_id), self._environment_values(facet)))
            if not location_values and not cell_values:
                continue
            environment_summary.append(
                LocationEnvironmentSummaryRow(
                    getattr(facet_type, "facet_key", facet_type.__name__),
                    scope.value,
                    location_values,
                    tuple(cell_values),
                )
            )

        anchors: tuple[SurfaceAccessAnchorRow, ...] = ()
        if sim.surface_infrastructure is not None:
            anchors = tuple(
                SurfaceAccessAnchorRow(
                    str(anchor.facility_id),
                    str(anchor.facility_definition_id),
                    str(anchor.cell_id),
                )
                for anchor in sim.surface_infrastructure.active_access_anchors(
                    location_id, sim.day
                )
            )
        return SurfaceLocationDecisionRow(
            str(location.core_cell_id),
            tuple(str(cell_id) for cell_id in sorted(location.developed_cell_ids, key=str)),
            anchors,
            tuple(environment_summary),
        )

    def _operational_node_view(self, location_id: SpatialNodeId) -> OperationalNodeView:
        sim = self._simulation
        node = sim.graph.operational_node(location_id)
        decision = self._tick_decision_projection()
        power = decision.allocations.power_by_location[location_id]
        research_power = decision.allocations.power_by_location
        service_allocations = decision.allocations.services
        resource_allocations = decision.allocations.resources
        execution_allocations = decision.allocations.execution

        facilities = []
        for facility in sorted(
            (row for row in sim.facilities.facilities.values() if row.operational_node_id == location_id),
            key=lambda row: str(row.id),
        ):
            definition = sim.facilities.definitions[facility.definition_id]
            activation_failures = sim.facilities.activation_failures(facility, sim.day)
            active_and_compatible = not activation_failures
            research_provider = (
                None
                if sim.research is None
                else sim.research.facility_provider_spec(facility.id)
            )
            if research_provider is None:
                research_tier = None
                research_generation = 0.0
                research_storage = 0.0
            else:
                research_tier = research_provider.tier
                research_generation = sim.research.provider_generation(
                    facility.id, research_power, sim.day
                )
                research_storage = sim.research.provider_storage_capacity(
                    facility.id, research_power, sim.day
                )
            power_utilization = power.utilization_by_facility.get(
                facility.id, 0.0 if not active_and_compatible else 1.0
            )
            maintenance_requirements = sim.facilities.maintenance_requirements_per_day(facility.id)
            operating_blockers = list(activation_failures)
            if active_and_compatible and power_utilization < 1.0 - 1e-9:
                operating_blockers.append(("power", "電力配分不足"))
            maintenance_satisfaction = power.maintenance_factor_by_facility.get(
                facility.id, 1.0
            )
            if maintenance_satisfaction < 1.0 - 1e-9:
                operating_blockers.append(("maintenance", "維持資源充足率不足"))
            operational_utilization = (
                power_utilization * maintenance_satisfaction
                if active_and_compatible else 0.0
            )
            recovery_potential = sim.facilities.decommission_salvage(facility.id)
            post_removal_headroom = sim.storage.post_decommission_admission_headroom(
                facility.id, sim.day, power
            )
            recovery_projection = project_salvage_recovery(
                sim.inventory,
                facility.operational_node_id,
                recovery_potential,
                admission_headroom_by_pool=post_removal_headroom,
            )
            decommission_failures = sim.projects.decommission_plan_failures(facility.id)
            active_decommission = next((
                project
                for project in sim.projects.projects.values()
                if isinstance(project.target, FacilityDecommissionTarget)
                and project.target.facility_id == facility.id
                and project.status not in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}
            ), None)
            facilities.append(
                FacilityRow(
                    str(facility.id),
                    str(facility.definition_id),
                    definition.display_name,
                    facility.level,
                    facility.paused,
                    active_and_compatible,
                    constraints_from_pairs(
                        activation_failures,
                        affected_action="operate_facility",
                        related_entity_kind="facility",
                        related_entity_id=str(facility.id),
                    ),
                    facility.activity_priority,
                    facility.maintenance_priority,
                    tuple(sorted(supply.id for supply in definition.capability_supplies)),
                    power_utilization,
                    research_tier,
                    research_generation,
                    research_storage,
                    self._facility_upgrade_option(facility, power),
                    tuple(
                        (str(resource_id), amount)
                        for resource_id, amount in sorted(facility.invested_resources.items(), key=lambda row: str(row[0]))
                    ),
                    tuple(
                        (str(resource_id), amount)
                        for resource_id, amount in sorted(maintenance_requirements.items(), key=lambda row: str(row[0]))
                    ),
                    maintenance_satisfaction,
                    operational_utilization,
                    constraints_from_pairs(
                        operating_blockers,
                        affected_action="operate_facility",
                        related_entity_kind="facility",
                        related_entity_id=str(facility.id),
                    ),
                    definition.placement_scope.value,
                    None if facility.site_cell_id is None else str(facility.site_cell_id),
                    tuple(
                        sorted(
                            (supply.service_type, supply.nominal_rate)
                            for supply in definition.service_capacity_supplies
                        )
                    ),
                    facility.lifecycle.value,
                    constraints_from_pairs(
                        tuple((blocker.code, blocker.detail) for blocker in decommission_failures),
                        affected_action="plan_facility_decommission",
                        related_entity_kind="facility",
                        related_entity_id=str(facility.id),
                    ),
                    tuple(
                        (str(resource_id), amount)
                        for resource_id, amount in sorted(
                            recovery_potential.items(), key=lambda row: str(row[0])
                        )
                    ),
                    recovery_projection.recoverable_fraction,
                    tuple(
                        (str(resource_id), amount)
                        for resource_id, amount in recovery_projection.recovered_by_resource
                    ),
                    not decommission_failures,
                    None if active_decommission is None else str(active_decommission.id),
                )
            )

        industry = []
        resource_allocation_rows = []
        for allocation in resource_allocations.rows:
            if allocation.operational_node_id != location_id:
                continue
            definition = self._catalog.resources.get(allocation.resource_id)
            resource_allocation_rows.append(
                ResourceAllocationRow(
                    str(allocation.id),
                    str(allocation.resource_id),
                    self._resource_name(allocation.resource_id),
                    "t" if definition is None else definition.unit,
                    allocation.owner_kind,
                    str(allocation.owner_id),
                    allocation.purpose,
                    allocation.priority,
                    allocation.requested_amount,
                    allocation.allocated_amount,
                    allocation.unmet_amount,
                    allocation.effective_minimum_amount,
                    allocation.atomic,
                    None if allocation.requirement_id is None else str(allocation.requirement_id),
                )
            )
        snapshots = {
            snap.facility_id: snap
            for snap in sim.industry.snapshots(
                location_id, sim.facilities, sim.inventory, sim.day,
                execution_allocations,
            )
        }
        for facility in sorted(sim.facilities.all_at(location_id), key=lambda row: str(row.id)):
            compatible = tuple(
                sorted(
                    sim.industry.compatible_processes(facility.definition_id),
                    key=lambda process: str(process.id),
                )
            )
            if not compatible:
                continue
            definition = sim.facilities.definitions[facility.definition_id]
            options = tuple((str(process.id), process.display_name) for process in compatible)
            snap = snapshots.get(facility.id)
            process = sim.industry.process_for(facility)
            selection_required = len(compatible) > 1 and facility.selected_process_id is None
            if snap is not None:
                limiting = snap.limiting_factors
                scale = snap.scale
                inputs = tuple(
                    (str(key), value)
                    for key, value in sorted(
                        snap.input_rates_per_day.items(), key=lambda row: str(row[0])
                    )
                )
                outputs = tuple(
                    (str(key), value)
                    for key, value in sorted(
                        snap.output_rates_per_day.items(), key=lambda row: str(row[0])
                    )
                )
            else:
                failures = sim.facilities.activation_failures(facility, sim.day)
                limiting = (
                    tuple(f"facility:{code}" for code, _detail in failures)
                    if failures
                    else ("process:unselected",)
                )
                scale = 0.0
                inputs = ()
                outputs = ()
            industry.append(
                IndustryRow(
                    str(facility.id),
                    str(facility.definition_id),
                    definition.display_name,
                    None if process is None else str(process.id),
                    None if process is None else process.display_name,
                    options,
                    selection_required,
                    scale,
                    limiting_factors_from_codes(
                        limiting,
                        affected_action="run_process",
                        related_entity_kind="facility",
                        related_entity_id=str(facility.id),
                    ),
                    inputs,
                    outputs,
                )
            )

        extraction: list[ExtractionRow] = []
        extraction_resources: list[ExtractionResourceRow] = []
        if sim.extraction is not None:
            for snap in sim.extraction.snapshots(
                location_id, sim.facilities, sim.inventory, power, sim.day,
                execution_allocations,
            ):
                definition = sim.facilities.definitions[snap.facility_def_id]
                extraction.append(
                    ExtractionRow(
                        str(snap.facility_id),
                        str(snap.facility_def_id),
                        definition.display_name,
                        str(snap.resource_id),
                        self._resource_name(snap.resource_id),
                        str(snap.output_resource_id),
                        self._resource_name(snap.output_resource_id),
                        snap.nominal_capacity_t_per_day,
                        snap.effective_opportunity,
                        snap.marginal_efficiency,
                        snap.scale,
                        snap.output_t_per_day,
                        limiting_factors_from_codes(
                            snap.limiting_factors,
                            affected_action="run_extraction",
                            related_entity_kind="facility",
                            related_entity_id=str(snap.facility_id),
                        ),
                    )
                )
            extraction_resources.extend(
                ExtractionResourceRow(
                    str(row.resource_id),
                    self._resource_name(row.resource_id),
                    row.effective_opportunity,
                    row.installed_nominal_capacity_t_per_day,
                    row.operational_fulfillment,
                    row.diminishing_efficiency,
                    row.marginal_efficiency,
                    row.output_t_per_day,
                )
                for row in sim.extraction.resource_snapshots(
                    location_id, sim.facilities, power, sim.day, execution_allocations
                )
            )

        capability_rows = tuple(
            CapabilityRow(
                capability_id,
                sim.facilities.installed_capability_at(location_id, capability_id),
                sim.facilities.active_capability_at(location_id, capability_id, sim.day),
            )
            for capability_id in sorted(sim.facilities.capability_ids())
            if sim.facilities.installed_capability_at(location_id, capability_id)
        )

        service_types = {
            service_type
            for (node_id, service_type) in service_allocations.supply_nominal
            if node_id == location_id
        } | {
            request.service_type
            for request in service_allocations.requests
            if request.operational_node_id == location_id
        }
        service_capacity_rows = tuple(
            ServiceCapacityRow(
                summary.service_type,
                summary.nominal_rate,
                summary.enabled_rate,
                summary.requested_rate,
                summary.allocated_rate,
                summary.spare_rate,
                limiting_factors_from_codes(
                    summary.limiting_factors,
                    affected_action="allocate_service_capacity",
                    related_entity_kind="service",
                    related_entity_id=summary.service_type,
                ),
            )
            for summary in (
                service_allocations.summary(location_id, service_type)
                for service_type in sorted(service_types)
            )
            if summary.nominal_rate > 1e-9 or summary.requested_rate > 1e-9
        )

        surface_infrastructure = None
        if sim.surface_infrastructure is not None and location_id in sim.graph.locations:
            snapshot = sim.surface_infrastructure.snapshot(
                location_id,
                sim.facilities,
                power,
                sim.day,
                allocation_plan=service_allocations,
            )
            improvement_ids = tuple(
                sorted(
                    str(definition.id)
                    for definition in sim.facilities.definitions.values()
                    if definition.id in sim.projects.recipes
                    and any(
                        supply.service_type == sim.surface_infrastructure.service_type
                        for supply in definition.service_capacity_supplies
                    )
                )
            )
            surface_infrastructure = SurfaceInfrastructureRow(
                snapshot.nominal_capacity,
                snapshot.available_capacity,
                snapshot.demand,
                snapshot.allocated_capacity,
                snapshot.spare_capacity,
                snapshot.fulfillment,
                tuple(
                    SurfaceInfrastructureLoadRow(load.code, load.demand)
                    for load in snapshot.load_sources
                ),
                limiting_factors_from_codes(
                    snapshot.limiting_factors,
                    affected_action="serve_surface_infrastructure",
                    related_entity_kind="operational_node",
                    related_entity_id=str(location_id),
                ),
                improvement_ids,
            )

        return OperationalNodeView(
            str(location_id),
            node.display_name,
            sim.day,
            self._environment_rows(location_id),
            power.generation_mw,
            power.demand_mw,
            power.allocated_mw,
            sim.projects.construction_capacity_at(location_id, power, sim.day),
            capability_rows,
            service_capacity_rows,
            surface_infrastructure,
            self._inventory_rows(location_id),
            tuple(resource_allocation_rows),
            self._storage_rows(location_id),
            tuple(facilities),
            tuple(industry),
            tuple(extraction),
            tuple(extraction_resources),
            self._project_rows(location_id),
            self._surface_location_decision_row(location_id),
        )

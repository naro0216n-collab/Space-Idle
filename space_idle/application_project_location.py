from __future__ import annotations

from dataclasses import fields, is_dataclass

from .application_views import (
    CapabilityRow,
    ServiceCapacityRow,
    EnvironmentFacetRow,
    ExtractionRow,
    ExtractionResourceRow,
    FacilityRow,
    IndustryRow,
    InventoryRow,
    ResourceClaimRow,
    OperationalNodeView,
    SurfaceInfrastructureLoadRow,
    SurfaceInfrastructureRow,
    StorageRow,
)
from .shared import SpatialNodeId
from .spatial import SpatialContextId


class LocationProjectorMixin:
    def _inventory_rows(self, location_id: SpatialNodeId) -> tuple[InventoryRow, ...]:
        sim = self._simulation
        resource_ids = set(self._catalog.resources)
        resource_ids.update(res for (loc, res) in sim.inventory.stock if loc == location_id)
        rows = []
        for resource_id in sorted(resource_ids, key=str):
            amount = sim.inventory.amount(location_id, resource_id)
            reserved = sim.inventory.reserved_total(location_id, resource_id)
            storage_class = sim.inventory.resource_storage_class.get(resource_id)
            physical_capacity = sim.inventory.physical_capacity(location_id, resource_id)
            usable_capacity = sim.inventory.usable_capacity(location_id, resource_id)
            free = sim.inventory.free_capacity(location_id, resource_id)
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
                    storage_class,
                    physical_capacity,
                    usable_capacity,
                    free,
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
        for loc, storage_class in sorted(keys, key=lambda row: (str(row[0]), row[1])):
            physical = sim.inventory.physical_storage_capacity_t.get((loc, storage_class), 0.0)
            usable = sim.inventory.usable_storage_capacity_t.get((loc, storage_class), 0.0)
            stock = sum(
                amount
                for (stock_loc, resource_id), amount in sim.inventory.stock.items()
                if stock_loc == location_id
                and sim.inventory.resource_storage_class.get(resource_id) == storage_class
            )
            staging = sum(
                amount
                for (_owner, occ_loc, resource_id), amount in sim.inventory.external_occupancy.items()
                if occ_loc == location_id
                and sim.inventory.resource_storage_class.get(resource_id) == storage_class
            )
            occupied = stock + staging
            rows.append(
                StorageRow(
                    storage_class,
                    stock,
                    staging,
                    physical,
                    usable,
                    max(0.0, usable - occupied),
                    max(0.0, occupied - usable),
                )
            )
        return tuple(rows)

    def _environment_rows(self, location_id: SpatialContextId) -> tuple[EnvironmentFacetRow, ...]:
        sim = self._simulation
        facet_types = {facet_type for (_node_id, facet_type) in sim.environment.static.facets}
        rows: list[EnvironmentFacetRow] = []
        for facet_type in sorted(
            facet_types, key=lambda value: getattr(value, "facet_key", value.__name__)
        ):
            facet = sim.environment.get(location_id, facet_type, sim.day)
            if facet is None:
                continue
            if is_dataclass(facet):
                values = tuple(
                    (field.name, self._transport_value(getattr(facet, field.name)))
                    for field in fields(facet)
                )
            else:
                values = tuple(
                    (key, self._transport_value(value))
                    for key, value in sorted(vars(facet).items())
                    if not key.startswith("_")
                )
            rows.append(
                EnvironmentFacetRow(
                    getattr(facet_type, "facet_key", facet_type.__name__), values
                )
            )
        return tuple(rows)

    def _operational_node_view(self, location_id: SpatialNodeId) -> OperationalNodeView:
        sim = self._simulation
        node = sim.graph.operational_node(location_id)
        power = sim.power.snapshot(location_id, sim.facilities, sim.day)
        research_power = {location_id: power}
        service_allocations = sim.service_capacity_allocation_projection(
            {location_id: power}
        )

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
                else sim.research.providers.get(facility.definition_id)
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
            if facility.maintenance_satisfaction < 1.0 - 1e-9:
                operating_blockers.append(("maintenance", "維持資源充足率不足"))
            operational_utilization = (
                power_utilization * facility.maintenance_satisfaction
                if active_and_compatible else 0.0
            )
            facilities.append(
                FacilityRow(
                    str(facility.id),
                    str(facility.definition_id),
                    definition.display_name,
                    facility.level,
                    facility.paused,
                    active_and_compatible,
                    tuple(activation_failures),
                    facility.power_priority,
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
                    facility.maintenance_satisfaction,
                    operational_utilization,
                    tuple(operating_blockers),
                    definition.placement_scope.value,
                    None if facility.site_cell_id is None else str(facility.site_cell_id),
                    tuple(
                        sorted(
                            (supply.service_type, supply.nominal_rate)
                            for supply in definition.service_capacity_supplies
                        )
                    ),
                )
            )

        industry = []
        resource_allocations = sim.resource_allocation_projection({location_id: power})
        resource_claim_rows = []
        for claim in resource_allocations.claims:
            if claim.operational_node_id != location_id:
                continue
            allocation = resource_allocations.allocation(claim.id)
            definition = self._catalog.resources.get(claim.resource_id)
            resource_claim_rows.append(
                ResourceClaimRow(
                    str(claim.id),
                    str(claim.resource_id),
                    self._resource_name(claim.resource_id),
                    "t" if definition is None else definition.unit,
                    claim.owner_kind,
                    str(claim.owner_id),
                    claim.purpose,
                    claim.priority,
                    allocation.requested_amount,
                    allocation.allocated_amount,
                    allocation.unmet_amount,
                    claim.effective_minimum_amount,
                    claim.atomic,
                    None if claim.demand_id is None else str(claim.demand_id),
                )
            )
        snapshots = {
            snap.facility_id: snap
            for snap in sim.industry.snapshots(
                location_id, sim.facilities, sim.inventory, power, sim.day,
                resource_allocations, service_allocations,
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
            process = None if snap is None else sim.industry.processes[snap.process_id]
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
                    scale,
                    limiting,
                    inputs,
                    outputs,
                )
            )

        extraction: list[ExtractionRow] = []
        extraction_resources: list[ExtractionResourceRow] = []
        if sim.extraction is not None:
            for snap in sim.extraction.snapshots(
                location_id, sim.facilities, sim.inventory, power, sim.day,
                service_allocations,
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
                        snap.limiting_factors,
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
                    location_id, sim.facilities, power, sim.day, service_allocations
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
                summary.limiting_factors,
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
                snapshot.limiting_factors,
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
            tuple(resource_claim_rows),
            self._storage_rows(location_id),
            tuple(facilities),
            tuple(industry),
            tuple(extraction),
            tuple(extraction_resources),
            self._project_rows(location_id),
        )

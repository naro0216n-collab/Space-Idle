from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Mapping

from .application_views import CapabilityRow, EnvironmentFacetRow, ExtractionRow, FacilityRow, IndustryRow, InventoryRow, LocationView, StorageRow
from .contracts import CapabilityContractTemplate, CargoContractTemplate
from .shared import ContractId, DefinitionId, EntityId, ProjectId, RouteId, SpatialNodeId
from .site import evaluate_site_requirements


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
            service_capacity = sim.inventory.service_capacity(location_id, resource_id)
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
                    service_capacity,
                    free,
                )
            )
        return tuple(rows)

    def _storage_rows(self, location_id: SpatialNodeId) -> tuple[StorageRow, ...]:
        sim = self._simulation
        rows = []
        keys = {
            key for key in sim.inventory.storage_capacity_t if key[0] == location_id
        } | {
            key for key in sim.inventory.storage_service_capacity_t if key[0] == location_id
        }
        for loc, storage_class in sorted(keys, key=lambda x: (str(x[0]), x[1])):
            physical = sim.inventory.storage_capacity_t.get((loc, storage_class), 0.0)
            service = sim.inventory.storage_service_capacity_t.get((loc, storage_class), 0.0)
            stock = sum(
                amount for (stock_loc, resource_id), amount in sim.inventory.stock.items()
                if stock_loc == location_id and sim.inventory.resource_storage_class.get(resource_id) == storage_class
            )
            staging = sum(
                amount for (_owner, occ_loc, resource_id), amount in sim.inventory.external_occupancy.items()
                if occ_loc == location_id and sim.inventory.resource_storage_class.get(resource_id) == storage_class
            )
            occupied = stock + staging
            rows.append(StorageRow(
                storage_class, stock, staging, physical, service,
                max(0.0, service - occupied), max(0.0, occupied - service),
            ))
        return tuple(rows)

    def _environment_rows(self, location_id: SpatialNodeId) -> tuple[EnvironmentFacetRow, ...]:
        sim = self._simulation
        facet_types = {facet_type for (_node_id, facet_type) in sim.environment.static.facets}
        rows: list[EnvironmentFacetRow] = []
        for facet_type in sorted(facet_types, key=lambda t: getattr(t, "facet_key", t.__name__)):
            facet = sim.environment.get(location_id, facet_type, sim.day)
            if facet is None:
                continue
            if is_dataclass(facet):
                values = tuple((f.name, self._transport_value(getattr(facet, f.name))) for f in fields(facet))
            else:
                values = tuple(
                    (k, self._transport_value(v))
                    for k, v in sorted(vars(facet).items())
                    if not k.startswith("_")
                )
            rows.append(EnvironmentFacetRow(getattr(facet_type, "facet_key", facet_type.__name__), values))
        return tuple(rows)

    def _location_view(self, location_id: SpatialNodeId) -> LocationView:
        sim = self._simulation
        node = sim.graph.nodes[location_id]
        power = sim.power.snapshot(location_id, sim.facilities, sim.day)
        facilities = []
        for f in sorted((x for x in sim.facilities.facilities.values() if x.location_id == location_id), key=lambda x: str(x.id)):
            definition = sim.facilities.definitions[f.definition_id]
            activation_failures = sim.facilities.activation_failures(f, sim.day)
            active_and_compatible = not activation_failures
            facilities.append(FacilityRow(
                str(f.id), str(f.definition_id), definition.display_name, f.level, f.paused, active_and_compatible,
                tuple(activation_failures), f.power_priority, tuple(sorted((x.id, x.rated_capacity) for x in definition.capability_supplies)),
                power.utilization_by_facility.get(f.id, 0.0 if not active_and_compatible else 1.0),
            ))
        industry = []
        snapshots = {
            snap.facility_id: snap
            for snap in sim.industry.snapshots(location_id, sim.facilities, sim.inventory, power, sim.day)
        }
        for facility in sorted(sim.facilities.all_at(location_id), key=lambda f: str(f.id)):
            compatible = tuple(sorted(sim.industry.compatible_processes(facility.definition_id), key=lambda p: str(p.id)))
            if not compatible:
                continue
            definition = sim.facilities.definitions[facility.definition_id]
            options = tuple((str(p.id), p.display_name) for p in compatible)
            snap = snapshots.get(facility.id)
            process = None if snap is None else sim.industry.processes[snap.process_id]
            if snap is not None:
                limiting = snap.limiting_factors
                scale = snap.scale
                inputs = tuple((str(k), v) for k, v in sorted(snap.input_rates_per_day.items(), key=lambda x: str(x[0])))
                outputs = tuple((str(k), v) for k, v in sorted(snap.output_rates_per_day.items(), key=lambda x: str(x[0])))
            else:
                failures = sim.facilities.activation_failures(facility, sim.day)
                if failures:
                    limiting = tuple(f"facility:{code}" for code, _detail in failures)
                else:
                    limiting = ("process:unselected",)
                scale = 0.0
                inputs = ()
                outputs = ()
            industry.append(IndustryRow(
                str(facility.id), str(facility.definition_id), definition.display_name,
                None if process is None else str(process.id),
                None if process is None else process.display_name,
                options, scale, limiting, inputs, outputs,
            ))

        extraction: list[ExtractionRow] = []
        if sim.extraction is not None:
            for snap in sim.extraction.snapshots(location_id, sim.facilities, sim.inventory, power, sim.day):
                definition = sim.facilities.definitions[snap.facility_def_id]
                extraction.append(ExtractionRow(
                    str(snap.facility_id), str(snap.facility_def_id), definition.display_name,
                    str(snap.output_resource_id), self._resource_name(snap.output_resource_id),
                    snap.scale, snap.output_t_per_day, snap.limiting_factors,
                ))

        capability_rows = tuple(
            CapabilityRow(
                capability_id,
                sim.facilities.infrastructure_capability_capacity_at(location_id, capability_id, sim.day),
                sim.facilities.active_capability_capacity_at(location_id, capability_id, sim.day),
                sim.facilities.available_capability_capacity_at(location_id, capability_id, power, sim.day),
            )
            for capability_id in sorted(sim.facilities.capability_ids())
            if sim.facilities.infrastructure_capability_capacity_at(location_id, capability_id, sim.day) > 1e-9
        )

        return LocationView(
            str(location_id), node.display_name, sim.day, self._environment_rows(location_id),
            power.generation_mw, power.demand_mw, power.allocated_mw,
            sim.projects.construction_capacity_at(location_id, power, sim.day),
            capability_rows, self._inventory_rows(location_id), self._storage_rows(location_id), tuple(facilities), tuple(industry),
            tuple(extraction), self._project_rows(location_id),
        )

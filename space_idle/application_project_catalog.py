from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Mapping

from .application_views import (
    CapabilityRequirementRow, CatalogView, CelestialBodyDefinitionRow,
    FacilityDefinitionRow, LocationDefinitionRow, LocationSummary,
    OperationCapabilityDefinitionRow, ProcessDefinitionRow,
    RequirementConditionRow, ResearchDefinitionRow, ResourceDefinitionRow,
    RouteDefinitionRow, SiteRequirementsDefinitionRow,
    TransportServiceDefinitionRow, VehicleDefinitionRow, WorldView,
)
from .shared import DefinitionId
from .site import SiteRequirements


class CatalogWorldProjectorMixin:
    @staticmethod
    def _definition_value(value: object) -> object:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, type):
            return getattr(value, "facet_key", value.__name__)
        if isinstance(value, Mapping):
            return tuple(
                (str(k), CatalogWorldProjectorMixin._definition_value(v))
                for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            )
        if isinstance(value, (set, frozenset)):
            return tuple(sorted((CatalogWorldProjectorMixin._definition_value(v) for v in value), key=str))
        if isinstance(value, (tuple, list)):
            return tuple(CatalogWorldProjectorMixin._definition_value(v) for v in value)
        if is_dataclass(value):
            return tuple(
                (field.name, CatalogWorldProjectorMixin._definition_value(getattr(value, field.name)))
                for field in fields(value)
            )
        if isinstance(value, str):
            return str(value)
        return value

    def _condition_definition_row(self, condition: object) -> RequirementConditionRow:
        parameters: list[tuple[str, object]] = []
        if is_dataclass(condition):
            for field in fields(condition):
                if field.name in {"code", "description"}:
                    continue
                parameters.append((field.name, self._definition_value(getattr(condition, field.name))))
        return RequirementConditionRow(
            type(condition).__name__,
            str(getattr(condition, "code", type(condition).__name__)),
            str(getattr(condition, "description", "")),
            tuple(parameters),
        )

    def _site_requirements_definition(self, requirements: SiteRequirements) -> SiteRequirementsDefinitionRow:
        return SiteRequirementsDefinitionRow(
            tuple(self._condition_definition_row(condition) for condition in requirements.environment),
            tuple(
                CapabilityRequirementRow(req.capability_id, req.minimum_capacity, req.mode)
                for req in requirements.capability_requirements
            ),
        )

    def _operation_capability_definition(self, capability: object) -> OperationCapabilityDefinitionRow:
        parameters: list[tuple[str, object]] = []
        if is_dataclass(capability):
            for field in fields(capability):
                if field.name == "operation_type":
                    continue
                parameters.append((field.name, self._definition_value(getattr(capability, field.name))))
        return OperationCapabilityDefinitionRow(str(getattr(capability, "operation_type")), tuple(parameters))

    @staticmethod
    def _vehicle_concept(definition: object) -> str:
        from .logistics import VehicleDisposition
        return (
            "launch_vehicle"
            if definition.powered_ascent is not None
            and definition.default_disposition is VehicleDisposition.RETURN_TO_ORIGIN
            and definition.spaceflight is None
            else "spacecraft"
        )

    def _catalog_view(self) -> CatalogView:
        sim = self._simulation
        resources = tuple(
            ResourceDefinitionRow(
                str(definition.id), definition.display_name, definition.unit, definition.category,
                sim.inventory.resource_storage_class.get(definition.id),
            )
            for definition in sorted(self._catalog.resources.values(), key=lambda d: str(d.id))
        )
        facilities = tuple(
            FacilityDefinitionRow(
                str(definition.id),
                definition.display_name,
                tuple(sorted((supply.id, supply.rated_capacity) for supply in definition.capability_supplies)),
                tuple(self._condition_definition_row(condition) for condition in definition.installation_environment),
                tuple(self._condition_definition_row(condition) for condition in definition.operating_environment),
            )
            for definition in sorted(sim.facilities.definitions.values(), key=lambda d: str(d.id))
        )
        processes = tuple(
            ProcessDefinitionRow(
                str(process.id), process.display_name, str(process.facility_def_id),
                tuple((str(resource_id), amount) for resource_id, amount in sorted(process.inputs_per_day.items(), key=lambda item: str(item[0]))),
                tuple((str(resource_id), amount) for resource_id, amount in sorted(process.outputs_per_day.items(), key=lambda item: str(item[0]))),
            )
            for process in sorted(sim.industry.processes.values(), key=lambda row: str(row.id))
        )
        research = ()
        if sim.research is not None:
            research = tuple(
                ResearchDefinitionRow(
                    str(definition.id), definition.display_name, definition.theory_points,
                    tuple(sorted(str(item) for item in definition.prerequisites)),
                    self._site_requirements_definition(definition.theory_site_requirements),
                    tuple((str(resource_id), amount) for resource_id, amount in sorted(definition.prototype_resources.items(), key=lambda item: str(item[0]))),
                    self._site_requirements_definition(definition.prototype_site_requirements),
                    definition.demonstration_days,
                    self._site_requirements_definition(definition.demonstration_site_requirements),
                )
                for definition in sorted(sim.research.definitions.values(), key=lambda row: str(row.id))
            )
        vehicles = tuple(
            VehicleDefinitionRow(
                str(definition.id), definition.display_name, self._vehicle_concept(definition),
                definition.dry_mass_t, definition.payload_t, definition.propellant_capacity_t,
                None if definition.propellant_resource_id is None else str(definition.propellant_resource_id),
                tuple(sorted(capability.operation_type for capability in definition.performance.operation_capabilities)),
                tuple((req.operation_type, req.location.value, req.capability_id) for req in definition.operation_support_requirements),
                definition.production_capability_id, definition.production_days, definition.production_cost_musd,
                tuple((str(resource_id), amount_t) for resource_id, amount_t in definition.production_resources),
                definition.turnaround_capability_id, definition.turnaround_days, definition.turnaround_cost_musd,
                tuple((str(resource_id), amount_t) for resource_id, amount_t in definition.turnaround_resources),
                tuple(self._operation_capability_definition(capability) for capability in definition.performance.operation_capabilities),
            )
            for definition in sorted(sim.logistics.vehicle_defs.values(), key=lambda d: str(d.id))
        )
        routes = tuple(
            RouteDefinitionRow(
                str(route.id), route.display_name or str(route.id), str(route.origin_id), str(route.destination_id),
                route.transit_days, route.delta_v_km_s,
                tuple((operation.operation_type, operation.delta_v_km_s) for operation in route.operations),
                self._site_requirements_definition(route.origin_requirements),
                self._site_requirements_definition(route.destination_requirements),
            )
            for route in sorted(sim.logistics.routes.values(), key=lambda row: str(row.id))
        )
        transport_services = tuple(
            TransportServiceDefinitionRow(
                str(service.id), service.display_name, service.capacity_t_per_day, service.cost_musd_per_t,
                service.performance.dry_mass_t, service.performance.payload_t, service.transit_time_multiplier,
                tuple(self._operation_capability_definition(capability) for capability in service.performance.operation_capabilities),
                self._site_requirements_definition(service.origin_requirements),
                self._site_requirements_definition(service.destination_requirements),
            )
            for service in sorted(sim.logistics.external_services.values(), key=lambda row: str(row.id))
        )
        celestial_bodies = tuple(
            CelestialBodyDefinitionRow(str(body.id), body.display_name)
            for body in sorted(sim.graph.bodies.values(), key=lambda body: str(body.id))
        )
        locations = tuple(
            LocationDefinitionRow(
                str(node.id), node.display_name,
                None if node.parent_id is None else str(node.parent_id),
                None if node.body_id is None else str(node.body_id), node.kind.value,
            )
            for node in sorted(sim.graph.nodes.values(), key=lambda n: str(n.id))
        )
        return CatalogView(
            resources, facilities, vehicles, celestial_bodies, locations,
            processes, research, routes, transport_services,
        )

    def _world_view(self) -> WorldView:
        sim = self._simulation
        locations = []
        for node in sorted(sim.graph.nodes.values(), key=lambda n: str(n.id)):
            facility_count = sum(1 for f in sim.facilities.facilities.values() if f.location_id == node.id)
            active_projects = sum(
                1 for p in sim.projects.projects.values()
                if p.location_id == node.id and p.status not in {"complete", "cancelled"}
            )
            locations.append(LocationSummary(
                str(node.id), node.display_name,
                None if node.parent_id is None else str(node.parent_id),
                None if node.body_id is None else str(node.body_id),
                node.kind.value, facility_count, active_projects,
            ))
        return WorldView(
            sim.content_id, sim.day, sim.account.funds_musd,
            sim.account.passive_income_musd_per_day, tuple(locations),
        )

    def _resource_name(self, resource_id: DefinitionId) -> str:
        definition = self._catalog.resources.get(resource_id)
        return definition.display_name if definition is not None else str(resource_id)

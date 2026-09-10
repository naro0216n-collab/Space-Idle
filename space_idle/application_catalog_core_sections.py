from __future__ import annotations

from .application_catalog_support import condition_definition_row, site_requirements_definition
from .application_views import (
    CelestialBodyDefinitionRow, FacilityDefinitionRow, LocationDefinitionRow,
    ProcessDefinitionRow, ResearchDefinitionRow, ResourceDefinitionRow,
)
from .site import SiteRequirements


def project_resources(projector):
    sim = projector._simulation
    return tuple(
        ResourceDefinitionRow(
            str(definition.id), definition.display_name, definition.unit, definition.category,
            sim.inventory.resource_storage_class.get(definition.id),
        )
        for definition in sorted(projector._catalog.resources.values(), key=lambda d: str(d.id))
    )


def project_facilities(projector):
    return tuple(
        FacilityDefinitionRow(
            str(definition.id), definition.display_name,
            tuple(sorted((supply.id, supply.rated_capacity) for supply in definition.capability_supplies)),
            tuple(condition_definition_row(condition) for condition in definition.installation_environment),
            tuple(condition_definition_row(condition) for condition in definition.operating_environment),
            definition.maintenance_fraction_per_year,
        )
        for definition in sorted(projector._simulation.facilities.definitions.values(), key=lambda d: str(d.id))
    )


def project_processes(projector):
    return tuple(
        ProcessDefinitionRow(
            str(process.id), process.display_name, str(process.facility_def_id),
            tuple((str(resource_id), amount) for resource_id, amount in sorted(process.inputs_per_day.items(), key=lambda item: str(item[0]))),
            tuple((str(resource_id), amount) for resource_id, amount in sorted(process.outputs_per_day.items(), key=lambda item: str(item[0]))),
        )
        for process in sorted(projector._simulation.industry.processes.values(), key=lambda row: str(row.id))
    )


def project_research(projector):
    sim = projector._simulation
    if sim.research is None:
        return ()
    empty_site = SiteRequirements()
    rows = []
    for definition in sorted(sim.research.definitions.values(), key=lambda row: str(row.id)):
        prototype = definition.prototype
        demonstration = definition.demonstration
        rows.append(ResearchDefinitionRow(
            str(definition.id),
            definition.display_name,
            definition.research_point_cost,
            tuple(sorted(str(item) for item in definition.prerequisites)),
            () if prototype is None else tuple(
                (str(resource_id), amount)
                for resource_id, amount in sorted(prototype.resources.items(), key=lambda item: str(item[0]))
            ),
            site_requirements_definition(empty_site if prototype is None else prototype.site_requirements),
            0 if demonstration is None else demonstration.days,
            site_requirements_definition(empty_site if demonstration is None else demonstration.site_requirements),
        ))
    return tuple(rows)


def project_celestial_bodies(projector):
    return tuple(
        CelestialBodyDefinitionRow(str(body.id), body.display_name)
        for body in sorted(projector._simulation.graph.bodies.values(), key=lambda body: str(body.id))
    )


def project_locations(projector):
    return tuple(
        LocationDefinitionRow(
            str(node.id), node.display_name,
            None if node.parent_id is None else str(node.parent_id),
            None if node.body_id is None else str(node.body_id), node.kind.value,
        )
        for node in sorted(projector._simulation.graph.nodes.values(), key=lambda n: str(n.id))
    )

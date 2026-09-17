from __future__ import annotations

from .application_catalog_support import site_requirements_definition
from .application_views import (
    CelestialBodyDefinitionRow, FacilityDefinitionRow, OperationalNodeDefinitionRow,
    ProcessDefinitionRow, ResearchDefinitionRow, ResearchStageDefinitionRow, ResourceDefinitionRow,
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
            id=str(definition.id),
            display_name=definition.display_name,
            capabilities=tuple(sorted(supply.id for supply in definition.capability_supplies)),
            service_capacity_supplies=tuple(
                sorted((supply.service_type, supply.nominal_rate) for supply in definition.service_capacity_supplies)
            ),
            installation_requirements=site_requirements_definition(definition.installation_requirements),
            operating_requirements=site_requirements_definition(definition.operating_requirements),
            maintenance_fraction_per_year=definition.maintenance_fraction_per_year,
            placement_scope=definition.placement_scope.value,
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
    from .research_models import (
        ResearchTheoryStageSpec, ResearchPrototypeStageSpec,
        ResearchDemonstrationStageSpec, ResearchOperationalExperienceStageSpec,
    )
    sim = projector._simulation
    if sim.research is None:
        return ()
    rows = []
    for definition in sorted(sim.research.definitions.values(), key=lambda row: str(row.id)):
        stage_rows = []
        for spec in definition.stage_specs:
            required = None
            resources = ()
            site = SiteRequirements()
            experience = ()
            if isinstance(spec, ResearchTheoryStageSpec):
                required = spec.research_point_cost
            elif isinstance(spec, ResearchPrototypeStageSpec):
                required = spec.required_work
                resources = tuple(
                    (str(resource_id), amount)
                    for resource_id, amount in sorted(spec.resources.items(), key=lambda item: str(item[0]))
                )
                site = spec.site_requirements
            elif isinstance(spec, ResearchDemonstrationStageSpec):
                required = spec.required_work
                site = spec.site_requirements
            elif isinstance(spec, ResearchOperationalExperienceStageSpec):
                experience = tuple(sorted(spec.requirements.items()))
            stage_rows.append(ResearchStageDefinitionRow(
                spec.stage_id, spec.stage_type.value, required, resources,
                site_requirements_definition(site), experience,
            ))
        rows.append(ResearchDefinitionRow(
            str(definition.id), definition.display_name,
            tuple(sorted(str(item) for item in definition.prerequisites)),
            tuple(stage_rows),
        ))
    return tuple(rows)


def project_celestial_bodies(projector):
    return tuple(
        CelestialBodyDefinitionRow(str(body.id), body.display_name)
        for body in sorted(projector._simulation.graph.bodies.values(), key=lambda body: str(body.id))
    )


def project_operational_nodes(projector):
    return tuple(
        OperationalNodeDefinitionRow(
            str(node.id), node.display_name,
            None if node.parent_id is None else str(node.parent_id),
            None if node.body_id is None else str(node.body_id), node.kind.value,
        )
        for node in projector._simulation.graph.operational_nodes()
    )

from __future__ import annotations

from .application_catalog_support import (
    site_requirements_definition, execution_requirement_definition, research_provider_definition,
)
from .application_views import (
    CelestialBodyDefinitionRow, FacilityDefinitionRow, OperationalNodeDefinitionRow,
    ProcessDefinitionRow, ResearchDefinitionRow, ResearchStageDefinitionRow, ResourceDefinitionRow,
    ServiceCapacityDefinitionRow,
)
from .app_contracts.catalog_views import FacilityDesignCoefficientsRow, ExtractionMethodDefinitionRow
from .site import SiteRequirements


def project_resources(projector):
    sim = projector._simulation
    return tuple(
        ResourceDefinitionRow(
            str(definition.id), definition.display_name, definition.unit, definition.category,
            definition.storage_pool_key,
        )
        for definition in sorted(projector._catalog.resources.values(), key=lambda d: str(d.id))
    )


def _sorted_resources(resources):
    return tuple((str(k), float(v)) for k, v in sorted(resources, key=lambda pair: str(pair[0])))


def _facility_design(projector, definition):
    sim = projector._simulation
    recipe = sim.projects.recipes.get(definition.id)
    investment = None if recipe is None else _sorted_resources(
        (item.resource_id, item.amount_t) for item in recipe.resources
    )
    provider = None if sim.research is None else sim.research.facility_provider_for_definition(definition.id)
    power_spec = sim.power.specs.get(definition.id)
    generation = None if power_spec is None else power_spec.generation
    reference_generation = (0.0 if generation is None else
                            generation.mw if hasattr(generation, "mw") else
                            generation.rated_mw_at_reference_flux)
    maintenance = (None if recipe is None else _sorted_resources(
        sim.facilities.maintenance_requirements_for_investment(
            definition.id, {row.resource_id: row.amount_t for row in recipe.resources}
        ).items()
    ))
    return FacilityDesignCoefficientsRow(
        investment, None if recipe is None else recipe.construction_work,
        None if recipe is None else recipe.self_deploying,
        () if recipe is None else tuple(sorted(map(str, recipe.prerequisite_technologies))),
        maintenance, _sorted_resources(definition.operating_resources_per_day),
        definition.process_throughput_per_day,
        (sim.projects.construction_providers[definition.id].work_per_day
         if definition.id in sim.projects.construction_providers else 0.0),
        0.0 if power_spec is None else power_spec.load_mw,
        "none" if generation is None else type(generation).__name__,
        reference_generation, definition.extraction_capacity_t_per_day,
        definition.housing_capacity,
        None if definition.life_support is None else definition.life_support.person_days_per_day,
        () if definition.life_support is None else _sorted_resources(definition.life_support.net_resources),
        None if provider is None else research_provider_definition(provider),
    )


def project_extraction_methods(projector):
    sim = projector._simulation
    if sim.extraction is None:
        return ()
    return tuple(ExtractionMethodDefinitionRow(
        str(spec.id), spec.display_name or str(spec.id), str(spec.resource_id),
        str(spec.output_resource_id), tuple(sorted(map(str, spec.prerequisite_technologies))),
        tuple(sorted(str(fid) for fid in sim.facilities.definitions
                     if spec in sim.extraction.compatible_methods(fid))),
    ) for spec in sorted(sim.extraction.specs.values(), key=lambda item: str(item.id)))


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
            design=_facility_design(projector, definition),
        )
        for definition in sorted(projector._simulation.facilities.definitions.values(), key=lambda d: str(d.id))
    )


def project_processes(projector):
    return tuple(
        ProcessDefinitionRow(
            str(process.id), process.display_name, tuple(sorted(process.required_capabilities)),
            tuple((str(resource_id), amount) for resource_id, amount in sorted(process.inputs_per_day.items(), key=lambda item: str(item[0]))),
            tuple((str(resource_id), amount) for resource_id, amount in sorted(process.outputs_per_day.items(), key=lambda item: str(item[0]))),
            tuple(sorted(map(str, process.prerequisite_technologies))),
            tuple(sorted(str(fid) for fid, facility in projector._simulation.facilities.definitions.items()
                         if process.required_capabilities <= facility.capability_ids)),
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
            else:
                raise TypeError(f"unprojected Research Stage definition: {type(spec).__name__}")
            stage_rows.append(ResearchStageDefinitionRow(
                spec.stage_id, spec.stage_type.value, required, resources,
                site_requirements_definition(site), experience,
                tuple(execution_requirement_definition(req) for req in getattr(spec, "execution_requirements", ())),
            ))
        rows.append(ResearchDefinitionRow(
            str(definition.id), definition.display_name,
            tuple(sorted(str(item) for item in definition.prerequisites)),
            tuple(stage_rows), definition.progression_stage, definition.category, definition.series,
        ))
    return tuple(rows)


def project_celestial_bodies(projector):
    graph = projector._simulation.graph
    return tuple(
        CelestialBodyDefinitionRow(
            str(body.id), body.display_name, str(body.star_system_id),
            None if body.parent_body_id is None else str(body.parent_body_id),
            body.physical_surface.value, len(graph.cells_for_body(body.id)),
            body.mean_radius_km, body.representative_gravity_m_s2,
            body.heliocentric_semimajor_axis_au, body.parent_orbit_semimajor_axis_km,
            graph.representative_solar_flux_w_m2(body.id),
        )
        for body in sorted(graph.bodies.values(), key=lambda body: str(body.id))
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


def project_survey_service_capacities(projector):
    """Project actual physical Survey source names for finite Service identifiers.

    Provider-owned compatibility and identifiers are authoritative; the UI does
    not interpret internal provider/source ID composition.
    """
    sim = projector._simulation
    if sim.survey is None:
        return ()
    return tuple(
        ServiceCapacityDefinitionRow(
            sim.survey.service_type_for_provider(provider.id, source_id),
            f"{projector._survey_source_display_name(provider.source_kind, source_id)} 調査能力",
        )
        for provider in sorted(sim.survey.providers.values(), key=lambda row: str(row.id))
        for source_id in sim.survey.compatible_source_definition_ids(provider)
    )

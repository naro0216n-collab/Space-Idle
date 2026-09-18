from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .validation_support import (
    ValidationContext, require as _require, validate_site_requirements,
)
from .exploration_models import (
    KnowledgeLevel, SurveyCampaign, SurveyProviderSourceKind,
)
from .shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId


def capture_survey(sim: Any) -> dict[str, Any]:
    if sim.survey is None:
        return {"knowledge_progress": [], "knowledge_precision_fraction": [], "campaigns": []}
    return {
        "knowledge_progress": [
            {"cell_id": str(cell), "resource_id": str(res), "progress": progress}
            for (cell, res), progress in sorted(
                sim.survey.knowledge_progress.items(),
                key=lambda x: (str(x[0][0]), str(x[0][1])),
            )
        ],
        "knowledge_precision_fraction": [
            {"cell_id": str(cell), "resource_id": str(res), "precision_fraction": precision}
            for (cell, res), precision in sorted(
                sim.survey.knowledge_precision_fraction.items(),
                key=lambda x: (str(x[0][0]), str(x[0][1])),
            )
        ],
        "campaigns": [
            {
                "provider_definition_id": str(c.provider_definition_id),
                "observation_mode_id": c.observation_mode_id,
                "provider_operational_node_id": str(c.provider_operational_node_id),
                "cell_id": str(c.cell_id),
                "resource_id": str(c.resource_id),
                "target_knowledge_level": int(c.target_knowledge_level),
                "priority": int(c.priority),
                "paused": c.paused,
                "fleet_commitment_ref": None if c.fleet_commitment_ref is None else str(c.fleet_commitment_ref),
            }
            for _, c in sorted(
                sim.survey.campaigns.items(),
                key=lambda x: (str(x[0][0]), str(x[0][1])),
            )
        ],
    }


def restore_survey(sim: Any, data: dict[str, Any]) -> None:
    if sim.survey is None:
        return
    sim.survey.knowledge_progress = {
        (SurfaceCellId(r["cell_id"]), DefinitionId(r["resource_id"])): float(r["progress"])
        for r in data.get("knowledge_progress", [])
    }
    sim.survey.knowledge_precision_fraction = {
        (SurfaceCellId(r["cell_id"]), DefinitionId(r["resource_id"])): float(r["precision_fraction"])
        for r in data.get("knowledge_precision_fraction", [])
    }
    sim.survey.campaigns.clear()
    for r in data.get("campaigns", []):
        cell_id = SurfaceCellId(r["cell_id"])
        resource_id = DefinitionId(r["resource_id"])
        fleet_ref = r.get("fleet_commitment_ref")
        sim.survey.campaigns[(cell_id, resource_id)] = SurveyCampaign(
            DefinitionId(r["provider_definition_id"]),
            str(r["observation_mode_id"]),
            SpatialNodeId(r["provider_operational_node_id"]),
            cell_id,
            resource_id,
            KnowledgeLevel(int(r["target_knowledge_level"])),
            priority=int(r["priority"]),
            paused=bool(r["paused"]),
            fleet_commitment_ref=None if fleet_ref is None else EntityId(fleet_ref),
        )


def survey_referenced_resources(sim: Any) -> set[DefinitionId]:
    if sim.survey is None:
        return set()
    return {resource_id for (_cell_id, resource_id) in sim.survey.targets}


def extraction_referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    if sim.extraction is not None:
        for spec in sim.extraction.specs.values():
            result.add(spec.resource_id)
            result.add(spec.output_resource_id)
    return result


SURVEY_STATE_CODEC = StateCodec("survey", capture_survey, restore_survey, True)


def validate_survey_configuration(sim: Any, ctx: ValidationContext) -> None:
    if sim.survey is None:
        return
    _require(sim.survey.graph is sim.graph, "survey service must use simulation spatial graph")
    _require(sim.survey.transport is sim.transport, "survey service must use simulation Fleet owner")
    for key, target in sim.survey.targets.items():
        _require(key == (target.cell_id, target.resource_id), f"survey target key mismatch: {key}")
        _require(target.cell_id in sim.graph.surface_cells, f"survey target references unknown surface cell: {key}")
        if target.cell_id in sim.graph.surface_cells:
            cell = sim.graph.surface_cells[target.cell_id]
            _require(target.resource_id in cell.resource_potential_by_resource, f"survey target resource has no static potential entry: {key}")
        _require(len(target.thresholds) == 3, f"survey target must define three knowledge thresholds: {key}")
        _require(all(v >= 0 for v in target.thresholds), f"negative survey threshold: {key}")
        _require(tuple(sorted(target.thresholds)) == target.thresholds, f"unsorted survey thresholds: {key}")
    for provider_id, provider in sim.survey.providers.items():
        _require(provider_id == provider.id, f"survey provider key mismatch: {provider_id}")
        _require(provider.capacity_units_per_source_per_day > 0, f"non-positive survey provider capacity: {provider_id}")
        if provider.source_kind is SurveyProviderSourceKind.FACILITY:
            _require(provider.source_definition_id in ctx.facility_defs, f"survey provider references unknown facility: {provider_id}")
        else:
            _require(sim.transport.vehicle_definition(provider.source_definition_id) is not None, f"survey provider references unknown Vehicle: {provider_id}")
        for mode in provider.observation_modes:
            _require(KnowledgeLevel.PRESENCE_PROBABILITY <= mode.max_knowledge_level <= KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL, f"invalid Survey Knowledge cap: {provider_id}/{mode.id}")
            validate_site_requirements(mode.site_requirements, ctx.known_capabilities, f"survey:{provider_id}/{mode.id}")


def validate_extraction_configuration(sim: Any, ctx: ValidationContext) -> None:
    if sim.extraction is None:
        return
    _require(sim.extraction.graph is sim.graph, "extraction service must use simulation spatial graph")
    for definition_id, spec in sim.extraction.specs.items():
        _require(definition_id == spec.facility_def_id, f"extraction spec key mismatch: {definition_id}")
        _require(definition_id in ctx.facility_defs, f"extraction spec references unknown facility: {definition_id}")
        _require(spec.nominal_capacity_t_per_day >= 0, f"negative extraction capacity: {definition_id}")
        validate_site_requirements(
            spec.opportunity_requirements,
            ctx.known_capabilities,
            f"extraction:{definition_id}",
        )
        if spec.geology_accessibility_key is not None:
            _require(
                any(
                    spec.geology_accessibility_key in cell.static_geology
                    for cell in sim.graph.surface_cells.values()
                ),
                f"extraction spec references unknown geology accessibility: {definition_id}/{spec.geology_accessibility_key}",
            )
        if spec.terrain_accessibility_attribute is not None:
            _require(
                all(
                    hasattr(cell.terrain, spec.terrain_accessibility_attribute)
                    for cell in sim.graph.surface_cells.values()
                ),
                f"extraction spec references unknown terrain accessibility: {definition_id}/{spec.terrain_accessibility_attribute}",
            )


def validate_survey_runtime(sim: Any) -> None:
    if sim.survey is None:
        return
    for key, progress in sim.survey.knowledge_progress.items():
        _require(key in sim.survey.targets, f"knowledge references unknown survey target: {key}")
        _require(progress >= -1e-9, f"negative survey knowledge progress: {key}")
        if key in sim.survey.targets:
            _require(progress <= sim.survey.targets[key].thresholds[-1] + 1e-8, f"survey knowledge exceeds final threshold: {key}")
    for key, precision in sim.survey.knowledge_precision_fraction.items():
        _require(key in sim.survey.targets, f"survey precision references unknown target: {key}")
        _require(0.0 <= precision <= 1.0, f"survey precision outside 0..1: {key}")
        _require(sim.survey.knowledge_level(*key) >= KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL, f"survey precision exists before estimated knowledge: {key}")
    for key, campaign in sim.survey.campaigns.items():
        _require(key == (campaign.cell_id, campaign.resource_id), f"survey campaign key mismatch: {key}")
        _require(key in sim.survey.targets, f"campaign references unknown survey target: {key}")
        _require(campaign.provider_definition_id in sim.survey.providers, f"campaign references unknown survey provider: {key}")
        _require(sim.graph.has_operational_node(campaign.provider_operational_node_id), f"campaign provider operational node is unknown: {key}")
        if campaign.provider_definition_id in sim.survey.providers:
            provider = sim.survey.providers[campaign.provider_definition_id]
            try:
                mode = provider.observation_mode(campaign.observation_mode_id)
            except KeyError:
                _require(False, f"campaign references unknown observation mode: {key}")
                continue
            _require(campaign.target_knowledge_level <= mode.max_knowledge_level, f"campaign exceeds observation mode Knowledge cap: {key}")
            if provider.source_kind is SurveyProviderSourceKind.FLEET and campaign.fleet_commitment_ref is not None:
                commitment = sim.transport.fleet_commitment(campaign.fleet_commitment_ref)
                _require(commitment is not None, f"survey Fleet commitment missing: {key}")
                if commitment is not None:
                    _require(commitment.owner_activity_ref.activity_type == "survey", f"survey Fleet commitment owner type mismatch: {key}")
                    _require(commitment.owner_activity_ref.activity_id == sim.survey.campaign_owner_id(*key), f"survey Fleet commitment owner id mismatch: {key}")
                    _require(commitment.vehicle_definition_id == provider.source_definition_id, f"survey Fleet commitment Vehicle mismatch: {key}")
        _require(KnowledgeLevel.PRESENCE_PROBABILITY <= campaign.target_knowledge_level <= KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL, f"invalid survey campaign Knowledge target: {key}")
        _require(sim.survey.knowledge_level(*key) < campaign.target_knowledge_level, f"survey campaign already reached target: {key}")
        _require(1 <= int(campaign.priority) <= 5, f"survey priority must be 1..5: {key}")


def validate_extraction_runtime(sim: Any) -> None:
    if sim.extraction is None:
        return
    # Extraction has no mutable reserve/deposit state. Throughput is derived from
    # static Surface Cell potential, current Facilities, and operational fulfillment.
    for location_id in sim.graph.locations:
        for resource_id in {
            spec.resource_id for spec in sim.extraction.specs.values()
        }:
            _require(
                sim.extraction.static_opportunity(location_id, resource_id) >= 0.0,
                f"negative extraction opportunity: {(location_id, resource_id)}",
            )
            _require(
                sim.extraction.effective_opportunity(
                    location_id, resource_id, sim.facilities, day=sim.day
                ) >= 0.0,
                f"negative effective extraction opportunity: {(location_id, resource_id)}",
            )


SURVEY_EXTENSION = DomainExtension(
    "survey",
    state_codec=SURVEY_STATE_CODEC,
    configuration_validator=validate_survey_configuration,
    runtime_validator=validate_survey_runtime,
    referenced_resources=survey_referenced_resources,
    service_capacity_provider=lambda sim: sim.survey,
)
EXTRACTION_EXTENSION = DomainExtension(
    "extraction",
    configuration_validator=validate_extraction_configuration,
    runtime_validator=validate_extraction_runtime,
    referenced_resources=extraction_referenced_resources,
    service_capacity_provider=lambda sim: sim.extraction,
)

from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .validation_support import ValidationContext, require as _require
from .exploration_models import SurveyCampaign
from .shared import DefinitionId, SpatialNodeId, SurfaceCellId


def capture_survey(sim: Any) -> dict[str, Any]:
    if sim.survey is None:
        return {"knowledge_progress": [], "campaigns": []}
    return {
        "knowledge_progress": [
            {"cell_id": str(cell), "resource_id": str(res), "progress": progress}
            for (cell, res), progress in sorted(
                sim.survey.knowledge_progress.items(),
                key=lambda x: (str(x[0][0]), str(x[0][1])),
            )
        ],
        "campaigns": [
            {
                "provider_operational_node_id": str(c.provider_operational_node_id),
                "cell_id": str(c.cell_id),
                "resource_id": str(c.resource_id),
                "target_knowledge_level": c.target_knowledge_level,
                "priority": c.priority,
                "paused": c.paused,
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
    sim.survey.campaigns.clear()
    for r in data.get("campaigns", []):
        provider_operational_node_id = SpatialNodeId(r["provider_operational_node_id"])
        cell_id = SurfaceCellId(r["cell_id"])
        resource_id = DefinitionId(r["resource_id"])
        sim.survey.campaigns[(cell_id, resource_id)] = SurveyCampaign(
            provider_operational_node_id,
            cell_id,
            resource_id,
            target_knowledge_level=int(r.get("target_knowledge_level", 4)),
            priority=int(r["priority"]),
            paused=bool(r["paused"]),
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
    for key, target in sim.survey.targets.items():
        _require(key == (target.cell_id, target.resource_id), f"survey target key mismatch: {key}")
        _require(target.cell_id in sim.graph.surface_cells, f"survey target references unknown surface cell: {key}")
        if target.cell_id in sim.graph.surface_cells:
            cell = sim.graph.surface_cells[target.cell_id]
            _require(
                target.resource_id in cell.resource_potential_by_resource,
                f"survey target resource has no static potential entry: {key}",
            )
        _require(0 <= target.prior_presence_probability <= 1, f"survey probability outside 0..1: {key}")
        _require(len(target.thresholds) == 4, f"survey target must define four knowledge thresholds: {key}")
        _require(all(v >= 0 for v in target.thresholds), f"negative survey threshold: {key}")
        _require(tuple(sorted(target.thresholds)) == target.thresholds, f"unsorted survey thresholds: {key}")
    for definition_id, provider in sim.survey.providers.items():
        _require(definition_id == provider.facility_def_id, f"survey provider key mismatch: {definition_id}")
        _require(definition_id in ctx.facility_defs, f"survey provider references unknown facility: {definition_id}")
        _require(provider.points_per_day >= 0, f"negative survey capacity: {definition_id}")
        _require(1 <= provider.max_knowledge_level <= 4, f"invalid survey provider knowledge cap: {definition_id}")


def validate_extraction_configuration(sim: Any, ctx: ValidationContext) -> None:
    if sim.extraction is None:
        return
    _require(sim.extraction.graph is sim.graph, "extraction service must use simulation spatial graph")
    for definition_id, spec in sim.extraction.specs.items():
        _require(definition_id == spec.facility_def_id, f"extraction spec key mismatch: {definition_id}")
        _require(definition_id in ctx.facility_defs, f"extraction spec references unknown facility: {definition_id}")
        _require(spec.nominal_capacity_t_per_day >= 0, f"negative extraction capacity: {definition_id}")


def validate_survey_runtime(sim: Any) -> None:
    if sim.survey is None:
        return
    for key, progress in sim.survey.knowledge_progress.items():
        _require(key in sim.survey.targets, f"knowledge references unknown survey target: {key}")
        _require(progress >= -1e-9, f"negative survey knowledge progress: {key}")
        _require(
            progress <= sim.survey.targets[key].thresholds[-1] + 1e-8,
            f"survey knowledge exceeds final threshold: {key}",
        )
    for key, campaign in sim.survey.campaigns.items():
        _require(key == (campaign.cell_id, campaign.resource_id), f"survey campaign key mismatch: {key}")
        _require(key in sim.survey.targets, f"campaign references unknown survey target: {key}")
        _require(sim.graph.has_operational_node(campaign.provider_operational_node_id), f"campaign provider operational node is unknown: {key}")
        if key in sim.survey.targets and sim.graph.has_operational_node(campaign.provider_operational_node_id):
            provider_body = sim.graph.operational_node(campaign.provider_operational_node_id).body_id
            target_body = sim.graph.surface_cells[campaign.cell_id].body_id
            _require(provider_body == target_body, f"survey campaign crosses celestial bodies: {key}")
            provider_specs = [
                sim.survey.providers.get(f.definition_id)
                for f in sim.facilities.all_at(campaign.provider_operational_node_id)
            ]
            _require(
                any(
                    spec is not None
                    and sim.survey._provider_covers_target(
                        campaign.provider_operational_node_id, spec, campaign.cell_id
                    )
                    and spec.max_knowledge_level >= campaign.target_knowledge_level
                    for spec in provider_specs
                ),
                f"survey campaign has no provider matching its coverage and knowledge target: {key}",
            )
        _require(1 <= campaign.target_knowledge_level <= 4, f"invalid survey campaign knowledge target: {key}")
        _require(
            sim.survey.knowledge_level(*key) < campaign.target_knowledge_level,
            f"survey campaign already reached its provider knowledge target: {key}",
        )
        _require(isinstance(campaign.priority, int), f"invalid survey priority: {key}")


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


SURVEY_EXTENSION = DomainExtension(
    "survey",
    state_codec=SURVEY_STATE_CODEC,
    configuration_validator=validate_survey_configuration,
    runtime_validator=validate_survey_runtime,
    referenced_resources=survey_referenced_resources,
)
EXTRACTION_EXTENSION = DomainExtension(
    "extraction",
    configuration_validator=validate_extraction_configuration,
    runtime_validator=validate_extraction_runtime,
    referenced_resources=extraction_referenced_resources,
)

from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .validation_support import ValidationContext, require as _require
from .exploration_models import SurveyCampaign
from .shared import DefinitionId, SpatialNodeId


def capture_survey(sim: Any) -> dict[str, Any]:
    if sim.survey is None:
        return {"campaigns": []}
    return {
        "campaigns": [
            {
                "location_id": str(c.location_id), "resource_id": str(c.resource_id),
                "progress": c.progress, "allocation_weight": c.allocation_weight, "paused": c.paused,
            }
            for _, c in sorted(sim.survey.campaigns.items(), key=lambda x: (str(x[0][0]), str(x[0][1])))
        ]
    }


def restore_survey(sim: Any, data: dict[str, Any]) -> None:
    if sim.survey is None:
        return
    sim.survey.campaigns.clear()
    for r in data.get("campaigns", []):
        loc = SpatialNodeId(r["location_id"])
        res = DefinitionId(r["resource_id"])
        sim.survey.campaigns[(loc, res)] = SurveyCampaign(
            loc, res, float(r["progress"]), float(r["allocation_weight"]), bool(r["paused"])
        )


def capture_extraction(sim: Any) -> dict[str, Any]:
    if sim.extraction is None:
        return {"remaining_reserve_t": []}
    return {
        "remaining_reserve_t": [
            {"location_id": str(loc), "resource_id": str(res), "amount": amount}
            for (loc, res), amount in sorted(sim.extraction.remaining_reserve_t.items(), key=lambda x: (str(x[0][0]), str(x[0][1])))
        ]
    }


def restore_extraction(sim: Any, data: dict[str, Any]) -> None:
    if sim.extraction is None:
        return
    sim.extraction.remaining_reserve_t = {
        (SpatialNodeId(r["location_id"]), DefinitionId(r["resource_id"])): float(r["amount"])
        for r in data.get("remaining_reserve_t", [])
    }


def survey_referenced_resources(sim: Any) -> set[DefinitionId]:
    if sim.survey is None:
        return set()
    return {resource_id for (_location_id, resource_id) in sim.survey.targets}


def extraction_referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    if sim.extraction is not None:
        for spec in sim.extraction.specs.values():
            result.add(spec.deposit_resource_id)
            result.add(spec.output_resource_id)
    return result


SURVEY_STATE_CODEC = StateCodec("survey", capture_survey, restore_survey, True)
EXTRACTION_STATE_CODEC = StateCodec("extraction", capture_extraction, restore_extraction, True)
def validate_survey_configuration(sim: Any, ctx: ValidationContext) -> None:
    if sim.survey is None:
        return
    for key, target in sim.survey.targets.items():
        _require(key == (target.location_id, target.resource_id), f"survey target key mismatch: {key}")
        _require(target.location_id in ctx.nodes, f"survey target references unknown location: {key}")
        _require(0 <= target.prior_presence_probability <= 1, f"survey probability outside 0..1: {key}")
        _require(0 <= target.actual_concentration <= 1, f"survey concentration outside 0..1: {key}")
        _require(target.reserve_t >= 0, f"negative reserve: {key}")
        _require(len(target.thresholds) == 4, f"survey target must define four knowledge thresholds: {key}")
        _require(all(v >= 0 for v in target.thresholds), f"negative survey threshold: {key}")
        _require(tuple(sorted(target.thresholds)) == target.thresholds, f"unsorted survey thresholds: {key}")
    for definition_id, provider in sim.survey.providers.items():
        _require(definition_id == provider.facility_def_id, f"survey provider key mismatch: {definition_id}")
        _require(definition_id in ctx.facility_defs, f"survey provider references unknown facility: {definition_id}")
        _require(provider.points_per_day >= 0, f"negative survey capacity: {definition_id}")


def validate_extraction_configuration(sim: Any, ctx: ValidationContext) -> None:
    if sim.extraction is None:
        return
    for definition_id, spec in sim.extraction.specs.items():
        _require(definition_id == spec.facility_def_id, f"extraction spec key mismatch: {definition_id}")
        _require(definition_id in ctx.facility_defs, f"extraction spec references unknown facility: {definition_id}")
        _require(spec.excavated_t_per_day >= 0, f"negative extraction rate: {definition_id}")
        _require(0 <= spec.min_knowledge_level <= 4, f"invalid survey knowledge requirement: {definition_id}")


def validate_survey_runtime(sim: Any) -> None:
    if sim.survey is None:
        return
    for key, campaign in sim.survey.campaigns.items():
        _require(key == (campaign.location_id, campaign.resource_id), f"survey campaign key mismatch: {key}")
        _require(key in sim.survey.targets, f"campaign references unknown survey target: {key}")
        _require(campaign.progress >= -1e-9, f"negative survey progress: {key}")
        _require(campaign.allocation_weight >= 0, f"negative survey allocation: {key}")


def validate_extraction_runtime(sim: Any) -> None:
    if sim.extraction is None:
        return
    _require(sim.survey is not None, "extraction service requires survey service")
    for key, amount in sim.extraction.remaining_reserve_t.items():
        _require(key in sim.survey.targets, f"remaining reserve references unknown deposit: {key}")
        _require(amount >= -1e-9, f"negative remaining reserve: {key}")
        _require(amount <= sim.survey.targets[key].reserve_t + 1e-8, f"remaining reserve exceeds initial reserve: {key}")


SURVEY_EXTENSION = DomainExtension(
    "survey", state_codec=SURVEY_STATE_CODEC, configuration_validator=validate_survey_configuration,
    runtime_validator=validate_survey_runtime, referenced_resources=survey_referenced_resources,
)
EXTRACTION_EXTENSION = DomainExtension(
    "extraction", state_codec=EXTRACTION_STATE_CODEC, configuration_validator=validate_extraction_configuration,
    runtime_validator=validate_extraction_runtime, referenced_resources=extraction_referenced_resources,
)

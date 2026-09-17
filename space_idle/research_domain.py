from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .execution_requirements import ServiceCapacityRequirement
from .validation_support import ValidationContext, require as _require, validate_site_requirements as _validate_site_requirements
from .research_models import (
    ResearchExecutionSite,
    ResearchTheoryStageSpec,
    ResearchPrototypeStageSpec,
    ResearchDemonstrationStageSpec,
    ResearchOperationalExperienceStageSpec,
    ResearchProviderSourceKind,
    ResearchState,
)
from .shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .site import requires_surface_cell_context


def _capture_execution_site(site: ResearchExecutionSite | None) -> dict[str, str | None] | None:
    if site is None:
        return None
    return {
        "operational_node_id": str(site.operational_node_id),
        "surface_cell_id": None if site.surface_cell_id is None else str(site.surface_cell_id),
    }


def _restore_execution_site(data: dict[str, Any] | None) -> ResearchExecutionSite | None:
    if data is None:
        return None
    return ResearchExecutionSite(
        SpatialNodeId(data["operational_node_id"]),
        None if data.get("surface_cell_id") is None else SurfaceCellId(data["surface_cell_id"]),
    )


def capture_research(sim: Any) -> dict[str, Any]:
    if sim.research is None:
        return {"stored_points": 0.0, "knowledge": {}, "active": [], "provider_assignments": []}
    return {
        "stored_points": sim.research.stored_points,
        "knowledge": dict(sorted(sim.research.knowledge_state.experience_by_category.items())),
        "active": [
            {
                "definition_id": str(r.definition_id),
                "current_stage_id": r.current_stage_id,
                "stage_progress": r.stage_progress,
                "priority": r.priority,
                "paused": r.paused,
                "execution_context": _capture_execution_site(r.execution_context),
                "stage_started_day": r.stage_started_day,
            }
            for r in sorted(sim.research.active.values(), key=lambda row: str(row.definition_id))
        ],
        "provider_assignments": [],
    }


def restore_research(sim: Any, data: dict[str, Any]) -> None:
    if sim.research is None:
        return
    sim.research.stored_points = float(data["stored_points"])
    sim.research.knowledge_state.experience_by_category = {
        str(category): float(value) for category, value in data.get("knowledge", {}).items()
    }
    sim.research.active.clear()
    sim.research.provider_assignments.clear()
    sim.research.last_point_allocations.clear()
    sim.research.last_point_requests.clear()
    sim.research.last_execution_allocations.clear()
    sim.research.last_execution_requests.clear()
    for row in data.get("active", []):
        rid = DefinitionId(row["definition_id"])
        sim.research.active[rid] = ResearchState(
            definition_id=rid,
            current_stage_id=str(row["current_stage_id"]),
            stage_progress=None if row.get("stage_progress") is None else float(row["stage_progress"]),
            priority=row["priority"],
            paused=bool(row["paused"]),
            execution_context=_restore_execution_site(row.get("execution_context")),
            stage_started_day=int(row.get("stage_started_day", 0)),
        )


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    if sim.research is None:
        return result
    for definition in sim.research.definitions.values():
        for spec in definition.stage_specs:
            if isinstance(spec, ResearchPrototypeStageSpec):
                result.update(spec.resources)
    return result


STATE_CODEC = StateCodec("research", capture_research, restore_research, True)


def _validate_execution_requirements(requirements, research_id, stage_id, ctx):
    for requirement in requirements:
        if isinstance(requirement, ServiceCapacityRequirement):
            _require(
                requirement.service_type in ctx.known_service_types,
                f"research stage references unknown service type: {research_id}/{stage_id}/{requirement.service_type}",
            )


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    if sim.research is None:
        return
    definitions = sim.research.definitions
    rule_categories = {rule.category_id for rule in sim.research.experience_rules}
    for research_id, research in definitions.items():
        _require(research_id == research.id, f"research definition key mismatch: {research_id}")
        _require(research.prerequisites.issubset(definitions), f"unknown research prerequisite: {research_id}")
        _require(research_id not in research.prerequisites, f"self research prerequisite: {research_id}")
        _require(bool(research.stage_specs), f"research has no stages: {research_id}")
        stage_ids = [spec.stage_id for spec in research.stage_specs]
        _require(len(stage_ids) == len(set(stage_ids)), f"research repeats stage id: {research_id}")
        for spec in research.stage_specs:
            owner = f"research:{research_id}:{spec.stage_id}"
            if isinstance(spec, ResearchTheoryStageSpec):
                _require(spec.research_point_cost > 0, f"invalid theory cost: {owner}")
                _validate_execution_requirements(spec.execution_requirements, research_id, spec.stage_id, ctx)
            elif isinstance(spec, ResearchPrototypeStageSpec):
                _require(all(value >= 0 for value in spec.resources.values()), f"negative prototype resource requirement: {owner}")
                _require(spec.required_work > 0, f"invalid prototype work: {owner}")
                _validate_site_requirements(spec.site_requirements, ctx.known_capabilities, owner)
                _validate_execution_requirements(spec.execution_requirements, research_id, spec.stage_id, ctx)
            elif isinstance(spec, ResearchDemonstrationStageSpec):
                _require(spec.required_work > 0, f"invalid demonstration work: {owner}")
                _validate_site_requirements(spec.site_requirements, ctx.known_capabilities, owner)
                _validate_execution_requirements(spec.execution_requirements, research_id, spec.stage_id, ctx)
            elif isinstance(spec, ResearchOperationalExperienceStageSpec):
                for category, required in spec.requirements.items():
                    _require(required >= 0, f"negative experience requirement: {owner}/{category}")
                    _require(category in rule_categories, f"research references experience category with no contribution rule: {owner}/{category}")
            else:
                raise TypeError(f"unknown research stage spec: {type(spec)!r}")

    visiting: set[object] = set(); visited: set[object] = set()
    def visit(node: object) -> None:
        if node in visited: return
        _require(node not in visiting, f"research prerequisite cycle at {node}")
        visiting.add(node)
        for dep in definitions[node].prerequisites: visit(dep)  # type: ignore[index]
        visiting.remove(node); visited.add(node)
    for research_id in definitions: visit(research_id)

    for provider_id, provider in sim.research.providers.items():
        _require(provider_id == provider.id, f"research provider key mismatch: {provider_id}")
        if provider.source_kind is ResearchProviderSourceKind.FACILITY:
            _require(provider.source_definition_id in ctx.facility_defs, f"research provider references unknown facility: {provider_id}")
        else:
            _require(sim.transport.vehicle_definition(provider.source_definition_id) is not None, f"research provider references unknown vehicle: {provider_id}")
        _require(provider.tier >= 1, f"invalid research provider tier: {provider_id}")
        levels = [level.level for level in provider.levels]
        _require(len(levels) == len(set(levels)), f"duplicate research provider level: {provider_id}")


def validate_runtime(sim: Any) -> None:
    if sim.research is None:
        return
    _require(sim.research.stored_points >= -1e-9, "negative stored research points")
    for category, value in sim.research.knowledge_state.experience_by_category.items():
        _require(category != "", "empty knowledge category")
        _require(value >= -1e-9, f"negative knowledge value: {category}")

    def validate_execution_context(research_id, spec, site):
        if site is None: return
        _require(sim.graph.has_operational_node(site.operational_node_id), f"research stage references unknown operational node: {research_id}/{spec.stage_id}")
        needs_cell = requires_surface_cell_context(spec.site_requirements)
        if site.surface_cell_id is None:
            _require(not (site.operational_node_id in sim.graph.locations and needs_cell), f"research stage requires explicit surface cell: {research_id}/{spec.stage_id}")
            return
        location = sim.graph.locations.get(site.operational_node_id)
        _require(location is not None, f"research stage cell requires surface location: {research_id}/{spec.stage_id}")
        if location is not None:
            _require(site.surface_cell_id in location.developed_cell_ids, f"research stage references undeveloped cell: {research_id}/{spec.stage_id}/{site.surface_cell_id}")
        _require(needs_cell, f"research stage stores unnecessary surface cell: {research_id}/{spec.stage_id}")

    allowed_reservations: dict[EntityId, tuple[DefinitionId, str, SpatialNodeId, ResearchPrototypeStageSpec]] = {}
    for research_id, state in sim.research.active.items():
        _require(research_id == state.definition_id, f"research state key mismatch: {research_id}")
        definition = sim.research.definitions[research_id]
        try: spec = definition.stage_spec(state.current_stage_id)
        except KeyError:
            _require(False, f"invalid active research stage id: {research_id}/{state.current_stage_id}"); continue
        _require(state.stage_started_day >= 0, f"negative research stage start day: {research_id}")
        if isinstance(spec, ResearchOperationalExperienceStageSpec):
            _require(state.stage_progress is None, f"operational experience stores project progress: {research_id}/{spec.stage_id}")
            _require(state.execution_context is None, f"operational experience stores execution context: {research_id}/{spec.stage_id}")
        else:
            _require(state.stage_progress is not None and state.stage_progress >= -1e-9, f"progress-bearing stage lacks progress: {research_id}/{spec.stage_id}")
        if isinstance(spec, ResearchTheoryStageSpec):
            _require(state.execution_context is None, f"theory stage stores execution context: {research_id}/{spec.stage_id}")
            _require((state.stage_progress or 0.0) <= spec.research_point_cost + 1e-7, f"theory progress exceeds requirement: {research_id}/{spec.stage_id}")
        elif isinstance(spec, ResearchPrototypeStageSpec):
            _require((state.stage_progress or 0.0) <= spec.required_work + 1e-7, f"prototype progress exceeds requirement: {research_id}/{spec.stage_id}")
            validate_execution_context(research_id, spec, state.execution_context)
            if state.execution_context is not None:
                allowed_reservations[sim.research._prototype_reservation_owner_id(research_id, spec.stage_id)] = (research_id, spec.stage_id, state.execution_context.operational_node_id, spec)
        elif isinstance(spec, ResearchDemonstrationStageSpec):
            _require((state.stage_progress or 0.0) <= spec.required_work + 1e-7, f"demonstration progress exceeds requirement: {research_id}/{spec.stage_id}")
            validate_execution_context(research_id, spec, state.execution_context)

    for (owner_id, location_id, resource_id), amount in sim.inventory.reserved.items():
        if not str(owner_id).startswith("research.stage:"): continue
        _require(owner_id in allowed_reservations, f"orphaned research stage reservation: {owner_id}")
        if owner_id not in allowed_reservations: continue
        research_id, stage_id, expected_location, spec = allowed_reservations[owner_id]
        _require(location_id == expected_location, f"research reservation at wrong location: {research_id}/{stage_id}")
        _require(resource_id in spec.resources, f"research stage reserves unexpected resource: {research_id}/{stage_id}/{resource_id}")
        if resource_id in spec.resources:
            _require(-1e-9 <= amount <= spec.resources[resource_id] + 1e-9, f"research reserved resource outside requirement: {research_id}/{stage_id}/{resource_id}")
    _require(sim.research.completed.issubset(sim.research.definitions), "completed research contains unknown definition")


DOMAIN_EXTENSION = DomainExtension(
    "research", state_codec=STATE_CODEC, configuration_validator=validate_configuration,
    runtime_validator=validate_runtime, referenced_resources=referenced_resources,
    allocation_pool_provider=lambda sim: sim.research,
)

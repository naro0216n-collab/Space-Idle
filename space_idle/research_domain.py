from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .validation_support import (
    ValidationContext,
    require as _require,
    validate_site_requirements as _validate_site_requirements,
)
from .research_models import ResearchStage, ResearchState
from .shared import DefinitionId, EntityId, SpatialNodeId


def capture_research(sim: Any) -> dict[str, Any]:
    if sim.research is None:
        return {"stored_points": 0.0, "knowledge": {}, "active": []}
    return {
        "stored_points": sim.research.stored_points,
        "knowledge": dict(sorted(sim.research.knowledge_state.experience_by_category.items())),
        "active": [
            {
                "definition_id": str(r.definition_id),
                "stage": r.stage.value,
                "stage_progress": r.stage_progress,
                "priority": r.priority,
                "paused": r.paused,
                "prototype_operational_node_id": (
                    None if r.prototype_operational_node_id is None else str(r.prototype_operational_node_id)
                ),
                "demonstration_operational_node_id": (
                    None if r.demonstration_operational_node_id is None else str(r.demonstration_operational_node_id)
                ),
            }
            for r in sorted(sim.research.active.values(), key=lambda row: str(row.definition_id))
        ],
    }


def restore_research(sim: Any, data: dict[str, Any]) -> None:
    if sim.research is None:
        return
    sim.research.stored_points = float(data["stored_points"])
    sim.research.knowledge_state.experience_by_category = {
        str(category): float(value)
        for category, value in data.get("knowledge", {}).items()
    }
    sim.research.active.clear()
    sim.research.last_point_allocations.clear()
    sim.research.last_point_requests.clear()
    sim.research.last_execution_allocations.clear()
    sim.research.last_execution_requests.clear()
    for r in data.get("active", []):
        rid = DefinitionId(r["definition_id"])
        sim.research.active[rid] = ResearchState(
            rid,
            ResearchStage(r["stage"]),
            float(r.get("stage_progress", 0.0)),
            int(r.get("priority", 50)),
            bool(r["paused"]),
            None
            if r["prototype_operational_node_id"] is None
            else SpatialNodeId(r["prototype_operational_node_id"]),
            None
            if r.get("demonstration_operational_node_id") is None
            else SpatialNodeId(r["demonstration_operational_node_id"]),
        )


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    if sim.research is not None:
        for definition in sim.research.definitions.values():
            if definition.prototype is not None:
                result.update(definition.prototype.resources)
    return result


STATE_CODEC = StateCodec("research", capture_research, restore_research, True)


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    if sim.research is None:
        return
    definitions = sim.research.definitions
    known_capabilities = ctx.known_capabilities
    facility_defs = ctx.facility_defs
    rule_categories = {rule.category_id for rule in sim.research.experience_rules}
    for research_id, research in definitions.items():
        _require(research_id == research.id, f"research definition key mismatch: {research_id}")
        _require(
            research.prerequisites.issubset(definitions),
            f"unknown research prerequisite: {research_id}",
        )
        _require(
            research_id not in research.prerequisites,
            f"self research prerequisite: {research_id}",
        )
        _require(research.stages, f"research has no stages: {research_id}")
        _require(
            len(set(research.stages)) == len(research.stages),
            f"research repeats a stage: {research_id}",
        )
        _require(
            (ResearchStage.THEORY in research.stages) == (research.research_point_cost > 0),
            f"research theory/cost mismatch: {research_id}",
        )
        _require(
            (ResearchStage.PROTOTYPE in research.stages) == (research.prototype is not None),
            f"research prototype stage mismatch: {research_id}",
        )
        _require(
            (ResearchStage.DEMONSTRATION in research.stages)
            == (research.demonstration is not None),
            f"research demonstration stage mismatch: {research_id}",
        )
        _require(
            (ResearchStage.OPERATIONAL_EXPERIENCE in research.stages)
            == (research.operational_experience is not None),
            f"research operational experience stage mismatch: {research_id}",
        )
        if research.prototype is not None:
            _require(
                all(v >= 0 for v in research.prototype.resources.values()),
                f"negative prototype resource requirement: {research_id}",
            )
            _validate_site_requirements(
                research.prototype.site_requirements,
                known_capabilities,
                f"research:{research_id}:prototype",
                ctx.known_service_types,
            )
        if research.demonstration is not None:
            _require(
                research.demonstration.days > 0,
                f"invalid research demonstration duration: {research_id}",
            )
            _validate_site_requirements(
                research.demonstration.site_requirements,
                known_capabilities,
                f"research:{research_id}:demonstration",
                ctx.known_service_types,
            )
        if research.operational_experience is not None:
            for category, required in research.operational_experience.requirements.items():
                _require(required >= 0, f"negative experience requirement: {research_id}/{category}")
                _require(
                    category in rule_categories,
                    f"research references experience category with no contribution rule: {research_id}/{category}",
                )

    visiting: set[object] = set()
    visited: set[object] = set()

    def visit(node: object) -> None:
        if node in visited:
            return
        _require(node not in visiting, f"research prerequisite cycle at {node}")
        visiting.add(node)
        for dep in definitions[node].prerequisites:  # type: ignore[index]
            visit(dep)
        visiting.remove(node)
        visited.add(node)

    for research_id in definitions:
        visit(research_id)
    for definition_id, provider in sim.research.providers.items():
        _require(
            definition_id == provider.facility_def_id,
            f"research provider key mismatch: {definition_id}",
        )
        _require(
            definition_id in facility_defs,
            f"research provider references unknown facility: {definition_id}",
        )
        _require(provider.tier >= 1, f"invalid research provider tier: {definition_id}")
        seen_levels: set[int] = set()
        for level in provider.levels:
            _require(
                level.level >= 1,
                f"invalid research provider level: {definition_id}/{level.level}",
            )
            _require(
                level.level not in seen_levels,
                f"duplicate research provider level: {definition_id}/{level.level}",
            )
            seen_levels.add(level.level)
            _require(
                level.generation_points_per_day >= 0,
                f"negative research generation: {definition_id}/{level.level}",
            )
            _require(
                level.storage_capacity_points >= 0,
                f"negative research storage: {definition_id}/{level.level}",
            )


def validate_runtime(sim: Any) -> None:
    if sim.research is None:
        return
    _require(sim.research.stored_points >= -1e-9, "negative stored research points")
    for category, value in sim.research.knowledge_state.experience_by_category.items():
        _require(category != "", "empty knowledge category")
        _require(value >= -1e-9, f"negative knowledge value: {category}")

    for research_id, state in sim.research.active.items():
        _require(
            research_id == state.definition_id,
            f"research state key mismatch: {research_id}",
        )
        _require(
            research_id in sim.research.definitions,
            f"active unknown research: {research_id}",
        )
        definition = sim.research.definitions[research_id]
        _require(
            state.stage in definition.stages,
            f"invalid active research stage: {research_id}/{state.stage}",
        )
        _require(state.stage_progress >= -1e-9, f"negative research stage progress: {research_id}")
        if state.stage is ResearchStage.THEORY:
            _require(
                state.stage_progress <= definition.research_point_cost + 1e-7,
                f"theory progress exceeds requirement: {research_id}",
            )
        elif state.stage is ResearchStage.PROTOTYPE:
            _require(definition.prototype is not None, f"prototype state without definition: {research_id}")
            _require(state.stage_progress <= 1.0 + 1e-7, f"invalid prototype progress: {research_id}")
        elif state.stage is ResearchStage.DEMONSTRATION:
            _require(
                definition.demonstration is not None,
                f"demonstration state without definition: {research_id}",
            )
            if definition.demonstration is not None:
                _require(
                    state.stage_progress <= definition.demonstration.days + 1e-7,
                    f"invalid demonstration progress: {research_id}",
                )
        _require(
            state.prototype_operational_node_id is None
            or sim.graph.has_operational_node(state.prototype_operational_node_id),
            f"research prototype references unknown location: {research_id}",
        )
        _require(
            state.demonstration_operational_node_id is None
            or sim.graph.has_operational_node(state.demonstration_operational_node_id),
            f"research demonstration references unknown location: {research_id}",
        )

    allowed_staging: dict[EntityId, tuple[DefinitionId, SpatialNodeId]] = {}
    for research_id, state in sim.research.active.items():
        if state.stage is ResearchStage.PROTOTYPE and state.prototype_operational_node_id is not None:
            allowed_staging[sim.research._prototype_staging_owner_id(research_id)] = (
                research_id,
                state.prototype_operational_node_id,
            )
    for (owner_id, location_id, resource_id), amount in sim.inventory.external_occupancy.items():
        if not str(owner_id).startswith("research.prototype:"):
            continue
        _require(owner_id in allowed_staging, f"orphaned research prototype staging: {owner_id}")
        if owner_id not in allowed_staging:
            continue
        research_id, expected_location_id = allowed_staging[owner_id]
        prototype = sim.research.definitions[research_id].prototype
        _require(
            prototype is not None,
            f"research prototype staging lacks prototype definition: {research_id}",
        )
        if prototype is None:
            continue
        _require(
            location_id == expected_location_id,
            f"research prototype staging at wrong location: {research_id}",
        )
        _require(
            resource_id in prototype.resources,
            f"research prototype stages unexpected resource: {research_id}/{resource_id}",
        )
        if resource_id in prototype.resources:
            _require(
                -1e-9 <= amount <= prototype.resources[resource_id] + 1e-9,
                f"research prototype staged resource outside requirement: {research_id}/{resource_id}",
            )
    _require(
        sim.research.completed.issubset(sim.research.definitions),
        "completed research contains unknown definition",
    )


DOMAIN_EXTENSION = DomainExtension(
    "research",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)

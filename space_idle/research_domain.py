from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .validation_support import ValidationContext, require as _require, validate_site_requirements as _validate_site_requirements
from .research_models import ResearchPhase, ResearchState
from .shared import DefinitionId, SpatialNodeId


def capture_research(sim: Any) -> dict[str, Any]:
    if sim.research is None:
        return {"stored_points": 0.0, "active": []}
    return {
        "stored_points": sim.research.stored_points,
        "active": [
            {
                "definition_id": str(r.definition_id),
                "status": r.status.value,
                "demonstration_done_days": r.demonstration_done_days,
                "paused": r.paused,
                "prototype_location_id": None if r.prototype_location_id is None else str(r.prototype_location_id),
                "demonstration_location_id": None if r.demonstration_location_id is None else str(r.demonstration_location_id),
            }
            for r in sorted(sim.research.active.values(), key=lambda row: str(row.definition_id))
        ],
    }


def restore_research(sim: Any, data: dict[str, Any]) -> None:
    if sim.research is None:
        return
    sim.research.stored_points = float(data["stored_points"])
    sim.research.active.clear()
    for r in data.get("active", []):
        rid = DefinitionId(r["definition_id"])
        sim.research.active[rid] = ResearchState(
            rid,
            ResearchPhase(r["status"]),
            int(r["demonstration_done_days"]),
            bool(r["paused"]),
            None if r["prototype_location_id"] is None else SpatialNodeId(r["prototype_location_id"]),
            None if r.get("demonstration_location_id") is None else SpatialNodeId(r["demonstration_location_id"]),
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
    for research_id, research in definitions.items():
        _require(research_id == research.id, f"research definition key mismatch: {research_id}")
        _require(research.prerequisites.issubset(definitions), f"unknown research prerequisite: {research_id}")
        _require(research_id not in research.prerequisites, f"self research prerequisite: {research_id}")
        _require(research.research_point_cost >= 0, f"negative research point cost: {research_id}")
        if research.prototype is not None:
            _require(
                all(v >= 0 for v in research.prototype.resources.values()),
                f"negative prototype resource requirement: {research_id}",
            )
            _validate_site_requirements(
                research.prototype.site_requirements,
                known_capabilities,
                f"research:{research_id}:prototype",
            )
        if research.demonstration is not None:
            _require(research.demonstration.days > 0, f"invalid research demonstration duration: {research_id}")
            _validate_site_requirements(
                research.demonstration.site_requirements,
                known_capabilities,
                f"research:{research_id}:demonstration",
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
        _require(definition_id == provider.facility_def_id, f"research provider key mismatch: {definition_id}")
        _require(definition_id in facility_defs, f"research provider references unknown facility: {definition_id}")
        _require(provider.tier >= 1, f"invalid research provider tier: {definition_id}")
        seen_levels: set[int] = set()
        for level in provider.levels:
            _require(level.level >= 1, f"invalid research provider level: {definition_id}/{level.level}")
            _require(level.level not in seen_levels, f"duplicate research provider level: {definition_id}/{level.level}")
            seen_levels.add(level.level)
            _require(level.generation_points_per_day >= 0, f"negative research generation: {definition_id}/{level.level}")
            _require(level.storage_capacity_points >= 0, f"negative research storage: {definition_id}/{level.level}")


def validate_runtime(sim: Any) -> None:
    if sim.research is None:
        return
    _require(sim.research.stored_points >= -1e-9, "negative stored research points")
    for research_id, state in sim.research.active.items():
        _require(research_id == state.definition_id, f"research state key mismatch: {research_id}")
        _require(research_id in sim.research.definitions, f"active unknown research: {research_id}")
        _require(
            state.status in {ResearchPhase.PROTOTYPE, ResearchPhase.DEMONSTRATION},
            f"invalid active research phase: {research_id}/{state.status}",
        )
        definition = sim.research.definitions[research_id]
        if state.status is ResearchPhase.PROTOTYPE:
            _require(definition.prototype is not None, f"prototype state without prototype definition: {research_id}")
            _require(state.demonstration_done_days == 0, f"prototype research has demonstration progress: {research_id}")
            _require(state.demonstration_location_id is None, f"prototype research retains demonstration site: {research_id}")
        else:
            _require(definition.demonstration is not None, f"demonstration state without demonstration definition: {research_id}")
            _require(
                0 <= state.demonstration_done_days <= definition.demonstration.days,
                f"invalid demonstration progress: {research_id}",
            )
        _require(
            state.prototype_location_id is None or sim.graph.has_operational_node(state.prototype_location_id),
            f"research prototype references unknown location: {research_id}",
        )
        _require(
            state.demonstration_location_id is None or sim.graph.has_operational_node(state.demonstration_location_id),
            f"research demonstration references unknown location: {research_id}",
        )
    _require(sim.research.completed.issubset(sim.research.definitions), "completed research contains unknown definition")


DOMAIN_EXTENSION = DomainExtension(
    "research",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)

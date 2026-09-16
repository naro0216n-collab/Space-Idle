from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .validation_support import (
    ValidationContext,
    require as _require,
    validate_site_requirements as _validate_site_requirements,
)
from .research_models import ResearchExecutionSite, ResearchStage, ResearchState
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
                "prototype_execution_site": _capture_execution_site(r.prototype_execution_site),
                "demonstration_execution_site": _capture_execution_site(r.demonstration_execution_site),
                "stage_started_day": r.stage_started_day,
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
            definition_id=rid,
            stage=ResearchStage(r["stage"]),
            stage_progress=float(r.get("stage_progress", 0.0)),
            priority=r["priority"],
            paused=bool(r["paused"]),
            prototype_execution_site=_restore_execution_site(r.get("prototype_execution_site")),
            demonstration_execution_site=_restore_execution_site(r.get("demonstration_execution_site")),
            stage_started_day=int(r.get("stage_started_day", 0)),
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

    def validate_execution_site(
        research_id: DefinitionId,
        label: str,
        site: ResearchExecutionSite | None,
        requirements,
    ) -> None:
        if site is None:
            return
        _require(
            sim.graph.has_operational_node(site.operational_node_id),
            f"research {label} references unknown operational node: {research_id}",
        )
        if not sim.graph.has_operational_node(site.operational_node_id):
            return
        needs_cell = requires_surface_cell_context(requirements)
        if site.surface_cell_id is None:
            _require(
                not (
                    site.operational_node_id in sim.graph.locations
                    and needs_cell
                ),
                f"research {label} requires explicit surface cell: {research_id}",
            )
            return
        location = sim.graph.locations.get(site.operational_node_id)
        _require(
            location is not None,
            f"research {label} surface cell requires surface location: {research_id}",
        )
        if location is None:
            return
        _require(
            site.surface_cell_id in location.developed_cell_ids,
            f"research {label} references undeveloped surface cell: {research_id}/{site.surface_cell_id}",
        )
        _require(
            needs_cell,
            f"research {label} stores unnecessary surface cell: {research_id}/{site.surface_cell_id}",
        )

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
        _require(state.stage_started_day >= 0, f"negative research stage start day: {research_id}")
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
        if definition.prototype is not None:
            validate_execution_site(
                research_id,
                "prototype",
                state.prototype_execution_site,
                definition.prototype.site_requirements,
            )
        else:
            _require(
                state.prototype_execution_site is None,
                f"research without prototype stores prototype execution site: {research_id}",
            )
        if definition.demonstration is not None:
            validate_execution_site(
                research_id,
                "demonstration",
                state.demonstration_execution_site,
                definition.demonstration.site_requirements,
            )
        else:
            _require(
                state.demonstration_execution_site is None,
                f"research without demonstration stores demonstration execution site: {research_id}",
            )
        if state.stage is ResearchStage.THEORY:
            _require(
                state.prototype_execution_site is None
                and state.demonstration_execution_site is None,
                f"theory research must not own an execution site: {research_id}",
            )

    allowed_reservations: dict[EntityId, tuple[DefinitionId, SpatialNodeId]] = {}
    for research_id, state in sim.research.active.items():
        site = state.prototype_execution_site
        if (
            state.stage is ResearchStage.PROTOTYPE
            and site is not None
        ):
            allowed_reservations[
                sim.research._prototype_reservation_owner_id(research_id)
            ] = (research_id, site.operational_node_id)
    for (owner_id, location_id, resource_id), amount in sim.inventory.reserved.items():
        if not str(owner_id).startswith("research.prototype:"):
            continue
        _require(
            owner_id in allowed_reservations,
            f"orphaned research prototype reservation: {owner_id}",
        )
        if owner_id not in allowed_reservations:
            continue
        research_id, expected_location_id = allowed_reservations[owner_id]
        prototype = sim.research.definitions[research_id].prototype
        _require(
            prototype is not None,
            f"research prototype reservation lacks prototype definition: {research_id}",
        )
        if prototype is None:
            continue
        _require(
            location_id == expected_location_id,
            f"research prototype reservation at wrong location: {research_id}",
        )
        _require(
            resource_id in prototype.resources,
            f"research prototype reserves unexpected resource: {research_id}/{resource_id}",
        )
        if resource_id in prototype.resources:
            _require(
                -1e-9 <= amount <= prototype.resources[resource_id] + 1e-9,
                f"research prototype reserved resource outside requirement: {research_id}/{resource_id}",
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

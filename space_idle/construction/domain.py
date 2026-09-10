from __future__ import annotations

from typing import Any

from ..domain import DomainExtension, StateCodec
from ..validation_support import (
    ValidationContext,
    require as _require,
    validate_site_requirements as _validate_site_requirements,
)
from ..shared import DefinitionId, EntityId, ProjectId, SpatialNodeId
from .models import (
    ConstructionProject,
    FacilityUpgradeTarget,
    NewFacilityTarget,
    ProjectResourceState,
    ProjectStatus,
)


def _capture_target(target) -> dict[str, Any]:
    if isinstance(target, NewFacilityTarget):
        return {"kind": "new_facility", "facility_def_id": str(target.facility_def_id)}
    return {
        "kind": "facility_upgrade",
        "facility_id": str(target.facility_id),
        "target_level": target.target_level,
    }


def _restore_target(data: dict[str, Any]):
    if data["kind"] == "new_facility":
        return NewFacilityTarget(DefinitionId(data["facility_def_id"]))
    if data["kind"] == "facility_upgrade":
        return FacilityUpgradeTarget(EntityId(data["facility_id"]), int(data["target_level"]))
    raise ValueError(f"unknown construction target kind: {data['kind']}")


def capture_projects(sim: Any) -> dict[str, Any]:
    return {
        "counter": sim.projects._counter,
        "items": [
            {
                "id": str(project.id),
                "target": _capture_target(project.target),
                "location_id": str(project.location_id),
                "priority": project.priority,
                "sourcing_policy": project.sourcing_policy,
                "import_source_id": None if project.import_source_id is None else str(project.import_source_id),
                "status": project.status.value,
                "procurement_started_day": project.procurement_started_day,
                "construction_done": project.construction_done,
                "construction_weight": project.construction_weight,
                "paused": project.paused,
                "pause_started_day": project.pause_started_day,
                "completed_facility_id": None if project.completed_facility_id is None else str(project.completed_facility_id),
                "materials_committed": project.materials_committed,
                "resources": [
                    {
                        "resource_id": str(resource_id),
                        "committed_t": state.committed_t,
                        "import_committed_t": state.import_committed_t,
                    }
                    for resource_id, state in sorted(project.resources.items(), key=lambda row: str(row[0]))
                ],
            }
            for project in sorted(sim.projects.projects.values(), key=lambda row: str(row.id))
        ],
    }


def restore_projects(sim: Any, data: dict[str, Any]) -> None:
    sim.projects._counter = int(data["counter"])
    sim.projects.projects.clear()
    for row in data["items"]:
        project_id = ProjectId(row["id"])
        resources = {
            DefinitionId(item["resource_id"]): ProjectResourceState(
                committed_t=float(item["committed_t"]),
                import_committed_t=None if item["import_committed_t"] is None else float(item["import_committed_t"]),
            )
            for item in row["resources"]
        }
        sim.projects.projects[project_id] = ConstructionProject(
            id=project_id,
            target=_restore_target(row["target"]),
            location_id=SpatialNodeId(row["location_id"]),
            priority=int(row["priority"]),
            sourcing_policy=row["sourcing_policy"],
            import_source_id=None if row["import_source_id"] is None else SpatialNodeId(row["import_source_id"]),
            status=ProjectStatus(row["status"]),
            procurement_started_day=row["procurement_started_day"],
            construction_done=float(row["construction_done"]),
            construction_weight=float(row["construction_weight"]),
            paused=bool(row["paused"]),
            pause_started_day=None if row["pause_started_day"] is None else int(row["pause_started_day"]),
            resources=resources,
            materials_committed=bool(row["materials_committed"]),
            completed_facility_id=None if row["completed_facility_id"] is None else EntityId(row["completed_facility_id"]),
        )


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set(sim.projects.construction_resource_providers)
    for recipe in tuple(sim.projects.recipes.values()) + tuple(sim.projects.upgrade_recipes.values()):
        result.update(requirement.resource_id for requirement in recipe.resources)
    return result


STATE_CODEC = StateCodec("projects", capture_projects, restore_projects)


def _validate_recipe(recipe, owner: str, ctx: ValidationContext) -> None:
    _require(recipe.facility_def_id in ctx.facility_defs, f"construction recipe references unknown facility: {owner}")
    _require(recipe.construction_work >= 0, f"negative construction work: {owner}")
    _require(recipe.prerequisite_technologies.issubset(ctx.known_technologies), f"construction references unknown technology: {owner}")
    _validate_site_requirements(recipe.site_requirements, ctx.known_capabilities, owner)
    resource_ids: set[DefinitionId] = set()
    for requirement in recipe.resources:
        _require(requirement.resource_id not in resource_ids, f"duplicate construction resource: {owner}/{requirement.resource_id}")
        resource_ids.add(requirement.resource_id)
        _require(requirement.amount_t > 0, f"non-positive construction resource amount: {owner}/{requirement.resource_id}")
    _require(
        2 <= len(recipe.resources) <= 3,
        f"construction recipe must use 2-3 physical resources: {owner}",
    )


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    for facility_id, recipe in sim.projects.recipes.items():
        _require(facility_id == recipe.facility_def_id, f"construction recipe key mismatch: {facility_id}")
        _validate_recipe(recipe, f"construction:{facility_id}", ctx)
    seen_upgrade_targets: set[tuple[DefinitionId, int]] = set()
    for key, recipe in sim.projects.upgrade_recipes.items():
        expected = (recipe.facility_def_id, recipe.target_level)
        _require(key == expected, f"upgrade recipe key mismatch: {key}")
        _require(recipe.target_level >= 2, f"invalid upgrade target level: {expected}")
        _require(not recipe.self_deploying, f"facility upgrade cannot self-deploy: {expected}")
        _require(expected not in seen_upgrade_targets, f"duplicate facility upgrade recipe: {expected}")
        seen_upgrade_targets.add(expected)
        _validate_recipe(recipe, f"construction_upgrade:{recipe.facility_def_id}:L{recipe.target_level}", ctx)
    _require(set(sim.projects.sourcing_wait_days) == {"import_now", "mixed", "local_priority"}, "invalid sourcing policy configuration")
    _require(all(days >= 0 for days in sim.projects.sourcing_wait_days.values()), "negative sourcing wait period")
    for definition_id, spec in sim.projects.construction_providers.items():
        _require(definition_id == spec.facility_def_id, f"construction provider key mismatch: {definition_id}")
        _require(definition_id in ctx.facility_defs, f"construction provider references unknown facility: {definition_id}")
        _require(spec.work_per_day >= 0, f"negative construction capacity: {definition_id}")
    for resource_id, spec in sim.projects.construction_resource_providers.items():
        _require(resource_id == spec.resource_id, f"construction resource provider key mismatch: {resource_id}")
        _require(spec.work_per_t_per_day >= 0, f"negative construction resource productivity: {spec.resource_id}")


def validate_runtime(sim: Any) -> None:
    active_upgrade_targets: set[EntityId] = set()
    for project_id, project in sim.projects.projects.items():
        _require(project.location_id in sim.graph.nodes, f"project references unknown location: {project_id}")
        if project.import_source_id is not None:
            _require(project.import_source_id in sim.graph.nodes, f"project import source is unknown: {project_id}")
            _require(project.import_source_id != project.location_id, f"project import source equals destination: {project_id}")
        if isinstance(project.target, NewFacilityTarget):
            _require(project.target.facility_def_id in sim.projects.recipes, f"project references unknown build recipe: {project_id}")
            recipe = sim.projects.recipes[project.target.facility_def_id]
        else:
            _require(project.target.facility_id in sim.facilities.facilities, f"upgrade project references unknown facility: {project_id}")
            facility = sim.facilities.facilities[project.target.facility_id]
            _require(facility.location_id == project.location_id, f"upgrade project location mismatch: {project_id}")
            key = (facility.definition_id, project.target.target_level)
            _require(key in sim.projects.upgrade_recipes, f"upgrade project references unknown recipe: {project_id}")
            recipe = sim.projects.upgrade_recipes[key]
            if project.status not in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
                _require(project.target.facility_id not in active_upgrade_targets, f"duplicate active facility upgrade: {project.target.facility_id}")
                active_upgrade_targets.add(project.target.facility_id)
                _require(facility.level == project.target.target_level - 1, f"active upgrade target level mismatch: {project_id}")
            if project.status is ProjectStatus.COMPLETE:
                _require(facility.level == project.target.target_level, f"completed upgrade did not apply target level: {project_id}")
        _require(-1e-9 <= project.construction_done <= recipe.construction_work + 1e-8, f"invalid construction progress: {project_id}")
        _require(project.construction_weight >= 0, f"negative construction allocation: {project_id}")
        _require(not project.paused or project.pause_started_day is not None, f"paused project missing pause day: {project_id}")
        _require(project.paused or project.pause_started_day is None, f"active project retains pause day: {project_id}")
        if project.materials_committed:
            _require(project.status in {ProjectStatus.BUILDING, ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}, f"materials committed before construction: {project_id}")
            _require(not any(owner == EntityId(project.id) for owner, _location, _resource in sim.inventory.reserved), f"committed project retains inventory reservation: {project_id}")
        if project.status is ProjectStatus.COMPLETE:
            _require(project.completed_facility_id in sim.facilities.facilities, f"complete project lacks affected facility: {project_id}")
            completed = sim.facilities.facilities[project.completed_facility_id]
            _require(completed.location_id == project.location_id, f"completed facility location mismatch: {project_id}")
            _require(completed.definition_id == recipe.facility_def_id, f"completed facility definition mismatch: {project_id}")
            if isinstance(project.target, FacilityUpgradeTarget):
                _require(project.completed_facility_id == project.target.facility_id, f"upgrade completed wrong facility: {project_id}")
        else:
            _require(project.completed_facility_id is None, f"incomplete project has completed facility: {project_id}")
        expected_resources = {requirement.resource_id for requirement in recipe.resources}
        _require(set(project.resources) == expected_resources, f"project resource state mismatch: {project_id}")
        for resource_id, state in project.resources.items():
            _require(state.committed_t >= -1e-9, f"negative project resource accounting: {project_id}/{resource_id}")
            if state.import_committed_t is not None:
                _require(state.import_committed_t >= -1e-9, f"negative project import commitment: {project_id}/{resource_id}")


DOMAIN_EXTENSION = DomainExtension(
    "construction",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)

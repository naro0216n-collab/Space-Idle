from __future__ import annotations

from typing import Any

from ..domain import DomainExtension, StateCodec
from ..validation_support import ValidationContext, require as _require, validate_site_requirements as _validate_site_requirements
from ..shared import CelestialBodyId, DefinitionId, EntityId, ProjectId, SpatialNodeId, SurfaceCellId
from .models import (
    ConstructionProject,
    FacilityUpgradeTarget,
    LocationFoundingTarget,
    NewFacilityTarget,
    ProjectResourceState,
    ProjectStatus,
    SurfaceCellDevelopmentTarget,
)


def _capture_target(target) -> dict[str, Any]:
    if isinstance(target, NewFacilityTarget):
        return {"kind": "new_facility", "facility_def_id": str(target.facility_def_id)}
    if isinstance(target, FacilityUpgradeTarget):
        return {"kind": "facility_upgrade", "facility_id": str(target.facility_id), "target_level": target.target_level}
    if isinstance(target, LocationFoundingTarget):
        return {
            "kind": "location_founding",
            "recipe_id": str(target.recipe_id),
            "new_location_id": str(target.new_location_id),
            "display_name": target.display_name,
            "body_id": str(target.body_id),
            "core_cell_id": str(target.core_cell_id),
        }
    return {"kind": "surface_cell_development", "recipe_id": str(target.recipe_id), "cell_id": str(target.cell_id)}


def _restore_target(data: dict[str, Any]):
    kind = data["kind"]
    if kind == "new_facility":
        return NewFacilityTarget(DefinitionId(data["facility_def_id"]))
    if kind == "facility_upgrade":
        return FacilityUpgradeTarget(EntityId(data["facility_id"]), int(data["target_level"]))
    if kind == "location_founding":
        return LocationFoundingTarget(
            DefinitionId(data["recipe_id"]),
            SpatialNodeId(data["new_location_id"]),
            str(data["display_name"]),
            CelestialBodyId(data["body_id"]),
            SurfaceCellId(data["core_cell_id"]),
        )
    if kind == "surface_cell_development":
        return SurfaceCellDevelopmentTarget(DefinitionId(data["recipe_id"]), SurfaceCellId(data["cell_id"]))
    raise ValueError(f"unknown construction target kind: {kind}")


def capture_projects(sim: Any) -> dict[str, Any]:
    return {
        "counter": sim.projects._counter,
        "items": [
            {
                "id": str(project.id),
                "target": _capture_target(project.target),
                "location_id": str(project.location_id),
                "site_cell_id": None if project.site_cell_id is None else str(project.site_cell_id),
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
                    {"resource_id": str(resource_id), "committed_t": state.committed_t, "import_committed_t": state.import_committed_t}
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
            site_cell_id=None if row["site_cell_id"] is None else SurfaceCellId(row["site_cell_id"]),
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
    recipes = tuple(sim.projects.recipes.values()) + tuple(sim.projects.upgrade_recipes.values()) + tuple(sim.projects.spatial_recipes.values())
    for recipe in recipes:
        result.update(requirement.resource_id for requirement in recipe.resources)
    return result


STATE_CODEC = StateCodec("projects", capture_projects, restore_projects)


def _validate_physical_recipe(recipe, owner: str, ctx: ValidationContext) -> None:
    _require(recipe.construction_work >= 0, f"negative construction work: {owner}")
    _require(recipe.prerequisite_technologies.issubset(ctx.known_technologies), f"construction references unknown technology: {owner}")
    _validate_site_requirements(recipe.site_requirements, ctx.known_capabilities, owner)
    resource_ids: set[DefinitionId] = set()
    for requirement in recipe.resources:
        _require(requirement.resource_id not in resource_ids, f"duplicate construction resource: {owner}/{requirement.resource_id}")
        resource_ids.add(requirement.resource_id)
        _require(requirement.amount_t > 0, f"non-positive construction resource amount: {owner}/{requirement.resource_id}")
    _require(2 <= len(recipe.resources) <= 3, f"construction recipe must use 2-3 physical resources: {owner}")


def _validate_facility_recipe(recipe, owner: str, ctx: ValidationContext) -> None:
    _require(recipe.facility_def_id in ctx.facility_defs, f"construction recipe references unknown facility: {owner}")
    _validate_physical_recipe(recipe, owner, ctx)


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    for facility_id, recipe in sim.projects.recipes.items():
        _require(facility_id == recipe.facility_def_id, f"construction recipe key mismatch: {facility_id}")
        _validate_facility_recipe(recipe, f"construction:{facility_id}", ctx)
    seen_upgrade_targets: set[tuple[DefinitionId, int]] = set()
    for key, recipe in sim.projects.upgrade_recipes.items():
        expected = (recipe.facility_def_id, recipe.target_level)
        _require(key == expected, f"upgrade recipe key mismatch: {key}")
        _require(recipe.target_level >= 2, f"invalid upgrade target level: {expected}")
        _require(not recipe.self_deploying, f"facility upgrade cannot self-deploy: {expected}")
        _require(expected not in seen_upgrade_targets, f"duplicate facility upgrade recipe: {expected}")
        seen_upgrade_targets.add(expected)
        _validate_facility_recipe(recipe, f"construction_upgrade:{recipe.facility_def_id}:L{recipe.target_level}", ctx)
    for recipe_id, recipe in sim.projects.spatial_recipes.items():
        _require(recipe_id == recipe.id, f"spatial development recipe key mismatch: {recipe_id}")
        _require(not recipe.self_deploying, f"spatial development must use construction capacity: {recipe_id}")
        _validate_physical_recipe(recipe, f"spatial_development:{recipe_id}", ctx)
    if sim.projects.location_founding_recipe_id is not None:
        _require(sim.projects.location_founding_recipe_id in sim.projects.spatial_recipes, "unknown location founding recipe")
    if sim.projects.surface_cell_development_recipe_id is not None:
        _require(sim.projects.surface_cell_development_recipe_id in sim.projects.spatial_recipes, "unknown surface cell development recipe")
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
    active_spatial_cells: set[SurfaceCellId] = set()
    active_new_location_ids: set[SpatialNodeId] = set()
    for project_id, project in sim.projects.projects.items():
        _require(sim.graph.has_operational_node(project.location_id), f"project references unknown host location: {project_id}")
        if project.import_source_id is not None:
            _require(sim.graph.has_operational_node(project.import_source_id), f"project import source is unknown: {project_id}")
            _require(project.import_source_id != project.location_id, f"project import source equals destination: {project_id}")
        target = project.target
        if isinstance(target, NewFacilityTarget):
            _require(target.facility_def_id in sim.projects.recipes, f"project references unknown build recipe: {project_id}")
            recipe = sim.projects.recipes[target.facility_def_id]
            _require(not sim.facilities.placement_failures(target.facility_def_id, project.location_id, project.site_cell_id), f"project has invalid facility placement: {project_id}")
        elif isinstance(target, FacilityUpgradeTarget):
            _require(project.site_cell_id is None, f"upgrade project duplicates facility site cell: {project_id}")
            _require(target.facility_id in sim.facilities.facilities, f"upgrade project references unknown facility: {project_id}")
            facility = sim.facilities.facilities[target.facility_id]
            _require(facility.location_id == project.location_id, f"upgrade project location mismatch: {project_id}")
            key = (facility.definition_id, target.target_level)
            _require(key in sim.projects.upgrade_recipes, f"upgrade project references unknown recipe: {project_id}")
            recipe = sim.projects.upgrade_recipes[key]
            if project.status not in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
                _require(target.facility_id not in active_upgrade_targets, f"duplicate active facility upgrade: {target.facility_id}")
                active_upgrade_targets.add(target.facility_id)
                _require(facility.level == target.target_level - 1, f"active upgrade target level mismatch: {project_id}")
            if project.status is ProjectStatus.COMPLETE:
                _require(facility.level == target.target_level, f"completed upgrade did not apply target level: {project_id}")
        elif isinstance(target, LocationFoundingTarget):
            _require(project.site_cell_id is None, f"location founding duplicates target cell: {project_id}")
            _require(target.recipe_id in sim.projects.spatial_recipes, f"founding project references unknown recipe: {project_id}")
            recipe = sim.projects.spatial_recipes[target.recipe_id]
            _require(target.core_cell_id in sim.graph.surface_cells, f"founding project references unknown cell: {project_id}")
            _require(sim.graph.surface_cells[target.core_cell_id].body_id == target.body_id, f"founding project body mismatch: {project_id}")
            _require(sim.graph.operational_node(project.location_id).body_id == target.body_id, f"founding construction host body mismatch: {project_id}")
            if project.status not in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
                _require(target.core_cell_id not in active_spatial_cells, f"duplicate active spatial target cell: {target.core_cell_id}")
                _require(target.new_location_id not in active_new_location_ids, f"duplicate active new location id: {target.new_location_id}")
                active_spatial_cells.add(target.core_cell_id)
                active_new_location_ids.add(target.new_location_id)
                _require(target.new_location_id not in sim.graph.locations and target.new_location_id not in sim.graph.nodes, f"active founding target already exists: {project_id}")
            if project.status is ProjectStatus.COMPLETE:
                _require(target.new_location_id in sim.graph.locations, f"completed founding project did not create location: {project_id}")
                location = sim.graph.locations[target.new_location_id]
                _require(location.body_id == target.body_id and location.core_cell_id == target.core_cell_id, f"completed founding location mismatch: {project_id}")
        else:
            _require(project.site_cell_id is None, f"surface development duplicates target cell: {project_id}")
            _require(target.recipe_id in sim.projects.spatial_recipes, f"development project references unknown recipe: {project_id}")
            recipe = sim.projects.spatial_recipes[target.recipe_id]
            _require(project.location_id in sim.graph.locations, f"surface development host is not a surface location: {project_id}")
            _require(target.cell_id in sim.graph.surface_cells, f"surface development references unknown cell: {project_id}")
            if project.status not in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
                _require(target.cell_id not in active_spatial_cells, f"duplicate active spatial target cell: {target.cell_id}")
                active_spatial_cells.add(target.cell_id)
            if project.status is ProjectStatus.COMPLETE:
                _require(target.cell_id in sim.graph.locations[project.location_id].developed_cell_ids, f"completed development project did not attach cell: {project_id}")

        _require(-1e-9 <= project.construction_done <= recipe.construction_work + 1e-8, f"invalid construction progress: {project_id}")
        _require(project.construction_weight >= 0, f"negative construction allocation: {project_id}")
        _require(not project.paused or project.pause_started_day is not None, f"paused project missing pause day: {project_id}")
        _require(project.paused or project.pause_started_day is None, f"active project retains pause day: {project_id}")
        if project.materials_committed:
            _require(project.status in {ProjectStatus.BUILDING, ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}, f"materials committed before construction: {project_id}")
            _require(not any(owner == EntityId(project.id) for owner, _location, _resource in sim.inventory.reserved), f"committed project retains inventory reservation: {project_id}")
        if isinstance(target, (NewFacilityTarget, FacilityUpgradeTarget)):
            if project.status is ProjectStatus.COMPLETE:
                _require(project.completed_facility_id in sim.facilities.facilities, f"complete project lacks affected facility: {project_id}")
                completed = sim.facilities.facilities[project.completed_facility_id]
                _require(completed.location_id == project.location_id, f"completed facility location mismatch: {project_id}")
                _require(completed.definition_id == recipe.facility_def_id, f"completed facility definition mismatch: {project_id}")
                if isinstance(target, NewFacilityTarget):
                    _require(completed.site_cell_id == project.site_cell_id, f"completed facility site mismatch: {project_id}")
                else:
                    _require(project.completed_facility_id == target.facility_id, f"upgrade completed wrong facility: {project_id}")
            else:
                _require(project.completed_facility_id is None, f"incomplete project has completed facility: {project_id}")
        else:
            _require(project.completed_facility_id is None, f"spatial project must not own a completed facility: {project_id}")
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

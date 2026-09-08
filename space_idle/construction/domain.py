from __future__ import annotations

from typing import Any

from ..domain import DomainExtension, StateCodec
from ..validation_support import ValidationContext, require as _require, validate_site_requirements as _validate_site_requirements
from ..shared import CargoOrderId, DefinitionId, EntityId, ProjectId, RouteId, SpatialNodeId
from .models import BuildProject, ProjectComponentState, ProjectStatus


def capture_projects(sim: Any) -> dict[str, Any]:
    return {
        "counter": sim.projects._counter,
        "items": [
            {
                "id": str(p.id), "facility_def_id": str(p.facility_def_id), "location_id": str(p.location_id),
                "priority": p.priority, "sourcing_policy": p.sourcing_policy,
                "import_source_id": None if p.import_source_id is None else str(p.import_source_id),
                "import_path": None if p.import_path is None else [str(x) for x in p.import_path],
                "import_mode_by_route": {str(k): v for k, v in sorted(p.import_mode_by_route.items(), key=lambda row: str(row[0]))},
                "status": p.status.value, "procurement_started_day": p.procurement_started_day,
                "construction_done": p.construction_done, "construction_weight": p.construction_weight,
                "paused": p.paused, "pause_started_day": p.pause_started_day,
                "installed_facility_id": None if p.installed_facility_id is None else str(p.installed_facility_id),
                "local_fraction_targets": dict(sorted(p.local_fraction_targets.items())),
                "local_resource_choices": {k: str(v) for k, v in sorted(p.local_resource_choices.items())},
                "materials_committed": p.materials_committed,
                "components": [
                    {
                        "component_id": cid, "reserved_local_t": c.reserved_local_t,
                        "reserved_local_resource_id": None if c.reserved_local_resource_id is None else str(c.reserved_local_resource_id),
                        "reserved_import_t": c.reserved_import_t, "committed_local_t": c.committed_local_t,
                        "committed_local_resource_id": None if c.committed_local_resource_id is None else str(c.committed_local_resource_id),
                        "committed_import_t": c.committed_import_t, "local_target_t": c.local_target_t,
                        "import_committed_t": c.import_committed_t,
                        "import_order_id": None if c.import_order_id is None else str(c.import_order_id),
                    }
                    for cid, c in sorted(p.components.items())
                ],
            }
            for p in sorted(sim.projects.projects.values(), key=lambda row: str(row.id))
        ],
    }


def restore_projects(sim: Any, data: dict[str, Any]) -> None:
    sim.projects._counter = int(data["counter"])
    sim.projects.projects.clear()
    for r in data["items"]:
        pid = ProjectId(r["id"])
        components: dict[str, ProjectComponentState] = {}
        for c in r["components"]:
            components[c["component_id"]] = ProjectComponentState(
                float(c["reserved_local_t"]),
                None if c["reserved_local_resource_id"] is None else DefinitionId(c["reserved_local_resource_id"]),
                float(c["reserved_import_t"]), float(c["committed_local_t"]),
                None if c["committed_local_resource_id"] is None else DefinitionId(c["committed_local_resource_id"]),
                float(c["committed_import_t"]), float(c["local_target_t"]),
                None if c["import_committed_t"] is None else float(c["import_committed_t"]),
                None if c["import_order_id"] is None else CargoOrderId(c["import_order_id"]),
            )
        sim.projects.projects[pid] = BuildProject(
            pid, DefinitionId(r["facility_def_id"]), SpatialNodeId(r["location_id"]), int(r["priority"]),
            r["sourcing_policy"], None if r["import_source_id"] is None else SpatialNodeId(r["import_source_id"]),
            None if r.get("import_path") is None else tuple(RouteId(x) for x in r["import_path"]),
            {RouteId(k): v for k, v in r.get("import_mode_by_route", {}).items()}, ProjectStatus(r["status"]),
            r["procurement_started_day"], float(r["construction_done"]), float(r["construction_weight"]),
            bool(r["paused"]), None if r["pause_started_day"] is None else int(r["pause_started_day"]),
            components, {k: float(v) for k, v in r.get("local_fraction_targets", {}).items()},
            {k: DefinitionId(v) for k, v in r.get("local_resource_choices", {}).items()},
            bool(r["materials_committed"]),
            None if r["installed_facility_id"] is None else EntityId(r["installed_facility_id"]),
        )


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set(sim.projects.construction_resource_providers)
    for recipe in sim.projects.recipes.values():
        for component in recipe.components:
            result.add(component.import_resource_id)
            result.update(tier.local_resource_id for tier in component.local_tiers)
    return result


STATE_CODEC = StateCodec("projects", capture_projects, restore_projects)
def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    facility_defs = ctx.facility_defs
    known_capabilities = ctx.known_capabilities
    known_technologies = ctx.known_technologies
    for facility_id, recipe in sim.projects.recipes.items():
        _require(facility_id == recipe.facility_def_id, f"construction recipe key mismatch: {facility_id}")
        _require(facility_id in facility_defs, f"construction recipe references unknown facility: {facility_id}")
        _require(recipe.construction_work >= 0, f"negative construction work: {facility_id}")
        _require(recipe.prerequisite_technologies.issubset(known_technologies), f"construction references unknown technology: {facility_id}")
        _validate_site_requirements(recipe.site_requirements, known_capabilities, f"construction:{facility_id}")
        component_ids: set[str] = set()
        for component in recipe.components:
            _require(component.component_id not in component_ids, f"duplicate build component: {facility_id}/{component.component_id}")
            component_ids.add(component.component_id)
            _require(component.amount_t >= 0, f"negative component mass: {facility_id}/{component.component_id}")
            seen_local_resources: set[object] = set()
            for tier in component.local_tiers:
                _require(0 <= tier.max_fraction <= 1, f"local substitution outside 0..1: {facility_id}/{component.component_id}")
                _require(tier.local_resource_id not in seen_local_resources,
                         f"duplicate local substitution resource: {facility_id}/{component.component_id}/{tier.local_resource_id}")
                seen_local_resources.add(tier.local_resource_id)
    _require(set(sim.projects.sourcing_wait_days) == {"import_now", "mixed", "local_priority"}, "invalid sourcing policy configuration")
    _require(all(days >= 0 for days in sim.projects.sourcing_wait_days.values()), "negative sourcing wait period")
    for definition_id, spec in sim.projects.construction_providers.items():
        _require(definition_id == spec.facility_def_id, f"construction provider key mismatch: {definition_id}")
        _require(definition_id in facility_defs, f"construction provider references unknown facility: {definition_id}")
        _require(spec.work_per_day >= 0, f"negative construction capacity: {definition_id}")
    for resource_id, spec in sim.projects.construction_resource_providers.items():
        _require(resource_id == spec.resource_id, f"construction resource provider key mismatch: {resource_id}")
        _require(spec.work_per_t_per_day >= 0, f"negative construction resource productivity: {spec.resource_id}")


def validate_runtime(sim: Any) -> None:
    for project_id, project in sim.projects.projects.items():
        _require(project.facility_def_id in sim.projects.recipes, f"project references unknown recipe: {project_id}")
        _require(project.location_id in sim.graph.nodes, f"project references unknown location: {project_id}")
        if project.import_path is None:
            _require(not project.import_mode_by_route, f"automatic project import path retains explicit modes: {project_id}")
        else:
            _require(project.import_source_id is not None, f"explicit project import path lacks source: {project_id}")
            sim.logistics.validate_path_structure(project.import_source_id, project.location_id, project.import_path)
            sim.logistics.validate_mode_selection(project.import_path, project.import_mode_by_route)
        recipe = sim.projects.recipes[project.facility_def_id]
        _require(-1e-9 <= project.construction_done <= recipe.construction_work + 1e-8, f"invalid construction progress: {project_id}")
        _require(project.construction_weight >= 0, f"negative construction allocation: {project_id}")
        _require(not project.paused or project.pause_started_day is not None, f"paused project missing pause day: {project_id}")
        _require(project.paused or project.pause_started_day is None, f"active project retains pause day: {project_id}")
        if project.materials_committed:
            _require(project.status in {ProjectStatus.BUILDING, ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}, f"materials committed before construction: {project_id}")
            _require(not any(owner == EntityId(project.id) for owner, _loc, _res in sim.inventory.reserved),
                     f"committed project retains inventory reservation: {project_id}")
        if project.status is ProjectStatus.COMPLETE:
            _require(project.installed_facility_id in sim.facilities.facilities, f"complete project lacks installed facility: {project_id}")
            installed = sim.facilities.facilities[project.installed_facility_id]
            _require(installed.definition_id == project.facility_def_id and installed.location_id == project.location_id,
                     f"installed facility mismatch: {project_id}")
        expected_components = {component.component_id for component in recipe.components}
        _require(set(project.components) == expected_components, f"project component state mismatch: {project_id}")
        _require(set(project.local_resource_choices).issubset(expected_components), f"project local material choice references unknown component: {project_id}")
        for component_id, resource_id in project.local_resource_choices.items():
            requirement = next(c for c in recipe.components if c.component_id == component_id)
            _require(resource_id in {tier.local_resource_id for tier in requirement.local_tiers},
                     f"invalid project local material choice: {project_id}/{component_id}/{resource_id}")
        expected_reservations: dict[object, float] = {}
        for component_id, state in project.components.items():
            _require(state.reserved_local_t >= -1e-9, f"negative local reservation: {project_id}/{component_id}")
            _require(state.reserved_import_t >= -1e-9, f"negative import reservation: {project_id}/{component_id}")
            _require(state.committed_local_t >= -1e-9, f"negative committed local material: {project_id}/{component_id}")
            _require(state.committed_import_t >= -1e-9, f"negative committed imported material: {project_id}/{component_id}")
            _require(state.local_target_t >= -1e-9, f"negative local target: {project_id}/{component_id}")
            _require(state.reserved_local_t + state.reserved_import_t + state.committed_local_t + state.committed_import_t
                     <= next(c.amount_t for c in recipe.components if c.component_id == component_id) + 1e-8,
                     f"project component allocation exceeds requirement: {project_id}/{component_id}")
            if state.import_committed_t is not None:
                _require(state.import_committed_t >= -1e-9, f"negative import commitment: {project_id}/{component_id}")
            if state.import_order_id is not None:
                _require(state.import_committed_t is not None and state.import_committed_t > 1e-9,
                         f"project import order lacks commitment: {project_id}/{component_id}")
                _require(state.import_order_id in sim.logistics.orders, f"project references unknown import order: {project_id}/{component_id}")
                order = sim.logistics.orders[state.import_order_id]
                requirement = next(c for c in recipe.components if c.component_id == component_id)
                _require(project.import_source_id is not None, f"project import order lacks source: {project_id}/{component_id}")
                _require(order.owner_kind == "project" and order.owner_id == EntityId(project.id), f"project import order owner mismatch: {project_id}/{component_id}")
                _require(order.source_id == project.import_source_id and order.destination_id == project.location_id,
                         f"project import order endpoint mismatch: {project_id}/{component_id}")
                _require(order.resource_id == requirement.import_resource_id, f"project import order resource mismatch: {project_id}/{component_id}")
                _require(abs(order.amount_t - state.import_committed_t) <= 1e-7, f"project import order amount mismatch: {project_id}/{component_id}")
                if project.import_path is not None:
                    _require(order.path == project.import_path, f"project import order path mismatch: {project_id}/{component_id}")
                    _require(order.mode_by_route == project.import_mode_by_route, f"project import order transport mode mismatch: {project_id}/{component_id}")
            if not project.materials_committed and project.status is not ProjectStatus.CANCELLED:
                if state.reserved_local_t > 1e-12:
                    _require(state.reserved_local_resource_id is not None, f"local reservation lacks resource: {project_id}/{component_id}")
                    expected_reservations[state.reserved_local_resource_id] = expected_reservations.get(state.reserved_local_resource_id, 0.0) + state.reserved_local_t
                requirement = next(c for c in recipe.components if c.component_id == component_id)
                if state.reserved_import_t > 1e-12:
                    expected_reservations[requirement.import_resource_id] = expected_reservations.get(requirement.import_resource_id, 0.0) + state.reserved_import_t
        owner = EntityId(project.id)
        actual_reservations = {
            resource_id: amount
            for (reservation_owner, location_id, resource_id), amount in sim.inventory.reserved.items()
            if reservation_owner == owner and location_id == project.location_id and amount > 1e-12
        }
        _require(set(actual_reservations) == set(expected_reservations), f"project reservation resources mismatch: {project_id}")
        for resource_id, expected in expected_reservations.items():
            _require(abs(actual_reservations.get(resource_id, 0.0) - expected) <= 1e-7,
                     f"project reservation amount mismatch: {project_id}/{resource_id}")


DOMAIN_EXTENSION = DomainExtension(
    "construction", state_codec=STATE_CODEC, configuration_validator=validate_configuration,
    runtime_validator=validate_runtime, referenced_resources=referenced_resources,
)

from __future__ import annotations

from ..power import PowerSnapshot
from ..shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from ..site import SiteRequirementFailure, SiteRequirements, evaluate_site_requirements
from .models import (
    ConstructionProject,
    FacilityUpgradeRecipe,
    FacilityUpgradeTarget,
    LocationFoundingTarget,
    NewFacilityTarget,
    ProjectRecipe,
    SurfaceCellDevelopmentTarget,
)


class ConstructionRulesMixin:
    def target_facility_definition_id(self, project: ConstructionProject) -> DefinitionId | None:
        return self._target_facility_def_id(project)

    def recipe_for_project(self, project: ConstructionProject) -> ProjectRecipe:
        return self._recipe_for_project(project)

    def _target_facility_def_id(self, project: ConstructionProject) -> DefinitionId | None:
        target = project.target
        if isinstance(target, NewFacilityTarget):
            return target.facility_def_id
        if isinstance(target, FacilityUpgradeTarget):
            facility = self.facilities.facilities.get(target.facility_id)
            if facility is None:
                raise KeyError(target.facility_id)
            return facility.definition_id
        return None

    def _recipe_for_project(self, project: ConstructionProject) -> ProjectRecipe:
        target = project.target
        if isinstance(target, NewFacilityTarget):
            return self.recipes[target.facility_def_id]
        if isinstance(target, FacilityUpgradeTarget):
            facility = self.facilities.facilities.get(target.facility_id)
            if facility is None:
                raise KeyError(target.facility_id)
            return self.upgrade_recipes[(facility.definition_id, target.target_level)]
        return self.spatial_recipes[target.recipe_id]

    def next_upgrade_recipe(self, facility_id: EntityId) -> FacilityUpgradeRecipe | None:
        facility = self.facilities.facilities[facility_id]
        return self.upgrade_recipes.get((facility.definition_id, facility.level + 1))

    def _facility_site_failures_for_recipe(
        self,
        recipe: ProjectRecipe,
        location_id: SpatialNodeId,
        day: int = 0,
        power: PowerSnapshot | None = None,
        *,
        site_cell_id: SurfaceCellId | None = None,
        existing_facility_id: EntityId | None = None,
    ):
        facility_def_id = self._recipe_facility_def_id(recipe)
        definition = self.facilities.definitions[facility_def_id]
        if existing_facility_id is None:
            placement = self.facilities.placement_failures(facility_def_id, location_id, site_cell_id)
            if placement:
                return tuple(SiteRequirementFailure(code, detail) for code, detail in placement)
            environment_context = self.facilities.placement_context(facility_def_id, location_id, site_cell_id)
        else:
            facility = self.facilities.facilities[existing_facility_id]
            environment_context = self.facilities.facility_environment_context(facility)
        snapshot = power if power is not None else self.power.snapshot(location_id, self.facilities, day)
        failures = list(evaluate_site_requirements(
            SiteRequirements(environment=definition.installation_environment),
            location_id, day, self.facilities.environment, self.facilities, snapshot,
            environment_context_id=environment_context,
        ))
        failures.extend(evaluate_site_requirements(
            recipe.site_requirements, location_id, day, self.facilities.environment, self.facilities, snapshot,
            environment_context_id=environment_context,
        ))
        return tuple(dict.fromkeys(failures))

    @staticmethod
    def _recipe_facility_def_id(recipe: ProjectRecipe) -> DefinitionId:
        if hasattr(recipe, "facility_def_id"):
            return recipe.facility_def_id  # type: ignore[return-value]
        raise TypeError("spatial development recipe has no facility definition")

    def _spatial_target_cell(self, project: ConstructionProject) -> SurfaceCellId | None:
        target = project.target
        if isinstance(target, LocationFoundingTarget):
            return target.core_cell_id
        if isinstance(target, SurfaceCellDevelopmentTarget):
            return target.cell_id
        return None

    def active_spatial_project_for_cell(self, cell_id: SurfaceCellId):
        from .models import ProjectStatus
        for project in sorted(self.projects.values(), key=lambda row: str(row.id)):
            if project.status in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
                continue
            target_cell = self._spatial_target_cell(project)
            if target_cell == cell_id:
                return project
        return None

    def _spatial_recipe_site_failures(
        self, recipe_id: DefinitionId, location_id: SpatialNodeId, cell_id: SurfaceCellId,
        day: int = 0, power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        recipe = self.spatial_recipes[recipe_id]
        snapshot = power if power is not None else self.power.snapshot(location_id, self.facilities, day)
        return evaluate_site_requirements(
            recipe.site_requirements, location_id, day, self.facilities.environment, self.facilities, snapshot,
            environment_context_id=cell_id,
        )

    def location_founding_failures(
        self, provider_location_id: SpatialNodeId, body_id, cell_id: SurfaceCellId,
        day: int = 0, power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        recipe_id = self.location_founding_recipe_id
        if recipe_id is None or recipe_id not in self.spatial_recipes:
            return (SiteRequirementFailure("construction_recipe", "location founding recipe is not configured"),)
        graph = self.facilities.environment.graph
        failures = [SiteRequirementFailure(code, detail) for code, detail in graph.location_foundation_failures(body_id, cell_id)]
        if not graph.has_operational_node(provider_location_id):
            failures.append(SiteRequirementFailure("construction_host", str(provider_location_id)))
            return tuple(failures)
        host_body = graph.operational_node(provider_location_id).body_id
        if host_body != body_id:
            failures.append(SiteRequirementFailure("construction_host_body", f"host={host_body}, target={body_id}"))
        active = self.active_spatial_project_for_cell(cell_id)
        if active is not None:
            failures.append(SiteRequirementFailure("active_spatial_project", str(active.id)))
        failures.extend(self._spatial_recipe_site_failures(recipe_id, provider_location_id, cell_id, day, power))
        return tuple(dict.fromkeys(failures))

    def surface_cell_development_failures(
        self, location_id: SpatialNodeId, cell_id: SurfaceCellId,
        day: int = 0, power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        recipe_id = self.surface_cell_development_recipe_id
        if recipe_id is None or recipe_id not in self.spatial_recipes:
            return (SiteRequirementFailure("construction_recipe", "surface cell development recipe is not configured"),)
        graph = self.facilities.environment.graph
        failures = [SiteRequirementFailure(code, detail) for code, detail in graph.surface_cell_development_failures(location_id, cell_id)]
        active = self.active_spatial_project_for_cell(cell_id)
        if active is not None:
            failures.append(SiteRequirementFailure("active_spatial_project", str(active.id)))
        if graph.has_operational_node(location_id):
            failures.extend(self._spatial_recipe_site_failures(recipe_id, location_id, cell_id, day, power))
        return tuple(dict.fromkeys(failures))

    def spatial_project_failures(
        self,
        project: ConstructionProject,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        target = project.target
        if not isinstance(target, (LocationFoundingTarget, SurfaceCellDevelopmentTarget)):
            raise TypeError("project is not a spatial development project")
        graph = self.facilities.environment.graph
        failures: list[SiteRequirementFailure] = []
        if isinstance(target, LocationFoundingTarget):
            host_body = graph.operational_node(project.location_id).body_id
            if host_body != target.body_id:
                failures.append(SiteRequirementFailure(
                    "construction_host_body",
                    f"host={host_body}, target={target.body_id}",
                ))
            failures.extend(
                SiteRequirementFailure(code, detail)
                for code, detail in graph.location_foundation_failures(target.body_id, target.core_cell_id)
            )
            if target.new_location_id in graph.locations or target.new_location_id in graph.nodes:
                failures.append(SiteRequirementFailure("location_id_in_use", str(target.new_location_id)))
            environment_context = target.core_cell_id
        else:
            failures.extend(
                SiteRequirementFailure(code, detail)
                for code, detail in graph.surface_cell_development_failures(project.location_id, target.cell_id)
            )
            environment_context = target.cell_id
        snapshot = power if power is not None else self.power.snapshot(project.location_id, self.facilities, day)
        failures.extend(evaluate_site_requirements(
            self._recipe_for_project(project).site_requirements,
            project.location_id,
            day,
            self.facilities.environment,
            self.facilities,
            snapshot,
            environment_context_id=environment_context,
        ))
        return tuple(dict.fromkeys(failures))

    def site_failures(
        self,
        facility_def_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
        power: PowerSnapshot | None = None,
        *,
        site_cell_id: SurfaceCellId | None = None,
    ):
        return self._facility_site_failures_for_recipe(
            self.recipes[facility_def_id], location_id, day, power, site_cell_id=site_cell_id
        )

    def upgrade_site_failures(
        self,
        facility_id: EntityId,
        target_level: int,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ):
        facility = self.facilities.facilities[facility_id]
        recipe = self.upgrade_recipes[(facility.definition_id, target_level)]
        return self._facility_site_failures_for_recipe(
            recipe, facility.location_id, day, power, existing_facility_id=facility_id
        )

    def project_site_failures(
        self, project: ConstructionProject, day: int = 0, power: PowerSnapshot | None = None
    ):
        if isinstance(project.target, FacilityUpgradeTarget):
            return self._facility_site_failures_for_recipe(
                self._recipe_for_project(project), project.location_id, day, power,
                existing_facility_id=project.target.facility_id,
            )
        if isinstance(project.target, NewFacilityTarget):
            return self._facility_site_failures_for_recipe(
                self._recipe_for_project(project), project.location_id, day, power,
                site_cell_id=project.site_cell_id,
            )
        return self.spatial_project_failures(project, day, power)

    def construction_capacity_at(self, location_id: SpatialNodeId, power: PowerSnapshot, day: int) -> float:
        capacity = 0.0
        for facility in self.facilities.active_compatible_at(location_id, day):
            spec = self.construction_providers.get(facility.definition_id)
            if spec is None:
                continue
            utilization = power.utilization_by_facility.get(facility.id, 1.0)
            maintenance = power.maintenance_factor_by_facility.get(
                facility.id, self.facilities.maintenance_factor(facility.id)
            )
            capacity += spec.work_per_day * utilization * maintenance
        for resource_id, spec in self.construction_resource_providers.items():
            capacity += self.inventory.available(location_id, resource_id) * spec.work_per_t_per_day
        return capacity

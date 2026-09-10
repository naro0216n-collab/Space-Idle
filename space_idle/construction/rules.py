from __future__ import annotations

from ..power import PowerSnapshot
from ..shared import DefinitionId, EntityId, SpatialNodeId
from ..site import SiteRequirements, evaluate_site_requirements
from .models import (
    ConstructionProject,
    FacilityUpgradeRecipe,
    FacilityUpgradeTarget,
    NewFacilityTarget,
    ProjectRecipe,
)


class ConstructionRulesMixin:
    def target_facility_definition_id(self, project: ConstructionProject) -> DefinitionId:
        return self._target_facility_def_id(project)

    def recipe_for_project(self, project: ConstructionProject) -> ProjectRecipe:
        return self._recipe_for_project(project)

    def _target_facility_def_id(self, project: ConstructionProject) -> DefinitionId:
        target = project.target
        if isinstance(target, NewFacilityTarget):
            return target.facility_def_id
        facility = self.facilities.facilities.get(target.facility_id)
        if facility is None:
            raise KeyError(target.facility_id)
        return facility.definition_id

    def _recipe_for_project(self, project: ConstructionProject) -> ProjectRecipe:
        target = project.target
        if isinstance(target, NewFacilityTarget):
            return self.recipes[target.facility_def_id]
        facility = self.facilities.facilities.get(target.facility_id)
        if facility is None:
            raise KeyError(target.facility_id)
        return self.upgrade_recipes[(facility.definition_id, target.target_level)]

    def next_upgrade_recipe(self, facility_id: EntityId) -> FacilityUpgradeRecipe | None:
        facility = self.facilities.facilities[facility_id]
        return self.upgrade_recipes.get((facility.definition_id, facility.level + 1))

    def _site_failures_for_recipe(
        self,
        recipe: ProjectRecipe,
        location_id: SpatialNodeId,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ):
        definition = self.facilities.definitions[recipe.facility_def_id]
        snapshot = power if power is not None else self.power.snapshot(location_id, self.facilities, day)
        failures = list(evaluate_site_requirements(
            SiteRequirements(environment=definition.installation_environment),
            location_id, day, self.facilities.environment, self.facilities, snapshot,
        ))
        failures.extend(evaluate_site_requirements(
            recipe.site_requirements, location_id, day, self.facilities.environment, self.facilities, snapshot,
        ))
        return tuple(dict.fromkeys(failures))

    def site_failures(
        self,
        facility_def_id: DefinitionId,
        location_id: SpatialNodeId,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ):
        return self._site_failures_for_recipe(self.recipes[facility_def_id], location_id, day, power)

    def upgrade_site_failures(
        self,
        facility_id: EntityId,
        target_level: int,
        day: int = 0,
        power: PowerSnapshot | None = None,
    ):
        facility = self.facilities.facilities[facility_id]
        recipe = self.upgrade_recipes[(facility.definition_id, target_level)]
        return self._site_failures_for_recipe(recipe, facility.location_id, day, power)

    def project_site_failures(
        self, project: ConstructionProject, day: int = 0, power: PowerSnapshot | None = None
    ):
        return self._site_failures_for_recipe(self._recipe_for_project(project), project.location_id, day, power)

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

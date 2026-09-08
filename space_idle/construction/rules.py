from __future__ import annotations

from ..power import PowerSnapshot
from ..shared import DefinitionId, EntityId, SpatialNodeId
from ..site import SiteRequirements, evaluate_site_requirements
from .models import (
    BuildComponentRequirement,
    ConstructionProject,
    ConstructionRecipe,
    FacilityUpgradeRecipe,
    FacilityUpgradeTarget,
    NewFacilityTarget,
    ProjectRecipe,
)


class ConstructionRulesMixin:
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

    def _selected_local_target(
        self, project: ConstructionProject, component: BuildComponentRequirement, day: int
    ) -> tuple[DefinitionId | None, float]:
        if project.sourcing_policy == "import_now":
            return None, 0.0
        state = project.components[component.component_id]
        eligible = list(component.local_tiers)
        if state.reserved_local_resource_id is not None:
            same_resource = [tier for tier in eligible if tier.local_resource_id == state.reserved_local_resource_id]
            if not same_resource:
                return None, max(state.local_target_t, state.reserved_local_t)
            selected = max(same_resource, key=lambda tier: (tier.max_fraction, str(tier.local_resource_id)))
        else:
            if not eligible:
                return None, 0.0
            explicit_resource = project.local_resource_choices.get(component.component_id)
            if explicit_resource is not None:
                selected = next(tier for tier in eligible if tier.local_resource_id == explicit_resource)
            else:
                def score(tier) -> tuple[float, float, str]:
                    available = self.inventory.available(project.location_id, tier.local_resource_id)
                    stocked_fraction = min(tier.max_fraction, available / component.amount_t) if component.amount_t > 1e-12 else tier.max_fraction
                    return stocked_fraction, tier.max_fraction, str(tier.local_resource_id)
                selected = max(eligible, key=score)
        requested = project.local_fraction_targets.get(component.component_id, selected.max_fraction)
        fraction = min(selected.max_fraction, max(0.0, requested))
        return selected.local_resource_id, component.amount_t * fraction

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
            capacity += spec.work_per_day * utilization
        for resource_id, spec in self.construction_resource_providers.items():
            capacity += self.inventory.available(location_id, resource_id) * spec.work_per_t_per_day
        return capacity

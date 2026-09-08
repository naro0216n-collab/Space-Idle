from __future__ import annotations

from ..power import PowerSnapshot
from ..shared import DefinitionId, SpatialNodeId
from ..site import SiteRequirements, evaluate_site_requirements
from .models import BuildComponentRequirement, BuildProject


class ConstructionRulesMixin:
    def _selected_local_target(self, project: BuildProject, component: BuildComponentRequirement, day: int) -> tuple[DefinitionId | None, float]:
        if project.sourcing_policy == "import_now":
            return None, 0.0
        state = project.components[component.component_id]
        eligible = list(component.local_tiers)
        # Once material has actually been reserved, keep that material choice
        # stable until the player explicitly replans sourcing.
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
                # Automatic sourcing policies may choose a material, but the
                # player can override this per component. Prefer stock that can
                # satisfy the greatest share before considering substitution grade.
                def score(tier: LocalSubstitutionTier) -> tuple[float, float, str]:
                    available = self.inventory.available(project.location_id, tier.local_resource_id)
                    stocked_fraction = min(tier.max_fraction, available / component.amount_t) if component.amount_t > 1e-12 else tier.max_fraction
                    return stocked_fraction, tier.max_fraction, str(tier.local_resource_id)
                selected = max(eligible, key=score)
        requested = project.local_fraction_targets.get(component.component_id, selected.max_fraction)
        fraction = min(selected.max_fraction, max(0.0, requested))
        return selected.local_resource_id, component.amount_t * fraction

    def site_failures(
        self, facility_def_id: DefinitionId, location_id: SpatialNodeId, day: int = 0,
        power: PowerSnapshot | None = None,
        ):
        """Evaluate one authoritative site model for construction.

        A facility definition owns its intrinsic installation environment.
        Construction recipes add project-specific technology/infrastructure
        prerequisites. Operating environment is evaluated separately after the
        facility exists, so a currently inoperable facility may still be built
        in anticipation of later environmental change.
        """
        recipe = self.recipes[facility_def_id]
        definition = self.facilities.definitions[facility_def_id]
        snapshot = power if power is not None else self.power.snapshot(location_id, self.facilities, day)
        failures = list(evaluate_site_requirements(
            SiteRequirements(environment=definition.installation_environment),
            location_id, day, self.facilities.environment, self.facilities, snapshot,
        ))
        failures.extend(evaluate_site_requirements(
            recipe.site_requirements, location_id, day, self.facilities.environment, self.facilities, snapshot,
        ))
        # A condition may intentionally be shared by operation and construction
        # prerequisites. Do not expose duplicate blockers to the application.
        return tuple(dict.fromkeys(failures))

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


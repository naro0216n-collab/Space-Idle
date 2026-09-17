from __future__ import annotations

from ..execution_requirements import ExecutionAllocationPlan
from ..power import PowerSnapshot
from ..service_capacity import ServiceCapacityAllocationPlan, ServiceCapacityScope
from ..shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from ..spatial_claims import SurfaceCellClaim
from ..site import SiteRequirementFailure, SiteRequirements, evaluate_site_requirements
from .models import (
    CONSTRUCTION_SERVICE_TYPE,
    ConstructionProject,
    FacilityDecommissionTarget,
    FacilityUpgradeRecipe,
    FacilityUpgradeTarget,
    NewFacilityTarget,
    ProjectRecipe,
    ProjectStatus,
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
        if isinstance(target, FacilityDecommissionTarget):
            return target.facility_definition_id
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
        if isinstance(target, FacilityDecommissionTarget):
            return self.decommission_recipes[target.facility_definition_id]
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
        failures = list(evaluate_site_requirements(
            definition.installation_requirements,
            location_id, day, self.facilities.environment, self.facilities, power,
            environment_context_id=environment_context,
        ))
        failures.extend(evaluate_site_requirements(
            recipe.site_requirements, location_id, day, self.facilities.environment, self.facilities, power,
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
        if isinstance(target, SurfaceCellDevelopmentTarget):
            return target.cell_id
        return None

    def surface_cell_claims(self) -> tuple[SurfaceCellClaim, ...]:
        return tuple(
            SurfaceCellClaim(
                target_cell,
                "construction_project",
                EntityId(project.id),
                "surface_cell_development",
            )
            for project in sorted(self.projects.values(), key=lambda row: str(row.id))
            if project.status not in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}
            if (target_cell := self._spatial_target_cell(project)) is not None
        )

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
        failures = list(evaluate_site_requirements(
            recipe.site_requirements, location_id, day, self.facilities.environment, self.facilities, power,
            environment_context_id=cell_id,
        ))
        required_level = recipe.minimum_survey_knowledge_level
        if required_level > 0:
            provider = self.surface_knowledge_level_provider
            actual_level = 0 if provider is None else provider(cell_id)
            if actual_level < required_level:
                failures.append(SiteRequirementFailure(
                    "survey_knowledge", f"level={actual_level}/{required_level}"
                ))
        return tuple(failures)

    def surface_cell_development_failures(
        self, location_id: SpatialNodeId, cell_id: SurfaceCellId,
        day: int = 0, power: PowerSnapshot | None = None,
    ) -> tuple[SiteRequirementFailure, ...]:
        recipe_id = self.surface_cell_development_recipe_id
        if recipe_id is None or recipe_id not in self.spatial_recipes:
            return (SiteRequirementFailure("construction_recipe", "surface cell development recipe is not configured"),)
        graph = self.facilities.environment.graph
        failures = [SiteRequirementFailure(code, detail) for code, detail in graph.surface_cell_development_failures(location_id, cell_id)]
        for claim in self.surface_cell_claim_registry.claims_for(cell_id):
            failures.append(SiteRequirementFailure("cell_claimed", str(claim.claimant_id)))
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
        if not isinstance(target, SurfaceCellDevelopmentTarget):
            raise TypeError("project is not a surface development project")
        graph = self.facilities.environment.graph
        failures: list[SiteRequirementFailure] = [
            SiteRequirementFailure(code, detail)
            for code, detail in graph.surface_cell_development_failures(project.operational_node_id, target.cell_id)
        ]
        for claim in self.surface_cell_claim_registry.claims_for(
            target.cell_id,
            exclude=("construction_project", EntityId(project.id)),
        ):
            failures.append(SiteRequirementFailure("cell_claimed", str(claim.claimant_id)))
        failures.extend(self._spatial_recipe_site_failures(
            target.recipe_id, project.operational_node_id, target.cell_id, day, power
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
            recipe, facility.operational_node_id, day, power, existing_facility_id=facility_id
        )

    def project_site_failures(
        self, project: ConstructionProject, day: int = 0, power: PowerSnapshot | None = None
    ):
        if isinstance(project.target, FacilityUpgradeTarget):
            return self._facility_site_failures_for_recipe(
                self._recipe_for_project(project), project.operational_node_id, day, power,
                existing_facility_id=project.target.facility_id,
            )
        if isinstance(project.target, FacilityDecommissionTarget):
            facility = self.facilities.facilities.get(project.target.facility_id)
            if facility is None:
                return (SiteRequirementFailure("decommission_target_missing", str(project.target.facility_id)),)
            recipe = self._recipe_for_project(project)
            return evaluate_site_requirements(
                recipe.site_requirements,
                project.operational_node_id,
                day,
                self.facilities.environment,
                self.facilities,
                power,
                environment_context_id=self.facilities.facility_environment_context(facility),
            )
        if isinstance(project.target, NewFacilityTarget):
            return self._facility_site_failures_for_recipe(
                self._recipe_for_project(project), project.operational_node_id, day, power,
                site_cell_id=project.site_cell_id,
            )
        return self.spatial_project_failures(project, day, power)

    def project_construction_fulfillment(
        self,
        project: ConstructionProject,
        power: PowerSnapshot,
        execution_allocations: ExecutionAllocationPlan,
        service_allocations: ServiceCapacityAllocationPlan,
        day: int = 0,
    ) -> float:
        """Return current or projected Construction execution fulfillment."""
        del power
        if project.status in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
            return 1.0
        if project.status in {ProjectStatus.READY, ProjectStatus.BUILDING}:
            try:
                return max(0.0, min(1.0, execution_allocations.fulfillment(
                    self.construction_execution_bundle_id(project.id)
                )))
            except KeyError:
                return 0.0
        if not isinstance(project.target, SurfaceCellDevelopmentTarget):
            return 1.0
        service = self.surface_infrastructure
        if service is None:
            return 1.0
        try:
            snapshot = service.prospective_development_snapshot(
                project.operational_node_id, project.target.cell_id, service_allocations, day=day
            )
        except (KeyError, ValueError):
            return 0.0
        return max(0.0, min(1.0, snapshot.fulfillment))

    def project_limiting_factors(
        self,
        project: ConstructionProject,
        power: PowerSnapshot,
        execution_allocations: ExecutionAllocationPlan,
        service_allocations: ServiceCapacityAllocationPlan,
        day: int = 0,
    ) -> tuple[str, ...]:
        if project.status in {ProjectStatus.READY, ProjectStatus.BUILDING}:
            try:
                allocation = execution_allocations.allocation(
                    self.construction_execution_bundle_id(project.id)
                )
            except KeyError:
                return ()
            factors: list[str] = []
            for key in allocation.limiting_constraints:
                if (
                    key.kind == "service"
                    and self.surface_infrastructure is not None
                    and key.name == self.surface_infrastructure.service_type
                ):
                    factors.append("surface_infrastructure")
                elif key.kind == "service":
                    factors.append(f"service:{key.name}")
                else:
                    factors.append(f"{key.kind}:{key.name}")
            return tuple(dict.fromkeys(factors))
        if self.project_construction_fulfillment(
            project, power, execution_allocations, service_allocations, day
        ) < 1.0 - 1e-9:
            return ("surface_infrastructure",)
        return ()

    def service_capacity_types(self) -> tuple[str, ...]:
        return (CONSTRUCTION_SERVICE_TYPE,)

    def service_capacity_scope(self, service_type: str) -> ServiceCapacityScope:
        if service_type != CONSTRUCTION_SERVICE_TYPE:
            raise KeyError(service_type)
        return ServiceCapacityScope.OPERATIONAL_NODE

    def service_capacity_provider_definition_ids(
        self, service_type: str
    ) -> frozenset[DefinitionId]:
        if service_type != CONSTRUCTION_SERVICE_TYPE:
            raise KeyError(service_type)
        return frozenset(self.construction_providers)

    def service_capacity_upstream_services(
        self, service_type: str
    ) -> frozenset[str]:
        if service_type != CONSTRUCTION_SERVICE_TYPE:
            raise KeyError(service_type)
        return frozenset()

    def service_capacity_supply_at(
        self,
        location_id: SpatialNodeId,
        service_type: str,
        facilities,
        power: PowerSnapshot,
        day: int = 0,
        *,
        provider_factors: dict[EntityId, float] | None = None,
    ) -> tuple[float, float]:
        del facilities
        if service_type != CONSTRUCTION_SERVICE_TYPE:
            return (0.0, 0.0)
        return (
            self.construction_nominal_capacity_at(location_id, day),
            self.construction_capacity_at(
                location_id, power, day, provider_factors=provider_factors
            ),
        )

    def construction_nominal_capacity_at(
        self, location_id: SpatialNodeId, day: int = 0
    ) -> float:
        capacity = 0.0
        for facility in self.facilities.active_compatible_at(location_id, day):
            spec = self.construction_providers.get(facility.definition_id)
            if spec is not None:
                capacity += spec.work_per_day
        for resource_id, spec in self.construction_resource_providers.items():
            capacity += (
                self.inventory.available(location_id, resource_id)
                * spec.work_per_t_per_day
            )
        return capacity

    def construction_capacity_at(
        self, location_id: SpatialNodeId, power: PowerSnapshot, day: int = 0, *,
        provider_factors: dict[EntityId, float] | None = None,
    ) -> float:
        """Enabled Construction Service Capacity before consumer allocation."""
        capacity = 0.0
        for facility in self.facilities.active_compatible_at(location_id, day):
            spec = self.construction_providers.get(facility.definition_id)
            if spec is None:
                continue
            utilization = power.utilization_by_facility.get(facility.id, 1.0)
            maintenance = power.maintenance_factor_by_facility.get(facility.id, 1.0)
            upstream = (provider_factors or {}).get(facility.id, 1.0)
            capacity += spec.work_per_day * utilization * maintenance * upstream
        for resource_id, spec in self.construction_resource_providers.items():
            capacity += (
                self.inventory.available(location_id, resource_id)
                * spec.work_per_t_per_day
            )
        return capacity

from __future__ import annotations

from math import ceil

from .application_constraints import constraints_from_pairs, limiting_factors_from_codes
from .application_views import (
    BuildResourceOption,
    BuildOptionRow, BuildProcessOptionRow, BuildResearchCapacityRow,
    BuildSurveyModeRow, BuildSurveyProviderRow,
    BuildOptionsView,
    FacilityUpgradeOption, FacilityUpgradeDifferenceRow,
    ProjectResourceRow,
    ProjectKnowledgeRequirementRow,
    ProjectRow,
)
from .construction.models import (
    CONSTRUCTION_SERVICE_TYPE,
    FacilityUpgradeTarget, FacilityDecommissionTarget, NewFacilityTarget,
    ProjectStatus, SurfaceCellDevelopmentTarget, SurfaceCellEngineeringTarget,
)
from .facilities import FacilityPlacementScope
from .survey import SurveyProviderSourceKind
from .disposal import project_salvage_recovery
from .shared import EntityId, SpatialNodeId
from .supply import SupplyRequirement


class ProjectProjectorMixin:

    @staticmethod
    def _projected_material_readiness_day(
        *, day: int, owner_kind: str, owner_id: str, resources, requirement_rows
    ) -> int | None:
        shortages = [row for row in resources if row.shortage_t > 1e-9]
        if not shortages:
            return day
        by_resource = {
            row.resource_id: row
            for row in requirement_rows
            if row.owner_kind == owner_kind and row.owner_id == owner_id
        }
        readiness_days: list[int] = []
        for resource in shortages:
            requirement = by_resource.get(resource.resource_id)
            if requirement is None:
                return None
            if requirement.external_required_t <= 1e-9:
                readiness_days.append(day)
                continue
            if requirement.remaining_t > 1e-9:
                return None
            if requirement.latest_in_transit_arrival_day is None:
                return None
            readiness_days.append(requirement.latest_in_transit_arrival_day)
        return max(readiness_days, default=day)
    def _construction_resource_options(
        self, recipe, location_id: SpatialNodeId, execution_allocation
    ) -> tuple[tuple[BuildResourceOption, ...], int | None]:
        """Project candidate material availability without creating procurement state.

        Candidate projection must not borrow Cargo already committed to another owner.
        It starts with unreserved local Inventory and asks Logistics for the residual.
        Resources whose selected paths share Transport Services are grouped so they
        cannot each claim the full shared capacity at the same time.
        """
        sim = self._simulation
        projections: list[dict[str, object]] = []
        for requirement in recipe.resources:
            available = sim.inventory.available(location_id, requirement.resource_id)
            shortage = max(0.0, requirement.amount_t - available)
            projection: dict[str, object] = {
                "resource_id": str(requirement.resource_id),
                "required_t": requirement.amount_t,
                "available_t": available,
                "shortage_t": shortage,
                "source_id": None,
                "arrival_day": sim.day if shortage <= 1e-9 else None,
                "capacity": None,
                "service_ids": frozenset(),
            }
            if shortage > 1e-9:
                # Path selection is amount-independent.  Reusing a location/resource
                # projection identity lets Logistics share candidate-path work across
                # multiple Facility candidates in the same derived projection scope.
                projection_id = EntityId(
                    f"projection.build:{location_id}:{requirement.resource_id}"
                )
                options = sim.logistics.supply_planning_options(
                    SupplyRequirement(
                        id=projection_id,
                        owner_kind="construction_preview",
                        owner_id=projection_id,
                        destination_id=location_id,
                        resource_id=requirement.resource_id,
                        amount_t=shortage,
                        forecast_requirement_day=sim.day,
                        purpose="construction_preview",
                    ),
                    sim.day,
                    execution_allocation=execution_allocation,
                )
                if options.selected_source_id is not None:
                    source_available = sim.inventory.available(
                        options.selected_source_id, requirement.resource_id
                    )
                    capacity = options.selected_bottleneck_capacity_t_per_day
                    if (
                        source_available + 1e-9 >= shortage
                        and options.projected_arrival_day is not None
                        and capacity is not None
                        and capacity > 1e-12
                    ):
                        projection.update(
                            source_id=str(options.selected_source_id),
                            arrival_day=options.projected_arrival_day,
                            capacity=float(capacity),
                            service_ids=frozenset(options.selected_service_ids),
                        )
            projections.append(projection)

        # Connected components of overlapping Service paths share at least one
        # bottleneck.  Serialize their aggregate shortage through the lowest current
        # bottleneck capacity; this is conservative when paths only partially overlap.
        remote_indices = [
            index for index, row in enumerate(projections)
            if row["shortage_t"] > 1e-9 and row["arrival_day"] is not None
        ]
        remaining = set(remote_indices)
        while remaining:
            component = {remaining.pop()}
            changed = True
            while changed:
                changed = False
                component_services = set().union(*(projections[i]["service_ids"] for i in component))
                connected = {
                    index for index in remaining
                    if component_services.intersection(projections[index]["service_ids"])
                }
                if connected:
                    component.update(connected)
                    remaining.difference_update(connected)
                    changed = True
            total_shortage = sum(float(projections[i]["shortage_t"]) for i in component)
            capacity = min(float(projections[i]["capacity"]) for i in component)
            first_arrival = max(int(projections[i]["arrival_day"]) for i in component)
            readiness = first_arrival + max(1, ceil(total_shortage / capacity)) - 1
            for index in component:
                projections[index]["arrival_day"] = readiness

        rows = tuple(
            BuildResourceOption(
                row["resource_id"],
                float(row["required_t"]),
                shortage_t=float(row["shortage_t"]),
                available_t=float(row["available_t"]),
                projected_source_id=row["source_id"],
                projected_arrival_day=row["arrival_day"],
            )
            for row in projections
        )
        readiness_days = [row.projected_arrival_day for row in rows]
        return (
            rows,
            max(readiness_days, default=sim.day)
            if all(day is not None for day in readiness_days)
            else None,
        )

    def _facility_upgrade_differences(self, facility, recipe) -> tuple[tuple[FacilityUpgradeDifferenceRow, ...], tuple[str, ...]]:
        sim = self._simulation
        target_level = recipe.target_level
        rows: list[FacilityUpgradeDifferenceRow] = [
            FacilityUpgradeDifferenceRow("level", "Level", facility.level, target_level),
        ]
        definition = sim.facilities.definitions[facility.definition_id]

        if sim.extraction is not None:
            if sim.extraction.compatible_methods(facility.definition_id):
                current = sim.extraction.nominal_capacity(facility)
                target = definition.extraction_capacity_t_per_day * target_level
                if abs(target - current) > 1e-9:
                    rows.append(FacilityUpgradeDifferenceRow(
                        "capacity", "抽出公称Capacity", current, target, "t/日"
                    ))

        provider = None if sim.research is None else sim.research.facility_provider_spec(facility.id)
        if provider is not None:
            current_spec = provider.level_spec(facility.level)
            target_spec = provider.level_spec(target_level)
            for kind, label, current, target, unit in (
                ("capacity", "研究RP生成Capacity", current_spec.generation_points_per_day, target_spec.generation_points_per_day, "RP/日"),
                ("capacity", "研究RP貯蔵Capacity", current_spec.storage_capacity_points, target_spec.storage_capacity_points, "RP"),
                ("service", "研究実行Service供給", current_spec.research_execution_per_day, target_spec.research_execution_per_day, "work/日"),
            ):
                if abs(target - current) > 1e-9:
                    rows.append(FacilityUpgradeDifferenceRow(kind, label, current, target, unit))

        if provider is not None and provider.crew_person_days_per_research_point > 0:
            crew_rate = provider.crew_person_days_per_research_point
            rows.append(FacilityUpgradeDifferenceRow(
                "demand", "研究RP生成時Crew最大需要",
                provider.level_spec(facility.level).generation_points_per_day * crew_rate,
                provider.level_spec(target_level).generation_points_per_day * crew_rate,
                "人日/日",
            ))

        # Installed unit additions alter both nominal output and physical demand.
        per_unit = definition.process_throughput_per_day
        if sim.industry.compatible_processes(facility.definition_id) and per_unit > 0:
            rows.append(FacilityUpgradeDifferenceRow(
                "capacity", "Industry Process実行量", per_unit * facility.level,
                per_unit * target_level, "実行/日"))
        if definition.housing_capacity:
            rows.append(FacilityUpgradeDifferenceRow(
                "capacity", "居住Capacity", definition.housing_at_level(facility.level),
                definition.housing_at_level(target_level), "人"))
        if definition.life_support is not None:
            life = definition.life_support
            rows.append(FacilityUpgradeDifferenceRow(
                "service", "Life Support供給", life.capacity_at_level(facility.level),
                life.capacity_at_level(target_level), "人日/日"))
        power_spec = sim.power.specs.get(facility.definition_id)
        if power_spec is not None:
            context = sim.facilities.facility_environment_context(facility)
            environment_known = sim.surface_knowledge.publishes_environment(context)
            generation, load = sim.power.nominal_for_definition_at_context(facility.definition_id, context)
            for label, amount, unit, site_dependent in (
                ("発電Capacity", generation, "MW", True),
                ("Power需要", load, "MW", True),
                ("停止中Power需要", power_spec.standby_load_mw, "MW", False),
            ):
                if amount or (site_dependent and not environment_known):
                    rows.append(FacilityUpgradeDifferenceRow(
                        "capacity" if "Capacity" in label else "demand", label,
                        (amount * facility.level if environment_known or not site_dependent else "未測定"),
                        (amount * target_level if environment_known or not site_dependent else "未測定"), unit))
        for supply in definition.service_capacity_supplies:
            rows.append(FacilityUpgradeDifferenceRow(
                "service", f"Service供給 · {supply.service_type}",
                supply.nominal_rate * facility.level, supply.nominal_rate * target_level,
                "単位/日"))
        construction_provider = sim.projects.construction_providers.get(facility.definition_id)
        if construction_provider is not None:
            rows.append(FacilityUpgradeDifferenceRow(
                "service", "Construction Service供給",
                construction_provider.work_per_day * facility.level,
                construction_provider.work_per_day * target_level, "work/日"))
        storage_provider = sim.storage.providers.get(facility.definition_id)
        if storage_provider is not None:
            for pool, capacity in sorted(storage_provider.capacity_t_by_pool.items()):
                rows.append(FacilityUpgradeDifferenceRow(
                    "capacity", f"保管Capacity · {pool}", capacity * facility.level,
                    capacity * target_level, "t"))
        if sim.survey is not None:
            for survey_provider in sim.survey.providers.values():
                if survey_provider.source_kind.value != "facility":
                    continue
                if not sim.survey.source_is_compatible(survey_provider, facility.definition_id):
                    continue
                rate = survey_provider.capacity_units_per_source_per_day
                rows.append(FacilityUpgradeDifferenceRow(
                    "service", f"Survey Service · {survey_provider.id}",
                    rate * facility.level, rate * target_level, "観測単位/日"))

        maintenance_fraction = definition.maintenance_fraction_per_year
        if maintenance_fraction > 1e-12:
            current_maintenance = sim.facilities.maintenance_requirements_per_day(facility.id)
            target_investment = dict(facility.invested_resources)
            for requirement in recipe.resources:
                target_investment[requirement.resource_id] = target_investment.get(requirement.resource_id, 0.0) + requirement.amount_t
            target_maintenance = sim.facilities.maintenance_requirements_for_investment(
                facility.definition_id, target_investment
            )
            for resource_id in sorted(set(current_maintenance) | set(target_maintenance), key=str):
                current = current_maintenance.get(resource_id, 0.0)
                target = target_maintenance.get(resource_id, 0.0)
                if abs(target - current) > 1e-12:
                    rows.append(FacilityUpgradeDifferenceRow(
                        "maintenance", f"維持需要 · {self._resource_name(resource_id)}", current, target, "t/日"
                    ))

        unchanged: list[str] = []
        if definition.capability_supplies:
            unchanged.append("Capability構成")
        if sim.industry.compatible_processes(facility.definition_id):
            unchanged.append("Process選択肢")
        return tuple(rows), tuple(unchanged)

    def _facility_upgrade_option(self, facility, power=None) -> FacilityUpgradeOption | None:
        sim = self._simulation
        recipe = sim.projects.next_upgrade_recipe(facility.id)
        if recipe is None:
            return None
        plan_failures = sim.projects.upgrade_plan_failures(facility.id)
        active_project_id = next(
            (failure.detail for failure in plan_failures if failure.code == "active_upgrade_project"),
            None,
        )
        decision = self._tick_decision_projection()
        snapshot = (
            power
            if power is not None
            else decision.allocations.power_by_location[facility.operational_node_id]
        )
        site_failures = sim.projects.upgrade_site_failures(
            facility.id, recipe.target_level, sim.day, snapshot
        )
        context_id = facility.site_cell_id or facility.operational_node_id
        definition = sim.facilities.definitions[facility.definition_id]
        public_site_failures, _ = sim.surface_knowledge.public_site_blockers(
            context_id,
            tuple((failure.code, failure.detail) for failure in site_failures),
            definition.installation_requirements, recipe.site_requirements,
        )
        blockers = tuple(
            ("technology", str(technology))
            for technology in sorted(
                recipe.prerequisite_technologies - sim.projects.unlocked_technologies,
                key=str,
            )
        ) + public_site_failures
        for failure in plan_failures:
            row = (failure.code, failure.detail)
            if row not in blockers:
                blockers += (row,)
        differences, unchanged_aspects = self._facility_upgrade_differences(facility, recipe)
        resources, _ = self._construction_resource_options(
            recipe, facility.operational_node_id, decision.allocations.transport
        )
        return FacilityUpgradeOption(
            target_level=recipe.target_level,
            construction_required=recipe.construction_work,
            resources=resources,
            blockers=constraints_from_pairs(
                blockers,
                affected_action="plan_facility_upgrade",
                related_entity_kind="facility",
                related_entity_id=str(facility.id),
            ),
            can_plan=not plan_failures,
            active_project_id=active_project_id,
            differences=differences,
            unchanged_aspects=unchanged_aspects,
        )

    def _external_supply_blocker(
        self, requirement, execution_allocation=None
    ) -> tuple[str, str]:
        """Translate Logistics Supply Requirement state into an owning-project blocker.

        Finite project domains own their resource need and sourcing preference;
        Logistics owns whether residual off-site requirement has a usable source/path,
        source stock and active pipeline.  The Application layer combines those public
        contracts without making either domain inspect the other's state.
        """
        sim = self._simulation
        resource_id = str(requirement.resource_id)
        if sim.logistics.requirement_remaining_t(requirement) <= 1e-9:
            return ("import_transit", resource_id)

        options = sim.logistics.supply_planning_options(
            requirement,
            sim.day,
            execution_allocation=execution_allocation,
        )
        if not options.candidate_source_ids:
            return ("import_source", resource_id)
        if not options.operational_source_ids:
            detail = resource_id
            if options.blockers:
                detail += ":" + ";".join(options.blockers)
            return ("import_transport_blocked", detail)
        if not options.stocked_source_ids:
            return ("import_stock", resource_id)
        return ("import_transit", resource_id)

    def _external_requirements(self, owner_kind: str, requirements=None) -> dict[str, object]:
        return {
            str(requirement.id): requirement
            for requirement in (
                self._simulation.supplys()
                if requirements is None else requirements
            )
            if requirement.owner_kind == owner_kind
        }

    def _resource_blockers(
        self,
        blockers,
        *,
        owner_kind: str,
        owner_id: str,
        requirements: dict[str, object],
        execution_allocation=None,
    ) -> tuple[tuple[str, str], ...]:
        rows: list[tuple[str, str]] = []
        for blocker in blockers:
            if blocker.code != "resource_shortage":
                rows.append((blocker.code, blocker.detail))
                continue
            requirement_id = f"requirement.{owner_kind}:{owner_id}:{blocker.detail}"
            requirement = requirements.get(requirement_id)
            rows.append(
                self._external_supply_blocker(requirement, execution_allocation)
                if requirement is not None
                else (blocker.code, blocker.detail)
            )
        return tuple(rows)

    def _project_blockers(
        self, project, power, external_requirements=None, execution_allocation=None
    ) -> tuple[tuple[str, str], ...]:
        sim = self._simulation
        requirements = self._external_requirements("project") if external_requirements is None else external_requirements
        return self._resource_blockers(
            sim.projects.blockers(project.id, sim.day, power),
            owner_kind="project",
            owner_id=str(project.id),
            requirements=requirements,
            execution_allocation=execution_allocation,
        )

    def _project_rows(self, location_id: SpatialNodeId | None) -> tuple[ProjectRow, ...]:
        sim = self._simulation
        decision = self._tick_decision_projection()
        requirement_rows = self._requirement_rows(
            execution_allocation=decision.allocations.transport,
            resolutions=decision.plan.requirement_resolutions,
        )
        external_requirements = self._external_requirements(
            "project", decision.plan.external_requirements
        )
        founding_requirements = self._external_requirements(
            "founding", decision.plan.external_requirements
        )
        powers = decision.allocations.power_by_location
        rows = []
        for project in sorted(sim.projects.projects.values(), key=lambda row: str(row.id)):
            if location_id is not None and project.operational_node_id != location_id:
                continue
            recipe = sim.projects.recipe_for_project(project)
            facility_definition_id = sim.projects.target_facility_definition_id(project)
            project_power = powers[project.operational_node_id]
            blockers = self._project_blockers(
                project,
                project_power,
                external_requirements,
                decision.allocations.transport,
            )
            # A queued or executing Site Project may be physically unsuitable.
            # Its real blockers govern simulation; the player's read model must
            # not reveal an unobserved Cell through an in-progress Project.
            if isinstance(project.target, (SurfaceCellDevelopmentTarget, SurfaceCellEngineeringTarget)):
                blockers, _ = sim.surface_knowledge.public_site_blockers(
                    project.target.cell_id, blockers, recipe.site_requirements,
                )
            elif isinstance(project.target, NewFacilityTarget):
                definition = sim.facilities.definitions[project.target.facility_def_id]
                blockers, _ = sim.surface_knowledge.public_site_blockers(
                    project.site_cell_id or project.operational_node_id, blockers,
                    definition.installation_requirements, recipe.site_requirements,
                )
            elif isinstance(project.target, FacilityUpgradeTarget):
                existing = sim.facilities.facilities.get(project.target.facility_id)
                if existing is not None:
                    definition = sim.facilities.definitions[existing.definition_id]
                    blockers, _ = sim.surface_knowledge.public_site_blockers(
                        existing.site_cell_id or existing.operational_node_id,
                        blockers, definition.installation_requirements,
                        recipe.site_requirements,
                    )
            resources = []
            for requirement in recipe.resources:
                state = project.resources[requirement.resource_id]
                reserved_t = sim.projects.reserved_resource_t(project, requirement.resource_id)
                shortage = max(0.0, requirement.amount_t - reserved_t - state.committed_t)
                candidate_requirement_id = f"requirement.project:{project.id}:{requirement.resource_id}"
                requirement_id = (
                    candidate_requirement_id
                    if shortage > 1e-9 and candidate_requirement_id in external_requirements
                    else None
                )
                resources.append(ProjectResourceRow(
                    str(requirement.resource_id), requirement.amount_t, reserved_t, 0.0, state.committed_t,
                    shortage, requirement_id,
                ))

            target_facility_id = None
            target_level = None
            target_cell_id = None
            target_body_id = None
            target_location_id = None
            target = project.target
            if isinstance(target, NewFacilityTarget):
                target_kind = "new_facility"
                definition = sim.facilities.definitions[target.facility_def_id]
                display_name = definition.display_name
            elif isinstance(target, FacilityUpgradeTarget):
                target_kind = "facility_upgrade"
                target_facility_id = str(target.facility_id)
                target_level = target.target_level
                definition = sim.facilities.definitions[facility_definition_id]
                display_name = definition.display_name
            elif isinstance(target, FacilityDecommissionTarget):
                target_kind = "facility_decommission"
                target_facility_id = str(target.facility_id)
                facility_definition_id = target.facility_definition_id
                definition = sim.facilities.definitions[target.facility_definition_id]
                display_name = definition.display_name
            else:
                target_kind = ("surface_cell_engineering" if isinstance(target, SurfaceCellEngineeringTarget)
                               else "surface_cell_development")
                target_cell_id = str(target.cell_id)
                target_location_id = str(project.operational_node_id)
                display_name = recipe.display_name

            construction_fulfillment = sim.projects.project_construction_fulfillment(
                project, project_power, decision.allocations.execution,
                decision.allocations.services, sim.day
            )
            limiting_factors = sim.projects.project_limiting_factors(
                project, project_power, decision.allocations.execution,
                decision.allocations.services, sim.day
            )

            salvage_potential = {}
            salvage_projection = None
            if isinstance(project.target, FacilityDecommissionTarget):
                salvage_potential = sim.projects.decommission_salvage_for_project(project)
                facility = sim.facilities.facilities.get(project.target.facility_id)
                if facility is not None:
                    post_removal_headroom = sim.storage.post_decommission_admission_headroom(
                        facility.id, sim.day, project_power
                    )
                    salvage_projection = project_salvage_recovery(
                        sim.inventory,
                        project.operational_node_id,
                        salvage_potential,
                        admission_headroom_by_pool=post_removal_headroom,
                    )

            rows.append(ProjectRow(
                str(project.id), target_kind, str(project.operational_node_id),
                None if facility_definition_id is None else str(facility_definition_id),
                target_facility_id, target_level, display_name, project.status, project.paused,
                project.priority, project.procurement_policy,
                sim.projects.settings_mutable(project.id), sim.projects.procurement_mutable(project.id),
                tuple(sim.projects.procurement_policy_options()),
                project.construction_done, recipe.construction_work,
                project.materials_committed,
                None if project.completed_facility_id is None else str(project.completed_facility_id),
                tuple(resources), constraints_from_pairs(
                    blockers,
                    affected_action="progress_construction_project",
                    related_entity_kind="project",
                    related_entity_id=str(project.id),
                ),
                None if project.site_cell_id is None else str(project.site_cell_id),
                target_cell_id, target_body_id, target_location_id,
                construction_fulfillment, limiting_factors_from_codes(
                    limiting_factors,
                    affected_action="progress_construction_project",
                    related_entity_kind="project",
                    related_entity_id=str(project.id),
                ),
                self._projected_material_readiness_day(
                    day=sim.day,
                    owner_kind="project",
                    owner_id=str(project.id),
                    resources=resources,
                    requirement_rows=requirement_rows,
                ),
                project.irreversible_started,
                tuple(
                    (str(resource_id), amount)
                    for resource_id, amount in sorted(salvage_potential.items(), key=lambda row: str(row[0]))
                ),
                projected_salvage_fraction=(
                    None if salvage_projection is None else salvage_projection.recoverable_fraction
                ),
                projected_salvage=(
                    ()
                    if salvage_projection is None
                    else tuple(
                        (str(resource_id), amount)
                        for resource_id, amount in salvage_projection.recovered_by_resource
                    )
                ),
                actual_salvage_fraction=project.salvage_recovered_fraction,
                actual_salvage=tuple(
                    (str(resource_id), amount)
                    for resource_id, amount in sorted(project.salvage_recovered.items(), key=lambda row: str(row[0]))
                ),
            ))
        if sim.founding is not None:
            for project in sorted(sim.founding.projects.values(), key=lambda row: str(row.id)):
                if location_id is not None and project.staging_node_id != location_id:
                    continue
                recipe = sim.founding.deployment_recipes[project.deployment_recipe_id]
                resource_status = sim.founding.project_resource_status(project.id)
                resources = [
                    ProjectResourceRow(
                        str(status.resource_id), status.required_t, 0.0, status.staged_t,
                        status.committed_t, status.shortage_t, None,
                    )
                    for status in resource_status
                ]
                blockers = self._resource_blockers(
                    sim.founding.blockers(project.id, sim.day, powers[project.staging_node_id]),
                    owner_kind="founding", owner_id=str(project.id),
                    requirements=founding_requirements,
                    execution_allocation=decision.allocations.transport,
                )
                target_spec = project.target_spec
                target_cell = sim.founding.target_surface_cell_id(target_spec)
                target_body = sim.founding.target_body_id(target_spec)
                target_node = sim.founding.target_operational_node_id(target_spec)
                knowledge_rows = []
                if sim.survey is not None:
                    for requirement in sim.founding.knowledge_requirements_for_target(target_spec, recipe):
                        current = sim.surface_knowledge.knowledge_level(
                            requirement.target_cell_id, requirement.subject_resource_id
                        )
                        knowledge_rows.append(ProjectKnowledgeRequirementRow(
                            target_cell_id=str(requirement.target_cell_id),
                            subject_resource_id=str(requirement.subject_resource_id),
                            minimum_level=int(requirement.minimum_level),
                            current_level=int(current),
                            met=current >= requirement.minimum_level,
                        ))
                if target_cell is not None:
                    unpublished = sim.surface_knowledge.unpublished_site_condition_codes(
                        target_cell, recipe.target_requirements,
                    )
                    unknown_facility = (
                        not sim.surface_knowledge.publishes_environment(target_cell)
                        and any(sim.facilities.definitions[deployment.facility_def_id].installation_requirements.environment
                                for deployment in recipe.deployed_facilities)
                    )
                    blockers = tuple(row for row in blockers
                        if row[0] not in {f"target:{code}" for code in unpublished}
                        and not (unknown_facility and row[0] == "facility_environment"))
                    if unpublished or unknown_facility:
                        blockers += (("site_knowledge_unverified", "現地環境条件は未測定・再測定待ち"),)
                site_blockers = tuple(
                    row for row in blockers
                    if row[0].startswith("staging:") or row[0].startswith("target:")
                    or row[0] in {"knowledge_requirement", "knowledge_target_type", "surface_facility_target"}
                )
                movement_blockers = tuple(
                    row for row in blockers if row[0] in {"deployment_vehicle", "fleet_units"}
                )
                rows.append(ProjectRow(
                    id=str(project.id), target_kind="operational_node_founding",
                    operational_node_id=str(project.staging_node_id), facility_definition_id=None,
                    target_facility_id=None, target_level=None, display_name=project.display_name,
                    status=project.status.value, paused=project.paused, priority=project.priority,
                    procurement_policy="founding",
                    settings_editable=project.status.value == "preparing", procurement_editable=False,
                    procurement_policy_options=(),
                    construction_done=project.preparation_done, construction_required=recipe.preparation_work,
                    materials_committed=project.inputs_consumed, completed_facility_id=None,
                    resources=tuple(resources),
                    blockers=constraints_from_pairs(
                        blockers,
                        affected_action="progress_founding",
                        related_entity_kind="founding_project",
                        related_entity_id=str(project.id),
                    ),
                    site_cell_id=None,
                    target_cell_id=None if target_cell is None else str(target_cell),
                    target_body_id=None if target_body is None else str(target_body),
                    target_location_id=str(target_node),
                    construction_fulfillment=sim.founding.preparation_fulfillment(project.id, decision.allocations.execution),
                    limiting_factors=limiting_factors_from_codes(
                        sim.founding.preparation_limiting_factors(project.id, decision.allocations.execution),
                        affected_action="progress_founding",
                        related_entity_kind="founding_project",
                        related_entity_id=str(project.id),
                    ),
                    projected_material_readiness_day=self._projected_material_readiness_day(
                        day=sim.day, owner_kind="founding", owner_id=str(project.id),
                        resources=resources, requirement_rows=requirement_rows,
                    ),
                    founding_target_type=sim.founding.target_type(target_spec),
                    founding_knowledge_requirements=tuple(knowledge_rows),
                    fleet_commitment_id=None if project.fleet_commitment_id is None else str(project.fleet_commitment_id),
                    manifest_ready=all(row.shortage_t <= 1e-9 for row in resource_status),
                    deployment_phase=project.status.value,
                    site_blockers=constraints_from_pairs(
                        site_blockers,
                        affected_action="progress_founding",
                        related_entity_kind="founding_project",
                        related_entity_id=str(project.id),
                    ),
                    movement_blockers=constraints_from_pairs(
                        movement_blockers,
                        affected_action="progress_founding",
                        related_entity_kind="founding_project",
                        related_entity_id=str(project.id),
                    ),
                ))
        return tuple(rows)

    def _prospective_facility_effects(self, recipe, context_id) -> dict[str, object]:
        """Nominal Level 1 effects of a new Facility at its actual physical site.

        Construction and Surface Cell placement share the same Domain sources.
        These are *not* executable flow forecasts; resource/service allocation
        still determines actual production and upkeep after construction.
        """
        sim = self._simulation
        definition = sim.facilities.definitions[recipe.facility_def_id]
        compatible = sim.industry.compatible_processes(recipe.facility_def_id)
        process_options = tuple(
            BuildProcessOptionRow(
                process_id=str(process.id),
                display_name=process.display_name,
                input_rates_per_day=tuple(
                    (str(resource), rate * definition.process_throughput_per_day)
                    for resource, rate in sorted(process.inputs_per_day.items(), key=lambda pair: str(pair[0]))
                ),
                output_rates_per_day=tuple(
                    (str(resource), rate * definition.process_throughput_per_day)
                    for resource, rate in sorted(process.outputs_per_day.items(), key=lambda pair: str(pair[0]))
                ),
                missing_technology_ids=tuple(
                    str(technology) for technology in sim.industry.missing_process_technologies(process)
                ),
            )
            for process in compatible
        )
        invested = {}
        for resource in recipe.resources:
            invested[resource.resource_id] = invested.get(resource.resource_id, 0.0) + resource.amount_t
        upkeep = sim.facilities.maintenance_requirements_for_investment(
            recipe.facility_def_id, invested
        )
        provider = (
            None if sim.research is None else
            sim.research.facility_provider_for_definition(recipe.facility_def_id)
        )
        research_capacity = None
        if provider is not None:
            level = provider.level_spec(1)
            research_capacity = BuildResearchCapacityRow(
                provider_tier=provider.tier,
                generation_points_per_day=level.generation_points_per_day,
                storage_capacity_points=level.storage_capacity_points,
                execution_work_per_day=level.research_execution_per_day,
                crew_person_days_per_research_point=provider.crew_person_days_per_research_point,
            )
        survey_providers = ()
        if sim.survey is not None:
            survey_providers = tuple(
                BuildSurveyProviderRow(
                    provider_id=str(provider.id),
                    capacity_units_per_source_per_day=provider.capacity_units_per_source_per_day,
                    observation_modes=tuple(
                        BuildSurveyModeRow(
                            display_name=mode.display_name or mode.id,
                            survey_rate=mode.survey_rate,
                            max_knowledge_level=int(mode.max_knowledge_level),
                        )
                        for mode in provider.observation_modes
                        if sim.survey.source_supports_mode(provider, mode, recipe.facility_def_id)
                    ),
                )
                for provider in sorted(sim.survey.providers.values(), key=lambda row: str(row.id))
                if provider.source_kind is SurveyProviderSourceKind.FACILITY
                and sim.survey.source_is_compatible(provider, recipe.facility_def_id)
            )
        nominal_generation, nominal_load = sim.power.nominal_for_definition_at_context(
            recipe.facility_def_id, context_id,
        )
        services = [
            (supply.service_type, supply.nominal_rate)
            for supply in definition.service_capacity_supplies
        ]
        construction_provider = sim.projects.construction_providers.get(recipe.facility_def_id)
        if construction_provider is not None:
            services.append((CONSTRUCTION_SERVICE_TYPE, construction_provider.work_per_day))
        return dict(
            capabilities=tuple(sorted(supply.id for supply in definition.capability_supplies)),
            service_capacity_supplies=tuple(sorted(services)),
            process_options=process_options,
            power_nominal_generation_mw=nominal_generation,
            power_nominal_load_mw=nominal_load,
            power_nominal_standby_load_mw=(
                sim.power.specs[recipe.facility_def_id].standby_load_mw
                if recipe.facility_def_id in sim.power.specs else 0.0
            ),
            process_nominal_throughput_per_day=(
                definition.process_throughput_per_day if compatible else None
            ),
            extraction_nominal_capacity_t_per_day=(
                definition.extraction_capacity_t_per_day
                if definition.extraction_capacity_t_per_day > 0 else None
            ),
            maintenance_rates_per_day=tuple(
                (str(resource_id), rate)
                for resource_id, rate in sorted(upkeep.items(), key=lambda item: str(item[0]))
            ),
            housing_capacity=definition.housing_capacity,
            life_support_person_days_per_day=(
                definition.life_support.person_days_per_day
                if definition.life_support is not None else 0.0
            ),
            life_support_net_resources_per_person_day=(
                tuple((str(resource), rate)
                      for resource, rate in definition.life_support.net_resources)
                if definition.life_support is not None else ()
            ),
            research_capacity=research_capacity,
            survey_providers=survey_providers,
        )

    def _build_options_view(self, location_id: SpatialNodeId) -> BuildOptionsView:
        sim = self._simulation
        decision = self._tick_decision_projection()
        powers = decision.allocations.power_by_location
        rows = []
        for recipe in sorted(sim.projects.recipes.values(), key=lambda row: str(row.facility_def_id)):
            definition = sim.facilities.definitions[recipe.facility_def_id]
            if definition.placement_scope is not FacilityPlacementScope.OPERATIONAL_NODE:
                continue
            plan_failures = sim.projects.build_plan_failures(
                recipe.facility_def_id, location_id
            )
            site_failures = sim.projects.site_failures(
                recipe.facility_def_id, location_id, sim.day, powers[location_id]
            )
            public_site_failures, site_unknown = sim.surface_knowledge.public_site_blockers(
                location_id, tuple((failure.code, failure.detail) for failure in site_failures),
                definition.installation_requirements, recipe.site_requirements,
            )
            blockers = tuple(
                ("technology", str(technology))
                for technology in sorted(
                    recipe.prerequisite_technologies - sim.projects.unlocked_technologies,
                    key=str,
                )
            ) + public_site_failures
            build_resources, material_readiness_day = self._construction_resource_options(
                recipe, location_id, decision.allocations.transport
            )
            rows.append(BuildOptionRow(
                facility_definition_id=str(recipe.facility_def_id),
                display_name=definition.display_name,
                construction_required=recipe.construction_work,
                self_deploying=recipe.self_deploying,
                resources=build_resources,
                blockers=constraints_from_pairs(
                    blockers,
                    affected_action="plan_facility_construction",
                    related_entity_kind="facility_definition",
                    related_entity_id=str(recipe.facility_def_id),
                ),
                can_plan=not plan_failures,
                placement_scope=definition.placement_scope.value,
                projected_material_readiness_day=material_readiness_day,
                site_knowledge_unverified=site_unknown,
                **self._surface_facility_public_effects(
                    recipe, location_id, sim.surface_knowledge.publishes_environment(location_id)
                ),
            ))
        return BuildOptionsView(
            str(location_id),
            tuple(sim.projects.procurement_policy_options()),
            tuple(rows),
        )

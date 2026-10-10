"""Explicit opt-in composition for static dependency and balance analysis.

This is an observer of the same registered Definitions as gameplay, not a second
eligibility engine and not part of Simulation's canonical tick.
"""
from __future__ import annotations

from ..analysis_graph import (
    Contributor, DependencyDefinitionGraph, DependencyFragment, DependencyNode,
    DependencyRelation, DefinitionGraphRegistry,
)
from ..catalog import GameCatalog
from ..construction.models import CONSTRUCTION_SERVICE_TYPE
from ..exploration_models import KnowledgeLevel, SurveyProviderSourceKind, SurveyReachScope
from ..research_models import (
    ResearchTheoryStageSpec, ResearchPrototypeStageSpec,
    ResearchDemonstrationStageSpec, ResearchOperationalExperienceStageSpec,
)
from ..execution_requirements import (
    ResourceRequirement, ServiceCapacityRequirement, PoolRequirement,
    PoolAdmissionRequirement, StockOrPoolAdmissionRequirement,
)
from ..power import FixedGeneration, SolarGeneration
from ..inventory import DEFAULT_STORAGE_POOL_KEY
from ..simulation import Simulation
from . import analysis_context_contributors as context_contributors


def _node(kind: str, identifier: object) -> DependencyNode:
    return DependencyNode(kind, str(identifier))


def build_definition_dependency_graph(
    sim: Simulation, catalog: GameCatalog, *,
    additional_contributors: tuple[tuple[str, Contributor, frozenset[str]], ...] = (),
) -> DependencyDefinitionGraph:
    """Build only when requested; extension registration never alters live State."""
    registry = DefinitionGraphRegistry()

    def resources() -> DependencyFragment:
        all_capabilities: set[str] = set()
        for facility in sim.facilities.definitions.values():
            all_capabilities.update(supply.id for supply in facility.capability_supplies)
        for vehicle in sim.transport.vehicle_definitions():
            all_capabilities.update(vehicle.generic_capabilities)
        for process in sim.industry.processes.values():
            all_capabilities.update(process.required_capabilities)
        if sim.extraction is not None:
            for method in sim.extraction.specs.values():
                all_capabilities.update(method.required_capabilities)
        if sim.survey is not None:
            for provider in sim.survey.providers.values():
                all_capabilities.update(provider.required_source_capabilities)
                for mode in provider.observation_modes:
                    all_capabilities.update(mode.required_source_capabilities)
                    all_capabilities.update(
                        requirement.capability_id for requirement in mode.site_requirements.capability_requirements
                    )
        if sim.research is not None:
            for technology in sim.research.definitions.values():
                for stage in technology.stage_specs:
                    if isinstance(stage, (ResearchPrototypeStageSpec, ResearchDemonstrationStageSpec)):
                        all_capabilities.update(
                            requirement.capability_id
                            for requirement in stage.site_requirements.capability_requirements
                        )
        if sim.scientific_exploration is not None:
            for campaign in sim.scientific_exploration.definitions.values():
                all_capabilities.update(campaign.required_vehicle_capabilities)
                for requirements in (campaign.origin_requirements, campaign.destination_requirements):
                    all_capabilities.update(row.capability_id for row in requirements.capability_requirements)
        for recipe in (
            *sim.projects.recipes.values(), *sim.projects.upgrade_recipes.values(),
            *sim.projects.decommission_recipes.values(), *sim.projects.spatial_recipes.values(),
        ):
            all_capabilities.update(
                requirement.capability_id for requirement in recipe.site_requirements.capability_requirements
            )
        services = {"power", "life_support", "onboard_life_support", CONSTRUCTION_SERVICE_TYPE}
        services.update(supply.service_type
                        for facility in sim.facilities.definitions.values()
                        for supply in facility.service_capacity_supplies)
        for vehicle in sim.transport.vehicle_definitions():
            for service in (vehicle.production.service_type, vehicle.maintenance.service_type,
                            vehicle.retirement.service_type):
                if service is not None:
                    services.add(service)
        if sim.research is not None:
            for technology in sim.research.definitions.values():
                for stage in technology.stage_specs:
                    if isinstance(stage, (ResearchTheoryStageSpec, ResearchPrototypeStageSpec,
                                          ResearchDemonstrationStageSpec)):
                        services.update(requirement.service_type for requirement in stage.execution_requirements
                                        if isinstance(requirement, ServiceCapacityRequirement))
        if sim.survey is not None:
            services.update(sim.survey.service_capacity_types())
        resource_pools = {
            resource.storage_pool_key or DEFAULT_STORAGE_POOL_KEY
            for resource in catalog.resources.values()
        }
        for provider in sim.storage.providers.values():
            resource_pools.update(provider.capacity_t_by_pool)
        return DependencyFragment(
            tuple(_node("resource", value) for value in catalog.resources)
            + tuple(_node("storage_pool", pool) for pool in sorted(resource_pools))
            + tuple(_node("capability", cap) for cap in sorted(all_capabilities))
            + tuple(_node("service_capacity", service) for service in sorted(services))
            + (_node("capacity_pool", "housing"), _node("capacity_pool", "passenger_seats"),
               _node("research_point_pool", "research_points"),
               _node("capacity_pool", "fleet_units"), _node("capacity_pool", "population")),
            tuple(DependencyRelation(
                "uses_storage_pool", _node("resource", resource.id),
                _node("storage_pool", resource.storage_pool_key or DEFAULT_STORAGE_POOL_KEY),
                f"resource:{resource.id}:storage_pool_key",
            ) for resource in catalog.resources.values()),
        )

    registry.register("catalog", resources, relation_kinds={"uses_storage_pool"},
                      expected_definitions=lambda: (_node("resource", key) for key in catalog.resources))

    def research() -> DependencyFragment:
        if sim.research is None:
            return DependencyFragment((), ())
        nodes = [
            _node("experience_category", category)
            for category in sorted({rule.category_id for rule in sim.research.experience_rules})
        ]
        relations = []
        for rule in sim.research.experience_rules:
            activity = _node("activity_kind", rule.activity_kind)
            if activity not in nodes:
                nodes.append(activity)
            relations.append(DependencyRelation(
                "contributes_experience", activity,
                _node("experience_category", rule.category_id),
                f"experience:{rule.activity_kind}:{rule.category_id}",
                rule.points_per_unit, "experience_points/activity_unit", "per_activity_unit",
            ))
        for technology in sim.research.definitions.values():
            owner = _node("technology", technology.id)
            nodes.append(owner)
            for requirement in technology.prerequisites:
                relations.append(DependencyRelation(
                    "technology_prerequisite", _node("technology", requirement), owner,
                    f"research:{technology.id}:prerequisites",
                ))
            for index, stage in enumerate(technology.stage_specs):
                stage_node = _node("research_stage", f"{technology.id}/{stage.stage_id}")
                nodes.append(stage_node)
                relations.append(DependencyRelation(
                    "research_stage", stage_node, owner, f"research:{technology.id}:stage:{stage.stage_id}",
                    condition=f"type:{stage.stage_type.value};order:{index}",
                ))
                provenance = f"research:{technology.id}:stage:{stage.stage_id}"
                if isinstance(stage, ResearchTheoryStageSpec):
                    relations.append(DependencyRelation(
                        "research_point_cost", _node("research_point_pool", "research_points"), stage_node,
                        provenance,
                        quantity=stage.research_point_cost, unit="research_points",
                        time_basis="per_stage",
                    ))
                elif isinstance(stage, (ResearchPrototypeStageSpec, ResearchDemonstrationStageSpec)):
                    relations.append(DependencyRelation(
                        "research_work", stage_node, owner, provenance,
                        stage.required_work, "work", "per_stage",
                    ))
                    if isinstance(stage, ResearchPrototypeStageSpec):
                        for resource_id, amount in sorted(stage.resources.items()):
                            relations.append(DependencyRelation(
                                "consumes_resource", _node("resource", resource_id), stage_node,
                                f"{provenance}:resources:{resource_id}", amount, "t", "per_stage",
                            ))
                    # Research uses the same physical Site definition contract as
                    # construction, founding, and movement. Keep each typed
                    # constraint as a prerequisite of the actual Stage, including
                    # environment parameters rather than just display descriptions.
                    context_contributors.contribute_site_requirements(
                        stage_node, "research_stage", stage.site_requirements, nodes, relations,
                    )
                elif isinstance(stage, ResearchOperationalExperienceStageSpec):
                    for category, amount in sorted(stage.requirements.items()):
                        relations.append(DependencyRelation(
                            "requires_experience", _node("experience_category", category), stage_node,
                            f"{provenance}:experience:{category}",
                            amount, "experience_points", "completion_threshold",
                        ))
                if isinstance(stage, (ResearchTheoryStageSpec, ResearchPrototypeStageSpec,
                                      ResearchDemonstrationStageSpec)):
                    for requirement in stage.execution_requirements:
                        if isinstance(requirement, ResourceRequirement):
                            kind, identifier = "resource", requirement.resource_id
                        elif isinstance(requirement, ServiceCapacityRequirement):
                            kind, identifier = "service_capacity", requirement.service_type
                        elif isinstance(requirement, (PoolRequirement, PoolAdmissionRequirement,
                                                      StockOrPoolAdmissionRequirement)):
                            kind, identifier = (
                                ("research_point_pool", requirement.pool_id)
                                if requirement.pool_id == "research_points" else
                                ("capacity_pool", requirement.pool_id)
                            )
                            pool_node = _node(kind, identifier)
                            if pool_node not in nodes and identifier not in {
                                "research_points", "housing", "passenger_seats", "fleet_units", "population",
                            }:
                                nodes.append(pool_node)
                        else:
                            raise TypeError(f"unknown Research Stage requirement: {type(requirement).__name__}")
                        relations.append(DependencyRelation(
                            "requires_execution_capacity", _node(kind, identifier), stage_node,
                            f"{provenance}:execution:{type(requirement).__name__}:{identifier}",
                            requirement.amount_per_execution, "requirement_units/execution", "per_execution",
                            condition=f"scope:{getattr(getattr(requirement, 'scope', None), 'value', 'node')}",
                        ))
        for provider in sim.research.providers.values():
            target = _node("research_provider", provider.id)
            nodes.append(target)
            if provider.source_kind.value == "fleet":
                sources = (("vehicle", definition.id) for definition in sim.research.compatible_vehicle_definitions(provider.id))
            else:
                sources = (("facility", definition_id) for definition_id in sim.research.compatible_facility_definition_ids(provider.id))
            for source_kind, definition_id in sources:
                relations.append(DependencyRelation(
                    "uses_asset_definition", _node(source_kind, definition_id), target,
                    f"research_provider:{provider.id}:required_source_capabilities",
                    condition="source_capabilities:" + ",".join(sorted(provider.required_source_capabilities)),
                ))
            for level in sorted(provider.levels, key=lambda row: row.level):
                qualifier = f"research_provider:{provider.id}:level:{level.level}"
                if level.generation_points_per_day:
                    relations.append(DependencyRelation(
                        "nominal_research_point_generation", target,
                        _node("research_point_pool", "research_points"),
                        f"{qualifier}:generation_points_per_day",
                        level.generation_points_per_day, "research_points/day", "per_active_source",
                        condition="admission_headroom_and_source_operations_required",
                    ))
                if level.storage_capacity_points:
                    relations.append(DependencyRelation(
                        "nominal_research_point_storage", target,
                        _node("research_point_pool", "research_points"),
                        f"{qualifier}:storage_capacity_points",
                        level.storage_capacity_points, "research_points", "per_installed_source",
                    ))
                if level.research_execution_per_day:
                    relations.append(DependencyRelation(
                        "nominal_research_execution", target,
                        _node("service_capacity", "research_execution"),
                        f"{qualifier}:research_execution_per_day",
                        level.research_execution_per_day, "execution_units/day", "per_active_source",
                        condition="organization_pool;source_site_and_power_required",
                    ))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("research", research, expected_definitions=lambda: (
        _node("technology", key) for key in (() if sim.research is None else sim.research.definitions)
    ), relation_kinds={
        "technology_prerequisite", "research_stage", "research_point_cost",
        "research_work", "consumes_resource", "requires_site_capability",
        "requires_site_classification", "requires_site_environment",
        "contributes_experience", "requires_experience", "requires_execution_capacity",
        "uses_asset_definition", "nominal_research_point_generation",
        "nominal_research_point_storage", "nominal_research_execution",
    })

    def facilities() -> DependencyFragment:
        nodes = []
        relations = []
        for facility in sim.facilities.definitions.values():
            owner = _node("facility", facility.id)
            nodes.append(owner)
            for supply in facility.capability_supplies:
                relations.append(DependencyRelation(
                    "supplies_capability", owner, _node("capability", supply.id),
                    f"facility:{facility.id}:capability_supplies",
                ))
            for supply in facility.service_capacity_supplies:
                relations.append(DependencyRelation(
                    "nominal_service_supply", owner, _node("service_capacity", supply.service_type),
                    f"facility:{facility.id}:service_capacity_supplies:{supply.service_type}",
                    supply.nominal_rate, "service_units/day", "per_installed_facility",
                    condition=f"scope:{supply.scope.value};active_and_maintained",
                ))
            if facility.housing_capacity:
                relations.append(DependencyRelation(
                    "nominal_housing_capacity", owner, _node("capacity_pool", "housing"),
                    f"facility:{facility.id}:housing_capacity", facility.housing_capacity,
                    "people", "per_facility_level", condition="installed_and_habitable",
                ))
            if facility.life_support is not None:
                support = _node("life_support_method", facility.id)
                nodes.append(support)
                relations.append(DependencyRelation(
                    "uses_asset_definition", owner, support,
                    f"facility:{facility.id}:life_support",
                ))
                relations.append(DependencyRelation(
                    "nominal_life_support_supply", support, _node("service_capacity", "life_support"),
                    f"facility:{facility.id}:life_support.person_days_per_day",
                    facility.life_support.person_days_per_day, "person_days/day",
                    "per_facility_level", condition="active_power_maintenance_and_allocation",
                ))
                for resource_id, rate in facility.life_support.net_resources:
                    relations.append(DependencyRelation(
                        "consumes_resource", _node("resource", resource_id), support,
                        f"facility:{facility.id}:life_support.net_resources:{resource_id}",
                        rate, "t/person_day", "per_supported_person_day",
                    ))
            if facility.maintenance_fraction_per_year:
                policy = _node("facility_maintenance_policy", facility.id)
                nodes.append(policy)
                relations.append(DependencyRelation(
                    "maintenance_investment_fraction", owner, policy,
                    f"facility:{facility.id}:maintenance_fraction_per_year",
                    facility.maintenance_fraction_per_year, "fraction/year",
                    "of_actual_instance_investment",
                ))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("facility", facilities, expected_definitions=lambda: (
        _node("facility", key) for key in sim.facilities.definitions
    ), relation_kinds={
        "supplies_capability", "nominal_service_supply", "nominal_housing_capacity",
        "uses_asset_definition", "nominal_life_support_supply", "consumes_resource",
        "maintenance_investment_fraction",
    })

    def power_and_storage() -> DependencyFragment:
        # Nominal installed supply and load. Daily usable power and storage are
        # resolved from physical environment, pause, maintenance and allocation
        # by their owner domains, not inferred from these static edges.
        nodes = set()
        relations = []
        for facility_id, spec in sim.power.specs.items():
            facility = _node("facility", facility_id)
            power = _node("service_capacity", "power")
            if isinstance(spec.generation, FixedGeneration):
                relations.append(DependencyRelation(
                    "nominal_power_supply", facility, power,
                    f"power:{facility_id}:generation.fixed", spec.generation.mw, "MW",
                    "installed_rating", condition="facility_active_and_maintained",
                ))
            elif isinstance(spec.generation, SolarGeneration):
                relations.append(DependencyRelation(
                    "nominal_power_supply", facility, power,
                    f"power:{facility_id}:generation.solar",
                    spec.generation.rated_mw_at_reference_flux, "MW", "at_reference_flux",
                    condition=f"reference_flux_w_m2:{spec.generation.reference_flux_w_m2:g};illumination_required",
                ))
            if spec.load_mw:
                relations.append(DependencyRelation(
                    "nominal_power_load", power, facility,
                    f"power:{facility_id}:load_mw", spec.load_mw, "MW", "when_active",
                ))
            if spec.standby_load_mw:
                relations.append(DependencyRelation(
                    "standby_power_load", power, facility,
                    f"power:{facility_id}:standby_load_mw", spec.standby_load_mw, "MW", "when_paused",
                ))
        for facility_id, spec in sim.storage.providers.items():
            for pool, amount in spec.capacity_t_by_pool.items():
                storage = _node("storage_pool", pool)
                relations.append(DependencyRelation(
                    "nominal_storage_capacity", _node("facility", facility_id), storage,
                    f"storage:{facility_id}:capacity_t_by_pool:{pool}", amount, "t",
                    "per_installed_facility",
                    condition="power_sensitive" if pool in spec.power_sensitive_pools else "physical_capacity",
                ))
        return DependencyFragment(tuple(sorted(nodes)), tuple(relations))

    registry.register("power_and_storage", power_and_storage, relation_kinds={
        "nominal_power_supply", "nominal_power_load", "standby_power_load", "nominal_storage_capacity",
    })

    def external_market() -> DependencyFragment:
        nodes = []
        relations = []
        for provider in sim.market.provider_defs.values():
            source = _node("market_provider", provider.id)
            nodes.append(source)
            for resource_id, price in provider.buy_offers_musd_per_t:
                target = _node("resource", resource_id)
                relations.append(DependencyRelation(
                    "external_buy_offer", source, target,
                    f"market:{provider.id}:buy_offers_musd_per_t:{resource_id}",
                    price, "MUSD/t", "offer_price",
                    condition=f"interface_required;lead_time_days:{provider.lead_time_days}",
                ))
            for resource_id, price in provider.sell_offers_musd_per_t:
                relations.append(DependencyRelation(
                    "external_sell_offer", _node("resource", resource_id), source,
                    f"market:{provider.id}:sell_offers_musd_per_t:{resource_id}",
                    price, "MUSD/t", "offer_price", condition="interface_required",
                ))
            for row in provider.supply:
                relations.append(DependencyRelation(
                    "external_supply_capacity", source, _node("resource", row.resource_id),
                    f"market:{provider.id}:supply:{row.resource_id}",
                    row.capacity_t, "t", "stock_capacity",
                    condition=f"replenishment_t_per_day:{row.replenishment_t_per_day:g};finite_provider_state",
                ))
            for row in provider.demand:
                relations.append(DependencyRelation(
                    "external_demand_capacity", _node("resource", row.resource_id), source,
                    f"market:{provider.id}:demand:{row.resource_id}",
                    row.capacity_t, "t", "stock_capacity",
                    condition=f"replenishment_t_per_day:{row.replenishment_t_per_day:g};finite_provider_state",
                ))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("external_market", external_market, expected_definitions=lambda: (
        _node("market_provider", key) for key in sim.market.provider_defs
    ), relation_kinds={
        "external_buy_offer", "external_sell_offer", "external_supply_capacity", "external_demand_capacity",
    })

    def industry() -> DependencyFragment:
        nodes = []
        relations = []
        for process in sim.industry.processes.values():
            owner = _node("process", process.id)
            nodes.append(owner)
            for capability in process.required_capabilities:
                relations.append(DependencyRelation(
                    "requires_capability", _node("capability", capability), owner,
                    f"process:{process.id}:required_capabilities",
                ))
            for resource_id, amount in process.inputs_per_day.items():
                relations.append(DependencyRelation(
                    "consumes_resource", _node("resource", resource_id), owner,
                    f"process:{process.id}:inputs_per_day", amount, "t", "per_execution_day",
                ))
            for resource_id, amount in process.outputs_per_day.items():
                relations.append(DependencyRelation(
                    "produces_resource", owner, _node("resource", resource_id),
                    f"process:{process.id}:outputs_per_day", amount, "t", "per_execution_day",
                ))
            for tech in process.prerequisite_technologies:
                relations.append(DependencyRelation(
                    "unlocks_method", _node("technology", tech), owner,
                    f"process:{process.id}:prerequisite_technologies",
                ))
        if sim.extraction is not None:
            for method in sim.extraction.specs.values():
                owner = _node("extraction_method", method.id)
                nodes.append(owner)
                for capability in method.required_capabilities:
                    relations.append(DependencyRelation(
                        "requires_capability", _node("capability", capability), owner,
                        f"extraction:{method.id}:required_capabilities",
                    ))
                relations.append(DependencyRelation(
                    "extracts_resource", owner, _node("resource", method.output_resource_id),
                    f"extraction:{method.id}:output_resource_id",
                    condition="physical_opportunity_and_finite_installed_capacity_required",
                ))
                relations.append(DependencyRelation(
                    "requires_resource_opportunity", _node("resource", method.resource_id), owner,
                    f"extraction:{method.id}:resource_id",
                    condition="developed_cell_static_potential_and_local_distribution_required",
                ))
                context_contributors.contribute_site_requirements(
                    owner, "opportunity", method.opportunity_requirements, nodes, relations,
                )
                if method.minimum_knowledge_level is not None:
                    relations.append(DependencyRelation(
                        "requires_knowledge", _node("resource", method.resource_id), owner,
                        f"extraction:{method.id}:minimum_knowledge_level",
                        condition=f"target_cell_resource_level:{method.minimum_knowledge_level.name}",
                    ))
                for field_name in ("geology_accessibility_key", "terrain_accessibility_attribute"):
                    value = getattr(method, field_name)
                    if value is not None:
                        relations.append(DependencyRelation(
                            "requires_opportunity_factor", _node("opportunity_factor", f"{field_name}:{value}"), owner,
                            f"extraction:{method.id}:{field_name}",
                            condition="typed_static_cell_parameter;not_inventory",
                        ))
            for facility in sim.facilities.definitions.values():
                if facility.extraction_capacity_t_per_day <= 0:
                    continue
                method = sim.extraction.method_for_definition(facility.id)
                if method is None:
                    continue
                relations.append(DependencyRelation(
                    "nominal_extraction_capacity", _node("facility", facility.id),
                    _node("extraction_method", method.id),
                    f"facility:{facility.id}:extraction_capacity_t_per_day",
                    facility.extraction_capacity_t_per_day, "t/day", "per_facility_level",
                    condition="requires_developed_opportunity;actual_site_power_maintenance_and_allocation",
                ))
        if sim.extraction is not None:
            nodes.extend(_node("opportunity_factor", field + ":" + value) for field, values in (
                ("geology_accessibility_key", {spec.geology_accessibility_key for spec in sim.extraction.specs.values()}),
                ("terrain_accessibility_attribute", {spec.terrain_accessibility_attribute for spec in sim.extraction.specs.values()}),
            ) for value in sorted(row for row in values if row is not None))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("production_and_extraction", industry, expected_definitions=lambda: (
        list(_node("process", key) for key in sim.industry.processes) +
        list(_node("extraction_method", key) for key in (() if sim.extraction is None else sim.extraction.specs))
    ), relation_kinds={
        "requires_capability", "consumes_resource", "produces_resource", "unlocks_method",
        "extracts_resource", "requires_resource_opportunity", "requires_knowledge",
        "requires_opportunity_factor", "requires_site_capability", "requires_site_classification",
        "requires_site_environment", "nominal_extraction_capacity",
    })

    def construction() -> DependencyFragment:
        nodes: list[DependencyNode] = []
        relations: list[DependencyRelation] = []

        def add_method(kind: str, identity: str, recipe, *, scope: str) -> DependencyNode:
            """Observe the typed Project Recipe, not a particular Facility or Scenario."""
            owner = _node(kind, identity)
            nodes.append(owner)
            provenance = f"{kind}:{identity}"
            for requirement in recipe.resources:
                relations.append(DependencyRelation(
                    "consumes_resource", _node("resource", requirement.resource_id), owner,
                    f"{provenance}:resources:{requirement.resource_id}",
                    requirement.amount_t, "t", "per_project",
                ))
            for technology in sorted(recipe.prerequisite_technologies):
                relations.append(DependencyRelation(
                    "unlocks_method", _node("technology", technology), owner,
                    f"{provenance}:prerequisite_technologies",
                    condition="acquisition_eligibility_not_retroactive_asset_modification",
                ))
            if recipe.construction_work > 0 and not recipe.self_deploying:
                relations.append(DependencyRelation(
                    "requires_construction_work", _node("service_capacity", CONSTRUCTION_SERVICE_TYPE), owner,
                    f"{provenance}:construction_work", recipe.construction_work,
                    "work_units", "per_project",
                    condition="shared_finite_construction_work;requires_real_site_and_provider",
                ))
            context_contributors.contribute_site_requirements(
                owner, scope, recipe.site_requirements, nodes, relations,
            )
            return owner

        for recipe in sim.projects.recipes.values():
            owner = add_method("construction_method", str(recipe.facility_def_id), recipe, scope="construction")
            relations.append(DependencyRelation(
                "constructs_facility", owner, _node("facility", recipe.facility_def_id),
                f"construction:{recipe.facility_def_id}:facility_def_id",
            ))
        for recipe in sim.projects.upgrade_recipes.values():
            identity = f"{recipe.facility_def_id}/level:{recipe.target_level}"
            owner = add_method("facility_upgrade_method", identity, recipe, scope="upgrade")
            relations.append(DependencyRelation(
                "upgrades_facility", _node("facility", recipe.facility_def_id), owner,
                f"upgrade:{identity}:facility_def_id",
                condition=f"from_level:{recipe.target_level - 1};to_level:{recipe.target_level}",
            ))
        for recipe in sim.projects.decommission_recipes.values():
            owner = add_method("facility_decommission_method", str(recipe.facility_def_id), recipe, scope="decommission")
            relations.append(DependencyRelation(
                "decommissions_facility", _node("facility", recipe.facility_def_id), owner,
                f"decommission:{recipe.facility_def_id}:facility_def_id",
                condition="irreversible_commitment_and_recovery_admission_required",
            ))
        for recipe in sim.projects.spatial_recipes.values():
            owner = add_method("spatial_development_method", str(recipe.id), recipe, scope="spatial_development")
            for requirement in recipe.knowledge_requirements:
                relations.append(DependencyRelation(
                    "requires_knowledge", _node("resource", requirement.subject_resource_id), owner,
                    f"spatial_development:{recipe.id}:knowledge:{requirement.subject_resource_id}",
                    condition=f"minimum_level:{requirement.minimum_level.value};target_cell_required",
                ))
        for provider in sim.projects.construction_providers.values():
            relations.append(DependencyRelation(
                "nominal_construction_service_supply", _node("facility", provider.facility_def_id),
                _node("service_capacity", CONSTRUCTION_SERVICE_TYPE),
                f"construction_provider:{provider.facility_def_id}:work_per_day",
                provider.work_per_day, "work_units/day", "per_active_facility_level",
                condition="actual_power_maintenance_site_allocation_required",
            ))
        for provider in sim.projects.construction_resource_providers.values():
            relations.append(DependencyRelation(
                "nominal_resource_construction_supply", _node("resource", provider.resource_id),
                _node("service_capacity", CONSTRUCTION_SERVICE_TYPE),
                f"construction_resource_provider:{provider.resource_id}:work_per_t_per_day",
                provider.work_per_t_per_day, "work_units/t/day", "per_available_stock",
                condition="non_consuming_available_unreserved_stock",
            ))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("construction", construction, expected_definitions=lambda: (
        *(_node("construction_method", key) for key in sim.projects.recipes),
        *(_node("facility_upgrade_method", f"{key[0]}/level:{key[1]}") for key in sim.projects.upgrade_recipes),
        *(_node("facility_decommission_method", key) for key in sim.projects.decommission_recipes),
        *(_node("spatial_development_method", key) for key in sim.projects.spatial_recipes),
    ), relation_kinds={
        "constructs_facility", "upgrades_facility", "decommissions_facility",
        "consumes_resource", "unlocks_method", "requires_construction_work",
        "requires_site_capability", "requires_site_classification", "requires_site_environment",
        "requires_knowledge", "nominal_construction_service_supply", "nominal_resource_construction_supply",
    })

    def vehicle_production() -> DependencyFragment:
        nodes = []
        relations = []
        for vehicle in sim.transport.vehicle_definitions():
            owner = _node("vehicle", vehicle.id)
            production = _node("vehicle_production_method", vehicle.id)
            nodes.extend((owner, production))
            relations.append(DependencyRelation(
                "produces_vehicle", production, owner, f"vehicle:{vehicle.id}:production",
            ))
            for capability in vehicle.generic_capabilities:
                relations.append(DependencyRelation(
                    "supplies_capability", owner, _node("capability", capability),
                    f"vehicle:{vehicle.id}:capabilities",
                ))
            for resource_id, amount in vehicle.production.resources:
                relations.append(DependencyRelation(
                    "consumes_resource", _node("resource", resource_id), production,
                    f"vehicle:{vehicle.id}:production.resources", amount, "t", "per_vehicle",
                ))
            for technology in vehicle.production.prerequisite_technologies:
                relations.append(DependencyRelation(
                    "unlocks_method", _node("technology", technology), production,
                    f"vehicle:{vehicle.id}:production.prerequisite_technologies",
                ))
            if vehicle.production.service_type is not None:
                relations.append(DependencyRelation(
                    "requires_service_capacity", _node("service_capacity", vehicle.production.service_type), production,
                    f"vehicle:{vehicle.id}:production.service_type",
                    condition=f"production_days:{vehicle.production.days:g};installed_service_required",
                ))
            if vehicle.maintenance.turnaround_days or vehicle.maintenance.resources or vehicle.maintenance.service_type:
                method = _node("vehicle_turnaround_method", vehicle.id)
                nodes.append(method)
                relations.append(DependencyRelation(
                    "uses_asset_definition", owner, method, f"vehicle:{vehicle.id}:maintenance",
                ))
                if vehicle.maintenance.service_type is not None:
                    relations.append(DependencyRelation(
                        "requires_service_capacity", _node("service_capacity", vehicle.maintenance.service_type), method,
                        f"vehicle:{vehicle.id}:maintenance.service_type",
                        condition=f"turnaround_days:{vehicle.maintenance.turnaround_days:g}",
                    ))
                for resource_id, amount in vehicle.maintenance.resources:
                    relations.append(DependencyRelation(
                        "consumes_resource", _node("resource", resource_id), method,
                        f"vehicle:{vehicle.id}:maintenance.resources:{resource_id}",
                        amount, "t", "per_turnaround",
                    ))
            if vehicle.retirement.enabled:
                method = _node("vehicle_retirement_method", vehicle.id)
                nodes.append(method)
                relations.append(DependencyRelation(
                    "retires_vehicle", owner, method, f"vehicle:{vehicle.id}:retirement",
                    vehicle.retirement.work_days_per_unit, "work_days", "per_vehicle",
                ))
                if vehicle.retirement.service_type is not None:
                    relations.append(DependencyRelation(
                        "requires_service_capacity", _node("service_capacity", vehicle.retirement.service_type), method,
                        f"vehicle:{vehicle.id}:retirement.service_type",
                    ))
                for resource_id, amount in vehicle.retirement.resources_per_unit:
                    relations.append(DependencyRelation(
                        "consumes_resource", _node("resource", resource_id), method,
                        f"vehicle:{vehicle.id}:retirement.resources_per_unit:{resource_id}",
                        amount, "t", "per_vehicle",
                    ))
                for resource_id, amount in vehicle.retirement.recovery_resources_per_unit:
                    relations.append(DependencyRelation(
                        "recovers_resource", method, _node("resource", resource_id),
                        f"vehicle:{vehicle.id}:retirement.recovery_resources_per_unit:{resource_id}",
                        amount, "t", "maximum_recovery_per_vehicle",
                        condition="requires_irreversible_retirement_and_usable_storage",
                    ))
            if vehicle.passengers.seats:
                method = _node("onboard_life_support_method", vehicle.id)
                nodes.append(method)
                relations.append(DependencyRelation(
                    "nominal_passenger_seats", owner, _node("capacity_pool", "passenger_seats"),
                    f"vehicle:{vehicle.id}:passengers.seats", vehicle.passengers.seats,
                    "people", "per_vehicle",
                ))
                relations.append(DependencyRelation(
                    "uses_asset_definition", owner, method, f"vehicle:{vehicle.id}:passengers",
                ))
                relations.append(DependencyRelation(
                    "nominal_life_support_supply", method, _node("service_capacity", "onboard_life_support"),
                    f"vehicle:{vehicle.id}:passengers.life_support_person_days_per_day",
                    vehicle.passengers.life_support_person_days_per_day,
                    "person_days/day", "per_vehicle", condition="onboard_power_and_provisions_required",
                ))
                for resource_id, rate in vehicle.passengers.net_resources_per_person_day:
                    relations.append(DependencyRelation(
                        "consumes_resource", _node("resource", resource_id), method,
                        f"vehicle:{vehicle.id}:passengers.net_resources_per_person_day:{resource_id}",
                        rate, "t/person_day", "per_onboard_person_day",
                    ))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("vehicle_production", vehicle_production, expected_definitions=lambda: (
        _node("vehicle", definition.id) for definition in sim.transport.vehicle_definitions()
    ), relation_kinds={
        "produces_vehicle", "supplies_capability", "consumes_resource", "unlocks_method",
        "requires_service_capacity", "uses_asset_definition", "retires_vehicle",
        "recovers_resource", "nominal_passenger_seats", "nominal_life_support_supply",
    })

    def observations() -> DependencyFragment:
        nodes = []
        relations = []
        if sim.survey is not None:
            # A target is a physical Cell x Resource pair, not an Operational Node
            # or an inventory owned by a Provider. Levels are authored thresholds.
            knowledge_levels = tuple(level for level in KnowledgeLevel if level is not KnowledgeLevel.UNKNOWN)
            nodes.extend(_node("survey_knowledge_level", level.name) for level in knowledge_levels)
            nodes.extend(_node("survey_reach_scope", scope.value) for scope in SurveyReachScope)
            nodes.extend(_node("survey_parameter", key) for key in (
                "progress", "distance", "delta_v", "uncertainty", "precision",
            ))
            for target in sim.survey.targets.values():
                subject = _node("survey_target", f"{target.cell_id}/{target.resource_id}")
                nodes.append(subject)
                relations.extend((
                    DependencyRelation("targets_surface_cell", subject, _node("surface_cell", target.cell_id),
                                       f"survey_target:{subject.id}:cell_id"),
                    DependencyRelation("observes_resource", subject, _node("resource", target.resource_id),
                                       f"survey_target:{subject.id}:resource_id",
                                       condition=f"prior_presence_probability:{target.prior_presence_probability:g}"),
                ))
                for level, threshold in zip(knowledge_levels, target.thresholds):
                    relations.append(DependencyRelation(
                        "survey_knowledge_threshold", subject, _node("survey_knowledge_level", level.name),
                        f"survey_target:{subject.id}:thresholds:{level.name}",
                        threshold, "survey_progress", "per_cell_resource_level",
                    ))
            for provider in sim.survey.providers.values():
                owner = _node("survey_provider", provider.id)
                nodes.append(owner)
                for capability in sorted(provider.required_source_capabilities):
                    relations.append(DependencyRelation(
                        "requires_capability", _node("capability", capability), owner,
                        f"survey_provider:{provider.id}:required_source_capabilities",
                    ))
                for source_id in sim.survey.compatible_source_definition_ids(provider):
                    asset_kind = ("facility" if provider.source_kind is SurveyProviderSourceKind.FACILITY else "vehicle")
                    asset = _node(asset_kind, source_id)
                    service = _node("service_capacity", sim.survey.service_type_for_provider(provider.id, source_id))
                    relations.extend((
                        DependencyRelation("uses_asset_definition", asset, owner,
                                           f"survey_provider:{provider.id}:source_capabilities",
                                           condition="definition_compatible;real_installed_or_committed_source_required"),
                        DependencyRelation("nominal_survey_service_supply", asset, service,
                                           f"survey_provider:{provider.id}:capacity_units_per_source_per_day:{source_id}",
                                           provider.capacity_units_per_source_per_day, "survey_capacity_units/day",
                                           "per_active_source_unit", condition="power_site_commitment_and_shared_allocation_required"),
                    ))
                for mode in provider.observation_modes:
                    mode_node = _node("survey_mode", f"{provider.id}/{mode.id}")
                    nodes.append(mode_node)
                    provenance = f"survey:{provider.id}/{mode.id}"
                    relations.append(DependencyRelation(
                        "provides_mode", owner, mode_node,
                        f"survey:{provider.id}:observation_modes",
                    ))
                    for capability in sorted(mode.required_source_capabilities):
                        relations.append(DependencyRelation(
                            "requires_capability", _node("capability", capability), mode_node,
                            f"{provenance}:required_source_capabilities",
                        ))
                    context_contributors.contribute_site_requirements(
                        mode_node, "survey_provider_site", mode.site_requirements, nodes, relations,
                    )
                    relations.extend((
                        DependencyRelation("requires_survey_reach", _node("survey_reach_scope", mode.reach.scope.value),
                                           mode_node, f"{provenance}:reach.scope",
                                           condition="physical_context_not_initial_body_id"),
                        DependencyRelation("nominal_survey_progress", mode_node,
                                           _node("survey_parameter", "progress"), f"{provenance}:survey_rate",
                                           mode.survey_rate, "survey_progress/capacity_unit", "per_allocated_survey_unit"),
                        DependencyRelation("minimum_source_units", owner, mode_node,
                                           f"{provenance}:minimum_source_units", mode.minimum_source_units,
                                           "source_units", "per_concurrent_mode", condition="source_definition_specific"),
                        DependencyRelation("max_survey_knowledge", mode_node,
                                           _node("survey_knowledge_level", mode.max_knowledge_level.name),
                                           f"{provenance}:max_knowledge_level"),
                    ))
                    for value, name in ((mode.estimate_uncertainty_fraction, "uncertainty"),
                                        (mode.measurement_precision_fraction, "precision")):
                        relations.append(DependencyRelation(
                            "nominal_survey_measurement", mode_node, _node("survey_parameter", name),
                            f"{provenance}:{name}", value, "fraction", "per_observation_mode",
                        ))
                    for value, name, unit in (
                        (mode.reach.max_characteristic_distance_km, "distance", "km"),
                        (mode.reach.max_characteristic_delta_v_km_s, "delta_v", "km/s"),
                    ):
                        if value is not None:
                            relations.append(DependencyRelation(
                                "max_survey_reach", mode_node, _node("survey_parameter", name),
                                f"{provenance}:reach:{name}", value, unit, "per_observation_mode",
                            ))
                    for operation in sorted(mode.reach.required_operation_types):
                        relations.append(DependencyRelation(
                            "requires_operation", _node("transport_operation", operation), mode_node,
                            f"{provenance}:reach.required_operation_types:{operation}",
                        ))
                    for source_id in sim.survey.compatible_mode_source_definition_ids(provider, mode):
                        # The same Asset may support some modes but not all.
                        relations.append(DependencyRelation(
                            "requires_service_capacity", _node("service_capacity",
                                sim.survey.service_type_for_provider(provider.id, source_id)), mode_node,
                            f"{provenance}:service_capacity:{source_id}",
                            condition="one_of_compatible_physical_sources;per_execution_unit",
                        ))
                    for technology in sorted(mode.prerequisite_technologies):
                        relations.append(DependencyRelation(
                            "unlocks_method", _node("technology", technology), mode_node,
                            f"{provenance}:prerequisite_technologies",
                        ))
        if sim.scientific_exploration is not None:
            from ..transport.models import MovementEndpoint
            for definition in sim.scientific_exploration.definitions.values():
                owner = _node("scientific_exploration", definition.id)
                nodes.append(owner)
                origin = _node("spatial_node", definition.origin_id)
                target_kind = (
                    "surface_cell" if isinstance(definition.destination, MovementEndpoint)
                    and definition.destination.physical_target_cell_id is not None
                    else "spatial_node"
                )
                target = _node(target_kind, definition.destination_id)
                provenance = f"scientific_exploration:{definition.id}"
                relations.extend((
                    DependencyRelation(
                        "requires_origin_context", origin, owner,
                        f"{provenance}:origin_id", condition="real_departure_site_and_movement_required",
                    ),
                    DependencyRelation(
                        "targets_spatial_context", owner, target,
                        f"{provenance}:destination", condition=(
                            "physical_target_no_automatic_operational_node" if isinstance(definition.destination, MovementEndpoint)
                            else "operational_destination_required"
                        ),
                    ),
                    DependencyRelation(
                        "requires_fleet_units", _node("capacity_pool", "fleet_units"), owner,
                        f"{provenance}:required_units", definition.required_units,
                        "units", "per_campaign_commitment", condition="real_fleet_commitment_and_movement_required",
                    ),
                    DependencyRelation(
                        "campaign_duration", owner, _node("exploration_parameter", "duration"),
                        f"{provenance}:duration_days", definition.duration_days,
                        "days", "per_campaign", condition="after_physical_arrival",
                    ),
                    DependencyRelation(
                        "finite_research_point_reward", owner,
                        _node("research_point_pool", "research_points"),
                        f"{provenance}:research_points_total",
                        definition.research_points_total, "research_points", "per_completed_campaign",
                        condition="finite_reward;rp_pool_admission_required",
                    ),
                ))
                for rid, amount in definition.consumable_resources:
                    relations.append(DependencyRelation(
                        "consumes_resource", _node("resource", rid), owner,
                        f"{provenance}:consumable_resources:{rid}", amount, "t", "per_campaign",
                        condition="actual_launch_site_inventory_settlement_required",
                    ))
                if definition.required_crew:
                    relations.append(DependencyRelation(
                        "requires_population_commitment", _node("capacity_pool", "population"), owner,
                        f"{provenance}:required_crew", definition.required_crew,
                        "people", "per_campaign_commitment", condition="real_crew_and_onboard_support_required",
                    ))
                for capability in definition.required_vehicle_capabilities:
                    relations.append(DependencyRelation(
                        "requires_capability", _node("capability", capability), owner,
                        f"{provenance}:required_vehicle_capabilities:{capability}",
                        condition="compatible_real_vehicle_required",
                    ))
                for scope, requirements in (("origin", definition.origin_requirements),
                                            ("destination", definition.destination_requirements)):
                    context_contributors.contribute_site_requirements(owner, scope, requirements, nodes, relations)
                for technology in definition.prerequisite_technologies:
                    relations.append(DependencyRelation(
                        "unlocks_method", _node("technology", technology), owner,
                        f"{provenance}:prerequisite_technologies",
                    ))
            nodes.append(_node("exploration_parameter", "duration"))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("observation", observations, expected_definitions=lambda: (
        list(_node("survey_provider", key) for key in (() if sim.survey is None else sim.survey.providers)) +
        list(_node("survey_target", f"{cell_id}/{resource_id}") for cell_id, resource_id in (
            () if sim.survey is None else sim.survey.targets)) +
        list(_node("scientific_exploration", key) for key in (
            () if sim.scientific_exploration is None else sim.scientific_exploration.definitions))
    ), relation_kinds={
        "provides_mode", "requires_capability", "unlocks_method", "uses_asset_definition",
        "finite_research_point_reward", "consumes_resource", "requires_fleet_units",
        "requires_population_commitment", "requires_origin_context", "targets_spatial_context",
        "campaign_duration", "requires_site_capability", "requires_site_classification",
        "requires_site_environment", "targets_surface_cell", "observes_resource",
        "survey_knowledge_threshold", "uses_asset_definition", "nominal_survey_service_supply",
        "requires_survey_reach", "nominal_survey_progress", "minimum_source_units",
        "max_survey_knowledge", "nominal_survey_measurement", "max_survey_reach",
        "requires_operation", "requires_service_capacity",
    })

    registry.register('world', lambda: context_contributors.world(sim),
                      expected_definitions=lambda: (
                          [_node('star_system', key) for key in sim.graph.star_systems]
                          + [_node('body', key) for key in sim.graph.bodies]
                          + [_node('spatial_node', key) for key in sim.graph.nodes]
                          + [_node('surface_cell', key) for key in sim.graph.surface_cells]
                      ), relation_kinds=context_contributors.WORLD_RELATIONS)
    registry.register('movement', lambda: context_contributors.movement(sim),
                      expected_definitions=lambda: (
                          [_node('surface_movement_rule', r.id) for r in sim.transport.surface_movement_rules]
                          + [_node('surface_access_movement_rule', r.id) for r in sim.transport.surface_access_movement_rules]
                          + [_node('spaceflight_movement_rule', r.id) for r in sim.transport.spaceflight_movement_rules]
                      ), relation_kinds=context_contributors.MOVEMENT_RELATIONS)
    registry.register('founding', lambda: context_contributors.founding(sim),
                      expected_definitions=lambda: (
                          _node('founding_method', key) for key in (
                              () if sim.founding is None else sim.founding.deployment_recipes)
                      ), relation_kinds=context_contributors.FOUNDING_RELATIONS)
    registry.register('population', lambda: context_contributors.population(sim),
                      expected_definitions=lambda: (
                          _node('external_population_source', key) for key in (
                              () if sim.population is None else sim.population.external_definitions)
                      ), relation_kinds=context_contributors.POPULATION_RELATIONS)
    for name, contributor, kinds in additional_contributors:
        registry.register(name, contributor, relation_kinds=kinds)
    return registry.build()

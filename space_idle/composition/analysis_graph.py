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
                for mode in provider.observation_modes:
                    all_capabilities.update(mode.required_source_capabilities)
        if sim.research is not None:
            for technology in sim.research.definitions.values():
                for stage in technology.stage_specs:
                    if isinstance(stage, (ResearchPrototypeStageSpec, ResearchDemonstrationStageSpec)):
                        all_capabilities.update(
                            requirement.capability_id
                            for requirement in stage.site_requirements.capability_requirements
                        )
        services = {"power", "life_support", "onboard_life_support"}
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
                    for requirement in stage.site_requirements.capability_requirements:
                        relations.append(DependencyRelation(
                            "requires_capability", _node("capability", requirement.capability_id), stage_node,
                            f"{provenance}:site_capabilities:{requirement.capability_id}",
                            condition=f"required_state:{requirement.required_state.value}",
                        ))
                    for requirement in stage.site_requirements.spatial_classification_requirements:
                        relations.append(DependencyRelation(
                            "requires_site_condition", stage_node, owner,
                            f"{provenance}:spatial_classification:{requirement.code}",
                            condition=f"classification:{requirement.classification.value}",
                        ))
                    for requirement in stage.site_requirements.environment:
                        relations.append(DependencyRelation(
                            "requires_site_condition", stage_node, owner,
                            f"{provenance}:environment:{requirement.code}",
                            condition=requirement.description,
                        ))
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
        "research_work", "consumes_resource", "requires_capability", "requires_site_condition",
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
                    condition=f"opportunity:{method.resource_id}",
                ))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("production_and_extraction", industry, expected_definitions=lambda: (
        list(_node("process", key) for key in sim.industry.processes) +
        list(_node("extraction_method", key) for key in (() if sim.extraction is None else sim.extraction.specs))
    ), relation_kinds={
        "requires_capability", "consumes_resource", "produces_resource", "unlocks_method",
        "extracts_resource",
    })

    def construction() -> DependencyFragment:
        nodes = []
        relations = []
        for recipe in sim.projects.recipes.values():
            owner = _node("construction_method", recipe.facility_def_id)
            nodes.append(owner)
            relations.append(DependencyRelation(
                "constructs_facility", owner, _node("facility", recipe.facility_def_id),
                f"construction:{recipe.facility_def_id}:facility_def_id",
            ))
            for requirement in recipe.resources:
                relations.append(DependencyRelation(
                    "consumes_resource", _node("resource", requirement.resource_id), owner,
                    f"construction:{recipe.facility_def_id}:resources", requirement.amount_t, "t", "per_facility",
                ))
            for technology in recipe.prerequisite_technologies:
                relations.append(DependencyRelation(
                    "unlocks_method", _node("technology", technology), owner,
                    f"construction:{recipe.facility_def_id}:prerequisite_technologies",
                ))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("construction", construction, expected_definitions=lambda: (
        _node("construction_method", key) for key in sim.projects.recipes
    ), relation_kinds={
        "constructs_facility", "consumes_resource", "unlocks_method",
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
            for provider in sim.survey.providers.values():
                owner = _node("survey_provider", provider.id)
                nodes.append(owner)
                for capability in sorted(provider.required_source_capabilities):
                    relations.append(DependencyRelation(
                        "requires_capability", _node("capability", capability), owner,
                        f"survey_provider:{provider.id}:required_source_capabilities",
                    ))
                for mode in provider.observation_modes:
                    mode_node = _node("survey_mode", f"{provider.id}/{mode.id}")
                    nodes.append(mode_node)
                    relations.append(DependencyRelation(
                        "provides_mode", owner, mode_node,
                        f"survey:{provider.id}:observation_modes",
                    ))
                    for capability in mode.required_source_capabilities:
                        relations.append(DependencyRelation(
                            "requires_capability", _node("capability", capability), mode_node,
                            f"survey:{provider.id}/{mode.id}:required_source_capabilities",
                        ))
                    for technology in mode.prerequisite_technologies:
                        relations.append(DependencyRelation(
                            "unlocks_method", _node("technology", technology), mode_node,
                            f"survey:{provider.id}/{mode.id}:prerequisite_technologies",
                        ))
        if sim.scientific_exploration is not None:
            for definition in sim.scientific_exploration.definitions.values():
                owner = _node("scientific_exploration", definition.id)
                nodes.append(owner)
                relations.append(DependencyRelation(
                    "finite_research_point_reward", owner,
                    _node("research_point_pool", "research_points"),
                    f"scientific_exploration:{definition.id}:research_points_total",
                    definition.research_points_total, "research_points", "per_completed_campaign",
                    condition="finite_reward;rp_pool_admission_required",
                ))
                for technology in definition.prerequisite_technologies:
                    relations.append(DependencyRelation(
                        "unlocks_method", _node("technology", technology), owner,
                        f"scientific_exploration:{definition.id}:prerequisite_technologies",
                    ))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("observation", observations, expected_definitions=lambda: (
        list(_node("survey_provider", key) for key in (() if sim.survey is None else sim.survey.providers)) +
        list(_node("scientific_exploration", key) for key in (
            () if sim.scientific_exploration is None else sim.scientific_exploration.definitions))
    ), relation_kinds={
        "provides_mode", "requires_capability", "unlocks_method", "uses_asset_definition",
        "finite_research_point_reward",
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

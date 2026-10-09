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
from ..research_models import ResearchTheoryStageSpec
from ..power import FixedGeneration, SolarGeneration
from ..inventory import DEFAULT_STORAGE_POOL_KEY
from ..simulation import Simulation


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
            + (_node("research_point_pool", "research_points"),),
            tuple(DependencyRelation(
                "uses_storage_pool", _node("resource", resource.id),
                _node("storage_pool", resource.storage_pool_key or DEFAULT_STORAGE_POOL_KEY),
                f"resource:{resource.id}:storage_pool_key",
            ) for resource in catalog.resources.values()),
        )

    registry.register("catalog", resources, relation_kinds={"uses_storage_pool"})

    def research() -> DependencyFragment:
        if sim.research is None:
            return DependencyFragment((), ())
        nodes = []
        relations = []
        for technology in sim.research.definitions.values():
            owner = _node("technology", technology.id)
            nodes.append(owner)
            for requirement in technology.prerequisites:
                relations.append(DependencyRelation(
                    "technology_prerequisite", _node("technology", requirement), owner,
                    f"research:{technology.id}:prerequisites",
                ))
            for stage in technology.stage_specs:
                stage_node = _node("research_stage", f"{technology.id}/{stage.stage_id}")
                nodes.append(stage_node)
                relations.append(DependencyRelation(
                    "research_stage", stage_node, owner, f"research:{technology.id}:stage:{stage.stage_id}",
                ))
                if isinstance(stage, ResearchTheoryStageSpec):
                    relations.append(DependencyRelation(
                        "research_point_cost", _node("research_point_pool", "research_points"), stage_node,
                        f"research:{technology.id}:stage:{stage.stage_id}",
                        quantity=stage.research_point_cost, unit="research_points",
                        time_basis="per_stage",
                    ))
        for provider in sim.research.providers.values():
            source = _node("vehicle" if provider.source_kind.value == "fleet" else "facility", provider.source_definition_id)
            target = _node("research_provider", provider.id)
            nodes.append(target)
            relations.append(DependencyRelation(
                "uses_asset_definition", source, target,
                f"research_provider:{provider.id}:source_definition_id",
            ))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("research", research, relation_kinds={
        "technology_prerequisite", "research_stage", "research_point_cost",
        "uses_asset_definition",
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
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("facility", facilities, relation_kinds={"supplies_capability"})

    def power_and_storage() -> DependencyFragment:
        # Nominal installed supply and load. Daily usable power and storage are
        # resolved from physical environment, pause, maintenance and allocation
        # by their owner domains, not inferred from these static edges.
        nodes = {_node("service_capacity", "power")}
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

    registry.register("external_market", external_market, relation_kinds={
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

    registry.register("production_and_extraction", industry, relation_kinds={
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

    registry.register("construction", construction, relation_kinds={
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
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("vehicle_production", vehicle_production, relation_kinds={
        "produces_vehicle", "supplies_capability", "consumes_resource", "unlocks_method",
    })

    def observations() -> DependencyFragment:
        nodes = []
        relations = []
        if sim.survey is not None:
            for provider in sim.survey.providers.values():
                owner = _node("survey_provider", provider.id)
                nodes.append(owner)
                relations.append(DependencyRelation(
                    "uses_asset_definition",
                    _node("vehicle" if provider.source_kind.value == "fleet" else "facility", provider.source_definition_id), owner,
                    f"survey_provider:{provider.id}:source_definition_id",
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
                for technology in definition.prerequisite_technologies:
                    relations.append(DependencyRelation(
                        "unlocks_method", _node("technology", technology), owner,
                        f"scientific_exploration:{definition.id}:prerequisite_technologies",
                    ))
        return DependencyFragment(tuple(nodes), tuple(relations))

    registry.register("observation", observations, relation_kinds={
        "provides_mode", "requires_capability", "unlocks_method", "uses_asset_definition",
    })

    for name, contributor, kinds in additional_contributors:
        registry.register(name, contributor, relation_kinds=kinds)
    return registry.build()

from __future__ import annotations

import json
from dataclasses import replace

from space_idle import build_game_application
from space_idle.analysis_graph import (
    DefinitionGraphRegistry, DependencyFragment, DependencyNode, DependencyRelation,
)
from space_idle.composition.analysis_graph import build_definition_dependency_graph
from space_idle.production import ProcessSpec
from space_idle.shared import DefinitionId


def test_registered_definition_graph_reuses_real_content_without_gameplay_side_effects():
    app = build_game_application()
    sim = app._simulation
    original_day = sim.day
    original_technology = sim.technology.completed.copy()
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert not graph.diagnostics
    assert sim.day == original_day
    assert sim.technology.completed == original_technology
    assert json.loads(json.dumps(graph.to_json_data())) == graph.to_json_data()
    assert any(edge.kind == "requires_capability" and edge.target.kind == "survey_provider"
               for edge in graph.relations)
    assert any(edge.kind == "uses_asset_definition" and edge.target.kind == "research_provider"
               for edge in graph.relations)

    sample = next(p for p in sim.industry.processes.values() if p.inputs_per_day and p.outputs_per_day)
    method = DependencyNode("process", str(sample.id))
    subset = graph.subset((method,))
    assert any(edge.target == method and edge.kind == "consumes_resource" for edge in subset.relations)
    assert any(edge.source == method and edge.kind == "produces_resource" for edge in subset.relations)

    # Movement methods must retain the physical gateway/body inputs when the
    # graph is filtered to an individual method (not just the global graph).
    for relation_kind in ("requires_gateway_capability", "requires_body_context"):
        relation = next(edge for edge in graph.relations if edge.kind == relation_kind)
        filtered = graph.subset((relation.target,))
        assert relation in filtered.relations

    # A new Definition participates without extending a Core ID table.
    extra = DefinitionId("test.process.unlisted")
    missing_resource = DefinitionId("test.resource.missing")
    sim.industry.processes[extra] = ProcessSpec(
        extra, "alternate plant process", sample.required_capabilities,
        {missing_resource: 2.0}, dict(sample.outputs_per_day),
    )
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert any(d.code == "undefined_reference" and d.node == DependencyNode("resource", str(missing_resource))
               for d in graph.diagnostics)
    assert any(e.target == DependencyNode("process", str(extra)) for e in graph.relations)


def test_research_stage_dependency_graph_keeps_typed_costs_sites_services_and_experience_sources():
    from space_idle.research import (
        ResearchDefinition, ResearchTheoryStageSpec, ResearchPrototypeStageSpec,
        ResearchDemonstrationStageSpec, ResearchOperationalExperienceStageSpec,
    )
    from space_idle.execution_requirements import ServiceCapacityRequirement
    from space_idle.service_capacity import ServiceCapacityScope
    from space_idle.site import (SiteRequirements, CapabilityRequirement, CapabilityRequirementState,
                                 SpatialClassificationRequirement, SpatialClassification,
                                 RequiresFacet)
    from space_idle.content import base_ids as ids
    from space_idle.spatial import AtmosphereField
    from space_idle.analysis_coverage import inspect_definition_coverage

    app = build_game_application()
    sim = app._simulation
    before = sim.day, sim.research.stored_points, sim.technology.completed.copy()
    target = DefinitionId("test.research.typed_graph")
    stage = DependencyNode("research_stage", f"{target}/prototype")
    sim.research.definitions[target] = ResearchDefinition(target, "Typed Stage Graph", (
        ResearchTheoryStageSpec("theory", 2.0),
        ResearchPrototypeStageSpec(
            "prototype", {ids.MACHINERY: 1.25},
            SiteRequirements(
                capability_requirements=(CapabilityRequirement(
                    "general_research_equipment", CapabilityRequirementState.ACTIVE,
                ),),
                spatial_classification_requirements=(SpatialClassificationRequirement(
                    SpatialClassification.SURFACE, "test.prototype.surface", "surface equipment",
                ),),
                environment=(RequiresFacet(AtmosphereField, "test.prototype.atmosphere", "atmosphere measured"),),
            ),
            (ServiceCapacityRequirement("research_execution", 0.6, scope=ServiceCapacityScope.ORGANIZATION),),
            required_work=4.0,
        ),
        ResearchDemonstrationStageSpec("demonstration", 3.0),
        ResearchOperationalExperienceStageSpec(
            "operational_experience", {ids.EXPERIENCE_MANUFACTURING_OPERATIONS: 2.0},
        ),
    ))
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert not graph.diagnostics
    def matches(kind, dest):
        return [row for row in graph.relations if row.kind == kind and row.target == dest]
    assert matches("consumes_resource", stage)[0].quantity == 1.25
    assert matches("consumes_resource", stage)[0].time_basis == "per_stage"
    assert matches("requires_site_capability", stage)[0].condition == "required_state:ACTIVE"
    site_classification = matches("requires_site_classification", stage)[0]
    assert site_classification.source == DependencyNode("spatial_classification", "SURFACE")
    site_environment = matches("requires_site_environment", stage)[0]
    assert site_environment.source.kind == "site_condition"
    assert "AtmosphereField" in site_environment.condition
    stage_subset = graph.subset((stage,))
    assert {"requires_site_capability", "requires_site_classification", "requires_site_environment"} <= {
        row.kind for row in stage_subset.relations if row.target == stage
    }
    # Requesting a Technology's partial graph retains its Research Stage and
    # the Stage's own resource/service/knowledge AND inputs transitively.
    technology_subset = graph.subset((DependencyNode("technology", str(target)),))
    assert stage in technology_subset.nodes
    assert any(row.kind == "research_stage" and row.source == stage
               for row in technology_subset.relations)
    assert {"consumes_resource", "requires_site_capability", "requires_execution_capacity"} <= {
        row.kind for row in technology_subset.relations if row.target == stage
    }
    assert matches("requires_execution_capacity", stage)[0].quantity == 0.6
    assert matches("requires_execution_capacity", stage)[0].condition == "scope:ORGANIZATION"
    assert matches("research_work", DependencyNode("technology", str(target)))
    experience = DependencyNode("research_stage", f"{target}/operational_experience")
    required = matches("requires_experience", experience)
    assert len(required) == 1 and required[0].quantity == 2.0
    assert any(row.kind == "contributes_experience" and row.target == required[0].source
               for row in graph.relations)
    assert before == (sim.day, sim.research.stored_points, sim.technology.completed)

    # A research requirement unsupported by any registered Domain activity is
    # a genuine unbound reference, not an inferred zero-cost source.
    definition = sim.research.definitions[target]
    sim.research.definitions[target] = replace(
        definition, stage_specs=definition.stage_specs[:-1] + (
            ResearchOperationalExperienceStageSpec("operational_experience", {"unknown.experience": 1.0}),
        ),
    )
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert any(row.code == "undefined_reference" and row.node == DependencyNode(
        "experience_category", "unknown.experience") for row in graph.diagnostics)

    # Site capability authoring gaps must be visible to the coverage analyzer,
    # including Research Stage constraints, rather than silently ignored.
    unrelated = sim.research.definitions[target]
    prototype = unrelated.stage_specs[1]
    sim.research.definitions[target] = replace(unrelated, stage_specs=(
        unrelated.stage_specs[0],
        replace(prototype, site_requirements=SiteRequirements(capability_requirements=(
            CapabilityRequirement("test.no_physical_supplier"),
        ))),
    ))
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert not graph.diagnostics
    assert any(row.code == "required_capability_without_definition_supplier"
               and row.subject == DependencyNode("capability", "test.no_physical_supplier")
               for row in inspect_definition_coverage(graph))


def test_registered_contributor_schema_detects_missing_types_duplicates_and_bad_relations():
    a = DependencyNode("a", "one")
    b = DependencyNode("b", "two")
    registry = DefinitionGraphRegistry()
    registry.register("source", lambda: DependencyFragment((a,), (
        DependencyRelation("unknown", a, b, "contributor:source"),
    )), relation_kinds={"declared"})
    registry.register("duplicated", lambda: DependencyFragment((a,), ()), relation_kinds={"declared"})
    graph = registry.build()
    assert {d.code for d in graph.diagnostics} == {
        "unknown_relation_kind", "undefined_reference", "duplicate_definition_owner",
    }

    # Typed coverage reports missing registered paths, without making a claim
    # about scenario initial stocks or current physical execution eligibility.
    from space_idle.analysis_coverage import inspect_definition_coverage
    from space_idle.analysis_graph import DependencyDefinitionGraph

    resource = DependencyNode("resource", "test.resource.input")
    service = DependencyNode("service_capacity", "test.service")
    process = DependencyNode("process", "test.process")
    facility = DependencyNode("facility", "test.facility")
    vehicle = DependencyNode("vehicle", "test.vehicle")
    nodes = (resource, service, process, facility, vehicle)
    requirements = (
        DependencyRelation("consumes_resource", resource, process, "process:input"),
        DependencyRelation("requires_service_capacity", service, process, "process:service"),
    )
    findings = inspect_definition_coverage(DependencyDefinitionGraph(nodes, requirements, ()))
    assert {f.code for f in findings} == {
        "resource_demand_without_registered_replenishment",
        "service_demand_without_registered_capacity_supplier",
    }
    assert all(f.significance == "informational" and f.evidence for f in findings)
    # Any registered supplier is an alternative, not an AND requirement; it
    # removes the missing-definition finding but proves no current stock/flow.
    supplies = (
        DependencyRelation("external_buy_offer", process, resource, "market:offer"),
        DependencyRelation("nominal_service_supply", facility, service, "facility:service"),
        DependencyRelation("constructs_facility", process, facility, "build:fixture"),
        DependencyRelation("decommissions_facility", facility, process, "decommission:fixture"),
        DependencyRelation("produces_vehicle", process, vehicle, "production:fixture"),
        DependencyRelation("retires_vehicle", vehicle, process, "retire:fixture"),
    )
    covered = inspect_definition_coverage(DependencyDefinitionGraph(nodes, requirements + supplies, ()))
    # Coverage is complete, but construction is conditionally self-dependent:
    # the only provider of the required service is the facility being acquired.
    assert {f.code for f in covered} == {"potential_asset_self_bootstrap_dependency"}
    assert covered[0].subject == facility

    # A first installed asset cannot be its own exclusive construction service
    # source. This is only a conditional authoring risk: an alternative source
    # (OR), or a second acquisition method, removes it without inventing State.
    work = DependencyNode("service_capacity", "test.work")
    recipe = DependencyNode("construction_method", "test.build_facility")
    self_only = (
        DependencyRelation("constructs_facility", recipe, facility, "test:build"),
        DependencyRelation("requires_construction_work", work, recipe, "test:work"),
        DependencyRelation("nominal_construction_service_supply", facility, work, "test:self"),
    )
    self_graph = DependencyDefinitionGraph((facility, work, recipe), self_only, ())
    assert any(row.code == "potential_asset_self_bootstrap_dependency" and row.subject == facility
               for row in inspect_definition_coverage(self_graph))
    alternate = DependencyRelation("nominal_construction_service_supply", vehicle, work, "test:other")
    assert not any(row.code == "potential_asset_self_bootstrap_dependency"
                   for row in inspect_definition_coverage(DependencyDefinitionGraph(
                       (facility, vehicle, work, recipe), self_only + (alternate,), ())))
    self_deploy_method = DependencyNode("construction_method", "test.self_deploy")
    method_alternative = DependencyRelation("constructs_facility", self_deploy_method, facility,
                                            "test:independent")
    assert not any(row.code == "potential_asset_self_bootstrap_dependency"
                   for row in inspect_definition_coverage(DependencyDefinitionGraph(
                       (facility, work, recipe, self_deploy_method), self_only + (method_alternative,), ())))


def test_definition_acquisition_cycles_keep_alternative_methods_and_unknown_sources_distinct():
    from space_idle.analysis_coverage import inspect_definition_coverage
    from space_idle.analysis_graph import DependencyDefinitionGraph

    a = DependencyNode("facility", "test.asset.a")
    b = DependencyNode("vehicle", "test.asset.b")
    c = DependencyNode("facility", "test.asset.c")
    service_a = DependencyNode("service_capacity", "test.service.a")
    service_b = DependencyNode("service_capacity", "test.service.b")
    method_a = DependencyNode("construction_method", "test.acquire.a")
    method_b = DependencyNode("vehicle_production_method", "test.acquire.b")
    method_c = DependencyNode("construction_method", "test.acquire.c")
    nodes = (a, b, c, service_a, service_b, method_a, method_b, method_c)
    circular = (
        DependencyRelation("constructs_facility", method_a, a, "test:acquire:a"),
        DependencyRelation("produces_vehicle", method_b, b, "test:acquire:b"),
        DependencyRelation("constructs_facility", method_c, c, "test:acquire:c"),
        DependencyRelation("nominal_service_supply", a, service_a, "test:service:a"),
        DependencyRelation("nominal_service_supply", b, service_b, "test:service:b"),
        DependencyRelation("requires_service_capacity", service_b, method_a, "test:need:b"),
        DependencyRelation("requires_service_capacity", service_a, method_b, "test:need:a"),
        DependencyRelation("requires_service_capacity", service_a, method_c, "test:need:a:other"),
    )
    risks = [r for r in inspect_definition_coverage(DependencyDefinitionGraph(nodes, circular, ()))
             if r.code == "potential_asset_acquisition_dependency_cycle"]
    assert len(risks) == 1
    assert risks[0].subject == a
    assert {f"member:{node.kind}:{node.id}" for node in (a, b)} <= set(risks[0].evidence)
    assert f"member:{c.kind}:{c.id}" not in risks[0].evidence

    independent_method = DependencyNode("construction_method", "test.acquire.b.alternative")
    independent = (
        DependencyRelation("produces_vehicle", independent_method, b, "test:alternative"),
    )
    # Any physically independent method breaks the OR dependency loop.
    resolved = inspect_definition_coverage(DependencyDefinitionGraph(
        nodes + (independent_method,), circular + independent, ()))
    assert not any(r.code == "potential_asset_acquisition_dependency_cycle" for r in resolved)

    # Missing definition providers are a separate coverage gap. They do not
    # magically make an unknown initial Scenario physically impossible.
    external = DependencyNode("service_capacity", "test.unknown.service")
    missing_input = DependencyRelation("requires_service_capacity", external, method_b, "test:unknown")
    unknown = inspect_definition_coverage(DependencyDefinitionGraph(
        nodes + (external,), circular + (missing_input,), ()))
    assert any(r.code == "service_demand_without_registered_capacity_supplier" for r in unknown)
    assert any(r.code == "potential_asset_acquisition_dependency_cycle" for r in unknown)


def test_definition_resource_acquisition_cycles_preserve_alternative_sources_and_physical_inputs():
    from space_idle.analysis_coverage import inspect_definition_coverage
    from space_idle.analysis_graph import DependencyDefinitionGraph

    def node(kind, key):
        return DependencyNode(kind, f"test.{key}")

    facility = node("facility", "smelter")
    capability = node("capability", "smelt")
    ore = node("resource", "ore")
    metal = node("resource", "metal")
    construction = node("construction_method", "smelter.build")
    process = node("process", "metal.from.ore")
    extraction = node("extraction_method", "ore.extract")
    source_facility = node("facility", "mine")
    mine_build = node("construction_method", "mine.build")
    graph_nodes = (facility, capability, ore, metal, construction, process,
                   extraction, source_facility, mine_build)
    relations = (
        DependencyRelation("constructs_facility", construction, facility, "test:build"),
        DependencyRelation("consumes_resource", metal, construction, "test:build:metal"),
        DependencyRelation("supplies_capability", facility, capability, "test:smelt"),
        DependencyRelation("requires_capability", capability, process, "test:process:smelt"),
        DependencyRelation("consumes_resource", ore, process, "test:process:ore"),
        DependencyRelation("produces_resource", process, metal, "test:process:metal"),
        DependencyRelation("constructs_facility", mine_build, source_facility, "test:build:mine"),
        DependencyRelation("nominal_extraction_capacity", source_facility, extraction,
                           "test:extraction:installed_capacity"),
        DependencyRelation("extracts_resource", extraction, ore, "test:extraction:ore"),
    )

    def risks(edges, nodes=graph_nodes):
        return [finding for finding in inspect_definition_coverage(
            DependencyDefinitionGraph(nodes, edges, ())
        ) if finding.code == "potential_resource_acquisition_dependency_cycle"]

    circular = risks(relations)
    assert len(circular) == 1
    assert {"member:facility:test.smelter", "member:resource:test.metal"} <= set(circular[0].evidence)
    assert "member:resource:test.ore" not in circular[0].evidence
    assert "initial_stock_assets_and_external_conditions_unknown" in " ".join(circular[0].evidence)
    assert "method:construction_method:test.smelter.build:needs:resource:test.metal" in circular[0].evidence
    assert "method:process:test.metal.from.ore:needs:facility:test.smelter" in circular[0].evidence
    assert all(finding.significance == "informational" for finding in circular)

    # A Market import is an alternative *definition* supply path. It says
    # nothing about the current Market interface, Funds or provider stock.
    provider = node("market_provider", "imports")
    market = DependencyRelation("external_buy_offer", provider, metal, "test:market:metal")
    assert not risks(relations + (market,), graph_nodes + (provider,))

    # A different producing process attached to an independently acquired
    # facility is another OR path; the original AND inputs are retained.
    alternate_facility = node("facility", "independent.smelter")
    alternate_capability = node("capability", "independent.smelt")
    alternate_process = node("process", "metal.alternative")
    alternate_build = node("construction_method", "independent.build")
    alternates = (
        DependencyRelation("constructs_facility", alternate_build, alternate_facility,
                           "test:alternative:build"),
        DependencyRelation("supplies_capability", alternate_facility, alternate_capability,
                           "test:alternative:capability"),
        DependencyRelation("requires_capability", alternate_capability, alternate_process,
                           "test:alternative:requires"),
        DependencyRelation("consumes_resource", ore, alternate_process,
                           "test:alternative:ore"),
        DependencyRelation("produces_resource", alternate_process, metal,
                           "test:alternative:output"),
    )
    assert not risks(relations + alternates, graph_nodes + (
        alternate_facility, alternate_capability, alternate_process, alternate_build,
    ))
    # A purely Resource-to-Resource feedback loop is also a conditional
    # authoring risk, without asserting anything about initial inventories.
    feedstock = node("resource", "seed")
    recycle = node("process", "seed.recycle")
    cyclic_recycle = (
        DependencyRelation("consumes_resource", feedstock, recycle, "test:feedstock"),
        DependencyRelation("produces_resource", recycle, feedstock, "test:recycled"),
    )
    assert len(risks(cyclic_recycle, (feedstock, recycle))) == 1
    assert risks(cyclic_recycle + (
        DependencyRelation("external_buy_offer", provider, feedstock, "test:seed:supply"),
    ), (feedstock, recycle, provider)) == []


def test_provider_supplied_services_trace_to_real_assets_in_acquisition_diagnostics():
    from space_idle.analysis_coverage import inspect_definition_coverage
    from space_idle.analysis_graph import DependencyDefinitionGraph

    facility = DependencyNode("facility", "test.science_lab")
    alternate = DependencyNode("facility", "test.alternative_lab")
    provider = DependencyNode("research_provider", "test.research_provider")
    execution = DependencyNode("service_capacity", "research_execution")
    method = DependencyNode("construction_method", "test.build_lab")
    alternate_method = DependencyNode("construction_method", "test.build_alternate_lab")
    relations = (
        DependencyRelation("constructs_facility", method, facility, "test:lab:construction"),
        DependencyRelation("requires_service_capacity", execution, method, "test:lab:work"),
        DependencyRelation("uses_asset_definition", facility, provider, "test:provider:real_source"),
        DependencyRelation("nominal_research_execution", provider, execution, "test:provider:execution"),
    )

    def coverage(rows, nodes):
        return inspect_definition_coverage(DependencyDefinitionGraph(nodes, rows, ()))

    findings = coverage(relations, (facility, provider, execution, method))
    assert any(row.code == "potential_asset_self_bootstrap_dependency"
               and row.subject == facility for row in findings)

    # A different built asset can provide the same service, and the provider's
    # ID never appears in the physical asset ledger as an additional unit.
    alternatives = (
        DependencyRelation("constructs_facility", alternate_method, alternate, "test:other:construction"),
        DependencyRelation("uses_asset_definition", alternate, provider, "test:provider:other_source"),
    )
    assert not any(row.code == "potential_asset_self_bootstrap_dependency"
                   for row in coverage(relations + alternatives, (
                       facility, alternate, provider, execution, method, alternate_method,
                   )))

    # A typed Provider without a source cannot create a fictitious independent
    # construction supply; its absence is an ordinary catalogue fact.
    orphan = coverage(tuple(row for row in relations if row.kind != "uses_asset_definition"),
                      (facility, provider, execution, method))
    assert not any(row.code == "potential_asset_self_bootstrap_dependency" for row in orphan)

    life_support = DependencyNode("life_support_method", "test.lab.life_support")
    habitat_service = DependencyNode("service_capacity", "life_support")
    habitat_edges = (
        DependencyRelation("constructs_facility", method, facility, "test:habitat:construction"),
        DependencyRelation("uses_asset_definition", facility, life_support, "test:life_support:physical_source"),
        DependencyRelation("nominal_life_support_supply", life_support, habitat_service,
                           "test:life_support:capacity"),
        DependencyRelation("requires_service_capacity", habitat_service, method,
                           "test:habitat:required_support"),
    )
    assert any(row.code == "potential_asset_self_bootstrap_dependency" and row.subject == facility
               for row in coverage(habitat_edges, (
                   facility, life_support, habitat_service, method,
               )))


def test_installed_power_storage_and_external_market_remain_typed_nominal_dependencies():
    from dataclasses import replace
    from space_idle.power import FixedGeneration, SolarGeneration

    app = build_game_application()
    sim = app._simulation
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert not graph.diagnostics

    def edges(kind, source, target):
        return tuple(edge for edge in graph.relations
                     if edge.kind == kind and edge.source == source and edge.target == target)

    for facility_id, spec in sim.power.specs.items():
        source = DependencyNode("facility", str(facility_id))
        power = DependencyNode("service_capacity", "power")
        if isinstance(spec.generation, FixedGeneration):
            rows = edges("nominal_power_supply", source, power)
            assert len(rows) == 1
            assert (rows[0].quantity, rows[0].unit, rows[0].time_basis) == (
                spec.generation.mw, "MW", "installed_rating")
        elif isinstance(spec.generation, SolarGeneration):
            rows = edges("nominal_power_supply", source, power)
            assert len(rows) == 1
            assert rows[0].quantity == spec.generation.rated_mw_at_reference_flux
            assert rows[0].time_basis == "at_reference_flux"
            assert "illumination_required" in (rows[0].condition or "")
        if spec.load_mw:
            assert edges("nominal_power_load", power, source)[0].quantity == spec.load_mw

    for resource in app._catalog.resources.values():
        storage = resource.storage_pool_key or "default"
        assert edges("uses_storage_pool", DependencyNode("resource", str(resource.id)),
                     DependencyNode("storage_pool", storage))

    for facility_id, spec in sim.storage.providers.items():
        for pool, capacity in spec.capacity_t_by_pool.items():
            rows = edges("nominal_storage_capacity", DependencyNode("facility", str(facility_id)),
                         DependencyNode("storage_pool", pool))
            assert len(rows) == 1
            assert rows[0].quantity == capacity
            assert rows[0].unit == "t" and rows[0].time_basis == "per_installed_facility"

    # Service, housing and life support are not fungible: a housing slot is
    # installed stock capacity, whereas oxygen/water throughput is a daily flow.
    for facility in sim.facilities.definitions.values():
        owner = DependencyNode("facility", str(facility.id))
        for service in facility.service_capacity_supplies:
            rows = edges("nominal_service_supply", owner,
                         DependencyNode("service_capacity", service.service_type))
            assert len(rows) == 1 and rows[0].quantity == service.nominal_rate
            assert rows[0].time_basis == "per_installed_facility"
        if facility.housing_capacity:
            row = edges("nominal_housing_capacity", owner,
                        DependencyNode("capacity_pool", "housing"))[0]
            assert (row.quantity, row.unit) == (facility.housing_capacity, "people")
        if facility.life_support is not None:
            support = DependencyNode("life_support_method", str(facility.id))
            assert edges("uses_asset_definition", owner, support)
            row = edges("nominal_life_support_supply", support,
                        DependencyNode("service_capacity", "life_support"))[0]
            assert row.quantity == facility.life_support.person_days_per_day
            assert row.unit == "person_days/day"
            for rid, rate in facility.life_support.net_resources:
                row = edges("consumes_resource", DependencyNode("resource", str(rid)), support)[0]
                assert (row.quantity, row.unit) == (rate, "t/person_day")
        if facility.maintenance_fraction_per_year:
            row = edges("maintenance_investment_fraction", owner,
                        DependencyNode("facility_maintenance_policy", str(facility.id)))[0]
            assert (row.quantity, row.time_basis) == (
                facility.maintenance_fraction_per_year, "of_actual_instance_investment")

    for vehicle in sim.transport.vehicle_definitions():
        owner = DependencyNode("vehicle", str(vehicle.id))
        production = DependencyNode("vehicle_production_method", str(vehicle.id))
        if vehicle.production.service_type is not None:
            assert edges("requires_service_capacity",
                         DependencyNode("service_capacity", vehicle.production.service_type), production)
        if vehicle.retirement.enabled:
            method = DependencyNode("vehicle_retirement_method", str(vehicle.id))
            assert edges("retires_vehicle", owner, method)
            for rid, amount in vehicle.retirement.recovery_resources_per_unit:
                row = edges("recovers_resource", method, DependencyNode("resource", str(rid)))[0]
                assert (row.quantity, row.time_basis) == (amount, "maximum_recovery_per_vehicle")
        if vehicle.maintenance.turnaround_days or vehicle.maintenance.resources or vehicle.maintenance.service_type:
            method = DependencyNode("vehicle_turnaround_method", str(vehicle.id))
            assert edges("uses_asset_definition", owner, method)
            for rid, amount in vehicle.maintenance.resources:
                row = edges("consumes_resource", DependencyNode("resource", str(rid)), method)[0]
                assert (row.quantity, row.time_basis) == (amount, "per_turnaround")
        if vehicle.passengers.seats:
            method = DependencyNode("onboard_life_support_method", str(vehicle.id))
            assert edges("nominal_passenger_seats", owner,
                         DependencyNode("capacity_pool", "passenger_seats"))
            assert edges("nominal_life_support_supply", method,
                         DependencyNode("service_capacity", "onboard_life_support"))
            for rid, rate in vehicle.passengers.net_resources_per_person_day:
                row = edges("consumes_resource", DependencyNode("resource", str(rid)), method)[0]
                assert (row.quantity, row.unit) == (rate, "t/person_day")

    # External buy availability and offer prices have distinct units, semantics,
    # and interface requirements. Neither is a player-owned inventory stock.
    market = next(iter(sim.market.provider_defs.values()))
    resource_id, price = next(iter(market.buy_offers_musd_per_t))
    source = DependencyNode("market_provider", str(market.id))
    target = DependencyNode("resource", str(resource_id))
    assert edges("external_buy_offer", source, target)[0].quantity == price
    assert edges("external_buy_offer", source, target)[0].unit == "MUSD/t"
    assert edges("external_supply_capacity", source, target)[0].time_basis == "stock_capacity"

    # The same code reads another registered definition; no ID-specific analysis table.
    other = replace(market, id=DefinitionId("test.market.other"))
    sim.market.register_provider_definition(other)
    expanded = build_definition_dependency_graph(sim, app._catalog)
    assert not expanded.diagnostics
    assert any(row.source == DependencyNode("market_provider", str(other.id))
               and row.kind == "external_buy_offer" for row in expanded.relations)


def test_live_state_observation_uses_owned_state_and_is_distinct_from_definition_graph():
    from space_idle.analysis_observation import observe_state
    from space_idle.shared import EntityId

    app = build_game_application()
    sim = app._simulation
    key = next(key for key, amount in sim.inventory.stock.items() if amount >= 2)
    node_id, resource_id = key
    start = observe_state(sim, operational_node_ids=frozenset({node_id}),
                          resource_ids=frozenset({resource_id}))
    initial = {(m.kind, m.subject_id, m.context_id): m.quantity for m in start.metrics}
    def amount(observation, kind):
        return next(row.quantity for row in observation.metrics if row.kind == kind)

    assert start.day == sim.day and start.scenario_id == sim.scenario_id
    assert start.operational_node_ids == (str(node_id),)
    assert start.resource_ids == (str(resource_id),)
    assert start.to_json_data()["scope"] == {
        "operational_node_ids": [str(node_id)], "resource_ids": [str(resource_id)],
    }
    assert all(row.context_id == str(node_id) and row.subject_id == str(resource_id)
               for row in start.metrics if row.kind.startswith("inventory_"))
    # Provider quantities retain their provider scope even when the Node has
    # an interface; they are never counted as local Inventory.
    assert all(row.kind.startswith(("inventory_", "external_market_"))
               for row in start.metrics)
    assert amount(start, "inventory_available") == max(
        0.0, amount(start, "inventory_stock") - amount(start, "inventory_reserved"))
    assert json.loads(json.dumps(start.to_json_data())) == start.to_json_data()

    owner = EntityId("analysis.test.reservation")
    assert sim.inventory.reserve(owner, node_id, resource_id, 1) == 1
    observed = observe_state(sim, operational_node_ids=frozenset({node_id}),
                             resource_ids=frozenset({resource_id}))
    assert amount(observed, "inventory_stock") == amount(start, "inventory_stock")
    assert amount(observed, "inventory_reserved") == amount(start, "inventory_reserved") + 1
    assert amount(observed, "inventory_available") == amount(start, "inventory_available") - 1
    assert sim.day == start.day

    sim.inventory.release_reservation(owner)
    assert {(m.kind, m.subject_id, m.context_id): m.quantity for m in
            observe_state(sim, operational_node_ids=frozenset({node_id}),
                          resource_ids=frozenset({resource_id})).metrics} == initial
    complete = observe_state(sim)
    kinds = {metric.kind for metric in complete.metrics}
    assert {"physical_storage_capacity", "usable_storage_capacity",
            "storage_pool_occupied", "storage_pool_admission_available",
            "external_market_supply_available", "funds_balance", "fleet_total"} <= kinds
    assert any(metric.provenance.startswith("inventory.") for metric in complete.metrics)
    assert observe_state(sim) == complete  # no implicit tick / mutable analysis state

    # A physical Fleet Commitment parked at an Operational Node is visible
    # under that Node's scope; a geographically unrelated Node cannot inherit
    # its units. In-transit and unestablished targets have no Node Inventory.
    for commitment in sim.transport.fleet_commitment_snapshots():
        if commitment.operational_node_id is None:
            continue
        scoped = observe_state(sim, operational_node_ids=frozenset({commitment.operational_node_id}))
        matches = [row for row in scoped.metrics if row.kind == 'fleet_committed'
                   and row.provenance == f'transport.fleet_commitment:{commitment.id}']
        assert len(matches) == 1
        assert matches[0].context_id == str(commitment.operational_node_id)
        assert matches[0].quantity == commitment.quantity
        outside = observe_state(sim, operational_node_ids=frozenset())
        assert all(row.provenance != matches[0].provenance for row in outside.metrics)

    for (pool_node, pool_key), _physical in sim.inventory.physical_storage_capacity_t.items():
        admission = sim.inventory.admission_state_for_pool(pool_node, pool_key)
        observed_pool = {(m.kind, m.subject_id, m.context_id): m.quantity
                         for m in complete.metrics}
        assert observed_pool[("storage_pool_occupied", pool_key, str(pool_node))] == admission.occupied_t
        assert observed_pool[("storage_pool_over_capacity", pool_key, str(pool_node))] == admission.over_capacity_t

    # Supply committed to a pending Buy Order cannot simultaneously be
    # advertised as freely available for another purchase.
    for provider_id, state in sim.market.provider_states.items():
        for rid, remaining in state.supply_available_t.items():
            rows = {(m.kind, m.subject_id, m.context_id): m.quantity for m in complete.metrics}
            assert rows[("external_market_supply_remaining", str(rid), str(provider_id))] == remaining
            assert rows[("external_market_supply_available", str(rid), str(provider_id))] == (
                sim.market.available_provider_supply_t(provider_id, rid))
    for interface in sim.market.interfaces.values():
        if not interface.enabled:
            continue
        scoped = observe_state(sim, operational_node_ids=frozenset({interface.operational_node_id}))
        assert any(row.context_id == str(interface.provider_id)
                   and row.kind.startswith("external_market_") for row in scoped.metrics)
        break


def test_canonical_experiments_replay_player_commands_and_preserve_absent_metrics():
    from scripts.analysis_experiments import (
        ExperimentCase, run_experiments, compare_experiments,
    )
    from space_idle.application_commands import StartResearch

    app = build_game_application()
    technology = next(iter(app._simulation.research.definitions))
    # The two cases start from independently composed Scenario/Domain States.
    cases = (
        ExperimentCase("baseline", build_game_application, lambda _app, _day: ()),
        ExperimentCase("research", build_game_application,
                       lambda _app, day: (StartResearch(str(technology)),) if day == 0 else ()),
        ExperimentCase("rejected", build_game_application,
                       lambda _app, day: (StartResearch("unregistered.technology"),) if day == 0 else ()),
    )
    observed = run_experiments(cases, days=2)
    repeated = run_experiments(cases, days=2)
    assert [run.to_json_data() for run in observed] == [run.to_json_data() for run in repeated]
    assert {run.initial_state_sha256 for run in observed}.__len__() == 1
    assert {run.definition_graph_sha256 for run in observed}.__len__() == 1
    assert all([snapshot.day for snapshot in run.observations] == [0, 1, 2] for run in observed)
    assert observed[2].rejected_commands[0].code == "not_found"
    assert not observed[1].rejected_commands
    assert observed[0].observations == observed[2].observations
    differences = compare_experiments(observed)
    assert differences["baseline"] == "baseline"
    assert differences["comparisons"][0]["same_initial_state"]
    # RP or resulting research activity differs due to a *real* Application Command.
    assert differences["comparisons"][0]["metric_differences"]

    # A missing metric is never silently converted into zero or an invented flow.
    from space_idle.analysis_observation import StateObservation, StateMetric
    from dataclasses import replace
    base = observed[0]
    expanded = replace(observed[1], observations=(
        StateObservation(0, base.scenario_id, ()),
        StateObservation(1, base.scenario_id, ()),
        StateObservation(2, base.scenario_id, (StateMetric(
            "inventory_stock", "new-resource", "another-node", 1, "t", "inventory.stock"),)),
    ))
    missing = compare_experiments((base, expanded))["comparisons"][0]["metric_differences"]
    new = next(row for row in missing if row["subject_id"] == "new-resource")
    assert new["baseline_final"] is None and new["variant_initial"] is None
    assert new["final_difference"] is None and new["variant_net_change"] is None


def test_experiment_input_requires_explicit_time_and_real_command_types():
    from scripts.analysis_experiments import ExperimentCase, run_experiments
    from space_idle.application_commands import AdvanceTime
    from scripts.compare_experiments import parse_cases
    import pytest

    with pytest.raises(ValueError, match="names must be unique"):
        run_experiments((ExperimentCase("same", build_game_application, lambda a, d: ()),
                         ExperimentCase("same", build_game_application, lambda a, d: ())), days=0)
    with pytest.raises(ValueError, match="cannot control"):
        run_experiments((ExperimentCase("bad", build_game_application,
                                         lambda a, d: (AdvanceTime(5),)),), days=1)
    with pytest.raises(ValueError, match="outside experiment horizon"):
        parse_cases({"days": 2, "cases": [{"name": "late", "commands": [
            {"day": 2, "type": "StartResearch", "args": {"research_id": "anything"}},
        ]}]})
    with pytest.raises(ValueError, match="unknown or unsupported"):
        parse_cases({"days": 1, "cases": [{"name": "untyped", "commands": [
            {"day": 0, "type": "MagicResult", "args": {}},
        ]}]})


def test_comparison_accepts_distinct_validated_scenario_definitions_without_mutating_live_state():
    from dataclasses import replace
    from space_idle.content.base_scenario import build_standard_scenario_definition
    from space_idle import build_game_application_for_scenario
    from scripts.analysis_experiments import ExperimentCase, run_experiments, compare_experiments

    initial = build_standard_scenario_definition()
    first = initial.inventory_stock[0]
    more = replace(initial, id="test.scenario.resource_perturbation", inventory_stock=(
        replace(first, amount_t=first.amount_t + 10.0), *initial.inventory_stock[1:],
    ))
    cases = (
        ExperimentCase("normal", lambda: build_game_application_for_scenario(initial), lambda _app, _day: ()),
        ExperimentCase("extra", lambda: build_game_application_for_scenario(more), lambda _app, _day: ()),
    )
    runs = run_experiments(cases, days=1)
    differences = compare_experiments(runs)["comparisons"][0]
    assert not differences["same_initial_state"]
    assert not differences["same_scenario"]
    change = next(row for row in differences["metric_differences"]
                  if row["kind"] == "inventory_stock" and
                  row["subject_id"] == str(first.resource_id) and
                  row["context_id"] == str(first.operational_node_id))
    assert change["variant_initial"] - change["baseline_initial"] == 10.0
    assert change["final_difference"] is not None
    assert build_standard_scenario_definition() == initial


def test_definition_coverage_reports_missing_suppliers_without_classifying_technology_value():
    from space_idle.analysis_coverage import inspect_definition_coverage

    app = build_game_application()
    graph = build_definition_dependency_graph(app._simulation, app._catalog)
    findings = inspect_definition_coverage(graph)
    assert not any(row.code == "required_capability_without_definition_supplier" for row in findings)
    # Absence of a declared outlet is an inventory classification, not
    # an automatic balance defect for every Technology.
    assert not any(row.code.startswith("technology_") for row in findings)
    assert inspect_definition_coverage(graph) == findings

    # A known capability node is not proof that any physical Definition
    # supplies it. Only a supply edge is evidence of an authored provider.
    from space_idle.analysis_graph import DependencyDefinitionGraph, DependencyNode, DependencyRelation
    capability = DependencyNode("capability", "test.unavailable")
    consumer = DependencyNode("process", "test.process")
    missing = DependencyDefinitionGraph((capability, consumer), (
        DependencyRelation("requires_capability", capability, consumer,
                           "process:test.process:required_capabilities"),
    ), ())
    gaps = inspect_definition_coverage(missing)
    by_code = {row.code: row for row in gaps}
    assert set(by_code) == {"required_capability_without_definition_supplier"}
    assert by_code["required_capability_without_definition_supplier"].evidence == (
        "process:test.process:required_capabilities",
    )
    assert by_code["required_capability_without_definition_supplier"].to_json_data()["subject"]["id"] == "test.unavailable"

    connected = DependencyDefinitionGraph((capability, consumer, DependencyNode("facility", "supplier")), (
        *missing.relations,
        DependencyRelation("supplies_capability", DependencyNode("facility", "supplier"),
                           capability, "facility:supplier:capability_supplies"),
    ), ())
    assert not any(row.code == "required_capability_without_definition_supplier"
                   for row in inspect_definition_coverage(connected))

    # Research and manufacturing graphs may each be acyclic while their
    # *combined* acquisition requirement is self-gated. An alternative
    # ungated supplier makes the diagnosis disappear (OR alternatives), while
    # multiple prerequisites of one method are still an AND gate.
    technology = DependencyNode("technology", "test.microscope.research")
    successor = DependencyNode("technology", "test.follow_on")
    stage = DependencyNode("research_stage", "test.microscope.research/prototype")
    method = DependencyNode("construction_method", "test.lab.build")
    supplier = DependencyNode("facility", "test.lab")
    relations = (
        DependencyRelation("research_stage", stage, technology, "test:prototype"),
        DependencyRelation("requires_site_capability", capability, stage, "test:required_instrument"),
        DependencyRelation("supplies_capability", supplier, capability, "test:instrument"),
        DependencyRelation("constructs_facility", method, supplier, "test:build"),
        DependencyRelation("technology_prerequisite", technology, successor, "test:prerequisite"),
        DependencyRelation("unlocks_method", successor, method, "test:unlock"),
    )
    all_nodes = (technology, successor, stage, method, supplier, capability)
    risks = inspect_definition_coverage(DependencyDefinitionGraph(all_nodes, relations, ()))
    gated = tuple(row for row in risks if row.code == "potential_research_supply_acquisition_cycle")
    assert len(gated) == 1
    assert gated[0].subject == technology
    assert any("initial_stock_assets_sites_and_market_conditions_unknown" in evidence for evidence in gated[0].evidence)
    assert any("test.follow_on" in evidence for evidence in gated[0].evidence)
    alternative = DependencyNode("construction_method", "test.lab.alternative")
    alternatives = (
        *relations,
        DependencyRelation("constructs_facility", alternative, supplier, "test:alternative"),
    )
    assert not any(row.code == "potential_research_supply_acquisition_cycle"
                   for row in inspect_definition_coverage(
                       DependencyDefinitionGraph((*all_nodes, alternative), alternatives, ())
                   ))


def test_technology_outlet_classification_follows_declared_research_edges_only():
    from space_idle.analysis_technology_outlets import classify_technology_outlets
    from space_idle.analysis_graph import DependencyDefinitionGraph, DependencyNode, DependencyRelation

    def technology(name):
        return DependencyNode("technology", name)

    a, b, c, d, e, f = tuple(technology(name) for name in "abcdef")
    method = DependencyNode("process", "production_method")
    no_effect = DependencyNode("research_stage", "research_stage_a")
    relations = (
        DependencyRelation("technology_prerequisite", a, b, "b:prerequisites"),
        DependencyRelation("technology_prerequisite", a, c, "c:prerequisites"),
        DependencyRelation("technology_prerequisite", b, d, "d:prerequisites"),
        DependencyRelation("technology_prerequisite", c, d, "d:prerequisites"),
        DependencyRelation("technology_prerequisite", e, f, "f:prerequisites"),
        DependencyRelation("unlocks_method", d, method, "production:prerequisite"),
        DependencyRelation("research_stage", no_effect, e, "e:stage"),
    )
    nodes = (a, b, c, d, e, f, method, no_effect)
    graph = DependencyDefinitionGraph(nodes, relations, ())
    rows = classify_technology_outlets(graph)
    classified = {row.technology.id: row for row in rows}
    assert classified["a"].classification == "via_research"
    assert classified["a"].reachable_method_count == 1
    assert classified["a"].downstream_technology_count == 3  # diamond is not double counted
    assert classified["a"].reachable_methods == (method,)
    assert classified["d"].direct_methods == (method,)
    assert [row["id"] for row in classified["a"].to_json_data()["reachable_methods"]] == [method.id]
    assert {row.id for row in classified["a"].downstream_technologies} == {"b", "c", "d"}
    assert classified["d"].classification == "direct_method"
    assert classified["e"].classification == "research_only_no_method"
    assert classified["f"].classification == "no_downstream_outlet"
    # Classification remains available as a deliberate audit, not as
    # hundreds of automatic coverage warnings in ordinary output.
    from space_idle.analysis_coverage import inspect_definition_coverage
    assert not any(row.code.startswith("technology_") for row in inspect_definition_coverage(graph))
    assert classify_technology_outlets(DependencyDefinitionGraph(tuple(reversed(nodes)),
                                                                tuple(reversed(relations)), ())) == rows
    # Independently necessary branches of a research DAG are not redundant;
    # an ancestor repeated alongside its descendant on one method is. The
    # finding is Content-only and must not suppress actual Application options.
    overlapping = DependencyDefinitionGraph(nodes, (*relations,
        DependencyRelation("unlocks_method", a, method, "production:duplicate_gate"),
        DependencyRelation("unlocks_method", b, method, "production:duplicate_gate"),
    ), ())
    repeated_gates = [row for row in inspect_definition_coverage(overlapping)
                      if row.code == "redundant_method_technology_requirement"]
    assert {(row.subject, row.evidence[1], row.evidence[2]) for row in repeated_gates} == {
        (method, "redundant_ancestor:technology:a", "required_descendant:technology:b"),
        (method, "redundant_ancestor:technology:a", "required_descendant:technology:d"),
        (method, "redundant_ancestor:technology:b", "required_descendant:technology:d"),
    }
    assert not any(row.evidence[1] == "redundant_ancestor:technology:c" for row in repeated_gates)
    assert [row for row in inspect_definition_coverage(DependencyDefinitionGraph(
        tuple(reversed(nodes)), tuple(reversed(overlapping.relations)), ()))
        if row.code == "redundant_method_technology_requirement"] == repeated_gates

    # Real Content is classified through registered graph contributors, not by
    # hard-coded branch counts, names, or a fixed future gameplay progression.
    app = build_game_application()
    full = build_definition_dependency_graph(app._simulation, app._catalog)
    report = classify_technology_outlets(full)
    assert {row.technology for row in report} == {node for node in full.nodes if node.kind == "technology"}
    assert all(row.reachable_method_count >= row.direct_method_count for row in report)
    assert all(row.direct_method_count > 0 for row in report if row.classification == "direct_method")


def test_every_registered_project_method_participates_in_analysis_including_upgrade_and_retirement():
    """Construction owns all four physical Project kinds; a new Recipe needs no analyzer switch."""
    from dataclasses import replace
    from space_idle.content import base_ids as ids
    from space_idle.construction import BuildResourceRequirement, FacilityUpgradeRecipe
    from space_idle.analysis_technology_outlets import classify_technology_outlets

    app = build_game_application()
    sim = app._simulation
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert not graph.diagnostics

    for recipe in sim.projects.recipes.values():
        method = DependencyNode("construction_method", str(recipe.facility_def_id))
        assert method in graph.nodes
    for (definition_id, level), recipe in sim.projects.upgrade_recipes.items():
        method = DependencyNode("facility_upgrade_method", f"{definition_id}/level:{level}")
        assert method in graph.nodes
        assert any(row.kind == "upgrades_facility" and row.target == method for row in graph.relations)
        assert any(row.kind == "requires_construction_work" and row.target == method
                   and row.quantity == recipe.construction_work for row in graph.relations)
        assert any(row.kind == "consumes_resource" and row.target == method
                   for row in graph.relations)
    for definition_id in sim.projects.decommission_recipes:
        method = DependencyNode("facility_decommission_method", str(definition_id))
        assert method in graph.nodes
        assert any(row.kind == "decommissions_facility" and row.target == method for row in graph.relations)
    for definition_id in sim.projects.spatial_recipes:
        method = DependencyNode("spatial_development_method", str(definition_id))
        assert method in graph.nodes
        assert any(row.kind == "requires_construction_work" and row.target == method
                   for row in graph.relations)

    # A research-gated second generation is a normal typed Content addition:
    # detect it and its finite inputs without modifying Domain/Core analysis.
    new_facility = ids.METALLURGY
    new_level = 2
    recipe = FacilityUpgradeRecipe(
        new_facility, new_level, (BuildResourceRequirement(ids.MACHINERY, 1.25),),
        4.0, prerequisite_technologies=frozenset({ids.RP_RESOURCE_CHAIN_14}),
    )
    sim.projects.upgrade_recipes[(new_facility, new_level)] = recipe
    expanded = build_definition_dependency_graph(sim, app._catalog)
    assert not expanded.diagnostics
    method = DependencyNode("facility_upgrade_method", f"{new_facility}/level:{new_level}")
    subgraph = expanded.subset((method,))
    assert any(edge.kind == "consumes_resource" and edge.target == method
               and edge.source == DependencyNode("resource", str(ids.MACHINERY))
               for edge in subgraph.relations)
    assert any(edge.kind == "requires_construction_work" and edge.target == method
               for edge in subgraph.relations)
    assert any(edge.kind == "unlocks_method" and edge.target == method
               and edge.source == DependencyNode("technology", str(ids.RP_RESOURCE_CHAIN_14))
               for edge in subgraph.relations)
    outlet = next(row for row in classify_technology_outlets(expanded)
                  if row.technology.id == str(ids.RP_RESOURCE_CHAIN_14))
    assert outlet.classification == "direct_method"
    assert outlet.direct_method_count >= 2


def test_scientific_exploration_dependency_graph_preserves_real_movement_inputs_and_site_requirements():
    """A newly registered finite Campaign uses the same site/asset graph contract."""
    from space_idle.content import base_ids as ids
    from space_idle.scientific_exploration import ScientificExplorationDefinition
    from space_idle.transport.models import MovementEndpoint
    from space_idle.site import (SiteRequirements, SpatialClassificationRequirement,
                                 SpatialClassification, RequiresFacet)
    from space_idle.spatial import RadiationField

    app = build_game_application()
    sim = app._simulation
    identifier = DefinitionId('test.exploration.physical_context')
    capability = next(cap for vehicle in sim.transport.vehicle_definitions()
                      for cap in vehicle.generic_capabilities)
    definition = ScientificExplorationDefinition(
        identifier, 'physical survey campaign', ids.LEO,
        MovementEndpoint(physical_target_node_id=ids.MARS_ORBIT), 7.0, 19.0,
        consumable_resources=((ids.MACHINERY, 1.2),), required_units=2,
        required_crew=2, required_vehicle_capabilities=(capability,),
        destination_requirements=SiteRequirements(
            spatial_classification_requirements=(SpatialClassificationRequirement(
                SpatialClassification.ORBITAL, 'orbit.required', 'orbit target',
            ),), environment=(RequiresFacet(RadiationField, 'radiation.required', 'radiation known'),),
        ),
    )
    sim.scientific_exploration.definitions[identifier] = definition
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert not graph.diagnostics
    method = DependencyNode('scientific_exploration', str(identifier))
    subset = graph.subset((method,))
    def get(kind):
        return [row for row in subset.relations if row.kind == kind and row.target == method]

    assert get('requires_origin_context')[0].source == DependencyNode('spatial_node', str(ids.LEO))
    assert any(row.kind == 'targets_spatial_context' and row.source == method
               and row.target == DependencyNode('spatial_node', str(ids.MARS_ORBIT))
               for row in subset.relations)
    assert get('consumes_resource')[0].quantity == 1.2
    assert get('requires_fleet_units')[0].quantity == 2
    assert get('requires_population_commitment')[0].quantity == 2
    assert get('requires_capability')[0].source == DependencyNode('capability', capability)
    assert get('requires_site_classification')[0].source == DependencyNode('spatial_classification', 'ORBITAL')
    assert get('requires_site_environment')[0].source.kind == 'site_condition'
    assert any(row.kind == 'campaign_duration' and row.source == method and row.quantity == 7.0
               for row in subset.relations)
    assert not sim.graph.has_operational_node(ids.MARS_ORBIT)


def test_survey_and_extraction_dependencies_preserve_physical_methods_and_targets():
    """Analysis must not reduce acquisition and Survey to names or RP outputs."""
    from dataclasses import replace

    from space_idle.analysis_coverage import inspect_definition_coverage
    from space_idle.exploration_models import SurveyObservationModeSpec
    from space_idle.site import SiteRequirements, CapabilityRequirement

    app = build_game_application()
    sim = app._simulation
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert not graph.diagnostics

    for (cell_id, resource_id), target in sim.survey.targets.items():
        owner = DependencyNode("survey_target", f"{cell_id}/{resource_id}")
        assert any(r.source == owner and r.kind == "targets_surface_cell"
                   and r.target == DependencyNode("surface_cell", str(cell_id)) for r in graph.relations)
        assert any(r.source == owner and r.kind == "observes_resource"
                   and r.target == DependencyNode("resource", str(resource_id)) for r in graph.relations)
        thresholds = [r for r in graph.relations
                      if r.source == owner and r.kind == "survey_knowledge_threshold"]
        assert len(thresholds) == len(target.thresholds)
        assert {r.target.id: r.quantity for r in thresholds} == dict(zip(
            ("PRESENCE_PROBABILITY", "ESTIMATED_RESOURCE_POTENTIAL", "MEASURED_RESOURCE_POTENTIAL"),
            target.thresholds,
        ))

    for provider in sim.survey.providers.values():
        provider_node = DependencyNode("survey_provider", str(provider.id))
        compatible = sim.survey.compatible_source_definition_ids(provider)
        assert {r.source.id for r in graph.relations if r.target == provider_node
                and r.kind == "uses_asset_definition"} == {str(key) for key in compatible}
        for mode in provider.observation_modes:
            owner = DependencyNode("survey_mode", f"{provider.id}/{mode.id}")
            assert any(r.source == owner and r.kind == "nominal_survey_progress"
                       and r.quantity == mode.survey_rate for r in graph.relations)
            assert any(r.target == owner and r.kind == "requires_survey_reach"
                       and r.source.id == mode.reach.scope.value for r in graph.relations)
            expected_services = {
                sim.survey.service_type_for_provider(provider.id, source_id)
                for source_id in sim.survey.compatible_mode_source_definition_ids(provider, mode)
            }
            assert {r.source.id for r in graph.relations if r.target == owner
                    and r.kind == "requires_service_capacity"} == expected_services

    for method in sim.extraction.specs.values():
        owner = DependencyNode("extraction_method", str(method.id))
        assert any(r.source == DependencyNode("resource", str(method.resource_id))
                   and r.target == owner and r.kind == "requires_resource_opportunity"
                   for r in graph.relations)
        assert any(r.target == owner and r.kind == "requires_knowledge"
                   and r.source == DependencyNode("resource", str(method.resource_id))
                   for r in graph.relations) == (method.minimum_knowledge_level is not None)
        assert any(r.target == owner and r.kind == "requires_site_classification"
                   for r in graph.relations) == bool(method.opportunity_requirements.spatial_classification_requirements)
        for key in (method.geology_accessibility_key, method.terrain_accessibility_attribute):
            if key is not None:
                assert any(r.target == owner and r.kind == "requires_opportunity_factor"
                           and key in r.source.id for r in graph.relations)
    for facility in sim.facilities.definitions.values():
        if facility.extraction_capacity_t_per_day > 0:
            methods = sim.extraction.compatible_methods(facility.id)
            assert methods
            for method in methods:
                assert any(r.kind == "nominal_extraction_capacity"
                           and r.source == DependencyNode("facility", str(facility.id))
                           and r.target == DependencyNode("extraction_method", str(method.id))
                           and r.quantity == facility.extraction_capacity_t_per_day
                           for r in graph.relations)

    # Content can add a mode-specific physical requirement and site condition;
    # the graph must report that requirement without modifying Generic Core.
    provider = next(iter(sim.survey.providers.values()))
    original = provider.observation_modes[0]
    additional = replace(original, id="different_equipment_mode", required_source_capabilities=frozenset({
        "unprovided_observation_instrument",
    }), site_requirements=SiteRequirements(capability_requirements=(
        CapabilityRequirement("unprovided_observation_instrument"),
    )))
    sim.survey.providers[provider.id] = replace(provider, observation_modes=(*provider.observation_modes, additional))
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert not graph.diagnostics
    mode_node = DependencyNode("survey_mode", f"{provider.id}/{additional.id}")
    assert any(r.kind == "requires_site_capability" and r.target == mode_node
               for r in graph.relations)
    assert not any(r.kind == "requires_service_capacity" and r.target == mode_node
                   for r in graph.relations)
    assert any(f.code == "required_capability_without_definition_supplier"
               and f.subject == DependencyNode("capability", "unprovided_observation_instrument")
               for f in inspect_definition_coverage(graph))


def test_research_stage_supply_dependencies_preserve_alternative_sources_and_technology_gates():
    """An input to an unfinished technology cannot depend exclusively on its unlocked methods."""
    from space_idle.analysis_coverage import inspect_definition_coverage
    from space_idle.analysis_graph import DependencyDefinitionGraph

    def node(kind, suffix):
        return DependencyNode(kind, f"test.research_supply.{suffix}")

    technology = node("technology", "initial")
    successor = node("technology", "successor")
    stage = node("research_stage", "initial.prototype")
    input_resource = node("resource", "feedstock")
    method = node("process", "synthesis")
    provider = node("market_provider", "supplier")
    facility = node("facility", "lab")
    construction = node("construction_method", "build_lab")
    research_provider = node("research_provider", "lab_provider")
    execution = node("service_capacity", "research_execution")

    base = (
        DependencyRelation("research_stage", stage, technology, "test:stage"),
        DependencyRelation("consumes_resource", input_resource, stage, "test:research_cost"),
        DependencyRelation("produces_resource", method, input_resource, "test:production"),
        DependencyRelation("unlocks_method", technology, method, "test:gate"),
        DependencyRelation("technology_prerequisite", technology, successor, "test:research_prerequisite"),
    )

    def risks(relations):
        nodes = tuple(sorted({node for relation in relations for node in (relation.source, relation.target)}))
        graph = DependencyDefinitionGraph(nodes, relations, ())
        return [row for row in inspect_definition_coverage(graph)
                if row.code == "potential_research_supply_acquisition_cycle"]

    resource_risks = risks(base)
    assert len(resource_risks) == 1 and resource_risks[0].subject == technology
    assert f"stage:{stage.id}:requires:resource:{input_resource.id}" in resource_risks[0].evidence
    assert any(f"blocked_method:process:{method.id}:requires:{technology.id}" == entry
               for entry in resource_risks[0].evidence)
    assert all(row.significance == "informational" for row in resource_risks)
    downstream_gated = tuple(DependencyRelation(
        "unlocks_method", successor if row.kind == "unlocks_method" else row.source,
        row.target, row.provenance,
    ) if row.kind == "unlocks_method" else row for row in base)
    assert len(risks(downstream_gated)) == 1

    market = DependencyRelation("external_buy_offer", provider, input_resource, "test:market:alternative")
    assert risks(base + (market,)) == []
    alternate_process = node("process", "other_production")
    assert risks(base + (DependencyRelation(
        "produces_resource", alternate_process, input_resource, "test:independent_production"
    ),)) == []

    # A nominal Research Provider capacity is not an independent physical
    # source; it requires an eligible installed Facility from the same Owner.
    provider_dependency = (
        DependencyRelation("research_stage", stage, technology, "test:stage"),
        DependencyRelation("requires_execution_capacity", execution, stage, "test:stage:service"),
        DependencyRelation("uses_asset_definition", facility, research_provider, "test:lab:backing_asset"),
        DependencyRelation("nominal_research_execution", research_provider, execution, "test:lab:service"),
        DependencyRelation("constructs_facility", construction, facility, "test:lab:build"),
        DependencyRelation("unlocks_method", technology, construction, "test:lab:locked"),
    )
    service_risks = risks(provider_dependency)
    assert len(service_risks) == 1
    assert f"stage:{stage.id}:requires:service_capacity:{execution.id}" in service_risks[0].evidence
    alternative_lab = node("facility", "other_lab")
    alternative_build = node("construction_method", "other_lab_build")
    alternative_provider = (
        DependencyRelation("uses_asset_definition", alternative_lab, research_provider,
                           "test:other_lab:backing_asset"),
        DependencyRelation("constructs_facility", alternative_build, alternative_lab,
                           "test:other_lab:build"),
    )
    assert risks(provider_dependency + alternative_provider) == []

    # Missing sources have their own diagnostics and must never be described
    # as a closed cycle: initial Content/Scenario coverage is unknown.
    assert risks(tuple(row for row in base if row.kind != "produces_resource")) == []


def test_unconnected_physical_methods_and_providers_never_supply_ghost_capacity(tmp_path):
    """Incomplete authored Content is distinct from a corrupt reference.

    A future physical asset may be introduced without its operating method;
    similarly, a provider can require real capabilities which existing assets
    only supply *separately*. Neither generates free capacity or becomes a
    runnable player option until a compatible source really exists.
    """
    from datetime import datetime, timezone

    import pytest

    from space_idle import AdvanceTime, ApplicationError, GetOperationalNode, SetFacilityExtractionMethod
    from space_idle.analysis_coverage import inspect_definition_coverage
    from space_idle.bootstrap import build_game_application_for_load, build_game_application_for_scenario
    from space_idle.content import base_ids as ids
    from space_idle.content.base_scenario import build_standard_scenario_definition
    from space_idle.facilities import FacilityDef, CapabilitySupply
    from space_idle.research import ResearchProviderSpec, ResearchProviderSourceKind, ResearchProviderLevelSpec
    from space_idle.survey import SurveyProviderSpec, SurveyProviderSourceKind, SurveyObservationModeSpec, SurveyReachSpec, SurveyReachScope, KnowledgeLevel
    from space_idle.scenario import ScenarioFacility
    from space_idle.persistence import capture_state, save_game, load_game
    from space_idle.power import PowerSpec

    future_facility = DefinitionId("test.future.miner")
    future_research = DefinitionId("test.future.research_provider")
    future_survey = DefinitionId("test.future.survey_provider")
    future_survey_mode = DefinitionId("test.future.survey_mode_provider")
    future_extraction_method = DefinitionId("test.future.extraction_method")
    future_process = DefinitionId("test.future.process")
    # Each source capability is individually known, but no *single* physical
    # research or survey source contains the required combination.
    def add_future_content(sim, _catalog):
        sim.facilities.definitions[future_facility] = FacilityDef(
            future_facility, "Unconfigured ore plant", (CapabilitySupply("research_lab"),),
            extraction_capacity_t_per_day=4.0,
        )
        sim.power.specs[future_facility] = PowerSpec(None, 0.1)
        sim.extraction.specs[future_extraction_method] = replace(
            sim.extraction.specs[ids.EXTRACTION_CRUST_ORE],
            id=future_extraction_method,
            required_capabilities=frozenset(("research_lab", "metal_ore_extraction")),
        )
        process = next(iter(sim.industry.processes.values()))
        sim.industry.processes[future_process] = replace(
            process, id=future_process,
            required_capabilities=frozenset(("research_lab", "metal_ore_extraction")),
        )
        sim.research.providers[future_research] = ResearchProviderSpec(
            future_research, ResearchProviderSourceKind.FACILITY,
            frozenset(("general_research_equipment", "propulsion_test_equipment")),
            tier=2, levels=(ResearchProviderLevelSpec(1, 4.0, 100.0, 1.0),),
        )
        # This Provider has a real sensor-carrying source, but the new mode
        # needs an additional instrument not installed on that same Vehicle.
        sim.survey.providers[future_survey_mode] = SurveyProviderSpec(
            future_survey_mode, SurveyProviderSourceKind.FLEET,
            frozenset(("survey_sensor",)),
            (SurveyObservationModeSpec(
                "future_radar", 4.0, SurveyReachSpec(SurveyReachScope.SAME_BODY),
                KnowledgeLevel.PRESENCE_PROBABILITY, 0.5, 0.1,
                required_source_capabilities=frozenset(("radar_sounder",)),
            ),),
        )
        sim.survey.providers[future_survey] = SurveyProviderSpec(
            future_survey, SurveyProviderSourceKind.FLEET,
            frozenset(("robotic_prospecting_sensor", "radar_sounder")),
            (SurveyObservationModeSpec(
                "future_mapping", 4.0, SurveyReachSpec(SurveyReachScope.SAME_BODY),
                KnowledgeLevel.PRESENCE_PROBABILITY, 0.5, 0.1,
                required_source_capabilities=frozenset(("radar_sounder",)),
            ),),
        )

    scenario = replace(build_standard_scenario_definition(), facilities=(
        *build_standard_scenario_definition().facilities,
        ScenarioFacility(future_facility, ids.EARTH),
    ))
    app = build_game_application_for_scenario(scenario, definition_transform=add_future_content)
    sim = app._simulation
    assert sim.extraction.compatible_methods(future_facility) == ()
    future_row = next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).extraction
                      if row.facility_definition_id == str(future_facility))
    assert future_row.output_t_per_day == 0
    assert not future_row.method_options
    assert any("no_compatible_method" in item.code and item.message
               for item in future_row.limiting_factors)
    with pytest.raises(ApplicationError):
        app.execute(SetFacilityExtractionMethod(future_row.facility_id, str(ids.EXTRACTION_CRUST_ORE)))
    assert not sim.industry.service_capacity_provider_definition_ids(
        sim.industry.process_service_type(future_process))
    assert not sim.research.compatible_facility_definition_ids(future_research)
    assert not sim.survey.compatible_source_definition_ids(sim.survey.providers[future_survey])
    assert sim.survey.compatible_source_definition_ids(sim.survey.providers[future_survey_mode])
    assert not any(not sim.survey._source_capability_failures(
        sim.survey.providers[future_survey_mode],
        sim.survey.providers[future_survey_mode].observation_modes[0], vehicle,
    ) for vehicle in sim.survey.compatible_source_definition_ids(
        sim.survey.providers[future_survey_mode]))

    graph = build_definition_dependency_graph(sim, app._catalog)
    assert graph.diagnostics == ()
    # Physical availability is observable through the actual Application and
    # Owner domains above; the analysis layer need not re-count missing asset IDs.
    original = capture_state(sim)
    app.execute(AdvanceTime(1))
    future_after = next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).extraction
                        if row.facility_definition_id == str(future_facility))
    assert future_after.output_t_per_day == 0
    assert future_after.method_id is None
    save_path = tmp_path / "unconnected.json"
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    save_game(app, save_path, saved_at=now)
    loaded, offline = load_game(
        save_path, lambda: build_game_application_for_load(
            scenario=scenario, definition_transform=add_future_content,
        ), now=now,
    )
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(sim)
    assert capture_state(sim) != original

    # A different Facility Definition with the compatible physical interface
    # joins the same method, Application choice, installed capacity and actual
    # finite production without any Core ID-specific code or manual reindexing.
    def add_compatible_source(sim, catalog):
        add_future_content(sim, catalog)
        sim.facilities.definitions[future_facility] = replace(
            sim.facilities.definitions[future_facility],
            capability_supplies=(CapabilitySupply("metal_ore_extraction"),),
        )

    connected = build_game_application_for_scenario(
        scenario, definition_transform=add_compatible_source,
    )
    assert tuple(method.id for method in connected._simulation.extraction.compatible_methods(
        future_facility
    )) == (ids.EXTRACTION_CRUST_ORE,)
    connected_row = next(row for row in connected.query(GetOperationalNode(str(ids.EARTH))).extraction
                         if row.facility_definition_id == str(future_facility))
    assert connected_row.method_id == str(ids.EXTRACTION_CRUST_ORE)
    assert connected_row.output_t_per_day > 0
    connected_graph = build_definition_dependency_graph(connected._simulation, connected._catalog)
    assert any(relation.kind == "nominal_extraction_capacity" and
               relation.source.id == str(future_facility) and
               relation.target.id == str(ids.EXTRACTION_CRUST_ORE)
               for relation in connected_graph.relations)
    before_ore = connected._simulation.inventory.amount(ids.EARTH, ids.METAL_ORE)
    connected.execute(AdvanceTime(1))
    assert connected._simulation.inventory.amount(ids.EARTH, ids.METAL_ORE) > before_ore

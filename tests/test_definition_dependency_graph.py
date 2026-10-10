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
        "facility_without_registered_acquisition_method",
        "facility_without_registered_retirement_method",
        "vehicle_without_registered_acquisition_method",
        "vehicle_without_registered_retirement_method",
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
    assert covered == ()


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


def test_definition_coverage_distinguishes_missing_supply_from_terminal_technology():
    from space_idle.analysis_coverage import inspect_definition_coverage

    app = build_game_application()
    graph = build_definition_dependency_graph(app._simulation, app._catalog)
    findings = inspect_definition_coverage(graph)
    assert not any(row.code == "required_capability_without_definition_supplier" for row in findings)
    terminal = tuple(row for row in findings if row.code == "technology_without_declared_downstream_outlet")
    assert terminal
    assert all(row.significance == "informational" and row.evidence for row in terminal)
    assert all(row.subject.kind == "technology" for row in terminal)
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
    assert len(gaps) == 1
    assert gaps[0].code == "required_capability_without_definition_supplier"
    assert gaps[0].evidence == ("process:test.process:required_capabilities",)
    assert gaps[0].to_json_data()["subject"]["id"] == "test.unavailable"

    connected = DependencyDefinitionGraph((capability, consumer, DependencyNode("facility", "supplier")), (
        *missing.relations,
        DependencyRelation("supplies_capability", DependencyNode("facility", "supplier"),
                           capability, "facility:supplier:capability_supplies"),
    ), ())
    assert not any(row.code == "required_capability_without_definition_supplier"
                   for row in inspect_definition_coverage(connected))


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
    assert classify_technology_outlets(DependencyDefinitionGraph(tuple(reversed(nodes)),
                                                                tuple(reversed(relations)), ())) == rows

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
            method = sim.extraction.method_for_definition(facility.id)
            assert method is not None
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

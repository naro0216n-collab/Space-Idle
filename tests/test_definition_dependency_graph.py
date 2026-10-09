from __future__ import annotations

import json

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
    assert any(edge.kind == "uses_asset_definition" and edge.target.kind == "survey_provider"
               for edge in graph.relations)
    assert any(edge.kind == "uses_asset_definition" and edge.target.kind == "research_provider"
               for edge in graph.relations)

    sample = next(p for p in sim.industry.processes.values() if p.inputs_per_day and p.outputs_per_day)
    method = DependencyNode("process", str(sample.id))
    subset = graph.subset((method,))
    assert any(edge.target == method and edge.kind == "consumes_resource" for edge in subset.relations)
    assert any(edge.source == method and edge.kind == "produces_resource" for edge in subset.relations)

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
    assert not inspect_definition_coverage(connected)

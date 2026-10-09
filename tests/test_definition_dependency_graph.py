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

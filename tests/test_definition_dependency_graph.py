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

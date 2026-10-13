"""Definition provenance contracts needed by the quantitative balance ledger.

No Game Command, actual allocation, authoring coverage score or Technology
outlet count belongs to this suite.
"""
from __future__ import annotations

from copy import deepcopy
import json

from space_idle.analysis_graph import (
    DefinitionGraphRegistry, DependencyDefinitionGraph, DependencyFragment,
    DependencyNode, DependencyRelation,
)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.composition.analysis_graph import build_definition_dependency_graph
from space_idle.persistence import capture_state
from space_idle.production import ProcessSpec
from space_idle.shared import DefinitionId


def test_registered_graph_is_read_only_and_preserves_typed_material_sources():
    app = build_game_application_for_load()
    sim = app._simulation
    before = deepcopy(capture_state(sim))
    graph = build_definition_dependency_graph(sim, app._catalog)
    assert not graph.diagnostics
    assert json.loads(json.dumps(graph.to_json_data())) == graph.to_json_data()
    process = next(p for p in sim.industry.processes.values() if p.inputs_per_day and p.outputs_per_day)
    node = DependencyNode('process', str(process.id))
    subset = graph.subset((node,), downstream=False)
    assert {rel.source.id: rel.quantity for rel in subset.relations
            if rel.target == node and rel.kind == 'consumes_resource'} == {
                str(resource): amount for resource, amount in process.inputs_per_day.items()}
    assert all(rel.unit is not None and rel.time_basis is not None and rel.provenance
               for rel in subset.relations if rel.target == node and rel.quantity is not None)
    assert capture_state(sim) == before


def test_new_registered_method_changes_graph_without_implicit_supply_or_state():
    app = build_game_application_for_load()
    sim = app._simulation
    sample = next(p for p in sim.industry.processes.values() if p.outputs_per_day)
    new_id = DefinitionId('test.balance.added.method')
    missing_resource = DefinitionId('test.balance.missing.input')
    sim.industry.processes[new_id] = ProcessSpec(
        new_id, 'added method', sample.required_capabilities,
        {missing_resource: 2.5}, dict(sample.outputs_per_day),
    )
    graph = build_definition_dependency_graph(sim, app._catalog)
    target = DependencyNode('process', str(new_id))
    assert any(r.target == target and r.source == DependencyNode('resource', str(missing_resource))
               and r.quantity == 2.5 and r.time_basis == 'per_execution_day'
               for r in graph.relations)
    assert any(d.code == 'undefined_reference' and d.node == DependencyNode('resource', str(missing_resource))
               for d in graph.diagnostics)


def test_contributor_contract_reports_missing_owners_references_and_untyped_relations():
    method = DependencyNode('method', 'added')
    resource = DependencyNode('resource', 'input')
    missing_method = DependencyNode('method', 'unrepresented')
    edge = DependencyRelation('consumes_resource', resource, method, 'process:registered', 1.5, 't')
    registry = DefinitionGraphRegistry()
    registry.register('method', lambda: DependencyFragment((method,), (edge, edge)),
                      relation_kinds={'consumes_resource'},
                      expected_definitions=lambda: (method, missing_method))
    registry.register('other', lambda: DependencyFragment((method,), (
        DependencyRelation('unregistered_kind', resource, method, 'unknown:definition'),
    )), relation_kinds={'declared_kind'})
    diagnostics = {row.code for row in registry.build().diagnostics}
    assert diagnostics == {
        'duplicate_definition_owner', 'unrepresented_registered_definition',
        'duplicate_relation', 'quantitative_relation_without_time_basis',
        'undefined_reference', 'unknown_relation_kind',
    }


def test_dependency_subset_retains_multiple_inputs_without_inferring_feasibility():
    a, b = DependencyNode('resource', 'a'), DependencyNode('resource', 'b')
    result = DependencyNode('resource', 'result')
    method = DependencyNode('process', 'method')
    alternative = DependencyNode('process', 'alternative')
    links = (
        DependencyRelation('consumes_resource', a, method, 'recipe:primary', 2, 't', 'per_execution_day'),
        DependencyRelation('consumes_resource', b, method, 'recipe:secondary', 3, 't', 'per_execution_day'),
        DependencyRelation('produces_resource', method, result, 'recipe:output', 1, 't', 'per_execution_day'),
        DependencyRelation('produces_resource', alternative, result, 'recipe:other', 1, 't', 'per_execution_day'),
    )
    graph = DependencyDefinitionGraph((a, b, method, alternative, result), links, ())
    subset = graph.subset((method,))
    assert all(link in subset.relations for link in links[:3])
    assert links[3] not in subset.relations
    assert len([r for r in subset.relations if r.target == method]) == 2

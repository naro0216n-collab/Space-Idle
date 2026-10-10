"""Cross-domain invariants of optional canonical observation and analysis.

Uses the real Application command boundary and Owner Domains, not a second
supply/eligibility implementation or a frozen preferred gameplay sequence.
"""
from __future__ import annotations

from dataclasses import replace
import json

import pytest

from scripts.analysis_experiments import (
    ExperimentCase, ParetoObjective, compare_experiments, compare_pareto, run_experiments,
)
from scripts.analysis_projection import project_html, to_csv
from scripts.compare_experiments import parse_cases
from space_idle import build_game_application
from space_idle.analysis_execution import ActivityFlow, observe_canonical_day
from space_idle.analysis_graph import (
    DependencyFragment, DependencyNode, DependencyRelation, DefinitionGraphRegistry,
)
from space_idle.analysis_observation import observe_state
from space_idle.bootstrap import build_game_application_for_scenario
from space_idle.content.base_scenario import build_standard_scenario_definition
from space_idle.content import base_ids as ids
from scripts.analysis_variants import apply_content_variant, scenario_variant
from space_idle.application_commands import AdvanceTime
from space_idle.persistence import capture_state
from space_idle.shared import DefinitionId, EntityId, SpatialNodeId


def _idle(_app, _day):
    return ()


def test_registered_definition_alternatives_require_shared_inputs_and_physical_conditions():
    """A Contributor's new method kind participates without ID-specific rules.

    Matching authored relations produce *candidates*, never actual eligibility
    or automatic Content removal. Process Pareto reasoning retains AND gates.
    """
    from space_idle.analysis_coverage import inspect_definition_alternatives

    ore = DependencyNode("resource", "input.ore")
    product = DependencyNode("resource", "product.alloy")
    capability = DependencyNode("capability", "smelting")
    different_capability = DependencyNode("capability", "advanced.smelting")
    p1, p2, p3, p4 = (
        DependencyNode("process", f"process.{index}") for index in range(4)
    )
    future1, future2 = (
        DependencyNode("future_operation_method", f"new.{index}") for index in range(2)
    )

    def source_fragment():
        return DependencyFragment((ore, product, capability, different_capability), ())

    def process_fragment():
        relations = []
        for node, amount, cap in (
            (p1, 3.0, capability), (p2, 5.0, capability),
            (p3, 5.0, different_capability), (p4, 3.0, capability),
        ):
            relations.extend((
                DependencyRelation("consumes_resource", ore, node, f"input:{node.id}",
                                   amount, "t", "per_execution"),
                DependencyRelation("produces_resource", node, product, f"output:{node.id}",
                                   4.0, "t", "per_execution"),
                DependencyRelation("requires_capability", cap, node, f"capability:{node.id}"),
            ))
        return DependencyFragment((p1, p2, p3, p4), tuple(relations))

    def added_domain_fragment():
        return DependencyFragment((future1, future2), (
            DependencyRelation("requires_capability", capability, future1, "added:one"),
            DependencyRelation("requires_capability", capability, future2, "added:two"),
        ))

    registry = DefinitionGraphRegistry()
    registry.register("inputs", source_fragment, relation_kinds=("requires_capability",))
    registry.register("processes", process_fragment,
                      relation_kinds=("consumes_resource", "produces_resource", "requires_capability"))
    registry.register("new_contributor", added_domain_fragment,
                      relation_kinds=("requires_capability",))
    graph = registry.build()
    assert not graph.diagnostics
    findings = inspect_definition_alternatives(graph)
    # Registration order changes neither typed relations nor the audit.
    reordered = DefinitionGraphRegistry()
    reordered.register("new_contributor", added_domain_fragment,
                       relation_kinds=("requires_capability",))
    reordered.register("processes", process_fragment,
                       relation_kinds=("consumes_resource", "produces_resource", "requires_capability"))
    reordered.register("inputs", source_fragment, relation_kinds=("requires_capability",))
    assert inspect_definition_alternatives(reordered.build()) == findings
    by_subject = {(finding.code, finding.subject.id): finding.evidence for finding in findings}
    assert "candidate:process:process.3" in by_subject[
        ("possible_equivalent_relation_contract", "process.0")
    ]
    assert "candidate:future_operation_method:new.1" in by_subject[
        ("possible_equivalent_relation_contract", "new.0")
    ]
    assert "possible_dominator:process:process.0" in by_subject[
        ("possible_dominated_process", "process.1")
    ]
    assert ("possible_dominated_process", "process.2") not in by_subject
    assert ("possible_equivalent_relation_contract", "process.2") not in by_subject
    assert all(finding.significance == "informational" for finding in findings)

    # Confirm the same diagnosis on a *real* Composition with an additional
    # compatible Process. The Domain and Application intentionally continue to
    # offer both candidates: a diagnostic is not an automatic rule or deletion.
    from space_idle.app_contracts.queries import GetOperationalNode
    from space_idle.composition.analysis_graph import build_definition_dependency_graph
    from space_idle.analysis_coverage import inspect_definition_coverage
    from space_idle.content.base_ids import PROCESS_FOOD_PRODUCTION, FOOD_FARM, EARTH

    new_id = DefinitionId("experiment.duplicate.food_process")

    def author_variant(sim, _catalog):
        sim.industry.processes[new_id] = replace(
            sim.industry.processes[PROCESS_FOOD_PRODUCTION], id=new_id,
            display_name="Alternate food production",
        )

    app = build_game_application_for_scenario(
        build_standard_scenario_definition(), definition_transform=author_variant,
    )
    before = capture_state(app._simulation)
    authored_graph = build_definition_dependency_graph(app._simulation, app._catalog)
    assert not authored_graph.diagnostics
    authored_findings = inspect_definition_coverage(authored_graph)
    assert any(row.code == "possible_equivalent_relation_contract"
               and row.subject.id == str(new_id)
               and f"candidate:process:{PROCESS_FOOD_PRODUCTION}" in row.evidence
               for row in authored_findings)
    food = next(row for row in app.query(GetOperationalNode(str(EARTH))).industry
                if row.facility_definition_id == str(FOOD_FARM))
    assert {candidate.process_id for candidate in food.process_options} == {
        str(new_id), str(PROCESS_FOOD_PRODUCTION),
    }
    assert capture_state(app._simulation) == before


def test_current_decision_projection_uses_live_queries_and_does_not_change_owner_state(monkeypatch, capsys):
    """Static relations, present eligibility and actual settlements never share a solver.

    The explicit Founder/Transport scopes are ordinary Domain Queries and
    their blockers are not inferred from Content names or the static Graph.
    """
    from dataclasses import asdict

    from scripts.analysis_decision_projection import observe_application_decisions
    from space_idle.app_contracts.queries import (
        GetBuildOptions, GetCatalog, GetLogistics, GetMarket, GetNonSurfaceFoundingOptions,
        GetOperationalNode, GetResearch, GetSurfaceMap, GetTransportAllocationOptions, GetWorld,
    )

    app, ordinary = build_game_application(), build_game_application()
    before = capture_state(app._simulation)
    world = app.query(GetWorld())
    selected = world.operational_nodes[0].id
    scope = frozenset((SpatialNodeId(selected),))
    founding_target = next((body.id, context.spatial_node_id)
                          for body in app.query(GetCatalog()).celestial_bodies
                          for context in app.query(GetNonSurfaceFoundingOptions(body.id)).contexts
                          if not context.operational)
    transport_pair = (world.operational_nodes[0].id, world.operational_nodes[1].id)
    surface = next(body for body in app.query(GetCatalog()).celestial_bodies
                   if body.id == "base.body.earth")
    surface_cell = (surface.id, app.query(GetSurfaceMap(surface.id)).cells[0].id)
    observed = observe_application_decisions(
        app, operational_node_ids=scope,
        founding_targets=(founding_target,), surface_cells=(surface_cell,),
        transport_pairs=(transport_pair,),
    )
    assert observed["day"] == world.day
    assert observed["operational_node_scope"] == [selected]
    assert observed["layer"] == "application_current_eligibility"
    assert capture_state(app._simulation) == before
    assert observed == observe_application_decisions(
        app, operational_node_ids=scope,
        founding_targets=(founding_target,), surface_cells=(surface_cell,),
        transport_pairs=(transport_pair,),
    )
    rows = observed["entries"]
    assert rows == sorted(rows, key=lambda row: (row["kind"], row["context"], row["id"]))
    assert all(isinstance(row["blockers"], list) for row in rows)
    assert len({(row["kind"], row["context"], row["id"]) for row in rows}) == len(rows)
    by_kind = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)
    local = app.query(GetOperationalNode(selected))
    for facility in local.facilities:
        value = next(row for row in by_kind["facility_decommission"] if row["id"] == facility.id)
        assert (value["allowed"], value["blockers"]) == (
            facility.can_decommission, [asdict(item) for item in facility.decommission_blockers])
    for industry in local.industry:
        for option in industry.process_options:
            row = next(value for value in by_kind["process_selection"]
                       if value["id"] == f"{industry.facility_id}:{option.process_id}")
            assert row["allowed"] == option.can_select
            assert row["blockers"] == [asdict(item) for item in option.blockers]
    for extraction in local.extraction:
        for option in extraction.method_options:
            row = next(value for value in by_kind["extraction_selection"]
                       if value["id"] == f"{extraction.facility_id}:{option.method_id}")
            assert row["allowed"] == option.can_select
            assert row["blockers"] == [asdict(item) for item in option.blockers]
    for option in app.query(GetBuildOptions(selected)).items:
        row = next(value for value in by_kind["facility_construction"]
                   if value["id"] == option.facility_definition_id)
        assert row["allowed"] == option.can_plan
        assert row["blockers"] == [asdict(item) for item in option.blockers]
    by_research = {row["id"]: row for row in by_kind["research_start"]}
    for research in app.query(GetResearch()).items:
        assert by_research[research.id]["allowed"] == research.can_start
        assert by_research[research.id]["blockers"] == [asdict(value) for value in research.start_blockers]
    assert any(not row["allowed"] and row["blockers"] for row in by_research.values())
    for candidate in app.query(GetLogistics()).vehicle_production_options:
        if candidate.operational_node_id != selected:
            continue
        row = next(value for value in by_kind["vehicle_production"]
                   if value["id"] == candidate.vehicle_definition_id)
        assert row["allowed"] == candidate.can_plan
        assert row["blockers"] == [asdict(value) for value in candidate.blockers]
    for option in app.query(GetNonSurfaceFoundingOptions(*founding_target)).contexts:
        if option.spatial_node_id != founding_target[1]:
            continue
        for founding in option.foundation_options:
            row = next(value for value in by_kind["non_surface_founding"]
                       if value["id"] == founding.comparison_key)
            assert row["allowed"] == founding.can_plan
            assert row["blockers"] == [asdict(value) for value in founding.blockers]
    map_view = app.query(GetSurfaceMap(surface_cell[0], founding_cell_ids=(surface_cell[1],)))
    selected_cell = next(item for item in map_view.cells if item.id == surface_cell[1])
    for found in selected_cell.foundation_options:
        row = next(value for value in by_kind["surface_founding"]
                   if value["id"] == found.comparison_key)
        assert row["allowed"] == found.can_plan
        assert row["blockers"] == [asdict(value) for value in found.blockers]
    for development in selected_cell.development_options:
        row = next(value for value in by_kind["surface_development"]
                   if value["id"] == development.location_id)
        assert row["allowed"] == development.can_plan
        assert row["blockers"] == [asdict(value) for value in development.blockers]
    for option in app.query(GetTransportAllocationOptions(*transport_pair)).options:
        row = next(value for value in by_kind["transport_allocation_option"]
                   if value["observed"]["vehicle_definition_id"] == option.vehicle_definition_id)
        assert row["allowed"] is None  # Query deliberately does not expose can_plan.
        assert row["blockers"] == [asdict(value) for value in option.blockers]
    interfaces = {item.id: item.operational_node_id for item in app.query(GetMarket()).interfaces}
    assert all(interfaces[row["observed"]["market_interface_id"]] == selected
               for row in by_kind.get("market_order", ()))
    with pytest.raises(ValueError, match="unknown Operational Node"):
        observe_application_decisions(app, operational_node_ids=frozenset((SpatialNodeId("invalid.node"),)))
    # The executable dev export keeps static graph, current eligibility and
    # inventory/capacity observation as separate layers with the same node ID.
    import sys
    from scripts.analyze_definition_graph import main as export_graph
    with monkeypatch.context() as patch:
        patch.setattr(sys, "argv", ["analyze_definition_graph.py", "--state", "--decisions",
                                    "--coverage", "--technology-outlets",
                                    "--node", selected, "--founding-target",
                                    ":".join(founding_target), "--surface-cell",
                                    ":".join(surface_cell), "--transport-pair",
                                    ":".join(transport_pair)])
        export_graph()
    exported = json.loads(capsys.readouterr().out)
    assert exported["current_eligibility"] == observed
    assert exported["state_observation"]
    assert exported["definition_graph"]
    assert len(exported["technology_outlets"]) == len(app.query(GetResearch()).items)
    assert isinstance(exported["coverage_findings"], list)
    assert exported["current_eligibility"]["layer"] != exported["state_observation"].get("layer")
    assert capture_state(app._simulation) == before
    for instance in (app, ordinary):
        instance.execute(AdvanceTime(2))
    assert capture_state(app._simulation) == capture_state(ordinary._simulation)


def test_optional_canonical_trace_matches_authoritative_stock_and_preserves_save_and_gameplay():
    ordinary = build_game_application()
    observed = build_game_application()
    start = capture_state(observed._simulation)
    assert start == capture_state(ordinary._simulation)
    sim = observed._simulation
    stock = {(str(node), str(rid)): value for (node, rid), value in sim.inventory.stock.items()}
    with observe_canonical_day(sim) as trace:
        observed.execute(AdvanceTime(1))
    ordinary.execute(AdvanceTime(1))
    assert capture_state(sim) == capture_state(ordinary._simulation)
    assert sim.inventory._settlement_observer is None
    assert sim._analysis_decision_observer is None
    assert trace.allocations
    assert trace.movements
    # Capacity headroom is unused supply, never an unmet Activity request.
    capacities = [row for row in trace.allocations if row.kind == "finite_constraint"]
    assert capacities
    assert all(row.requested is None and row.allocated is None and row.unmet is None
               and row.capacity is not None and row.used is not None and row.remaining is not None
               and row.capacity >= row.used - 1e-9 for row in capacities)
    assert any(row.remaining > 0 for row in capacities)
    assert all(row.capacity is None and row.used is None and row.remaining is None
               for row in trace.allocations if row.kind != "finite_constraint")
    final = {(str(node), str(rid)): value for (node, rid), value in sim.inventory.stock.items()}
    reconciled = trace.reconcile(stock, final)
    assert all(abs(item['unattributed_delta_t']) < 1e-7 for item in reconciled)
    assert all(item['settled_net_t'] == pytest.approx(
        item['attributed_activity_delta_t'] + item['custody_delta_t']
        + item['unknown_cause_delta_t']) for item in reconciled)
    assert any(abs(item['attributed_activity_delta_t']) > 1e-7 for item in reconciled)
    assert all(abs(item['unknown_cause_delta_t']) < 1e-7 for item in reconciled)
    assert any(row.direction == 'inventory_in' for row in trace.movements)
    assert any(row.direction == 'inventory_out' for row in trace.movements)
    # These are actual Owner settlements, not static output rate forecasts.
    flows = trace.activity_flows()
    assert any(row.activity_id.startswith('industry_process:') and row.source_owner.startswith('process:')
               and row.destination_owner.startswith('inventory:') for row in flows)
    assert any(row.activity_id.startswith('extraction:') and row.source_owner.startswith('extraction_facility:')
               for row in flows)
    assert any(row.activity_id.startswith('facility_maintenance:')
               and row.destination_owner.startswith('maintained_facility:') for row in flows)
    assert any(row.activity_id.startswith('population_life_support:')
               and row.destination_owner.startswith('life_support:') for row in flows)
    assert all(row.quantity_t > 0 for row in flows)
    for direction in ('inventory_in', 'inventory_out'):
        attributed = [move for move in trace.movements if move.direction == direction
                      and move.counterparty_id is not None and move.activity_id is not None]
        projected = [flow for flow in flows if (
            (flow.destination_owner.startswith('inventory:')) if direction == 'inventory_in'
            else (flow.source_owner.startswith('inventory:'))
        )]
        assert sum(row.quantity_t for row in projected) == pytest.approx(
            sum(row.quantity_t for row in attributed)
        )
    assert all(row.counterparty_id is not None and row.activity_id is not None
               for row in trace.movements if row.activity_id is not None)
    assert sum(row.quantity_t for row in flows if row.destination_owner.startswith('inventory:')) <= (
        sum(row.quantity_t for row in trace.movements if row.direction == 'inventory_in') + 1e-9
    )
    assert json.dumps(observe_state(sim).to_json_data(), ensure_ascii=False)
    with pytest.raises(RuntimeError, match='nested'):
        with observe_canonical_day(sim):
            with observe_canonical_day(sim):
                pass
    assert capture_state(sim) == capture_state(ordinary._simulation)


def test_scoped_canonical_allocation_preserves_node_constraint_and_resource_identity():
    app = build_game_application()
    sim = app._simulation
    node, resource = next((node, resource) for (node, resource), stock in sim.inventory.stock.items()
                          if stock > 0)
    with observe_canonical_day(sim, operational_node_ids=frozenset((node,)),
                               resource_ids=frozenset((resource,))) as trace:
        app.execute(AdvanceTime(1))
    constraints = [row for row in trace.allocations if row.kind == "finite_constraint"]
    assert any(row.provenance == "allocation:resource" and row.subject_id == str(resource)
               and row.context_id == f"node:{node}" for row in constraints)
    assert all(row.subject_id == str(resource) for row in constraints
               if row.provenance == "allocation:resource")
    assert all(row.context_id in (str(node), f"node:{node}", "organization")
               for row in trace.allocations)
    assert all(row.subject_id == str(resource) for row in trace.allocations
               if row.kind == "resource_request")
    assert all(row.unmet is None and row.remaining is not None for row in constraints)


def test_owner_scoped_custody_transfer_is_not_mistaken_for_inventory_or_resource_creation():
    app = build_game_application()
    sim = app._simulation
    node, resource = next((node, rid) for node, rid in sim.inventory.stock
                          if sim.inventory.available(node, rid) >= 1)
    owner = EntityId('test.analytics.project.custody')
    quantity = min(0.25, sim.inventory.available(node, resource))
    before = sim.inventory.amount(node, resource)
    with observe_canonical_day(sim, operational_node_ids=frozenset((node,)),
                               resource_ids=frozenset((resource,))) as trace:
        sim.inventory.stage_allocated(owner, node, resource, quantity)
        assert sim.inventory.amount(node, resource) == pytest.approx(before - quantity)
        assert sim.inventory.staged_for(owner, node, resource) == pytest.approx(quantity)
        staged = [row for row in observe_state(sim, operational_node_ids=frozenset((node,)),
                                               resource_ids=frozenset((resource,))).metrics
                  if row.kind == 'staged_resource']
        assert len(staged) == 1
        assert staged[0].quantity == pytest.approx(quantity)
        assert staged[0].context_id == str(node)
        assert staged[0].provenance == f'inventory.external_occupancy:{owner}'
        assert sim.inventory.amount(node, resource) == pytest.approx(before - quantity)
        sim.inventory.unstage_to_stock(owner, node, resource, quantity)
    assert sim.inventory.amount(node, resource) == pytest.approx(before)
    assert sim.inventory.staged_for(owner, node, resource) == pytest.approx(0)
    assert {row.direction for row in trace.movements} == {
        'inventory_in', 'inventory_out', 'external_storage_in', 'external_storage_out'
    }
    assert trace.inventory_balance(node_id=str(node), resource_id=str(resource)) == pytest.approx(0)
    transfers = trace.custody_transfers()
    assert len(transfers) == 2
    assert [(row.source_owner, row.destination_owner) for row in transfers] == [
        (f'inventory:{node}', f'staging:{owner}'),
        (f'staging:{owner}', f'inventory:{node}'),
    ]
    assert all(row.quantity_t == pytest.approx(quantity) for row in transfers)
    payload = {'runs': [{'name': 'custody', 'canonical_traces': [trace.to_json_data()]}]}
    assert 'staging:' in to_csv(payload, 'custody_transfers')
    assert trace.activity_flows() == ()  # custody reclassification is not new production
    assert trace.unattributed_movements() == ()  # not an unknown source/sink either
    assert trace.to_json_data()['unattributed_movements'] == []
    assert to_csv(payload, 'unattributed_movements') == ''
    html = project_html({**payload, 'runs': [{**payload['runs'][0],
        'observations': [{'day': 0}, {'day': 1}],
        'content_definitions_sha256': 'known', 'flow_reconciliation': []}]})
    assert '確定した拠点Inventory' in html
    assert '供給元未確定' in html  # diagram headings, but no fabricated lanes
    assert 'staging:' in html
    # A later transfer from staging to a known real activity is a single
    # additional causal flow, not another Inventory production/consumption.
    with observe_canonical_day(sim, operational_node_ids=frozenset((node,)),
                               resource_ids=frozenset((resource,))) as transferred:
        sim.inventory.stage_allocated(owner, node, resource, quantity)
        sim.inventory.release_storage_occupancy(
            owner, node, resource, quantity,
            destination_owner='vehicle_production:test', activity_id='vehicle_production_inputs:test',
        )
    assert len(transferred.custody_transfers()) == 1
    assert transferred.activity_flows() == (ActivityFlow(
        sim.day, str(resource), quantity, f'staging:{owner}',
        'vehicle_production:test', 'vehicle_production_inputs:test',
        'inventory.release_storage_occupancy',
    ),)
    assert transferred.unattributed_movements() == ()
    assert transferred.inventory_balance(node_id=str(node), resource_id=str(resource)) == pytest.approx(-quantity)
    with observe_canonical_day(sim, operational_node_ids=frozenset((node,)),
                               resource_ids=frozenset((resource,))) as unknown:
        sim.inventory.occupy_storage(owner, node, resource, quantity)
        sim.inventory.release_storage_occupancy(owner, node, resource, quantity)
    assert unknown.activity_flows() == ()
    assert {row.direction for row in unknown.unattributed_movements()} == {
        'external_storage_in', 'external_storage_out',
    }


def test_external_market_commitment_observation_distinguishes_provider_stock_and_pending_admission():
    from space_idle.application_commands import CreateTradeOrder, AdvanceTime, GetMarket
    from space_idle.persistence import capture_state

    app = build_game_application()
    sim = app._simulation
    interface = next(row for row in app.query(GetMarket()).interfaces
                     if row.enabled and any(offer.buy_price_musd_per_t is not None
                                            for offer in row.offers))
    offer = next(offer for offer in interface.offers if offer.buy_price_musd_per_t is not None)
    result = app.execute(CreateTradeOrder('buy', offer.resource_id, interface.id,
                                          quantity_target_t=0.2))
    assert result.created_id
    app.execute(AdvanceTime(1))
    commitments = tuple(row for row in sim.market.buy_commitments.values()
                        if str(row.order_id) == result.created_id)
    assert commitments  # Market acquisition reserves before the boundary delivery.
    resource = DefinitionId(offer.resource_id)
    provider = DefinitionId(interface.provider_id)
    node = SpatialNodeId(interface.operational_node_id)
    before = capture_state(sim)
    scoped = observe_state(sim, operational_node_ids=frozenset((node,)),
                           resource_ids=frozenset((resource,)))
    assert capture_state(sim) == before
    committed = [row for row in scoped.metrics if row.kind == 'external_market_supply_committed']
    assert sum(row.quantity for row in committed) == pytest.approx(
        sim.market.reserved_provider_supply_t(provider, resource))
    assert all(row.context_id == str(provider) and row.provenance.startswith('market.buy_commitment:')
               for row in committed)
    # Commitment is a claim on existing external supply, not an extra physical
    # stock at the operational Node or a completed Inventory arrival.
    supply = {row.kind: row.quantity for row in observe_state(sim).metrics
              if row.context_id == str(provider) and row.subject_id == str(resource)}
    assert supply['external_market_supply_remaining'] == pytest.approx(
        supply['external_market_supply_available'] + sum(row.quantity for row in committed))
    assert not [row for row in observe_state(sim, operational_node_ids=frozenset((node,)),
                                             resource_ids=frozenset((DefinitionId('unrelated'),))).metrics
                if row.kind == 'external_market_supply_committed']
    # Disable the interface without cancelling an existing physical obligation.
    market_interface = sim.market.interfaces[EntityId(interface.id)]
    sim.market.interfaces[market_interface.id] = replace(market_interface, enabled=False)
    held = observe_state(sim, operational_node_ids=frozenset((node,)),
                         resource_ids=frozenset((resource,)))
    assert sum(row.quantity for row in held.metrics if row.kind == 'external_market_supply_committed') == pytest.approx(
        sum(commitment.remaining_quantity_t for commitment in commitments))


def test_typed_independent_scenario_and_content_variants_do_not_mutate_base_or_initialization():
    base = build_standard_scenario_definition()
    original = base.inventory_stock[0]
    variation = scenario_variant(base, {'inventory_stock': [{
        'operational_node_id': str(original.operational_node_id),
        'resource_id': str(original.resource_id),
        'amount_t': original.amount_t + 2,
    }]})
    assert base.inventory_stock[0] == original
    assert variation != base
    control = build_game_application_for_scenario(base)
    variant = build_game_application_for_scenario(variation)
    assert capture_state(control._simulation) != capture_state(variant._simulation)
    process = next(p for p in control._simulation.industry.processes.values() if p.outputs_per_day)
    rid = next(iter(process.outputs_per_day))
    value = process.outputs_per_day[rid] + 0.25
    def edit(sim, catalog):
        apply_content_variant(sim, catalog, ({'kind': 'process', 'id': str(process.id),
                                              'field': 'outputs_per_day', 'resource_id': str(rid),
                                              'value': value},))
    modified = build_game_application_for_scenario(base, definition_transform=edit)
    assert modified._simulation.industry.processes[process.id].outputs_per_day[rid] == pytest.approx(value)
    assert control._simulation.industry.processes[process.id].outputs_per_day[rid] != value
    assert capture_state(control._simulation) == capture_state(modified._simulation)
    with pytest.raises(ValueError, match='unknown Scenario variant'):
        scenario_variant(base, {'impossible_initial_state': []})
    with pytest.raises(ValueError, match='unsupported typed Content'):
        edit_that_does_not_exist = ({'kind': 'planet', 'id': 'X', 'field': 'gravity', 'value': 9},)
        apply_content_variant(modified._simulation, modified._catalog, edit_that_does_not_exist)


def test_case_execution_reproducibility_projection_and_missing_observation_pareto():
    app = build_game_application()
    resource, node = next((str(rid), str(node)) for (node, rid), value in app._simulation.inventory.stock.items()
                          if value > 0)
    plan = {'days': 1, 'cases': [
        {'name': 'baseline', 'commands': []},
        {'name': 'inventory-change', 'commands': [], 'scenario_variant': {
            'inventory_stock': [{'resource_id': resource, 'operational_node_id': node, 'amount_t': 777.0}],
        }},
    ]}
    days, cases = parse_cases(plan)
    runs = run_experiments(cases, days=days)
    again = run_experiments(cases, days=days)
    assert [row.to_json_data() for row in runs] == [row.to_json_data() for row in again]
    report = compare_experiments(runs)['comparisons'][0]
    assert not report['same_comparison_conditions']
    assert report['same_observation_scope']
    assert all(row['difference_t'] == pytest.approx(
        row['variant_settled_t'] - row['baseline_settled_t'])
        for row in report['settlement_differences'])
    assert all(row['difference'] is not None for row in report['allocation_differences'])
    assert runs[0].content_definitions_sha256 == runs[1].content_definitions_sha256
    assert runs[0].initial_state_sha256 != runs[1].initial_state_sha256
    # Optional experiments consume exactly the same canonical Simulation and
    # preserve rejection semantics; they merely add read-only Query snapshots.
    decision_runs = run_experiments(cases, days=days, observe_decisions=True,
                                    operational_node_ids=frozenset((SpatialNodeId(node),)))
    repeated = run_experiments(cases, days=days, observe_decisions=True,
                               operational_node_ids=frozenset((SpatialNodeId(node),)))
    assert [item.to_json_data() for item in decision_runs] == [item.to_json_data() for item in repeated]
    assert all(len(item.decision_observations) == days + 1 for item in decision_runs)
    scoped_runs = run_experiments(cases, days=days,
                                  operational_node_ids=frozenset((SpatialNodeId(node),)))
    assert all(item.observations == run.observations
               and item.rejected_commands == run.rejected_commands
               and item.canonical_traces == run.canonical_traces
               for item, run in zip(decision_runs, scoped_runs))
    decision_diff = compare_experiments(decision_runs)['comparisons'][0]['decision_differences']
    assert isinstance(decision_diff, list)
    assert all(row['baseline_initial'] is None or row['baseline_initial']['kind'] == row['kind']
               for row in decision_diff)
    assert report['decision_differences'] is None
    # Independent Definition additions change *candidate membership*, not
    # the canonical eligibility rule. Missing alternatives are null, not false.
    from space_idle.content.base_ids import PROCESS_FOOD_PRODUCTION
    from space_idle.content.base_scenario import build_standard_scenario_definition
    added = DefinitionId("experiment.alternative.food_process")
    def alternative_factory():
        def insert(sim, _catalog):
            sim.industry.processes[added] = replace(
                sim.industry.processes[PROCESS_FOOD_PRODUCTION], id=added,
                display_name="Alternate food processing",
            )
        return build_game_application_for_scenario(
            build_standard_scenario_definition(), definition_transform=insert,
        )
    alternate = run_experiments((ExperimentCase("standard", build_game_application, _idle),
                                 ExperimentCase("added-method", alternative_factory, _idle)),
                                days=0, observe_decisions=True)
    changed = compare_experiments(alternate)['comparisons'][0]
    assert not changed['same_content_definitions']
    assert any(item['kind'] == 'process_selection'
               and item['id'].endswith(f":{added}")
               and item['baseline_initial'] is None
               and item['variant_initial'] is not None
               for item in changed['decision_differences'])
    assert alternate[0].initial_state_sha256 == alternate[1].initial_state_sha256
    assert all(abs(row['unattributed_delta_t']) < 1e-7 for run in runs for row in run.flow_reconciliation)
    payload = {'runs': [run.to_json_data() for run in runs]}
    assert 'inventory_in' in to_csv(payload, 'inventory_movements')
    assert 'provenance' in to_csv(payload, 'state_metrics')
    assert '<svg' in project_html(payload) and '確定入出庫' in project_html(payload)
    metric = next(row for row in runs[0].observations[-1].metrics if row.kind == 'inventory_stock')
    objective = ParetoObjective(metric.kind, metric.subject_id, metric.context_id,
                                metric.unit, metric.provenance, 'maximize')
    result = compare_pareto(runs, [objective])
    assert len(result['cases']) == 2
    missing = replace(objective, subject_id='nonexistent.Resource')
    assert all(row['values'] is None and not row['comparable']
               for row in compare_pareto(runs, [missing])['cases'])


def test_graph_reports_registered_definition_omissions_duplicate_relations_and_time_basis():
    node = DependencyNode('test_method', 'generic')
    resource = DependencyNode('resource', 'R')
    extra = DependencyNode('test_method', 'expected')
    relation = DependencyRelation('consumes_resource', resource, node, 'test:recipe', 2.0, 't')
    registry = DefinitionGraphRegistry()
    registry.register('method', lambda: DependencyFragment((node, resource), (relation, relation)),
                      expected_definitions=lambda: (node, extra), relation_kinds={'consumes_resource'})
    diagnostic = {row.code for row in registry.build().diagnostics}
    assert {'duplicate_relation', 'quantitative_relation_without_time_basis',
            'unrepresented_registered_definition'} <= diagnostic


def test_initial_facility_scenario_variants_use_regular_site_and_power_contracts():
    from space_idle.content.base_scenario import build_standard_scenario_definition

    scenario = build_standard_scenario_definition()
    # A complete typed asset list retains multiplicity and actual investment.
    replacement = [
        {
            "definition_id": str(row.definition_id),
            "operational_node_id": str(row.operational_node_id),
            "site_cell_id": None if row.site_cell_id is None else str(row.site_cell_id),
            "invested_resources": [[str(resource), amount] for resource, amount in row.invested_resources],
        }
        for row in scenario.facilities
        if row.definition_id != ids.GRID_POWER_SUPPLY
    ]
    without_grid = scenario_variant(scenario, {"facilities": replacement})
    assert len(without_grid.facilities) == len(scenario.facilities) - 1
    assert len(scenario.facilities) == len(build_standard_scenario_definition().facilities)

    original = build_game_application_for_scenario(scenario)
    variant = build_game_application_for_scenario(without_grid)
    # The variant omitted the Grid asset, but initial Facility levels still go
    # through normal installed Capacity and later Save/Load semantics.
    leveled = build_game_application_for_scenario(scenario_variant(scenario, {
        'facilities': [{
            'definition_id': str(row.definition_id),
            'operational_node_id': str(row.operational_node_id),
            'site_cell_id': None if row.site_cell_id is None else str(row.site_cell_id),
            'invested_resources': [[str(resource), amount] for resource, amount in row.invested_resources],
            'level': 2 if row.definition_id == ids.METAL_ORE_MINE else 1,
        } for row in scenario.facilities],
    }))
    normal_mine = next(row for row in original._simulation.facilities.facilities.values()
                       if row.definition_id == ids.METAL_ORE_MINE)
    leveled_mine = next(row for row in leveled._simulation.facilities.facilities.values()
                        if row.definition_id == ids.METAL_ORE_MINE)
    assert leveled_mine.level == 2
    assert leveled._simulation.extraction.nominal_capacity(leveled_mine) == pytest.approx(
        2 * original._simulation.extraction.nominal_capacity(normal_mine)
    )
    with pytest.raises(ValueError, match='level'):
        scenario_variant(scenario, {'facilities': [{
            'definition_id': str(ids.METAL_ORE_MINE),
            'operational_node_id': str(ids.EARTH), 'level': 0,
        }]})
    node = ids.EARTH
    original_power = original._simulation.power.snapshot(node, original._simulation.facilities, 0)
    variant_power = variant._simulation.power.snapshot(node, variant._simulation.facilities, 0)
    assert original_power.generation_mw > variant_power.generation_mw
    assert all(row.definition_id != ids.GRID_POWER_SUPPLY for row in variant._simulation.facilities.all_at(node))
    assert variant._simulation.projects.recipes[ids.GRID_POWER_SUPPLY] == original._simulation.projects.recipes[ids.GRID_POWER_SUPPLY]
    with pytest.raises(ValueError, match="nonnegative"):
        scenario_variant(scenario, {"facilities": [{"definition_id": str(ids.FOOD_FARM),
            "operational_node_id": str(node), "invested_resources": [[str(ids.WATER), -1.0]]}]})


def test_comparative_canonical_policy_connects_market_construction_power_and_multiple_nodes():
    """Different authored conditions remain distinct from policy and observed stock flow.

    An adaptive policy reads actual Application options, not guessed recipe IDs
    or a fixture-specific preferred build order. All cases use the same Command
    policy; each case composes its own State and typed Content before executing.
    """
    from space_idle.application_commands import CreateTradeOrder, GetBuildOptions, GetMarket, PlanBuild
    from space_idle.content import base_ids as ids
    from space_idle.content.base_scenario import build_standard_scenario_definition

    original = build_standard_scenario_definition()
    candidate_stock = next(row for row in original.inventory_stock
                           if row.operational_node_id == ids.EARTH
                           and row.resource_id == ids.STRUCTURAL_COMPONENTS)
    extra_stock = scenario_variant(original, {'inventory_stock': [{
        'operational_node_id': str(candidate_stock.operational_node_id),
        'resource_id': str(candidate_stock.resource_id),
        'amount_t': candidate_stock.amount_t + 50.0,
    }]})

    def make_case(name, scenario, edits=()):
        def factory():
            return build_game_application_for_scenario(
                scenario,
                definition_transform=(
                    (lambda sim, catalog: apply_content_variant(sim, catalog, edits)) if edits else None
                ),
            )

        def policy(app, offset):
            if offset != 0:
                return ()
            options = app.query(GetBuildOptions(str(ids.EARTH)))
            feasible = [row for row in options.items if row.can_plan and not row.blockers
                        and row.construction_required > 0]
            assert feasible
            selected = min(feasible, key=lambda row: (row.construction_required,
                                                       row.facility_definition_id))
            interface = next(row for row in app.query(GetMarket()).interfaces
                             if row.operational_node_id == str(ids.EARTH) and row.enabled)
            offer = next(row for row in interface.offers if row.buy_price_musd_per_t is not None)
            return (CreateTradeOrder('buy', offer.resource_id, interface.id,
                                     quantity_target_t=1.25),
                    PlanBuild(str(ids.EARTH), selected.facility_definition_id))

        return ExperimentCase(name, factory, policy)

    runs = run_experiments((
        make_case('baseline', original),
        make_case('reduced-power', original, ({'kind': 'power', 'id': str(ids.GRID_POWER_SUPPLY),
                                              'field': 'generation_mw', 'value': 0.1},)),
        make_case('additional-stock', extra_stock),
    ), days=4, operational_node_ids=frozenset((ids.EARTH, ids.LEO)))
    assert all(len(run.attempted_commands) == 2 and not run.rejected_commands for run in runs)
    assert all(len(run.canonical_traces) == 4 and len(run.observations) == 5 for run in runs)
    assert all(abs(row['unattributed_delta_t']) < 1e-7
               for run in runs for row in run.flow_reconciliation)
    assert all({move.operation for trace in run.canonical_traces for move in trace.movements}
               for run in runs)
    assert runs[0].content_definitions_sha256 != runs[1].content_definitions_sha256
    assert runs[0].initial_state_sha256 == runs[1].initial_state_sha256
    assert runs[0].content_definitions_sha256 == runs[2].content_definitions_sha256
    assert runs[0].initial_state_sha256 != runs[2].initial_state_sha256
    comparison = compare_experiments(runs)
    assert len(comparison['comparisons']) == 2
    assert all(row['same_observation_scope'] for row in comparison['comparisons'])
    # Comparison comes from measured settlements and the actual finite
    # allocation, not final Stock inferred as gross output or a second Solver.
    assert all('settlement_differences' in row and 'allocation_differences' in row
               for row in comparison['comparisons'])
    for row in comparison['comparisons']:
        assert all(delta['unit'] == 't' and delta['layer'] in {'activity', 'unknown', 'custody'}
                   for delta in row['settlement_differences'])
        assert all(delta['difference']['unmet'] == pytest.approx(
            delta['variant']['unmet'] - delta['baseline']['unmet'])
            for delta in row['allocation_differences'])
    assert all(not row['same_comparison_conditions'] for row in comparison['comparisons'])
    assert all((metric.context_id in (str(ids.EARTH), str(ids.LEO), 'organization')
                or metric.kind.startswith('external_market_'))
               for run in runs for observation in run.observations for metric in observation.metrics)
    again = run_experiments((make_case('baseline', original),), days=4,
                            operational_node_ids=frozenset((ids.EARTH, ids.LEO)))
    assert again[0].to_json_data() == runs[0].to_json_data()


def test_typed_content_add_remove_recompose_application_and_preserve_accounting(tmp_path):
    """New research/method/resource and deletion share Composition and UI contracts.

    Experiment cases recompose Definitions before Scenario instead of modifying
    a running game or inventing a second supply / tech eligibility evaluator.
    """
    from space_idle.application_commands import (GetCatalog, GetOperationalNode,
        GetResearch, StartResearch, SetResearchPrototypeSite,
        SetFacilityProcess, AdvanceTime, ApplicationError)
    from space_idle.persistence import save_game, load_game
    from space_idle.bootstrap import build_game_application_for_load
    from space_idle.validation_support import ConfigurationError

    resource_id = "experiment.resource.raw_mineral"
    research_id = "experiment.research.refining_method"
    process_id = "experiment.process.refining_method"
    changes = (
        {"operation": "add", "kind": "resource", "id": resource_id,
         "definition": {"display_name": "実験原料", "unit": "t", "category": "bulk"}},
        {"operation": "add", "kind": "research", "id": research_id,
         "definition": {"display_name": "代替資源加工", "prerequisites": [], "stage_specs": [
             {"stage_type": "theory", "stage_id": "concept", "research_point_cost": 1.0},
             {"stage_type": "prototype", "stage_id": "bench", "required_work": 1.0,
              "resources": {resource_id: 0.5},
              "site_requirements": {"capabilities": [
                  {"capability_id": "basic_structural_material", "required_state": "ACTIVE"}],
                  "spatial_classifications": [
                  {"classification": "SURFACE", "code": "prototype:surface",
                   "description": "試作には地表の作業場所が必要"}]},
              "execution_requirements": [{"service_type": "research_execution",
                                          "amount_per_execution": 1.0, "scope": "ORGANIZATION"}]},
         ]}},
        {"operation": "add", "kind": "process", "id": process_id,
         "definition": {"display_name": "実験用代替製法",
                        "required_capabilities": ["basic_structural_material"],
                        "inputs_per_day": {resource_id: 0.5},
                        "outputs_per_day": {str(ids.STRUCTURAL_COMPONENTS): 0.25},
                        "prerequisite_technologies": [research_id]}},
    )
    base = build_standard_scenario_definition()
    scenario = scenario_variant(base, {"inventory_stock": [{
        "operational_node_id": str(ids.EARTH), "resource_id": resource_id,
        "amount_t": 20.0,
    }]})

    def factory(scenario=scenario, changes=changes):
        return build_game_application_for_scenario(
            scenario, definition_transform=lambda sim, cat: apply_content_variant(sim, cat, changes),
        )

    app = factory()
    catalog = app.query(GetCatalog())
    assert any(str(row.id) == resource_id for row in catalog.resources)
    assert any(row.id == process_id for row in catalog.processes)
    assert any(row.id == research_id for row in catalog.research)
    assert any(row.id == research_id for row in app.query(GetResearch()).items)
    added_stages = app._simulation.research.definitions[DefinitionId(research_id)].stage_specs
    assert len(added_stages) == 2
    site_requirement = added_stages[1].site_requirements.spatial_classification_requirements[0]
    assert site_requirement.code == "prototype:surface"
    assert site_requirement.description == "試作には地表の作業場所が必要"
    assert added_stages[1].execution_requirements[0].service_type == "research_execution"
    from space_idle.composition.analysis_graph import build_definition_dependency_graph
    graph = build_definition_dependency_graph(app._simulation, app._catalog)
    assert not graph.diagnostics
    stage_node = DependencyNode("research_stage", research_id + "/bench")
    assert any(row.kind == "requires_site_capability" and row.target == stage_node
               and row.condition == "required_state:ACTIVE" for row in graph.relations)
    assert any(row.kind == "requires_site_classification" and row.target == stage_node
               and row.provenance.endswith("prototype:surface") for row in graph.relations)
    assert any(row.kind == "requires_execution_capacity" and row.target == stage_node
               and row.source == DependencyNode("service_capacity", "research_execution")
               and row.condition == "scope:ORGANIZATION" for row in graph.relations)
    assert any(row.kind == "consumes_resource" and row.target == stage_node
               and row.source == DependencyNode("resource", resource_id) for row in graph.relations)
    industry = next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                    if any(option.process_id == process_id for option in row.process_options))
    locked = next(option for option in industry.process_options if option.process_id == process_id)
    assert any(f"technology:{research_id}" in constraint.code for constraint in locked.blockers)
    with pytest.raises(ApplicationError):
        app.execute(SetFacilityProcess(industry.facility_id, process_id))
    assert app._simulation.inventory.amount(ids.EARTH, DefinitionId(resource_id)) == 20.0

    # The new authored Technology must also be obtainable through the actual
    # Research Stage lifecycle, rather than only a pre-completed Scenario flag.
    # Its typed Site and finite Service constraints are evaluated by Research,
    # not by an experiment-specific approximation.
    researched = factory()
    researched.execute(StartResearch(research_id))
    for _ in range(8):
        research_row = next(item for item in researched.query(GetResearch()).items if item.id == research_id)
        if research_row.current_stage_id == "bench":
            break
        researched.execute(AdvanceTime(1))
    assert research_row.current_stage_id == "bench"
    earth_site = next(site for site in research_row.execution_context_options
                      if site.operational_node_id == str(ids.EARTH))
    assert earth_site.can_select
    orbital_site = next(site for site in research_row.execution_context_options
                        if site.operational_node_id == str(ids.LEO))
    assert not orbital_site.can_select
    assert any(blocker.code == "prototype:surface" for blocker in orbital_site.blockers)
    with pytest.raises(ApplicationError):
        researched.execute(SetResearchPrototypeSite(research_id, "bench", str(ids.LEO)))
    researched.execute(SetResearchPrototypeSite(research_id, "bench", str(ids.EARTH)))
    researched.execute(AdvanceTime(1))
    stage_save = tmp_path / "research-prototype-variant.json"
    save_game(researched, stage_save)
    resumed, _ = load_game(stage_save, lambda: build_game_application_for_load(
        scenario=scenario, definition_transform=lambda sim, cat: apply_content_variant(sim, cat, changes),
    ))
    assert capture_state(resumed._simulation) == capture_state(researched._simulation)
    for _ in range(8):
        if DefinitionId(research_id) in resumed._simulation.technology.completed:
            break
        resumed.execute(AdvanceTime(1))
    assert DefinitionId(research_id) in resumed._simulation.technology.completed
    assert next(option for row in resumed.query(GetOperationalNode(str(ids.EARTH))).industry
                for option in row.process_options if option.process_id == process_id).can_select
    assert next(option for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                for option in row.process_options if option.process_id == process_id).can_select is False

    # Acquisition and existing equipment use different criteria: this research
    # enables an explicit Process choice, not an automatic asset modification.
    with_technology = scenario_variant(scenario, {"completed_technologies": [
        *map(str, base.completed_technologies), research_id,
    ]})
    enabled = factory(with_technology)
    chosen = next(row for row in enabled.query(GetOperationalNode(str(ids.EARTH))).industry
                  if any(option.process_id == process_id for option in row.process_options))
    option = next(option for option in chosen.process_options if option.process_id == process_id)
    assert option.can_select
    enabled.execute(SetFacilityProcess(chosen.facility_id, process_id))
    # A predeployed Facility's authored Process choice must use exactly the
    # same physical interface and completed-Technology gate as SetFacilityProcess.
    authored_process_rows = [{
        'definition_id': str(row.definition_id),
        'operational_node_id': str(row.operational_node_id),
        'site_cell_id': None if row.site_cell_id is None else str(row.site_cell_id),
        'invested_resources': [[str(resource), amount]
                               for resource, amount in row.invested_resources],
        'selected_process_id': (
            process_id if row.definition_id == enabled._simulation.facilities.facilities[
                EntityId(chosen.facility_id)
            ].definition_id else None
        ),
    } for row in scenario.facilities]
    initially_configured = scenario_variant(scenario, {'facilities': authored_process_rows})
    with pytest.raises(ValueError, match='technology'):
        factory(initially_configured)
    initially_unlocked = scenario_variant(with_technology, {'facilities': authored_process_rows})
    initial_process_app = factory(initially_unlocked)
    assert any(facility.selected_process_id == DefinitionId(process_id)
               for facility in initial_process_app._simulation.facilities.facilities.values())
    assert any(row.process_id == process_id
               for row in initial_process_app.query(GetOperationalNode(str(ids.EARTH))).industry)

    first = enabled._simulation.inventory.amount(ids.EARTH, DefinitionId(resource_id))
    enabled.execute(AdvanceTime(1))
    last = enabled._simulation.inventory.amount(ids.EARTH, DefinitionId(resource_id))
    assert last < first
    assert enabled._simulation.facilities.facilities[EntityId(chosen.facility_id)].selected_process_id == DefinitionId(process_id)
    path = tmp_path / "content-variant-state.json"
    save_game(enabled, path)
    restored, _ = load_game(path, lambda: build_game_application_for_load(
        scenario=with_technology,
        definition_transform=lambda sim, cat: apply_content_variant(sim, cat, changes),
    ))
    assert capture_state(restored._simulation) == capture_state(enabled._simulation)

    def policy(app, day):
        if day > 0:
            return ()
        rows = app.query(GetOperationalNode(str(ids.EARTH))).industry
        matches = (row for row in rows if any(option.process_id == process_id for option in row.process_options))
        row = next(matches, None)
        return () if row is None else (SetFacilityProcess(row.facility_id, process_id),)

    cases = (
        ExperimentCase("original", lambda: build_game_application_for_scenario(base), policy),
        ExperimentCase("new-method-locked", factory, policy),
        ExperimentCase("new-method-enabled", lambda: factory(with_technology), policy),
    )
    runs = run_experiments(cases, days=2)
    repeat = run_experiments(cases, days=2)
    assert [run.to_json_data() for run in runs] == [run.to_json_data() for run in repeat]
    assert runs[0].content_definitions_sha256 != runs[1].content_definitions_sha256
    assert runs[1].content_definitions_sha256 == runs[2].content_definitions_sha256
    assert runs[1].initial_state_sha256 != runs[2].initial_state_sha256
    assert runs[0].definition_graph_sha256 != runs[1].definition_graph_sha256
    assert len(runs[1].rejected_commands) == 1
    assert not runs[2].rejected_commands
    assert all(abs(row["unattributed_delta_t"]) < 1e-7
               for run in runs for row in run.flow_reconciliation)

    # Typed extraction methods participate in the same independent Content and
    # Scenario comparison: no experiment-only source or eligibility is invented.
    from space_idle.application_commands import SetFacilityExtractionMethod
    extraction_id = 'experiment.extraction.alternate_crust'
    extraction_edits = changes + (
        {'operation': 'add', 'kind': 'extraction', 'id': extraction_id,
         'source_id': str(ids.EXTRACTION_CRUST_ORE)},
        {'kind': 'extraction', 'id': extraction_id, 'field': 'resource_id',
         'value': str(ids.MINERAL_FEEDSTOCK)},
        {'kind': 'extraction', 'id': extraction_id, 'field': 'output_resource_id',
         'value': str(ids.MINERAL_FEEDSTOCK)},
        {'kind': 'extraction', 'id': extraction_id, 'field': 'prerequisite_technologies',
         'value': [research_id]},
    )
    authored_facilities = [{
        'definition_id': str(row.definition_id),
        'operational_node_id': str(row.operational_node_id),
        'site_cell_id': None if row.site_cell_id is None else str(row.site_cell_id),
        'invested_resources': [[str(resource), quantity]
                               for resource, quantity in row.invested_resources],
        'selected_extraction_method_id': (
            str(ids.EXTRACTION_CRUST_ORE) if row.definition_id == ids.METAL_ORE_MINE else None
        ),
    } for row in scenario.facilities]
    scenario_with_choice = scenario_variant(scenario, {'facilities': authored_facilities})
    scenario_with_unlock = scenario_variant(with_technology, {'facilities': authored_facilities})
    extraction_locked = factory(scenario_with_choice, extraction_edits)
    extraction_node = extraction_locked.query(GetOperationalNode(str(ids.EARTH)))
    method_row = next(row for row in extraction_node.extraction
                      if any(option.method_id == extraction_id for option in row.method_options))
    assert method_row.method_id == str(ids.EXTRACTION_CRUST_ORE)
    assert not next(option for option in method_row.method_options
                    if option.method_id == extraction_id).can_select
    graph = build_definition_dependency_graph(extraction_locked._simulation,
                                              extraction_locked._catalog)
    assert any(rel.kind == 'unlocks_method'
               and rel.source == DependencyNode('technology', research_id)
               and rel.target == DependencyNode('extraction_method', extraction_id)
               for rel in graph.relations)

    def choose_extraction(app, day):
        if day != 0:
            return ()
        node = app.query(GetOperationalNode(str(ids.EARTH)))
        row = next(item for item in node.extraction
                   if any(option.method_id == extraction_id for option in item.method_options))
        return (SetFacilityExtractionMethod(row.facility_id, extraction_id),)

    extraction_cases = (
        ExperimentCase('extraction-locked',
                       lambda: factory(scenario_with_choice, extraction_edits), choose_extraction),
        ExperimentCase('extraction-unlocked',
                       lambda: factory(scenario_with_unlock, extraction_edits), choose_extraction),
    )
    extraction_runs = run_experiments(extraction_cases, days=2)
    assert [run.to_json_data() for run in extraction_runs] == [
        run.to_json_data() for run in run_experiments(extraction_cases, days=2)
    ]
    assert len(extraction_runs[0].rejected_commands) == 1
    assert not extraction_runs[1].rejected_commands
    assert extraction_runs[0].content_definitions_sha256 == extraction_runs[1].content_definitions_sha256
    assert extraction_runs[0].initial_state_sha256 != extraction_runs[1].initial_state_sha256
    assert any(flow.activity_id.endswith(f':{ids.MINERAL_FEEDSTOCK}:{extraction_id}')
               for trace in extraction_runs[1].canonical_traces
               for flow in trace.activity_flows())
    assert all(abs(row['unattributed_delta_t']) < 1e-7
               for run in extraction_runs for row in run.flow_reconciliation)

    # An extraction method with no installed-compatible hardware is not an
    # invalid Content reference. It is an explicit authoring-coverage gap until
    # appropriate hardware appears; no imaginary provider is added to the game.
    from space_idle.analysis_coverage import inspect_definition_coverage
    orphan_id = 'experiment.extraction.future_instrument'
    orphan_edits = changes + (
        {'operation': 'add', 'kind': 'extraction', 'id': orphan_id,
         'source_id': str(ids.EXTRACTION_CRUST_ORE)},
        {'kind': 'extraction', 'id': orphan_id, 'field': 'required_capabilities',
         'value': ['basic_structural_material']},
    )
    orphan_app = factory(scenario, orphan_edits)
    orphan_graph = build_definition_dependency_graph(orphan_app._simulation, orphan_app._catalog)
    assert not orphan_graph.diagnostics
    assert any(row.code == 'extraction_method_without_registered_compatible_facility'
               and row.subject.id == orphan_id
               for row in inspect_definition_coverage(orphan_graph))

    # Removing a method changes the actual candidates/Definition Graph; nothing
    # rewrites the Scenario or dependent Technology requirements to conceal it.
    removed_method = changes + ({"operation": "remove", "kind": "process", "id": process_id},)
    no_method = factory(scenario, removed_method)
    assert all(row.id != process_id for row in no_method.query(GetCatalog()).processes)
    assert all(option.process_id != process_id
               for row in no_method.query(GetOperationalNode(str(ids.EARTH))).industry
               for option in row.process_options)

    # Removing referenced definitions must fail closed during Composition;
    # removing an unreferenced Resource still fails when Scenario retains stock.
    with pytest.raises((ConfigurationError, ValueError), match="Resource|catalog|unknown"):
        factory(scenario, changes + ({"operation": "remove", "kind": "resource", "id": resource_id},))
    with pytest.raises((ConfigurationError, ValueError), match="unknown research|technology|prerequisite"):
        factory(scenario, changes + ({"operation": "remove", "kind": "research", "id": research_id},))
    with pytest.raises((ConfigurationError, ValueError), match="Resource|resource definitions"):
        factory(scenario, removed_method + ({"operation": "remove", "kind": "resource", "id": resource_id},))
    # Definitions are isolated from the standard factory and other experiment cases.
    assert all(row.id != process_id for row in build_game_application().query(GetCatalog()).processes)


def test_independent_definition_membership_connects_assets_providers_acquisition_and_policy():
    """Added Definitions participate in the real Application, not a parallel experiment ruleset."""
    base = build_game_application()
    sim = base._simulation
    source_provider = next(provider for provider in sim.research.providers.values()
                           if provider.source_kind.value == "facility"
                           and any(fid in sim.projects.recipes and fid in sim.power.specs
                                   for fid in sim.research.compatible_facility_definition_ids(provider.id)))
    source_facility = next(fid for fid in sim.research.compatible_facility_definition_ids(source_provider.id)
                           if fid in sim.projects.recipes and fid in sim.power.specs)
    # Select by the actual Application acquisition contract, not registration order.
    from space_idle.application_commands import GetLogistics
    from space_idle.shared import DefinitionId
    # An independent Scenario explicitly supplies the researched acquisition
    # prerequisite. Both comparison variants start from the identical owner State.
    source_vehicle = min(
        (sim.transport.vehicle_defs[DefinitionId(row.vehicle_definition_id)]
         for row in base.query(GetLogistics()).vehicle_production_options
         if row.operational_node_id == str(ids.EARTH)
         and sim.transport.vehicle_defs[DefinitionId(row.vehicle_definition_id)].production.days > 0
         and not any(blocker.kind == "site" for blocker in row.blockers)),
        key=lambda row: (len(row.production.prerequisite_technologies), str(row.id)),
    )
    scenario = replace(build_standard_scenario_definition(),
                       completed_technologies=tuple(sorted(source_vehicle.production.prerequisite_technologies)))
    new_facility = 'experiment.facility.research'
    new_provider = 'experiment.provider.research'
    new_vehicle = 'experiment.vehicle.production'
    additions = [
        {'operation': 'add', 'kind': kind, 'source_id': str(source), 'id': target}
        for kind, source, target in (
            ('facility', source_facility, new_facility),
            ('construction', source_facility, new_facility),
            ('decommission', source_facility, new_facility),
            ('power', source_facility, new_facility),
            ('vehicle', source_vehicle.id, new_vehicle),
            ('research_provider', source_provider.id, new_provider),
        )
    ]
    edits = [
        {'kind': 'facility', 'id': new_facility, 'field': 'capability_supplies',
         'value': ['experiment_research_equipment']},
        {'kind': 'research_provider', 'id': new_provider,
         'field': 'required_source_capabilities', 'value': ['experiment_research_equipment']},
        {'kind': 'vehicle', 'id': new_vehicle, 'field': 'production_days', 'value': 5.0},
        {'kind': 'construction', 'id': new_facility, 'field': 'construction_work', 'value': 5.0},
    ]
    from space_idle.application_commands import GetBuildOptions, GetLogistics, PlanBuild, ProduceVehicle
    from space_idle.composition.analysis_graph import build_definition_dependency_graph

    def factory(additions=additions):
        return build_game_application_for_scenario(
            scenario,
            definition_transform=lambda runtime, catalog: apply_content_variant(
                runtime, catalog, additions + edits),
        )

    app = factory()
    options = app.query(GetBuildOptions(str(ids.EARTH)))
    facility_option = next(row for row in options.items
                           if row.facility_definition_id == new_facility)
    vehicle_option = next(row for row in app.query(GetLogistics()).vehicle_production_options
                          if row.vehicle_definition_id == new_vehicle
                          and row.operational_node_id == str(ids.EARTH))
    assert facility_option.can_plan and vehicle_option.can_plan
    graph = build_definition_dependency_graph(app._simulation, app._catalog)
    assert not graph.diagnostics
    assert any(row.kind == 'facility' and row.id == new_facility for row in graph.nodes)
    assert any(row.kind == 'vehicle' and row.id == new_vehicle for row in graph.nodes)
    assert any(row.kind == 'research_provider' and row.id == new_provider for row in graph.nodes)

    # Both strategies issue the same Player intent. The baseline rejects unknown
    # authored assets and records the blocker; the modified Content accepts them.
    def policy(_app, day):
        return (PlanBuild(str(ids.EARTH), new_facility),
                ProduceVehicle(new_vehicle, str(ids.EARTH))) if day == 0 else ()

    runs = run_experiments((ExperimentCase('base', lambda: build_game_application_for_scenario(scenario), policy),
                            ExperimentCase('variant', factory, policy)), days=2)
    assert len(runs[0].rejected_commands) == 2
    assert not runs[1].rejected_commands
    assert len(runs[1].attempted_commands) == 2
    assert all(abs(row['unattributed_delta_t']) < 1e-7
               for run in runs for row in run.flow_reconciliation)
    assert runs[0].content_definitions_sha256 != runs[1].content_definitions_sha256
    assert runs[0].initial_state_sha256 == runs[1].initial_state_sha256
    assert not compare_experiments(runs)['comparisons'][0]['same_comparison_conditions']
    assert runs[1].to_json_data() == run_experiments(
        (ExperimentCase('variant', factory, policy),), days=2,
    )[0].to_json_data()
    reordered = factory(list(reversed(additions)))
    assert build_definition_dependency_graph(reordered._simulation, reordered._catalog).to_json_data() == graph.to_json_data()

    # Additions never silently invent acquisition recipes. Missing references
    # or competing providers are invalid through normal Composition validation.
    with pytest.raises(ValueError):
        build_game_application_for_scenario(
            build_standard_scenario_definition(),
            definition_transform=lambda runtime, catalog: apply_content_variant(
                runtime, catalog, additions + edits + [
                    {'operation': 'remove', 'kind': 'facility', 'id': new_facility},
                ]),
        )
    with pytest.raises(ValueError):
        build_game_application_for_scenario(
            build_standard_scenario_definition(),
            definition_transform=lambda runtime, catalog: apply_content_variant(
                runtime, catalog, [additions[-1]]),
        )


def test_independent_survey_definition_requires_a_real_compatible_vehicle(tmp_path):
    from space_idle.composition.analysis_graph import build_definition_dependency_graph
    base = build_game_application()
    sim = base._simulation
    source = next(provider for provider in sim.survey.providers.values()
                  if provider.source_kind.value == 'fleet')
    craft = next(vehicle for vehicle in sim.transport.vehicle_definitions()
                 if source.required_source_capabilities.issubset(vehicle.generic_capabilities))
    added_vehicle = 'experiment.vehicle.survey'
    added_provider = 'experiment.provider.survey'
    edits = [
        {'operation': 'add', 'kind': 'vehicle', 'id': added_vehicle, 'source_id': str(craft.id)},
        {'kind': 'vehicle', 'id': added_vehicle, 'field': 'generic_capabilities',
         'value': sorted(set(craft.generic_capabilities) | {'experiment_survey_sensor'})},
        {'operation': 'add', 'kind': 'survey_provider', 'id': added_provider,
         'source_id': str(source.id)},
        {'kind': 'survey_provider', 'id': added_provider,
         'field': 'required_source_capabilities', 'value': ['experiment_survey_sensor']},
        {'kind': 'survey_provider', 'id': added_provider,
         'field': 'capacity_units_per_source_per_day', 'value': 2.0},
    ]
    def factory(changes):
        return build_game_application_for_scenario(
            build_standard_scenario_definition(),
            definition_transform=lambda runtime, catalog: apply_content_variant(runtime, catalog, changes),
        )
    modified = factory(edits)
    assert not build_definition_dependency_graph(modified._simulation, modified._catalog).diagnostics
    assert modified._simulation.survey.compatible_source_definition_ids(
        modified._simulation.survey.providers[DefinitionId(added_provider)]
    )
    # The copied Fleet is a real physical asset in an independent Scenario.
    # Application candidates, exclusive commitment, Save/Load and progression
    # all use the ordinary Survey and Transport Domains.
    from datetime import datetime, timezone
    from space_idle.application_commands import GetSurveys, SetSurveyProviderFleetQuantity, AdvanceTime
    from space_idle.bootstrap import build_game_application_for_load
    from space_idle.persistence import save_game, load_game
    node_id = ids.LUNAR_ORBIT
    variant_scenario = scenario_variant(build_standard_scenario_definition(), {
        'fleet': [{'operational_node_id': str(node_id),
                   'vehicle_definition_id': added_vehicle, 'units': 1}],
    })
    variant = build_game_application_for_scenario(
        variant_scenario,
        definition_transform=lambda runtime, catalog: apply_content_variant(runtime, catalog, edits),
    )
    def candidate(app):
        return next(row for row in app.query(GetSurveys(str(node_id))).provider_fleet
                    if row.provider_definition_id == added_provider
                    and row.vehicle_definition_id == added_vehicle)
    assert candidate(variant).free_units == 1 and candidate(variant).can_set_quantity
    assignment = variant.execute(SetSurveyProviderFleetQuantity(
        added_provider, str(node_id), added_vehicle, 1,
    )).created_id
    assert assignment is not None
    assert candidate(variant).committed_units == 1
    assert variant._simulation.transport.fleet_free_units(DefinitionId(added_vehicle), node_id) == 0
    path = tmp_path / 'independent-content-survey.json'
    save_game(variant, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, lambda: build_game_application_for_load(
        scenario=variant_scenario,
        definition_transform=lambda runtime, catalog: apply_content_variant(runtime, catalog, edits),
    ))
    assert capture_state(loaded._simulation) == capture_state(variant._simulation)
    variant.execute(AdvanceTime(1))
    loaded.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(variant._simulation)
    assert candidate(loaded).committed_units == 1
    with pytest.raises(ValueError):
        factory(edits[2:])  # No compatible physical source for the new provider.


def test_canonical_experiment_compares_actual_process_flow_and_scoped_unmet_without_stock_inference():
    """Independent Content changes alter actual settlement, not chart predictions."""
    from space_idle.content.base_ids import PROCESS_FOOD_PRODUCTION, FOOD, EARTH

    base = build_game_application()
    process = base._simulation.industry.processes[PROCESS_FOOD_PRODUCTION]
    output = process.outputs_per_day[FOOD]

    def with_output(sim, catalog):
        apply_content_variant(sim, catalog, ({
            "kind": "process", "id": str(PROCESS_FOOD_PRODUCTION),
            "field": "outputs_per_day", "resource_id": str(FOOD),
            "value": output * 0.6,
        },))

    cases = (
        ExperimentCase("original", build_game_application, _idle),
        ExperimentCase("lower-output", lambda: build_game_application_for_scenario(
            build_standard_scenario_definition(), definition_transform=with_output,
        ), _idle),
    )
    runs = run_experiments(cases, days=2, operational_node_ids=frozenset((EARTH,)))
    report = compare_experiments(runs)["comparisons"][0]
    assert report["same_observation_scope"] and not report["same_content_definitions"]
    production = [row for row in report["settlement_differences"]
                  if row["resource_id"] == str(FOOD)
                  and row["source_owner"].startswith("process:")
                  and row["destination_owner"] == f"inventory:{EARTH}"
                  and row["layer"] == "activity"]
    assert production and sum(row["difference_t"] for row in production) < 0
    assert all(row["baseline_settled_t"] > row["variant_settled_t"] for row in production)
    assert all(row["time_basis"] == "cumulative_canonical_days"
               and not row["unit"].endswith("/day")
               for row in report["allocation_differences"])
    assert all(abs(row["unattributed_delta_t"]) <= 1e-7
               for run in runs for row in run.flow_reconciliation)
    # Independent canonical games are reproducible, not mutated running States.
    assert [run.to_json_data() for run in runs] == [
        run.to_json_data() for run in run_experiments(cases, days=2,
            operational_node_ids=frozenset((EARTH,)))
    ]


def test_independent_exploration_founding_and_market_variants_use_existing_domain_lifecycles(tmp_path):
    """New Content identities require real Scenario ownership and real Commands."""
    from space_idle.application_commands import (
        GetScientificExplorations, GetMarket, GetSurfaceMap,
        StartScientificExploration, CreateTradeOrder,
    )
    from space_idle.content.base_market import EARTH_MARKET_PROVIDER
    from space_idle.bootstrap import build_game_application_for_load
    from space_idle.persistence import load_game, save_game

    new_science = 'experiment.science.orbital'
    new_founding = 'experiment.founding.surface'
    new_provider = 'experiment.market.provider'
    new_interface = 'experiment.market.interface'
    changes = tuple({"operation": "add", "kind": kind,
                     "source_id": str(source), "id": target}
                    for kind, source, target in (
                        ('scientific_exploration', ids.CISLUNAR_SCIENCE_EXPLORATION, new_science),
                        ('founding', ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE, new_founding),
                        ('market_provider', EARTH_MARKET_PROVIDER, new_provider),
                    )) + (
                        {"kind": "scientific_exploration", "id": new_science,
                         "field": "duration_days", "value": 6.0},
                        {"kind": "founding", "id": new_founding,
                         "field": "preparation_work", "value": 4.0},
                        {"kind": "market_provider", "id": new_provider,
                         "field": "lead_time_days", "value": 4},
                    )
    scenario = scenario_variant(build_standard_scenario_definition(), {
        'market_provider_ids': [new_provider],
        'market_interfaces': [{
            'id': new_interface, 'provider_id': new_provider,
            'operational_node_id': str(ids.EARTH), 'enabled': True,
        }],
    })

    def factory():
        return build_game_application_for_scenario(
            scenario, definition_transform=lambda sim, catalog: apply_content_variant(sim, catalog, changes),
        )

    app = factory()
    assert app._simulation.scientific_exploration.definitions[DefinitionId(new_science)].duration_days == 6.0
    assert app._simulation.founding.deployment_recipes[DefinitionId(new_founding)].preparation_work == 4.0
    assert app._simulation.market.provider_defs[DefinitionId(new_provider)].lead_time_days == 4
    assert any(row.id == new_science for row in app.query(GetScientificExplorations()).items)
    assert any(row.id == new_interface and row.provider_id == new_provider
               for row in app.query(GetMarket()).interfaces)
    cell = next(row for row in app.query(GetSurfaceMap(
        str(ids.MOON), (str(ids.MOON_CELL_FARSIDE_HIGHLANDS),)
    )).cells if row.id == str(ids.MOON_CELL_FARSIDE_HIGHLANDS))
    assert any(row.deployment_recipe_id == new_founding for row in cell.foundation_options)
    assert all(row.deployment_recipe_id != new_founding
               for cell in build_game_application().query(GetSurfaceMap(
                   str(ids.MOON), (str(ids.MOON_CELL_FARSIDE_HIGHLANDS),)
               )).cells for row in cell.foundation_options)

    def player(_app, day):
        if day != 0:
            return ()
        return (StartScientificExploration(new_science),
                CreateTradeOrder('buy', str(ids.MACHINERY), new_interface,
                                 quantity_target_t=1.0))

    fast_changes = changes + (
        {"kind": "market_provider", "id": new_provider,
         "field": "lead_time_days", "value": 1},
        {"kind": "scientific_exploration", "id": new_science,
         "field": "duration_days", "value": 4.0},
    )
    def fast_factory():
        return build_game_application_for_scenario(
            scenario, definition_transform=lambda sim, catalog: apply_content_variant(
                sim, catalog, fast_changes),
        )

    cases = (ExperimentCase('base', build_game_application, player),
             ExperimentCase('added', factory, player),
             ExperimentCase('shorter-delay', fast_factory, player))
    runs = run_experiments(cases, days=6)
    assert len(runs[0].rejected_commands) == 2
    assert not runs[1].rejected_commands
    assert runs[1].to_json_data() == run_experiments((cases[1],), days=6)[0].to_json_data()
    assert runs[1].content_definitions_sha256 != runs[0].content_definitions_sha256
    assert runs[1].initial_state_sha256 != runs[0].initial_state_sha256
    assert runs[1].initial_state_sha256 == runs[2].initial_state_sha256
    assert runs[1].content_definitions_sha256 != runs[2].content_definitions_sha256
    comparison = compare_experiments(runs[1:])['comparisons'][0]
    assert comparison['same_initial_state'] and not comparison['same_content_definitions']
    def first_market_delivery(run):
        return min(row.day for trace in run.canonical_traces
                   for row in trace.activity_flows()
                   if row.activity_id.startswith(('market:', 'market_'))
                   and row.destination_owner.startswith('inventory:'))
    assert first_market_delivery(runs[2]) < first_market_delivery(runs[1])
    assert any(row.activity_id.startswith('market:') or row.activity_id.startswith('market_')
               for trace in runs[1].canonical_traces for row in trace.activity_flows())

    app.execute(StartScientificExploration(new_science))
    app.execute(CreateTradeOrder('buy', str(ids.MACHINERY), new_interface,
                                 quantity_target_t=1.0))
    app.execute(AdvanceTime(1))
    path = tmp_path / 'independent-market-science.json'
    save_game(app, path)
    loaded, _ = load_game(path, lambda: build_game_application_for_load(
        scenario=scenario, definition_transform=lambda sim, catalog: apply_content_variant(sim, catalog, changes)
    ))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)
    loaded.execute(AdvanceTime(1))
    app.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)

    # A newly authored Founding method must also participate in the physical
    # lifecycle, not merely appear in a candidate list. Endow a separate
    # Scenario through the normal inventory/Fleet owners, never through a
    # test-only resource injection after simulation initialization.
    from space_idle.application_commands import (
        PlanOperationalNodeFounding, SurfaceLocationFoundingTarget, GetProjects,
    )
    recipe = app._simulation.founding.deployment_recipes[DefinitionId(new_founding)]
    founding_stocks = [
        {'operational_node_id': str(ids.LUNAR_ORBIT),
         'resource_id': str(requirement.resource_id),
         'amount_t': requirement.amount_t + 5}
        for requirement in recipe.payload_resources
    ]
    founding_stocks.append({'operational_node_id': str(ids.LUNAR_ORBIT),
                            'resource_id': str(ids.PROPELLANT), 'amount_t': 30.0})
    founding_scenario = scenario_variant(scenario, {
        'inventory_stock': founding_stocks,
        'fleet': [{'operational_node_id': str(ids.LUNAR_ORBIT),
                   'vehicle_definition_id': str(ids.REUSABLE_SURFACE_CARGO_LANDER),
                   'units': 1}],
    })
    def founding_factory():
        return build_game_application_for_scenario(
            founding_scenario,
            definition_transform=lambda sim, catalog: apply_content_variant(sim, catalog, changes),
        )
    founded = founding_factory()
    founding_command = PlanOperationalNodeFounding(
        str(ids.LUNAR_ORBIT), 'Independent lunar site',
        SurfaceLocationFoundingTarget('surface_location', str(ids.MOON),
                                     str(ids.MOON_CELL_FARSIDE_HIGHLANDS)),
        new_founding, str(ids.REUSABLE_SURFACE_CARGO_LANDER),
    )
    founding_result = founded.execute(founding_command)
    assert founding_result.created_id
    founded.execute(AdvanceTime(1))
    assert any(row.id == founding_result.created_id
               for row in founded.query(GetProjects(str(ids.LUNAR_ORBIT))).items)
    founding_path = tmp_path / 'independent-founding.json'
    save_game(founded, founding_path)
    founded_loaded, _ = load_game(founding_path, lambda: build_game_application_for_load(
        scenario=founding_scenario,
        definition_transform=lambda sim, catalog: apply_content_variant(sim, catalog, changes),
    ))
    assert capture_state(founded_loaded._simulation) == capture_state(founded._simulation)
    founded.execute(AdvanceTime(1))
    founded_loaded.execute(AdvanceTime(1))
    assert capture_state(founded_loaded._simulation) == capture_state(founded._simulation)

    # Definitions cannot be deleted while Scenario states still refer to them.
    with pytest.raises((ValueError, KeyError)):
        build_game_application_for_scenario(
            scenario, definition_transform=lambda sim, catalog: apply_content_variant(
                sim, catalog, changes + ({'operation': 'remove', 'kind': 'market_provider', 'id': new_provider},)
            ),
        )

    # Changing real Provider or Construction capacity is a Content variant,
    # even when it does not alter static Graph edges or the initial State.
    research_provider = next(iter(app._simulation.research.providers.values()))
    changed_capacity = ({'kind': 'research_provider', 'id': str(research_provider.id),
                         'field': 'crew_person_days_per_research_point', 'value': 1.5},)
    provider_case = ExperimentCase('provider-change', lambda: build_game_application_for_scenario(
        scenario, definition_transform=lambda sim, catalog: apply_content_variant(
            sim, catalog, changes + changed_capacity)), _idle)
    same_initial = run_experiments((ExperimentCase('unchanged', factory, _idle), provider_case), days=0)
    assert same_initial[0].content_definitions_sha256 != same_initial[1].content_definitions_sha256
    assert same_initial[0].initial_state_sha256 == same_initial[1].initial_state_sha256
    assert same_initial[0].definition_graph_sha256 == same_initial[1].definition_graph_sha256

    # Survey fleet and externally acquired Population remain finite and owned
    # by their normal Domains when alternative Definitions are introduced.
    new_survey = 'experiment.provider.survey'
    survey_changes = changes + ({'operation': 'add', 'kind': 'survey_provider',
                                 'id': new_survey,
                                 'source_id': str(ids.LUNAR_FLEET_SURVEY_PROVIDER)},)
    multi_owner_scenario = scenario_variant(scenario, {
        'fleet': [{'operational_node_id': str(ids.LUNAR_ORBIT),
                   'vehicle_definition_id': str(ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT), 'units': 2}],
        'survey_fleet_assignments': [{
            'provider_definition_id': new_survey,
            'operational_node_id': str(ids.LUNAR_ORBIT),
            'vehicle_definition_id': str(ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT), 'units': 1,
        }],
        'external_population_sources': [{
            'id': 'experiment.population.earth',
            'operational_node_id': str(ids.EARTH), 'initial_people': 12,
            'max_acquisition_per_day': 4,
        }],
    })
    def owner_factory():
        return build_game_application_for_scenario(
            multi_owner_scenario,
            definition_transform=lambda sim, catalog: apply_content_variant(sim, catalog, survey_changes))

    multi_owner = owner_factory()
    assert multi_owner._simulation.population.external_remaining['experiment.population.earth'] == 12
    assert sum(assignment.units for assignment in multi_owner_scenario.survey_fleet_assignments
               if assignment.operational_node_id == ids.LUNAR_ORBIT) == 2
    survey_assigned = multi_owner._simulation.survey.provider_assignments
    assert len(survey_assigned) >= 2
    owner_before = capture_state(multi_owner._simulation)
    multi_owner.execute(AdvanceTime(1))
    owner_save = tmp_path / 'independent-survey-population.json'
    save_game(multi_owner, owner_save)
    owner_loaded, _ = load_game(owner_save, lambda: build_game_application_for_load(
        scenario=multi_owner_scenario,
        definition_transform=lambda sim, catalog: apply_content_variant(sim, catalog, survey_changes),
    ))
    assert capture_state(owner_loaded._simulation) == capture_state(multi_owner._simulation)
    assert capture_state(multi_owner._simulation) != owner_before

    # Same Domain registrations handle spatial development and construction
    # capacity additions, with reference validation on their removal.
    spatial_original = next(iter(app._simulation.projects.spatial_recipes))
    spatial_copy = 'experiment.spatial.development'
    spatial_changes = changes + (
        {'operation': 'add', 'kind': 'spatial_development',
         'source_id': str(spatial_original), 'id': spatial_copy},
    )
    spatial_app = build_game_application_for_scenario(scenario, definition_transform=(
        lambda sim, catalog: apply_content_variant(sim, catalog, spatial_changes)))
    assert DefinitionId(spatial_copy) in spatial_app._simulation.projects.spatial_recipes
    assert spatial_app._simulation.projects.spatial_recipes[DefinitionId(spatial_copy)].id == DefinitionId(spatial_copy)


def test_movement_rule_content_variants_reuse_canonical_app_and_physical_targets():
    """Independent transport Content changes preserve one Movement model.

    Additional authored profile IDs must not collide or create an alternate
    arrival/return solver; removing a profile removes its routes in that case.
    """
    from space_idle.application_commands import GetMovementPlans

    original = build_game_application()
    origin = ids.LEO
    target = ids.MARS_CELL_EQUATORIAL_PLAIN
    source = next(rule for rule in original._simulation.transport.surface_access_movement_rules
                  if str(rule.body_id) == "base.body.mars")
    original_plans = original._simulation.transport.movement_plans_to_physical_target(origin, target)
    assert len(original_plans) == 1

    variant_changes = (
        {"operation": "add", "kind": "surface_access_movement_rule",
         "source_id": str(source.id), "id": "test.movement.alt_mars_access"},
        {"kind": "surface_access_movement_rule", "id": "test.movement.alt_mars_access",
         "field": "transit_days", "value": source.transit_days + 5},
        {"operation": "add", "kind": "spaceflight_movement_rule",
         "source_id": "base.movement.spaceflight", "id": "test.movement.alt_spaceflight"},
    )

    def factory(changes):
        return build_game_application_for_scenario(
            build_standard_scenario_definition(),
            definition_transform=lambda sim, catalog: apply_content_variant(sim, catalog, changes),
        )

    changed = factory(variant_changes)
    changed_plans = changed._simulation.transport.movement_plans_to_physical_target(origin, target)
    # Two surface-access profiles x two spaceflight profiles; physical target
    # remains distinct from an owned operational Node.
    assert len(changed_plans) == 4
    assert len({plan.id for plan in changed_plans}) == 4
    assert target not in changed._simulation.graph.operational_node_ids()
    assert all(plan.relation.movement_context == "interplanetary_transfer_surface_access"
               for plan in changed_plans)
    assert original._simulation.transport.movement_plans_to_physical_target(origin, target) == original_plans
    assert changed.query(GetMovementPlans(origin_id=str(origin), include_modes=False)).items

    # A separate case can legitimately remove the route. The World/Resource
    # owner stays intact and no invented fallback movement is added.
    removed = factory(({"operation": "remove", "kind": "surface_access_movement_rule",
                        "id": str(source.id)},))
    assert not removed._simulation.transport.movement_plans_to_physical_target(origin, target)
    assert target in removed._simulation.graph.surface_cells
    with pytest.raises(ValueError, match="duplicate .* Definition"):
        factory(({"operation": "add", "kind": "surface_access_movement_rule",
                  "id": str(source.id), "source_id": str(source.id)},))
    with pytest.raises(ValueError, match="unknown .* Definition"):
        factory(({"operation": "remove", "kind": "surface_access_movement_rule",
                  "id": "test.no_such_rule"},))

    runs = run_experiments((
        ExperimentCase("original", build_game_application, _idle),
        ExperimentCase("alternative", lambda: factory(variant_changes), _idle),
    ), days=1)
    comparison = compare_experiments(runs)["comparisons"][0]
    assert not comparison["same_content_definitions"]
    assert comparison["same_initial_state"]
    assert [row.to_json_data() for row in run_experiments((
        ExperimentCase("alternative", lambda: factory(variant_changes), _idle),
    ), days=1)[0].observations] == [row.to_json_data() for row in runs[1].observations]

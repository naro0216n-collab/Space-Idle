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
from space_idle.analysis_graph import DependencyNode
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

    app = build_game_application()
    before = capture_state(app._simulation)
    world = app.query(GetWorld())
    selected = world.operational_nodes[0].id
    scope = frozenset((SpatialNodeId(selected),))
    founding_target = next((body.id, context.spatial_node_id)
                          for body in app.query(GetCatalog()).celestial_bodies
                          for context in app.query(GetNonSurfaceFoundingOptions(body.id)).contexts
                          if not context.operational)
    transport_pair = (world.operational_nodes[0].id, world.operational_nodes[1].id)
    # Any registered physical Surface Cell is a valid projection scope. This
    # does not require a named Earth cell or a particular new-game geography.
    sample_cell = next(iter(app._simulation.graph.surface_cells.values()))
    surface_cell = (str(sample_cell.body_id), str(sample_cell.id))
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
                                    "--node", selected, "--founding-target",
                                    ":".join(founding_target), "--surface-cell",
                                    ":".join(surface_cell), "--transport-pair",
                                    ":".join(transport_pair)])
        export_graph()
    exported = json.loads(capsys.readouterr().out)
    assert exported["current_eligibility"] == observed
    assert exported["state_observation"]
    assert exported["definition_graph"]
    assert exported["current_eligibility"]["layer"] != exported["state_observation"].get("layer")
    assert capture_state(app._simulation) == before


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
    # The trace must account for actual Owner settlements, but a particular
    # composition need not run all of Industry, Extraction, Maintenance and
    # Life Support on the selected day.
    assert flows
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
    # Experiment cases may vary a validated Scenario as well as its initial State.
    distinct = replace(base, id="test.scenario.resource_perturbation", inventory_stock=(
        replace(original, amount_t=original.amount_t + 10.0), *base.inventory_stock[1:],
    ))
    cases = (
        ExperimentCase("base", lambda: build_game_application_for_scenario(base), _idle),
        ExperimentCase("variant", lambda: build_game_application_for_scenario(distinct), _idle),
    )
    comparison = compare_experiments(run_experiments(cases, days=1))["comparisons"][0]
    assert not comparison["same_initial_state"]
    assert not comparison["same_scenario"]
    delta = next(row for row in comparison["metric_differences"]
                 if row["kind"] == "inventory_stock"
                 and row["subject_id"] == str(original.resource_id)
                 and row["context_id"] == str(original.operational_node_id))
    assert delta["variant_initial"] - delta["baseline_initial"] == 10.0
    assert delta["final_difference"] is not None
    assert build_standard_scenario_definition() == base

    with pytest.raises(ValueError, match='unknown Scenario variant'):
        scenario_variant(base, {'impossible_initial_state': []})
    with pytest.raises(ValueError, match='unsupported typed Content'):
        edit_that_does_not_exist = ({'kind': 'planet', 'id': 'X', 'field': 'gravity', 'value': 9},)
        apply_content_variant(modified._simulation, modified._catalog, edit_that_does_not_exist)


def test_canonical_experiments_replay_player_commands_and_preserve_absent_metrics():
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

    # The optional quantitative comparator must not silently treat missing
    # measurements as zero, including its multi-objective output.
    objective = ParetoObjective("inventory_stock", "new-resource", "another-node", "t", "inventory.stock", "maximize")
    pareto = compare_pareto((base, expanded), (objective,))
    assert len(pareto["cases"]) == 2
    missing_objective = replace(objective, subject_id="unobserved-resource")
    assert all(not case["comparable"] and case["values"] is None
               for case in compare_pareto((base, expanded), (missing_objective,))["cases"])


def test_experiment_input_requires_explicit_time_and_real_command_types():

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






def test_typed_content_add_remove_recompose_application_and_preserve_accounting():
    """New research/method/resource and deletion share Composition and UI contracts.

    Experiment cases recompose Definitions before Scenario instead of modifying
    a running game or inventing a second supply / tech eligibility evaluator.
    """
    from space_idle.application_commands import (GetCatalog, GetOperationalNode,
        GetResearch, SetFacilityProcess, AdvanceTime, ApplicationError)
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
    first = enabled._simulation.inventory.amount(ids.EARTH, DefinitionId(resource_id))
    enabled.execute(AdvanceTime(1))
    last = enabled._simulation.inventory.amount(ids.EARTH, DefinitionId(resource_id))
    assert last < first
    assert enabled._simulation.facilities.facilities[EntityId(chosen.facility_id)].selected_process_id == DefinitionId(process_id)
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
    assert runs[0].content_definitions_sha256 != runs[1].content_definitions_sha256
    assert runs[1].content_definitions_sha256 == runs[2].content_definitions_sha256
    assert runs[1].initial_state_sha256 != runs[2].initial_state_sha256
    assert runs[0].definition_graph_sha256 != runs[1].definition_graph_sha256
    assert len(runs[1].rejected_commands) == 1
    assert not runs[2].rejected_commands
    assert all(abs(row["unattributed_delta_t"]) < 1e-7
               for run in runs for row in run.flow_reconciliation)

    # Removing a method changes the actual candidates/Definition Graph; nothing
    # rewrites the Scenario or dependent Technology requirements to conceal it.
    removed_method = changes + ({"operation": "remove", "kind": "process", "id": process_id},)
    no_method = factory(scenario, removed_method)
    assert all(row.id != process_id for row in no_method.query(GetCatalog()).processes)
    assert all(option.process_id != process_id
               for row in no_method.query(GetOperationalNode(str(ids.EARTH))).industry
               for option in row.process_options)

    # All typed Content families must still pass through the real Composition
    # boundary. Unattached definitions are legitimate future Content, not a
    # reason to fabricate a physical supplier or an executable activity.
    survey_source = next(provider for provider in app._simulation.survey.providers.values()
                         if provider.source_kind.value == "fleet")
    extraction_id = "experiment.extraction.future"
    survey_id = "experiment.survey.future"
    additional = changes + (
        {"operation": "add", "kind": "extraction", "id": extraction_id,
         "source_id": str(ids.EXTRACTION_CRUST_ORE)},
        {"kind": "extraction", "id": extraction_id, "field": "required_capabilities",
         "value": ["research_lab", "metal_ore_extraction"]},
        {"operation": "add", "kind": "survey_provider", "id": survey_id,
         "source_id": str(survey_source.id)},
        {"kind": "survey_provider", "id": survey_id, "field": "required_source_capabilities",
         "value": ["robotic_prospecting_sensor", "radar_sounder"]},
    )
    extended = factory(scenario, additional)
    extended_graph = build_definition_dependency_graph(extended._simulation, extended._catalog)
    assert DependencyNode("extraction_method", extraction_id) in extended_graph.nodes
    assert DependencyNode("survey_provider", survey_id) in extended_graph.nodes
    assert not extended._simulation.survey.compatible_source_definition_ids(
        extended._simulation.survey.provider(DefinitionId(survey_id))
    )
    assert all(DefinitionId(extraction_id) not in {
        method.id for method in extended._simulation.extraction.compatible_methods(facility_id)
    } for facility_id in extended._simulation.facilities.definitions)

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
        {'operation': 'add', 'kind': 'asset_bundle', 'asset_kind': 'facility',
         'source_id': str(source_facility), 'id': new_facility},
        {'operation': 'add', 'kind': 'asset_bundle', 'asset_kind': 'vehicle',
         'source_id': str(source_vehicle.id), 'id': new_vehicle},
        {'operation': 'add', 'kind': 'research_provider',
         'source_id': str(source_provider.id), 'id': new_provider},
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
    reordered = factory(list(reversed(additions)))
    assert build_definition_dependency_graph(reordered._simulation, reordered._catalog).to_json_data() == graph.to_json_data()

    # Incomplete assets cannot bypass the ordinary installation path. Missing
    # provider references are rejected by Composition validation.
    with pytest.raises(ValueError, match='complete asset bundle'):
        build_game_application_for_scenario(
            build_standard_scenario_definition(),
            definition_transform=lambda runtime, catalog: apply_content_variant(
                runtime, catalog, additions + edits + [
                    {'operation': 'add', 'kind': 'facility', 'source_id': str(source_facility),
                     'id': 'experiment.invalid.partial'},
                ]),
        )
    with pytest.raises(ValueError):
        build_game_application_for_scenario(
            build_standard_scenario_definition(),
            definition_transform=lambda runtime, catalog: apply_content_variant(
                runtime, catalog, [additions[-1]]),
        )


def test_canonical_experiment_compares_actual_process_flow_and_scoped_unmet_without_stock_inference():
    """Independent Content changes alter actual settlement, not chart predictions."""
    from space_idle import GetOperationalNode, GetWorld

    base = build_game_application()
    # Select an operating Process from the authoritative decision projection,
    # not a specific authored food-production ID or output Resource.
    operating = next(
        (node.id, industry.process_id, resource_id, output)
        for node in base.query(GetWorld()).operational_nodes
        for industry in base.query(GetOperationalNode(node.id)).industry
        if industry.scale > 0 and industry.process_id is not None
        for resource_id, output in base._simulation.industry.processes[
            DefinitionId(industry.process_id)].outputs_per_day.items()
        if output > 0
    )
    node_id, process_id, resource_id, output = operating

    def with_output(sim, catalog):
        apply_content_variant(sim, catalog, ({
            "kind": "process", "id": str(process_id),
            "field": "outputs_per_day", "resource_id": str(resource_id),
            "value": output * 0.6,
        },))

    cases = (
        ExperimentCase("original", build_game_application, _idle),
        ExperimentCase("lower-output", lambda: build_game_application_for_scenario(
            build_standard_scenario_definition(), definition_transform=with_output,
        ), _idle),
    )
    runs = run_experiments(cases, days=2, operational_node_ids=frozenset((node_id,)))
    report = compare_experiments(runs)["comparisons"][0]
    assert report["same_observation_scope"] and not report["same_content_definitions"]
    production = [row for row in report["settlement_differences"]
                  if row["resource_id"] == str(resource_id)
                  and row["source_owner"].startswith("process:")
                  and row["destination_owner"] == f"inventory:{node_id}"
                  and row["layer"] == "activity"]
    assert production and sum(row["difference_t"] for row in production) < 0
    assert all(row["baseline_settled_t"] > row["variant_settled_t"] for row in production)
    assert all(row["time_basis"] == "cumulative_canonical_days"
               and not row["unit"].endswith("/day")
               for row in report["allocation_differences"])
    assert all(abs(row["unattributed_delta_t"]) <= 1e-7
               for run in runs for row in run.flow_reconciliation)

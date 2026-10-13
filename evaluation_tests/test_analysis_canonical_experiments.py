"""Cross-domain invariants of optional canonical observation and analysis.

Uses the real Application command boundary and Owner Domains, not a second
supply/eligibility implementation or a frozen preferred gameplay sequence.
"""
from __future__ import annotations

import pytest

from scripts.analysis_experiments import (
    ExperimentCase, ParetoObjective, compare_experiments, compare_pareto, run_experiments,
)
from scripts.compare_experiments import parse_cases
from space_idle import build_game_application
from space_idle.bootstrap import build_game_application_for_scenario
from space_idle.content.base_scenario import build_standard_scenario_definition
from scripts.analysis_variants import apply_content_variant
from space_idle.application_commands import AdvanceTime
from space_idle.shared import DefinitionId


def _idle(_app, _day):
    return ()


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

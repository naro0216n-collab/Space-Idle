"""Opt-in reproducible canonical-day experiments, not a second simulation.

Each case supplies a freshly composed/validated GameApplication and an explicit
Player policy. Commands are executed through Application; only domain-owned
State is observed. Stock changes are *net deltas*, never gross resource flows.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
from collections.abc import Mapping
import json

from space_idle.analysis_observation import StateMetric, StateObservation, observe_state
from space_idle.analysis_execution import CanonicalDayTrace, observe_canonical_day
from space_idle.application import GameApplication
from space_idle.application_commands import AdvanceTime, ApplicationError, Command
from space_idle.composition.analysis_graph import build_definition_dependency_graph
from space_idle.persistence import capture_state
from space_idle.shared import DefinitionId, SpatialNodeId
from space_idle.validation import (
    validate_catalog_coverage, validate_runtime_state, validate_simulation_configuration,
)


PlayerPolicy = Callable[[GameApplication, int], Sequence[Command]]


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _command_data(value: object) -> object:
    """JSON-stable Player intent payload (not Python object identity/repr)."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _command_data(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _command_data(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_command_data(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_command_data(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported Player Command value for experiment serialization: {type(value).__name__}")


@dataclass(frozen=True)
class ExperimentCase:
    name: str
    application_factory: Callable[[], GameApplication]
    policy: PlayerPolicy

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("experiment case requires a name")


@dataclass(frozen=True)
class RejectedExperimentCommand:
    day: int
    command: str
    code: str
    detail: str


@dataclass(frozen=True)
class ExperimentRun:
    name: str
    content_id: str
    world_definition_id: str
    scenario_id: str
    definition_graph_sha256: str
    initial_state_sha256: str
    content_definitions_sha256: str
    observations: tuple[StateObservation, ...]
    rejected_commands: tuple[RejectedExperimentCommand, ...]
    attempted_commands: tuple[dict, ...]
    canonical_traces: tuple[CanonicalDayTrace, ...]
    flow_reconciliation: tuple[dict, ...]
    decision_observations: tuple[dict, ...] = ()

    def to_json_data(self) -> dict:
        result = {
            "name": self.name, "content_id": self.content_id,
            "world_definition_id": self.world_definition_id,
            "scenario_id": self.scenario_id,
            # A graph digest identifies the extracted relation model, NOT all
            # authored Content (e.g. environment and movement parameters).
            "definition_graph_sha256": self.definition_graph_sha256,
            "initial_state_sha256": self.initial_state_sha256,
            "content_definitions_sha256": self.content_definitions_sha256,
            "observation_scope": self.observations[0].to_json_data()["scope"],
            "canonical_traces": [trace.to_json_data() for trace in self.canonical_traces],
            "flow_reconciliation": list(self.flow_reconciliation),
            "observations": [row.to_json_data() for row in self.observations],
            "attempted_commands": list(self.attempted_commands),
            "rejected_commands": [vars(row) for row in self.rejected_commands],
        }
        if self.decision_observations:
            result["decision_observations"] = list(self.decision_observations)
        return result


def _content_definitions_sha(app: GameApplication, graph_data: dict) -> str:
    """Fingerprint authored definition values, not only their relation edges.

    World facets use typed keys; physical overlays and active Operational Nodes
    are state and must not be mistaken for authored World values.
    """
    sim = app._simulation
    world = sim.graph
    static = sim.environment.static
    facets = [
        [str(context_id), field_type.__name__, _command_data(value)]
        for mapping in (static.body_facets, static.facets)
        for (context_id, field_type), value in mapping.items()
    ]
    snapshot = {
        "content_id": app.content_id,
        "world_definition_id": app.world_definition_id,
        "graph": graph_data,
        "catalog": app._catalog,
        "world": {
            "star_systems": world.star_systems,
            "bodies": world.bodies,
            "spatial_nodes": world.nodes,
            "surface_cells": world.surface_cells,
            "static_environment": sorted(facets, key=lambda row: (row[0], row[1])),
        },
        "facilities": sim.facilities.definitions,
        "processes": sim.industry.processes,
        "power": sim.power.specs,
        "storage": sim.storage.providers,
        "vehicles": {row.id: row for row in sim.transport.vehicle_definitions()},
        "movement": (sim.transport.surface_movement_rules,
                     sim.transport.surface_access_movement_rules,
                     sim.transport.spaceflight_movement_rules),
        "extraction": {} if sim.extraction is None else sim.extraction.specs,
        "survey_providers": {} if sim.survey is None else sim.survey.providers,
        "research": {} if sim.research is None else sim.research.definitions,
        "research_providers": {} if sim.research is None else sim.research.providers,
        "construction_providers": sim.projects.construction_providers,
        "construction_resource_providers": sim.projects.construction_resource_providers,
        "construction": sim.projects.recipes,
        "construction_upgrade": sim.projects.upgrade_recipes,
        "construction_decommission": sim.projects.decommission_recipes,
        "surface_development": sim.projects.spatial_recipes,
        "founding": {} if sim.founding is None else sim.founding.deployment_recipes,
        "population_rules": None if sim.population is None else sim.population.rules,
        "population_external_sources": ({} if sim.population is None
                                        else sim.population.external_definitions),
        "scientific_exploration": ({} if sim.scientific_exploration is None
                                   else sim.scientific_exploration.definitions),
        "market": sim.market.provider_defs,
    }
    return _digest(_command_data(snapshot))


def _stocks(sim, nodes, resources) -> dict[tuple[str, str], float]:
    return {(str(node), str(resource)): amount
            for (node, resource), amount in sim.inventory.stock.items()
            if (nodes is None or node in nodes) and (resources is None or resource in resources)}


def run_experiments(
    cases: Sequence[ExperimentCase], *, days: int,
    operational_node_ids: frozenset[SpatialNodeId] | None = None,
    resource_ids: frozenset[DefinitionId] | None = None,
    observe_decisions: bool = False,
    founding_targets: tuple[tuple[str, str], ...] = (),
    surface_cells: tuple[tuple[str, str], ...] = (),
    transport_pairs: tuple[tuple[str, str], ...] = (),
) -> tuple[ExperimentRun, ...]:
    """Run independent cases with real Commands and canonical one-day steps.

    Day offset 0 policy is applied to the day-0 State; policy is called once
    per game day through offset ``days - 1``. Rejected Commands are recorded
    and subsequent scheduled Commands are still attempted. No command is
    silently retried or replaced with an alternative strategy.
    """
    if days < 0:
        raise ValueError("experiment days must be nonnegative")
    if len({case.name for case in cases}) != len(cases):
        raise ValueError("experiment case names must be unique")
    runs: list[ExperimentRun] = []
    for case in cases:
        app = case.application_factory()
        sim = app._simulation
        validate_simulation_configuration(sim)
        validate_catalog_coverage(sim, app._catalog)
        validate_runtime_state(sim)
        graph = build_definition_dependency_graph(sim, app._catalog)
        if graph.diagnostics:
            raise ValueError(f"unresolved definition references in {case.name}: {graph.diagnostics}")
        content_sha = _content_definitions_sha(app, graph.to_json_data())
        start_state_sha = _digest(capture_state(sim))
        observations = [observe_state(sim, operational_node_ids=operational_node_ids,
                                      resource_ids=resource_ids)]
        if observe_decisions:
            from scripts.analysis_decision_projection import observe_application_decisions
            def snapshot():
                return observe_application_decisions(
                    app, operational_node_ids=operational_node_ids,
                    founding_targets=founding_targets, surface_cells=surface_cells,
                    transport_pairs=transport_pairs,
                )
            decision_observations = [snapshot()]
        else:
            decision_observations = []
        failures: list[RejectedExperimentCommand] = []
        attempted: list[dict] = []
        traces: list[CanonicalDayTrace] = []
        reconciliations: list[dict] = []
        for offset in range(days):
            before = _stocks(sim, operational_node_ids, resource_ids)
            with observe_canonical_day(sim, operational_node_ids=operational_node_ids,
                                       resource_ids=resource_ids) as trace:
                for command in case.policy(app, offset):
                    if isinstance(command, AdvanceTime):
                        raise ValueError("Player policy cannot control canonical experiment time")
                    name = type(command).__name__
                    attempted.append({"day": sim.day, "type": name, "arguments": _command_data(command)})
                    try:
                        app.execute(command)
                    except ApplicationError as exc:
                        failures.append(RejectedExperimentCommand(sim.day, name, exc.code, exc.message))
                app.execute(AdvanceTime(1))
            traces.append(trace)
            reconciliations.extend({"day": trace.day, **row}
                                   for row in trace.reconcile(before, _stocks(sim, operational_node_ids, resource_ids)))
            observations.append(observe_state(sim, operational_node_ids=operational_node_ids,
                                              resource_ids=resource_ids))
            if observe_decisions:
                decision_observations.append(snapshot())
        runs.append(ExperimentRun(
            case.name, app.content_id, app.world_definition_id, app.scenario_id,
            _digest(graph.to_json_data()), start_state_sha, content_sha, tuple(observations),
            tuple(failures), tuple(attempted), tuple(traces), tuple(reconciliations),
            tuple(decision_observations),
        ))
    return tuple(runs)


MetricKey = tuple[str, str, str, str, str]


def _metrics(observation: StateObservation) -> dict[MetricKey, StateMetric]:
    return {(m.kind, m.subject_id, m.context_id, m.unit, m.provenance): m
            for m in observation.metrics}


def _settlement_totals(run: ExperimentRun) -> dict[tuple[str, str, str, str, str, str], float]:
    """Observe independent physical settlement boundaries, never graph-implied Flow.

    An Inventory admission and a later Cargo dispatch remain separate physical
    handoffs. They are not summed into fictitious production or net transferred
    tonnage. Custody is a third distinct layer, not gross production.
    """
    from collections import defaultdict

    totals = defaultdict(float)
    for trace in run.canonical_traces:
        for row in trace.activity_flows():
            key = ("activity", row.resource_id, row.source_owner,
                   row.activity_id, row.destination_owner, row.operation)
            totals[key] += row.quantity_t
        for row in trace.custody_transfers():
            key = ("custody", row.resource_id, row.source_owner,
                   "", row.destination_owner, row.operation)
            totals[key] += row.quantity_t
        for row in trace.unattributed_movements():
            inventory = f"inventory:{row.node_id}"
            source = "unknown" if row.direction == "inventory_in" else inventory
            target = inventory if row.direction == "inventory_in" else "unknown"
            key = ("unknown", row.resource_id, source, "", target, row.operation)
            totals[key] += row.quantity_t
    return dict(totals)


def _allocation_totals(run: ExperimentRun) -> dict[tuple[str, str, str, str, str], tuple[float, float, float]]:
    """Time-integrated observed demand and fulfillment, with original typed units."""
    totals = {}
    for trace in run.canonical_traces:
        for metric in trace.allocations:
            if metric.kind == "finite_constraint":
                continue  # Capacity is a stock/rate bound, not requested work.
            # The observed allocation is a rate for one canonical day. One
            # tick integrates exactly one day: t/day -> t, executions/day ->
            # executions, without creating another allocation or stock owner.
            integrated_unit = (metric.unit[:-4] if metric.unit.endswith("/day")
                               else metric.unit)
            key = (metric.kind, metric.subject_id, metric.context_id,
                   integrated_unit, metric.provenance)
            old = totals.get(key, (0.0, 0.0, 0.0))
            totals[key] = tuple(a + (0.0 if b is None else b) for a, b in zip(
                old, (metric.requested, metric.allocated, metric.unmet)
            ))
    return totals


def _compare_settlements(baseline: ExperimentRun, variant: ExperimentRun, *, comparable: bool) -> list[dict]:
    source, target = _settlement_totals(baseline), _settlement_totals(variant)
    rows = []
    for key in sorted(source.keys() | target.keys()):
        old, new = source.get(key, 0.0), target.get(key, 0.0)
        if abs(old - new) <= 1e-9:
            continue
        rows.append({
            "layer": key[0], "resource_id": key[1], "source_owner": key[2],
            "activity_id": key[3] or None, "destination_owner": key[4],
            "operation": key[5], "unit": "t",
            "baseline_settled_t": old, "variant_settled_t": new,
            "difference_t": new - old if comparable else None,
        })
    return rows


def _compare_allocations(baseline: ExperimentRun, variant: ExperimentRun, *, comparable: bool) -> list[dict]:
    source, target = _allocation_totals(baseline), _allocation_totals(variant)
    rows = []
    for key in sorted(source.keys() | target.keys()):
        old, new = source.get(key, (0.0, 0.0, 0.0)), target.get(key, (0.0, 0.0, 0.0))
        if all(abs(a - b) <= 1e-9 for a, b in zip(old, new)):
            continue
        rows.append({
            "kind": key[0], "subject_id": key[1], "context_id": key[2],
            "unit": key[3], "time_basis": "cumulative_canonical_days",
            "provenance": key[4],
            "baseline": {"requested": old[0], "allocated": old[1], "unmet": old[2]},
            "variant": {"requested": new[0], "allocated": new[1], "unmet": new[2]},
            "difference": ({"requested": new[0] - old[0], "allocated": new[1] - old[1],
                            "unmet": new[2] - old[2]} if comparable else None),
        })
    return rows


def _decision_changes(baseline: ExperimentRun, variant: ExperimentRun) -> list[dict] | None:
    """Differences between public Query results, not evaluations of strategy.

    A missing candidate remains null, never "blocked". Qualitative blocker and
    numeric preview changes both matter; choices with different Content are
    compared as differently authored identities, not equated by display name.
    """
    if not baseline.decision_observations or not variant.decision_observations:
        return None
    b, v = baseline.decision_observations, variant.decision_observations
    if len(b) != len(v) or [x["day"] for x in b] != [x["day"] for x in v]:
        raise ValueError("decision observation days differ")
    for left, right in zip(b, v):
        if any(left[field] != right[field] for field in (
            "operational_node_scope", "on_demand_founding_targets",
            "on_demand_surface_cells", "on_demand_transport_pairs",
        )):
            return None

    def rows(snapshot):
        return {(item["kind"], item["context"], item["id"]): item
                for item in snapshot["entries"]}
    old_initial, old_final, new_initial, new_final = map(rows, (b[0], b[-1], v[0], v[-1]))
    output = []
    for kind, context, identity in sorted(old_initial.keys() | old_final.keys()
                                          | new_initial.keys() | new_final.keys()):
        key = kind, context, identity
        initial_b, final_b = old_initial.get(key), old_final.get(key)
        initial_v, final_v = new_initial.get(key), new_final.get(key)
        if initial_b == initial_v and final_b == final_v:
            continue
        output.append({
            "kind": kind, "context": context, "id": identity,
            "baseline_initial": initial_b, "variant_initial": initial_v,
            "baseline_final": final_b, "variant_final": final_v,
        })
    return output


def compare_experiments(runs: Sequence[ExperimentRun]) -> dict:
    """Compare observed final stocks/capacities, without inferring gross Flow.

    Absent metrics remain null, not invented zero values. Comparisons use
    identical typed metric identity, units and provenance, and expose initial
    values so Scenario differences cannot masquerade as strategy effects.
    """
    if not runs:
        return {"baseline": None, "comparisons": []}
    baseline = runs[0]
    rows = []
    for variant in runs[1:]:
        if len(variant.observations) != len(baseline.observations):
            raise ValueError("experiment durations differ")
        if [o.day for o in variant.observations] != [o.day for o in baseline.observations]:
            raise ValueError("experiment observation days differ")
        base_initial, base_final = map(_metrics, (baseline.observations[0], baseline.observations[-1]))
        other_initial, other_final = map(_metrics, (variant.observations[0], variant.observations[-1]))
        keys = sorted(set(base_initial) | set(base_final) | set(other_initial) | set(other_final))
        differences = []
        for key in keys:
            b0, b1 = base_initial.get(key), base_final.get(key)
            v0, v1 = other_initial.get(key), other_final.get(key)
            if b0 == v0 and b1 == v1:
                continue
            differences.append({
                "kind": key[0], "subject_id": key[1], "context_id": key[2],
                "unit": key[3], "provenance": key[4],
                "baseline_initial": None if b0 is None else b0.quantity,
                "variant_initial": None if v0 is None else v0.quantity,
                "baseline_final": None if b1 is None else b1.quantity,
                "variant_final": None if v1 is None else v1.quantity,
                "final_difference": (v1.quantity - b1.quantity) if b1 is not None and v1 is not None else None,
                "baseline_net_change": (b1.quantity - b0.quantity) if b0 is not None and b1 is not None else None,
                "variant_net_change": (v1.quantity - v0.quantity) if v0 is not None and v1 is not None else None,
            })
        same_observation_scope = (
            baseline.observations[0].operational_node_ids == variant.observations[0].operational_node_ids
            and baseline.observations[0].resource_ids == variant.observations[0].resource_ids
        )
        rows.append({
            "variant": variant.name,
            "same_definition_graph": baseline.definition_graph_sha256 == variant.definition_graph_sha256,
            "same_content_definitions": baseline.content_definitions_sha256 == variant.content_definitions_sha256,
            "same_initial_state": baseline.initial_state_sha256 == variant.initial_state_sha256,
            "same_content_id": baseline.content_id == variant.content_id,
            "same_world_definition": baseline.world_definition_id == variant.world_definition_id,
            "same_scenario": baseline.scenario_id == variant.scenario_id,
            "metric_differences": differences,
            "settlement_differences": _compare_settlements(baseline, variant, comparable=same_observation_scope),
            "allocation_differences": _compare_allocations(baseline, variant, comparable=same_observation_scope),
            "same_observation_scope": same_observation_scope,
            "rejected_commands": [vars(row) for row in variant.rejected_commands],
            "decision_differences": _decision_changes(baseline, variant),
            "same_comparison_conditions": (
                baseline.content_definitions_sha256 == variant.content_definitions_sha256
                and baseline.initial_state_sha256 == variant.initial_state_sha256
                and same_observation_scope
            ),
        })
    return {"baseline": baseline.name, "comparisons": rows, "interpretation": "typed stocks, gross Owner settlements, and finite demand are distinct; dispatch and arrival are not production, comparison deltas require equal observation scopes"}


@dataclass(frozen=True)
class ParetoObjective:
    """Explicit typed final-State objective; no implicit global score."""
    kind: str
    subject_id: str
    context_id: str
    unit: str
    provenance: str
    direction: str  # maximize / minimize

    def __post_init__(self) -> None:
        if self.direction not in ("maximize", "minimize"):
            raise ValueError("Pareto direction must be maximize or minimize")


def compare_pareto(runs: Sequence[ExperimentRun], objectives: Sequence[ParetoObjective]) -> dict:
    """Missing observations are incomparable, never converted to 0.

    Dominance is reported only among experiments observing every requested
    metric with the same typed key.  Distinct Scenario/Content/initial State
    remain disclosed by experiment metadata, not mislabelled as sensitivity.
    """
    if not objectives:
        raise ValueError("Pareto analysis requires explicit objectives")
    if len(set(objectives)) != len(objectives):
        raise ValueError("duplicate Pareto objective")
    scored: dict[str, list[float] | None] = {}
    for run in runs:
        metrics = _metrics(run.observations[-1])
        values = []
        for objective in objectives:
            key = (objective.kind, objective.subject_id, objective.context_id,
                   objective.unit, objective.provenance)
            metric = metrics.get(key)
            if metric is None:
                scored[run.name] = None
                break
            values.append(metric.quantity * (1 if objective.direction == "maximize" else -1))
        else:
            scored[run.name] = values
    def dominates(a: list[float], b: list[float]) -> bool:
        return all(x >= y - 1e-9 for x, y in zip(a, b)) and any(x > y + 1e-9 for x, y in zip(a, b))
    return {
        "objectives": [vars(row) for row in objectives],
        "cases": [{"case": name,
                   "values": None if values is None else [
                       value * (1 if obj.direction == "maximize" else -1)
                       for value, obj in zip(values, objectives)],
                   "dominated_by": [] if values is None else [other_name
                       for other_name, other_values in scored.items()
                       if other_name != name and other_values is not None and dominates(other_values, values)],
                   "comparable": values is not None}
                  for name, values in scored.items()],
    }

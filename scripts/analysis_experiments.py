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
    observations: tuple[StateObservation, ...]
    rejected_commands: tuple[RejectedExperimentCommand, ...]
    attempted_commands: tuple[dict, ...]

    def to_json_data(self) -> dict:
        return {
            "name": self.name, "content_id": self.content_id,
            "world_definition_id": self.world_definition_id,
            "scenario_id": self.scenario_id,
            # A graph digest identifies the extracted relation model, NOT all
            # authored Content (e.g. environment and movement parameters).
            "definition_graph_sha256": self.definition_graph_sha256,
            "initial_state_sha256": self.initial_state_sha256,
            "observations": [row.to_json_data() for row in self.observations],
            "attempted_commands": list(self.attempted_commands),
            "rejected_commands": [vars(row) for row in self.rejected_commands],
        }


def run_experiments(
    cases: Sequence[ExperimentCase], *, days: int,
    operational_node_ids: frozenset[SpatialNodeId] | None = None,
    resource_ids: frozenset[DefinitionId] | None = None,
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
        start_state_sha = _digest(capture_state(sim))
        observations = [observe_state(sim, operational_node_ids=operational_node_ids,
                                      resource_ids=resource_ids)]
        failures: list[RejectedExperimentCommand] = []
        attempted: list[dict] = []
        for offset in range(days):
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
            observations.append(observe_state(sim, operational_node_ids=operational_node_ids,
                                              resource_ids=resource_ids))
        runs.append(ExperimentRun(
            case.name, app.content_id, app.world_definition_id, app.scenario_id,
            _digest(graph.to_json_data()), start_state_sha, tuple(observations),
            tuple(failures), tuple(attempted),
        ))
    return tuple(runs)


MetricKey = tuple[str, str, str, str, str]


def _metrics(observation: StateObservation) -> dict[MetricKey, StateMetric]:
    return {(m.kind, m.subject_id, m.context_id, m.unit, m.provenance): m
            for m in observation.metrics}


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
        rows.append({
            "variant": variant.name,
            "same_definition_graph": baseline.definition_graph_sha256 == variant.definition_graph_sha256,
            "same_initial_state": baseline.initial_state_sha256 == variant.initial_state_sha256,
            "same_content_id": baseline.content_id == variant.content_id,
            "same_world_definition": baseline.world_definition_id == variant.world_definition_id,
            "same_scenario": baseline.scenario_id == variant.scenario_id,
            "metric_differences": differences,
            "rejected_commands": [vars(row) for row in variant.rejected_commands],
        })
    return {"baseline": baseline.name, "comparisons": rows, "interpretation": "typed observed stock/capacity differences; net stock change is not settled gross flow"}

"""Run actual GameApplication commands and aggregate actual settlement evidence.

No alternative physics, fixed stage build orders or created assets are implied by
an experiment script. Experiment records are non-authoritative and never Saved
as a parallel Game State.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, TextIO

from ..api.codec import decode_command, decode_query, to_jsonable
from ..app_contracts.operations import AdvanceTime
from ..application import GameApplication
from ..persistence import save_game


def _positive_int(value, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


class PeriodEvidence:
    """Exact, bounded-memory rollups of observed canonical-day settlements."""

    def __init__(self):
        self.days = 0
        self.inventory = defaultdict(float)
        self.activity_flows = defaultdict(float)
        self.custody = defaultdict(float)
        self.unknown = defaultdict(float)
        self.allocation = defaultdict(lambda: defaultdict(float))
        self.limiters = defaultdict(int)

    def append(self, trace):
        self.days += 1
        for movement in trace.movements:
            self.inventory[(movement.node_id, movement.resource_id, movement.direction,
                            movement.operation)] += movement.quantity_t
        for flow in trace.activity_flows():
            self.activity_flows[(flow.activity_id, flow.resource_id, flow.source_owner,
                                 flow.destination_owner, flow.operation)] += flow.quantity_t
        for transfer in trace.custody_transfers():
            self.custody[(transfer.node_id, transfer.resource_id, transfer.source_owner,
                          transfer.destination_owner, transfer.operation)] += transfer.quantity_t
        for movement in trace.unattributed_movements():
            self.unknown[(movement.node_id, movement.resource_id, movement.direction,
                          movement.operation)] += movement.quantity_t
        for row in trace.allocations:
            key = (row.kind, row.subject_id, row.context_id, row.unit, row.provenance)
            bucket = self.allocation[key]
            for field in ("requested", "allocated", "unmet", "capacity", "used", "remaining"):
                value = getattr(row, field)
                if value is not None:
                    bucket[field + "_sum"] += value
            for limiter in row.limiting_factors:
                self.limiters[(row.kind, row.subject_id, row.context_id, limiter)] += 1

    def to_json_data(self) -> dict:
        def rows(values, fields, measure):
            return [{**dict(zip(fields, key)), measure: amount}
                    for key, amount in sorted(values.items())]
        return {
            "observed_days": self.days,
            "settlements_by_operation": rows(self.inventory,
                ("node", "resource", "direction", "operation"), "quantity_t"),
            "attributed_activity_flows": rows(self.activity_flows,
                ("activity", "resource", "source_owner", "destination_owner", "operation"), "quantity_t"),
            "custody_transfers": rows(self.custody,
                ("node", "resource", "source_owner", "destination_owner", "operation"), "quantity_t"),
            "unattributed_settlements": rows(self.unknown,
                ("node", "resource", "direction", "operation"), "quantity_t"),
            "allocation_integrals": [
                {**dict(zip(("kind", "subject", "context", "unit", "provenance"), key)), **dict(sorted(v.items()))}
                for key, v in sorted(self.allocation.items())
            ],
            "limiting_factor_days": rows(self.limiters,
                ("kind", "subject", "context", "factor"), "observed_occurrences"),
            "interpretation": (
                "Actual owner settlement and allocation from canonical days. "
                "Settlement directions may be custody reclassification, not production/consumption; "
                "attributed activity and unattributed settlement remain separate. "
                "Allocation sums are observations across days, not additional Resource flows. "
                "These records are not saved game State or evidence of pre-start acquisitions."
            ),
        }


def run_experiment(app: GameApplication, steps: list[dict], *, trace_file: TextIO | None = None,
                   checkpoint_root: Path | None = None) -> dict:
    """Execute an authored sequence, with explicit stops and no automatic decisions."""
    import json

    if not isinstance(steps, list):
        raise ValueError("steps must be a list")
    report = {"start_day": app.game_day, "scenario_id": app.scenario_id,
              "content_id": app.content_id, "world_definition_id": app.world_definition_id,
              "steps": []}
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or "action" not in step:
            raise ValueError(f"step {index}: expected action object")
        action = step["action"]
        before = app.game_day
        entry = {"index": index, "action": action, "start_day": before}
        try:
            if action == "command":
                cmd = decode_command({"type": step["type"], "payload": step.get("payload", {})})
                if isinstance(cmd, AdvanceTime):
                    raise ValueError("use advance action for observed time progression")
                entry["command"] = {"type": step["type"], "payload": step.get("payload", {})}
                with app.observe_development_day() as trace:
                    entry["result"] = to_jsonable(app.execute(cmd))
                entry["actual_settlements"] = trace.to_json_data()
                if trace_file is not None:
                    trace_file.write(json.dumps({"kind": "command", "index": index,
                                                 "trace": trace.to_json_data()}, ensure_ascii=False) + "\n")
            elif action == "query":
                entry["query"] = {"type": step["type"], "payload": step.get("payload", {})}
                entry["result"] = to_jsonable(app.query(decode_query(entry["query"])))
            elif action == "queries":
                raw = step["queries"]
                if not isinstance(raw, dict):
                    raise ValueError("queries must be an object")
                entry["result"] = to_jsonable(app.query_many({name: decode_query(spec)
                                                                for name, spec in raw.items()}))
            elif action == "state":
                scope = step.get("scope", {})
                if not isinstance(scope, dict) or set(scope) - {"nodes", "resources"}:
                    raise ValueError("state scope supports nodes/resources")
                nodes = None if "nodes" not in scope else frozenset(scope["nodes"])
                resources = None if "resources" not in scope else frozenset(scope["resources"])
                entry["result"] = app.observe_development_state(
                    operational_node_ids=nodes, resource_ids=resources).to_json_data()
            elif action == "advance":
                days = _positive_int(step["days"], "days")
                evidence = PeriodEvidence()
                for _ in range(days):
                    with app.observe_development_day() as trace:
                        app.execute(AdvanceTime(days=1))
                    evidence.append(trace)
                    if trace_file is not None:
                        trace_file.write(json.dumps({"kind": "day", "trace": trace.to_json_data()}, ensure_ascii=False) + "\n")
                entry["days"] = days
                entry["result"] = evidence.to_json_data()
            elif action == "checkpoint":
                if checkpoint_root is None:
                    raise ValueError("checkpoint requires --checkpoint-dir")
                name = step.get("name")
                if not isinstance(name, str) or not name or name in (".", "..") or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in name):
                    raise ValueError("invalid checkpoint name")
                path = checkpoint_root / f"{name}.json"
                checkpoint_root.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    raise FileExistsError(f"checkpoint exists: {path}")
                save_game(app, path)
                entry["save"] = str(path)
            else:
                raise ValueError(f"unknown action: {action}")
        except Exception as exc:
            entry["error"] = {"type": type(exc).__name__, "message": str(exc)}
            entry["end_day"] = app.game_day
            report["steps"].append(entry)
            report["failed_step"] = index
            report["end_day"] = entry["end_day"]
            return report
        entry["end_day"] = app.game_day
        report["steps"].append(entry)
    report["end_day"] = app.game_day
    return report


def compare_experiments(left: dict, right: dict) -> dict:
    """Compare measured, like-for-like final State metrics, not proposed plans."""
    fields = ("content_id", "world_definition_id", "scenario_id", "start_day",
              "origin_state_sha256")
    same_start = all(left.get(k) is not None and left.get(k) == right.get(k) for k in fields)

    def metrics(data):
        records = data.get("end_state", {}).get("metrics", ())
        result = {}
        for row in records:
            key = (row["kind"], row["subject_id"], row["context_id"],
                   row["unit"], row["provenance"])
            if key in result:
                raise ValueError(f"duplicate state metric: {key}")
            result[key] = row["quantity"]
        return result

    def settlements(data):
        values = defaultdict(float)
        for step in data.get("steps", ()):  # Same owner records; no inferred supply/consumption.
            if step.get("action") == "advance":
                rows = step.get("result", {}).get("settlements_by_operation", ())
                for row in rows:
                    key = (row["node"], row["resource"], row["direction"], row["operation"])
                    values[key] += row["quantity_t"]
            if step.get("action") == "command":
                for row in step.get("actual_settlements", {}).get("inventory_movements", ()):
                    key = (row["node_id"], row["resource_id"], row["direction"], row["operation"])
                    values[key] += row["quantity_t"]
        return values

    a, b = metrics(left), metrics(right)
    changes = []
    for key in sorted(a.keys() | b.keys()):
        value_a, value_b = a.get(key), b.get(key)
        if value_a == value_b:
            continue
        changes.append({**dict(zip(("kind", "subject", "context", "unit", "provenance"), key)),
                        "left": value_a, "right": value_b,
                        "difference": None if value_a is None or value_b is None else value_b - value_a})
    a_settled, b_settled = settlements(left), settlements(right)
    settlement_changes = [
        {**dict(zip(("node", "resource", "direction", "operation"), key)),
         "left_t": a_settled.get(key, 0.0), "right_t": b_settled.get(key, 0.0),
         "difference_t": b_settled.get(key, 0.0) - a_settled.get(key, 0.0)}
        for key in sorted(a_settled.keys() | b_settled.keys())
        if a_settled.get(key, 0.0) != b_settled.get(key, 0.0)
    ]
    return {
        "same_start_state": same_start,
        "left": {"start_day": left.get("start_day"), "end_day": left.get("end_day"),
                 "failed_step": left.get("failed_step")},
        "right": {"start_day": right.get("start_day"), "end_day": right.get("end_day"),
                  "failed_step": right.get("failed_step")},
        "state_metric_differences": changes,
        "actual_settlement_differences": settlement_changes,
        "scope": ("Actual end-state metric differences; absent metrics are null, not zero. "
                  "Different end days are reported as such, not normalized. "
                  "Equal start fingerprints certify equivalent canonical State and Content, "
                  "not identical choices or balance merit."),
    }

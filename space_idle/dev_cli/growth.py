"""Measured economic growth from canonical GameApplication progression.

No plan replay, alternative allocator, predicted completion, or persistent Game
State. Observations only summarize what ordinary game ticks actually settled.
"""
from __future__ import annotations

from collections import defaultdict

from ..app_contracts.operations import AdvanceTime


def _quantities(snapshot: dict, kind: str, columns: tuple[str, ...], value: str) -> dict:
    return {tuple(row[field] for field in columns): row[value] for row in snapshot[kind]}


def _changes(before: dict, after: dict) -> list[dict]:
    events = []
    for kind, keys, count in (("facilities", ("node", "facility"), "count"),
                              ("fleet", ("node", "vehicle"), "count"),
                              ("population", ("node",), "people")):
        old = _quantities(before, kind, keys, count)
        new = _quantities(after, kind, keys, count)
        for k in sorted(old.keys() | new.keys()):
            if old.get(k, 0) != new.get(k, 0):
                events.append({"day": after["day"], "kind": kind, **dict(zip(keys, k)),
                               "before": old.get(k, 0), "after": new.get(k, 0),
                               "delta": new.get(k, 0) - old.get(k, 0)})
    old_stages = {item["research"]: item["stage"] for item in before["active_research"]}
    new_stages = {item["research"]: item["stage"] for item in after["active_research"]}
    for rid in sorted(new_stages.keys() | old_stages.keys()):
        if new_stages.get(rid) != old_stages.get(rid):
            events.append({"day": after["day"], "kind": "research_stage_transition",
                           "research": rid, "before": old_stages.get(rid), "after": new_stages.get(rid)})
    for tid in sorted(set(after["completed_technologies"]) - set(before["completed_technologies"])):
        events.append({"day": after["day"], "kind": "technology_completed", "research": tid})
    return events


def observe_growth(app, days: int, *, sample_days: int = 30) -> dict:
    """Read measured settlements and sparse asset snapshots while normal ticks run.

    An already queued plan may change assets; absent player decisions are not
    synthesized. Allocations are service measures, not additional physical flow.
    """
    if type(days) is not int or days <= 0:
        raise ValueError("observe-days must be a positive integer")
    if type(sample_days) is not int or sample_days <= 0:
        raise ValueError("sample-days must be a positive integer")
    original = app.balance_growth_state()
    previous = original
    snapshots = [original]
    events = []
    movements = defaultdict(float)
    proven_flows = defaultdict(float)
    custody = defaultdict(float)
    unknown = defaultdict(float)
    allocations = defaultdict(lambda: defaultdict(float))
    limiter_days = defaultdict(int)
    for day_index in range(1, days + 1):
        with app.observe_development_day() as trace:
            app.execute(AdvanceTime(days=1))
        for item in trace.movements:
            movements[(item.node_id, item.resource_id, item.direction, item.operation)] += item.quantity_t
        for item in trace.activity_flows():
            proven_flows[(item.activity_id, item.resource_id, item.source_owner,
                          item.destination_owner, item.operation)] += item.quantity_t
        for item in trace.custody_transfers():
            custody[(item.node_id, item.resource_id, item.source_owner, item.destination_owner)] += item.quantity_t
        for item in trace.unattributed_movements():
            unknown[(item.node_id, item.resource_id, item.direction, item.operation)] += item.quantity_t
        day_limiters = set()
        for item in trace.allocations:
            key = (item.kind, item.subject_id, item.context_id, item.unit, item.provenance)
            for field in ("requested", "allocated", "unmet", "capacity", "used", "remaining"):
                amount = getattr(item, field)
                if amount is not None:
                    allocations[key][field + "_sum"] += amount
            for limiter in item.limiting_factors:
                day_limiters.add((item.kind, item.subject_id, item.context_id, limiter))
        for limiter in day_limiters:
            limiter_days[limiter] += 1
        current = app.balance_growth_state()
        changed = _changes(previous, current)
        if changed:
            events.extend(changed)
        if changed or day_index % sample_days == 0 or day_index == days:
            snapshots.append(current)
        previous = current

    def entries(values, fields, amount_field="quantity_t"):
        return [{**dict(zip(fields, key)), amount_field: amount}
                for key, amount in sorted(values.items())]

    before_inventory = _quantities(original, "inventory", ("node", "resource"), "stock_t")
    after_inventory = _quantities(previous, "inventory", ("node", "resource"), "stock_t")
    inventory_changes = [
        {"node": node, "resource": resource, "initial_stock_t": before_inventory.get((node, resource), 0.0),
         "final_stock_t": after_inventory.get((node, resource), 0.0),
         "delta_stock_t": after_inventory.get((node, resource), 0.0) - before_inventory.get((node, resource), 0.0)}
        for node, resource in sorted(before_inventory.keys() | after_inventory.keys())
        if before_inventory.get((node, resource), 0.0) != after_inventory.get((node, resource), 0.0)
    ]
    return {
        "kind": "canonical_growth_observation", "start_day": original["day"],
        "end_day": previous["day"], "observed_days": days, "sample_days": sample_days,
        "start": original, "end": previous, "snapshots": snapshots,
        "asset_and_technology_events": events, "inventory_stock_changes": inventory_changes,
        "settlements_by_operation": entries(movements, ("node", "resource", "direction", "operation")),
        "attributed_activity_flows": entries(proven_flows,
            ("activity", "resource", "source_owner", "destination_owner", "operation")),
        "custody_transfers": entries(custody, ("node", "resource", "source_owner", "destination_owner")),
        "unattributed_settlements": entries(unknown, ("node", "resource", "direction", "operation")),
        "allocation_integrals": [{**dict(zip(("kind", "subject", "context", "unit", "provenance"), key)),
                                  **dict(sorted(v.items()))}
                                 for key, v in sorted(allocations.items())],
        "limiting_factor_days": entries(limiter_days,
            ("kind", "subject", "context", "factor"), "days"),
        "interpretation": ("Canonical GameApplication ticks from the input State with only its existing plans. "
                           "Snapshots record owned stock and assets, not the cause of changes. "
                           "Inventory custody transfers and owner-attributed flow are separate; "
                           "unattributed settlements are not inferred production or consumption. "
                           "Allocation integrals are not Resource flows. This run is not a completed "
                           "design-scale plan, and no player decisions are invented."),
    }

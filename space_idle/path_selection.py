from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable
from typing import TypeVar

from .transport.models import PathPolicy

NodeT = TypeVar("NodeT")
EdgeT = TypeVar("EdgeT")

_EPS = 1.0e-12


def _dijkstra(
    origin: NodeT,
    destination: NodeT,
    *,
    outgoing: Callable[[NodeT], Iterable[EdgeT]],
    edge_destination: Callable[[EdgeT], NodeT],
    edge_weight: Callable[[EdgeT], float],
    edge_key: Callable[[EdgeT], str],
) -> tuple[float, tuple[EdgeT, ...]]:
    queue: list[tuple[float, tuple[str, ...], NodeT, tuple[EdgeT, ...]]] = [
        (0.0, (), origin, ())
    ]
    best: dict[NodeT, tuple[float, tuple[str, ...]]] = {}
    while queue:
        score, keys, node, path = heapq.heappop(queue)
        prior = best.get(node)
        if prior is not None and prior <= (score, keys):
            continue
        best[node] = (score, keys)
        if node == destination:
            return score, path
        for edge in sorted(outgoing(node), key=edge_key):
            weight = float(edge_weight(edge))
            if weight < 0:
                raise ValueError("path metric must be non-negative")
            key = edge_key(edge)
            heapq.heappush(
                queue,
                (
                    score + weight,
                    keys + (key,),
                    edge_destination(edge),
                    path + (edge,),
                ),
            )
    raise ValueError(f"no path {origin} -> {destination}")



def select_canonical_path(
    origin: NodeT,
    destination: NodeT,
    *,
    outgoing: Callable[[NodeT], Iterable[EdgeT]],
    edge_destination: Callable[[EdgeT], NodeT],
    edge_time: Callable[[EdgeT], float],
    edge_propellant: Callable[[EdgeT], float],
    edge_capacity: Callable[[EdgeT], float],
    edge_key: Callable[[EdgeT], str],
) -> tuple[EdgeT, ...]:
    """Select the canonical operational path without player strategy modes.

    Latency, operational propellant burden, handoff burden and currently
    available capacity are normalized against the best achievable total for
    the same candidate graph. Stable keys are only used to break equal scores.
    """

    best_time, _ = _dijkstra(
        origin, destination, outgoing=outgoing, edge_destination=edge_destination,
        edge_weight=edge_time, edge_key=edge_key,
    )
    best_propellant, _ = _dijkstra(
        origin, destination, outgoing=outgoing, edge_destination=edge_destination,
        edge_weight=edge_propellant, edge_key=edge_key,
    )
    best_hops, _ = _dijkstra(
        origin, destination, outgoing=outgoing, edge_destination=edge_destination,
        edge_weight=lambda _edge: 1.0, edge_key=edge_key,
    )
    best_capacity_burden, _ = _dijkstra(
        origin, destination, outgoing=outgoing, edge_destination=edge_destination,
        edge_weight=lambda edge: 1.0 / max(float(edge_capacity(edge)), _EPS),
        edge_key=edge_key,
    )
    time_scale = max(best_time, _EPS)
    propellant_scale = max(best_propellant, _EPS)
    hop_scale = max(best_hops, 1.0)
    capacity_scale = max(best_capacity_burden, _EPS)
    return _dijkstra(
        origin,
        destination,
        outgoing=outgoing,
        edge_destination=edge_destination,
        edge_weight=lambda edge: (
            float(edge_time(edge)) / time_scale
            + float(edge_propellant(edge)) / propellant_scale
            + 1.0 / hop_scale
            + (1.0 / max(float(edge_capacity(edge)), _EPS)) / capacity_scale
        ),
        edge_key=edge_key,
    )[1]


def select_canonical_candidate(
    candidates: Iterable[EdgeT],
    *,
    metric_time: Callable[[EdgeT], float],
    metric_propellant: Callable[[EdgeT], float],
    metric_handoffs: Callable[[EdgeT], float],
    metric_capacity_burden: Callable[[EdgeT], float],
    stable_key: Callable[[EdgeT], str],
) -> EdgeT:
    """Compare complete candidates with unit-independent canonical metrics."""

    rows = tuple(candidates)
    if not rows:
        raise ValueError("no path candidate")

    metric_functions = (
        metric_time, metric_propellant, metric_handoffs, metric_capacity_burden
    )
    bounds: list[tuple[float, float]] = []
    for metric in metric_functions:
        values = tuple(float(metric(row)) for row in rows)
        bounds.append((min(values), max(values)))

    def normalized(value: float, bounds: tuple[float, float]) -> float:
        low, high = bounds
        if high - low <= _EPS:
            return 0.0
        return (value - low) / (high - low)

    return min(
        rows,
        key=lambda row: (
            sum(
                normalized(float(metric(row)), bound)
                for metric, bound in zip(metric_functions, bounds, strict=True)
            ),
            stable_key(row),
        ),
    )

def select_tradeoff_path(
    origin: NodeT,
    destination: NodeT,
    *,
    outgoing: Callable[[NodeT], Iterable[EdgeT]],
    edge_destination: Callable[[EdgeT], NodeT],
    edge_time: Callable[[EdgeT], float],
    edge_propellant: Callable[[EdgeT], float],
    edge_key: Callable[[EdgeT], str],
    preference: PathPolicy,
) -> tuple[EdgeT, ...]:
    """Select one deterministic path using the canonical time/propellant preference.

    BALANCED normalizes each additive metric by the best achievable end-to-end
    total for the same origin/destination, then minimizes the sum of the two
    normalized totals. This keeps the default independent of metric units while
    preserving deterministic stable-key tie breaking.
    """

    preference = PathPolicy(preference)
    if preference is PathPolicy.FASTEST:
        return _dijkstra(
            origin,
            destination,
            outgoing=outgoing,
            edge_destination=edge_destination,
            edge_weight=edge_time,
            edge_key=edge_key,
        )[1]
    if preference is PathPolicy.LOWEST_PROPELLANT:
        return _dijkstra(
            origin,
            destination,
            outgoing=outgoing,
            edge_destination=edge_destination,
            edge_weight=edge_propellant,
            edge_key=edge_key,
        )[1]
    if preference is not PathPolicy.BALANCED:
        raise ValueError(f"unsupported path preference: {preference}")

    fastest_total, _ = _dijkstra(
        origin,
        destination,
        outgoing=outgoing,
        edge_destination=edge_destination,
        edge_weight=edge_time,
        edge_key=edge_key,
    )
    lowest_propellant_total, _ = _dijkstra(
        origin,
        destination,
        outgoing=outgoing,
        edge_destination=edge_destination,
        edge_weight=edge_propellant,
        edge_key=edge_key,
    )
    time_scale = max(fastest_total, _EPS)
    propellant_scale = max(lowest_propellant_total, _EPS)
    return _dijkstra(
        origin,
        destination,
        outgoing=outgoing,
        edge_destination=edge_destination,
        edge_weight=lambda edge: (
            float(edge_time(edge)) / time_scale
            + float(edge_propellant(edge)) / propellant_scale
        ),
        edge_key=edge_key,
    )[1]


def select_tradeoff_candidate(
    candidates: Iterable[EdgeT],
    *,
    metric_time: Callable[[EdgeT], float],
    metric_propellant: Callable[[EdgeT], float],
    stable_key: Callable[[EdgeT], str],
    preference: PathPolicy,
) -> EdgeT:
    rows = tuple(candidates)
    if not rows:
        raise ValueError("no path candidate")
    preference = PathPolicy(preference)
    if preference is PathPolicy.FASTEST:
        return min(rows, key=lambda row: (float(metric_time(row)), stable_key(row)))
    if preference is PathPolicy.LOWEST_PROPELLANT:
        return min(rows, key=lambda row: (float(metric_propellant(row)), stable_key(row)))
    if preference is not PathPolicy.BALANCED:
        raise ValueError(f"unsupported path preference: {preference}")
    best_time = min(float(metric_time(row)) for row in rows)
    best_propellant = min(float(metric_propellant(row)) for row in rows)
    time_scale = max(best_time, _EPS)
    propellant_scale = max(best_propellant, _EPS)
    return min(
        rows,
        key=lambda row: (
            float(metric_time(row)) / time_scale
            + float(metric_propellant(row)) / propellant_scale,
            stable_key(row),
        ),
    )

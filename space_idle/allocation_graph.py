from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AllocationDependency:
    """Directed same-tick dependency between allocation nodes.

    ``node`` may be resolved only after ``upstream_node``.  The dependency is
    transient planning/configuration data and is never persisted.
    """

    node: str
    upstream_node: str

    def __post_init__(self) -> None:
        if not self.node or not self.upstream_node:
            raise ValueError("allocation dependency nodes must not be empty")


def allocation_dependency_order(
    nodes: Iterable[str],
    dependencies: Iterable[AllocationDependency],
    *,
    cycle_label: str = "allocation dependency cycle",
) -> tuple[str, ...]:
    """Return deterministic upstream-first order and fail closed on cycles."""

    node_set = set(nodes)
    edges = tuple(dependencies)
    for edge in edges:
        node_set.add(edge.node)
        node_set.add(edge.upstream_node)

    downstream: dict[str, set[str]] = {node: set() for node in node_set}
    indegree: dict[str, int] = {node: 0 for node in node_set}
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        key = (edge.upstream_node, edge.node)
        if key in seen:
            continue
        seen.add(key)
        downstream[edge.upstream_node].add(edge.node)
        indegree[edge.node] += 1

    ready = sorted(node for node, count in indegree.items() if count == 0)
    ordered: list[str] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for dependent in sorted(downstream[node]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort()

    if len(ordered) != len(node_set):
        cyclic = tuple(sorted(node for node, count in indegree.items() if count > 0))
        raise ValueError(f"{cycle_label}: " + " -> ".join(cyclic))
    return tuple(ordered)

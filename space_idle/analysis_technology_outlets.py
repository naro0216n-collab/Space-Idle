"""Research-outlet reachability across registered Definition relations.

An outlet is an *authored* method unlock. Reaching one does not establish that a
player can acquire its requirements or that any gameplay outcome is desirable.
This is deliberately a read-only graph projection, not a technology evaluator.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Iterable
from typing import Hashable

from .analysis_graph import DependencyDefinitionGraph, DependencyNode


@dataclass(frozen=True)
class TechnologyOutlet:
    technology: DependencyNode
    classification: str
    direct_methods: tuple[DependencyNode, ...]
    reachable_methods: tuple[DependencyNode, ...]
    downstream_technologies: tuple[DependencyNode, ...]

    @property
    def direct_method_count(self) -> int:
        return len(self.direct_methods)

    @property
    def reachable_method_count(self) -> int:
        return len(self.reachable_methods)

    @property
    def downstream_technology_count(self) -> int:
        return len(self.downstream_technologies)

    def to_json_data(self) -> dict:
        # Preserve actual target identity: counts alone cannot support a
        # per-Technology Content audit, and an outlet is not proof of usability.
        def reference(node: DependencyNode) -> dict:
            return {"kind": node.kind, "id": node.id}

        return {
            "technology_id": self.technology.id,
            "classification": self.classification,
            "direct_method_count": self.direct_method_count,
            "reachable_method_count": self.reachable_method_count,
            "downstream_technology_count": self.downstream_technology_count,
            "direct_methods": [reference(node) for node in self.direct_methods],
            "reachable_methods": [reference(node) for node in self.reachable_methods],
            "downstream_technologies": [node.id for node in self.downstream_technologies],
        }


def registered_outlet_reachability(
    technology: Hashable,
    successors: Mapping[Hashable, Iterable[Hashable]],
    direct: Mapping[Hashable, Iterable[Hashable]],
) -> tuple[str, set[Hashable], set[Hashable]]:
    """Share declaration-only reachability between diagnostics and UI Query.

    Only the caller's registered method/prerequisite edges are consulted. This
    neither evaluates physical Eligibility nor constructs a full analysis graph
    for ordinary Application reads.
    """
    reached = {technology}
    frontier = [technology]
    while frontier:
        current = frontier.pop()
        for downstream in successors.get(current, ()):
            if downstream not in reached:
                reached.add(downstream)
                frontier.append(downstream)
    methods = {method for item in reached for method in direct.get(item, ())}
    classification = (
        "direct_method" if any(direct.get(technology, ())) else
        "via_research" if methods else
        "research_only_no_method" if len(reached) > 1 else
        "no_downstream_outlet"
    )
    return classification, methods, reached - {technology}


def classify_technology_outlets(graph: DependencyDefinitionGraph) -> tuple[TechnologyOutlet, ...]:
    """Report authored direct, prerequisite-only, and absent outlet paths.

    Traversal follows only technology prerequisite edges; a method's existence
    is not inferred from names, research stages, resource edges, or effects.
    Each method is counted once even when reachable through several paths.
    """
    technologies = tuple(sorted(node for node in graph.nodes if node.kind == "technology"))
    successors: dict[DependencyNode, set[DependencyNode]] = {node: set() for node in technologies}
    direct: dict[DependencyNode, set[DependencyNode]] = {node: set() for node in technologies}
    for relation in graph.relations:
        if relation.source not in successors:
            continue
        if relation.kind == "technology_prerequisite" and relation.target in successors:
            successors[relation.source].add(relation.target)
        elif relation.kind == "unlocks_method" and relation.target.kind != "technology":
            direct[relation.source].add(relation.target)

    rows = []
    for technology in technologies:
        classification, methods, downstream = registered_outlet_reachability(
            technology, successors, direct,
        )
        rows.append(TechnologyOutlet(
            technology, classification, tuple(sorted(direct[technology])),
            tuple(sorted(methods)), tuple(sorted(downstream)),
        ))
    return tuple(rows)

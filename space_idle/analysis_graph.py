"""Read-only typed definition dependencies for offline balance diagnostics.

The graph has no simulation authority. Domain contributors emit relations from the
registered definitions; live eligibility and allocation remain with their owners.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Iterable


@dataclass(frozen=True, order=True)
class DependencyNode:
    kind: str
    id: str
    scope: str = "definition"

    def __post_init__(self) -> None:
        if not self.kind or not self.id or not self.scope:
            raise ValueError("dependency node requires kind, id and scope")


@dataclass(frozen=True)
class DependencyRelation:
    kind: str
    source: DependencyNode
    target: DependencyNode
    provenance: str
    quantity: float | None = None
    unit: str | None = None
    time_basis: str | None = None
    condition: str | None = None

    def __post_init__(self) -> None:
        if not self.kind or not self.provenance:
            raise ValueError("dependency relation requires kind and provenance")
        if self.quantity is not None and (not math.isfinite(self.quantity) or self.quantity < 0):
            raise ValueError("dependency relation quantity must be finite and nonnegative")
        if (self.quantity is None) != (self.unit is None):
            raise ValueError("dependency relation quantity and unit must be declared together")
        if self.unit is not None and not self.unit:
            raise ValueError("dependency relation unit must be nonempty")


@dataclass(frozen=True)
class DependencyFragment:
    nodes: tuple[DependencyNode, ...]
    relations: tuple[DependencyRelation, ...]


@dataclass(frozen=True)
class DependencyDiagnostic:
    code: str
    detail: str
    relation_kind: str | None = None
    provenance: str | None = None
    node: DependencyNode | None = None


@dataclass(frozen=True)
class DependencyDefinitionGraph:
    nodes: tuple[DependencyNode, ...]
    relations: tuple[DependencyRelation, ...]
    diagnostics: tuple[DependencyDiagnostic, ...]

    def to_json_data(self) -> dict:
        """Return stable, serializable data without mutating the Simulation."""
        def node(row: DependencyNode) -> dict:
            return {"kind": row.kind, "id": row.id, "scope": row.scope}

        return {
            "nodes": [node(row) for row in self.nodes],
            "relations": [
                {
                    "kind": row.kind, "source": node(row.source), "target": node(row.target),
                    "quantity": row.quantity, "unit": row.unit, "time_basis": row.time_basis,
                    "condition": row.condition, "provenance": row.provenance,
                }
                for row in self.relations
            ],
            "diagnostics": [
                {
                    "code": row.code, "detail": row.detail,
                    "relation_kind": row.relation_kind, "provenance": row.provenance,
                    "node": node(row.node) if row.node else None,
                }
                for row in self.diagnostics
            ],
        }

    def subset(self, roots: Iterable[DependencyNode], *, downstream: bool = True) -> "DependencyDefinitionGraph":
        """Select reachable Definition relations, retaining their AND input groups.

        A relation's source/target direction describes its semantic dependency, not
        necessarily a physical input flow. Traversal is an analysis filter only.
        """
        selected = set(roots)
        previous_count = -1
        while previous_count != len(selected):
            previous_count = len(selected)
            for relation in self.relations:
                start, end = ((relation.source, relation.target) if downstream
                              else (relation.target, relation.source))
                if start in selected:
                    selected.add(end)
        # Include all requirements feeding a selected method, without traversing
        # onward from those incidental input nodes to unrelated methods.
        requirement_kinds = {
            "consumes_resource", "requires_capability", "unlocks_method",
            "technology_prerequisite", "research_point_cost", "requires_experience",
            "requires_execution_capacity", "requires_service_capacity",
            "requires_construction_work", "requires_site_capability",
            "requires_site_classification", "requires_site_environment", "requires_knowledge",
            "invests_resource", "funds_initial_inventory", "requires_fleet_units",
            "requires_population_commitment", "requires_origin_context",
            "requires_survey_reach", "requires_resource_opportunity", "requires_opportunity_factor",
            "minimum_source_units", "requires_operation",
        }
        selected.update(
            relation.source for relation in self.relations
            if relation.kind in requirement_kinds and relation.target in selected
        )
        return DependencyDefinitionGraph(
            tuple(node for node in self.nodes if node in selected),
            tuple(row for row in self.relations if row.source in selected and row.target in selected),
            tuple(row for row in self.diagnostics if row.node is None or row.node in selected),
        )


Contributor = Callable[[], DependencyFragment]


class DefinitionGraphRegistry:
    """Composition registers one contributor per owned Definition collection."""

    def __init__(self) -> None:
        self._contributors: dict[str, Contributor] = {}
        self._relation_kinds: dict[str, frozenset[str]] = {}
        self._expected_definitions: dict[str, Callable[[], Iterable[DependencyNode]]] = {}

    def register(self, domain: str, contributor: Contributor, *, relation_kinds: Iterable[str],
                 expected_definitions: Callable[[], Iterable[DependencyNode]] | None = None) -> None:
        kinds = frozenset(relation_kinds)
        if not domain or domain in self._contributors or not kinds or any(not kind for kind in kinds):
            raise ValueError(f"invalid or duplicate graph Contributor registration: {domain}")
        self._contributors[domain] = contributor
        self._relation_kinds[domain] = kinds
        if expected_definitions is not None:
            self._expected_definitions[domain] = expected_definitions

    def build(self) -> DependencyDefinitionGraph:
        definitions: dict[DependencyNode, str] = {}
        relations: list[DependencyRelation] = []
        diagnostics: list[DependencyDiagnostic] = []
        for domain in sorted(self._contributors):
            fragment = self._contributors[domain]()
            for node in fragment.nodes:
                if node in definitions:
                    diagnostics.append(DependencyDiagnostic(
                        "duplicate_definition_owner", f"{definitions[node]} and {domain} declare {node.id}", node=node,
                    ))
                else:
                    definitions[node] = domain
            if domain in self._expected_definitions:
                for node in self._expected_definitions[domain]():
                    if node not in fragment.nodes:
                        diagnostics.append(DependencyDiagnostic(
                            "unrepresented_registered_definition",
                            f"{domain} did not contribute {node.kind}:{node.id}", node=node,
                        ))
            for relation in fragment.relations:
                if relation.kind not in self._relation_kinds[domain]:
                    diagnostics.append(DependencyDiagnostic(
                        "unknown_relation_kind", f"{domain} emitted {relation.kind}",
                        relation.kind, relation.provenance, relation.source,
                    ))
                relations.append(relation)
        seen_relations: set[DependencyRelation] = set()
        for relation in relations:
            if relation in seen_relations:
                diagnostics.append(DependencyDiagnostic(
                    "duplicate_relation", f"duplicate {relation.kind} {relation.source} → {relation.target}",
                    relation.kind, relation.provenance, relation.target,
                ))
            seen_relations.add(relation)
            if relation.quantity is not None and relation.time_basis is None:
                diagnostics.append(DependencyDiagnostic(
                    "quantitative_relation_without_time_basis", f"{relation.kind} lacks time basis",
                    relation.kind, relation.provenance, relation.target,
                ))
            for endpoint in (relation.source, relation.target):
                if endpoint not in definitions:
                    diagnostics.append(DependencyDiagnostic(
                        "undefined_reference", f"{relation.kind} references {endpoint.kind}:{endpoint.id}",
                        relation.kind, relation.provenance, endpoint,
                    ))
        return DependencyDefinitionGraph(
            tuple(sorted(definitions)), tuple(sorted(relations, key=lambda row: (
                row.kind, row.source, row.target, row.provenance, row.unit or "", row.quantity or 0.0
            ))), tuple(sorted(diagnostics, key=lambda row: (
                row.code, row.detail, row.provenance or "",
            ))),
        )

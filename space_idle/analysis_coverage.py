"""Read-only coverage findings over the registered *definition* dependency graph.

These are possible authoring gaps, not physical feasibility verdicts. In particular,
a technology at the end of a DAG may deliberately have no downstream use yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict

from .analysis_graph import DependencyDefinitionGraph, DependencyNode


@dataclass(frozen=True)
class DefinitionCoverageFinding:
    code: str
    subject: DependencyNode
    evidence: tuple[str, ...]
    significance: str = "informational"

    def to_json_data(self) -> dict:
        return {
            "code": self.code,
            "significance": self.significance,
            "subject": {
                "kind": self.subject.kind,
                "id": self.subject.id,
                "scope": self.subject.scope,
            },
            "evidence": list(self.evidence),
        }


def inspect_definition_coverage(graph: DependencyDefinitionGraph) -> tuple[DefinitionCoverageFinding, ...]:
    """Identify potential gaps without inferring current eligibility or actual flow.

    The supply and requirement relations are deliberately directional. A
    prerequisite technology leading to another technology is an authored outlet;
    merely having a Research Stage or RP cost is not.
    """
    supplied = {
        relation.target for relation in graph.relations
        if relation.kind == "supplies_capability"
    }
    demands: dict[DependencyNode, set[str]] = defaultdict(set)
    outlet: dict[DependencyNode, set[str]] = defaultdict(set)
    for relation in graph.relations:
        if relation.kind == "requires_capability" and relation.source.kind == "capability":
            demands[relation.source].add(relation.provenance)
        if relation.kind in ("unlocks_method", "technology_prerequisite") and relation.source.kind == "technology":
            outlet[relation.source].add(relation.provenance)

    findings: list[DefinitionCoverageFinding] = []
    for capability in sorted(demands):
        if capability not in supplied:
            findings.append(DefinitionCoverageFinding(
                "required_capability_without_definition_supplier", capability,
                tuple(sorted(demands[capability])),
            ))
    for technology in graph.nodes:
        if technology.kind == "technology" and technology not in outlet:
            findings.append(DefinitionCoverageFinding(
                "technology_without_declared_downstream_outlet", technology,
                (f"technology:{technology.id}:no_unlocked_method_or_downstream_prerequisite",),
            ))
    return tuple(sorted(findings, key=lambda row: (row.code, row.subject)))

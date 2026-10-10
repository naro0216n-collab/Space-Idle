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
    # These are Definition availability hints only. Scenario endowments,
    # previously installed assets, physical eligibility and actual allocation
    # cannot be inferred from graph edges.
    supplier_relations = {
        "capability": ("supplies_capability",),
        "resource": ("produces_resource", "extracts_resource", "external_buy_offer"),
        "service_capacity": (
            "nominal_service_supply", "nominal_power_supply",
            "nominal_research_execution", "nominal_construction_service_supply",
            "nominal_resource_construction_supply", "nominal_survey_service_supply",
            "nominal_life_support_supply",
        ),
        "facility": ("constructs_facility", "deploys_facility"),
        "vehicle": ("produces_vehicle",),
    }
    requirement_relations = {
        "capability": ("requires_capability", "requires_site_capability"),
        "resource": ("consumes_resource", "invests_resource"),
        "service_capacity": (
            "requires_service_capacity", "requires_execution_capacity",
            "requires_construction_work", "nominal_power_load",
        ),
    }
    missing_supply_codes = {
        "capability": "required_capability_without_definition_supplier",
        "resource": "resource_demand_without_registered_replenishment",
        "service_capacity": "service_demand_without_registered_capacity_supplier",
    }
    supplied: set[DependencyNode] = set()
    demands: dict[DependencyNode, set[str]] = defaultdict(set)
    outlets: dict[DependencyNode, set[str]] = defaultdict(set)
    retirement: set[DependencyNode] = set()
    for relation in graph.relations:
        for kind, relation_kinds in supplier_relations.items():
            if relation.kind in relation_kinds and relation.target.kind == kind:
                supplied.add(relation.target)
        for kind, relation_kinds in requirement_relations.items():
            if relation.kind in relation_kinds and relation.source.kind == kind:
                evidence = (relation.provenance if kind == "capability"
                            else f"{relation.kind}:{relation.provenance}")
                demands[relation.source].add(evidence)
        if relation.kind in ("unlocks_method", "technology_prerequisite") and relation.source.kind == "technology":
            outlets[relation.source].add(relation.provenance)
        if relation.kind == "decommissions_facility" and relation.source.kind == "facility":
            retirement.add(relation.source)
        if relation.kind == "retires_vehicle" and relation.source.kind == "vehicle":
            retirement.add(relation.source)
    findings: list[DefinitionCoverageFinding] = []
    for node, evidence in sorted(demands.items()):
        if node not in supplied:
            findings.append(DefinitionCoverageFinding(
                missing_supply_codes[node.kind], node, tuple(sorted(evidence)),
            ))
    for node in sorted(graph.nodes):
        if node.kind == "technology" and node not in outlets:
            findings.append(DefinitionCoverageFinding(
                "technology_without_declared_downstream_outlet", node,
                (f"technology:{node.id}:no_unlocked_method_or_downstream_prerequisite",),
            ))
        if node.kind not in ("facility", "vehicle"):
            continue
        if node not in supplied:
            findings.append(DefinitionCoverageFinding(
                f"{node.kind}_without_registered_acquisition_method", node,
                (f"{node.kind}:{node.id}:no_registered_production_or_deployment",),
            ))
        if node not in retirement:
            findings.append(DefinitionCoverageFinding(
                f"{node.kind}_without_registered_retirement_method", node,
                (f"{node.kind}:{node.id}:no_registered_retirement_or_decommission",),
            ))
    return tuple(sorted(findings, key=lambda row: (row.code, row.subject)))

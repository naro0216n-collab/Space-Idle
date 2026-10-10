"""Read-only coverage findings over the registered *definition* dependency graph.

These are possible authoring gaps, not physical feasibility verdicts. In particular,
a technology at the end of a DAG may deliberately have no downstream use yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict

from .analysis_graph import DependencyDefinitionGraph, DependencyNode
from .analysis_technology_outlets import classify_technology_outlets


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
        if relation.kind == "decommissions_facility" and relation.source.kind == "facility":
            retirement.add(relation.source)
        if relation.kind == "retires_vehicle" and relation.source.kind == "vehicle":
            retirement.add(relation.source)
    # A static DAG can be acyclic even though the only authored route to a
    # Research Stage's required physical capability needs that very Research.
    # Keep alternative suppliers (OR) separate from each method's combined
    # prerequisites (AND). This is an authoring risk, not an assertion about
    # installed Scenario assets or environmental eligibility.
    downstream_technologies: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    capability_suppliers: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    acquisitions: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    method_techs: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    research_stages: dict[DependencyNode, DependencyNode] = {}
    stage_capabilities: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    for relation in graph.relations:
        if relation.kind == "technology_prerequisite":
            downstream_technologies[relation.source].add(relation.target)
        elif relation.kind == "supplies_capability" and relation.source.kind in ("facility", "vehicle"):
            capability_suppliers[relation.target].add(relation.source)
        elif relation.kind in ("constructs_facility", "deploys_facility", "produces_vehicle"):
            if relation.target.kind in ("facility", "vehicle"):
                acquisitions[relation.target].add(relation.source)
        elif relation.kind == "unlocks_method" and relation.source.kind == "technology":
            method_techs[relation.target].add(relation.source)
        elif relation.kind == "research_stage" and relation.target.kind == "technology":
            research_stages[relation.source] = relation.target
        elif relation.kind == "requires_site_capability" and relation.target.kind == "research_stage":
            stage_capabilities[relation.target].add(relation.source)

    def dependent_technologies(technology: DependencyNode) -> set[DependencyNode]:
        # These methods cannot be acquired before the input Technology, even
        # when it is only an indirect prerequisite of their gate Technology.
        reached = {technology}
        pending = [technology]
        while pending:
            for later in downstream_technologies.get(pending.pop(), ()):
                if later not in reached:
                    reached.add(later)
                    pending.append(later)
        return reached

    bootstrap_risks: list[DefinitionCoverageFinding] = []
    for stage, capabilities in stage_capabilities.items():
        technology = research_stages.get(stage)
        if technology is None:
            continue
        dependent = dependent_technologies(technology)
        for capability in capabilities:
            providers = capability_suppliers.get(capability, set())
            methods = set().union(*(acquisitions.get(asset, set()) for asset in providers))
            # Missing suppliers or missing acquisition paths are reported by
            # their own coverage categories, not reinterpreted as a cycle.
            if (not providers or any(not acquisitions.get(asset) for asset in providers)
                    or not methods):
                continue
            if not all(method_techs.get(method, set()) & dependent for method in methods):
                continue
            bootstrap_risks.append(DefinitionCoverageFinding(
                "potential_research_acquisition_dependency_cycle", technology,
                tuple(sorted((
                    f"stage:{stage.id}:requires_capability:{capability.id}",
                    "scope:registered_definition_acquisition_only;initial_assets_and_sites_unknown",
                    *(f"supplier:{asset.kind}:{asset.id}"
                      for asset in providers),
                    *(f"method:{method.kind}:{method.id}:depends_on:"
                      + ",".join(sorted(gate.id for gate in method_techs[method] & dependent))
                      for method in methods),
                ))),
            ))
    findings: list[DefinitionCoverageFinding] = []
    for node, evidence in sorted(demands.items()):
        if node not in supplied:
            findings.append(DefinitionCoverageFinding(
                missing_supply_codes[node.kind], node, tuple(sorted(evidence)),
            ))
    # A Research prerequisite edge by itself is not a usable outlet. Reuse the
    # full typed Technology reachability projection, distinguishing a terminal
    # definition from a chain whose registered descendants also lack methods.
    # These are Content-scope gaps, never claims about technical importance.
    for outlet in classify_technology_outlets(graph):
        if outlet.classification not in ("no_downstream_outlet", "research_only_no_method"):
            continue
        code = ("technology_without_declared_downstream_outlet"
                if outlet.classification == "no_downstream_outlet"
                else "technology_research_chain_without_registered_method")
        findings.append(DefinitionCoverageFinding(code, outlet.technology, (
            "scope:registered_definition_methods_only;future_content_unknown",
            f"technology:{outlet.technology.id}:reachable_method_count:0",
            *(f"downstream_technology:{row.id}" for row in outlet.downstream_technologies),
        )))
    for node in sorted(graph.nodes):
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
    # An installed asset cannot provide the only service needed to construct
    # its *first* instance through every registered acquisition route.  This
    # check deliberately preserves method OR and requirement AND: one viable
    # alternative provider or one independent construction method avoids the
    # self-bootstrap finding.  Initial Scenario endowments and unregistered
    # external capabilities remain unknown, so this is authoring information,
    # never a present-state impossibility verdict.
    owned_assets = {node for node in graph.nodes if node.kind in ("facility", "vehicle")}
    physical_suppliers: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    method_inputs: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    supply_kinds = {
        "supplies_capability", "nominal_service_supply", "nominal_power_supply",
        "nominal_research_execution", "nominal_construction_service_supply",
        "nominal_resource_construction_supply", "nominal_survey_service_supply",
        "nominal_life_support_supply",
    }
    input_kinds = {
        "requires_capability", "requires_site_capability", "requires_service_capacity",
        "requires_execution_capacity", "requires_construction_work",
    }
    for relation in graph.relations:
        if relation.kind in supply_kinds and relation.target.kind in ("capability", "service_capacity"):
            physical_suppliers[relation.target].add(relation.source)
        elif (relation.kind in input_kinds and
              relation.source.kind in ("capability", "service_capacity")):
            method_inputs[relation.target].add(relation.source)
    for asset in sorted(owned_assets):
        methods = acquisitions.get(asset, set())
        if not methods:
            continue  # Missing acquisitions are already a separate finding.
        bottlenecks = {}
        for method in methods:
            # Resource-only or self-deploying pathways remain independent of
            # the installed physical service offered by this asset.
            self_required = [requirement for requirement in method_inputs.get(method, ())
                             if physical_suppliers.get(requirement) == {asset}]
            if not self_required:
                break
            bottlenecks[method] = self_required
        else:
            findings.append(DefinitionCoverageFinding(
                "potential_asset_self_bootstrap_dependency", asset,
                tuple(sorted((
                    "scope:registered_definition_acquisition_only;initial_assets_and_external_sources_unknown",
                    *(f"method:{method.kind}:{method.id}:requires:{requirement.kind}:{requirement.id}"
                      for method, requirements in bottlenecks.items() for requirement in requirements),
                ))),
            ))
    # The self-bootstrap test above is a useful local explanation, but a
    # closed acquisition dependency may span several assets: A requires a
    # Service from B, whose acquisition in turn requires A. Evaluate *methods*
    # as OR choices and their requirements as AND inputs. No authored source is
    # assumed to be an installed or active real-world provider here.
    #
    # Missing registered acquisition methods and unknown suppliers are treated
    # as possible external/Scenario starting conditions, not proof of a loop.
    # They already have distinct coverage findings when appropriate.
    independent = {asset for asset in owned_assets if not acquisitions.get(asset)}

    def requirement_has_source(requirement: DependencyNode) -> bool:
        suppliers = physical_suppliers.get(requirement)
        return not suppliers or any(
            supplier not in owned_assets or supplier in independent
            for supplier in suppliers
        )

    changed = True
    while changed:
        changed = False
        for asset in sorted(owned_assets - independent):
            if any(all(requirement_has_source(req)
                       for req in method_inputs.get(method, ()))
                   for method in acquisitions[asset]):
                independent.add(asset)
                changed = True

    unresolved = owned_assets - independent
    # An unresolved asset may merely *depend on* a cycle; only the members of
    # the actual strongly connected group are cycle candidates.
    adjacency: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    for asset in unresolved:
        for method in acquisitions[asset]:
            for req in method_inputs.get(method, ()):
                adjacency[asset].update(physical_suppliers.get(req, set()) & unresolved)

    # Tarjan SCC over definition dependencies, not an alternative Game Solver.
    sequence = 0
    indices: dict[DependencyNode, int] = {}
    lowlink: dict[DependencyNode, int] = {}
    stack: list[DependencyNode] = []
    on_stack: set[DependencyNode] = set()
    components: list[tuple[DependencyNode, ...]] = []

    def visit(node: DependencyNode) -> None:
        nonlocal sequence
        indices[node] = lowlink[node] = sequence
        sequence += 1
        stack.append(node)
        on_stack.add(node)
        for next_node in sorted(adjacency[node]):
            if next_node not in indices:
                visit(next_node)
                lowlink[node] = min(lowlink[node], lowlink[next_node])
            elif next_node in on_stack:
                lowlink[node] = min(lowlink[node], indices[next_node])
        if lowlink[node] == indices[node]:
            component = []
            while True:
                popped = stack.pop()
                on_stack.remove(popped)
                component.append(popped)
                if popped == node:
                    break
            components.append(tuple(sorted(component)))

    for asset in sorted(unresolved):
        if asset not in indices:
            visit(asset)
    for component in components:
        if len(component) < 2:
            continue  # Single-asset cases are covered by the self-bootstrap check.
        evidence = [
            "scope:registered_definition_acquisition_only;initial_assets_and_external_sources_unknown",
            *(f"member:{asset.kind}:{asset.id}" for asset in component),
        ]
        members = set(component)
        for asset in component:
            for method in sorted(acquisitions[asset]):
                for req in sorted(method_inputs.get(method, ())):
                    for supplier in sorted(physical_suppliers.get(req, set()) & members):
                        evidence.append(
                            f"method:{method.kind}:{method.id}:requires:"
                            f"{req.kind}:{req.id}:supplied_by:{supplier.kind}:{supplier.id}"
                        )
        findings.append(DefinitionCoverageFinding(
            "potential_asset_acquisition_dependency_cycle", component[0],
            tuple(sorted(set(evidence))),
        ))
    findings.extend(bootstrap_risks)
    return tuple(sorted(findings, key=lambda row: (row.code, row.subject, row.evidence)))

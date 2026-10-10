"""Read-only coverage findings over the registered *definition* dependency graph.

These are possible authoring gaps, not physical feasibility verdicts. In particular,
a technology at the end of a DAG may deliberately have no downstream use yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from collections.abc import Iterable

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


def inspect_definition_alternatives(graph: DependencyDefinitionGraph) -> tuple[DefinitionCoverageFinding, ...]:
    """Surface conditional, relation-level alternatives from *all* Contributors.

    This is not a semantic deduplicator. The graph may omit physical parameters,
    acquisition availability and actual finite Allocation. Never declare that
    two Definitions are interchangeable or silently delete one from Content.
    Both inbound requirements and outbound effects must be considered; comparing
    a method's outputs alone would erase important Player tradeoffs.
    """
    # World, geographical and resource identities are not competing authored
    # methods. All other registered Definition kinds participate without an
    # analyzer-specific list of future Facility / Provider / Vehicle IDs.
    contextual_kinds = {
        "resource", "capability", "service_capacity", "capacity_pool", "storage_pool",
        "site_condition", "spatial_classification", "body", "surface_cell",
        "spatial_node", "star_system", "survey_target", "survey_parameter",
        "survey_knowledge_level", "survey_reach_scope", "activity_kind",
        "experience_category", "research_point_pool", "opportunity_factor",
        "movement_parameter", "founding_parameter", "exploration_parameter",
    }
    # Exact multiset signatures, including quantity, unit, time and conditions.
    # Relation provenance is evidence of authorship, not a physical parameter;
    # omitting it allows separately-authored Definitions to be compared.
    signatures: dict[DependencyNode, list[tuple]] = defaultdict(list)
    for relation in graph.relations:
        attributes = (relation.kind, relation.quantity, relation.unit,
                      relation.time_basis, relation.condition)
        signatures[relation.source].append(("out", relation.target, *attributes))
        if relation.target != relation.source:
            signatures[relation.target].append(("in", relation.source, *attributes))

    def stable(rows: Iterable[tuple]) -> tuple:
        return tuple(sorted(rows, key=repr))

    candidates = [node for node in graph.nodes
                  if node.kind not in contextual_kinds and signatures[node]]
    groups: dict[tuple, list[DependencyNode]] = defaultdict(list)
    for node in candidates:
        groups[(node.kind, node.scope, stable(signatures[node]))].append(node)

    findings: list[DefinitionCoverageFinding] = []
    for nodes in groups.values():
        if len(nodes) < 2:
            continue
        for node in sorted(nodes):
            alternatives = sorted(other for other in nodes if other != node)
            relation_evidence = tuple(
                f"relation:{direction}:{kind}:{neighbor.kind}:{neighbor.id}:"
                f"{quantity}:{unit}:{time_basis}:{condition}"
                for direction, neighbor, kind, quantity, unit, time_basis, condition
                in stable(signatures[node])
            )
            findings.append(DefinitionCoverageFinding(
                "possible_equivalent_relation_contract", node,
                ("scope:all_registered_relations_only;unmodeled_physical_differences_unknown",
                 *(f"candidate:{other.kind}:{other.id}" for other in alternatives),
                 *relation_evidence),
            ))

    # An additional narrow Pareto check: a production Process that asks for no
    # less of any *identical* input but yields no more of any *identical* output
    # may be dominated. Every other authored relation must match exactly,
    # including eligibility, service and technology requirements. This is only
    # a candidate because installed throughput and current access vary.
    processes = sorted(node for node in candidates if node.kind == "process")
    nonflow: dict[DependencyNode, tuple] = {}
    flow: dict[DependencyNode, dict[str, dict[tuple, float]]] = {}
    for node in processes:
        inputs: dict[tuple, float] = {}
        outputs: dict[tuple, float] = {}
        fixed = []
        for row in signatures[node]:
            direction, neighbor, kind, quantity, unit, time_basis, condition = row
            if (kind == "consumes_resource" and direction == "in" and neighbor.kind == "resource"
                    or kind == "produces_resource" and direction == "out" and neighbor.kind == "resource"):
                bucket = inputs if direction == "in" else outputs
                key = (neighbor, unit, time_basis, condition)
                if quantity is None:
                    # An unspecified quantity cannot establish a yield comparison.
                    fixed.append(row)
                else:
                    bucket[key] = bucket.get(key, 0.0) + quantity
            else:
                fixed.append(row)
        nonflow[node] = stable(fixed)
        flow[node] = {"inputs": inputs, "outputs": outputs}

    for dominated in processes:
        possible_dominators = []
        for dominator in processes:
            if dominated == dominator or nonflow[dominated] != nonflow[dominator]:
                continue
            inferior_inputs = flow[dominated]["inputs"]
            superior_inputs = flow[dominator]["inputs"]
            inferior_outputs = flow[dominated]["outputs"]
            superior_outputs = flow[dominator]["outputs"]
            if (not inferior_outputs or inferior_inputs.keys() != superior_inputs.keys()
                    or inferior_outputs.keys() != superior_outputs.keys()):
                continue
            if (all(inferior_inputs[key] >= superior_inputs[key] for key in inferior_inputs)
                    and all(inferior_outputs[key] <= superior_outputs[key] for key in inferior_outputs)
                    and (any(inferior_inputs[key] > superior_inputs[key] for key in inferior_inputs)
                         or any(inferior_outputs[key] < superior_outputs[key] for key in inferior_outputs))):
                possible_dominators.append(dominator)
        if not possible_dominators:
            continue
        # One candidate finding per inferior option, even when multiple authored
        # methods have identical or better ratios. All witnesses remain visible.
        findings.append(DefinitionCoverageFinding(
            "possible_dominated_process", dominated,
            ("scope:registered_process_ratios_and_identical_nonflow_relations_only;"
             "installed_capacity_and_eligibility_unknown",
             *(f"possible_dominator:process:{node.id}" for node in possible_dominators),
             *(f"comparison:{dominator.id}:input:{key[0].id}:"
               f"{flow[dominated]['inputs'][key]:g}->{flow[dominator]['inputs'][key]:g}"
               for dominator in possible_dominators
               for key in sorted(flow[dominated]["inputs"])),
             *(f"comparison:{dominator.id}:output:{key[0].id}:"
               f"{flow[dominated]['outputs'][key]:g}->{flow[dominator]['outputs'][key]:g}"
               for dominator in possible_dominators
               for key in sorted(flow[dominated]["outputs"]))),
        ))
    return tuple(sorted(findings, key=lambda row: (row.code, row.subject, row.evidence)))


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
    # Definition acquisition and Research Stage prerequisites are analyzed
    # together below, without a separate capability-only Research solver.
    downstream_technologies: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    acquisitions: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    method_techs: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    research_stages: dict[DependencyNode, DependencyNode] = {}
    for relation in graph.relations:
        if relation.kind == "technology_prerequisite":
            downstream_technologies[relation.source].add(relation.target)
        elif relation.kind in ("constructs_facility", "deploys_facility", "produces_vehicle"):
            if relation.target.kind in ("facility", "vehicle"):
                acquisitions[relation.target].add(relation.source)
        elif relation.kind == "unlocks_method" and relation.source.kind == "technology":
            method_techs[relation.target].add(relation.source)
        elif relation.kind == "research_stage" and relation.target.kind == "technology":
            research_stages[relation.source] = relation.target

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
    # A registered extraction method can be awaiting future hardware. This is
    # authoring coverage, not an invalid reference or a claim that the Scenario
    # cannot operate. Physical compatibility comes from the same Graph edges
    # emitted for normal installed extraction capacity.
    extractable = {
        relation.target for relation in graph.relations
        if relation.kind == "nominal_extraction_capacity"
        and relation.source.kind == "facility"
        and relation.target.kind == "extraction_method"
    }
    for method in sorted(node for node in graph.nodes if node.kind == "extraction_method"):
        if method not in extractable:
            findings.append(DefinitionCoverageFinding(
                "extraction_method_without_registered_compatible_facility", method,
                ("scope:registered_physical_interface_only;future_facilities_unknown",),
            ))
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
    # A Research Provider or Life Support method describes a physical asset's
    # usable service, not a standalone source. The typed asset→method relation
    # is an OR of compatible real assets; leaving the intermediate method as
    # a "free" supplier conceals physical acquisition dependency cycles.
    service_asset_sources: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    for relation in graph.relations:
        if (relation.kind == "uses_asset_definition"
                and relation.source in owned_assets):
            service_asset_sources[relation.target].add(relation.source)
    for provider in sorted(node for node in graph.nodes
                           if node.kind in ("research_provider", "survey_provider")):
        if provider not in service_asset_sources:
            findings.append(DefinitionCoverageFinding(
                "provider_without_registered_compatible_asset", provider,
                ("scope:registered_definition_source_compatibility_only;"
                 "initial_assets_and_site_conditions_unknown",),
            ))
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
            physical_suppliers[relation.target].update(
                service_asset_sources.get(relation.source, {relation.source})
            )
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

    # A single read-only SCC projection serves both capability-only and
    # Resource-assisted authoring diagnostics; neither is a Game Solver.
    components = _strongly_connected_components(unresolved, adjacency)
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
    # Resource stock may be a prerequisite for its own first production
    # facility. A cycle across Resource production and Asset acquisition is
    # invisible to the service-only acquisition SCC above. This is still a
    # Definition diagnostic: it does not determine initial inventories,
    # actual Market eligibility, available sites, or technology progress.
    findings.extend(_resource_acquisition_cycles(
        graph, owned_assets, acquisitions, physical_suppliers, method_inputs,
        method_techs, downstream_technologies, research_stages,
    ))
    findings.extend(inspect_definition_alternatives(graph))
    return tuple(sorted(findings, key=lambda row: (row.code, row.subject, row.evidence)))


def _resource_acquisition_cycles(
    graph: DependencyDefinitionGraph,
    owned_assets: set[DependencyNode],
    acquisitions: dict[DependencyNode, set[DependencyNode]],
    physical_suppliers: dict[DependencyNode, set[DependencyNode]],
    method_inputs: dict[DependencyNode, set[DependencyNode]],
    method_techs: dict[DependencyNode, set[DependencyNode]],
    downstream_technologies: dict[DependencyNode, set[DependencyNode]],
    research_stages: dict[DependencyNode, DependencyNode],
) -> tuple[DefinitionCoverageFinding, ...]:
    """Find conditional Resource/Asset and Research supply acquisition cycles.

    Each acquisition/production method is an alternative (OR). Its physical
    input Resource/Capability/Service requirements must all have a possible
    source (AND). A Market buy offer is a conditional alternative; missing
    Definition sources remain unknown, not proof of initial impossibility.
    No Simulation eligibility, stock or allocation is computed here.
    """
    resource_nodes = {node for node in graph.nodes if node.kind == "resource"}
    relevant = owned_assets | resource_nodes
    producers: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    external_offers: set[DependencyNode] = set()
    inputs: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    extraction_assets: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    for relation in graph.relations:
        if relation.kind in ("produces_resource", "extracts_resource") and relation.target in resource_nodes:
            producers[relation.target].add(relation.source)
        elif relation.kind == "external_buy_offer" and relation.target in resource_nodes:
            external_offers.add(relation.target)
        elif relation.kind in ("consumes_resource", "invests_resource") and relation.source in resource_nodes:
            inputs[relation.target].add(relation.source)
        elif relation.kind == "nominal_extraction_capacity" and relation.source in owned_assets:
            extraction_assets[relation.target].add(relation.source)

    # An unregistered acquisition or replenishment route may have a Scenario
    # endowment or an external source, so its absence cannot close a cycle.
    possible_initial_sources = {asset for asset in owned_assets if not acquisitions.get(asset)}
    possible_initial_sources.update(resource for resource in resource_nodes
                                    if resource in external_offers or not producers.get(resource))

    def alternatives(requirement: DependencyNode) -> set[DependencyNode]:
        if requirement.kind == "resource":
            return {requirement}
        return physical_suppliers.get(requirement, set())

    def method_requirements(method: DependencyNode) -> tuple[set[DependencyNode], ...]:
        groups = [alternatives(req) for req in method_inputs.get(method, ())]
        groups.extend({resource} for resource in inputs.get(method, ()))
        if method in extraction_assets:
            groups.append(extraction_assets[method])
        return tuple(groups)

    def possible_supply_without(blocked_methods: set[DependencyNode]) -> set[DependencyNode]:
        # OR of registered acquisition/production methods, AND of each
        # method's finite physical prerequisites. This produces an authoring
        # reachability hint, not a runtime eligibility/stock prediction.
        independent = set(possible_initial_sources)

        def method_has_source(method: DependencyNode) -> bool:
            return method not in blocked_methods and all(not group or any(
                candidate not in relevant or candidate in independent
                for candidate in group
            ) for group in method_requirements(method))

        changed = True
        while changed:
            changed = False
            for asset in sorted(owned_assets - independent):
                if any(method_has_source(method) for method in acquisitions[asset]):
                    independent.add(asset)
                    changed = True
            for resource in sorted(resource_nodes - independent):
                if any(method_has_source(method) for method in producers[resource]):
                    independent.add(resource)
                    changed = True
        return independent

    independent = possible_supply_without(set())
    unresolved = relevant - independent
    adjacency: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    evidence_by_edge: dict[tuple[DependencyNode, DependencyNode], set[str]] = defaultdict(set)
    for node in unresolved:
        for method in sorted(acquisitions.get(node, set()) | producers.get(node, set())):
            for group in method_requirements(method):
                for supplier in group & unresolved:
                    adjacency[node].add(supplier)
                    evidence_by_edge[(node, supplier)].add(
                        f"method:{method.kind}:{method.id}:needs:{supplier.kind}:{supplier.id}"
                    )

    components = _strongly_connected_components(unresolved, adjacency)
    findings = []
    for component in components:
        members = set(component)
        if (not any(node.kind == "resource" for node in component)
                or len(component) == 1 and component[0] not in adjacency[component[0]]):
            continue
        evidence = {
            "scope:registered_definition_acquisition_and_production_only;"
            "initial_stock_assets_and_external_conditions_unknown",
            *(f"member:{node.kind}:{node.id}" for node in component),
        }
        for node in component:
            for supplier in adjacency[node] & members:
                evidence.update(evidence_by_edge[(node, supplier)])
        findings.append(DefinitionCoverageFinding(
            "potential_resource_acquisition_dependency_cycle", component[0],
            tuple(sorted(evidence)),
        ))
    # A Technology cannot rely on physical inputs whose only registered
    # production/acquisition methods require that same Technology (or one of
    # its successors). Check actual typed Research Stage inputs, keeping
    # optional Market, initial Scenario and unknown real-world availability
    # separate from a definite deadlock. No method is created or executed.
    stage_requirements: dict[DependencyNode, set[DependencyNode]] = defaultdict(set)
    for relation in graph.relations:
        if (relation.target in research_stages
                and relation.kind in (
                    "consumes_resource", "requires_execution_capacity", "requires_site_capability",
                    "requires_capability", "requires_service_capacity",
                )
                and relation.source.kind in ("resource", "service_capacity", "capability")):
            stage_requirements[relation.target].add(relation.source)

    def source_possible(requirement: DependencyNode, available: set[DependencyNode]) -> bool | None:
        if requirement in relevant:
            return requirement in available
        suppliers = physical_suppliers.get(requirement)
        if not suppliers:
            return None  # Undeclared/Context source, not a circular proof.
        return any(supplier not in relevant or supplier in available
                   for supplier in suppliers)

    for stage in sorted(stage_requirements):
        technology = research_stages[stage]
        dependent = {technology}
        pending = [technology]
        while pending:
            for later in downstream_technologies.get(pending.pop(), ()):
                if later not in dependent:
                    dependent.add(later)
                    pending.append(later)
        blocked = {method for method, gates in method_techs.items() if gates & dependent}
        if not blocked:
            continue
        allowed = possible_supply_without(blocked)
        for requirement in sorted(stage_requirements[stage]):
            if (source_possible(requirement, independent) is not True
                    or source_possible(requirement, allowed) is not False):
                continue
            findings.append(DefinitionCoverageFinding(
                "potential_research_supply_acquisition_cycle", technology,
                tuple(sorted((
                    "scope:registered_definition_research_and_production_only;"
                    "initial_stock_assets_sites_and_market_conditions_unknown",
                    f"stage:{stage.id}:requires:{requirement.kind}:{requirement.id}",
                    *(f"blocked_method:{method.kind}:{method.id}:requires:"
                      + ",".join(sorted(gate.id for gate in method_techs[method] & dependent))
                      for method in blocked),
                ))),
            ))
    return tuple(findings)


def _strongly_connected_components(
    nodes: set[DependencyNode], adjacency: dict[DependencyNode, set[DependencyNode]],
) -> tuple[tuple[DependencyNode, ...], ...]:
    """Deterministic SCCs for conditional, read-only Definition diagnostics."""
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

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return tuple(components)

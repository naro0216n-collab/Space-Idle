#!/usr/bin/env python3
"""Explicit offline export of registered Space-Idle Definition dependencies.

Run from the repo root: python scripts/analyze_definition_graph.py [--root kind:id]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from space_idle import build_game_application
from space_idle.analysis_graph import DependencyNode
from space_idle.analysis_coverage import inspect_definition_coverage
from space_idle.analysis_technology_outlets import classify_technology_outlets
from space_idle.composition.analysis_graph import build_definition_dependency_graph
from space_idle.analysis_observation import observe_state
from space_idle.shared import DefinitionId, SpatialNodeId


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Definition node as kind:id; omit for complete static graph")
    parser.add_argument("--reverse", action="store_true", help="Follow upstream dependencies of root")
    parser.add_argument("--state", action="store_true", help="Add a separate snapshot of domain-owned stocks and capacities")
    parser.add_argument("--coverage", action="store_true", help="Include informational authoring-coverage findings")
    parser.add_argument("--technology-outlets", action="store_true", help="Report direct and prerequisite-only technology paths to declared usable methods")
    parser.add_argument("--node", action="append", help="Restrict state observation to this operational node; repeatable")
    parser.add_argument("--resource", action="append", help="Restrict state observation to this Resource Definition; repeatable")
    args = parser.parse_args()
    app = build_game_application()
    graph = build_definition_dependency_graph(app._simulation, app._catalog)
    full_graph = graph
    if args.root:
        kind, sep, definition_id = args.root.partition(":")
        if not sep or not kind or not definition_id:
            parser.error("--root must be kind:id")
        root = DependencyNode(kind, definition_id)
        if root not in graph.nodes:
            parser.error(f"unknown Definition node: {args.root}")
        graph = graph.subset((root,), downstream=not args.reverse)
    if (args.node or args.resource) and not args.state:
        parser.error("--node and --resource require --state")
    result = graph.to_json_data()
    if args.coverage:
        result = {"definition_graph": result, "coverage_findings": [
            row.to_json_data() for row in inspect_definition_coverage(full_graph)
            if row.subject in graph.nodes
        ]}
    if args.technology_outlets:
        # Attach authored research identity and typed-stage metadata from the
        # canonical registered Definitions. These are not inferred graph effects.
        technologies = ({} if app._simulation.research is None else {
            str(key): definition for key, definition in app._simulation.research.definitions.items()
        })
        report = []
        for row in classify_technology_outlets(full_graph):
            if row.technology not in graph.nodes:
                continue
            data = row.to_json_data()
            definition = technologies.get(row.technology.id)
            if definition is not None:
                data["definition"] = {
                    "display_name": definition.display_name,
                    "category": definition.category,
                    "series": definition.series,
                    "progression_stage": definition.progression_stage,
                    "prerequisites": sorted(str(value) for value in definition.prerequisites),
                    "stage_types": [type(stage).__name__ for stage in definition.stage_specs],
                }
            report.append(data)
        if "definition_graph" not in result:
            result = {"definition_graph": result}
        result["technology_outlets"] = report
    if args.state:
        state = observe_state(
            app._simulation,
            operational_node_ids=(None if not args.node else frozenset(SpatialNodeId(value) for value in args.node)),
            resource_ids=(None if not args.resource else frozenset(DefinitionId(value) for value in args.resource)),
        )
        if args.coverage or args.technology_outlets:
            result["state_observation"] = state.to_json_data()
        else:
            result = {"definition_graph": result, "state_observation": state.to_json_data()}
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

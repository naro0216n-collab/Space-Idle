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
from space_idle.composition.analysis_graph import build_definition_dependency_graph
from space_idle.analysis_observation import observe_state
from space_idle.shared import DefinitionId, SpatialNodeId


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Definition node as kind:id; omit for complete static graph")
    parser.add_argument("--reverse", action="store_true", help="Follow upstream dependencies of root")
    parser.add_argument("--state", action="store_true", help="Add a separate snapshot of domain-owned stocks and capacities")
    parser.add_argument("--coverage", action="store_true", help="Include informational authoring-coverage findings")
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
    if args.state:
        state = observe_state(
            app._simulation,
            operational_node_ids=(None if not args.node else frozenset(SpatialNodeId(value) for value in args.node)),
            resource_ids=(None if not args.resource else frozenset(DefinitionId(value) for value in args.resource)),
        )
        if args.coverage:
            result["state_observation"] = state.to_json_data()
        else:
            result = {"definition_graph": result, "state_observation": state.to_json_data()}
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

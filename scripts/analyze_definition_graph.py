#!/usr/bin/env python3
"""Export typed registered Definition dependencies for quantitative balance analysis.

A relation shows an authored dependency, never executed Resource Flow,
physical availability or a separate eligibility verdict.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from space_idle.bootstrap import build_game_application_for_load
from space_idle.analysis_graph import DependencyNode
from space_idle.composition.analysis_graph import build_definition_dependency_graph


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', help='Definition node kind:id')
    parser.add_argument('--reverse', action='store_true', help='Trace upstream rather than downstream dependencies')
    args = parser.parse_args()
    if args.reverse and not args.root:
        parser.error('--reverse requires --root')
    app = build_game_application_for_load()
    graph = build_definition_dependency_graph(app._simulation, app._catalog)
    if args.root:
        kind, sep, identity = args.root.partition(':')
        if not sep or not kind or not identity:
            parser.error('--root must be kind:id')
        root = DependencyNode(kind, identity)
        if root not in graph.nodes:
            parser.error(f'unknown Definition node: {args.root}')
        graph = graph.subset((root,), downstream=not args.reverse)
    json.dump(graph.to_json_data(), sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
    print()


if __name__ == '__main__':
    main()

from __future__ import annotations

from typing import Any

from .domain import DomainExtension
from .validation_support import ValidationContext, require as _require


def validate_core_configuration(sim: Any, ctx: ValidationContext) -> None:
    nodes = ctx.nodes
    _require(sim.environment.graph is sim.graph, "simulation/environment spatial graph mismatch")
    _require(sim.facilities.environment is sim.environment, "facility/environment resolver mismatch")
    _require(sim.power.environment is sim.environment, "power/environment resolver mismatch")
    _require(sim.account.funds_musd >= 0, "negative initial account funds")
    for node_id, node in nodes.items():
        _require(node_id == node.id, f"spatial node key mismatch: {node_id}")
        _require(node.parent_id is None or node.parent_id in nodes, f"spatial node has unknown parent: {node_id}")
        sim.graph.lineage(node_id)
    for (node_id, facet_type), facet in sim.environment.static.facets.items():
        _require(node_id in nodes, f"environment facet references unknown location: {node_id}")
        _require(isinstance(facet, facet_type), f"environment facet type mismatch: {node_id}/{facet_type.__name__}")
    sim.environment.ordered_overlays()


def validate_core_runtime(sim: Any) -> None:
    _require(sim.day >= 0, "negative simulation day")
    _require(sim.account.funds_musd >= -1e-9, "negative account funds")
    _require(0 <= sim.pending_offline_game_days < 1.0 + 1e-9, "invalid pending offline fraction")


DOMAIN_EXTENSION = DomainExtension(
    "core", configuration_validator=validate_core_configuration, runtime_validator=validate_core_runtime
)

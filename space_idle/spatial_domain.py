from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec
from .validation_support import ValidationContext, require as _require


def capture(sim: Any) -> dict[str, Any]:
    return {"overlays": sim.environment.capture_overlay_state()}


def restore(sim: Any, data: dict[str, Any]) -> None:
    sim.environment.restore_overlay_state(data.get("overlays", []))


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    _require(sim.environment.graph is sim.graph, "simulation/environment spatial graph mismatch")
    for body_id, body in sim.graph.bodies.items():
        _require(body_id == body.id, f"celestial body key mismatch: {body_id}")
    for node_id, node in sim.graph.nodes.items():
        _require(node_id == node.id, f"spatial node key mismatch: {node_id}")
        _require(node.parent_id is None or node.parent_id in sim.graph.nodes,
                 f"spatial node has unknown parent: {node_id}")
        _require(node.body_id is None or node.body_id in sim.graph.bodies,
                 f"spatial node has unknown celestial body: {node_id}")
        sim.graph.lineage(node_id)
        sim.graph.environment_lineage(node_id)
    for (node_id, facet_type), facet in sim.environment.static.facets.items():
        _require(node_id in sim.graph.nodes, f"environment facet references unknown location: {node_id}")
        _require(isinstance(facet, facet_type), f"environment facet type mismatch: {node_id}/{facet_type.__name__}")
    sim.environment.ordered_overlays()


STATE_CODEC = StateCodec("environment", capture, restore)
DOMAIN_EXTENSION = DomainExtension(
    "spatial", state_codec=STATE_CODEC, configuration_validator=validate_configuration
)

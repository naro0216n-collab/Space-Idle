from __future__ import annotations

from typing import Any

from .domain import DomainExtension, StateCodec, decode_float, decode_int, decode_list, decode_str, require_fields
from .exploration_models import KnowledgeLevel
from .shared import DefinitionId, SurfaceCellId
from .validation_support import require as _require


def capture_surface_knowledge(sim: Any) -> dict[str, Any]:
    return {
        "knowledge_progress": [
            {"cell_id": str(cell), "resource_id": str(res), "progress": progress}
            for (cell, res), progress in sorted(
                sim.surface_knowledge.knowledge_progress.items(),
                key=lambda x: (str(x[0][0]), str(x[0][1])),
            )
        ],
        "knowledge_precision_fraction": [
            {"cell_id": str(cell), "resource_id": str(res), "precision_fraction": precision}
            for (cell, res), precision in sorted(
                sim.surface_knowledge.knowledge_precision_fraction.items(),
                key=lambda x: (str(x[0][0]), str(x[0][1])),
            )
        ],
        "observed_presence_probability": [
            {"cell_id": str(cell), "resource_id": str(res), "probability": probability}
            for (cell, res), probability in sorted(
                sim.surface_knowledge.observed_presence_probability.items(),
                key=lambda x: (str(x[0][0]), str(x[0][1])),
            )
        ],
        "estimated_potential": [
            {"cell_id": str(cell), "resource_id": str(res), "estimated_potential": estimate}
            for (cell, res), estimate in sorted(
                sim.surface_knowledge.estimated_potential.items(),
                key=lambda x: (str(x[0][0]), str(x[0][1])),
            )
        ],
        "environment_observation_fingerprints": [
            {"cell_id": str(cell), "fingerprint": value}
            for cell, value in sorted(sim.surface_knowledge.environment_observation_fingerprints.items())
        ],
        "cell_attribute_levels": [
            {"cell_id": str(cell), "attribute": attribute, "level": level}
            for (cell, attribute), level in sorted(sim.surface_knowledge.cell_attribute_levels.items())
        ],
    }

def _restore_knowledge_map(
    value: Any, metric_field: str, metric_label: str
) -> dict[tuple[SurfaceCellId, DefinitionId], float]:
    fields = {"cell_id", "resource_id", metric_field}
    restored: dict[tuple[SurfaceCellId, DefinitionId], float] = {}
    for index, raw in enumerate(decode_list(value, f"knowledge {metric_label}")):
        row = require_fields(raw, fields, f"knowledge {metric_label}[{index}]")
        key = (
            SurfaceCellId(decode_str(row["cell_id"], "knowledge cell_id")),
            DefinitionId(decode_str(row["resource_id"], "knowledge resource_id")),
        )
        if key in restored:
            raise ValueError(f"duplicate knowledge {metric_label} key: {key}")
        restored[key] = decode_float(row[metric_field], f"knowledge {metric_label}")
    return restored


def restore_surface_knowledge(sim: Any, data: dict[str, Any]) -> None:
    knowledge = sim.surface_knowledge
    knowledge.knowledge_progress = _restore_knowledge_map(data["knowledge_progress"], "progress", "progress")
    knowledge.knowledge_precision_fraction = _restore_knowledge_map(data["knowledge_precision_fraction"], "precision_fraction", "precision_fraction")
    knowledge.estimated_potential = _restore_knowledge_map(data["estimated_potential"], "estimated_potential", "estimated_potential")
    knowledge.observed_presence_probability = _restore_knowledge_map(
        data["observed_presence_probability"], "probability", "presence_probability"
    )
    knowledge.environment_observation_fingerprints.clear()
    for index, raw in enumerate(decode_list(data["environment_observation_fingerprints"], "observed environment fingerprints")):
        row = require_fields(raw, {"cell_id", "fingerprint"}, f"environment fingerprint[{index}]")
        cell_id = SurfaceCellId(decode_str(row["cell_id"], "environment fingerprint cell id"))
        if cell_id in knowledge.environment_observation_fingerprints:
            raise ValueError(f"duplicate environment fingerprint: {cell_id}")
        knowledge.environment_observation_fingerprints[cell_id] = decode_str(row["fingerprint"], "environment fingerprint")
    knowledge.cell_attribute_levels.clear()
    for index, raw in enumerate(decode_list(data["cell_attribute_levels"], "knowledge cell attributes")):
        row = require_fields(raw, {"cell_id", "attribute", "level"}, f"knowledge cell attribute[{index}]")
        key = (SurfaceCellId(decode_str(row["cell_id"], "knowledge cell id")), decode_str(row["attribute"], "knowledge attribute"))
        if key in knowledge.cell_attribute_levels:
            raise ValueError(f"duplicate observed Cell attribute: {key}")
        knowledge.cell_attribute_levels[key] = decode_int(row["level"], "knowledge level")


def validate_surface_knowledge_configuration(sim: Any, ctx: Any) -> None:
    _require(sim.surface_knowledge is not None, "surface knowledge service required")
    _require(sim.surface_knowledge.graph is sim.graph, "surface knowledge must use World truth")
    _require(sim.survey.knowledge is sim.surface_knowledge, "Survey must report to Knowledge owner")
    _require(sim.survey.targets is sim.surface_knowledge.targets, "Survey targets must be canonical Knowledge targets")


def validate_surface_knowledge_runtime(sim: Any) -> None:
    for key, progress in sim.surface_knowledge.knowledge_progress.items():
        _require(key in sim.surface_knowledge.targets, f"knowledge references unknown survey target: {key}")
        _require(progress >= -1e-9, f"negative survey knowledge progress: {key}")
        if key in sim.surface_knowledge.targets:
            _require(progress <= sim.surface_knowledge.targets[key].thresholds[-1] + 1e-8, f"survey knowledge exceeds final threshold: {key}")
    for key, precision in sim.surface_knowledge.knowledge_precision_fraction.items():
        _require(key in sim.surface_knowledge.targets, f"survey precision references unknown target: {key}")
        _require(0.0 <= precision <= 1.0, f"survey precision outside 0..1: {key}")
        _require(sim.surface_knowledge.knowledge_level(*key) >= KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL, f"survey precision exists before estimated knowledge: {key}")
    for key, probability in sim.surface_knowledge.observed_presence_probability.items():
        _require(key in sim.surface_knowledge.targets, f"presence observation references unknown target: {key}")
        level = sim.surface_knowledge.knowledge_level(*key)
        _require(KnowledgeLevel.PRESENCE_PROBABILITY <= level < KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL,
                 f"presence observation stored at invalid Knowledge Level: {key}")
        _require(0.0 <= probability <= 1.0, f"presence probability outside 0..1: {key}")
    for key, estimate in sim.surface_knowledge.estimated_potential.items():
        _require(key in sim.surface_knowledge.targets, f"survey estimate references unknown target: {key}")
        _require(estimate >= 0.0, f"negative survey estimated potential: {key}")
        _require(sim.surface_knowledge.knowledge_level(*key) >= KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL, f"survey estimate exists before estimated knowledge: {key}")
    # Unobserved targets have no mutable knowledge state to validate.
    # Check the sparse authoritative set, not the entire static World grid
    # on every game day.
    for key in sim.surface_knowledge.knowledge_progress:
        level = sim.surface_knowledge.knowledge_level(*key)
        if KnowledgeLevel.PRESENCE_PROBABILITY <= level < KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL:
            _require(key in sim.surface_knowledge.observed_presence_probability,
                     f"Knowledge evidence missing presence observation: {key}")
        if level >= KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL:
            _require(
                key in sim.surface_knowledge.knowledge_precision_fraction,
                f"Survey Knowledge lacks uncertainty/precision metadata: {key}",
            )
        if level is KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL:
            _require(
                key in sim.surface_knowledge.estimated_potential,
                f"estimated Survey Knowledge lacks an estimated potential value: {key}",
            )
    for cell_id, fingerprint in sim.surface_knowledge.environment_observation_fingerprints.items():
        _require(cell_id in sim.graph.surface_cells, f"environment evidence references missing Cell: {cell_id}")
        _require(len(fingerprint) == 64 and all(c in '0123456789abcdef' for c in fingerprint),
                 f"invalid environment observation fingerprint: {cell_id}")
        _require((cell_id, 'environment') in sim.surface_knowledge.cell_attribute_levels,
                 f"environment evidence has no observed attribute: {cell_id}")
    for (cell_id, attr), level in sim.surface_knowledge.cell_attribute_levels.items():
        _require(cell_id in sim.graph.surface_cells, f"observed attribute references missing Cell: {cell_id}")
        _require(attr in ("terrain", "environment", "geology"), f"invalid observed attribute: {attr}")
        _require(type(level) is int and level in (1, 2), f"invalid observation level: {cell_id}/{attr}")
        if attr == 'environment' and sim.surface_knowledge.environment is not None:
            _require(cell_id in sim.surface_knowledge.environment_observation_fingerprints,
                     f"environment observation lacks physical evidence identity: {cell_id}")


DOMAIN_EXTENSION = DomainExtension(
    "surface_knowledge", state_codec=StateCodec("surface_knowledge", capture_surface_knowledge, restore_surface_knowledge),
    configuration_validator=validate_surface_knowledge_configuration,
    runtime_validator=validate_surface_knowledge_runtime,
)

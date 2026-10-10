"""Typed experiment inputs applied before composing each independent Simulation.

Allowed fields correspond to real authored Definitions, not a list of familiar
Content IDs. The regular Composition validator rejects broken references.
"""
from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Mapping, Sequence

from .catalog import GameCatalog
from .scenario import ScenarioDefinition, ScenarioInventoryStock, ScenarioFleet, ScenarioStorageInfrastructure, ScenarioPopulation
from .shared import DefinitionId, SpatialNodeId
from .simulation import Simulation


def _finite_nonnegative(value: object) -> float:
    if type(value) not in (float, int) or not isfinite(value) or value < 0:
        raise ValueError("variant quantity must be finite and nonnegative")
    return float(value)


def scenario_variant(base: ScenarioDefinition, changes: Mapping) -> ScenarioDefinition:
    """Override or append typed initial assets; no mutations of running Game State."""
    if not changes:
        return base
    allowed = {"inventory_stock", "fleet", "storage_infrastructure", "initial_population",
               "completed_technologies", "funds_balance_musd", "operational_node_ids"}
    if set(changes) - allowed:
        raise ValueError(f"unknown Scenario variant fields: {sorted(set(changes) - allowed)}")
    updated = {}
    for name in ("inventory_stock", "fleet", "storage_infrastructure", "initial_population"):
        if name not in changes:
            continue
        definitions = {
            "inventory_stock": (ScenarioInventoryStock, ("operational_node_id", "resource_id"), "amount_t"),
            "fleet": (ScenarioFleet, ("operational_node_id", "vehicle_definition_id"), "units"),
            "storage_infrastructure": (ScenarioStorageInfrastructure, ("operational_node_id", "storage_pool_key"), "amount_t"),
            "initial_population": (ScenarioPopulation, ("operational_node_id",), "count"),
        }
        klass, key_fields, quantity_field = definitions[name]
        rows = list(getattr(base, name))
        for raw in changes[name]:
            if set(raw) != set(key_fields) | {quantity_field}:
                raise ValueError(f"invalid {name} row fields")
            data = dict(raw)
            for key in key_fields:
                if key == "resource_id" or key == "vehicle_definition_id":
                    data[key] = DefinitionId(str(data[key]))
                elif key == "operational_node_id":
                    data[key] = SpatialNodeId(str(data[key]))
                elif not isinstance(data[key], str):
                    raise ValueError(f"invalid {name} key {key}")
            quantity = _finite_nonnegative(data[quantity_field])
            if quantity_field in ("units", "count"):
                if not quantity.is_integer():
                    raise ValueError(f"{quantity_field} must be an integer")
                data[quantity_field] = int(quantity)
            else:
                data[quantity_field] = quantity
            replacement = klass(**data)
            rows = [row for row in rows if tuple(getattr(row, key) for key in key_fields)
                    != tuple(getattr(replacement, key) for key in key_fields)]
            rows.append(replacement)
        updated[name] = tuple(sorted(rows, key=lambda row: tuple(str(getattr(row, key)) for key in key_fields)))
    if "funds_balance_musd" in changes:
        updated["funds_balance_musd"] = _finite_nonnegative(changes["funds_balance_musd"])
    if "operational_node_ids" in changes:
        new_nodes = changes["operational_node_ids"]
        if not isinstance(new_nodes, list) or any(not isinstance(row, str) for row in new_nodes):
            raise ValueError("operational_node_ids must be a list of stable IDs")
        updated["operational_node_ids"] = tuple(sorted(
            set(base.operational_node_ids) | {SpatialNodeId(node) for node in new_nodes}
        ))
    if "completed_technologies" in changes:
        technologies = changes["completed_technologies"]
        if not isinstance(technologies, list) or len(set(technologies)) != len(technologies):
            raise ValueError("completed_technologies must be a unique list")
        updated["completed_technologies"] = tuple(DefinitionId(id) for id in technologies)
    return replace(base, **updated)


def apply_content_variant(sim: Simulation, catalog: GameCatalog, changes: Sequence[Mapping]) -> None:
    """Edit typed method attributes before validation, without Core ID branching.

    Content IDs are runtime data used as lookup keys. The enum-like kind field
    identifies the owning Definition collection rather than a special asset.
    """
    del catalog
    for change in changes:
        kind = change.get("kind")
        definition_id = DefinitionId(str(change["id"]))
        field_name = change.get("field")
        value = change.get("value")
        if kind == "process" and field_name in ("inputs_per_day", "outputs_per_day"):
            process = sim.industry.processes[definition_id]
            resource_id = DefinitionId(str(change["resource_id"]))
            amounts = dict(getattr(process, field_name))
            amounts[resource_id] = _finite_nonnegative(value)
            sim.industry.processes[definition_id] = replace(process, **{field_name: amounts})
        elif kind == "facility" and field_name in (
            "maintenance_fraction_per_year", "process_throughput_per_day",
            "extraction_capacity_t_per_day", "housing_capacity"
        ):
            definition = sim.facilities.definitions[definition_id]
            if field_name == "housing_capacity":
                if type(value) is not int or value < 0:
                    raise ValueError("housing_capacity must be a nonnegative integer")
            else:
                value = _finite_nonnegative(value)
            sim.facilities.definitions[definition_id] = replace(definition, **{field_name: value})
        elif kind == "power" and field_name in ("load_mw", "standby_load_mw", "generation_mw"):
            spec = sim.power.specs[definition_id]
            amount = _finite_nonnegative(value)
            if field_name == "generation_mw":
                from .power import FixedGeneration, SolarGeneration
                model = spec.generation
                if isinstance(model, FixedGeneration):
                    spec = replace(spec, generation=replace(model, mw=amount))
                elif isinstance(model, SolarGeneration):
                    spec = replace(spec, generation=replace(model, rated_mw_at_reference_flux=amount))
                else:
                    raise ValueError("selected Power definition does not generate power")
            else:
                spec = replace(spec, **{field_name: amount})
            sim.power.specs[definition_id] = spec
        elif kind == "storage_provider" and field_name == "capacity_t_by_pool":
            spec = sim.storage.providers[definition_id]
            key = str(change["pool_key"])
            amounts = dict(spec.capacity_t_by_pool)
            amounts[key] = _finite_nonnegative(value)
            sim.storage.providers[definition_id] = replace(spec, capacity_t_by_pool=amounts)
        elif kind == "research_theory_stage" and field_name == "research_point_cost":
            from .research_models import ResearchTheoryStageSpec
            if sim.research is None:
                raise ValueError("Research Domain not available")
            definition = sim.research.definitions[definition_id]
            stage_id = str(change["stage_id"])
            amount = _finite_nonnegative(value)
            stages = []
            found = False
            for stage in definition.stage_specs:
                if stage.stage_id == stage_id:
                    if not isinstance(stage, ResearchTheoryStageSpec):
                        raise ValueError("research cost variant requires a Theory stage")
                    stage = replace(stage, research_point_cost=amount)
                    found = True
                stages.append(stage)
            if not found:
                raise ValueError("unrecognized Research stage ID")
            sim.research.definitions[definition_id] = replace(definition, stage_specs=tuple(stages))
        elif kind in ("process", "research", "construction") and field_name == "prerequisite_technologies":
            if not isinstance(value, list) or any(not isinstance(row, str) for row in value):
                raise ValueError("prerequisite_technologies must be a list of Definition IDs")
            prerequisites = frozenset(DefinitionId(row) for row in value)
            if len(prerequisites) != len(value):
                raise ValueError("duplicate prerequisite technologies")
            if kind == "process":
                domain = sim.industry.processes
                domain[definition_id] = replace(domain[definition_id], prerequisite_technologies=prerequisites)
            elif kind == "research":
                if sim.research is None:
                    raise ValueError("Research Domain not available")
                domain = sim.research.definitions
                domain[definition_id] = replace(domain[definition_id], prerequisites=prerequisites)
            else:
                domain = sim.projects.recipes
                domain[definition_id] = replace(domain[definition_id], prerequisite_technologies=prerequisites)
        elif kind == "spaceflight_movement_rule" and field_name in (
            "minimum_transit_days", "characteristic_speed_km_per_day"
        ):
            if field_name == "minimum_transit_days" and (type(value) is not int or value <= 0):
                raise ValueError("minimum_transit_days must be a positive integer")
            if field_name != "minimum_transit_days" and _finite_nonnegative(value) <= 0:
                raise ValueError("characteristic speed must be positive")
            found = False
            rules = []
            for rule in sim.transport.spaceflight_movement_rules:
                if rule.id == definition_id:
                    found = True
                    rule = replace(rule, **{field_name: value})
                rules.append(rule)
            if not found:
                raise ValueError(f"unknown spaceflight movement rule {definition_id}")
            sim.transport.spaceflight_movement_rules = tuple(rules)
            sim.transport.invalidate_movement_plans()
        else:
            raise ValueError(f"unsupported typed Content variant: {kind}.{field_name}")

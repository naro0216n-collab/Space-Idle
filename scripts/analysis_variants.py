"""Typed experiment inputs applied before composing each independent Simulation.

Allowed fields correspond to real authored Definitions, not a list of familiar
Content IDs. The regular Composition validator rejects broken references.
"""
from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Mapping, Sequence

from space_idle.catalog import GameCatalog
from space_idle.scenario import ScenarioDefinition, ScenarioInventoryStock, ScenarioFleet, ScenarioStorageInfrastructure, ScenarioPopulation, ScenarioFacility
from space_idle.shared import DefinitionId, SpatialNodeId, SurfaceCellId
from space_idle.simulation import Simulation


def _finite_nonnegative(value: object) -> float:
    if type(value) not in (float, int) or not isfinite(value) or value < 0:
        raise ValueError("variant quantity must be finite and nonnegative")
    return float(value)


def scenario_variant(base: ScenarioDefinition, changes: Mapping) -> ScenarioDefinition:
    """Override or append typed initial assets; no mutations of running Game State."""
    if not changes:
        return base
    allowed = {"inventory_stock", "fleet", "storage_infrastructure", "initial_population", "facilities",
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
    if "facilities" in changes:
        # Facilities have no authored per-instance key: two identical installed
        # assets may coexist at one Site. Replace the complete starting set
        # rather than ambiguously upserting by Definition or assigning IDs.
        raw_rows = changes["facilities"]
        if not isinstance(raw_rows, list):
            raise ValueError("facilities must be a complete list of initial assets")
        facilities = []
        for raw in raw_rows:
            if not isinstance(raw, Mapping) or set(raw) - {
                "definition_id", "operational_node_id", "site_cell_id", "invested_resources"
            } or not {"definition_id", "operational_node_id"} <= set(raw):
                raise ValueError("invalid facilities row fields")
            site = raw.get("site_cell_id")
            if site is not None and not isinstance(site, str):
                raise ValueError("site_cell_id must be a surface Cell ID or null")
            investments = raw.get("invested_resources", [])
            if not isinstance(investments, list):
                raise ValueError("invested_resources must be a list")
            invested = []
            for investment in investments:
                if not isinstance(investment, list) or len(investment) != 2 or not isinstance(investment[0], str):
                    raise ValueError("invested_resources must contain [resource ID, quantity] pairs")
                invested.append((DefinitionId(investment[0]), _finite_nonnegative(investment[1])))
            if len({resource for resource, _ in invested}) != len(invested):
                raise ValueError("duplicate investment resource")
            facilities.append(ScenarioFacility(
                DefinitionId(str(raw["definition_id"])),
                SpatialNodeId(str(raw["operational_node_id"])),
                None if site is None else SurfaceCellId(site),
                tuple(invested),
            ))
        updated["facilities"] = tuple(facilities)
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


def _definition_fields(value: object, required: set[str], optional: set[str], label: str) -> Mapping:
    if not isinstance(value, Mapping) or not required <= set(value) or set(value) - required - optional:
        raise ValueError(f"invalid {label} definition fields")
    return value


def _identifiers(raw: object, label: str) -> frozenset[str]:
    if not isinstance(raw, list) or any(not isinstance(value, str) or not value for value in raw):
        raise ValueError(f"{label} must be a list of nonempty identifiers")
    if len(set(raw)) != len(raw):
        raise ValueError(f"duplicate {label}")
    return frozenset(raw)


def _definition_ids(raw: object, label: str) -> frozenset[DefinitionId]:
    return frozenset(map(DefinitionId, _identifiers(raw, label)))


def _resource_amounts(raw: object, label: str) -> dict[DefinitionId, float]:
    if not isinstance(raw, Mapping) or any(not isinstance(key, str) or not key for key in raw):
        raise ValueError(f"{label} must map Resource IDs to quantities")
    return {DefinitionId(key): _finite_nonnegative(amount) for key, amount in raw.items()}


def _authored_research_site(raw: object):
    """Decode authored typed Site conditions; never infer them from Stage names."""
    from space_idle.site import (
        CapabilityRequirement, CapabilityRequirementState, SiteRequirements,
        SpatialClassification, SpatialClassificationRequirement,
    )

    site = _definition_fields(raw, set(), {"capabilities", "spatial_classifications"}, "site requirements")
    capabilities = site.get("capabilities", [])
    classifications = site.get("spatial_classifications", [])
    if not isinstance(capabilities, list) or not isinstance(classifications, list):
        raise ValueError("site requirements must contain typed lists")
    required_capabilities = []
    for capability in capabilities:
        item = _definition_fields(capability, {"capability_id", "required_state"}, set(), "capability")
        if not isinstance(item["capability_id"], str) or not item["capability_id"]:
            raise ValueError("site capability must identify a nonempty capability")
        required_capabilities.append(CapabilityRequirement(
            item["capability_id"], CapabilityRequirementState(item["required_state"]),
        ))
    required_classifications = []
    for classification in classifications:
        item = _definition_fields(
            classification, {"classification", "code", "description"}, set(), "spatial classification",
        )
        if not isinstance(item["code"], str) or not item["code"] or not isinstance(item["description"], str) or not item["description"]:
            raise ValueError("spatial classification requires authored blocker code and description")
        required_classifications.append(SpatialClassificationRequirement(
            SpatialClassification(item["classification"]), item["code"], item["description"],
        ))
    return SiteRequirements(
        capability_requirements=tuple(required_capabilities),
        spatial_classification_requirements=tuple(required_classifications),
    )


def _authored_research_execution(raw: object):
    """Retain real finite Service scope when a Research Stage requests it."""
    from space_idle.execution_requirements import ServiceCapacityRequirement
    from space_idle.service_capacity import ServiceCapacityScope

    if not isinstance(raw, list):
        raise ValueError("research execution requirements must be a typed list")
    requirements = []
    for requirement in raw:
        item = _definition_fields(
            requirement, {"service_type", "amount_per_execution", "scope"}, set(),
            "research service requirement",
        )
        requirements.append(ServiceCapacityRequirement(
            item["service_type"], _finite_nonnegative(item["amount_per_execution"]),
            scope=ServiceCapacityScope(item["scope"]),
        ))
    return tuple(requirements)


def _new_research_stages(raw: object) -> tuple:
    from space_idle.research_models import (
        ResearchTheoryStageSpec, ResearchPrototypeStageSpec,
        ResearchDemonstrationStageSpec, ResearchOperationalExperienceStageSpec,
    )
    if not isinstance(raw, list) or not raw:
        raise ValueError("research stage_specs must be a nonempty list")
    stages = []
    for stage in raw:
        if not isinstance(stage, Mapping):
            raise ValueError("research stage must be a typed object")
        stage_type = stage.get("stage_type")
        stage_id = stage.get("stage_id")
        if not isinstance(stage_id, str) or not stage_id:
            raise ValueError("research stage requires a nonempty stage_id")
        if stage_type == "theory":
            _definition_fields(stage, {"stage_id", "stage_type", "research_point_cost"}, set(), "Theory stage")
            stages.append(ResearchTheoryStageSpec(stage_id, _finite_nonnegative(stage["research_point_cost"])))
        elif stage_type in ("prototype", "demonstration"):
            required = {"stage_id", "stage_type", "required_work", "site_requirements"}
            if stage_type == "prototype":
                required.add("resources")
            _definition_fields(stage, required, {"execution_requirements"}, stage_type + " stage")
            site_requirements = _authored_research_site(stage["site_requirements"])
            work = _finite_nonnegative(stage["required_work"])
            execution = _authored_research_execution(stage.get("execution_requirements", []))
            if stage_type == "prototype":
                stages.append(ResearchPrototypeStageSpec(
                    stage_id, _resource_amounts(stage["resources"], "prototype resources"),
                    site_requirements, execution, required_work=work,
                ))
            else:
                stages.append(ResearchDemonstrationStageSpec(stage_id, work, site_requirements, execution))
        elif stage_type == "operational_experience":
            _definition_fields(stage, {"stage_id", "stage_type", "requirements"}, set(), "Experience stage")
            requirements = stage["requirements"]
            if not isinstance(requirements, Mapping) or any(not isinstance(key, str) or not key for key in requirements):
                raise ValueError("experience requirements must be keyed by category")
            stages.append(ResearchOperationalExperienceStageSpec(
                stage_id, {key: _finite_nonnegative(value) for key, value in requirements.items()},
            ))
        else:
            raise ValueError(f"unknown Research Stage type: {stage_type}")
    return tuple(stages)


def _owned_definition_collections(sim: Simulation) -> dict[str, tuple[dict, str | None]]:
    """Locate authored definitions at their real Domain owner, not in a test catalog.

    These are the existing Composition collections. Experiment membership edits
    must be followed by ordinary configuration/reference validation, never by
    synthetic access to runtime State or an experiment-only Content registry.
    """
    collections = {
        "facility": (sim.facilities.definitions, "id"),
        "vehicle": (sim.transport.vehicle_defs, "id"),
        "construction": (sim.projects.recipes, "facility_def_id"),
        "decommission": (sim.projects.decommission_recipes, "facility_def_id"),
        "power": (sim.power.specs, None),
        "storage_provider": (sim.storage.providers, "facility_def_id"),
    }
    if sim.research is not None:
        collections["research_provider"] = (sim.research.providers, "id")
    if sim.survey is not None:
        collections["survey_provider"] = (sim.survey.providers, "id")
    if sim.extraction is not None:
        collections["extraction"] = (sim.extraction.specs, "id")
    return collections


def _change_owned_definition(sim: Simulation, change: Mapping) -> None:
    """Copy an existing typed definition under a new ID before Scenario creation.

    Cloning is an explicit authoring operation for independent experiments,
    not an alias in the game. Related acquisition/retirement methods must be
    cloned separately, and regular validators reject invalid compositions.
    """
    action, kind = change.get("operation"), change.get("kind")
    collections = _owned_definition_collections(sim)
    if kind not in collections:
        raise ValueError(f"unsupported Content Definition kind: {kind}")
    definitions, identity_field = collections[kind]
    raw_id = change.get("id")
    if not isinstance(raw_id, str) or not raw_id:
        raise ValueError("Content Definition requires a nonempty ID")
    definition_id = DefinitionId(raw_id)
    if action == "remove":
        if set(change) != {"operation", "kind", "id"}:
            raise ValueError("Definition removal accepts only operation, kind and id")
        if definition_id not in definitions:
            raise ValueError(f"cannot remove unknown {kind} Definition: {definition_id}")
        del definitions[definition_id]
    elif action == "add":
        if set(change) != {"operation", "kind", "id", "source_id"}:
            raise ValueError("typed Definition copy requires operation, kind, id and source_id")
        source_id = change["source_id"]
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("Definition source_id must be a nonempty ID")
        if definition_id in definitions:
            raise ValueError(f"duplicate {kind} Definition ID: {definition_id}")
        source = definitions.get(DefinitionId(source_id))
        if source is None:
            raise ValueError(f"unknown {kind} source Definition: {source_id}")
        definitions[definition_id] = (replace(source, **{identity_field: definition_id})
                                      if identity_field is not None else replace(source))
    else:
        raise ValueError(f"unknown Content variant operation: {action}")
    if kind == "vehicle":
        sim.transport.invalidate_movement_plans()


def _change_definition_membership(sim: Simulation, catalog: GameCatalog, change: Mapping) -> None:
    """Author typed Content additions/deletions in a fresh pre-Scenario composition.

    No live State is migrated. The normal Composition, graph, and Scenario
    validators determine whether a removed Definition still has dependents.
    """
    from space_idle.catalog import ResourceDef
    from space_idle.production.models import ProcessSpec
    from space_idle.research_models import ResearchDefinition

    action = change.get("operation")
    kind = change.get("kind")
    if kind in _owned_definition_collections(sim):
        _change_owned_definition(sim, change)
        return
    if kind == "resource":
        definitions = catalog.resources
    elif kind == "process":
        definitions = sim.industry.processes
    elif kind == "research" and sim.research is not None:
        definitions = sim.research.definitions
    else:
        raise ValueError(f"unsupported Content Definition kind: {kind}")
    definition_id_raw = change.get("id")
    if not isinstance(definition_id_raw, str) or not definition_id_raw:
        raise ValueError("Content Definition requires a nonempty ID")
    definition_id = DefinitionId(definition_id_raw)
    if action == "remove":
        if set(change) != {"operation", "kind", "id"}:
            raise ValueError("Definition removal accepts only operation, kind and id")
        if definition_id not in definitions:
            raise ValueError(f"cannot remove unknown {kind} Definition: {definition_id}")
        del definitions[definition_id]
        return
    if action != "add" or set(change) != {"operation", "kind", "id", "definition"}:
        raise ValueError("Definition addition requires operation, kind, id and definition")
    if definition_id in definitions:
        raise ValueError(f"duplicate {kind} Definition ID: {definition_id}")
    data = change["definition"]
    if kind == "resource":
        data = _definition_fields(data, {"display_name"}, {"unit", "category", "storage_pool_key"}, "Resource")
        definition = ResourceDef(definition_id, data["display_name"], data.get("unit", "t"),
                                 data.get("category", "material"), data.get("storage_pool_key"))
    elif kind == "process":
        data = _definition_fields(data, {"display_name", "required_capabilities", "inputs_per_day",
                                         "outputs_per_day"}, {"prerequisite_technologies"}, "Process")
        capabilities = data["required_capabilities"]
        if not isinstance(capabilities, list) or any(not isinstance(cap, str) or not cap for cap in capabilities):
            raise ValueError("process capabilities must be a list of identifiers")
        definition = ProcessSpec(
            definition_id, data["display_name"], frozenset(capabilities),
            _resource_amounts(data["inputs_per_day"], "process inputs"),
            _resource_amounts(data["outputs_per_day"], "process outputs"),
            _definition_ids(data.get("prerequisite_technologies", []), "process prerequisites"),
        )
    else:
        data = _definition_fields(data, {"display_name", "stage_specs"},
                                  {"prerequisites", "progression_stage", "category", "series"}, "Research")
        definition = ResearchDefinition(
            definition_id, data["display_name"], _new_research_stages(data["stage_specs"]),
            _definition_ids(data.get("prerequisites", []), "research prerequisites"),
            data.get("progression_stage"), data.get("category"), data.get("series"),
        )
    definitions[definition_id] = definition


def apply_content_variant(sim: Simulation, catalog: GameCatalog, changes: Sequence[Mapping]) -> None:
    """Edit typed method attributes before validation, without Core ID branching.

    Content IDs are runtime data used as lookup keys. The enum-like kind field
    identifies the owning Definition collection rather than a special asset.
    """
    for change in changes:
        if change.get("operation") in ("add", "remove"):
            _change_definition_membership(sim, catalog, change)
            continue
        if change.get("operation", "edit") != "edit":
            raise ValueError(f"unknown Content variant operation: {change.get('operation')}")
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
        elif kind == "facility" and field_name == "capability_supplies":
            from space_idle.facilities import CapabilitySupply
            if not isinstance(value, list) or any(not isinstance(cap, str) or not cap for cap in value):
                raise ValueError("facility capabilities must be a list of nonempty IDs")
            if len(set(value)) != len(value):
                raise ValueError("duplicate facility capabilities")
            definition = sim.facilities.definitions[definition_id]
            sim.facilities.definitions[definition_id] = replace(
                definition, capability_supplies=tuple(CapabilitySupply(cap) for cap in value),
            )
        elif kind in ("research_provider", "survey_provider") and field_name == "required_source_capabilities":
            sources = _identifiers(value, "provider source capabilities")
            if not sources:
                raise ValueError("provider source capabilities must not be empty")
            providers = (sim.research.providers if kind == "research_provider" else sim.survey.providers)
            providers[definition_id] = replace(
                providers[definition_id], required_source_capabilities=sources,
            )
        elif kind == "vehicle" and field_name == "generic_capabilities":
            capabilities = _identifiers(value, "vehicle capabilities")
            vehicle = sim.transport.vehicle_defs[definition_id]
            sim.transport.vehicle_defs[definition_id] = replace(
                vehicle, performance=replace(vehicle.performance, generic_capabilities=tuple(sorted(capabilities))),
            )
            sim.transport.invalidate_movement_plans()
        elif kind == "vehicle" and field_name in (
            "production_days", "retirement_work_days_per_unit", "payload_t",
        ):
            vehicle = sim.transport.vehicle_defs[definition_id]
            amount = _finite_nonnegative(value)
            if field_name == "production_days":
                vehicle = replace(vehicle, production=replace(vehicle.production, days=amount))
            elif field_name == "retirement_work_days_per_unit":
                vehicle = replace(vehicle, retirement=replace(vehicle.retirement, work_days_per_unit=amount))
            else:
                vehicle = replace(vehicle, performance=replace(vehicle.performance, payload_t=amount))
            sim.transport.vehicle_defs[definition_id] = vehicle
            sim.transport.invalidate_movement_plans()
        elif kind == "research_provider" and field_name == "crew_person_days_per_research_point":
            if sim.research is None:
                raise ValueError("Research Domain not available")
            provider = sim.research.providers[definition_id]
            sim.research.providers[definition_id] = replace(
                provider, crew_person_days_per_research_point=_finite_nonnegative(value),
            )
        elif kind == "survey_provider" and field_name == "capacity_units_per_source_per_day":
            if sim.survey is None:
                raise ValueError("Survey Domain not available")
            amount = _finite_nonnegative(value)
            if amount <= 0:
                raise ValueError("survey provider capacity must be positive")
            provider = sim.survey.providers[definition_id]
            sim.survey.providers[definition_id] = replace(provider, capacity_units_per_source_per_day=amount)
        elif kind in ("construction", "decommission") and field_name == "construction_work":
            amount = _finite_nonnegative(value)
            if amount <= 0:
                raise ValueError("construction work must be positive")
            recipes = (sim.projects.recipes if kind == "construction"
                       else sim.projects.decommission_recipes)
            recipes[definition_id] = replace(recipes[definition_id], construction_work=amount)
        elif kind == "power" and field_name in ("load_mw", "standby_load_mw", "generation_mw"):
            spec = sim.power.specs[definition_id]
            amount = _finite_nonnegative(value)
            if field_name == "generation_mw":
                from space_idle.power import FixedGeneration, SolarGeneration
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
            from space_idle.research_models import ResearchTheoryStageSpec
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
        elif ((kind in ("process", "construction") and field_name == "prerequisite_technologies")
              or (kind == "research" and field_name == "prerequisites")):
            if not isinstance(value, list) or any(not isinstance(row, str) for row in value):
                raise ValueError(f"{field_name} must be a list of Definition IDs")
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

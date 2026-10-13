"""Typed Content changes for comparing Definition-derived balance outcomes.

Applied only during fresh Composition, before any Simulation state is created.
The owning Domain and normal Composition validators remain authoritative.
"""
from __future__ import annotations

from dataclasses import replace, is_dataclass
from math import isfinite
from typing import Mapping, Sequence

from space_idle.catalog import GameCatalog
from space_idle.content.asset_content import AssetDefinitions
from space_idle.shared import DefinitionId
from space_idle.population import ExternalPopulationSourceDefinition
from space_idle.simulation import Simulation


def _finite_nonnegative(value: object) -> float:
    if type(value) not in (float, int) or not isfinite(value) or value < 0:
        raise ValueError("variant quantity must be finite and nonnegative")
    return float(value)


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
        "market_provider": (sim.market.provider_defs, "id"),
        "spatial_development": (sim.projects.spatial_recipes, "id"),
        "construction_resource_provider": (sim.projects.construction_resource_providers, "resource_id"),
    }
    if sim.research is not None:
        collections["research_provider"] = (sim.research.providers, "id")
    if sim.survey is not None:
        collections["survey_provider"] = (sim.survey.providers, "id")
    if sim.extraction is not None:
        collections["extraction"] = (sim.extraction.specs, "id")
    if sim.scientific_exploration is not None:
        collections["scientific_exploration"] = (sim.scientific_exploration.definitions, "id")
    if sim.founding is not None:
        collections["founding"] = (sim.founding.deployment_recipes, "id")
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


def _change_movement_rule_membership(sim: Simulation, change: Mapping) -> None:
    """Edit typed Movement definitions in an isolated Composition, never State.

    Movement rules are tuple-owned by Transport, not an alternative global
    registry. A profile can be authored as an additional route choice, while
    every generated plan still goes through the normal Operation eligibility.
    """
    collections = {
        "surface_movement_rule": "surface_movement_rules",
        "surface_access_movement_rule": "surface_access_movement_rules",
        "spaceflight_movement_rule": "spaceflight_movement_rules",
    }
    kind = change.get("kind")
    attr = collections[kind]
    raw_id = change.get("id")
    if not isinstance(raw_id, str) or not raw_id:
        raise ValueError("Movement Definition requires a nonempty ID")
    definition_id = DefinitionId(raw_id)
    rules = {rule.id: rule for rule in getattr(sim.transport, attr)}
    if len(rules) != len(getattr(sim.transport, attr)):
        raise ValueError(f"duplicate {kind} Definition in Composition")
    operation = change.get("operation")
    if operation == "remove":
        if set(change) != {"operation", "kind", "id"}:
            raise ValueError("Movement Definition removal accepts only operation, kind and id")
        if definition_id not in rules:
            raise ValueError(f"unknown {kind} Definition: {definition_id}")
        del rules[definition_id]
    elif operation == "add":
        if set(change) != {"operation", "kind", "id", "source_id"}:
            raise ValueError("Movement Definition copy requires operation, kind, id and source_id")
        source_id = change["source_id"]
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("Movement Definition requires a nonempty source_id")
        if definition_id in rules:
            raise ValueError(f"duplicate {kind} Definition: {definition_id}")
        source = rules.get(DefinitionId(source_id))
        if source is None:
            raise ValueError(f"unknown {kind} source Definition: {source_id}")
        rules[definition_id] = replace(source, id=definition_id)
    else:
        raise ValueError(f"unknown Movement Definition operation: {operation}")
    setattr(sim.transport, attr, tuple(rules[key] for key in sorted(rules)))
    sim.transport.invalidate_movement_plans()


def _add_asset_bundle(sim: Simulation, catalog: GameCatalog, change: Mapping) -> None:
    """Register a complete typed asset variant from one authored list entry.

    Definitions remain owned by their original Domains. This composes a new
    Facility or Vehicle together with applicable acquisition and service specs;
    it is not a runtime Content owner, a copy of Player State or a Core alias.
    """
    data = _definition_fields(change, {"operation", "kind", "asset_kind", "id", "source_id"},
                              {"edits"}, "asset bundle")
    if data["operation"] != "add" or data["kind"] != "asset_bundle":
        raise ValueError("asset bundle must be an addition")
    asset_kind = data["asset_kind"]
    if asset_kind not in ("facility", "vehicle"):
        raise ValueError("asset bundle requires facility or vehicle asset_kind")
    source_id, target_id = DefinitionId(str(data["source_id"])), DefinitionId(str(data["id"]))
    if not str(source_id) or not str(target_id):
        raise ValueError("asset bundle requires nonempty identifiers")
    # Both standard and variant assets pass through the same typed owner map
    # installer. A variant is not a second Content registration architecture.
    authored = AssetDefinitions(
        facilities=sim.facilities.definitions,
        construction=sim.projects.recipes,
        power=sim.power.specs,
        storage=sim.storage.providers,
        construction_providers=sim.projects.construction_providers,
        upgrades=sim.projects.upgrade_recipes,
        decommission=sim.projects.decommission_recipes,
        vehicles=sim.transport.vehicle_defs,
    )
    owner = authored.facilities if asset_kind == "facility" else authored.vehicles
    if source_id not in owner or target_id in owner:
        raise ValueError("asset bundle requires an existing source and new target ID")
    if asset_kind == "facility":
        authored.copy_facility(source_id, target_id)
    else:
        authored.copy_vehicle(source_id, target_id)
        sim.transport.invalidate_movement_plans()
    related = ("facility", "construction", "decommission", "power",
               "storage_provider", "construction_provider") if asset_kind == "facility" else ("vehicle",)
    edits = data.get("edits", [])
    if not isinstance(edits, list):
        raise ValueError("asset bundle edits must be a list")
    for edit in edits:
        if not isinstance(edit, Mapping) or "kind" not in edit or "field" not in edit:
            raise ValueError("asset bundle edits must be typed field changes")
        if set(edit) - {"kind", "field", "value", "resource_id", "pool_key"}:
            raise ValueError("asset bundle edit contains unexpected fields")
        if edit["kind"] not in related:
            raise ValueError("asset bundle edit must affect its own asset Definitions")
        apply_content_variant(sim, catalog, ({**edit, "operation": "edit", "id": str(target_id)},))


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
    if kind == "asset_bundle":
        _add_asset_bundle(sim, catalog, change)
        return
    if kind in {"facility", "vehicle", "construction", "decommission", "power",
                "storage_provider", "construction_provider"}:
        raise ValueError("asset-owned Definitions must be added through one complete asset bundle")
    if kind in ("surface_movement_rule", "surface_access_movement_rule", "spaceflight_movement_rule"):
        _change_movement_rule_membership(sim, change)
        return
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


def _change_world_definition(sim: Simulation, catalog: GameCatalog, change: Mapping) -> None:
    """Change authoritative *static* World inputs before ordinary validation.

    These are the same physical definitions consumed by Extraction, Power,
    Movement, Surface development and Survey.  No balance-only coefficients or
    player-owned Location/Knowledge/Stock State are introduced.
    """
    from space_idle.shared import CelestialBodyId, SurfaceCellId, SpatialNodeId, StarSystemId

    kind = change["kind"]
    field_name = change.get("field")
    identity = change.get("id")
    if not isinstance(identity, str) or not identity:
        raise ValueError("World edit requires a registered physical ID")
    value = change.get("value")
    if kind == "world_cell" and field_name in {"latitude_deg", "longitude_deg"}:
        if type(value) not in (int, float) or not isfinite(value):
            raise ValueError("World geographic coordinate must be finite")
        amount = float(value)
    else:
        amount = _finite_nonnegative(value)
    graph = sim.graph

    if kind == "world_cell":
        cell_id = SurfaceCellId(identity)
        if cell_id not in graph.surface_cells:
            raise ValueError(f"unknown World Surface Cell: {identity}")
        cell = graph.surface_cells[cell_id]
        if field_name == "resource_potential":
            resource_id = change.get("resource_id")
            if not isinstance(resource_id, str) or DefinitionId(resource_id) not in catalog.resources:
                raise ValueError("World Resource Potential requires a registered Resource")
            updated = dict(cell.resource_potential_by_resource)
            updated[DefinitionId(resource_id)] = amount
            cell = replace(cell, resource_potential_by_resource=updated)
        elif field_name == "geology_accessibility":
            geology_key = change.get("geology_key")
            if not isinstance(geology_key, str) or not geology_key:
                raise ValueError("World geology edit requires a nonempty geology_key")
            updated = dict(cell.static_geology)
            updated[geology_key] = amount
            cell = replace(cell, static_geology=updated)
        elif field_name in {"terrain_factor", "bearing_capacity_factor", "dust_factor", "slope_factor"}:
            cell = replace(cell, terrain=replace(cell.terrain, **{field_name: amount}))
        elif field_name == "area_km2":
            if amount <= 0:
                raise ValueError("World Cell area must be positive")
            cell = replace(cell, area_km2=amount)
        elif field_name in {"latitude_deg", "longitude_deg"}:
            cell = replace(cell, centroid=replace(cell.centroid, **{field_name: amount}))
        else:
            raise ValueError(f"unsupported World Cell parameter: {field_name}")
        graph.surface_cells[cell_id] = cell
    elif kind == "world_body":
        body_id = CelestialBodyId(identity)
        if body_id not in graph.bodies:
            raise ValueError(f"unknown World Celestial Body: {identity}")
        if field_name not in {
            "mean_radius_km", "heliocentric_semimajor_axis_au", "parent_orbit_semimajor_axis_km",
            "standard_gravitational_parameter_km3_s2", "reference_gravity_m_s2",
        }:
            raise ValueError(f"unsupported World Celestial Body parameter: {field_name}")
        if amount <= 0:
            raise ValueError(f"World Celestial Body {field_name} must be positive")
        graph.bodies[body_id] = replace(graph.bodies[body_id], **{field_name: amount})
        sim.transport.invalidate_movement_plans()
    elif kind == "world_node":
        node_id = SpatialNodeId(identity)
        if node_id not in graph.nodes:
            raise ValueError(f"unknown World Spatial Node: {identity}")
        if field_name != "body_center_orbit_radius_km" or amount <= 0:
            raise ValueError(f"unsupported or nonpositive World Spatial Node parameter: {field_name}")
        graph.nodes[node_id] = replace(graph.nodes[node_id], body_center_orbit_radius_km=amount)
        sim.transport.invalidate_movement_plans()
    elif kind == "world_system":
        system_id = StarSystemId(identity)
        if system_id not in graph.star_systems:
            raise ValueError(f"unknown World Star System: {identity}")
        if field_name != "central_gravitational_parameter_km3_s2" or amount <= 0:
            raise ValueError(f"unsupported or nonpositive World Star System parameter: {field_name}")
        graph.star_systems[system_id] = replace(
            graph.star_systems[system_id], central_gravitational_parameter_km3_s2=amount)
        sim.transport.invalidate_movement_plans()
    elif kind == "world_environment":
        facet_name = change.get("facet")
        # The World-owning StaticFacetStore defines the physical field kinds
        # and scope. A supplied ID cannot turn a Body field into a Cell field.
        facet_types = {facet.facet_key: facet for facet in sim.environment.static.facet_types()}
        if not isinstance(facet_name, str) or facet_name not in facet_types:
            raise ValueError(f"unknown World environment facet: {facet_name}")
        facet_type = facet_types[facet_name]
        if identity in graph.bodies:
            definitions = sim.environment.static.body_facets
            key = (CelestialBodyId(identity), facet_type)
        elif identity in graph.surface_cells or identity in graph.nodes:
            definitions = sim.environment.static.facets
            key = (SurfaceCellId(identity) if identity in graph.surface_cells else SpatialNodeId(identity), facet_type)
        else:
            raise ValueError(f"unknown World environment context: {identity}")
        if key not in definitions:
            raise ValueError(f"World environment facet not registered at context: {identity}/{facet_name}")
        facet = definitions[key]
        from dataclasses import fields
        if field_name not in {field.name for field in fields(facet)}:
            raise ValueError(f"unsupported World environment parameter: {facet_name}.{field_name}")
        previous = getattr(facet, field_name)
        if type(previous) not in (int, float):
            raise ValueError("World environment parameter must be a numeric scalar")
        definitions[key] = replace(facet, **{field_name: amount})
    else:
        raise ValueError(f"unsupported World Definition kind: {kind}")


def _edit_registered_numeric_parameter(sim: Simulation, change: Mapping) -> bool:
    """Edit a numeric leaf in a *real owning Domain Definition*.

    This is deliberately not an analysis coefficient table. Dataclass
    constructors and the standard Composition validators check the edited
    Definition, and nested specifications retain their real types. Identities,
    collections, State and Resource amounts cannot be mutated by this route.
    """
    kind = change.get("kind")
    collections = {
        "facility": sim.facilities.definitions,
        "vehicle": sim.transport.vehicle_defs,
        "process": sim.industry.processes,
        "construction": sim.projects.recipes,
        "decommission": sim.projects.decommission_recipes,
        "power": sim.power.specs,
        "storage_provider": sim.storage.providers,
        "market_provider": sim.market.provider_defs,
        "spatial_development": sim.projects.spatial_recipes,
        "construction_resource_provider": sim.projects.construction_resource_providers,
    }
    collections.update({key: owner for key, (owner, _identity) in _owned_definition_collections(sim).items()})
    if sim.research is not None:
        collections["research"] = sim.research.definitions
    movement_rules = {
        "surface_movement_rule": "surface_movement_rules",
        "surface_access_movement_rule": "surface_access_movement_rules",
        "spaceflight_movement_rule": "spaceflight_movement_rules",
    }
    movement_attr = movement_rules.get(kind)
    if movement_attr is not None:
        collections[kind] = {rule.id: rule for rule in getattr(sim.transport, movement_attr)}
    if kind not in collections:
        return False
    field_path = change.get("field")
    if not isinstance(field_path, str) or not field_path or ".." in field_path:
        return False
    definition_id = DefinitionId(str(change.get("id")))
    definitions = collections[kind]
    if definition_id not in definitions:
        raise ValueError(f"unknown {kind} Definition: {definition_id}")
    definition = definitions[definition_id]
    parts = field_path.split(".")
    selector = change.get("selector")
    if selector is not None and (not isinstance(selector, dict) or not selector
                                 or any(not isinstance(key, str) or not key for key in selector)):
        raise ValueError("numeric entry selector must match named Definition fields")
    selected_entries = 0

    def edit(current, remaining):
        nonlocal selected_entries
        if not remaining:
            if type(current) not in (int, float):
                raise ValueError("selected Definition field is not a numeric scalar")
            amount = change.get("value")
            if type(amount) not in (int, float) or not isfinite(amount):
                raise ValueError("Definition numeric parameter must be finite")
            if type(current) is int and type(amount) is not int:
                raise ValueError("integer Definition parameter needs an integer")
            if amount < 0:
                raise ValueError("Definition numeric parameter must be nonnegative")
            if kind == "power" and field_path == "generation.reference_flux_w_m2" and amount == 0:
                raise ValueError("solar reference flux must be positive")
            return amount if type(current) is int else float(amount)
        if not is_dataclass(current) or remaining[0] not in current.__dataclass_fields__ or remaining[0].startswith("_"):
            raise ValueError(f"unsupported typed numeric Definition field: {kind}.{field_path}")
        field_name = remaining[0]
        if not remaining[1:] and field_name in {"id", "level", "stage_id"}:
            raise ValueError("registered Definition identity cannot be edited as a quantity")
        child = getattr(current, field_name)
        if isinstance(child, tuple):
            if selector is None or not remaining[1:]:
                raise ValueError("Definition tuple entries need a selector and numeric member")
            matched = [i for i, element in enumerate(child)
                       if is_dataclass(element) and all(getattr(element, key, object()) == value
                                                        for key, value in selector.items())]
            if len(matched) != 1:
                raise ValueError("Definition tuple selector must identify one registered entry")
            selected_entries += 1
            index = matched[0]
            elements = list(child)
            elements[index] = edit(elements[index], remaining[1:])
            child = tuple(elements)
        else:
            child = edit(child, remaining[1:])
        return replace(current, **{field_name: child})

    try:
        result = edit(definition, parts)
    except ValueError as exc:
        if "unsupported typed numeric Definition field" in str(exc):
            return False
        raise
    if selector is not None and selected_entries != 1:
        raise ValueError("Definition numeric selector must select one registered entry")
    if movement_attr is not None:
        setattr(sim.transport, movement_attr, tuple(
            result if rule.id == definition_id else rule
            for rule in getattr(sim.transport, movement_attr)))
    else:
        definitions[definition_id] = result
    if kind == "vehicle" or movement_attr is not None:
        sim.transport.invalidate_movement_plans()
    return True


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
        if kind in {"world_cell", "world_body", "world_node", "world_system", "world_environment"}:
            _change_world_definition(sim, catalog, change)
            continue
        definition_id = DefinitionId(str(change["id"]))
        field_name = change.get("field")
        value = change.get("value")
        if kind == "process" and field_name in ("inputs_per_day", "outputs_per_day"):
            process = sim.industry.processes[definition_id]
            resource_id = DefinitionId(str(change["resource_id"]))
            amounts = dict(getattr(process, field_name))
            amounts[resource_id] = _finite_nonnegative(value)
            sim.industry.processes[definition_id] = replace(process, **{field_name: amounts})
        elif kind in ("facility", "vehicle") and field_name == "display_name":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("display name must be nonempty")
            domain = (sim.facilities.definitions if kind == "facility" else sim.transport.vehicle_defs)
            domain[definition_id] = replace(domain[definition_id], display_name=value)
        elif kind in ("construction", "decommission") and field_name == "resources":
            from space_idle.projects import BuildResourceRequirement
            definition = (sim.projects.recipes if kind == "construction" else
                          sim.projects.decommission_recipes)[definition_id]
            amounts = _resource_amounts(value, "construction resources")
            requirements = tuple(BuildResourceRequirement(resource, quantity)
                                 for resource, quantity in amounts.items())
            if kind == "construction":
                sim.projects.recipes[definition_id] = replace(definition, resources=requirements)
            else:
                sim.projects.decommission_recipes[definition_id] = replace(definition, resources=requirements)
        elif kind == "vehicle" and field_name in ("production_resources", "turnaround_resources"):
            amounts = _resource_amounts(value, "Vehicle resource requirements")
            vehicle = sim.transport.vehicle_defs[definition_id]
            requirements = tuple(sorted(amounts.items()))
            if field_name == "production_resources":
                vehicle = replace(vehicle, production=replace(vehicle.production, resources=requirements))
            else:
                vehicle = replace(vehicle, maintenance=replace(vehicle.maintenance, resources=requirements))
            sim.transport.vehicle_defs[definition_id] = vehicle
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
        elif kind == "storage_provider" and field_name == "capacity_t_by_pool":
            spec = sim.storage.providers[definition_id]
            key = str(change["pool_key"])
            amounts = dict(spec.capacity_t_by_pool)
            amounts[key] = _finite_nonnegative(value)
            sim.storage.providers[definition_id] = replace(spec, capacity_t_by_pool=amounts)
        elif kind == "extraction" and field_name in ("resource_id", "output_resource_id"):
            if not isinstance(value, str) or not value:
                raise ValueError("extraction Resource reference must be a nonempty Definition ID")
            domain = sim.extraction.specs
            domain[definition_id] = replace(domain[definition_id], **{field_name: DefinitionId(value)})
        elif kind == "extraction" and field_name == "required_capabilities":
            required = _identifiers(value, "extraction method capabilities")
            if not required:
                raise ValueError("extraction method requires physical capabilities")
            domain = sim.extraction.specs
            domain[definition_id] = replace(domain[definition_id], required_capabilities=required)
        elif ((kind in ("process", "construction", "extraction") and field_name == "prerequisite_technologies")
              or (kind == "research" and field_name == "prerequisites")):
            if not isinstance(value, list) or any(not isinstance(row, str) for row in value):
                raise ValueError(f"{field_name} must be a list of Definition IDs")
            prerequisites = frozenset(DefinitionId(row) for row in value)
            if len(prerequisites) != len(value):
                raise ValueError("duplicate prerequisite technologies")
            if kind == "extraction":
                domain = sim.extraction.specs
                domain[definition_id] = replace(domain[definition_id], prerequisite_technologies=prerequisites)
            elif kind == "process":
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
        elif _edit_registered_numeric_parameter(sim, change):
            pass
        else:
            raise ValueError(f"unsupported typed Content variant: {kind}.{field_name}")

    # Definition membership and Capability edits change compatibility; refresh
    # derived indexes before the canonical Composition/Scenario validators run.
    if sim.extraction is not None:
        sim.extraction.refresh_definition_compatibility()

"""Opt-in read-only observation of current Application decision contracts.

This is a development projection, never a simulation-side eligibility engine.
Only existing Application Queries decide what is selectable and why. Definitions
and actual canonical settlement flows remain separate observation layers.
"""
from __future__ import annotations

from dataclasses import asdict

from space_idle.application import GameApplication
from space_idle.application_commands import (
    GetBuildOptions, GetLogistics, GetMarket, GetNonSurfaceFoundingOptions,
    GetOperationalNode, GetResearch, GetScientificExplorations, GetSurfaceMap,
    GetSurveys, GetTransportAllocationOptions, GetWorld,
)
from space_idle.shared import SpatialNodeId


def observe_application_decisions(
    app: GameApplication, *, operational_node_ids: frozenset[SpatialNodeId] | None = None,
    founding_targets: tuple[tuple[str, str], ...] = (),
    surface_cells: tuple[tuple[str, str], ...] = (),
    transport_pairs: tuple[tuple[str, str], ...] = (),
) -> dict:
    world = app.query(GetWorld())
    nodes = tuple(sorted((node.id for node in world.operational_nodes
                          if operational_node_ids is None
                          or SpatialNodeId(node.id) in operational_node_ids)))
    if operational_node_ids is not None and set(nodes) != {str(node) for node in operational_node_ids}:
        raise ValueError("decision observation scope includes an unknown Operational Node")
    node_scope = set(nodes)
    rows: list[dict] = []

    def json_value(value):
        if isinstance(value, (tuple, list)):
            return [json_value(item) for item in value]
        if isinstance(value, dict):
            return {key: json_value(item) for key, item in value.items()}
        return value

    def emit(kind: str, context: str, identity: str, allowed: bool | None,
             blockers: tuple = (), **observed) -> None:
        rows.append({
            "kind": kind, "context": context, "id": identity,
            "allowed": allowed, "blockers": [asdict(value) for value in blockers],
            "observed": json_value(observed),
        })

    for node_id in nodes:
        node_views = app.query_many({
            "view": GetOperationalNode(node_id),
            "build": GetBuildOptions(node_id),
        })
        view, build_options = node_views["view"], node_views["build"]
        for asset in view.facilities:
            emit("facility_decommission", node_id, asset.id, asset.can_decommission,
                 asset.decommission_blockers, definition_id=asset.definition_id,
                 level=asset.level, lifecycle=asset.lifecycle)
            if asset.next_upgrade is not None:
                upgrade = asset.next_upgrade
                emit("facility_upgrade", node_id, asset.id, upgrade.can_plan,
                     upgrade.blockers, definition_id=asset.definition_id,
                     level=asset.level, target_level=upgrade.target_level,
                     required_work=upgrade.construction_required,
                     inputs=tuple((x.resource_id, x.required_t) for x in upgrade.resources))
        for industry in view.industry:
            for option in industry.process_options:
                emit("process_selection", node_id, f"{industry.facility_id}:{option.process_id}",
                     option.can_select, option.blockers,
                     facility_id=industry.facility_id, process_id=option.process_id,
                     selected=industry.process_id == option.process_id,
                     inputs_per_day=option.input_rates_per_day,
                     outputs_per_day=option.output_rates_per_day)
        for extraction in view.extraction:
            for option in extraction.method_options:
                emit("extraction_selection", node_id,
                     f"{extraction.facility_id}:{option.method_id}", option.can_select,
                     option.blockers, facility_id=extraction.facility_id,
                     method_id=option.method_id,
                     selected=extraction.method_id == option.method_id,
                     resource_id=option.resource_id, output_resource_id=option.output_resource_id,
                     physical_opportunity=option.potential_opportunity,
                     nominal_output_t_per_day=option.nominal_output_t_per_day)
        for option in build_options.items:
            emit("facility_construction", node_id,
                 option.facility_definition_id or "", option.can_plan, option.blockers,
                 required_work=option.construction_required,
                 inputs=tuple((value.resource_id, value.required_t) for value in option.resources),
                 projected_material_readiness_day=option.projected_material_readiness_day,
                 placement_scope=option.placement_scope)

    # Research is organization-wide. Other decisions are scoped to physical
    # nodes, including the Market interface and provider's current location.
    for research in app.query(GetResearch()).items:
        emit("research_start", "organization", research.id, research.can_start,
             research.start_blockers, status=research.status,
             current_stage=research.current_stage_id,
             stage_progress=research.stage_progress,
             stage_required=research.stage_required,
             rp_requested=research.rp_requested, rp_allocated=research.rp_allocated)
    for exploration in app.query(GetScientificExplorations()).items:
        if exploration.origin_id not in node_scope:
            continue
        emit("scientific_exploration_start", exploration.origin_id,
             exploration.id, exploration.can_start, exploration.blockers,
             destination_id=exploration.destination_id,
             required_units=exploration.required_units,
             outbound_days=exploration.outbound_latency_days,
             return_days=exploration.return_latency_days,
             committed_units=exploration.committed_units)
    for campaign in app.query(GetSurveys()).campaigns:
        for option in campaign.candidates:
            if option.provider_operational_node_id not in node_scope:
                continue
            emit("survey_provider_option", option.provider_operational_node_id,
                 f"{campaign.id}:{option.comparison_key}", option.viable,
                 option.blockers, campaign_id=campaign.id,
                 provider_id=option.provider_definition_id,
                 mode_id=option.observation_mode_id,
                 rate=option.survey_rate, matches_constraints=option.matches_constraints)
    market = app.query(GetMarket())
    interface_nodes = {interface.id: interface.operational_node_id
                       for interface in market.interfaces}
    for candidate in market.order_candidates:
        if interface_nodes.get(candidate.market_interface_id) not in node_scope:
            continue
        emit("market_order", interface_nodes[candidate.market_interface_id],
             f"{candidate.market_interface_id}:{candidate.direction}:{candidate.resource_id}",
             candidate.can_create, candidate.blockers,
             market_interface_id=candidate.market_interface_id,
             direction=candidate.direction, resource_id=candidate.resource_id,
             unit_price=candidate.offer_price_musd_per_t)
    logistics = app.query(GetLogistics())
    for candidate in logistics.vehicle_production_options:
        if candidate.operational_node_id not in node_scope:
            continue
        emit("vehicle_production", candidate.operational_node_id,
             candidate.vehicle_definition_id, candidate.can_plan, candidate.blockers,
             required_days=candidate.production_days, resources=candidate.resources,
             service_type=candidate.production_service_type)
    for allocation in logistics.allocations:
        if allocation.anchor_node_id not in node_scope and allocation.destination_id not in node_scope:
            continue
        emit("transport_allocation_status", allocation.anchor_node_id,
             allocation.id, None, allocation.blockers,
             destination_id=allocation.destination_id,
             vehicle_definition_id=allocation.vehicle_definition_id,
             active_units=allocation.active_units,
             required_units=allocation.required_units,
             unfilled_units=allocation.unfilled_units,
             limiting_factors=tuple(asdict(value) for value in allocation.limiting_factors))

    # On-demand context/OD evaluations only; do not enumerate all bodies,
    # cells or global vehicle x OD combinations during unrelated analysis.
    for body_id, context_id in sorted(set(founding_targets)):
        view = app.query(GetNonSurfaceFoundingOptions(body_id, context_id))
        for context in view.contexts:
            if context.spatial_node_id != context_id:
                continue
            for option in context.foundation_options:
                emit("non_surface_founding", context.spatial_node_id,
                     option.comparison_key, option.can_plan, option.blockers,
                     body_id=body_id, operational=context.operational,
                     staging_node_id=option.staging_node_id,
                     deployment_recipe_id=option.deployment_recipe_id,
                     vehicle_definition_id=option.vehicle_definition_id,
                     transit_days=option.transit_days, required_units=option.required_units,
                     resources=option.resources)
    # Surface founding and expansion are likewise evaluated only for explicit
    # geographic cells. Mere physical existence is not an Operational Node.
    for body_id in sorted({body for body, _ in surface_cells}):
        selected_cells = tuple(sorted({cell for body, cell in surface_cells if body == body_id}))
        surface = app.query(GetSurfaceMap(body_id, founding_cell_ids=selected_cells))
        for cell in surface.cells:
            if cell.id not in selected_cells:
                continue
            for option in cell.foundation_options:
                emit("surface_founding", cell.id, option.comparison_key,
                     option.can_plan, option.blockers,
                     body_id=body_id, staging_node_id=option.staging_node_id,
                     deployment_recipe_id=option.deployment_recipe_id,
                     vehicle_definition_id=option.vehicle_definition_id,
                     preparation_work=option.preparation_work,
                     transit_days=option.transit_days,
                     resources=option.resources)
            for option in cell.development_options:
                emit("surface_development", cell.id, option.location_id,
                     option.can_plan, option.blockers,
                     body_id=body_id,
                     projected_infrastructure_fulfillment=option.projected_surface_infrastructure_fulfillment,
                     required_work=option.construction_required,
                     resources=option.resources)
            for option in cell.facility_placement_options:
                emit("surface_facility_placement", cell.id,
                     f"{option.location_id}:{option.facility_definition_id}",
                     option.can_plan, option.blockers,
                     body_id=body_id, required_work=option.construction_required,
                     resources=option.resources)
    for origin, destination in sorted(set(transport_pairs)):
        options = app.query(GetTransportAllocationOptions(origin, destination))
        for option in options.options:
            # The Domain query supplies blockers but no can_plan flag here.
            # Do not create a second boolean eligibility rule from them.
            emit("transport_allocation_option", origin,
                 f"{destination}:{option.vehicle_definition_id}", None, option.blockers,
                 destination_id=destination, vehicle_definition_id=option.vehicle_definition_id,
                 forward_path=option.forward_path, reverse_path=option.reverse_path,
                 nominal_forward_t_per_day=option.nominal_capacity.forward_t_per_day,
                 nominal_reverse_t_per_day=option.nominal_capacity.reverse_t_per_day,
                 cycle_days=option.cycle_days,
                 available_fleet_units=option.fleet_free_units)

    return {
        "layer": "application_current_eligibility", "day": world.day,
        "operational_node_scope": list(nodes),
        "on_demand_founding_targets": [list(pair) for pair in sorted(set(founding_targets))],
        "on_demand_surface_cells": [list(pair) for pair in sorted(set(surface_cells))],
        "on_demand_transport_pairs": [list(pair) for pair in sorted(set(transport_pairs))],
        "scope_semantics": ("Node-local choices and organization-wide Research; "
                             "explicit Founding Cell/Context and Transport OD requests "
                             "may extend outside node scope; no eligibility re-evaluation"),
        "entries": sorted(rows, key=lambda row: (row["kind"], row["context"], row["id"])),
    }

from __future__ import annotations

import pytest

from space_idle import GetDependencyAnalytics, build_game_application
from space_idle.catalog import ResourceGroupDef
from space_idle.content import base_ids as ids
from space_idle.content.base_game import EARTH, LEO
from space_idle.shared import DefinitionId, EntityId
from space_idle.validation import validate_catalog_coverage
from space_idle.validation_support import ConfigurationError
from space_idle.logistics_models import CargoFlowSegment, CargoServiceLeg
from space_idle.external_procurement import ExternalSupplyBatch


def _resource(view, resource_id):
    return next(row for row in view.resources if row.id == str(resource_id))


def test_scope_boundary_changes_import_export_without_double_counting_internal_flow():
    app = build_game_application()
    sim = app._simulation
    sim.logistics.cargo_flows[EntityId("flow.analytics.scope")] = CargoFlowSegment(
        id=EntityId("flow.analytics.scope"), resource_id=ids.WATER, amount_t=12.0,
        source_id=EARTH, final_destination_id=LEO, requirement_id=None,
        owner_kind="test", owner_id=EntityId("analytics.owner"), priority=3,
        leg=CargoServiceLeg("analytics.service", EARTH, LEO, 2, 2.0),
        remaining_legs=(), dispatch_start_day=sim.day, dispatch_end_day=sim.day + 1,
        dispatch_rate_t_per_day=12.0,
    )

    earth = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))
    leo = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),)))
    combined = app.query(GetDependencyAnalytics(
        "operational_nodes", node_ids=(str(LEO), str(EARTH))
    ))

    assert _resource(earth, ids.WATER).exports_pipeline == pytest.approx(12.0)
    assert _resource(earth, ids.WATER).imports_pipeline == pytest.approx(0.0)
    assert _resource(leo, ids.WATER).imports_pipeline == pytest.approx(12.0)
    assert _resource(leo, ids.WATER).exports_pipeline == pytest.approx(0.0)
    assert str(EARTH) in _resource(leo, ids.WATER).dependency_source_node_ids
    assert _resource(combined, ids.WATER).imports_pipeline == pytest.approx(0.0)
    assert _resource(combined, ids.WATER).exports_pipeline == pytest.approx(0.0)
    assert combined.node_ids == tuple(sorted((str(EARTH), str(LEO))))


def test_unmet_external_demand_is_projected_for_destination_scope():
    app = build_game_application()

    view = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))
    unmet = [row for row in view.resources if row.unmet_demand > 1e-9]

    assert unmet
    critical = set(view.critical_dependency_resource_ids)
    assert {row.id for row in unmet} <= critical
    assert {
        row.id for row in view.resources if row.external_dependency_per_day > 1e-9
    } <= critical
    assert all("unmet_demand" in row.limiting_factors for row in unmet)


def test_body_and_player_scopes_resolve_operational_nodes_in_application():
    app = build_game_application()
    graph = app._simulation.graph
    body_id = graph.context_body_id(EARTH)
    assert body_id is not None

    body = app.query(GetDependencyAnalytics("body", str(body_id)))
    player = app.query(GetDependencyAnalytics())

    assert set(body.node_ids) == {str(value) for value in graph.nodes_for_body(body_id)}
    assert set(player.node_ids) == {str(value) for value in graph.operational_node_ids()}


def test_content_defined_resource_group_aggregates_members_without_cross_resource_substitution():
    app = build_game_application()
    group_id = DefinitionId("test.group.non_substitutable")
    app._catalog.resource_groups[group_id] = ResourceGroupDef(
        group_id, "Non-substitutable", (ids.WATER, ids.MACHINERY)
    )

    view = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))
    water = _resource(view, ids.WATER)
    machinery = _resource(view, ids.MACHINERY)
    group = next(row for row in view.resource_groups if row.id == str(group_id))
    members = (water, machinery)

    assert group.local_production_per_day == pytest.approx(
        sum(row.local_production_per_day for row in members)
    )
    assert group.local_consumption_per_day == pytest.approx(
        sum(row.local_consumption_per_day for row in members)
    )
    assert group.imports_pipeline == pytest.approx(sum(row.imports_pipeline for row in members))
    assert group.exports_pipeline == pytest.approx(sum(row.exports_pipeline for row in members))

    assert water.local_production_per_day > machinery.local_demand_per_day
    assert machinery.external_dependency_per_day > 0
    assert group.external_dependency_per_day == pytest.approx(
        sum(row.external_dependency_per_day for row in members)
    )
    assert group.local_coverage_ratio == pytest.approx(
        sum(
            max(0.0, row.local_demand_per_day - row.external_dependency_per_day)
            for row in members
        ) / sum(row.local_demand_per_day for row in members)
    )

def test_current_authorized_transport_projects_boundary_flow_consumption_and_partial_unmet():
    app = build_game_application()
    sim = app._simulation
    sim.technology.completed.update(
        sim.projects.recipes[ids.ORBITAL_LOGISTICS_NODE].prerequisite_technologies
    )
    sim.transport.external_services.clear()
    sim.transport.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=1, day=sim.day
    )
    sim.projects.plan_build(
        ids.ORBITAL_LOGISTICS_NODE, LEO, 3, "import_now", day=sim.day,
        import_source_id=EARTH,
    )
    sim.projects.advance_procurement(sim.day)
    demands = sim.projects.supplys(sim.day)
    for demand in demands:
        sim.inventory.stock[(EARTH, demand.resource_id)] = demand.amount_t + 5.0

    machinery = next(demand for demand in demands if demand.resource_id == ids.MACHINERY)
    sim.inventory.stock[(EARTH, machinery.resource_id)] = machinery.amount_t / 2.0
    partial = _resource(
        app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),))),
        ids.MACHINERY,
    )
    assert partial.external_inflow_per_day > 0
    assert 0 < partial.unmet_demand < machinery.amount_t

    sim.inventory.stock[(EARTH, machinery.resource_id)] = machinery.amount_t + 5.0
    leo = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),)))
    earth = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))
    combined = app.query(GetDependencyAnalytics(
        "operational_nodes", node_ids=(str(EARTH), str(LEO))
    ))

    incoming = [row for row in leo.resources if row.external_inflow_per_day > 1e-9]
    assert incoming
    assert all(row.unmet_demand == pytest.approx(0.0) for row in incoming)
    assert sum(row.external_inflow_per_day for row in leo.resources) == pytest.approx(
        sum(row.external_outflow_per_day for row in earth.resources)
    )
    assert sum(row.external_inflow_per_day for row in combined.resources) == pytest.approx(0.0)
    assert sum(row.external_outflow_per_day for row in combined.resources) == pytest.approx(0.0)
    propellant = _resource(earth, ids.PROPELLANT)
    assert propellant.local_demand_per_day > 0
    assert propellant.local_consumption_per_day > 0

def test_authorized_external_procurement_is_current_inflow_and_not_unmet():
    app = build_game_application()
    sim = app._simulation
    project_id = sim.projects.plan_build(
        ids.CARGO_WAREHOUSE, EARTH, 4, "import_now", day=sim.day
    )
    sim.projects.advance_procurement(sim.day)
    project_demands = tuple(
        demand
        for demand in sim.projects.supplys(sim.day)
        if demand.owner_id == EntityId(str(project_id))
    )
    assert project_demands
    for demand in project_demands:
        sim.inventory.stock[(EARTH, demand.resource_id)] = 0.0

    before = app.query(
        GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),))
    )
    sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=(ids.EARTH_INDUSTRIAL_MARKET,),
        scope_kind="project",
        scope_id=EntityId(str(project_id)),
        day=sim.day,
    )
    decision = sim.tick_decision_projection()
    orders = tuple(
        order
        for order in decision.allocations.procurement.orders
        if order.requirement.owner_id == EntityId(str(project_id))
        and order.supply_node_id == EARTH
    )
    assert orders

    view = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))
    for demand in project_demands:
        expected = sum(
            order.amount_t
            for order in orders
            if order.requirement.id == demand.id
        )
        before_row = _resource(before, demand.resource_id)
        row = _resource(view, demand.resource_id)
        assert row.external_inflow_per_day - before_row.external_inflow_per_day == pytest.approx(
            expected
        )
        assert before_row.unmet_demand - row.unmet_demand == pytest.approx(expected)



def test_external_supply_pipeline_applies_only_at_its_supply_endpoint_scope():
    # When the supply endpoint is also the demand scope, in-flight external
    # supply is pipeline credit against unmet demand.
    app = build_game_application()
    sim = app._simulation
    project_id = sim.projects.plan_build(
        ids.CARGO_WAREHOUSE, EARTH, 4, "import_now", day=sim.day
    )
    sim.projects.advance_procurement(sim.day)
    demand = next(
        demand
        for demand in sim.projects.supplys(sim.day)
        if demand.owner_id == EntityId(str(project_id))
        and demand.resource_id == ids.MACHINERY
    )
    sim.inventory.stock[(EARTH, ids.MACHINERY)] = 0.0
    before = app.query(
        GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),))
    )
    pipeline_amount = min(0.4, demand.amount_t)
    sim.logistics.external_supply_batches[EntityId("external.supply.analytics.direct")] = (
        ExternalSupplyBatch(
            EntityId("external.supply.analytics.direct"),
            ids.EARTH_INDUSTRIAL_MARKET,
            demand.id,
            demand.owner_kind,
            demand.owner_id,
            EARTH,
            demand.resource_id,
            pipeline_amount,
            sim.day,
            sim.day + 2,
        )
    )
    after = app.query(
        GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),))
    )
    before_row = _resource(before, ids.MACHINERY)
    after_row = _resource(after, ids.MACHINERY)
    assert after_row.imports_pipeline - before_row.imports_pipeline == pytest.approx(
        pipeline_amount
    )
    assert before_row.unmet_demand - after_row.unmet_demand == pytest.approx(
        pipeline_amount
    )

    # For a remote final demand, that same external batch still exists only at
    # its physical supply endpoint until transport carries it onward.
    remote_app = build_game_application()
    remote = remote_app._simulation
    remote.technology.completed.update(
        remote.projects.recipes[ids.ORBITAL_LOGISTICS_NODE].prerequisite_technologies
    )
    remote_project_id = remote.projects.plan_build(
        ids.ORBITAL_LOGISTICS_NODE, LEO, 4, "import_now",
        day=remote.day, import_source_id=EARTH,
    )
    remote.projects.advance_procurement(remote.day)
    remote_demand = next(
        demand
        for demand in remote.projects.supplys(remote.day)
        if demand.owner_id == EntityId(str(remote_project_id))
        and demand.resource_id == ids.MACHINERY
    )
    remote.inventory.stock[(LEO, ids.MACHINERY)] = 0.0
    earth_before = remote_app.query(
        GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),))
    )
    leo_before = remote_app.query(
        GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),))
    )
    remote.logistics.external_supply_batches[EntityId("external.supply.analytics")] = (
        ExternalSupplyBatch(
            EntityId("external.supply.analytics"),
            ids.EARTH_INDUSTRIAL_MARKET,
            remote_demand.id,
            remote_demand.owner_kind,
            remote_demand.owner_id,
            EARTH,
            remote_demand.resource_id,
            remote_demand.amount_t,
            remote.day,
            remote.day + 2,
        )
    )
    earth = remote_app.query(
        GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),))
    )
    leo = remote_app.query(
        GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),))
    )
    assert (
        _resource(earth, ids.MACHINERY).imports_pipeline
        - _resource(earth_before, ids.MACHINERY).imports_pipeline
    ) == pytest.approx(remote_demand.amount_t)
    assert _resource(leo, ids.MACHINERY).imports_pipeline == pytest.approx(
        _resource(leo_before, ids.MACHINERY).imports_pipeline
    )
    assert _resource(leo, ids.MACHINERY).unmet_demand == pytest.approx(
        _resource(leo_before, ids.MACHINERY).unmet_demand
    )

def test_resource_group_definition_fails_closed_when_member_resource_is_missing():
    app = build_game_application()
    group_id = DefinitionId("test.group.invalid")
    app._catalog.resource_groups[group_id] = ResourceGroupDef(
        group_id, "Invalid", (DefinitionId("missing.resource"),)
    )

    with pytest.raises(ConfigurationError, match="references missing resources"):
        validate_catalog_coverage(app._simulation, app._catalog)

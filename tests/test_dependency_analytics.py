from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import GetDependencyAnalytics, build_game_application
from space_idle.catalog import ResourceGroupDef
from space_idle.content import base_ids as ids
from space_idle.content.base_game import EARTH, LEO
from space_idle.persistence import load_game, save_game
from space_idle.shared import DefinitionId, EntityId
from space_idle.validation import validate_catalog_coverage
from space_idle.validation_support import ConfigurationError
from space_idle.transport.models import CargoFlowBatch


def _resource(view, resource_id):
    return next(row for row in view.resources if row.id == str(resource_id))


def test_scope_boundary_changes_import_export_without_double_counting_internal_flow():
    app = build_game_application()
    sim = app._simulation
    sim.logistics.cargo_flows[EntityId("flow.analytics.scope")] = CargoFlowBatch(
        EntityId("flow.analytics.scope"), ids.WATER, 12.0,
        EARTH, LEO, None, None, "test", EntityId("analytics.owner"), 50,
        ("analytics.service",), (LEO,), sim.day, sim.day + 2,
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


def test_content_defined_resource_group_aggregates_resource_metrics_without_core_special_case():
    app = build_game_application()
    group_id = DefinitionId("test.group.volatiles")
    app._catalog.resource_groups[group_id] = ResourceGroupDef(
        group_id, "Volatiles", (ids.WATER, ids.OXYGEN, ids.HYDROGEN)
    )

    view = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))
    group = next(row for row in view.resource_groups if row.id == str(group_id))
    members = [row for row in view.resources if row.id in group.member_resource_ids]

    assert group.local_production_per_day == pytest.approx(
        sum(row.local_production_per_day for row in members)
    )
    assert group.local_consumption_per_day == pytest.approx(
        sum(row.local_consumption_per_day for row in members)
    )
    assert group.imports_pipeline == pytest.approx(sum(row.imports_pipeline for row in members))
    assert group.exports_pipeline == pytest.approx(sum(row.exports_pipeline for row in members))



def test_resource_group_does_not_use_one_resource_surplus_to_cover_another_resource_deficit():
    app = build_game_application()
    group_id = DefinitionId("test.group.non_substitutable")
    app._catalog.resource_groups[group_id] = ResourceGroupDef(
        group_id, "Non-substitutable", (ids.WATER, ids.MACHINERY)
    )

    view = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))
    water = _resource(view, ids.WATER)
    machinery = _resource(view, ids.MACHINERY)
    group = next(row for row in view.resource_groups if row.id == str(group_id))

    assert water.local_production_per_day > machinery.local_demand_per_day
    assert machinery.external_dependency_per_day > 0
    assert group.external_dependency_per_day == pytest.approx(
        water.external_dependency_per_day + machinery.external_dependency_per_day
    )
    assert group.local_coverage_ratio == pytest.approx(
        (
            max(0.0, water.local_demand_per_day - water.external_dependency_per_day)
            + max(0.0, machinery.local_demand_per_day - machinery.external_dependency_per_day)
        ) / (water.local_demand_per_day + machinery.local_demand_per_day)
    )


def test_current_authorized_transport_is_projected_as_boundary_flow_and_operation_consumption():
    app = build_game_application()
    sim = app._simulation
    sim.technology.completed.update({ids.TECH_ORBITAL_OPERATIONS, ids.TECH_CISLUNAR_LOGISTICS})
    sim.logistics.external_services.clear()
    sim.logistics.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=1, day=sim.day
    )
    sim.logistics.create_lane(EARTH, LEO, 100.0, 100)
    sim.projects.plan_build(
        ids.ORBITAL_LOGISTICS_NODE, LEO, 50, "import_now", day=sim.day,
        import_source_id=EARTH,
    )
    sim.projects.advance_procurement(sim.day)
    for demand in sim.projects.resource_demands(sim.day):
        sim.inventory.add(EARTH, demand.resource_id, demand.amount_t + 5.0)

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



def test_partial_current_dispatch_reduces_but_does_not_hide_unmet_demand():
    app = build_game_application()
    sim = app._simulation
    sim.technology.completed.update({ids.TECH_ORBITAL_OPERATIONS, ids.TECH_CISLUNAR_LOGISTICS})
    sim.logistics.external_services.clear()
    sim.logistics.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=1, day=sim.day
    )
    sim.logistics.create_lane(EARTH, LEO, 100.0, 100)
    sim.projects.plan_build(
        ids.ORBITAL_LOGISTICS_NODE, LEO, 50, "import_now", day=sim.day,
        import_source_id=EARTH,
    )
    sim.projects.advance_procurement(sim.day)
    demands = sim.projects.resource_demands(sim.day)
    for demand in demands:
        sim.inventory.stock[(EARTH, demand.resource_id)] = demand.amount_t + 5.0
    machinery = next(demand for demand in demands if demand.resource_id == ids.MACHINERY)
    sim.inventory.stock[(EARTH, machinery.resource_id)] = machinery.amount_t / 2.0

    view = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),)))
    row = _resource(view, ids.MACHINERY)

    assert row.external_inflow_per_day > 0
    assert row.unmet_demand > 0
    assert row.unmet_demand < machinery.amount_t


def test_dependency_analytics_query_is_observational():
    app = build_game_application()
    sim = app._simulation
    stock_before = dict(sim.inventory.stock)
    reserved_before = dict(sim.inventory.reserved)
    flows_before = dict(sim.logistics.cargo_flows)
    funds_before = sim.external_economy.account.funds_musd
    day_before = sim.day

    app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))

    assert sim.day == day_before
    assert sim.inventory.stock == stock_before
    assert sim.inventory.reserved == reserved_before
    assert sim.logistics.cargo_flows == flows_before
    assert sim.external_economy.account.funds_musd == pytest.approx(funds_before)

def test_resource_group_definition_fails_closed_when_member_resource_is_missing():
    app = build_game_application()
    group_id = DefinitionId("test.group.invalid")
    app._catalog.resource_groups[group_id] = ResourceGroupDef(
        group_id, "Invalid", (DefinitionId("missing.resource"),)
    )

    with pytest.raises(ConfigurationError, match="references missing resources"):
        validate_catalog_coverage(app._simulation, app._catalog)

def test_dependency_analytics_is_derived_again_after_load(tmp_path):
    app = build_game_application()
    sim = app._simulation
    sim.logistics.cargo_flows[EntityId("flow.analytics.persist")] = CargoFlowBatch(
        EntityId("flow.analytics.persist"), ids.WATER, 7.0,
        EARTH, LEO, None, None, "test", EntityId("analytics.owner"), 50,
        ("analytics.service",), (LEO,), sim.day, sim.day + 2,
    )
    before = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),)))

    path = tmp_path / "analytics-save.json"
    save_game(app, path, saved_at=datetime(2026, 9, 14, tzinfo=timezone.utc))
    loaded, offline = load_game(path, build_game_application)
    assert offline is None
    after = loaded.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),)))

    assert after == before

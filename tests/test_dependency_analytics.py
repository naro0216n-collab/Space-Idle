from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import GetDependencyAnalytics, build_game_application
from space_idle.catalog import ResourceGroupDef
from space_idle.content import base_ids as ids
from space_idle.content.base_game import EARTH, LEO
from space_idle.persistence import load_game, save_game
from space_idle.shared import DefinitionId, EntityId
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
    assert set(view.critical_dependency_resource_ids) == {row.id for row in unmet}
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

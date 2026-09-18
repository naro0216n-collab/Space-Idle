from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from space_idle import SetGlobalLogisticsPolicy, build_game_application
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content import base_ids as ids
from space_idle.content.base_scenario import STANDARD_SCENARIO_ID, build_standard_scenario_definition
from space_idle.content.base_spatial import BASE_WORLD_DEFINITION_ID, build_world_definition
from space_idle.persistence import SaveFormatError, load_game, save_game


def test_world_scenario_and_load_boundaries_keep_static_definition_runtime_state_and_identity_separate(tmp_path):
    graph, _environment = build_world_definition()
    assert graph.operational_node_states == {}
    assert graph.locations == {}
    assert ids.LEO in graph.nodes
    assert ids.LUNAR_ORBIT in graph.nodes
    assert graph.surface_cells

    load_app = build_game_application_for_load()
    load_sim = load_app._simulation
    assert not load_sim.runtime_state_initialized
    assert load_sim.graph.nodes
    assert load_sim.graph.surface_cells
    assert load_sim.facilities.definitions
    assert load_sim.transport.vehicle_defs
    assert load_sim.market.provider_defs
    assert load_sim.graph.operational_node_states == {}
    assert load_sim.graph.locations == {}
    assert load_sim.facilities.facilities == {}
    assert load_sim.transport.fleet_pools == {}
    assert load_sim.inventory.stock == {}
    assert load_sim.storage.infrastructure_capacity_t == {}
    assert load_sim.market.funds.balance == 0.0
    assert load_sim.market.provider_states == {}
    assert load_sim.market.interfaces == {}
    assert load_sim.survey is not None and load_sim.survey.knowledge_progress == {}

    app = build_game_application()
    sim = app._simulation
    assert app.world_definition_id == BASE_WORLD_DEFINITION_ID
    assert app.scenario_id == STANDARD_SCENARIO_ID
    assert sim.runtime_state_initialized
    assert sim.graph.has_operational_node(ids.EARTH)
    assert sim.graph.has_operational_node(ids.LEO)
    assert sim.graph.has_operational_node(ids.LUNAR_ORBIT)
    assert all(location.body_id != ids.MOON for location in sim.graph.locations.values())
    assert sim.facilities.facilities
    assert sim.transport.fleet_pools
    assert sim.inventory.stock
    assert sim.market.provider_states
    assert sim.market.interfaces

    with pytest.raises(ValueError, match="initial runtime state has already been established"):
        build_standard_scenario_definition().apply(sim)


    app = build_game_application()
    assert app._simulation.logistics.global_policy_id is not None
    app.execute(SetGlobalLogisticsPolicy(None))

    path = tmp_path / "identity.json"
    save_game(
        app,
        path,
        saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    loaded, offline = load_game(path, build_game_application_for_load)
    assert offline is None
    assert loaded._simulation.logistics.global_policy_id is None

    original = json.loads(path.read_text(encoding="utf-8"))

    for field in ("world_definition_id", "scenario_id"):
        payload = dict(original)
        payload[field] = "test.mismatched.definition"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SaveFormatError, match="mismatch"):
            load_game(path, build_game_application_for_load)

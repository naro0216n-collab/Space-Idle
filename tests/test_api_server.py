from __future__ import annotations

import http.client
import json
from threading import Thread

from space_idle import build_game_application
from space_idle.bootstrap import build_game_application_for_load
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.content import base_ids as ids


def _request(port: int, method: str, path: str, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    raw = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = dict(headers or {})
    if raw is not None:
        request_headers.setdefault("Content-Type", "application/json")
        request_headers.setdefault("Content-Length", str(len(raw)))
    conn.request(method, path, body=raw, headers=request_headers)
    response = conn.getresponse()
    data = response.read()
    response_headers = dict(response.getheaders())
    conn.close()
    parsed = None if not data else json.loads(data.decode("utf-8"))
    return response.status, response_headers, parsed


def _raw_request(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    response = conn.getresponse()
    data = response.read()
    headers = dict(response.getheaders())
    status = response.status
    conn.close()
    return status, headers, data


def test_http_api_command_query_and_save_load_boundary(tmp_path):
    runtime = GameRuntime(new_game_factory=build_game_application, load_factory=build_game_application_for_load, save_dir=tmp_path)
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, payload = _request(
            port, "POST", "/api/v1/commands",
            {"type": "AdvanceTime", "payload": {"days": 2}},
        )
        assert status == 200
        assert payload["revision"] == 1

        status, _, payload = _request(port, "GET", "/api/v1/world")
        assert status == 200
        assert payload["data"]["day"] == 2
        assert payload["data"]["operational_nodes"]

        status, _, payload = _request(
            port, "GET",
            f"/api/v1/ui-state?operational_node_id={ids.EARTH}&surface_body_id={ids.EARTH_BODY}",
        )
        assert status == 200
        data = payload["data"]
        required = {
            "world", "operational_node", "surface_map", "logistics",
            "scientific_explorations", "market", "dependency_analytics_current", "dependency_analytics_forecast",
        }
        assert required <= data.keys()
        assert data["operational_node"]["id"] == str(ids.EARTH)
        assert data["surface_map"]["body_id"] == str(ids.EARTH_BODY)
        assert data["dependency_analytics_current"]["time_basis"] == "CURRENT"
        assert data["dependency_analytics_forecast"]["time_basis"] == "FORECAST"

        status, _, payload = _request(
            port, "GET",
            f"/api/v1/target-stock-options?destination_id={ids.EARTH}&resource_id={ids.STRUCTURAL_COMPONENTS}",
        )
        assert status == 200
        target_stock_options = payload["data"]
        assert target_stock_options["destination_id"] == str(ids.EARTH)
        assert target_stock_options["resource_id"] == str(ids.STRUCTURAL_COMPONENTS)
        assert target_stock_options["normal_demand_t_per_day"] > 0
        assert [row["display_name"] for row in target_stock_options["presets"]] == ["1日分", "3日分", "7日分"]

        allocation_options_status, _, allocation_options_payload = _request(
            port, "GET",
            f"/api/v1/transport-allocation-options?source_id={ids.EARTH}&destination_id={ids.LEO}",
        )
        assert allocation_options_status == 200
        allocation_option = next(
            row for row in allocation_options_payload["data"]["options"]
            if row["vehicle_definition_id"] == str(ids.REUSABLE_LAUNCH_VEHICLE)
        )
        one_unit = next(row for row in allocation_option["capacity_presets"] if row["units"] == 1)
        preview_status, _, preview_payload = _request(
            port, "GET",
            "/api/v1/transport-allocation-preview"
            f"?vehicle_definition_id={ids.REUSABLE_LAUNCH_VEHICLE}"
            f"&source_id={ids.EARTH}&destination_id={ids.LEO}"
            f"&target_forward_t_per_day={one_unit['capacity']['forward_t_per_day']}"
            f"&target_reverse_t_per_day={one_unit['capacity']['reverse_t_per_day']}",
        )
        assert preview_status == 200
        assert preview_payload["data"]["required_units"] == 1
        assert preview_payload["data"]["selected_forward_path"] == allocation_option["forward_path"]

        status, _, payload = _request(
            port, "GET",
            f"/api/v1/dependency-analytics?scope_kind=operational_nodes&node_id={ids.EARTH}&time_basis=FORECAST",
        )
        assert status == 200
        assert payload["data"]["time_basis"] == "FORECAST"
        assert payload["data"]["forecast_resources"]
        assert not payload["data"]["current_resources"]

        status, _, payload = _request(
            port, "GET",
            f"/api/v1/detailed-forecast?scope_kind=operational_nodes&node_id={ids.EARTH}&horizon=SHORT_TERM&period_days=2",
        )
        assert status == 200
        assert payload["data"]["base_day"] == 2
        assert payload["data"]["projected_day"] == 4
        assert payload["data"]["period_days"] == 2
        assert payload["data"]["inventory"]

        # Exercise nested command decoding through the real HTTP boundary.
        # Domain validation should reject this not-yet-surveyed founding target,
        # proving the typed target reached the application command contract.
        status, _, payload = _request(
            port, "POST", "/api/v1/commands",
            {
                "type": "PlanOperationalNodeFounding",
                "payload": {
                    "staging_node_id": str(ids.LUNAR_ORBIT),
                    "display_name": "HTTP Lunar Target",
                    "target_spec": {
                        "target_type": "surface_location",
                        "body_id": str(ids.MOON),
                        "core_cell_id": str(ids.MOON_CELL_FARSIDE_HIGHLANDS),
                    },
                    "deployment_recipe_id": str(ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE),
                    "vehicle_definition_id": str(ids.REUSABLE_SURFACE_CARGO_LANDER),
                },
            },
        )
        assert status == 400
        assert payload["error"]["code"] == "invalid_command"
        assert "knowledge_requirement" in payload["error"]["message"]

        # Survey Campaign crosses the HTTP codec as a multi-target intent with a nested
        # optional provider constraint; the query must expose the same authoritative scope.
        survey_cells = [str(ids.MOON_CELL_SOUTH_POLAR_RIDGE), str(ids.MOON_CELL_FARSIDE_HIGHLANDS)]
        preview_path = (
            "/api/v1/survey-campaign-intent-preview"
            f"?target_cell_id={survey_cells[0]}"
            f"&target_cell_id={survey_cells[1]}"
            f"&resource_id={ids.WATER}"
            "&goal_knowledge_level=1"
        )
        status, _, payload = _request(port, "GET", preview_path)
        assert status == 200
        assert payload["data"]["can_apply"] is True
        assert payload["data"]["blockers"] == []
        status, _, payload = _request(
            port, "POST", "/api/v1/commands",
            {
                "type": "StartSurvey",
                "payload": {
                    "target_cell_ids": survey_cells,
                    "resource_ids": [str(ids.WATER)],
                    "goal_knowledge_level": 1,
                    "provider_constraint": {
                        "provider_definition_id": str(ids.LUNAR_RESOURCE_SURVEY_ORBITER),
                        "operational_node_id": str(ids.LUNAR_ORBIT),
                    },
                    "observation_mode_constraint": "remote_orbital_spectrometry",
                    "priority": 4,
                },
            },
        )
        assert status == 200
        campaign_id = payload["data"]["created_id"]
        assert campaign_id
        status, _, payload = _request(
            port, "GET",
            f"/api/v1/ui-state?operational_node_id={ids.LUNAR_ORBIT}&surface_body_id={ids.MOON}",
        )
        assert status == 200
        campaign = next(row for row in payload["data"]["surveys"]["campaigns"] if row["id"] == campaign_id)
        assert set(campaign["target_cell_ids"]) == set(survey_cells)
        assert campaign["resource_ids"] == [str(ids.WATER)]
        assert campaign["goal_knowledge_level"] == 1
        assert campaign["priority"] == 4
        assert campaign["projected_provider_definition_id"] == str(ids.LUNAR_RESOURCE_SURVEY_ORBITER)
        assert campaign["projected_provider_display_name"]
        assert "base." not in campaign["projected_provider_display_name"]

        status, _, payload = _request(port, "GET", preview_path)
        assert status == 200
        assert payload["data"]["can_apply"] is False
        conflict = next(
            blocker
            for blocker in payload["data"]["blockers"]
            if blocker["code"].startswith("campaign_scope_conflict:")
        )
        assert conflict["severity"] == "blocking"
        assert conflict["affected_action"] == "start_survey"
        assert conflict["related_entity_kind"] == "survey_campaign"

        status, _, payload = _request(port, "POST", "/api/v1/session/save", {"slot": "boundary"})
        assert status == 200 and payload["data"]["saved"] is True

        _request(port, "POST", "/api/v1/commands", {"type": "AdvanceTime", "payload": {"days": 3}})
        status, _, payload = _request(
            port, "POST", "/api/v1/session/load",
            {"slot": "boundary", "apply_offline": False},
        )
        assert status == 200 and payload["data"]["loaded"] is True
        status, _, payload = _request(port, "GET", "/api/v1/world")
        assert status == 200 and payload["data"]["day"] == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

def test_http_api_rejects_stale_command_revision(tmp_path):
    runtime = GameRuntime(new_game_factory=build_game_application, load_factory=build_game_application_for_load, save_dir=tmp_path)
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0, cors_origins=("*",)))
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, payload = _request(
            port, "POST", "/api/v1/commands",
            {"type": "AdvanceTime", "payload": {"days": 1}},
            headers={"If-Match": '"rev-0"'},
        )
        assert status == 200 and payload["revision"] == 1

        status, headers, payload = _request(
            port, "POST", "/api/v1/commands",
            {"type": "AdvanceTime", "payload": {"days": 1}},
            headers={"If-Match": '"rev-0"'},
        )
        assert status == 409
        assert payload["error"]["code"] == "revision_conflict"
        assert payload["error"]["details"]["current_revision"] == 1
        assert headers.get("X-Space-Idle-Revision") == "1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ui_state_conditional_refresh_skips_projection_until_revision_changes(tmp_path, monkeypatch):
    runtime = GameRuntime(
        new_game_factory=build_game_application,
        load_factory=build_game_application_for_load,
        save_dir=tmp_path,
    )
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        path = f"/api/v1/ui-state?operational_node_id={ids.EARTH}"
        status, headers, payload = _request(port, "GET", path)
        assert status == 200
        assert payload["revision"] == 0
        etag = headers["ETag"]
        assert etag.startswith('"ui-state-0-')

        original_query_many = runtime._app.query_many
        projection_calls = 0

        def counted_query_many(queries):
            nonlocal projection_calls
            projection_calls += 1
            return original_query_many(queries)

        monkeypatch.setattr(runtime._app, "query_many", counted_query_many)
        status, headers, payload = _request(
            port,
            "GET",
            path,
            headers={"X-Space-Idle-Known-View": etag},
        )
        assert status == 204
        assert payload is None
        assert projection_calls == 0
        assert headers["ETag"] == etag
        assert headers["X-Space-Idle-Revision"] == "0"

        # An ETag belongs to one concrete UI-state representation. Reusing the
        # Earth-node ETag for another scope must not suppress that projection.
        other_path = f"/api/v1/ui-state?operational_node_id={ids.LUNAR_ORBIT}"
        status, _, payload = _request(
            port,
            "GET",
            other_path,
            headers={"X-Space-Idle-Known-View": etag},
        )
        assert status == 200
        assert payload["data"]["operational_node"]["id"] == str(ids.LUNAR_ORBIT)
        assert projection_calls == 1

        status, _, payload = _request(
            port,
            "POST",
            "/api/v1/commands",
            {"type": "AdvanceTime", "payload": {"days": 1}},
        )
        assert status == 200
        assert payload["revision"] == 1

        status, headers, payload = _request(
            port,
            "GET",
            path,
            headers={"X-Space-Idle-Known-View": etag},
        )
        assert status == 200
        assert payload["revision"] == 1
        assert projection_calls == 2
        assert headers["ETag"].startswith('"ui-state-1-')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_static_webui_is_served_and_path_traversal_is_rejected(tmp_path):
    runtime = GameRuntime(new_game_factory=build_game_application, load_factory=build_game_application_for_load, save_dir=tmp_path)
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, body = _raw_request(port, "/")
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert body

        status, _, _ = _raw_request(port, "/%2e%2e/%2e%2e/README.md")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

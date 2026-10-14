from __future__ import annotations

import http.client
import json
from threading import Thread
from contextlib import contextmanager

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


@contextmanager
def running_api(tmp_path):
    """Give each HTTP scenario an isolated server and game runtime."""
    runtime = GameRuntime(
        new_game_factory=build_game_application,
        load_factory=build_game_application_for_load,
        save_dir=tmp_path,
    )
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    # The default 0.5s serve_forever poll delay only slows shutdown in
    # short-lived HTTP contract tests; it is not part of HTTP semantics.
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_command_and_world_read_cross_json_boundary(tmp_path):
    with running_api(tmp_path) as port:
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

        # Optimistic revision checking is part of the same HTTP Command boundary.
        status, headers, rejected = _request(
            port, "POST", "/api/v1/commands",
            {"type": "AdvanceTime", "payload": {"days": 1}},
            headers={"If-Match": '"rev-0"'},
        )
        assert status == 409
        assert rejected["error"]["code"] == "revision_conflict"
        assert rejected["error"]["details"]["current_revision"] == 1
        assert headers["X-Space-Idle-Revision"] == "1"
        assert _request(port, "GET", "/api/v1/world")[2]["data"]["day"] == 2

        # The independent finite passenger intent uses real HTTP Command and
        # Query contracts; setting a Population Target is not a prerequisite.
        status, _, payload = _request(port, "GET", f"/api/v1/population/passenger-preview?origin_node_id={ids.EARTH}&destination_node_id={ids.LEO}&requested_count=2")
        assert status == 200 and payload["data"]["requested_count"] == 2
        status, _, payload = _request(port, "POST", "/api/v1/commands", {
            "type": "RequestPassengerTransfer", "payload": {
                "origin_node_id": str(ids.EARTH), "destination_node_id": str(ids.LEO),
                "requested_count": 2, "capacity_source_constraint": {
                    "dedicated_vehicle_definition_id": str(ids.REUSABLE_LAUNCH_VEHICLE),
                    "dedicated_units": 1,
                },
            },
        })
        assert status == 200 and payload["data"]["created_id"]
        order_id = payload["data"]["created_id"]
        status, _, payload = _request(port, "GET", "/api/v1/population/passenger-transfers")
        assert status == 200 and payload["data"]["items"][0]["id"] == order_id
        status, _, payload = _request(port, "POST", "/api/v1/commands", {
            "type": "CancelPassengerTransfer", "payload": {"order_id": order_id},
        })
        assert status == 200


def test_http_decision_views_route_and_scoped_json_boundary(tmp_path):
    """HTTP owns routing, scope arguments and JSON transport, not Domain arithmetic."""
    with running_api(tmp_path) as port:
        status, _, payload = _request(
            port, "GET",
            f"/api/v1/ui-state?operational_node_id={ids.EARTH}&surface_body_id={ids.EARTH_BODY}",
        )
        assert status == 200
        assert {
            "world", "operational_node", "surface_map", "logistics", "market",
            "scientific_explorations", "dependency_analytics_current", "dependency_analytics_forecast",
        } <= payload["data"].keys()
        assert payload["data"]["operational_node"]["id"] == str(ids.EARTH)
        assert payload["data"]["surface_map"]["body_id"] == str(ids.EARTH_BODY)

        # Exercise each distinct query decoder and serialization route. Numerical
        # forecasts, eligibility and candidate selection belong to Application tests.
        urls = (
            f"/api/v1/surfaces/{ids.MOON}",
            f"/api/v1/surfaces/{ids.MOON}?founding_cell_id={ids.MOON_CELL_FARSIDE_HIGHLANDS}",
            "/api/v1/non-surface-founding-options?body_id=base.body.jupiter",
            f"/api/v1/target-stock-context?destination_id={ids.EARTH}&resource_id={ids.STRUCTURAL_COMPONENTS}",
            f"/api/v1/dependency-analytics?scope_kind=operational_nodes&node_id={ids.EARTH}&time_basis=FORECAST",
            f"/api/v1/detailed-forecast?scope_kind=operational_nodes&node_id={ids.EARTH}&horizon=SHORT_TERM&period_days=2",
        )
        for url in urls:
            status, _, response = _request(port, "GET", url)
            assert status == 200, url
            assert isinstance(response["data"], dict), url

        # Preview parses the directional capacity targets through the HTTP codec.
        status, _, allocation_options = _request(
            port, "GET",
            f"/api/v1/transport-allocation-options?source_id={ids.EARTH}&destination_id={ids.LEO}",
        )
        assert status == 200
        option = next(row for row in allocation_options["data"]["options"]
                      if row["vehicle_definition_id"] == str(ids.REUSABLE_LAUNCH_VEHICLE))
        nominal = option["nominal_capacity"]
        status, _, preview = _request(
            port, "GET", "/api/v1/transport-allocation-preview"
            f"?vehicle_definition_id={ids.REUSABLE_LAUNCH_VEHICLE}"
            f"&source_id={ids.EARTH}&destination_id={ids.LEO}"
            f"&target_forward_t_per_day={nominal['forward_t_per_day']}"
            f"&target_reverse_t_per_day={nominal['reverse_t_per_day']}",
        )
        assert status == 200
        assert preview["data"]["required_units"] == 1

        # A selected cell must belong to the selected body at the HTTP boundary.
        status, _, response = _request(
            port, "GET",
            f"/api/v1/ui-state?surface_body_id={ids.MOON}&founding_cell_id={ids.EARTH_CELL_INDUSTRIAL}",
        )
        assert status in (400, 422)
        assert response["error"]["code"]


def test_http_nested_intent_and_save_load_boundary(tmp_path):
    with running_api(tmp_path) as port:
        status, _, payload = _request(
            port, "POST", "/api/v1/commands",
            {"type": "AdvanceTime", "payload": {"days": 2}},
        )
        assert status == 200
        assert payload["revision"] == 1

        # Exercise nested command decoding through the real HTTP boundary.
        # Founding uses a typed target and a shared Application command contract.
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
                    "deployment_recipe_id": str(ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE),
                    "vehicle_definition_id": str(ids.REUSABLE_SURFACE_CARGO_LANDER),
                },
            },
        )
        assert status == 200
        assert payload["data"]["created_id"] is not None

        # Survey Campaign crosses the HTTP codec as a multi-target intent with a nested
        # optional provider constraint; the query must expose the same authoritative scope.
        survey_cells = [str(ids.MOON_CELL_SOUTH_POLAR_RIDGE), str(ids.MOON_CELL_FARSIDE_HIGHLANDS)]
        preview_path = (
            "/api/v1/survey-campaign-intent-preview"
            f"?target_cell_id={survey_cells[0]}"
            f"&target_cell_id={survey_cells[1]}"
            f"&resource_id={ids.VOLATILE_BEARING_MATERIAL}"
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
                    "resource_ids": [str(ids.VOLATILE_BEARING_MATERIAL)],
                    "goal_knowledge_level": 1,
                    "provider_constraint": {
                        "provider_definition_id": str(ids.ORBITAL_RESOURCE_MAPPING_PROVIDER),
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
        assert campaign["resource_ids"] == [str(ids.VOLATILE_BEARING_MATERIAL)]
        assert campaign["goal_knowledge_level"] == 1
        assert campaign["priority"] == 4
        assert campaign["projected_provider_definition_id"] == str(ids.ORBITAL_RESOURCE_MAPPING_PROVIDER)
        assert campaign["projected_provider_display_name"]
        assert campaign["projected_provider_display_name"] != campaign["projected_provider_definition_id"]

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

        # Save slots are portable filenames across supported hosts, including Windows.
        for invalid_slot in ("CON", "bad:name", "trailing."):
            status, _, payload = _request(
                port, "POST", "/api/v1/session/save", {"slot": invalid_slot}
            )
            assert status == 400
            assert payload["error"]["code"] == "invalid_request"

        (tmp_path / "broken.json").write_bytes(b"\xff\xfe\x00not-json")
        status, _, payload = _request(
            port, "POST", "/api/v1/session/load",
            {"slot": "broken", "apply_offline": False},
        )
        assert status == 400
        assert payload["error"]["code"] == "invalid_save"




def test_ui_state_conditional_refresh_uses_scope_specific_view_tokens_and_revision_invalidation(tmp_path):
    with running_api(tmp_path) as port:
        # The view-token contract needs a representative Surface scope, not
        # an unfiltered payload of every Survey target in the Solar System.
        surface_scope = f"&surface_body_id={ids.EARTH_BODY}"
        path = f"/api/v1/ui-state?operational_node_id={ids.EARTH}{surface_scope}"
        status, headers, payload = _request(port, "GET", path)
        assert status == 200
        assert payload["revision"] == 0
        etag = headers["ETag"]
        assert etag and etag.startswith('"') and etag.endswith('"')

        status, headers, payload = _request(
            port,
            "GET",
            path,
            headers={"X-Space-Idle-Known-View": etag},
        )
        assert status == 200
        assert payload["data"] == {"unchanged": True}
        assert payload["revision"] == 0
        assert headers["ETag"] == etag
        assert headers["X-Space-Idle-Revision"] == "0"

        # An ETag belongs to one concrete UI-state representation. Reusing the
        # Earth-node ETag for another scope must not suppress that projection.
        other_path = f"/api/v1/ui-state?operational_node_id={ids.LUNAR_ORBIT}{surface_scope}"
        status, _, payload = _request(
            port,
            "GET",
            other_path,
            headers={"X-Space-Idle-Known-View": etag},
        )
        assert status == 200
        assert payload["data"]["operational_node"]["id"] == str(ids.LUNAR_ORBIT)

        # The inspection node is independent of the execution node. Scope
        # changes invalidate the composite view token and constrain Movement.
        inspect_path = (
            f"/api/v1/ui-state?operational_node_id={ids.EARTH}"
            f"&inspect_node_id={ids.LUNAR_ORBIT}{surface_scope}"
        )
        status, _, payload = _request(port, "GET", inspect_path, headers={"X-Space-Idle-Known-View": etag})
        assert status == 200
        inspected = payload["data"]
        assert inspected["operational_node"]["id"] == str(ids.EARTH)
        assert inspected["inspected_node"]["id"] == str(ids.LUNAR_ORBIT)
        assert inspected["inspected_flow"]["operational_node_id"] == str(ids.LUNAR_ORBIT)
        assert all(
            str(ids.LUNAR_ORBIT) in (plan["origin_id"], plan["destination_id"])
            for plan in inspected["movement_plans"]["items"]
        )

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
        assert headers["ETag"] != etag
        assert headers["ETag"] and headers["ETag"].startswith('"')


def test_static_webui_is_served_and_path_traversal_is_rejected(tmp_path):
    with running_api(tmp_path) as port:
        status, headers, body = _raw_request(port, "/")
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert body

        status, _, _ = _raw_request(port, "/%2e%2e/%2e%2e/README.md")
        assert status == 404

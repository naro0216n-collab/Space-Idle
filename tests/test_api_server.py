from __future__ import annotations

import gzip
import http.client
import json
from threading import Thread

from space_idle import build_game_application
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.application_commands import (
    GetCatalog, GetFlowReport, GetLogisticsSummary, GetRoutes, GetWorld,
)
from space_idle.api.codec import to_jsonable
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
    if response_headers.get("Content-Encoding") == "gzip":
        data = gzip.decompress(data)
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


def test_ui_reports_and_split_logistics_queries_are_json_safe():
    app = build_game_application()
    catalog = app.query(GetCatalog())
    assert catalog.processes
    assert catalog.research
    assert catalog.routes
    assert catalog.transport_services
    assert to_jsonable(catalog)

    flow = app.query(GetFlowReport(str(ids.EARTH)))
    assert flow.location_id == str(ids.EARTH)
    assert isinstance(to_jsonable(flow)["issues"], list)

    summary = app.query(GetLogisticsSummary())
    assert summary.route_count > 0
    compact_routes = app.query(GetRoutes(include_modes=False))
    assert compact_routes.items and all(not route.modes for route in compact_routes.items)
    one_route = app.query(GetRoutes(route_id="base.route.earth_leo", include_modes=True))
    assert len(one_route.items) == 1 and one_route.items[0].modes


def test_http_api_revision_etag_gzip_command_and_save_load(tmp_path):
    runtime = GameRuntime(factory=build_game_application, save_dir=tmp_path)
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0, cors_origins=("*",), gzip_min_bytes=200))
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, payload = _request(port, "GET", "/api/v1/catalog", headers={"Accept-Encoding": "gzip"})
        assert status == 200
        assert headers.get("Content-Encoding") == "gzip"
        assert payload["ok"] is True
        etag = headers["ETag"]

        status, _, payload = _request(port, "GET", "/api/v1/catalog", headers={"If-None-Match": etag})
        assert status == 304 and payload is None

        status, _, payload = _request(port, "POST", "/api/v1/commands", {"type": "AdvanceTime", "payload": {"days": 2}})
        assert status == 200 and payload["revision"] == 1

        status, _, payload = _request(port, "GET", "/api/v1/world")
        assert status == 200 and payload["data"]["day"] == 2

        status, _, payload = _request(port, "GET", "/api/v1/logistics/routes?include_modes=false")
        assert status == 200 and payload["data"]["items"]
        assert all(not row["modes"] for row in payload["data"]["items"])

        status, _, payload = _request(
            port,
            "GET",
            "/api/v1/transport-allocation-options"
            "?source_id=base.node.low_earth_orbit"
            "&destination_id=base.node.lunar_orbit",
        )
        assert status == 200
        assert payload["data"]["options"]
        assert all("nominal_capacity" in row for row in payload["data"]["options"])
        assert all("blockers" in row for row in payload["data"]["options"])

        status, _, payload = _request(
            port,
            "GET",
            "/api/v1/logistics/fleet-relocation-preview"
            "?vehicle_definition_id=base.vehicle.reusable_orbital_cargo_tug"
            "&units=1&source_id=base.node.low_earth_orbit"
            "&destination_id=base.node.lunar_orbit&path_policy=fastest",
        )
        assert status == 200
        assert payload["data"]["vehicle_definition_id"] == "base.vehicle.reusable_orbital_cargo_tug"
        assert "infrastructure_requirements" in payload["data"]
        assert "blockers" in payload["data"]

        status, _, payload = _request(port, "POST", "/api/v1/session/save", {"slot": "ipad-test"})
        assert status == 200 and payload["data"]["saved"] is True

        _request(port, "POST", "/api/v1/commands", {"type": "AdvanceTime", "payload": {"days": 3}})
        status, _, payload = _request(port, "POST", "/api/v1/session/load", {"slot": "ipad-test", "apply_offline": False})
        assert status == 200 and payload["data"]["loaded"] is True
        status, _, payload = _request(port, "GET", "/api/v1/world")
        assert payload["data"]["day"] == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)



def test_ui_state_exposes_scientific_exploration_and_vehicle_production(tmp_path):
    runtime = GameRuntime(factory=build_game_application, save_dir=tmp_path)
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, payload = _request(
            port, "GET", f"/api/v1/ui-state?location_id={ids.EARTH}"
        )
        assert status == 200
        data = payload["data"]
        exploration = data["scientific_explorations"]["items"][0]
        assert exploration["mission_duration_days"] > 0
        assert exploration["minimum_payload_t"] >= 0
        assert "required_vehicle_capabilities" in exploration
        assert exploration["origin_requirements"]["environment"]
        assert exploration["destination_requirements"]["environment"]
        assert data["logistics"]["vehicle_production_options"]
        assert "vehicle_production" in data["logistics"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

def test_http_api_cors_preflight_for_ipad_dev_client(tmp_path):
    runtime = GameRuntime(factory=build_game_application, save_dir=tmp_path)
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0, cors_origins=("*",)))
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, _ = _request(
            port, "OPTIONS", "/api/v1/commands",
            headers={
                "Origin": "http://192.168.1.10:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert status == 204
        assert headers.get("Access-Control-Allow-Origin") == "*"
        assert "POST" in headers.get("Access-Control-Allow-Methods", "")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_runtime_catches_up_elapsed_time_without_ipad_client_timer(tmp_path):
    from space_idle.simulation import OfflineProgressPolicy

    now = [100.0]
    runtime = GameRuntime(
        factory=build_game_application,
        save_dir=tmp_path,
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=10.0),
        clock=lambda: now[0],
    )
    assert runtime.metadata()["day"] == 0
    assert runtime.revision == 0

    now[0] += 25.0
    result = runtime.query(GetWorld())
    assert result.data.day == 2
    assert result.revision == 1

    again = runtime.query(GetWorld())
    assert again.data.day == 2
    assert again.revision == 1


def test_http_api_rejects_stale_command_revision(tmp_path):
    runtime = GameRuntime(factory=build_game_application, save_dir=tmp_path)
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


def test_development_webui_is_served_from_same_origin(tmp_path):
    runtime = GameRuntime(factory=build_game_application, save_dir=tmp_path)
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, body = _raw_request(port, "/")
        html = body.decode("utf-8")
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert "拠点運用" in html
        assert "物流ネットワーク" in html
        assert 'id="operationsView"' in html
        assert 'id="logisticsView"' in html
        assert 'href="/research_tree.css"' in html
        assert 'src="/research_tree.js"' in html
        assert 'src="/operations_ui.js"' in html
        assert 'src="/logistics_ui.js"' in html

        status, headers, body = _raw_request(port, "/app.css")
        css = body.decode("utf-8")
        assert status == 200
        assert headers["Content-Type"].startswith("text/css")
        assert "--design-min-width: 1180px" in css
        assert "horizontally scrollable" in css

        status, headers, body = _raw_request(port, "/app.js")
        app_js = body.decode("utf-8")
        assert status == 200
        assert headers["Content-Type"].startswith("text/javascript")
        assert "If-Match" in app_js

        status, headers, body = _raw_request(port, "/operations_ui.js")
        operations_js = body.decode("utf-8")
        assert status == 200
        assert headers["Content-Type"].startswith("text/javascript")
        assert "SpaceIdleResearchTree.render" in operations_js
        assert "FundResearchPrototype" in operations_js
        assert "StartScientificExploration" in operations_js
        assert "AssignExplorationFleet" in operations_js
        assert "AssignExplorationVehicle" not in operations_js

        status, headers, body = _raw_request(port, "/logistics_ui.js")
        logistics_js = body.decode("utf-8")
        assert status == 200
        assert headers["Content-Type"].startswith("text/javascript")
        assert "CreateTransportAllocation" in logistics_js
        assert "SubmitCargo" not in logistics_js
        assert "CreateLogisticsLane" in logistics_js
        assert "ProduceVehicle" in logistics_js
        assert "PauseVehicleProduction" in logistics_js

        status, headers, body = _raw_request(port, "/research_tree.css")
        assert status == 200
        assert headers["Content-Type"].startswith("text/css")
        assert b"research-tree-stage" in body

        status, headers, body = _raw_request(port, "/research_tree.js")
        assert status == 200
        assert headers["Content-Type"].startswith("text/javascript")
        assert b"SpaceIdleResearchTree" in body

        status, headers, body = _raw_request(port, "/time_control.css")
        assert status == 200
        assert headers["Content-Type"].startswith("text/css")

        status, _, _ = _raw_request(port, "/%2e%2e/%2e%2e/README.md")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

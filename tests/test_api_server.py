from __future__ import annotations

import http.client
import json
from threading import Thread

from space_idle import build_game_application
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
    runtime = GameRuntime(factory=build_game_application, save_dir=tmp_path)
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
            "scientific_explorations", "external_economy", "dependency_analytics",
        }
        assert required <= data.keys()
        assert data["operational_node"]["id"] == str(ids.EARTH)
        assert data["surface_map"]["body_id"] == str(ids.EARTH_BODY)

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


def test_static_webui_is_served_and_path_traversal_is_rejected(tmp_path):
    runtime = GameRuntime(factory=build_game_application, save_dir=tmp_path)
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

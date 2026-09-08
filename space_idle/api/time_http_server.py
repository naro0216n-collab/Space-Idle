from __future__ import annotations

import ssl
from urllib.parse import urlsplit

from .codec import ApiPayloadError
from .http_server import ApiServerConfig, SpaceIdleHTTPServer, SpaceIdleRequestHandler
from .runtime import GameRuntime


_OLD_TIME_CONTROLS = '''      <div class="time-controls" aria-label="時間進行">
        <button type="button" data-advance="1">+1日</button>
        <button type="button" data-advance="7">+7日</button>
        <button type="button" data-advance="30">+30日</button>
      </div>'''
_NEW_TIME_CONTROLS = '''      <div class="time-controls" aria-label="時間進行">
        <button type="button" id="timePauseButton" aria-label="一時停止" aria-pressed="false">⏸ 一時停止</button>
        <button type="button" data-time-speed="1" aria-label="進行速度1倍" aria-pressed="true">1×</button>
        <button type="button" data-time-speed="4" aria-label="進行速度4倍" aria-pressed="false">4×</button>
        <button type="button" data-time-speed="16" aria-label="進行速度16倍" aria-pressed="false">16×</button>
        <span id="timeState" hidden>自動進行 · 1×</span>
      </div>'''


class TimeControlledRequestHandler(SpaceIdleRequestHandler):
    """HTTP adapter extension for player-facing simulation clock controls."""

    def _write_time_controlled_index(self) -> None:
        path = self._webui_root() / "index.html"
        try:
            html = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._error(404, "not_found", "asset not found")
            return
        if _OLD_TIME_CONTROLS not in html:
            raise RuntimeError("WebUI time-control composition point not found")
        html = html.replace(_OLD_TIME_CONTROLS, _NEW_TIME_CONTROLS, 1)
        html = html.replace("v0.4.4", "v0.4.5")
        html = html.replace(
            '  <link rel="stylesheet" href="/app.css">\n',
            '  <link rel="stylesheet" href="/app.css">\n  <link rel="stylesheet" href="/time_control.css">\n',
            1,
        )
        html = html.replace(
            '  <script src="/app.js" defer></script>\n',
            '  <script src="/app.js" defer></script>\n  <script src="/time_control.js" defer></script>\n',
            1,
        )
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_webui(self, path: str) -> bool:
        if path in {"/", "/index.html"}:
            self._write_time_controlled_index()
            return True
        if path == "/time_control.css":
            self._write_static(self._webui_root() / "time_control.css", "text/css; charset=utf-8")
            return True
        if path == "/time_control.js":
            self._write_static(self._webui_root() / "time_control.js", "text/javascript; charset=utf-8")
            return True
        return super()._serve_webui(path)

    def _handle_post(self) -> None:
        path = urlsplit(self.path).path.rstrip("/") or "/"
        if path != "/api/v1/time-control":
            super()._handle_post()
            return

        body = self._read_json()
        if not isinstance(body, dict):
            raise ApiPayloadError("time-control body must be an object")
        unknown = sorted(set(body) - {"paused", "speed_multiplier"})
        if unknown:
            raise ApiPayloadError(f"unknown time-control fields: {', '.join(unknown)}")
        result = self.server.runtime.set_time_control(
            paused=body.get("paused"),
            speed_multiplier=body.get("speed_multiplier"),
        )
        self._result(result, etag=f'"rev-{result.revision}"')


def create_server(runtime: GameRuntime, config: ApiServerConfig = ApiServerConfig()) -> SpaceIdleHTTPServer:
    if bool(config.tls_certfile) != bool(config.tls_keyfile):
        raise ValueError("tls_certfile and tls_keyfile must be provided together")
    server = SpaceIdleHTTPServer(
        (config.host, config.port),
        TimeControlledRequestHandler,
        runtime=runtime,
        config=config,
    )
    if config.tls_certfile is not None and config.tls_keyfile is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(config.tls_certfile, config.tls_keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server

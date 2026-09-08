from __future__ import annotations

import argparse
from pathlib import Path
import socket

from ..bootstrap import build_game_application
from ..simulation import OfflineProgressPolicy
from .http_server import ApiServerConfig, create_server
from .runtime import GameRuntime



def _discover_lan_ip() -> str | None:
    """Best-effort address hint for another device on the same LAN."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        address = sock.getsockname()[0]
        return None if address.startswith("127.") else address
    except OSError:
        try:
            address = socket.gethostbyname(socket.gethostname())
            return None if address.startswith("127.") else address
        except OSError:
            return None
    finally:
        sock.close()

def main() -> None:
    parser = argparse.ArgumentParser(description="Space Idle development API server")
    parser.add_argument("--host", default="0.0.0.0", help="listen address; 0.0.0.0 allows iPad access on the LAN")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--save-dir", default="saves")
    parser.add_argument(
        "--cors-origin", action="append", dest="cors_origins",
        help="allowed Origin; repeatable. Defaults to * for trusted-LAN development",
    )
    parser.add_argument("--tls-cert", default=None, help="PEM certificate for HTTPS (recommended when the iPad WebUI uses HTTPS/PWA)")
    parser.add_argument("--tls-key", default=None, help="PEM private key matching --tls-cert")
    parser.add_argument("--offline-seconds-per-day", type=float, default=None)
    parser.add_argument("--offline-max-days", type=int, default=None)
    args = parser.parse_args()

    policy = None
    if args.offline_seconds_per_day is not None:
        policy = OfflineProgressPolicy(args.offline_seconds_per_day, args.offline_max_days)
    runtime = GameRuntime(factory=build_game_application, save_dir=Path(args.save_dir), offline_policy=policy)
    config = ApiServerConfig(
        host=args.host,
        port=args.port,
        cors_origins=tuple(args.cors_origins or ["*"]),
        tls_certfile=args.tls_cert,
        tls_keyfile=args.tls_key,
    )
    server = create_server(runtime, config)
    host, port = server.server_address[:2]
    scheme = "https" if args.tls_cert else "http"
    print(f"Space Idle WebUI + API listening on {scheme}://{host}:{port}/")
    if args.host in {"0.0.0.0", "::"}:
        lan_ip = _discover_lan_ip()
        if lan_ip:
            print(f"iPad Safari: open {scheme}://{lan_ip}:{port}/ on the same LAN")
        else:
            print(f"iPad Safari: open {scheme}://<PC LAN IPv4 address>:{port}/ on the same LAN")
    print("Development server: use only on a trusted local network; authentication is not implemented.")
    if not args.tls_cert:
        print("HTTP is sufficient for same-LAN Safari development. Use --tls-cert/--tls-key when secure-context/PWA testing is required.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

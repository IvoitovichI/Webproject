"""A small dependency-free web application for Docker Fundamentals HW1."""

from __future__ import annotations

import html
import json
import os
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def env_port() -> int:
    """Read and validate the HTTP port from the environment."""
    raw_port = os.getenv("PORT", "8080")
    try:
        port = int(raw_port)
    except ValueError as error:
        raise SystemExit(f"PORT must be an integer, got {raw_port!r}") from error

    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be between 1 and 65535")
    return port


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "HW1WebApp/1.0"

    def send_body(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_body(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP method name
        route = self.path.split("?", maxsplit=1)[0]

        if route == "/health":
            self.send_json(HTTPStatus.OK, {"status": "healthy"})
            return

        if route == "/api/info":
            self.send_json(
                HTTPStatus.OK,
                {
                    "app": os.getenv("APP_NAME", "Docker Fundamentals"),
                    "message": os.getenv(
                        "APP_MESSAGE", "The application is running in a container."
                    ),
                    "hostname": socket.gethostname(),
                },
            )
            return

        if route != "/":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        app_name = html.escape(os.getenv("APP_NAME", "Docker Fundamentals"))
        message = html.escape(
            os.getenv("APP_MESSAGE", "The application is running in a container.")
        )
        hostname = html.escape(socket.gethostname())
        page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{app_name}</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
            background: linear-gradient(135deg, #102a43, #0b7285); }}
    main {{ width: min(38rem, calc(100% - 3rem)); padding: 2.5rem;
            border: 1px solid #ffffff30; border-radius: 1rem;
            background: #081c2ccc; box-shadow: 0 1.5rem 4rem #0006; }}
    .status {{ color: #63e6be; font-weight: 700; }}
    code {{ padding: .2rem .45rem; border-radius: .3rem; background: #ffffff14; }}
  </style>
</head>
<body>
  <main>
    <p class="status">● Container is healthy</p>
    <h1>{app_name}</h1>
    <p>{message}</p>
    <p>Served by host <code>{hostname}</code>.</p>
    <p>Try <a href="/api/info">/api/info</a> or <a href="/health">/health</a>.</p>
  </main>
</body>
</html>
"""
        self.send_body(
            HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8"
        )

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = env_port()
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"Listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

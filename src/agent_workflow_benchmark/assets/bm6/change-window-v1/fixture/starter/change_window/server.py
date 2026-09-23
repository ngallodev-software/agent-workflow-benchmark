from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .planner import ChangeWindowValidationError, build_change_plan, load_change_set


class Handler(BaseHTTPRequestHandler):
    data_path: Path
    web_root = Path(__file__).resolve().parent / "web"

    def _json(self, status: int, value: object) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _static(self, relative: str) -> None:
        relative = relative.lstrip("/") or "index.html"
        candidate = (self.web_root / relative).resolve()
        try:
            candidate.relative_to(self.web_root.resolve())
        except ValueError:
            self.send_error(404)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        payload = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        if path == "/api/plan":
            try:
                value = load_change_set(self.data_path)
                plan = build_change_plan(value)
                payload = dict(plan)
                payload.setdefault("services", value["services"])
                payload.setdefault("window", value["window"])
            except (OSError, ChangeWindowValidationError, ValueError, TypeError) as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, payload)
            return
        if path == "/":
            self._static("index.html")
            return
        self._static(path)

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(host: str, port: int, data: Path) -> None:
    handler = type("ConfiguredHandler", (Handler,), {"data_path": data.resolve()})
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", type=Path, default=Path("data/change-set.json"))
    args = parser.parse_args()
    serve(args.host, args.port, args.data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

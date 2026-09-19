from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .priority import BacklogValidationError, load_backlog, rank_items

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"


class Handler(BaseHTTPRequestHandler):
    data_path = Path("data/backlog.json")

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: int, value: object) -> None:
        payload = json.dumps(value, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        path = urlparse(self.path).path
        if path == "/api/items":
            try:
                self._json(HTTPStatus.OK, {"items": rank_items(load_backlog(self.data_path))})
            except (OSError, json.JSONDecodeError, BacklogValidationError, NotImplementedError) as exc:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
            return
        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        try:
            target.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--data", type=Path, default=Path("data/backlog.json"))
    args = parser.parse_args()
    Handler.data_path = args.data.resolve()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(json.dumps({"state": "ready", "host": args.host, "port": args.port}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

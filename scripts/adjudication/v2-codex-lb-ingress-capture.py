#!/usr/bin/env python3
"""Loopback-only Codex-LB ingress capture for v2 qualification diagnostics.

Captures only bounded structured-output metadata from requests and forwards the
request body byte-for-byte to the configured upstream Codex-LB endpoint.

Never records:
- Authorization or other header values
- prompts/messages/input
- tool arguments
- model responses
- full JSON schemas

The artifact records path/method/model, structured-output format controls, and
a canonical SHA-256 of the schema when present.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _canonical_sha256(value: Any) -> str | None:
    if value is None:
        return None
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_record(method: str, path: str, body: bytes) -> dict[str, Any]:
    record: dict[str, Any] = {
        "method": method,
        "path": path,
        "json": False,
        "model": None,
        "text_format": None,
        "response_format": None,
    }
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return record
    if not isinstance(payload, Mapping):
        return record

    record["json"] = True
    record["model"] = payload.get("model")

    text = payload.get("text")
    fmt = text.get("format") if isinstance(text, Mapping) else None
    if isinstance(fmt, Mapping):
        record["text_format"] = {
            "type": fmt.get("type"),
            "strict": fmt.get("strict"),
            "name": fmt.get("name"),
            "description": fmt.get("description"),
            "schema_sha256": _canonical_sha256(fmt.get("schema")),
        }

    response_format = payload.get("response_format")
    if isinstance(response_format, Mapping):
        schema = response_format.get("json_schema")
        schema_body = schema.get("schema") if isinstance(schema, Mapping) else None
        record["response_format"] = {
            "type": response_format.get("type"),
            "name": schema.get("name") if isinstance(schema, Mapping) else None,
            "strict": schema.get("strict") if isinstance(schema, Mapping) else None,
            "schema_sha256": _canonical_sha256(schema_body),
        }

    return record


class CaptureState:
    def __init__(self, *, output: Path, upstream_host: str, upstream_port: int):
        self.output = output
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.lock = threading.Lock()

    def append(self, record: Mapping[str, Any]) -> None:
        line = json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n"
        with self.lock:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            with self.output.open("a", encoding="utf-8") as stream:
                stream.write(line)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "v2-codex-lb-ingress-capture"

    @property
    def state(self) -> CaptureState:
        return self.server.capture_state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: object) -> None:
        # Console stays clean. Diagnostics are in the bounded JSONL artifact.
        return

    def _forward(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length) if content_length else b""

        self.state.append(_safe_record(self.command, self.path, body))

        headers: dict[str, str] = {}
        for key, value in self.headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP or lower == "host":
                continue
            headers[key] = value
        headers["Host"] = f"{self.state.upstream_host}:{self.state.upstream_port}"

        conn = http.client.HTTPConnection(
            self.state.upstream_host,
            self.state.upstream_port,
            timeout=7200,
        )
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            response = conn.getresponse()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                lower = key.lower()
                if lower in HOP_BY_HOP or lower == "content-length":
                    continue
                self.send_header(key, value)
            # Close-delimited forwarding avoids re-chunking while preserving the
            # upstream body bytes and works for both JSON and SSE responses.
            self.send_header("Connection", "close")
            self.end_headers()

            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        finally:
            conn.close()
            self.close_connection = True

    do_GET = _forward
    do_POST = _forward
    do_DELETE = _forward
    do_PATCH = _forward
    do_PUT = _forward


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=2456)
    parser.add_argument("--upstream", default="http://127.0.0.1:2455")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.listen_host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("capture proxy must listen on loopback only")

    parsed = urlsplit(args.upstream)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("capture proxy upstream must be loopback HTTP")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise SystemExit("capture proxy upstream must not include a path/query/fragment")

    upstream_port = parsed.port or 80
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"capture output already exists: {output}")

    state = CaptureState(
        output=output,
        upstream_host=parsed.hostname or "127.0.0.1",
        upstream_port=upstream_port,
    )

    server = ThreadingHTTPServer((args.listen_host, args.listen_port), Handler)
    server.capture_state = state  # type: ignore[attr-defined]

    print(
        json.dumps(
            {
                "status": "ready",
                "listen": f"http://{args.listen_host}:{args.listen_port}",
                "upstream": f"http://{state.upstream_host}:{state.upstream_port}",
                "output": str(output),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

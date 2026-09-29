#!/usr/bin/env python3
"""Fail-closed verification for sanitized Codex-LB ingress captures.

The capture format intentionally contains only bounded transport metadata. This
verifier checks structured-output controls and schema identity without reading or
printing prompts, responses, tool arguments, header values, or full schemas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def _schema_sha256(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _schema_paths(explicit: list[Path], roots: list[Path]) -> list[Path]:
    paths = [path.resolve() for path in explicit]
    for root in roots:
        root = root.resolve()
        if not root.is_dir():
            raise SystemExit(f"schema root not found: {root}")
        paths.extend(path.resolve() for path in root.rglob("codex-output-schema.json"))
    unique = sorted(set(paths))
    if not unique:
        raise SystemExit("no persisted codex-output-schema.json artifacts were supplied")
    for path in unique:
        if not path.is_file():
            raise SystemExit(f"schema artifact not found: {path}")
    return unique


def verify_capture(
    *,
    capture_path: Path,
    schema_paths: list[Path],
    model: str,
    require_all_schemas: bool = True,
) -> dict[str, Any]:
    if not capture_path.is_file():
        raise SystemExit(f"sanitized ingress capture not found: {capture_path}")

    expected = {_schema_sha256(path): str(path) for path in schema_paths}
    records: list[tuple[int, Mapping[str, Any]]] = []
    for line_no, raw in enumerate(
        capture_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"capture line {line_no} is invalid JSON: {exc}") from exc
        if not isinstance(value, Mapping):
            raise SystemExit(f"capture line {line_no} is not an object")
        if value.get("method") != "POST" or value.get("path") != "/v1/responses":
            continue
        if value.get("model") != model:
            continue
        records.append((line_no, value))

    if not records:
        raise SystemExit(f"no {model} POST /v1/responses requests were captured")

    failures: list[str] = []
    observed_hashes: set[str] = set()
    for line_no, value in records:
        fmt = value.get("text_format")
        if not isinstance(fmt, Mapping):
            failures.append(f"line {line_no}: missing text_format")
            continue
        if fmt.get("type") != "json_schema":
            failures.append(f"line {line_no}: type={fmt.get('type')!r}")
        if fmt.get("strict") is not True:
            failures.append(f"line {line_no}: strict={fmt.get('strict')!r}")
        schema_sha = str(fmt.get("schema_sha256") or "")
        if schema_sha not in expected:
            failures.append(
                f"line {line_no}: schema_sha256={schema_sha!r} is not a persisted stage schema"
            )
        else:
            observed_hashes.add(schema_sha)

    if require_all_schemas:
        missing = sorted(set(expected) - observed_hashes)
        for schema_sha in missing:
            failures.append(
                f"persisted stage schema was not observed at ingress: {schema_sha}"
            )

    result = {
        "structured_requests": len(records),
        "persisted_schema_hashes": sorted(expected),
        "observed_schema_hashes": sorted(observed_hashes),
        "json_schema_strict": not failures,
    }

    print(f"structured_requests: {result['structured_requests']}")
    print(f"persisted_schema_hashes: {len(result['persisted_schema_hashes'])}")
    print(f"observed_schema_hashes: {len(result['observed_schema_hashes'])}")
    print(f"json_schema_strict: {'pass' if not failures else 'fail'}")
    if failures:
        for failure in failures:
            print(f"  {failure}")
        raise SystemExit("sanitized ingress capture failed strict schema verification")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--schema", type=Path, action="append", default=[])
    parser.add_argument("--schema-root", type=Path, action="append", default=[])
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument(
        "--allow-unobserved-schema",
        action="store_true",
        help="Do not require every supplied persisted schema hash to appear in the capture.",
    )
    args = parser.parse_args()

    paths = _schema_paths(args.schema, args.schema_root)
    verify_capture(
        capture_path=args.capture.expanduser().resolve(),
        schema_paths=paths,
        model=args.model,
        require_all_schemas=not args.allow_unobserved_schema,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

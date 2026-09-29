#!/usr/bin/env python3
"""Compact, non-leaking diagnostics for routing-semantic-v2 qualification.

Safety and attribution rules:
- inspect exactly one explicit attempt;
- default to the active attempt only;
- never fall back to archived retries;
- never print prompts, full completions, response bodies, tool arguments, or secrets;
- print only qualification state, sample status, completion classification, and
  structured-output request controls/schema integrity.

Archived attempts must be selected explicitly with --attempt retry:<UTC-stamp>.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from inspect_ai.log import read_eval_log

UNSUPPORTED_KEYWORDS = frozenset({"const", "minItems", "maxItems"})


def _default_root() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return Path(
        os.environ.get(
            "V2_QUALIFICATION_ROOT",
            data_home / "agent-workflow" / "routing-semantic-v2-qualification",
        )
    )


def _pointer(path: str, token: object) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def _walk(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    yield path or "/", value
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield from _walk(nested, _pointer(path, key))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk(nested, _pointer(path, index))


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _schema_summary(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, Mapping):
        return {
            "present": False,
            "sha256": None,
            "empty_schema_paths": [],
            "unsupported_keyword_paths": [],
            "case_id_schemas": [],
        }

    empty_schema_paths: list[str] = []
    unsupported_keyword_paths: list[str] = []
    case_id_schemas: list[dict[str, Any]] = []

    for path, value in _walk(schema):
        if isinstance(value, Mapping):
            if not value and path != "/":
                empty_schema_paths.append(path)
            for key in value:
                if key in UNSUPPORTED_KEYWORDS:
                    unsupported_keyword_paths.append(
                        _pointer("" if path == "/" else path, key)
                    )
        if path.endswith("/properties/case_id"):
            case_id_schemas.append({"path": path, "value": value})

    return {
        "present": True,
        "sha256": _sha256_json(schema),
        "empty_schema_paths": sorted(set(empty_schema_paths)),
        "unsupported_keyword_paths": sorted(set(unsupported_keyword_paths)),
        "case_id_schemas": case_id_schemas,
    }


def _completion_class(text: str) -> str:
    raw = text.strip()
    if not raw:
        return "empty"

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = None

    if isinstance(value, dict):
        return "json_object_only"
    if value is not None:
        return "json_non_object_only"

    first_brace = raw.find("{")
    if first_brace > 0:
        try:
            suffix = json.loads(raw[first_brace:])
        except json.JSONDecodeError:
            suffix = None
        if isinstance(suffix, dict):
            return "prose_plus_json_object"

    return "non_json"


def _attempt_paths(root: Path, attempt: str) -> tuple[Path, Path, Path, Path, Path, Path]:
    if attempt == "current":
        return (
            root / "inspect-qualification",
            root / "qualification.json",
            root / "qualification-run.log",
            root / "attempt.json",
            root / "codex-lb-ingress.jsonl",
            root / "codex-lb-ingress-proxy.log",
        )
    if not attempt.startswith("retry:"):
        raise SystemExit("attempt must be 'current' or 'retry:<UTC-stamp>'")
    stamp = attempt.split(":", 1)[1].strip()
    if not stamp or "/" in stamp or ".." in stamp:
        raise SystemExit(f"invalid retry identity: {attempt!r}")
    retry = root / "retries" / stamp
    return (
        retry / "inspect-qualification",
        retry / "qualification.json",
        retry / "qualification-run.log",
        retry / "attempt.json",
        retry / "codex-lb-ingress.jsonl",
        retry / "codex-lb-ingress-proxy.log",
    )


def _list_attempts(root: Path) -> None:
    (
        current_evidence,
        current_qualification,
        current_runlog,
        current_meta,
        current_ingress,
        current_proxylog,
    ) = _attempt_paths(root, "current")
    print(
        "current"
        f"\tevidence={'present' if current_evidence.is_dir() else 'absent'}"
        f"\tqualification={'present' if current_qualification.is_file() else 'absent'}"
        f"\trunlog={'present' if current_runlog.is_file() else 'absent'}"
        f"\tmeta={'present' if current_meta.is_file() else 'absent'}"
        f"\tingress={'present' if current_ingress.is_file() else 'absent'}"
        f"\tproxylog={'present' if current_proxylog.is_file() else 'absent'}"
    )
    retries = root / "retries"
    if not retries.is_dir():
        return
    for item in sorted(path for path in retries.iterdir() if path.is_dir()):
        attempt = f"retry:{item.name}"
        evidence, qualification, runlog, meta, ingress, proxylog = _attempt_paths(root, attempt)
        print(
            f"{attempt}"
            f"\tevidence={'present' if evidence.is_dir() else 'absent'}"
            f"\tqualification={'present' if qualification.is_file() else 'absent'}"
            f"\trunlog={'present' if runlog.is_file() else 'absent'}"
            f"\tmeta={'present' if meta.is_file() else 'absent'}"
            f"\tingress={'present' if ingress.is_file() else 'absent'}"
            f"\tproxylog={'present' if proxylog.is_file() else 'absent'}"
        )


def _attempt_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"exists": True, "error": str(exc)}
    if not isinstance(value, Mapping):
        return {"exists": True, "error": "attempt metadata is not an object"}
    allowed = {
        "attempt_id",
        "model",
        "log_model_api",
        "capture_codex_lb_ingress",
        "status",
        "exit_status",
    }
    return {
        "exists": True,
        **{key: value.get(key) for key in sorted(allowed) if key in value},
    }


def _ingress_summary(path: Path, schema_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": path.is_file(),
        "path": str(path),
        "records": [],
    }
    if not path.is_file():
        return result

    schema_labels: dict[str, str] = {}
    for artifact in schema_artifacts:
        sha = artifact.get("sha256")
        artifact_path = str(artifact.get("path") or "")
        if not sha:
            continue
        if "/tiebreaker/" in artifact_path:
            schema_labels[str(sha)] = "C"
        elif "/primary/" in artifact_path:
            schema_labels[str(sha)] = "primary"

    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            records.append({"line": line_number, "error": f"invalid JSONL: {exc}"})
            continue
        if not isinstance(value, Mapping):
            records.append({"line": line_number, "error": "record is not an object"})
            continue
        text_format = value.get("text_format")
        schema_sha = (
            text_format.get("schema_sha256")
            if isinstance(text_format, Mapping)
            else None
        )
        records.append(
            {
                "line": line_number,
                "method": value.get("method"),
                "path": value.get("path"),
                "model": value.get("model"),
                "text_format": text_format,
                "response_format": value.get("response_format"),
                "schema_match": schema_labels.get(str(schema_sha)) if schema_sha else None,
            }
        )
    result["records"] = records
    return result


def _qualification_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "qualified": None, "gates": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "exists": True,
            "qualified": None,
            "gates": {},
            "error": f"invalid qualification JSON: {exc}",
        }

    gates = value.get("gates")
    statuses: dict[str, Any] = {}
    if isinstance(gates, Mapping):
        for number in range(1, 12):
            gate = f"IA-{number}"
            record = gates.get(gate)
            statuses[gate] = (
                record.get("status") if isinstance(record, Mapping) else None
            )
    return {
        "exists": True,
        "qualified": value.get("qualified"),
        "gates": statuses,
    }


def _request_summary(event: Any) -> dict[str, Any]:
    call = getattr(event, "call", None)
    request = getattr(call, "request", None)
    if not isinstance(request, Mapping):
        return {
            "recorded": False,
            "model": None,
            "request_keys": [],
            "format": None,
            "schema": _schema_summary(None),
        }

    text = request.get("text")
    format_value = text.get("format") if isinstance(text, Mapping) else None
    fmt = format_value if isinstance(format_value, Mapping) else None
    schema = fmt.get("schema") if fmt else None
    return {
        "recorded": True,
        "model": request.get("model"),
        "request_keys": sorted(str(key) for key in request),
        "format": (
            {
                "type": fmt.get("type"),
                "strict": fmt.get("strict"),
                "name": fmt.get("name"),
                "description": fmt.get("description"),
            }
            if fmt
            else None
        ),
        "schema": _schema_summary(schema),
    }


def _sample_summary(sample: Any) -> dict[str, Any]:
    output = getattr(sample, "output", None)
    completion = str(getattr(output, "completion", "") or "")
    events = [
        event
        for event in (getattr(sample, "events", None) or [])
        if getattr(event, "event", None) == "model"
    ]
    final_request = _request_summary(events[-1]) if events else _request_summary(None)
    return {
        "id": str(getattr(sample, "id", "")),
        "error": str(getattr(sample, "error", "") or "") or None,
        "model": getattr(output, "model", None),
        "completion_length": len(completion),
        "completion_class": _completion_class(completion),
        "model_events": len(events),
        "final_request": final_request,
    }


def _collect(attempt: str, root: Path) -> dict[str, Any]:
    (
        evidence_root,
        qualification_path,
        runlog_path,
        meta_path,
        ingress_path,
        proxylog_path,
    ) = _attempt_paths(root, attempt)
    result: dict[str, Any] = {
        "attempt": attempt,
        "root": str(root),
        "evidence_root": str(evidence_root),
        "evidence_exists": evidence_root.is_dir(),
        "qualification_path": str(qualification_path),
        "qualification": _qualification_summary(qualification_path),
        "attempt_meta": _attempt_meta(meta_path),
        "run_log": {
            "path": str(runlog_path),
            "exists": runlog_path.is_file(),
            "bytes": runlog_path.stat().st_size if runlog_path.is_file() else None,
        },
        "ingress_proxy_log": {
            "path": str(proxylog_path),
            "exists": proxylog_path.is_file(),
            "bytes": proxylog_path.stat().st_size if proxylog_path.is_file() else None,
        },
        "eval_logs": [],
    }

    schema_artifacts: list[dict[str, Any]] = []
    for path in sorted(evidence_root.rglob("codex-output-schema.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            summary = _schema_summary(value)
            schema_artifacts.append(
                {
                    "path": str(path.relative_to(root)),
                    **summary,
                }
            )
        except (OSError, json.JSONDecodeError) as exc:
            schema_artifacts.append(
                {
                    "path": str(path.relative_to(root)),
                    "read_error": str(exc),
                }
            )
    result["schema_artifacts"] = schema_artifacts
    result["codex_lb_ingress"] = _ingress_summary(ingress_path, schema_artifacts)

    if not evidence_root.is_dir():
        return result

    logs = sorted(evidence_root.rglob("*.eval"), key=lambda p: p.stat().st_mtime)
    for path in logs:
        try:
            log = read_eval_log(path)
        except Exception as exc:
            result["eval_logs"].append(
                {
                    "path": str(path.relative_to(root)),
                    "read_error": str(exc),
                }
            )
            continue
        result["eval_logs"].append(
            {
                "path": str(path.relative_to(root)),
                "status": getattr(log, "status", None),
                "error": str(getattr(log, "error", "") or "") or None,
                "samples": [_sample_summary(sample) for sample in (log.samples or [])],
            }
        )
    return result


def _print_text(result: Mapping[str, Any]) -> None:
    print(f"attempt: {result['attempt']}")
    print(f"evidence_exists: {result['evidence_exists']}")
    meta = result.get("attempt_meta") or {"exists": False}
    print(f"attempt_meta_exists: {meta.get('exists')}")
    if meta.get("exists"):
        print(
            "attempt_meta:"
            f" id={meta.get('attempt_id')}"
            f" status={meta.get('status')}"
            f" model={meta.get('model')}"
            f" log_model_api={meta.get('log_model_api')}"
            f" exit_status={meta.get('exit_status')}"
        )
    q = result["qualification"]
    print(f"qualification_exists: {q['exists']}")
    print(f"qualified: {q['qualified']}")
    if q.get("gates"):
        print(
            "gates:",
            " ".join(f"{key}={value}" for key, value in q["gates"].items()),
        )
    runlog = result["run_log"]
    print(
        "private_run_log:",
        f"{runlog['path']} ({runlog['bytes']} bytes)"
        if runlog["exists"]
        else "absent",
    )
    ingress = result.get("codex_lb_ingress") or {"exists": False, "records": []}
    print(f"codex_lb_ingress_exists: {ingress.get('exists')}")
    if ingress.get("exists"):
        print(f"codex_lb_ingress_records: {len(ingress.get('records') or [])}")
        for record in ingress.get("records") or []:
            if "error" in record:
                print(f"  ingress line={record['line']} error={record['error']}")
                continue
            fmt = record.get("text_format")
            print(
                "  ingress:"
                f" line={record.get('line')}"
                f" method={record.get('method')}"
                f" path={record.get('path')}"
                f" model={record.get('model')}"
                f" schema_match={record.get('schema_match')}"
                f" text_format={fmt}"
            )

    artifacts = result.get("schema_artifacts") or []
    print(f"schema_artifacts: {len(artifacts)}")
    for artifact in artifacts:
        print(f"  schema_artifact: {artifact['path']}")
        if "read_error" in artifact:
            print(f"    read_error: {artifact['read_error']}")
            continue
        print(
            "    schema:"
            f" sha256={artifact['sha256']}"
            f" empty_nodes={len(artifact['empty_schema_paths'])}"
            f" unsupported={len(artifact['unsupported_keyword_paths'])}"
        )
        if artifact["empty_schema_paths"]:
            print("      empty_schema_paths:", artifact["empty_schema_paths"])
        if artifact["unsupported_keyword_paths"]:
            print(
                "      unsupported_keyword_paths:",
                artifact["unsupported_keyword_paths"],
            )
        if artifact["case_id_schemas"]:
            print("      case_id_schemas:", artifact["case_id_schemas"])

    print(f"eval_logs: {len(result['eval_logs'])}")

    for log in result["eval_logs"]:
        print(f"\nlog: {log['path']}")
        if "read_error" in log:
            print(f"  read_error: {log['read_error']}")
            continue
        print(f"  status: {log['status']}")
        print(f"  error: {log['error']}")
        for sample in log["samples"]:
            print(
                "  sample:"
                f" id={sample['id']}"
                f" error={sample['error']}"
                f" model={sample['model']}"
                f" completion={sample['completion_class']}"
                f" completion_len={sample['completion_length']}"
                f" model_events={sample['model_events']}"
            )
            request = sample["final_request"]
            print(
                "    final_request:"
                f" recorded={request['recorded']}"
                f" model={request['model']}"
                f" format={request['format']}"
            )
            schema = request["schema"]
            print(
                "    schema:"
                f" present={schema['present']}"
                f" sha256={schema['sha256']}"
                f" empty_nodes={len(schema['empty_schema_paths'])}"
                f" unsupported={len(schema['unsupported_keyword_paths'])}"
            )
            if schema["empty_schema_paths"]:
                print("      empty_schema_paths:", schema["empty_schema_paths"])
            if schema["unsupported_keyword_paths"]:
                print(
                    "      unsupported_keyword_paths:",
                    schema["unsupported_keyword_paths"],
                )
            if schema["case_id_schemas"]:
                print("      case_id_schemas:", schema["case_id_schemas"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=_default_root())
    parser.add_argument("--attempt", default="current")
    parser.add_argument("--list-attempts", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if args.list_attempts:
        _list_attempts(root)
        return 0

    result = _collect(args.attempt, root)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

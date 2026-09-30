#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from inspect_ai.log import read_eval_log

SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|token|secret|password|passwd|cookie|authorization|private[_-]?key)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"']+"),
    re.compile(r"(?i)(typesafe_api_key\s*[:=]\s*)[^\s\"']+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
]
SELECTED_PROPOSAL = re.compile(
    r"selected_proposal_id[^0-9]{0,32}([0-9]+)",
    re.IGNORECASE,
)
MAX_MESSAGE_TEXT = 8000
MAX_TOOL_ARGUMENTS = 8000
MAX_TOOL_RESULT = 8000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redact_text(text: str, limit: int) -> str:
    value = text
    for pattern in SECRET_VALUE_PATTERNS:
        value = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "<redacted>", value)
    if len(value) > limit:
        return value[:limit] + "\n...[truncated]..."
    return value


def _safe(value: Any, *, key: str | None = None, limit: int = MAX_TOOL_ARGUMENTS) -> Any:
    if key and SENSITIVE_KEY.search(key):
        return "<redacted>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_text(value, limit)
    if isinstance(value, dict):
        return {str(k): _safe(v, key=str(k), limit=limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item, limit=limit) for item in value]
    if hasattr(value, "model_dump"):
        return _safe(value.model_dump(mode="json", exclude_none=True), limit=limit)
    return _redact_text(str(value), limit)


def _message_text(message: Any) -> str:
    text_value = getattr(message, "text", "")
    if callable(text_value):
        text_value = text_value()
    return _redact_text(str(text_value or ""), MAX_MESSAGE_TEXT)


def _tool_call_record(call: Any) -> dict[str, Any]:
    function = getattr(call, "function", None)
    arguments = getattr(call, "arguments", None)
    return {
        "function": str(function) if function is not None else None,
        "arguments": _safe(arguments, limit=MAX_TOOL_ARGUMENTS),
    }


def _extract_exec_command(arguments: Any) -> str | None:
    if not isinstance(arguments, dict):
        return None
    for key in ("cmd", "command", "script"):
        value = arguments.get(key)
        if isinstance(value, str):
            return _redact_text(value, MAX_TOOL_ARGUMENTS)
    return None


def _extract_selected_proposal(texts: list[str]) -> int | None:
    for text in reversed(texts):
        match = SELECTED_PROPOSAL.search(text)
        if match:
            return int(match.group(1))
    return None


def _message_record(message: Any) -> dict[str, Any]:
    role = str(getattr(message, "role", "unknown"))
    text = _message_text(message)
    content = getattr(message, "content", None)
    content_types: list[str] = []
    reasoning_blocks = 0
    if isinstance(content, list):
        for item in content:
            item_type = str(getattr(item, "type", type(item).__name__))
            content_types.append(item_type)
            if item_type == "reasoning":
                reasoning_blocks += 1

    tool_calls = [
        _tool_call_record(call)
        for call in (getattr(message, "tool_calls", None) or [])
    ]
    return {
        "role": role,
        "text": text,
        "content_types": content_types,
        "reasoning_blocks_observed": reasoning_blocks,
        "reasoning_content_exported": False,
        "tool_calls": tool_calls,
        "tool_function": getattr(message, "function", None),
        "tool_error": _safe(getattr(message, "error", None)),
    }


def _audit_one(sample_record: dict[str, Any]) -> dict[str, Any]:
    sample_id = str(sample_record["sample_id"])
    log_path = Path(str(sample_record["inspect_log"])).expanduser()
    if not log_path.is_file():
        raise FileNotFoundError(f"missing Inspect log for {sample_id}: {log_path}")

    log = read_eval_log(log_path)
    samples = log.samples or []
    if len(samples) != 1:
        raise RuntimeError(
            f"{sample_id}: expected one sample in {log_path}, observed {len(samples)}"
        )
    sample = samples[0]
    messages = [_message_record(message) for message in sample.messages]

    assistant_text = [
        item["text"] for item in messages
        if item["role"] == "assistant" and item["text"]
    ]
    tool_result_text = [
        item["text"] for item in messages
        if item["role"] == "tool" and item["text"]
    ]
    tool_calls = [
        call
        for item in messages
        for call in item["tool_calls"]
    ]
    exec_commands = [
        command
        for call in tool_calls
        for command in [_extract_exec_command(call.get("arguments"))]
        if command
    ]

    searchable = "\n".join(
        assistant_text
        + tool_result_text
        + [json.dumps(call, sort_keys=True, default=str) for call in tool_calls]
    ).lower()
    proposal_texts = (
        assistant_text
        + tool_result_text
        + exec_commands
        + [json.dumps(call, sort_keys=True, default=str) for call in tool_calls]
    )

    uncertainty_terms = [
        term for term in (
            "uncertain",
            "uncertainty",
            "likely",
            "probably",
            "appears",
            "seems",
            "trade-off",
            "tradeoff",
            "risk",
            "insufficient",
            "evidence",
            "confidence",
        )
        if term in searchable
    ]

    final_assistant_text = assistant_text[-1] if assistant_text else ""
    selected_proposal = _extract_selected_proposal(proposal_texts)

    return {
        "sample_id": sample_id,
        "inspect_log": str(log_path),
        "inspect_log_sha256": _sha256(log_path),
        "sample_status": sample_record.get("sample_status"),
        "jev_tool_calls_from_run_manifest": sample_record.get("jev_tool_calls"),
        "selected_proposal_id_observed": selected_proposal,
        "visible_final_assistant_text": final_assistant_text,
        "visible_assistant_messages": assistant_text,
        "observable_tool_calls": tool_calls,
        "observable_exec_commands": exec_commands,
        "observable_tool_results": tool_result_text,
        "reasoning_blocks_observed": sum(
            int(item["reasoning_blocks_observed"]) for item in messages
        ),
        "reasoning_content_exported": False,
        "mentions": {
            "jev": "jev" in searchable,
            "typesafe": "typesafe" in searchable,
            "skill": "skill" in searchable,
            "manager_decisions": "manager_decisions.json" in searchable,
            "uncertainty_terms": uncertainty_terms,
        },
        "audit_classification": {
            "semantic_seam_observed": None,
            "semantic_seam_type": None,
            "deterministic_evidence_appeared_decisive": None,
            "jev_nonuse_explanation": None,
            "auditor_confidence": None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive a read-only observable decision-trace audit from the immutable v2 manager run."
    )
    parser.add_argument("manager_run_root", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path; defaults to sibling manager-run-audit/audit.json",
    )
    args = parser.parse_args()

    root = args.manager_run_root.expanduser().resolve()
    manifest_path = root / "run-manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"missing manager run manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    execution = manifest.get("execution") or {}
    if execution.get("samples_observed") != 6:
        raise SystemExit("audit requires the completed six-sample v2 manager run")
    if execution.get("jev_tool_calls") != 0:
        raise SystemExit("this audit is scoped to the preserved zero-call v2 manager run")

    samples = manifest.get("samples")
    if not isinstance(samples, list) or len(samples) != 6:
        raise SystemExit("manager run manifest does not contain six sample records")

    output = args.output
    if output is None:
        output = root.parent / "manager-run-audit" / "audit.json"
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing audit: {output}")

    audited = [_audit_one(dict(item)) for item in samples]
    artifact = {
        "schema": "agent-workflow-benchmark/agentic-jev-manager-trace-audit/v1",
        "study_id": "agentic-jev-decision-skill-v2",
        "source": {
            "manager_run_root": str(root),
            "run_manifest": str(manifest_path),
            "run_manifest_sha256": _sha256(manifest_path),
            "samples": 6,
            "jev_tool_calls": 0,
        },
        "scope": {
            "purpose": (
                "inspect observable per-task decision evidence before changing "
                "the Jev skill or task cohort again"
            ),
            "private_derived_evidence": True,
            "raw_reasoning_exported": False,
            "assistant_visible_text_included": True,
            "tool_calls_and_results_included": True,
            "classification_is_manual": True,
        },
        "samples": audited,
    }
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Agentic Jev v2 manager observable-trace audit created")
    print("samples:", len(audited))
    print("source_manifest_sha256:", artifact["source"]["run_manifest_sha256"])
    print("selected_proposals:", {
        item["sample_id"]: item["selected_proposal_id_observed"]
        for item in audited
    })
    print("reasoning_blocks_observed:", {
        item["sample_id"]: item["reasoning_blocks_observed"]
        for item in audited
    })
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

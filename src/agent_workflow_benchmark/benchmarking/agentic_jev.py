from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from importlib.resources import files
from pathlib import Path
from time import monotonic
from typing import Any

from agent_workflow.errors import WorkflowError

TOOL_RECEIPT_SCHEMA = "agent-workflow-benchmark/agentic-jev-tool-receipt/v1"
PILOT_STUDY_ID = "agentic-jev-pilot-v1"
SKILL_UPSTREAM_COMMIT = "65a39f393687675ce170e6094757de20370365b9"
SKILL_UPSTREAM_RELEASE = "v0.5.7"
_ALLOWED_PRIMITIVES = frozenset({"choice", "noul", "score"})
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "x_api_key",
        "authorization",
        "proxy_authorization",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "cookie",
        "set_cookie",
        "credential",
        "credentials",
        "bearer",
    }
)
_SECRET_SUFFIXES = (
    "_api_key",
    "_password",
    "_secret",
    "_token",
    "_credential",
    "_credentials",
)
_MAX_TEXT = 8_000
_MAX_ITEMS = 100
_MAX_DEPTH = 8
_MAX_QUESTIONS = 16
_MAX_STATE_BYTES = 64 * 1024
_MAX_QUESTIONS_BYTES = 48 * 1024


@dataclass(frozen=True)
class AgenticJevArm:
    arm_id: str
    typesafe_skill: bool
    jev_tool: bool


PILOT_ARMS: tuple[AgenticJevArm, ...] = (
    AgenticJevArm("A-baseline", False, False),
    AgenticJevArm("B-skill-only", True, False),
    AgenticJevArm("C-skill-plus-jev", True, True),
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _safe(value: Any, *, key: str = "", depth: int = 0) -> Any:
    normalized = key.lower().replace("-", "_").strip()
    if normalized in _SECRET_KEYS or normalized.endswith(_SECRET_SUFFIXES):
        return "[redacted]"
    if depth >= _MAX_DEPTH:
        return "[depth_limit]"
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {
            str(k)[:200]: _safe(v, key=str(k), depth=depth + 1)
            for k, v in list(value.items())[:_MAX_ITEMS]
        }
    if isinstance(value, (list, tuple)):
        return [_safe(v, depth=depth + 1) for v in value[:_MAX_ITEMS]]
    return f"[unsupported:{type(value).__name__}]"


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _typesafe_sdk_version() -> str | None:
    try:
        return metadata.version("typesafe-sdk")
    except metadata.PackageNotFoundError:
        return None


def _validate_questions(questions: Mapping[str, object]) -> dict[str, object]:
    if not questions:
        raise WorkflowError("Jev tool requires at least one question")
    if len(questions) > _MAX_QUESTIONS:
        raise WorkflowError(
            f"Jev tool accepts at most {_MAX_QUESTIONS} questions per request"
        )

    normalized: dict[str, object] = {}
    for raw_id, raw_spec in questions.items():
        question_id = str(raw_id).strip()
        if not question_id:
            raise WorkflowError("Jev question IDs must be non-empty")
        if not isinstance(raw_spec, Mapping):
            raise WorkflowError(
                f"Jev question {question_id!r} must be an object"
            )
        primitive = str(raw_spec.get("type") or "").lower().strip()
        if primitive not in _ALLOWED_PRIMITIVES:
            raise WorkflowError(
                f"Jev question {question_id!r} has unsupported type {primitive!r}"
            )
        instructions = raw_spec.get("instructions")
        if not isinstance(instructions, (str, Mapping, list)) or not instructions:
            raise WorkflowError(
                f"Jev question {question_id!r} requires instructions"
            )

        spec: dict[str, object] = {
            "type": primitive,
            "instructions": _safe(instructions),
        }
        criteria = raw_spec.get("criteria")
        if primitive in {"choice", "score"} and criteria is None:
            raise WorkflowError(
                f"Jev {primitive} question {question_id!r} requires criteria"
            )
        if criteria is not None:
            spec["criteria"] = _safe(criteria)
        normalized[question_id] = spec

    if len(_canonical_json(normalized).encode("utf-8")) > _MAX_QUESTIONS_BYTES:
        raise WorkflowError("Jev question bundle exceeds the pilot size limit")
    return normalized


def _answers(response: Any) -> Mapping[str, object]:
    answers = getattr(response, "answers", None)
    if isinstance(answers, Mapping):
        return answers
    merged: dict[str, object] = {}
    for name in ("choices", "nouls", "scores"):
        values = getattr(response, name, None)
        if isinstance(values, Mapping):
            merged.update(values)
    if not merged:
        raise WorkflowError("TypeSafe response has no typed answer mapping")
    return merged


def _response_usage(response: Any) -> dict[str, object]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, Mapping):
        raw = dict(usage)
    elif hasattr(usage, "model_dump"):
        try:
            dumped = usage.model_dump()
            raw = dict(dumped) if isinstance(dumped, Mapping) else {}
        except Exception:
            raw = {}
    else:
        raw = {
            name: getattr(usage, name)
            for name in (
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "cached_input_tokens",
                "retry_count",
            )
            if getattr(usage, name, None) is not None
        }

    result: dict[str, object] = {}
    for raw_key, value in raw.items():
        if value is None or isinstance(value, bool) or not isinstance(
            value, (int, float)
        ):
            continue
        key = "provider_total_tokens" if str(raw_key) == "total_tokens" else str(raw_key)
        result[key] = value

    if (
        "provider_total_tokens" not in result
        and isinstance(result.get("input_tokens"), (int, float))
        and isinstance(result.get("output_tokens"), (int, float))
    ):
        result["provider_total_tokens"] = (
            float(result["input_tokens"]) + float(result["output_tokens"])
        )
    return result


def _normalize_answers(
    response: Any,
    questions: Mapping[str, object],
) -> dict[str, object]:
    answers = _answers(response)
    result: dict[str, object] = {}
    for question_id, spec in questions.items():
        answer = answers.get(question_id)
        if answer is None:
            raise WorkflowError(
                f"TypeSafe response is missing answer {question_id!r}"
            )
        primitive = str(spec["type"])
        if primitive == "choice":
            probabilities = getattr(answer, "probabilities", {})
            result[question_id] = {
                "type": "choice",
                "choice": _safe(getattr(answer, "choice", None)),
                "confidence": _safe(getattr(answer, "confidence", None)),
                "probabilities": (
                    {str(k): float(v) for k, v in probabilities.items()}
                    if isinstance(probabilities, Mapping)
                    else {}
                ),
            }
        elif primitive == "noul":
            probabilities = getattr(answer, "probabilities", {})
            result[question_id] = {
                "type": "noul",
                "probability": _safe(getattr(answer, "noul", None)),
                "probabilities": (
                    {str(k): float(v) for k, v in probabilities.items()}
                    if isinstance(probabilities, Mapping)
                    else {}
                ),
            }
        else:
            probabilities = getattr(answer, "probabilities", {})
            result[question_id] = {
                "type": "score",
                "score": _safe(getattr(answer, "score", None)),
                "confidence": _safe(getattr(answer, "confidence", None)),
                "probabilities": (
                    {str(k): float(v) for k, v in probabilities.items()}
                    if isinstance(probabilities, Mapping)
                    else {}
                ),
            }
    return result


def _response_request_id(response: Any, digest: str) -> str:
    value = getattr(response, "request_id", None)
    return value if isinstance(value, str) and value else f"typesafe:{digest[:32]}"


def _append_receipt(path: Path | None, value: Mapping[str, object]) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        )


def execute_jev_request(
    *,
    state: Mapping[str, object],
    questions: Mapping[str, object],
    purpose: str | None = None,
    model: str | None = None,
    client: Any | None = None,
    receipt_path: Path | None = None,
) -> dict[str, object]:
    safe_state = _safe(state)
    if not isinstance(safe_state, dict):
        raise WorkflowError("Jev state must be an object")
    if len(_canonical_json(safe_state).encode("utf-8")) > _MAX_STATE_BYTES:
        raise WorkflowError("Jev state exceeds the pilot size limit")
    safe_questions = _validate_questions(questions)

    request_payload = {
        "state": safe_state,
        "questions": safe_questions,
        "model": model,
    }
    request_sha256 = _sha256_json(request_payload)
    started = monotonic()
    primitive_counts = {
        primitive: sum(
            1
            for value in safe_questions.values()
            if isinstance(value, Mapping) and value.get("type") == primitive
        )
        for primitive in sorted(_ALLOWED_PRIMITIVES)
    }

    base_receipt: dict[str, object] = {
        "schema": TOOL_RECEIPT_SCHEMA,
        "study_id": PILOT_STUDY_ID,
        "timestamp": _utc(),
        "purpose": _safe(purpose or ""),
        "request_sha256": request_sha256,
        "requested_model": model,
        "typesafe_sdk_version": _typesafe_sdk_version(),
        "question_ids": list(safe_questions),
        "primitive_counts": primitive_counts,
        "state_sha256": _sha256_json(safe_state),
        "questions_sha256": _sha256_json(safe_questions),
        "request": {
            "state": safe_state,
            "questions": safe_questions,
        },
        "privacy": {
            "host_tool": True,
            "credentials_in_sandbox": False,
            "secret_like_fields_redacted": True,
            "public_safe": False,
        },
    }

    if client is None:
        if not os.environ.get("TYPESAFE_API_KEY"):
            receipt = {
                **base_receipt,
                "status": "service_failure",
                "error_class": "typesafe_api_key_unavailable",
                "duration_ms": round((monotonic() - started) * 1000, 3),
            }
            _append_receipt(receipt_path, receipt)
            raise WorkflowError("TYPESAFE_API_KEY is required on the host for Jev tool use")
        try:
            from typesafe_sdk import TypeSafeClient
        except ImportError as exc:
            receipt = {
                **base_receipt,
                "status": "service_failure",
                "error_class": "typesafe_sdk_unavailable",
                "duration_ms": round((monotonic() - started) * 1000, 3),
            }
            _append_receipt(receipt_path, receipt)
            raise WorkflowError(
                "typesafe-sdk is required for the agent-directed Jev pilot"
            ) from exc
        client = TypeSafeClient()

    try:
        response = client.system_one(
            state=safe_state,
            questions=safe_questions,
            model=model,
        )
        normalized = _normalize_answers(response, safe_questions)
        usage = _response_usage(response)
        resolved_model = getattr(response, "model", None)
        request_id = _response_request_id(response, request_sha256)
        duration_ms = round((monotonic() - started) * 1000, 3)
        result = {
            "status": "success",
            "request_id": request_id,
            "request_sha256": request_sha256,
            "model": resolved_model if isinstance(resolved_model, str) else None,
            "answers": normalized,
            "usage": usage,
            "duration_ms": duration_ms,
        }
        _append_receipt(
            receipt_path,
            {
                **base_receipt,
                **result,
                "response": {
                    "answers": normalized,
                    "usage": usage,
                },
            },
        )
        return result
    except WorkflowError:
        raise
    except Exception as exc:
        duration_ms = round((monotonic() - started) * 1000, 3)
        _append_receipt(
            receipt_path,
            {
                **base_receipt,
                "status": "service_failure",
                "error_class": type(exc).__name__,
                "duration_ms": duration_ms,
            },
        )
        raise WorkflowError(
            f"Jev tool request failed with {type(exc).__name__}"
        ) from exc


def agentic_jev_skill_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-pilot/typesafe-ai/SKILL.md"
    )
    return Path(str(resource))


def agentic_jev_skill_sha256() -> str:
    return hashlib.sha256(agentic_jev_skill_path().read_bytes()).hexdigest()


def pilot_arm(arm_id: str) -> AgenticJevArm:
    for arm in PILOT_ARMS:
        if arm.arm_id == arm_id:
            return arm
    raise WorkflowError(f"unknown agent-directed Jev pilot arm: {arm_id}")


def jev_bridged_tool(
    *,
    receipt_path: Path,
    model: str | None = None,
) -> Any:
    try:
        from inspect_ai.tool import tool
    except ImportError as exc:
        raise WorkflowError(
            "Inspect AI is required to expose the Jev bridged tool"
        ) from exc

    @tool
    def jev_system_one():
        async def execute(
            state: dict[str, Any],
            questions: dict[str, Any],
            purpose: str = "",
        ) -> str:
            """Ask Jev one or more bounded typed semantic questions.

            Use this only when a semantic judgment would materially help the coding
            task and ordinary deterministic inspection cannot answer it directly.

            Args:
                state: Bounded JSON evidence needed for the judgment. Do not include credentials.
                questions: Mapping of question IDs to TypeSafe question objects using type=choice, noul, or score.
                purpose: Short explanation of the coding decision this judgment will inform.
            """
            result = await asyncio.to_thread(
                execute_jev_request,
                state=state,
                questions=questions,
                purpose=purpose,
                model=model,
                receipt_path=receipt_path,
            )
            return json.dumps(result, ensure_ascii=False, separators=(",", ":"))

        return execute

    return jev_system_one()


def build_agentic_jev_solver(
    *,
    arm_id: str,
    codex_version: str,
    receipt_path: Path,
    jev_model: str | None = None,
) -> Any:
    try:
        from inspect_ai.agent import BridgedToolsSpec
        from inspect_swe import codex_cli
    except ImportError as exc:
        raise WorkflowError(
            "agent-directed Jev pilot requires agent-workflow-benchmark[inspect]"
        ) from exc

    arm = pilot_arm(arm_id)
    skills = [agentic_jev_skill_path()] if arm.typesafe_skill else None
    bridged_tools = (
        [
            BridgedToolsSpec(
                name="jev",
                tools=[jev_bridged_tool(receipt_path=receipt_path, model=jev_model)],
            )
        ]
        if arm.jev_tool
        else None
    )

    return codex_cli(
        version=codex_version,
        skills=skills,
        bridged_tools=bridged_tools,
        web_search="disabled",
        goals=False,
        attempts=1,
        mcp_servers=[],
        auto_review=False,
        home_dir="/tmp/codex-home",
        system_prompt=(
            "Complete the assigned coding task using only the supplied repository "
            "state and available tools. Use installed skills and optional semantic "
            "tools only when they materially improve a bounded decision; do not "
            "add dependencies or product code merely to access an experimental tool."
        ),
        config_overrides={
            "approval_policy": "never",
            "web_search": "disabled",
        },
    )


def pilot_treatment_manifest() -> dict[str, object]:
    return {
        "schema": "agent-workflow-benchmark/agentic-jev-treatment/v1",
        "study_id": PILOT_STUDY_ID,
        "skill": {
            "upstream_repository": "typesafe-ai/skills",
            "upstream_commit": SKILL_UPSTREAM_COMMIT,
            "upstream_release": SKILL_UPSTREAM_RELEASE,
            "sha256": agentic_jev_skill_sha256(),
        },
        "arms": [
            {
                "arm_id": arm.arm_id,
                "codex": True,
                "typesafe_skill": arm.typesafe_skill,
                "jev_tool": arm.jev_tool,
            }
            for arm in PILOT_ARMS
        ],
        "tool": {
            "transport": "Inspect bridged tool / MCP",
            "execution_location": "host",
            "api_key_location": "host-only",
            "primitives": sorted(_ALLOWED_PRIMITIVES),
            "receipt_schema": TOOL_RECEIPT_SCHEMA,
        },
    }

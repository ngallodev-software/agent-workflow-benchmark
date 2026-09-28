from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from importlib.resources import files
from pathlib import Path
from time import monotonic
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, sha256_file

from .schema_contracts import validate_instance

TOOL_RECEIPT_SCHEMA = "agent-workflow-benchmark/agentic-jev-tool-receipt/v1"
PILOT_STUDY_ID = "agentic-jev-pilot-v1"
PILOT_AGENT_MODEL = "openai-api/codex-lb/gpt-6-luna"
PILOT_AGENT_REASONING_EFFORT = "high"
PILOT_CODEX_MODEL_CONFIG = "gpt-6-luna"
PILOT_CODEX_MIN_VERSION = (0, 155, 0)
SKILL_UPSTREAM_COMMIT = "65a39f393687675ce170e6094757de20370365b9"
SKILL_UPSTREAM_RELEASE = "v0.5.7"
TYPESAFE_SDK_VERSION = "0.6.0"
SANDBOX_IMAGE = "python:3.12-bookworm"
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


def _codex_version_tuple(value: str) -> tuple[int, int, int]:
    raw = str(value).strip().removeprefix("v")
    parts = raw.split(".")
    if len(parts) < 3:
        raise WorkflowError(f"invalid resolved Codex CLI version: {value!r}")
    try:
        return tuple(int(part) for part in parts[:3])
    except ValueError as exc:
        raise WorkflowError(f"invalid resolved Codex CLI version: {value!r}") from exc


def _typesafe_sdk_version() -> str | None:
    try:
        return metadata.version("typesafe-sdk")
    except metadata.PackageNotFoundError:
        return None


def _inspect_harness_sha256() -> str:
    from . import inspect_adjudication as inspect_runtime

    return sha256_file(Path(inspect_runtime.__file__).resolve())


def _sandbox_image_identity() -> dict[str, object]:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", SANDBOX_IMAGE],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkflowError(
            f"agentic Jev sandbox image is unavailable: {SANDBOX_IMAGE}; "
            "materialize it before freezing the runtime"
        ) from exc
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise WorkflowError("unable to decode Docker sandbox image identity") from exc
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], Mapping):
        raise WorkflowError("Docker sandbox image inspection returned an unexpected shape")
    value = values[0]
    image_id = value.get("Id")
    if not isinstance(image_id, str) or not image_id:
        raise WorkflowError("Docker sandbox image inspection returned no image ID")
    repo_digests = value.get("RepoDigests")
    return {
        "reference": SANDBOX_IMAGE,
        "image_id": image_id,
        "repo_digests": sorted(
            str(item) for item in repo_digests
        )
        if isinstance(repo_digests, list)
        else [],
    }


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
        model_config=PILOT_CODEX_MODEL_CONFIG,
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
        "agent": {
            "model": PILOT_AGENT_MODEL,
            "reasoning_effort": PILOT_AGENT_REASONING_EFFORT,
            "responses_api": True,
            "codex_model_config": PILOT_CODEX_MODEL_CONFIG,
            "codex_min_version": ".".join(str(item) for item in PILOT_CODEX_MIN_VERSION),
        },
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



def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid agentic Jev contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"agentic Jev contract must be an object: {path}")
    return value


def load_pilot_tasks(path: Path) -> dict[str, Any]:
    value = _read_json_object(Path(path))
    validate_instance(
        value,
        "agent-workflow-benchmark/agentic-jev-pilot-tasks/v1",
        artifact=str(path),
    )
    task_ids = [str(item["task_id"]) for item in value["tasks"]]
    if len(task_ids) != len(set(task_ids)):
        raise WorkflowError("agentic Jev pilot task IDs must be unique")
    return value


def _pilot_samples(task_contract: Mapping[str, Any]) -> list[Any]:
    try:
        from inspect_ai.dataset import Sample
    except ImportError as exc:
        raise WorkflowError(
            "agent-directed Jev pilot requires agent-workflow-benchmark[inspect]"
        ) from exc

    samples: list[Any] = []
    for raw in task_contract["tasks"]:
        # Authoring tags are intentionally omitted from the sample. They exist only
        # for post-run exploratory analysis and must not steer the coding agent.
        samples.append(
            Sample(
                id=str(raw["task_id"]),
                input=str(raw["prompt"]),
                files={str(k): str(v) for k, v in raw["files"].items()},
            )
        )
    return samples


def _tool_call_functions(log: Any) -> list[str]:
    result: list[str] = []
    for sample in getattr(log, "samples", None) or []:
        for message in getattr(sample, "messages", None) or []:
            for call in getattr(message, "tool_calls", None) or []:
                function = getattr(call, "function", None)
                if isinstance(function, str):
                    result.append(function)
    return result


def _receipt_values(path: Path) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    result: list[dict[str, Any]] = []
    for number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkflowError(
                f"invalid Jev tool receipt line {number} in {path}: {exc}"
            ) from exc
        if not isinstance(value, dict) or value.get("schema") != TOOL_RECEIPT_SCHEMA:
            raise WorkflowError(f"invalid Jev tool receipt at {path}:{number}")
        result.append(value)
    return result


def _receipt_summary(path: Path) -> dict[str, object]:
    receipts = _receipt_values(path)
    primitive_counts = {name: 0 for name in sorted(_ALLOWED_PRIMITIVES)}
    statuses: dict[str, int] = {}
    input_tokens = output_tokens = provider_total_tokens = 0.0
    token_records = 0
    durations: list[float] = []
    for receipt in receipts:
        status = str(receipt.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        counts = receipt.get("primitive_counts")
        if isinstance(counts, Mapping):
            for name in primitive_counts:
                value = counts.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    primitive_counts[name] += value
        duration = receipt.get("duration_ms")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            durations.append(float(duration))
        response = receipt.get("response")
        usage = response.get("usage") if isinstance(response, Mapping) else None
        if isinstance(usage, Mapping):
            fields = (
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                usage.get("provider_total_tokens"),
            )
            if all(
                isinstance(item, (int, float)) and not isinstance(item, bool)
                for item in fields
            ):
                input_tokens += float(fields[0])
                output_tokens += float(fields[1])
                provider_total_tokens += float(fields[2])
                token_records += 1
    return {
        "receipts": len(receipts),
        "statuses": statuses,
        "primitive_counts": primitive_counts,
        "token_records": token_records,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "provider_total_tokens": provider_total_tokens,
        },
        "duration_ms": {
            "n": len(durations),
            "total": sum(durations),
            "min": min(durations) if durations else None,
            "max": max(durations) if durations else None,
        },
    }


def create_agentic_jev_runtime_lock(
    *,
    destination: Path,
    tasks_path: Path,
    agent_model: str,
    agent_reasoning_effort: str,
    agent_model_args: Mapping[str, Any] | None = None,
    jev_model: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from .inspect_adjudication import (
        INSPECT_AI_VERSION,
        INSPECT_SWE_VERSION,
        _docker_identity,
        resolve_latest_codex_cli,
    )

    destination = Path(destination)
    if destination.exists() and not force:
        raise WorkflowError(f"agentic Jev runtime lock already exists: {destination}")
    if destination.exists() and (destination.is_dir() or destination.is_symlink()):
        raise WorkflowError("agentic Jev runtime lock must be a regular file")

    tasks = load_pilot_tasks(Path(tasks_path))
    if len(tasks["tasks"]) != 24:
        raise WorkflowError("agentic Jev runtime lock requires exactly 24 pilot tasks")
    sdk_version = _typesafe_sdk_version()
    if sdk_version != TYPESAFE_SDK_VERSION:
        observed = sdk_version or "not installed"
        raise WorkflowError(
            "agentic Jev runtime freeze requires "
            f"typesafe-sdk=={TYPESAFE_SDK_VERSION}; observed {observed}"
        )
    model = str(agent_model).strip()
    if model != PILOT_AGENT_MODEL:
        raise WorkflowError(
            "agentic Jev pilot model is frozen to "
            f"{PILOT_AGENT_MODEL}; observed {model or 'empty'}"
        )
    reasoning_effort = str(agent_reasoning_effort).strip()
    if reasoning_effort != PILOT_AGENT_REASONING_EFFORT:
        raise WorkflowError(
            "agentic Jev pilot reasoning effort is frozen to "
            f"{PILOT_AGENT_REASONING_EFFORT}; observed {reasoning_effort or 'empty'}"
        )
    model_args = dict(agent_model_args or {})
    if model_args.get("responses_api") is not True:
        raise WorkflowError(
            "agentic Jev pilot requires model_args.responses_api=true"
        )
    forbidden_reasoning_keys = {
        "reasoning",
        "reasoning_effort",
        "reasoningEffort",
    }
    if forbidden_reasoning_keys.intersection(model_args):
        raise WorkflowError(
            "agentic Jev reasoning effort must be supplied through Inspect "
            "generation config, not model_args"
        )

    codex_cli = resolve_latest_codex_cli()
    resolved_codex_version = str(codex_cli["resolved"])
    if _codex_version_tuple(resolved_codex_version) < PILOT_CODEX_MIN_VERSION:
        minimum = ".".join(str(item) for item in PILOT_CODEX_MIN_VERSION)
        raise WorkflowError(
            "agentic Jev pilot requires Codex CLI "
            f">={minimum} for {PILOT_CODEX_MODEL_CONFIG}; "
            f"resolved {resolved_codex_version}"
        )

    record = {
        "schema": "agent-workflow-benchmark/agentic-jev-runtime-lock/v1",
        "created_at": _utc(),
        "study_id": PILOT_STUDY_ID,
        "inspect_ai_version": INSPECT_AI_VERSION,
        "inspect_swe_version": INSPECT_SWE_VERSION,
        "codex_cli": codex_cli,
        "codex_model_config": PILOT_CODEX_MODEL_CONFIG,
        "agent_model": model,
        "agent_reasoning_effort": reasoning_effort,
        "agent_model_args": model_args,
        "jev_model": jev_model,
        "skill": {
            "upstream_commit": SKILL_UPSTREAM_COMMIT,
            "upstream_release": SKILL_UPSTREAM_RELEASE,
            "sha256": agentic_jev_skill_sha256(),
        },
        "tasks": {
            "path": str(Path(tasks_path).resolve()),
            "sha256": sha256_file(Path(tasks_path)),
            "count": len(tasks["tasks"]),
            "version": str(tasks["version"]),
        },
        "tool": {
            "transport": "Inspect bridged tool / MCP",
            "execution_location": "host",
            "api_key_location": "host-only",
            "receipt_schema": TOOL_RECEIPT_SCHEMA,
            "primitives": sorted(_ALLOWED_PRIMITIVES),
        },
        "host_tool": {
            "module": "agent_workflow_benchmark.benchmarking.agentic_jev",
            "implementation_sha256": sha256_file(Path(__file__).resolve()),
            "typesafe_sdk_version": sdk_version,
        },
        "inspect_harness": {
            "module": "agent_workflow_benchmark.benchmarking.inspect_adjudication",
            "implementation_sha256": _inspect_harness_sha256(),
        },
        "docker": _docker_identity(),
        "sandbox_image": _sandbox_image_identity(),
        "frozen_for_pilot": True,
    }
    validate_instance(
        record,
        "agent-workflow-benchmark/agentic-jev-runtime-lock/v1",
        artifact="agentic Jev runtime lock",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, record)
    return {"path": str(destination), "sha256": sha256_file(destination), **record}


def load_agentic_jev_runtime_lock(path: Path) -> dict[str, Any]:
    from .inspect_adjudication import (
        _docker_identity,
        _require_inspect_dependencies,
        _sandbox_platform,
    )

    value = _read_json_object(Path(path))
    validate_instance(
        value,
        "agent-workflow-benchmark/agentic-jev-runtime-lock/v1",
        artifact=str(path),
    )
    _require_inspect_dependencies()
    if value["codex_model_config"] != PILOT_CODEX_MODEL_CONFIG:
        raise WorkflowError(
            "agentic Jev runtime lock Codex model config no longer matches pilot"
        )
    if _codex_version_tuple(str(value["codex_cli"]["resolved"])) < PILOT_CODEX_MIN_VERSION:
        raise WorkflowError(
            "agentic Jev runtime lock Codex CLI is too old for GPT-6 Luna"
        )
    if value["agent_model"] != PILOT_AGENT_MODEL:
        raise WorkflowError("agentic Jev runtime lock model no longer matches pilot")
    if value["agent_reasoning_effort"] != PILOT_AGENT_REASONING_EFFORT:
        raise WorkflowError(
            "agentic Jev runtime lock reasoning effort no longer matches pilot"
        )
    if value["agent_model_args"].get("responses_api") is not True:
        raise WorkflowError(
            "agentic Jev runtime lock no longer requires Responses API"
        )
    if value["codex_cli"]["platform"] != _sandbox_platform():
        raise WorkflowError(
            "agentic Jev runtime lock Codex platform no longer matches the host"
        )
    if value["docker"] != _docker_identity():
        raise WorkflowError(
            "agentic Jev runtime lock Docker/Compose identity no longer matches"
        )
    if value["sandbox_image"] != _sandbox_image_identity():
        raise WorkflowError(
            "agentic Jev runtime lock sandbox image identity no longer matches"
        )
    if value["skill"]["sha256"] != agentic_jev_skill_sha256():
        raise WorkflowError("agentic Jev runtime lock skill hash does not match package")
    inspect_harness = value["inspect_harness"]
    if inspect_harness["implementation_sha256"] != _inspect_harness_sha256():
        raise WorkflowError(
            "agentic Jev runtime lock Inspect harness implementation hash no longer matches"
        )
    host_tool = value["host_tool"]
    if host_tool["implementation_sha256"] != sha256_file(Path(__file__).resolve()):
        raise WorkflowError(
            "agentic Jev runtime lock host-tool implementation hash no longer matches"
        )
    if host_tool["typesafe_sdk_version"] != _typesafe_sdk_version():
        raise WorkflowError(
            "agentic Jev runtime lock TypeSafe SDK version no longer matches"
        )
    tasks_path = Path(str(value["tasks"]["path"]))
    if not tasks_path.is_file() or sha256_file(tasks_path) != value["tasks"]["sha256"]:
        raise WorkflowError("agentic Jev runtime lock task manifest no longer matches")
    return value


def run_agentic_jev_tool_qualification(
    *,
    output_root: Path,
    runtime_lock_path: Path,
    force: bool = False,
) -> dict[str, Any]:
    try:
        import inspect_ai
        from inspect_ai import Task
        from inspect_ai.dataset import Sample
    except ImportError as exc:
        raise WorkflowError(
            "agent-directed Jev qualification requires agent-workflow-benchmark[agentic-jev]"
        ) from exc
    from .inspect_adjudication import _inspect_sandbox_spec

    runtime_lock_path = Path(runtime_lock_path)
    runtime_lock = load_agentic_jev_runtime_lock(runtime_lock_path)
    codex_version = str(runtime_lock["codex_cli"]["resolved"])
    model = str(runtime_lock["agent_model"])
    reasoning_effort = str(runtime_lock["agent_reasoning_effort"])
    model_args = dict(runtime_lock["agent_model_args"])
    jev_model = runtime_lock.get("jev_model")

    output_root = Path(output_root)
    result_path = output_root / "qualification.json"
    if result_path.exists() and not force:
        raise WorkflowError(
            f"agent-directed Jev qualification already exists: {result_path}"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    receipt_path = output_root / "jev-tool-receipts.jsonl"
    if receipt_path.exists() and force:
        receipt_path.unlink()

    solver = build_agentic_jev_solver(
        arm_id="C-skill-plus-jev",
        codex_version=codex_version,
        receipt_path=receipt_path,
        jev_model=jev_model,
    )
    sample = Sample(
        id="agentic-jev-tool-smoke",
        input=(
            "Use the available Jev semantic tool exactly once. Give it bounded state "
            "describing this request: 'Review the existing parser change for defects; "
            "do not modify product behavior.' Ask one Choice question selecting the "
            "primary work type from implementation, diagnosis, review, documentation, "
            "or other. Then report the returned selected value and stop. Do not edit files."
        ),
        files={"README.md": "Synthetic agent-directed Jev qualification fixture.\n"},
    )
    task = Task(
        dataset=[sample],
        solver=solver,
        sandbox=_inspect_sandbox_spec(),
        checkpoint=False,
    )
    logs = inspect_ai.eval(
        task,
        model=model,
        model_args=dict(model_args or {}),
        reasoning_effort=reasoning_effort,
        log_dir=str(output_root / "inspect-logs"),
        log_format="eval",
        max_samples=1,
        max_sandboxes=1,
        max_subprocesses=2,
        fail_on_error=True,
        retry_on_error=0,
        score=False,
        display="plain",
    )
    if len(logs) != 1 or getattr(logs[0], "status", None) != "success":
        raise WorkflowError("agent-directed Jev tool qualification did not complete")
    log = logs[0]
    samples = getattr(log, "samples", None) or []
    if len(samples) != 1 or getattr(samples[0], "error", None):
        raise WorkflowError("agent-directed Jev tool qualification sample failed")

    functions = _tool_call_functions(log)
    jev_functions = [
        name for name in functions if name.endswith("jev_system_one")
    ]
    receipts = _receipt_values(receipt_path)
    successful = [item for item in receipts if item.get("status") == "success"]
    api_key = os.environ.get("TYPESAFE_API_KEY")
    transcript = json.dumps(
        [
            getattr(message, "model_dump", lambda: {"text": str(message)})()
            for message in (getattr(samples[0], "messages", None) or [])
        ],
        ensure_ascii=False,
        default=str,
    )
    key_absent = not api_key or api_key not in transcript
    qualified = (
        len(jev_functions) == 1
        and len(receipts) == 1
        and len(successful) == 1
        and key_absent
        and agentic_jev_skill_path().is_file()
    )
    record = {
        "schema": "agent-workflow-benchmark/agentic-jev-tool-qualification/v1",
        "study_id": PILOT_STUDY_ID,
        "created_at": _utc(),
        "qualified": qualified,
        "runtime_lock_sha256": sha256_file(runtime_lock_path),
        "codex_version": codex_version,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "jev_model": jev_model,
        "skill_sha256": agentic_jev_skill_sha256(),
        "tool_functions": functions,
        "receipt_summary": _receipt_summary(receipt_path),
        "checks": {
            "jev_tool_called": bool(jev_functions),
            "exactly_one_jev_tool_call": len(jev_functions) == 1,
            "exactly_one_receipt": len(receipts) == 1,
            "exactly_one_successful_receipt": len(successful) == 1,
            "api_key_absent_from_agent_transcript": key_absent,
            "skill_snapshot_present": agentic_jev_skill_path().is_file(),
        },
        "inspect_log": getattr(log, "location", None),
    }
    validate_instance(
        record,
        "agent-workflow-benchmark/agentic-jev-tool-qualification/v1",
        artifact="agentic Jev tool qualification",
    )
    atomic_write_json(result_path, record)
    if not qualified:
        raise WorkflowError(
            "agent-directed Jev tool qualification failed; inspect qualification.json"
        )
    return {"path": str(result_path), **record}


def run_agentic_jev_pilot(
    *,
    output_root: Path,
    runtime_lock_path: Path,
    qualification_path: Path,
    force: bool = False,
) -> dict[str, Any]:
    try:
        import inspect_ai
        from inspect_ai import Task
    except ImportError as exc:
        raise WorkflowError(
            "agent-directed Jev pilot requires agent-workflow-benchmark[agentic-jev]"
        ) from exc
    from .inspect_adjudication import _inspect_sandbox_spec

    runtime_lock_path = Path(runtime_lock_path)
    runtime_lock = load_agentic_jev_runtime_lock(runtime_lock_path)
    tasks_path = Path(str(runtime_lock["tasks"]["path"]))
    tasks = load_pilot_tasks(tasks_path)
    codex_version = str(runtime_lock["codex_cli"]["resolved"])
    model = str(runtime_lock["agent_model"])
    reasoning_effort = str(runtime_lock["agent_reasoning_effort"])
    model_args = dict(runtime_lock["agent_model_args"])
    jev_model = runtime_lock.get("jev_model")
    if len(tasks["tasks"]) != 24:
        raise WorkflowError(
            "the registered agentic Jev pilot requires exactly 24 development tasks"
        )

    qualification_path = Path(qualification_path)
    qualification = _read_json_object(qualification_path)
    validate_instance(
        qualification,
        "agent-workflow-benchmark/agentic-jev-tool-qualification/v1",
        artifact=str(qualification_path),
    )
    if qualification.get("qualified") is not True:
        raise WorkflowError("agentic Jev tool qualification is not passing")
    if qualification.get("skill_sha256") != agentic_jev_skill_sha256():
        raise WorkflowError("agentic Jev qualification used a different skill snapshot")
    if qualification.get("runtime_lock_sha256") != sha256_file(runtime_lock_path):
        raise WorkflowError("agentic Jev qualification used a different runtime lock")

    output_root = Path(output_root)
    manifest_path = output_root / "run-manifest.json"
    if manifest_path.exists() and not force:
        raise WorkflowError(f"agentic Jev pilot already exists: {manifest_path}")
    output_root.mkdir(parents=True, exist_ok=True)

    samples = _pilot_samples(tasks)
    arm_results: dict[str, Any] = {}
    for arm in PILOT_ARMS:
        arm_root = output_root / arm.arm_id
        arm_root.mkdir(parents=True, exist_ok=True)
        receipt_path = arm_root / "jev-tool-receipts.jsonl"
        if receipt_path.exists() and force:
            receipt_path.unlink()
        solver = build_agentic_jev_solver(
            arm_id=arm.arm_id,
            codex_version=codex_version,
            receipt_path=receipt_path,
            jev_model=jev_model,
        )
        task = Task(
            dataset=samples,
            solver=solver,
            sandbox=_inspect_sandbox_spec(),
            checkpoint=False,
        )
        logs = inspect_ai.eval(
            task,
            model=model,
            model_args=dict(model_args or {}),
            reasoning_effort=reasoning_effort,
            log_dir=str(arm_root / "inspect-logs"),
            log_format="eval",
            max_samples=len(samples),
            max_sandboxes=min(8, len(samples)),
            max_subprocesses=max(2, min(8, len(samples))),
            fail_on_error=False,
            retry_on_error=0,
            score=False,
            display="plain",
        )
        if len(logs) != 1:
            raise WorkflowError(
                f"agentic Jev arm {arm.arm_id} expected one Inspect log"
            )
        log = logs[0]
        log_samples = getattr(log, "samples", None) or []
        statuses = {"success": 0, "error": 0}
        for sample in log_samples:
            if getattr(sample, "error", None):
                statuses["error"] += 1
            else:
                statuses["success"] += 1
        functions = _tool_call_functions(log)
        jev_calls = sum(
            1 for name in functions if name.endswith("jev_system_one")
        )
        receipts = _receipt_summary(receipt_path)
        if not arm.jev_tool and (jev_calls or receipts["receipts"]):
            raise WorkflowError(
                f"arm {arm.arm_id} recorded Jev calls despite tool being disabled"
            )
        arm_results[arm.arm_id] = {
            "typesafe_skill": arm.typesafe_skill,
            "jev_tool": arm.jev_tool,
            "inspect_log": getattr(log, "location", None),
            "samples": len(log_samples),
            "sample_status": statuses,
            "jev_tool_calls": jev_calls,
            "tool_receipts": receipts,
        }

    manifest = {
        "schema": "agent-workflow-benchmark/agentic-jev-pilot-run/v1",
        "study_id": PILOT_STUDY_ID,
        "created_at": _utc(),
        "development_only": True,
        "runtime_lock_sha256": sha256_file(runtime_lock_path),
        "task_manifest": {
            "path": str(tasks_path),
            "sha256": sha256_file(tasks_path),
            "version": tasks["version"],
            "tasks": len(tasks["tasks"]),
            "authoring_tags_exposed_to_agents": False,
        },
        "runtime": {
            "codex_version": codex_version,
            "codex_model_config": PILOT_CODEX_MODEL_CONFIG,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "jev_model": jev_model,
        },
        "treatment": pilot_treatment_manifest(),
        "qualification": {
            "path": str(qualification_path),
            "sha256": sha256_file(qualification_path),
        },
        "arms": arm_results,
        "claim_boundary": {
            "exploratory_only": True,
            "effectiveness_claim_allowed": False,
            "purpose": "discover candidate agent-directed Jev seams before preregistration",
        },
    }
    validate_instance(
        manifest,
        "agent-workflow-benchmark/agentic-jev-pilot-run/v1",
        artifact="agentic Jev pilot run",
    )
    atomic_write_json(manifest_path, manifest)
    return {"path": str(manifest_path), **manifest}

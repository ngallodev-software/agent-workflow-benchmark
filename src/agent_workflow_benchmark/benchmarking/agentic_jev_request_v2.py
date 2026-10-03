"""Deterministic Jev request construction for versioned Agentic-Jev studies.

This module is additive. It does not alter the v1 bridge semantics that produced
the completed agentic-jev-swe-manager-v1 evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_workflow.errors import WorkflowError

REQUEST_BUILDER_SCHEMA = "agent-workflow-benchmark/jev-request-builder/v2"
REQUEST_HISTORY_SCHEMA = "agent-workflow-benchmark/jev-request-history/v2"
REQUEST_BUILDER_VERSION = "2.0.0"

_ALLOWED_PRIMITIVES = frozenset({"choice", "noul", "score"})
_MAX_TEXT = 8_000
_MAX_ITEMS = 100
_MAX_DEPTH = 8
_MAX_QUESTIONS = 16
_MAX_STATE_BYTES = 64 * 1024
_MAX_QUESTIONS_BYTES = 48 * 1024

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


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise WorkflowError("Jev request contains a non-JSON value") from exc


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _json_bytes(value: object) -> int:
    return len(canonical_json(value).encode("utf-8"))


def _secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").strip()
    return normalized in _SECRET_KEYS or normalized.endswith(_SECRET_SUFFIXES)


def _sanitize(
    value: Any,
    *,
    path: str = "$",
    key: str = "",
    depth: int = 0,
    redacted_paths: list[str] | None = None,
) -> Any:
    """Sanitize secrets but reject silent truncation or unsupported values."""
    if redacted_paths is None:
        redacted_paths = []
    if _secret_key(key):
        redacted_paths.append(path)
        return "[redacted]"
    if depth > _MAX_DEPTH:
        raise WorkflowError(f"Jev request exceeds maximum nesting depth at {path}")
    if isinstance(value, str):
        if len(value) > _MAX_TEXT:
            raise WorkflowError(
                f"Jev request text exceeds {_MAX_TEXT} characters at {path}"
            )
        return value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WorkflowError(f"Jev request contains a non-finite number at {path}")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_ITEMS:
            raise WorkflowError(
                f"Jev request object exceeds {_MAX_ITEMS} fields at {path}"
            )
        result: dict[str, Any] = {}
        for raw_key, child in value.items():
            item_key = str(raw_key)
            if not item_key.strip():
                raise WorkflowError(f"Jev request contains an empty key at {path}")
            if len(item_key) > 200:
                raise WorkflowError(f"Jev request key exceeds 200 characters at {path}")
            result[item_key] = _sanitize(
                child,
                path=f"{path}.{item_key}",
                key=item_key,
                depth=depth + 1,
                redacted_paths=redacted_paths,
            )
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > _MAX_ITEMS:
            raise WorkflowError(
                f"Jev request array exceeds {_MAX_ITEMS} items at {path}"
            )
        return [
            _sanitize(
                child,
                path=f"{path}[{index}]",
                depth=depth + 1,
                redacted_paths=redacted_paths,
            )
            for index, child in enumerate(value)
        ]
    raise WorkflowError(
        f"Jev request contains unsupported {type(value).__name__} at {path}"
    )


def _nonempty_json(value: object, *, label: str) -> None:
    if isinstance(value, str):
        if not value.strip():
            raise WorkflowError(f"{label} must be non-empty")
        return
    if isinstance(value, Mapping) or (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
    ):
        if not value:
            raise WorkflowError(f"{label} must be non-empty")
        return
    if value is None:
        raise WorkflowError(f"{label} must be non-empty")


def _validate_question_spec(
    question_id: str,
    raw_spec: Mapping[str, object],
    *,
    redacted_paths: list[str],
) -> dict[str, object]:
    primitive = str(raw_spec.get("type") or "").lower().strip()
    if primitive not in _ALLOWED_PRIMITIVES:
        raise WorkflowError(
            f"Jev question {question_id!r} has unsupported type {primitive!r}"
        )

    instructions = raw_spec.get("instructions")
    if not isinstance(instructions, (str, Mapping, list)):
        raise WorkflowError(
            f"Jev question {question_id!r} requires JSON instructions"
        )
    _nonempty_json(instructions, label=f"Jev question {question_id!r} instructions")
    safe_instructions = _sanitize(
        instructions,
        path=f"$.questions.{question_id}.instructions",
        key="instructions",
        redacted_paths=redacted_paths,
    )

    spec: dict[str, object] = {
        "type": primitive,
        "instructions": safe_instructions,
    }
    criteria = raw_spec.get("criteria")

    if primitive == "choice":
        if not isinstance(criteria, Mapping) or not 2 <= len(criteria) <= _MAX_ITEMS:
            raise WorkflowError(
                f"Jev choice question {question_id!r} requires 2-{_MAX_ITEMS} criteria"
            )
        normalized: dict[str, object] = {}
        for raw_key, description in criteria.items():
            key = str(raw_key).strip()
            if not key:
                raise WorkflowError(
                    f"Jev choice question {question_id!r} has an empty criterion ID"
                )
            if key in normalized:
                raise WorkflowError(
                    f"Jev choice question {question_id!r} has duplicate criterion ID {key!r}"
                )
            if description is not None and not isinstance(
                description, (str, Mapping, list)
            ):
                raise WorkflowError(
                    f"Jev choice criterion {key!r} must be JSON text/object/array/null"
                )
            if description is not None:
                _nonempty_json(
                    description,
                    label=f"Jev choice criterion {key!r}",
                )
            normalized[key] = _sanitize(
                description,
                path=f"$.questions.{question_id}.criteria.{key}",
                key=key,
                redacted_paths=redacted_paths,
            )
        spec["criteria"] = normalized

    elif primitive == "score":
        if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
            raise WorkflowError(
                f"Jev score question {question_id!r} requires 2-10 ordered criteria"
            )
        normalized_levels: list[object] = []
        for index, description in enumerate(criteria):
            if not isinstance(description, (str, Mapping, list)):
                raise WorkflowError(
                    f"Jev score level {index} must be JSON text/object/array"
                )
            _nonempty_json(
                description,
                label=f"Jev score level {index}",
            )
            normalized_levels.append(
                _sanitize(
                    description,
                    path=f"$.questions.{question_id}.criteria[{index}]",
                    redacted_paths=redacted_paths,
                )
            )
        spec["criteria"] = normalized_levels

    else:
        if criteria is not None:
            if not isinstance(criteria, Mapping) or set(map(str, criteria)) != {
                "true",
                "false",
            }:
                raise WorkflowError(
                    f"Jev noul question {question_id!r} criteria, when present, "
                    "must contain exactly true and false"
                )
            normalized_noul: dict[str, object] = {}
            for raw_key, description in criteria.items():
                key = str(raw_key)
                if description is not None and not isinstance(
                    description, (str, Mapping, list)
                ):
                    raise WorkflowError(
                        f"Jev noul criterion {key!r} must be JSON text/object/array/null"
                    )
                if description is not None:
                    _nonempty_json(
                        description,
                        label=f"Jev noul criterion {key!r}",
                    )
                normalized_noul[key] = _sanitize(
                    description,
                    path=f"$.questions.{question_id}.criteria.{key}",
                    key=key,
                    redacted_paths=redacted_paths,
                )
            spec["criteria"] = normalized_noul

    return spec


def normalize_questions(
    questions: Mapping[str, object],
    *,
    redacted_paths: list[str] | None = None,
) -> dict[str, object]:
    if redacted_paths is None:
        redacted_paths = []
    if not isinstance(questions, Mapping) or not questions:
        raise WorkflowError("Jev request requires at least one question")
    if len(questions) > _MAX_QUESTIONS:
        raise WorkflowError(
            f"Jev request accepts at most {_MAX_QUESTIONS} questions"
        )

    normalized: dict[str, object] = {}
    for raw_id, raw_spec in questions.items():
        question_id = str(raw_id).strip()
        if not question_id:
            raise WorkflowError("Jev question IDs must be non-empty")
        if question_id in normalized:
            raise WorkflowError(f"duplicate Jev question ID {question_id!r}")
        if not isinstance(raw_spec, Mapping):
            raise WorkflowError(f"Jev question {question_id!r} must be an object")
        normalized[question_id] = _validate_question_spec(
            question_id,
            raw_spec,
            redacted_paths=redacted_paths,
        )

    if _json_bytes(normalized) > _MAX_QUESTIONS_BYTES:
        raise WorkflowError("Jev question bundle exceeds the v2 local size limit")
    return normalized


def build_jev_request(
    *,
    state: Mapping[str, object],
    questions: Mapping[str, object],
    purpose: str,
    model: str | None = None,
    policy_id: str = "generic-v2",
    previous_decision_sha256: str | None = None,
    change_reason: str | None = None,
    agent_input: Mapping[str, object] | None = None,
    transformation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Validate, normalize, hash, and revision-bind one Jev request."""
    if not isinstance(state, Mapping) or not state:
        raise WorkflowError("Jev state must be a non-empty object")
    if not isinstance(purpose, str) or not purpose.strip():
        raise WorkflowError("Jev request purpose must be non-empty")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise WorkflowError("Jev model must be a non-empty string or null")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise WorkflowError("Jev request policy_id must be non-empty")

    if previous_decision_sha256 is not None:
        if re.fullmatch(r"[0-9a-f]{64}", previous_decision_sha256) is None:
            raise WorkflowError(
                "previous_decision_sha256 must be a lowercase SHA-256"
            )
        if not isinstance(change_reason, str) or not change_reason.strip():
            raise WorkflowError(
                "a revised Jev request requires a non-empty change_reason"
            )
    elif change_reason is not None:
        raise WorkflowError(
            "change_reason requires previous_decision_sha256"
        )

    redacted_paths: list[str] = []
    safe_state = _sanitize(
        state,
        path="$.state",
        redacted_paths=redacted_paths,
    )
    if not isinstance(safe_state, dict) or not safe_state:
        raise WorkflowError("Jev normalized state must be a non-empty object")
    if _json_bytes(safe_state) > _MAX_STATE_BYTES:
        raise WorkflowError("Jev state exceeds the v2 local size limit")

    safe_questions = normalize_questions(
        questions,
        redacted_paths=redacted_paths,
    )
    safe_purpose = _sanitize(
        purpose,
        path="$.purpose",
        key="purpose",
        redacted_paths=redacted_paths,
    )
    if not isinstance(safe_purpose, str) or not safe_purpose.strip():
        raise WorkflowError("Jev normalized purpose must be non-empty")

    request = {
        "state": safe_state,
        "questions": safe_questions,
        "model": model,
    }
    decision_payload = {
        "state": safe_state,
        "questions": safe_questions,
    }
    decision_sha256 = sha256_json(decision_payload)
    if previous_decision_sha256 == decision_sha256:
        raise WorkflowError(
            "revised Jev request is semantically unchanged; gather materially "
            "new evidence or change the alternatives before calling Jev again"
        )

    safe_agent_input: dict[str, object] | None = None
    if agent_input is not None:
        safe_agent_input_value = _sanitize(
            agent_input,
            path="$.agent_input",
            redacted_paths=redacted_paths,
        )
        if not isinstance(safe_agent_input_value, dict):
            raise WorkflowError("agent_input must normalize to an object")
        safe_agent_input = safe_agent_input_value

    safe_transformation: dict[str, object] = {}
    if transformation is not None:
        safe_transformation_value = _sanitize(
            transformation,
            path="$.transformation",
            redacted_paths=redacted_paths,
        )
        if not isinstance(safe_transformation_value, dict):
            raise WorkflowError("transformation metadata must normalize to an object")
        safe_transformation = safe_transformation_value

    result: dict[str, object] = {
        "schema": REQUEST_BUILDER_SCHEMA,
        "builder_version": REQUEST_BUILDER_VERSION,
        "policy_id": policy_id,
        "purpose": safe_purpose,
        "request": request,
        "state_sha256": sha256_json(safe_state),
        "questions_sha256": sha256_json(safe_questions),
        "decision_sha256": decision_sha256,
        "request_sha256": sha256_json(request),
        "sizes": {
            "state_bytes": _json_bytes(safe_state),
            "questions_bytes": _json_bytes(safe_questions),
            "request_bytes": _json_bytes(request),
        },
        "revision": {
            "previous_decision_sha256": previous_decision_sha256,
            "change_reason": change_reason,
        },
        "privacy": {
            "redacted_paths": sorted(set(redacted_paths)),
            "silent_truncation": False,
        },
        "transformation": safe_transformation,
    }
    if safe_agent_input is not None:
        result["agent_input"] = safe_agent_input
        result["agent_input_sha256"] = sha256_json(safe_agent_input)
    return result


def verify_built_jev_request(value: Mapping[str, object]) -> None:
    if not isinstance(value, Mapping):
        raise WorkflowError("built Jev request must be an object")
    if value.get("schema") != REQUEST_BUILDER_SCHEMA:
        raise WorkflowError("built Jev request has an unknown schema")
    request = value.get("request")
    if not isinstance(request, Mapping):
        raise WorkflowError("built Jev request is missing provider request")
    if set(request) != {"state", "questions", "model"}:
        raise WorkflowError("built Jev provider request has an invalid shape")
    state = request.get("state")
    questions = request.get("questions")
    if not isinstance(state, Mapping) or not isinstance(questions, Mapping):
        raise WorkflowError("built Jev request state/questions are malformed")

    expected = {
        "state_sha256": sha256_json(state),
        "questions_sha256": sha256_json(questions),
        "decision_sha256": sha256_json(
            {"state": state, "questions": questions}
        ),
        "request_sha256": sha256_json(request),
    }
    for key, digest in expected.items():
        if value.get(key) != digest:
            raise WorkflowError(
                f"built Jev request changed after validation ({key})"
            )


def _append_history(path: Path | None, value: Mapping[str, object]) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
        )


def execute_built_jev_request(
    built: Mapping[str, object],
    *,
    receipt_path: Path,
    history_path: Path,
    study_id: str,
    client: Any | None = None,
) -> dict[str, object]:
    """Execute exactly the normalized request and persist an explicit v2 history."""
    verify_built_jev_request(built)
    request = built["request"]
    assert isinstance(request, Mapping)
    state = request["state"]
    questions = request["questions"]
    model = request.get("model")
    assert isinstance(state, Mapping)
    assert isinstance(questions, Mapping)

    history_base: dict[str, object] = {
        "schema": REQUEST_HISTORY_SCHEMA,
        "timestamp": _utc(),
        "study_id": study_id,
        "builder_version": built.get("builder_version"),
        "policy_id": built.get("policy_id"),
        "purpose": built.get("purpose"),
        "request_sha256": built.get("request_sha256"),
        "decision_sha256": built.get("decision_sha256"),
        "state_sha256": built.get("state_sha256"),
        "questions_sha256": built.get("questions_sha256"),
        "revision": built.get("revision"),
        "sizes": built.get("sizes"),
        "privacy": built.get("privacy"),
        "transformation": built.get("transformation"),
        "request": {
            "state": state,
            "questions": questions,
            "model": model,
        },
        "provider_receipt_path": str(Path(receipt_path)),
    }
    if built.get("agent_input") is not None:
        history_base["agent_input"] = built.get("agent_input")
        history_base["agent_input_sha256"] = built.get("agent_input_sha256")

    try:
        from .agentic_jev import execute_jev_request

        result = execute_jev_request(
            state=state,
            questions=questions,
            purpose=str(built.get("purpose") or ""),
            model=model if isinstance(model, str) else None,
            client=client,
            receipt_path=receipt_path,
            study_id=study_id,
        )
        if result.get("request_sha256") != built.get("request_sha256"):
            raise WorkflowError(
                "provider-dispatch request hash differs from the validated builder request"
            )
        record = {
            **history_base,
            "status": "success",
            "provider_request_id": result.get("request_id"),
            "resolved_model": result.get("model"),
            "response": {
                "answers": result.get("answers"),
                "usage": result.get("usage"),
                "duration_ms": result.get("duration_ms"),
            },
        }
        _append_history(history_path, record)
        return {
            **result,
            "decision_sha256": built.get("decision_sha256"),
            "state_sha256": built.get("state_sha256"),
            "questions_sha256": built.get("questions_sha256"),
            "history_schema": REQUEST_HISTORY_SCHEMA,
        }
    except Exception as exc:
        _append_history(
            history_path,
            {
                **history_base,
                "status": "execution_failure",
                "error_class": type(exc).__name__,
            },
        )
        raise

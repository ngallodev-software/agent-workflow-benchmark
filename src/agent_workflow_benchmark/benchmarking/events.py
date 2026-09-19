from __future__ import annotations

from pathlib import Path
from typing import Any

from .schema_contracts import validate_instance
from agent_workflow.errors import WorkflowError
from agent_workflow.journal import JournalTransactionResult, read_jsonl, transact_jsonl
from agent_workflow.util import utc_now
from .contracts import BENCHMARK_PHASE_EVENT_SCHEMA


def _validate_event(value: object, line_number: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowError("benchmark event must be a JSON object")
    validate_instance(value, BENCHMARK_PHASE_EVENT_SCHEMA, artifact=f"benchmark event:{line_number}")
    if value.get("sequence") != line_number:
        raise WorkflowError(
            f"benchmark event sequence mismatch: expected {line_number}, got {value.get('sequence')!r}"
        )
    return value


def append_event(
    run_dir: Path,
    *,
    event_type: str,
    run_id: str,
    pair_id: str | None = None,
    arm: str | None = None,
    phase_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = run_dir / "events.jsonl"

    def decide(existing: list[dict[str, Any]]) -> JournalTransactionResult[dict[str, Any]]:
        event = {
            "schema": BENCHMARK_PHASE_EVENT_SCHEMA,
            "sequence": len(existing) + 1,
            "recorded_at": utc_now(),
            "event_type": event_type,
            "run_id": run_id,
            "pair_id": pair_id,
            "arm": arm,
            "phase_id": phase_id,
            "payload": payload or {},
        }
        event = _validate_event(event, len(existing) + 1)
        return JournalTransactionResult(value=event, record=event)

    return transact_jsonl(
        path,
        validator=_validate_event,
        transaction=decide,
        sequence_field="sequence",
    )


def read_events(run_dir: Path) -> list[dict[str, Any]]:
    return read_jsonl(
        run_dir / "events.jsonl",
        validator=_validate_event,
        missing_ok=True,
        sequence_field="sequence",
    )

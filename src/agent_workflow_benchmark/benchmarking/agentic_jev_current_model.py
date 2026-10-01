from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json

from .agentic_jev import (
    _receipt_summary,
    _receipt_values,
    jev_bridged_tool,
)
from .agentic_jev_decision_v4 import (
    decision_skill_interface_sha256,
    decision_skill_path,
    decision_skill_sha256,
    source_manifest,
)
from .schema_contracts import validate_instance

STUDY_ID = "agentic-jev-current-model-qualification-v1"
QUAL_SCHEMA = "agent-workflow-benchmark/agentic-jev-current-model-qualification/v1"
SUPPORTED_MODELS: dict[str, str] = {
    "openai-api/codex-lb/gpt-6-luna": "gpt-6-luna",
    "openai-api/codex-lb/gpt-6.1-sol": "gpt-6.1-sol",
}
DEFAULT_MODEL = "openai-api/codex-lb/gpt-6-luna"
DEFAULT_REASONING_EFFORT = "high"

_REQUIREMENT = """# Requirement source\n\nChoose the cache invalidation design that best balances maintainability, review\nsurface, reversibility, and future extension. The public get()/set() API must remain\nunchanged. The current product is single-process. No specification or test ranks a\nsmaller diff above a centralized invariant, or vice versa.\n"""

_PROPOSAL_1 = """# proposal_1\n\nAdd a per-key generation token at the two mutation call sites. This is the smallest\ndiff and easiest rollback, but it duplicates invalidation coordination in two places\nthat must remain consistent.\n"""

_PROPOSAL_2 = """# proposal_2\n\nCentralize invalidation inside CacheStore.invalidate(). This creates one shared\ninvariant and a clearer extension point, but changes a shared path used by every\ncaller and therefore increases review surface.\n"""

_DEPENDENCY = """class CacheStore:\n    def get(self, key):\n        return self._entries.get(key)\n\n    def set(self, key, value):\n        self._entries[key] = value\n\n    def delete(self, key):\n        self._entries.pop(key, None)\n"""

_VERIFICATION = """Independent prototype verification\n- proposal_1: 17 passed, 0 failed\n- proposal_2: 17 passed, 0 failed\n- static checks: both candidates passed\n- Not exercised: multi-process invalidation (product is currently single-process)\n- Not exercised: long-running migration/rollback behavior\n"""

QUALIFICATION_FILES: dict[str, str] = {
    "requirement.md": _REQUIREMENT,
    "proposal_1.md": _PROPOSAL_1,
    "proposal_2.md": _PROPOSAL_2,
    "src/cache.py": _DEPENDENCY,
    "verification.txt": _VERIFICATION,
}

QUALIFICATION_PROMPT = """Review the supplied requirement, both proposals, the unchanged cache code, and the\nindependent verification output. Choose the better proposal. Do not edit files.\n\nThe deterministic evidence intentionally leaves a real semantic trade-off. Use the\ninstalled skills when they apply, but do not invent facts that are absent from the\nfiles.\n\nYour final response must be exactly one JSON object with these fields:\n- selected_option: proposal_1 or proposal_2\n- justification: a concise observable decision rationale (80-1200 characters)\n- evidence_refs: a JSON array naming at least three supplied files that materially\n  support the decision\n- tradeoff: the principal trade-off that determined the choice\n- semantic_evidence_reconciliation: how any semantic decision-support evidence was\n  weighed against the inspected primary evidence\n- remaining_uncertainty: a concise string, or null\n\nDo not expose private chain-of-thought. The justification should state the decisive\nevidence and trade-off, not hidden reasoning.\n"""

_CONTEXT_ANCHORS = {
    "requirement_verbatim": "The public get()/set() API must remain unchanged.",
    "proposal_1": "per-key generation token at the two mutation call sites",
    "proposal_2": "Centralize invalidation inside CacheStore.invalidate()",
    "unchanged_dependency": "class CacheStore:",
    "verification_result": "17 passed, 0 failed",
    "verification_scope": "Not exercised: multi-process invalidation",
}

_FORBIDDEN_AGENT_JUDGMENT_KEYS = frozenset(
    {
        "agent_choice",
        "agent_confidence",
        "initial_agent_choice",
        "my_choice",
        "preferred_answer",
        "preferred_option",
        "selected_option",
        "verdict",
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _string_values(value: object) -> list[str]:
    result: list[str] = []
    if isinstance(value, str):
        result.append(value)
    elif isinstance(value, Mapping):
        for child in value.values():
            result.extend(_string_values(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.extend(_string_values(child))
    return result


def _forbidden_keys(value: object) -> list[str]:
    found: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                key = str(raw_key).lower().replace("-", "_").strip()
                if key in _FORBIDDEN_AGENT_JUDGMENT_KEYS:
                    found.add(key)
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return sorted(found)


def inspect_jev_receipt_context(receipt: Mapping[str, object]) -> dict[str, object]:
    request = receipt.get("request")
    if not isinstance(request, Mapping):
        raise WorkflowError("successful Jev receipt has no request object")
    state = request.get("state")
    questions = request.get("questions")
    if not isinstance(state, Mapping) or not isinstance(questions, Mapping):
        raise WorkflowError("successful Jev receipt request is missing state/questions")

    searchable_state = re.sub(r"\s+", " ", "\n".join(_string_values(state)))
    anchors = {
        name: re.sub(r"\s+", " ", fragment) in searchable_state
        for name, fragment in _CONTEXT_ANCHORS.items()
    }
    choice_questions = [
        str(question_id)
        for question_id, spec in questions.items()
        if isinstance(spec, Mapping) and str(spec.get("type")) == "choice"
    ]
    forbidden = _forbidden_keys(state)
    purpose = receipt.get("purpose")
    checks = {
        "all_primary_evidence_present": all(anchors.values()),
        "choice_question_present": bool(choice_questions),
        "purpose_present": isinstance(purpose, str) and bool(purpose.strip()),
        "agent_judgment_keys_absent": not forbidden,
    }
    return {
        "checks": checks,
        "anchors": anchors,
        "choice_question_ids": choice_questions,
        "forbidden_agent_judgment_keys": forbidden,
        "state_sha256": receipt.get("state_sha256"),
        "questions_sha256": receipt.get("questions_sha256"),
        "request_sha256": receipt.get("request_sha256"),
    }


def parse_decision_record(text: str) -> dict[str, object]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkflowError("final assistant response is not exactly one JSON object") from exc
    if not isinstance(value, dict):
        raise WorkflowError("final assistant decision record must be an object")
    required = {
        "selected_option",
        "justification",
        "evidence_refs",
        "tradeoff",
        "semantic_evidence_reconciliation",
        "remaining_uncertainty",
    }
    if set(value) != required:
        raise WorkflowError(
            "decision record fields must be exactly: " + ", ".join(sorted(required))
        )
    if value["selected_option"] not in {"proposal_1", "proposal_2"}:
        raise WorkflowError("decision record selected_option is invalid")
    justification = value["justification"]
    if not isinstance(justification, str) or not 80 <= len(justification.strip()) <= 1200:
        raise WorkflowError("decision record justification must be 80-1200 characters")
    tradeoff = value["tradeoff"]
    reconciliation = value["semantic_evidence_reconciliation"]
    if not isinstance(tradeoff, str) or len(tradeoff.strip()) < 20:
        raise WorkflowError("decision record tradeoff is too short")
    if not isinstance(reconciliation, str) or len(reconciliation.strip()) < 20:
        raise WorkflowError("decision record semantic reconciliation is too short")
    refs = value["evidence_refs"]
    if not isinstance(refs, list) or len(refs) < 3 or not all(isinstance(x, str) and x for x in refs):
        raise WorkflowError("decision record requires at least three evidence_refs")
    if len(refs) != len(set(refs)):
        raise WorkflowError("decision record evidence_refs must be unique")
    unknown_refs = sorted(set(refs) - set(QUALIFICATION_FILES))
    if unknown_refs:
        raise WorkflowError("decision record contains unknown evidence refs: " + ", ".join(unknown_refs))
    remaining = value["remaining_uncertainty"]
    if remaining is not None and (not isinstance(remaining, str) or not remaining.strip()):
        raise WorkflowError("remaining_uncertainty must be a non-empty string or null")
    return value


def _final_assistant_text(log: Any) -> tuple[str, int]:
    samples = getattr(log, "samples", None) or []
    if len(samples) != 1:
        raise WorkflowError(f"current-model qualification expected one sample; observed {len(samples)}")
    sample = samples[0]
    if getattr(sample, "error", None):
        raise WorkflowError("current-model qualification sample failed")
    assistant_text: list[str] = []
    reasoning_blocks = 0
    for message in getattr(sample, "messages", None) or []:
        if str(getattr(message, "role", "")) != "assistant":
            continue
        text_value = getattr(message, "text", "")
        if callable(text_value):
            text_value = text_value()
        if text_value:
            assistant_text.append(str(text_value))
        content = getattr(message, "content", None)
        if isinstance(content, list):
            reasoning_blocks += sum(
                1 for item in content if str(getattr(item, "type", "")) == "reasoning"
            )
    if not assistant_text:
        raise WorkflowError("current-model qualification produced no visible assistant text")
    return assistant_text[-1], reasoning_blocks


def _transcript_contains_secret(log: Any) -> bool:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        return False
    samples = getattr(log, "samples", None) or []
    transcript = json.dumps(
        [
            getattr(message, "model_dump", lambda: {"text": str(message)})()
            for sample in samples
            for message in (getattr(sample, "messages", None) or [])
        ],
        ensure_ascii=False,
        default=str,
    )
    return api_key in transcript


def _build_solver(*, model_config: str, codex_version: str, receipt_path: Path, jev_model: str | None) -> Any:
    try:
        from inspect_ai.agent import BridgedToolsSpec
        from inspect_swe import codex_cli
    except ImportError as exc:
        raise WorkflowError(
            "current-model qualification requires agent-workflow-benchmark[agentic-jev]"
        ) from exc

    return codex_cli(
        version=codex_version,
        model_config=model_config,
        skills=[decision_skill_path().parent],
        bridged_tools=[
            BridgedToolsSpec(
                name="jev",
                tools=[jev_bridged_tool(receipt_path=receipt_path, model=jev_model)],
            )
        ],
        web_search="disabled",
        goals=False,
        attempts=1,
        mcp_servers=[],
        auto_review=False,
        home_dir="/tmp/codex-home",
        system_prompt=(
            "Complete the assigned bounded decision task from the supplied files. "
            "Use installed skills when applicable. Preserve deterministic evidence "
            "authority, keep semantic evidence advisory, and provide only the visible "
            "decision record requested by the task rather than private chain-of-thought."
        ),
        config_overrides={"approval_policy": "never", "web_search": "disabled"},
    )


def run_current_model_qualification(
    *,
    output_root: Path,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    jev_model: str | None = None,
) -> dict[str, Any]:
    try:
        import inspect_ai
        from inspect_ai import Task
        from inspect_ai.dataset import Sample
    except ImportError as exc:
        raise WorkflowError("current-model qualification requires Inspect AI") from exc
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise WorkflowError("TYPESAFE_API_KEY must be configured on the host")

    model = str(model).strip()
    model_config = SUPPORTED_MODELS.get(model)
    if model_config is None:
        raise WorkflowError(
            "current-model qualification model must be one of: "
            + ", ".join(sorted(SUPPORTED_MODELS))
        )
    reasoning_effort = str(reasoning_effort).strip()
    if reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
        raise WorkflowError("reasoning_effort must be low, medium, high, xhigh, or max")

    from .inspect_adjudication import _inspect_sandbox_spec, resolve_latest_codex_cli

    output_root = Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise WorkflowError(f"qualification root is not empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    receipt_path = output_root / "jev-tool-receipts.jsonl"
    codex = resolve_latest_codex_cli()
    codex_version = str(codex["resolved"])
    solver = _build_solver(
        model_config=model_config,
        codex_version=codex_version,
        receipt_path=receipt_path,
        jev_model=jev_model,
    )
    task = Task(
        dataset=[
            Sample(
                id="jev-current-model-context-and-rationale",
                input=QUALIFICATION_PROMPT,
                files=dict(QUALIFICATION_FILES),
            )
        ],
        solver=solver,
        sandbox=_inspect_sandbox_spec(),
        checkpoint=False,
    )
    logs = inspect_ai.eval(
        task,
        model=model,
        model_args={"responses_api": True},
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
    if len(logs) != 1:
        raise WorkflowError("current-model qualification produced no log")
    log = logs[0]
    final_text, reasoning_blocks = _final_assistant_text(log)
    decision_record = parse_decision_record(final_text)

    receipts = _receipt_values(receipt_path)
    successful = [item for item in receipts if item.get("status") == "success"]
    context_evidence: dict[str, object] | None = None
    if len(successful) == 1:
        context_evidence = inspect_jev_receipt_context(successful[0])

    checks = {
        "exactly_one_jev_call": len(receipts) == 1,
        "exactly_one_successful_jev_call": len(successful) == 1,
        "api_key_absent_from_transcript": not _transcript_contains_secret(log),
        "decision_record_valid": True,
        "observable_justification_present": bool(decision_record["justification"]),
        "observable_tradeoff_present": bool(decision_record["tradeoff"]),
        "semantic_reconciliation_present": bool(
            decision_record["semantic_evidence_reconciliation"]
        ),
        "reasoning_content_exported": False,
    }
    if context_evidence is None:
        checks.update(
            {
                "all_primary_evidence_present": False,
                "choice_question_present": False,
                "purpose_present": False,
                "agent_judgment_keys_absent": False,
            }
        )
    else:
        checks.update(context_evidence["checks"])

    qualified = all(
        bool(value)
        for key, value in checks.items()
        if key != "reasoning_content_exported"
    ) and checks["reasoning_content_exported"] is False

    source = source_manifest()
    record = {
        "schema": QUAL_SCHEMA,
        "study_id": STUDY_ID,
        "qualified": qualified,
        "runtime": {
            "model": model,
            "model_config": model_config,
            "reasoning_effort": reasoning_effort,
            "model_args": {"responses_api": True},
            "codex_cli": codex,
            "jev_model": jev_model,
        },
        "skill": {
            "repository": source["repository"],
            "commit": source["commit"],
            "path": source["path"],
            "source_skill_git_blob": source["source_skill_git_blob"],
            "source_openai_git_blob": source["source_openai_git_blob"],
            "source_helper_git_blob": source["source_helper_git_blob"],
            "benchmark_skill_sha256": decision_skill_sha256(),
            "benchmark_interface_sha256": decision_skill_interface_sha256(),
        },
        "jev_execution": {
            "tool_calls": len(receipts),
            "successful_calls": len(successful),
            "receipt_summary": _receipt_summary(receipt_path),
            "context_evidence": context_evidence,
        },
        "decision_record": decision_record,
        "observable_reasoning": {
            "reasoning_blocks_observed": reasoning_blocks,
            "reasoning_content_exported": False,
            "justification_source": "visible_final_assistant_decision_record",
        },
        "checks": checks,
        "claim_boundary": {
            "qualification_only": True,
            "tests_jev_activation": True,
            "tests_context_fixture_completeness": True,
            "tests_visible_decision_justification": True,
            "does_not_test_decision_correctness": True,
            "hidden_chain_of_thought_not_required_or_exported": True,
        },
    }
    validate_instance(record, QUAL_SCHEMA, artifact="current-model Jev qualification")
    result_path = output_root / "qualification.json"
    atomic_write_json(result_path, record)
    if not qualified:
        raise WorkflowError(
            "current-model Jev qualification failed; inspect qualification.json"
        )
    return {"path": str(result_path), **record}

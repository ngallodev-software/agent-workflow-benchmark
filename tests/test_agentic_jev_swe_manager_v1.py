from __future__ import annotations

import csv
import json
import sys
import types
from pathlib import Path

import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_v1 import (
    COHORT_SALT,
    STUDY_ID,
    SYSTEM_PROMPT,
    _arm_evidence,
    _build_solver,
    _sample_usage,
    inspect_real_task_jev_context,
    parse_manager_decision_record,
    select_fresh_manager_tasks,
)


def _write_csv(path: Path) -> None:
    rows = [
        {
            "question_id": f"manager-{index}",
            "variant": "swe_manager",
            "set": "diamond",
            "title": f"Manager task {index}",
            # These deliberately invalid/non-parseable gold-adjacent fields prove
            # selection does not consult them.
            "manager_data": "DO NOT PARSE",
            "proposals": "DO NOT READ FOR SELECTION",
        }
        for index in range(40)
    ]
    rows.append(
        {
            "question_id": "ic-1",
            "variant": "ic_swe",
            "set": "diamond",
            "title": "not eligible",
            "manager_data": "DO NOT PARSE",
            "proposals": "DO NOT READ",
        }
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_fresh_manager_selection_is_deterministic_and_excludes_prior(tmp_path: Path) -> None:
    path = tmp_path / "tasks.csv"
    _write_csv(path)
    excluded = ["manager-3", "manager-7", "manager-11"]
    first = select_fresh_manager_tasks(path, excluded_ids=excluded, count=30)
    second = select_fresh_manager_tasks(path, excluded_ids=excluded, count=30)
    assert first == second
    assert len(first) == 30
    assert not set(excluded).intersection(item["id"] for item in first)
    assert all(item["first_arm"] in {"control", "treatment"} for item in first)
    assert COHORT_SALT == "agentic-jev-swe-manager-v1"


def test_manager_visible_record_requires_bounded_observable_justification() -> None:
    value = {
        "selected_proposal_id": 42,
        "justification": (
            "Repository inspection shows proposal 42 preserves the existing boundary while "
            "keeping the change localized. The competing proposal spreads state coordination "
            "across callers, so the centralized invariant is the decisive evidence."
        ),
        "evidence_refs": ["task requirement", "src/example.ts"],
        "tradeoff": "Broader shared-path review surface versus duplicated coordination.",
        "semantic_evidence_reconciliation": (
            "No live semantic evidence was used; the decision rests on the inspected primary evidence."
        ),
        "remaining_uncertainty": "The migration path is not exercised by the supplied task.",
    }
    parsed = parse_manager_decision_record(json.dumps(value))
    assert parsed["selected_proposal_id"] == "42"

    value["justification"] = "too short"
    with pytest.raises(WorkflowError, match="80-2000"):
        parse_manager_decision_record(json.dumps(value))


def test_system_prompt_preserves_official_output_and_visible_evidence() -> None:
    assert "/app/expensify/manager_decisions.json" in SYSTEM_PROMPT
    assert "private chain-of-thought" in SYSTEM_PROMPT
    assert "semantic_evidence_reconciliation" in SYSTEM_PROMPT


def test_real_task_context_check_requires_requirement_proposals_and_choice() -> None:
    prompt = """<title>Cache invalidation regression</title>
<description>The shared cache helper now invalidates stale keys after a mutation and must preserve compatibility.</description>
<proposals>
Proposal 10 centralizes invalidation in the shared helper.
Proposal 11 performs invalidation in each mutation caller.
</proposals>"""
    receipt = {
        "purpose": "Choose the best implementation proposal.",
        "state_sha256": "a" * 64,
        "questions_sha256": "b" * 64,
        "request_sha256": "c" * 64,
        "request": {
            "state": {
                "requirement": "Cache invalidation regression. The shared cache helper now invalidates stale keys after a mutation and must preserve compatibility.",
                "candidates": (
                    "Proposal 10 centralizes invalidation in the shared helper. "
                    "Proposal 11 performs invalidation in each mutation caller."
                ),
            },
            "questions": {
                "best_proposal": {
                    "type": "choice",
                    "instructions": "Choose the best proposal.",
                    "criteria": {"10": "central", "11": "local"},
                }
            },
        },
    }
    result = inspect_real_task_jev_context(receipt, prompt_text=prompt)
    assert result["complete"] is True
    assert all(result["checks"].values())

    receipt["request"]["state"]["selected_proposal_id"] = 10
    contaminated = inspect_real_task_jev_context(receipt, prompt_text=prompt)
    assert contaminated["complete"] is False
    assert contaminated["checks"]["agent_judgment_keys_absent"] is False



def test_phase7_solver_scopes_jev_receipts_to_effectiveness_study(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agent_workflow_benchmark.benchmarking import agentic_jev_swe_manager_v1 as module

    captured: dict[str, object] = {}

    class FakeBridgedToolsSpec:
        def __init__(self, **kwargs):
            captured["bridged_spec"] = kwargs

    def fake_codex_cli(**kwargs):
        captured["codex"] = kwargs
        return object()

    def fake_jev_bridged_tool(**kwargs):
        captured["jev"] = kwargs
        return object()

    inspect_ai_agent = types.ModuleType("inspect_ai.agent")
    inspect_ai_agent.BridgedToolsSpec = FakeBridgedToolsSpec
    inspect_swe = types.ModuleType("inspect_swe")
    inspect_swe.codex_cli = fake_codex_cli
    monkeypatch.setitem(sys.modules, "inspect_ai.agent", inspect_ai_agent)
    monkeypatch.setitem(sys.modules, "inspect_swe", inspect_swe)
    monkeypatch.setattr(module, "jev_bridged_tool", fake_jev_bridged_tool)

    solver = _build_solver(
        codex_version="0.159.1",
        treatment=True,
        receipt_path=tmp_path / "receipts.jsonl",
        jev_model=None,
    )

    assert solver is not None
    assert captured["jev"]["study_id"] == STUDY_ID


def test_sample_usage_preserves_nested_token_fields() -> None:
    class Usage:
        def model_dump(self):
            return {
                "input_tokens": 120,
                "output_tokens": 12,
                "total_tokens": 132,
            }

    sample = types.SimpleNamespace(model_usage={"gpt-6-luna": Usage()})
    assert _sample_usage(sample) == {
        "gpt-6-luna": {
            "input_tokens": 120,
            "output_tokens": 12,
            "total_tokens": 132,
        }
    }



def test_treatment_evidence_projects_jev_service_usage_without_raw_context(
    tmp_path: Path,
) -> None:
    prompt = """<title>Cache invalidation regression</title>
<description>The shared cache helper now invalidates stale keys after a mutation and must preserve compatibility.</description>
<proposals>
Proposal 10 centralizes invalidation in the shared helper.
Proposal 11 performs invalidation in each mutation caller.
</proposals>"""
    receipt = tmp_path / "jev-tool-receipts.jsonl"
    receipt.write_text(
        json.dumps(
            {
                "schema": "agent-workflow-benchmark/agentic-jev-tool-receipt/v1",
                "study_id": STUDY_ID,
                "status": "success",
                "model": "jev-default-v1",
                "request_sha256": "d" * 64,
                "duration_ms": 125.0,
                "primitive_counts": {"choice": 1, "noul": 0, "score": 0},
                "response": {
                    "usage": {
                        "input_tokens": 7,
                        "output_tokens": 3,
                        "provider_total_tokens": 10,
                    }
                },
                "purpose": "Choose the best implementation proposal.",
                "request": {
                    "state": {
                        "requirement": (
                            "Cache invalidation regression. The shared cache helper now "
                            "invalidates stale keys after a mutation and must preserve compatibility."
                        ),
                        "candidates": (
                            "Proposal 10 centralizes invalidation in the shared helper. "
                            "Proposal 11 performs invalidation in each mutation caller."
                        ),
                    },
                    "questions": {
                        "best_proposal": {
                            "type": "choice",
                            "instructions": "Choose the best proposal.",
                            "criteria": {"10": "central", "11": "local"},
                        }
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    sample = types.SimpleNamespace(
        error=None,
        scores=[],
        model_usage={},
        messages=[],
        total_time=1.2,
    )
    log = types.SimpleNamespace(samples=[sample], location="inspect-log.eval")
    evidence = _arm_evidence(
        arm="treatment",
        log=log,
        prompt_text=prompt,
        receipt_path=receipt,
    )

    jev = evidence["jev"]
    assert jev["service_token_records"] == 1
    assert jev["service_input_tokens"] == 7.0
    assert jev["service_output_tokens"] == 3.0
    assert jev["service_total_tokens"] == 10.0
    assert jev["service_duration_known_n"] == 1
    assert jev["service_duration_ms_total"] == 125.0
    assert jev["resolved_models"] == ["jev-default-v1"]

#!/usr/bin/env python3
"""Qualify Agentic-Jev request-builder v2 on one already-observed manager task."""
from __future__ import annotations

import argparse
import json
import os
import sys
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json

from agent_workflow_benchmark.benchmarking.agentic_jev_request_v2 import (
    execute_built_jev_request,
)
from agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_v2 import (
    POLICY_ID,
    POLICY_VERSION,
    QUALIFICATION_SAMPLE_ID,
    assess_manager_response,
    build_manager_jev_request,
    inspect_manager_built_request,
    load_manager_authoritative_context,
)

INSPECT_EVALS_COMMIT = "190dfa27bc2e9b3e966ea6e8a682626d55b513c0"
CSV_PATH = Path("src/inspect_evals/swe_lancer/data/all_swelancer_tasks.csv")
STUDY_ID = "agentic-jev-swe-manager-v2-request-qualification"


def _fixture_path() -> Path:
    resource = files("agent_workflow_benchmark").joinpath(
        "assets/agentic-jev-request-v2/qualification-18796-manager-0.json"
    )
    return Path(str(resource))


def _git_head(checkout: Path) -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorkflowError(
            f"cannot resolve Inspect Evals git identity: {checkout}"
        ) from exc


class _Choice:
    choice = "proposal_1"
    confidence = 0.78
    probabilities = {
        "proposal_0": 0.03,
        "proposal_1": 0.78,
        "proposal_2": 0.17,
        "insufficient_evidence": 0.02,
    }


class _Noul:
    noul = 0.86
    probabilities = {"false": 0.14, "true": 0.86}


class _Usage:
    def model_dump(self) -> dict[str, int]:
        return {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        }


class _QualificationClient:
    """Offline provider double used only to verify the request/history contract."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, object, object]] = []

    def system_one(self, *, state: object, questions: object, model: object = None) -> Any:
        self.calls.append((state, questions, model))
        if not isinstance(questions, dict):
            raise AssertionError("questions must be an object")
        if set(questions) != {"best_proposal", "evidence_sufficient"}:
            raise AssertionError("qualification request must use the frozen batch")
        return SimpleNamespace(
            answers={
                "best_proposal": _Choice(),
                "evidence_sufficient": _Noul(),
            },
            request_id="qualification-offline",
            model="jev-qualification-double",
            usage=_Usage(),
        )


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise WorkflowError(f"expected JSON object: {path}")
    return value


def _single_jsonl(path: Path) -> dict[str, object]:
    values = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(values) != 1 or not isinstance(values[0], dict):
        raise WorkflowError(f"expected exactly one JSONL record: {path}")
    return values[0]


def run_qualification(
    *,
    inspect_evals_checkout: Path,
    output_root: Path,
    live: bool,
    model: str | None,
) -> dict[str, object]:
    checkout = Path(inspect_evals_checkout).resolve()
    observed_commit = _git_head(checkout)
    if observed_commit != INSPECT_EVALS_COMMIT:
        raise WorkflowError(
            "qualification requires pinned Inspect Evals commit "
            f"{INSPECT_EVALS_COMMIT}; observed {observed_commit}"
        )
    csv_path = checkout / CSV_PATH
    authoritative = load_manager_authoritative_context(
        csv_path,
        sample_id=QUALIFICATION_SAMPLE_ID,
    )
    fixture = _load_json(_fixture_path())
    if fixture.get("sample_id") != QUALIFICATION_SAMPLE_ID:
        raise WorkflowError("qualification fixture sample identity mismatch")
    agent_state = fixture.get("agent_state")
    if not isinstance(agent_state, dict):
        raise WorkflowError("qualification fixture has no agent_state")

    output_root = Path(output_root).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise WorkflowError(
            "qualification output root is not empty; preserve prior evidence and use a fresh root"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    receipt_path = output_root / "jev-tool-receipts.jsonl"
    history_path = output_root / "jev-request-history-v2.jsonl"

    built = build_manager_jev_request(
        authoritative=authoritative,
        agent_state=agent_state,
        model=model,
    )
    completeness = inspect_manager_built_request(
        built,
        authoritative=authoritative,
    )
    if completeness.get("complete") is not True:
        raise WorkflowError("qualification request is not context-complete")

    client: Any | None = None
    if not live:
        client = _QualificationClient()
    elif not os.environ.get("TYPESAFE_API_KEY"):
        raise WorkflowError(
            "live qualification requires TYPESAFE_API_KEY on the host"
        )

    result = execute_built_jev_request(
        built,
        receipt_path=receipt_path,
        history_path=history_path,
        study_id=STUDY_ID,
        client=client,
    )
    assessment = assess_manager_response(result)
    receipt = _single_jsonl(receipt_path)
    history = _single_jsonl(history_path)

    provider_request = {
        "state": receipt["request"]["state"],
        "questions": receipt["request"]["questions"],
        "model": receipt.get("requested_model"),
    }
    checks = {
        "observed_task_reused": fixture.get("sample_id") == QUALIFICATION_SAMPLE_ID,
        "pinned_inspect_evals": observed_commit == INSPECT_EVALS_COMMIT,
        "context_complete": completeness.get("complete") is True,
        "one_provider_receipt": receipt.get("status") == "success",
        "one_request_history_record": history.get("status") == "success",
        "builder_hash_matches_result": (
            result.get("request_sha256") == built.get("request_sha256")
        ),
        "builder_hash_matches_provider_receipt": (
            receipt.get("request_sha256") == built.get("request_sha256")
        ),
        "history_hash_matches_builder": (
            history.get("request_sha256") == built.get("request_sha256")
        ),
        "history_request_matches_provider_dispatch": (
            history.get("request") == provider_request
        ),
        "history_agent_input_retained": (
            history.get("agent_input_sha256") == built.get("agent_input_sha256")
            and isinstance(history.get("agent_input"), dict)
        ),
        "proposal_ids_match_choice": bool(
            completeness.get("checks", {}).get("proposal_ids_match_choice")
        ),
        "no_silent_truncation": (
            built.get("privacy", {}).get("silent_truncation") is False
        ),
        "no_request_redactions": not built.get("privacy", {}).get("redacted_paths"),
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise WorkflowError(
            "request-builder qualification failed: " + ", ".join(failed)
        )

    report: dict[str, object] = {
        "schema": "agent-workflow-benchmark/agentic-jev-swe-manager-v2-request-qualification/v1",
        "study_id": STUDY_ID,
        "sample_id": QUALIFICATION_SAMPLE_ID,
        "live_provider": live,
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "inspect_evals_commit": observed_commit,
        "fixture": fixture.get("source_evidence"),
        "checks": checks,
        "completeness": completeness,
        "request": {
            "request_sha256": built.get("request_sha256"),
            "decision_sha256": built.get("decision_sha256"),
            "state_sha256": built.get("state_sha256"),
            "questions_sha256": built.get("questions_sha256"),
            "agent_input_sha256": built.get("agent_input_sha256"),
            "sizes": built.get("sizes"),
        },
        "response_assessment": assessment,
        "artifacts": {
            "provider_receipt": str(receipt_path),
            "request_history": str(history_path),
        },
    }
    atomic_write_json(output_root / "qualification-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-evals-checkout", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the configured TypeSafe/Jev service instead of the offline provider double.",
    )
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    try:
        report = run_qualification(
            inspect_evals_checkout=args.inspect_evals_checkout,
            output_root=args.output_root,
            live=args.live,
            model=args.model,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_class": type(exc).__name__,
                    "message": str(exc),
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

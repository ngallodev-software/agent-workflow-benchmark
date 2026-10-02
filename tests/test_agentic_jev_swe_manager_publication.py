from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_comparative_eval import (
    build_paired_decision_report,
    make_paired_decision_trial,
)

from agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_publication import (
    prepare_swe_manager_publication,
)
from agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_v1 import (
    STUDY_ID,
    STUDY_VERSION,
    TARGET_TASKS,
)


SOURCE = {
    "task": "inspect_evals/swe_lancer",
    "task_variant": "swe_manager",
    "inspect_evals_commit": "1" * 40,
    "eval_version": "1-B",
    "scorer": "inspect_evals.swe_lancer.scorers.swe_lancer_scorer",
    "scorer_source_sha256": "a" * 64,
    "cohort_sha256": "b" * 64,
}
RUNTIME_COMMON = {
    "model": "openai-api/codex-lb/gpt-6-luna",
    "reasoning_effort": "high",
    "skill_commit": "d0ac1ef45d1b79b18b2905872c62cb9e68d961c7",
    "skill_sha256": "c" * 64,
    "codex_version": "0.159.1",
    "requested_jev_model": None,
    "benchmark_source": {
        "repository": "ngallodev-software/agent-workflow-benchmark",
        "commit": "d" * 40,
        "runner_sha256": "e" * 64,
        "host_bridge_sha256": "f" * 64,
    },
    "package_versions": {
        "agent-workflow-benchmark": "0.6.7",
        "agent-workflow-comparative-eval": "0.3.4",
        "agent-workflow": "0.12.0",
        "inspect-ai": "0.3.268",
        "inspect-swe": "0.2.71",
        "inspect-evals": "0.23.0",
        "typesafe-sdk": "0.6.0",
    },
    "dependency_code_sha256": {
        "agent_workflow.errors": "1" * 64,
        "agent_workflow.util": "2" * 64,
        "agent_workflow_comparative_eval.paired_decisions": "3" * 64,
    },
}


def _decision(selected: str, *, semantic: str) -> dict[str, object]:
    return {
        "selected_proposal_id": selected,
        "justification": (
            "The selected proposal best preserves the inspected implementation boundary "
            "while satisfying the task requirement and the deterministic repository evidence."
        ),
        "evidence_refs": ["task requirement", "src/example.ts"],
        "tradeoff": "Localized change surface versus centralized invariant ownership.",
        "semantic_evidence_reconciliation": semantic,
        "remaining_uncertainty": "Unexercised integration behavior remains a bounded uncertainty.",
    }


def _trial(index: int) -> dict[str, object]:
    control_score = 1 if index % 3 else 0
    treatment_score = 1 if index % 4 else 0
    called = index % 2 == 0
    control_selected = f"proposal-{index % 3}"
    treatment_selected = (
        control_selected if index % 5 else f"proposal-{(index + 1) % 3}"
    )
    control = {
        "status": "success",
        "official_score": control_score,
        "selected_proposal_id": control_selected,
        "decision_record": _decision(
            control_selected,
            semantic="No live semantic evidence was available in the control arm.",
        ),
        "usage": {
            "gpt-6-luna": {
                "input_tokens": 100 + index,
                "output_tokens": 20,
                "total_tokens": 120 + index,
            }
        },
        "duration_seconds": 10.0 + index,
        "error_class": None,
    }
    treatment = {
        "status": "success",
        "official_score": treatment_score,
        "selected_proposal_id": treatment_selected,
        "decision_record": _decision(
            treatment_selected,
            semantic=(
                "Live semantic evidence was advisory and was reconciled against "
                "the primary repository evidence."
                if called
                else "No live semantic evidence was used; primary evidence was decisive."
            ),
        ),
        "usage": {
            "gpt-6-luna": {
                "input_tokens": 110 + index,
                "output_tokens": 22,
                "total_tokens": 132 + index,
            }
        },
        "duration_seconds": 11.0 + index,
        "error_class": None,
        "jev": {
            "tool_calls": 1 if called else 0,
            "successful_calls": 1 if called else 0,
            "context_complete": True if called else None,
            "context_known_calls": 1 if called else 0,
            "context_complete_calls": 1 if called else 0,
            "resolved_models": ["jev-default-v1"] if called else [],
            "request_hashes": ["4" * 64] if called else [],
            "service_token_records": 1 if called else 0,
            "service_input_tokens": 7 if called else 0,
            "service_output_tokens": 3 if called else 0,
            "service_total_tokens": 10 if called else 0,
            "service_duration_known_n": 1 if called else 0,
            "service_duration_ms_total": 125 if called else 0,
        },
    }
    return make_paired_decision_trial(
        study_id=STUDY_ID,
        sample_id=f"manager-{index:02d}",
        repetition=0,
        source=SOURCE,
        runtime=RUNTIME_COMMON,
        control=control,
        treatment=treatment,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_run(tmp_path: Path) -> tuple[Path, list[dict[str, object]]]:
    run_root = tmp_path / "private-run"
    run_root.mkdir()
    start = run_root / "run-start.json"
    _write_json(start, {"schema": "private-start", "cohort": SOURCE["cohort_sha256"]})

    trials = [_trial(index) for index in range(TARGET_TASKS)]
    samples = []
    for index, trial in enumerate(trials):
        sample_id = str(trial["sample_id"])
        sample_root = run_root / "samples" / sample_id
        _write_json(sample_root / "paired-trial.json", trial)
        control_log = sample_root / "control" / "inspect-logs" / "sample.eval"
        treatment_log = sample_root / "treatment" / "inspect-logs" / "sample.eval"
        control_log.parent.mkdir(parents=True, exist_ok=True)
        treatment_log.parent.mkdir(parents=True, exist_ok=True)
        control_log.write_text("private control inspect evidence\n", encoding="utf-8")
        treatment_log.write_text("private treatment inspect evidence\n", encoding="utf-8")
        if index % 2 == 0:
            receipt = sample_root / "treatment" / "jev-tool-receipts.jsonl"
            receipt.write_text(
                json.dumps(
                    {
                        "request": {"state": {"private": "context"}},
                        "status": "success",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        samples.append(
            {
                "sample_id": sample_id,
                "ordinal": index,
                "first_arm": "control" if index % 2 == 0 else "treatment",
                "trial_path": str(sample_root / "paired-trial.json"),
                "control_inspect_log": str(control_log),
                "treatment_inspect_log": str(treatment_log),
                "control_decision_record_error": None,
                "treatment_decision_record_error": None,
                "control_api_key_absent": True,
                "treatment_api_key_absent": True,
            }
        )

    report = build_paired_decision_report(
        trials,
        study_id=STUDY_ID,
        study_version=STUDY_VERSION,
        minimum_interval_n=10,
    )
    run = {
        "schema": "agent-workflow-benchmark/agentic-jev-swe-manager-run/v1",
        "study_id": STUDY_ID,
        "study_version": STUDY_VERSION,
        "created_at": "2026-10-02T00:00:00+00:00",
        "cohort": {
            "path": str(tmp_path / "private" / "cohort.json"),
            "sha256": SOURCE["cohort_sha256"],
            "samples": TARGET_TASKS,
        },
        "runtime": {
            **RUNTIME_COMMON,
            "codex_cli": {
                "policy": "latest-at-cohort-start",
                "requested": "latest",
                "resolved": "0.159.1",
                "platform": "linux-x64",
                "cached_path": "/home/private/.cache/codex",
            },
            "model_args": {"responses_api": True},
            "jev_model": None,
        },
        "start_manifest": {
            "path": str(start),
            "sha256": _sha256(start),
        },
        "execution": {
            "paired_samples_expected": TARGET_TASKS,
            "paired_samples_observed": TARGET_TASKS,
            "official_scoring_enabled": True,
            "outcome_read_after_both_arms": True,
            "epochs": 1,
            "samples": samples,
        },
        "report": report,
        "evidence_policy": {
            "inspect_logs_are_canonical_execution_evidence": True,
            "official_swe_lancer_score_is_canonical_correctness": True,
            "hidden_chain_of_thought_exported": False,
            "raw_jev_context_public": False,
            "raw_provider_http_public": False,
            "credentials_public": False,
        },
    }
    _write_json(run_root / "run-manifest.json", run)
    return run_root, trials


def test_publication_is_allowlisted_reproducible_and_path_safe(tmp_path: Path) -> None:
    run_root, _ = _build_run(tmp_path)
    destination = tmp_path / "public"
    result = prepare_swe_manager_publication(
        run_root=run_root,
        destination=destination,
    )

    expected_files = {
        "README.md",
        "publication.json",
        "metrics/paired-report.json",
        "evidence/paired-trials.jsonl",
        "evidence/private-artifact-hashes.json",
        "MANIFEST.sha256",
    }
    actual_files = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert actual_files == expected_files
    assert result["publication"]["paired_n"] == TARGET_TASKS
    assert result["publication"]["cohort_sha256"] == SOURCE["cohort_sha256"]
    assert result["publication"]["runtime"]["codex_cli"] == {
        "policy": "latest-at-cohort-start",
        "requested": "latest",
        "resolved": "0.159.1",
        "platform": "linux-x64",
    }
    assert result["publication"]["runtime"]["first_arm_counts"] == {
        "control": 15,
        "treatment": 15,
    }

    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in destination.rglob("*")
        if path.is_file()
    )
    assert str(run_root.resolve()) not in public_text
    assert "/home/private/" not in public_text
    assert '"private":"context"' not in public_text
    assert "private control inspect evidence" not in public_text

    private_hashes = json.loads(
        (destination / "evidence" / "private-artifact-hashes.json").read_text()
    )
    assert private_hashes["raw_private_artifacts_published"] is False
    assert len(private_hashes["samples"]) == TARGET_TASKS
    assert private_hashes["samples"][0]["treatment_jev_receipts_sha256"]

    manifest_entries = {
        line.split("  ", 1)[1]
        for line in (destination / "MANIFEST.sha256").read_text().splitlines()
        if line
    }
    assert manifest_entries == expected_files - {"MANIFEST.sha256"}


def test_publication_rejects_tampered_stored_report(tmp_path: Path) -> None:
    run_root, _ = _build_run(tmp_path)
    run_path = run_root / "run-manifest.json"
    run = json.loads(run_path.read_text())
    run["report"]["primary"]["treatment_minus_control_accuracy"] = 0.999
    _write_json(run_path, run)

    with pytest.raises(WorkflowError, match="does not reproduce exactly"):
        prepare_swe_manager_publication(
            run_root=run_root,
            destination=tmp_path / "public",
        )


def test_publication_rejects_incomplete_cohort(tmp_path: Path) -> None:
    run_root, _ = _build_run(tmp_path)
    run_path = run_root / "run-manifest.json"
    run = json.loads(run_path.read_text())
    removed = run["execution"]["samples"].pop()
    run["execution"]["paired_samples_expected"] = TARGET_TASKS - 1
    run["execution"]["paired_samples_observed"] = TARGET_TASKS - 1
    run["report"] = build_paired_decision_report(
        [
            json.loads(
                (
                    run_root
                    / "samples"
                    / item["sample_id"]
                    / "paired-trial.json"
                ).read_text()
            )
            for item in run["execution"]["samples"]
        ],
        study_id=STUDY_ID,
        study_version=STUDY_VERSION,
        minimum_interval_n=10,
    )
    _write_json(run_path, run)

    with pytest.raises(WorkflowError, match="complete preregistered 30-pair cohort"):
        prepare_swe_manager_publication(
            run_root=run_root,
            destination=tmp_path / "public",
        )
    assert removed["sample_id"]


def test_publication_secret_scan_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root, _ = _build_run(tmp_path)
    secret = "ts-secret-publication-test"
    monkeypatch.setenv("TYPESAFE_API_KEY", secret)
    trial_path = run_root / "samples" / "manager-00" / "paired-trial.json"
    trial = json.loads(trial_path.read_text())
    trial["control"]["decision_record"]["justification"] += " " + secret
    _write_json(trial_path, trial)

    with pytest.raises(WorkflowError, match="contains API key value"):
        prepare_swe_manager_publication(
            run_root=run_root,
            destination=tmp_path / "public",
        )

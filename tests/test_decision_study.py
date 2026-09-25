from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent_workflow.config import defaults
from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking import decision_study


def _corpus() -> dict:
    case = {
        "schema": "agent-workflow-comparative-eval/decision-study-case/v1",
        "case_id": "case-001",
        "dataset_version": "routing-study-smoke-v1.0.0",
        "task": "Review the proposed parser change and identify material issues.",
        "metadata": {"task_type": "implementation", "risk": "normal"},
        "tags": ["smoke", "review"],
        "oracle_eligible": {
            "routing.task_class": True,
            "routing.interaction_required": True,
            "routing.semantic_risk": True,
        },
    }
    return {
        "schema": "agent-workflow-benchmark/decision-study-corpus/v1",
        "study_id": "routing-semantic-v1",
        "dataset_version": "routing-study-smoke-v1.0.0",
        "cases": [case],
    }


def _oracle() -> dict:
    return {
        "schema": "agent-workflow-benchmark/decision-study-oracle-bundle/v1",
        "study_id": "routing-semantic-v1",
        "dataset_version": "routing-study-smoke-v1.0.0",
        "oracle_version": "smoke-oracle-v1",
        "frozen": True,
        "records": [
            {
                "schema": "agent-workflow-comparative-eval/decision-study-oracle/v1",
                "case_id": "case-001",
                "dataset_version": "routing-study-smoke-v1.0.0",
                "labels": {
                    "routing.task_class": "review",
                    "routing.interaction_required": True,
                    "routing.semantic_risk": 2,
                },
                "provenance": {"kind": "test-fixture"},
                "adjudication": {"status": "frozen-test-fixture"},
                "frozen": True,
            }
        ],
    }


def _semantic(kind, *, value=None, probability=None, confidence=None, distribution=None):
    return {
        "status": "success",
        "semantic_type": kind,
        "confidence": confidence,
        "probability": probability,
        "distribution": distribution or {},
        "model": "jev-test",
        "question_set_version": "routing/v2",
        "projector_version": "routing-state/v2",
        "request_sha256": "a" * 64,
        "request_id": "req-case-001",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 3,
            "provider_total_tokens": 103,
            "token_evidence_complete": True,
            "cost_evidence_complete": False,
        },
        "source_refs": ["case-001"],
        "error_class": None,
    }


def _advice(*args, **kwargs):
    return {
        "decision_receipts": {
            "routing.task_class": {
                "control_result": "implementation",
                "evidence_result": "review",
                "policy_candidate_result": "review",
                "applied_result": "implementation",
                "fallback": {"used": False, "reason": None},
                "semantic": _semantic(
                    "choice",
                    confidence=0.9,
                    distribution={
                        "implementation": 0.03,
                        "diagnosis": 0.02,
                        "review": 0.9,
                        "documentation": 0.03,
                        "other": 0.02,
                    },
                ),
            },
            "routing.interaction_required": {
                "control_result": False,
                "evidence_result": 0.9,
                "policy_candidate_result": True,
                "applied_result": False,
                "fallback": {"used": False, "reason": None},
                "semantic": _semantic("noul", probability=0.9),
            },
            "routing.semantic_risk": {
                "control_result": 1,
                "evidence_result": 1.8,
                "policy_candidate_result": None,
                "applied_result": 1,
                "fallback": {"used": True, "reason": "semantic_uncertainty"},
                "semantic": _semantic(
                    "score",
                    confidence=0.7,
                    distribution={"0": 0.05, "1": 0.1, "2": 0.85},
                ),
            },
        },
        "decision_timing": {
            "control_seconds": 0.001,
            "candidate_policy_seconds": 0.001,
            "provider_elapsed_seconds": 0.2,
        },
    }


def test_decision_study_run_separates_oracle_and_deduplicates_request(tmp_path: Path, monkeypatch):
    corpus = tmp_path / "corpus.json"
    oracle = tmp_path / "oracle.json"
    corpus.write_text(json.dumps(_corpus()), encoding="utf-8")
    oracle.write_text(json.dumps(_oracle()), encoding="utf-8")

    monkeypatch.setattr(decision_study, "require_decision_runtime_ready", lambda settings: {"ready": True})
    monkeypatch.setattr(decision_study, "advise_routing_with_policy", _advice)
    settings = replace(defaults(tmp_path / "missing.toml"), decision_mode="comparative")

    run = tmp_path / "run"
    result = decision_study.run_decision_study(settings, corpus, run)
    assert result["oracle_seen_during_inference"] is False
    assert result["observations"] == 3
    assert result["provider_requests"] == 1
    assert result["exclusions"] == 0

    manifest = json.loads((run / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["oracle_seen_during_inference"] is False
    assert "oracle" not in manifest["files"]

    report = decision_study.report_decision_study(run, oracle)
    assert report["study_eligible"] is False  # one case is deliberately below n=100
    data = json.loads((run / "decision-study-report.json").read_text(encoding="utf-8"))
    assert set(data["seams"]) == {
        "routing.task-class/v1",
        "routing.interaction-required/v1",
        "routing.semantic-risk/v1",
    }
    assert data["request_efficiency"]["unique_requests"] == 1
    assert data["request_efficiency"]["usage"]["input_tokens"] == 100
    assert data["seams"]["routing.task-class/v1"]["correctness"]["candidate_accuracy"]["rate"] == 1.0


def test_validate_rejects_oracle_like_keys_in_inference_metadata(tmp_path: Path):
    value = _corpus()
    value["cases"][0]["metadata"]["oracle"] = {"routing.task_class": "review"}
    path = tmp_path / "leaky.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(WorkflowError, match="oracle-like key"):
        decision_study.validate_decision_study(path)


def test_validate_accepts_separate_complete_frozen_oracle(tmp_path: Path):
    corpus = tmp_path / "corpus.json"
    oracle = tmp_path / "oracle.json"
    corpus.write_text(json.dumps(_corpus()), encoding="utf-8")
    oracle.write_text(json.dumps(_oracle()), encoding="utf-8")
    result = decision_study.validate_decision_study(corpus, oracle_path=oracle)
    assert result["valid"] is True
    assert result["oracle"]["frozen"] is True
    assert result["oracle"]["records"] == 1

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
        "schema": "agent-workflow-comparative-eval/decision-study-corpus/v1",
        "study_id": "routing-semantic-v1",
        "dataset_version": "routing-study-smoke-v1.0.0",
        "cases": [case],
    }


def _oracle() -> dict:
    return {
        "schema": "agent-workflow-comparative-eval/decision-study-oracle-bundle/v1",
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


def test_exports_packaged_corpus_and_blinded_oracle_view(tmp_path: Path):
    corpus_path = tmp_path / "corpus.json"
    view_path = tmp_path / "oracle-view.json"

    corpus_result = decision_study.export_decision_study_corpus(corpus_path)
    assert corpus_result["cases"] == 120
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    assert corpus["schema"] == "agent-workflow-comparative-eval/decision-study-corpus/v1"

    view_result = decision_study.export_oracle_authoring_view(view_path)
    assert view_result["cases"] == 120
    assert view_result["construction_tags_included"] is False
    view = json.loads(view_path.read_text(encoding="utf-8"))
    assert view["schema"] == "agent-workflow-comparative-eval/oracle-authoring-view/v1"
    assert all("tags" not in case for case in view["cases"])
    assert view["blinding"] == {
        "construction_tags_included": False,
        "control_outputs_included": False,
        "candidate_outputs_included": False,
    }


def test_explicit_unresolved_oracle_conflict_validates_and_reports_distinct_reason(
    tmp_path: Path,
    monkeypatch,
):
    corpus_value = _corpus()
    oracle_value = _oracle()
    oracle_value["records"][0]["labels"].pop("routing.semantic_risk")
    oracle_value["records"][0]["adjudication"] = {
        "routing.task_class": {"status": "resolved", "method": "a_b_agreement"},
        "routing.interaction_required": {"status": "resolved", "method": "a_b_agreement"},
        "routing.semantic_risk": {
            "status": "oracle_conflict_unresolved",
            "method": "recorded_discussion",
        },
    }

    corpus = tmp_path / "corpus.json"
    oracle = tmp_path / "oracle.json"
    corpus.write_text(json.dumps(corpus_value), encoding="utf-8")
    oracle.write_text(json.dumps(oracle_value), encoding="utf-8")

    validated = decision_study.validate_decision_study(corpus, oracle_path=oracle)
    assert validated["valid"] is True
    assert validated["oracle"]["unresolved_conflicts"] == 1

    monkeypatch.setattr(
        decision_study,
        "require_decision_runtime_ready",
        lambda settings: {"ready": True},
    )
    monkeypatch.setattr(decision_study, "advise_routing_with_policy", _advice)
    settings = replace(defaults(tmp_path / "missing.toml"), decision_mode="comparative")

    run = tmp_path / "run"
    decision_study.run_decision_study(settings, corpus, run)
    decision_study.report_decision_study(run, oracle)
    report = json.loads((run / "decision-study-report.json").read_text(encoding="utf-8"))
    assert report["exclusions"]["reason_counts"]["oracle_conflict_unresolved"] == 1
    assert report["seams"]["routing.semantic-risk/v1"]["counts"]["oracle_eligible"] == 0


def test_report_surfaces_probability_normalization_without_rerunning_inference(
    tmp_path: Path,
    monkeypatch,
) -> None:
    corpus = tmp_path / "corpus.json"
    oracle = tmp_path / "oracle.json"
    corpus.write_text(json.dumps(_corpus()), encoding="utf-8")
    oracle.write_text(json.dumps(_oracle()), encoding="utf-8")

    def subnormalized_advice(*args, **kwargs):
        value = _advice(*args, **kwargs)
        value["decision_receipts"]["routing.task_class"]["semantic"]["distribution"] = {
            "implementation": 0.03,
            "diagnosis": 0.02,
            "review": 0.89,
            "documentation": 0.03,
            "other": 0.02,
        }
        return value

    monkeypatch.setattr(
        decision_study,
        "require_decision_runtime_ready",
        lambda settings: {"ready": True},
    )
    monkeypatch.setattr(
        decision_study,
        "advise_routing_with_policy",
        subnormalized_advice,
    )
    settings = replace(
        defaults(tmp_path / "missing.toml"),
        decision_mode="comparative",
    )

    run = tmp_path / "run"
    decision_study.run_decision_study(settings, corpus, run)
    decision_study.report_decision_study(run, oracle)

    report = json.loads(
        (run / "decision-study-report.json").read_text(encoding="utf-8")
    )
    normalization = report["seams"]["routing.task-class/v1"]["calibration"][
        "probability_normalization"
    ]
    assert normalization["applied"] is True
    assert normalization["normalized_vectors"] == 1
    assert normalization["total_vectors"] == 1
    assert normalization["max_absolute_mass_deviation"] == pytest.approx(0.01)

    markdown = (run / "decision-study-report.md").read_text(encoding="utf-8")
    assert "normalized 1/1" in markdown
    assert "persisted raw evidence is unchanged" in markdown


def test_publication_redacts_private_oracle_adjudication_and_records_privacy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    corpus = tmp_path / "corpus.json"
    oracle = tmp_path / "oracle.json"
    corpus.write_text(json.dumps(_corpus()), encoding="utf-8")

    oracle_value = _oracle()
    record = oracle_value["records"][0]
    record["provenance"] = {
        "protocol_version": "routing-semantic-oracle-v1.0.0",
        "authoring_view_sha256": "a" * 64,
        "adjudicators": {"a": "codex-a", "b": "codex-b", "c": "codex-c"},
        "pass_sha256": {"a": "b" * 64, "b": "c" * 64, "c": "d" * 64},
        "pass_completed_at": {
            "a": "2026-09-26T00:00:00Z",
            "b": "2026-09-26T00:00:01Z",
            "c": "2026-09-26T00:00:02Z",
        },
        "resolutions_sha256": "e" * 64,
        "frozen_at": "2026-09-26T00:00:03Z",
    }
    record["adjudication"] = {
        "routing.task_class": {
            "status": "resolved",
            "method": "a_b_agreement",
            "a": "review",
            "b": "review",
        },
        "routing.interaction_required": {
            "status": "resolved",
            "method": "two_of_three_majority",
            "a": False,
            "b": True,
            "c": True,
        },
        "routing.semantic_risk": {
            "status": "resolved",
            "method": "recorded_discussion",
            "a": 0,
            "b": 1,
            "c": 2,
            "rationale": "private human resolution rationale",
            "participants": ["Private Reviewer"],
        },
    }
    oracle.write_text(json.dumps(oracle_value), encoding="utf-8")

    monkeypatch.setattr(
        decision_study,
        "require_decision_runtime_ready",
        lambda settings: {"ready": True},
    )
    monkeypatch.setattr(
        decision_study,
        "advise_routing_with_policy",
        _advice,
    )
    settings = replace(
        defaults(tmp_path / "missing.toml"),
        decision_mode="comparative",
    )

    run = tmp_path / "run"
    decision_study.run_decision_study(settings, corpus, run)
    destination = tmp_path / "public"
    result = decision_study.prepare_decision_study_publication(
        run,
        oracle,
        destination,
    )
    assert result["study_eligible"] is False

    published_oracle = json.loads(
        (destination / "datasets/oracle.json").read_text(encoding="utf-8")
    )
    published_record = published_oracle["records"][0]
    assert published_record["labels"] == record["labels"]
    assert published_record["provenance"] == {
        "protocol_version": "routing-semantic-oracle-v1.0.0",
        "authoring_view_sha256": "a" * 64,
        "frozen_at": "2026-09-26T00:00:03Z",
        "public_projection": (
            "labels plus resolution status/method only; adjudicator identities, "
            "individual votes, pass hashes, discussion rationale, and participants removed"
        ),
    }
    assert published_record["adjudication"] == {
        "routing.task_class": {
            "status": "resolved",
            "method": "a_b_agreement",
        },
        "routing.interaction_required": {
            "status": "resolved",
            "method": "two_of_three_majority",
        },
        "routing.semantic_risk": {
            "status": "resolved",
            "method": "recorded_discussion",
        },
    }

    encoded = "\n".join(
        path.read_text(encoding="utf-8")
        for path in destination.rglob("*")
        if path.is_file()
    )
    assert "Private Reviewer" not in encoded
    assert "private human resolution rationale" not in encoded
    assert '"codex-a"' not in encoded

    publication = json.loads(
        (destination / "publication.json").read_text(encoding="utf-8")
    )
    assert publication["privacy"]["oracle_projection"] == (
        "public-labels-resolution-method/v1"
    )
    assert publication["privacy"]["reasoning_summaries_included"] is False
    assert publication["privacy"]["private_adjudicator_votes_included"] is False
    assert publication["privacy"]["human_resolution_rationale_included"] is False
    assert publication["privacy"]["human_participant_identity_included"] is False
    assert publication["privacy"]["checks"]["oracle_public_projection"] is True

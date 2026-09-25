from __future__ import annotations

import hashlib
import json
from pathlib import Path

import agent_workflow_comparative_eval as comparative
import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.oracle_adjudication import (
    ADJUDICATION_PASS_SCHEMA,
    FREEZE_MANIFEST_SCHEMA,
    RESOLUTIONS_SCHEMA,
    export_oracle_dispute_view,
    freeze_oracle_bundle,
    validate_adjudication_pass,
)


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _authoring_view(tmp_path: Path) -> tuple[Path, dict]:
    corpus = comparative.load_study_corpus("routing-semantic-v1")
    view = comparative.oracle_authoring_view(corpus)
    path = tmp_path / "oracle-authoring-view.json"
    _write_json(path, view)
    return path, view


def _base_labels() -> dict:
    return {
        "routing.task_class": "implementation",
        "routing.interaction_required": False,
        "routing.semantic_risk": 1,
    }


def _pass(
    view_path: Path,
    view: dict,
    path: Path,
    adjudicator_id: str,
    *,
    overrides: dict[tuple[str, str], object] | None = None,
    disputed: dict[str, set[str]] | None = None,
) -> Path:
    overrides = overrides or {}
    records = []
    for case in view["cases"]:
        case_id = case["case_id"]
        if disputed is None:
            decision_ids = [
                decision_id
                for decision_id, eligible in case["oracle_eligible"].items()
                if eligible is True
            ]
        else:
            if case_id not in disputed:
                continue
            decision_ids = sorted(disputed[case_id])
        labels = {}
        defaults = _base_labels()
        for decision_id in decision_ids:
            labels[decision_id] = overrides.get(
                (case_id, decision_id), defaults[decision_id]
            )
        records.append({"case_id": case_id, "labels": labels})
    value = {
        "schema": ADJUDICATION_PASS_SCHEMA,
        "study_id": view["study_id"],
        "dataset_version": view["dataset_version"],
        "protocol_version": view["oracle_policy"]["protocol_version"],
        "input_view_sha256": _sha(view_path),
        "adjudicator_id": adjudicator_id,
        "completed_at": "2026-09-25T08:00:00+00:00",
        "attestation": {
            "independent": True,
            "treatment_outputs_seen": False,
            "other_adjudicator_labels_seen": False,
        },
        "records": records,
    }
    _write_json(path, value)
    return path


def test_validate_adjudication_pass_requires_complete_exact_view(tmp_path: Path):
    view_path, view = _authoring_view(tmp_path)
    pass_a = _pass(view_path, view, tmp_path / "a.json", "A")
    result = validate_adjudication_pass(view_path, pass_a)
    assert result["valid"] is True
    assert result["cases"] == 120
    assert result["labels"] == 360
    assert result["input_view_sha256"] == _sha(view_path)


def test_dispute_view_contains_only_disputed_seams_and_no_a_b_labels(tmp_path: Path):
    view_path, view = _authoring_view(tmp_path)
    first = view["cases"][0]["case_id"]
    pass_a = _pass(view_path, view, tmp_path / "a.json", "A")
    pass_b = _pass(
        view_path,
        view,
        tmp_path / "b.json",
        "B",
        overrides={(first, "routing.task_class"): "review"},
    )
    dispute_path = tmp_path / "c-view.json"
    result = export_oracle_dispute_view(view_path, pass_a, pass_b, dispute_path)
    assert result["requires_c"] is True
    assert result["disputed_cases"] == 1
    assert result["disputed_seams"] == 1
    dispute = json.loads(dispute_path.read_text(encoding="utf-8"))
    assert dispute["cases"][0]["case_id"] == first
    assert dispute["cases"][0]["disputed_decision_ids"] == ["routing.task_class"]
    assert "labels" not in dispute["cases"][0]
    assert dispute["blinding"]["a_b_labels_included"] is False


def test_freeze_oracle_direct_agreement_needs_no_c(tmp_path: Path):
    view_path, view = _authoring_view(tmp_path)
    pass_a = _pass(view_path, view, tmp_path / "a.json", "A")
    pass_b = _pass(view_path, view, tmp_path / "b.json", "B")
    oracle_path = tmp_path / "oracle.json"
    result = freeze_oracle_bundle(
        view_path,
        pass_a,
        pass_b,
        oracle_path,
        oracle_version="routing-semantic-oracle-v1.0.0",
    )
    assert result["frozen"] is True
    assert result["records"] == 120
    assert result["labels"] == 360
    assert result["direct_agreements"] == 360
    assert result["unresolved"] == 0
    manifest_path = oracle_path.with_name(oracle_path.name + ".manifest.json")
    assert result["manifest"] == str(manifest_path)
    freeze_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert freeze_manifest["schema"] == FREEZE_MANIFEST_SCHEMA
    assert freeze_manifest["oracle_sha256"] == result["sha256"]
    assert freeze_manifest["authoring_view_sha256"] == _sha(view_path)
    assert freeze_manifest["adjudication"]["a"]["input_view_sha256"] == _sha(view_path)
    assert freeze_manifest["adjudication"]["b"]["input_view_sha256"] == _sha(view_path)
    assert freeze_manifest["counts"]["direct_agreements"] == 360
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    assert oracle["frozen"] is True
    comparative.validate_decision_study_oracle_bundle(
        oracle,
        expected_study_id=view["study_id"],
        expected_dataset_version=view["dataset_version"],
    )


def test_freeze_requires_c_for_a_b_disagreement_and_accepts_majority(tmp_path: Path):
    view_path, view = _authoring_view(tmp_path)
    first = view["cases"][0]["case_id"]
    pass_a = _pass(view_path, view, tmp_path / "a.json", "A")
    pass_b = _pass(
        view_path,
        view,
        tmp_path / "b.json",
        "B",
        overrides={(first, "routing.task_class"): "review"},
    )
    with pytest.raises(WorkflowError, match="require both the blinded C dispute view"):
        freeze_oracle_bundle(
            view_path,
            pass_a,
            pass_b,
            tmp_path / "blocked.json",
            oracle_version="routing-semantic-oracle-v1.0.0",
        )

    c_view_path = tmp_path / "c-view.json"
    export_oracle_dispute_view(view_path, pass_a, pass_b, c_view_path)
    c_view = json.loads(c_view_path.read_text(encoding="utf-8"))
    disputed = {
        item["case_id"]: set(item["disputed_decision_ids"])
        for item in c_view["cases"]
    }
    pass_c = _pass(
        c_view_path,
        c_view,
        tmp_path / "c.json",
        "C",
        overrides={(first, "routing.task_class"): "review"},
        disputed=disputed,
    )
    result = freeze_oracle_bundle(
        view_path,
        pass_a,
        pass_b,
        tmp_path / "oracle.json",
        oracle_version="routing-semantic-oracle-v1.0.0",
        c_view_path=c_view_path,
        pass_c_path=pass_c,
    )
    assert result["majority_resolved"] == 1
    oracle = json.loads((tmp_path / "oracle.json").read_text(encoding="utf-8"))
    record = next(item for item in oracle["records"] if item["case_id"] == first)
    assert record["labels"]["routing.task_class"] == "review"
    assert record["adjudication"]["routing.task_class"]["method"] == "two_of_three_majority"
    assert record["provenance"]["c_dispute_view_sha256"] == _sha(c_view_path)
    assert set(record["provenance"]["pass_completed_at"]) == {"a", "b", "c"}
    freeze_manifest = json.loads(
        (tmp_path / "oracle.json.manifest.json").read_text(encoding="utf-8")
    )
    assert freeze_manifest["adjudication"]["c"]["input_view_sha256"] == _sha(c_view_path)


def test_three_way_conflict_requires_recorded_resolution_and_can_remain_unresolved(
    tmp_path: Path,
):
    view_path, view = _authoring_view(tmp_path)
    first = view["cases"][0]["case_id"]
    pass_a = _pass(
        view_path,
        view,
        tmp_path / "a.json",
        "A",
        overrides={(first, "routing.semantic_risk"): 0},
    )
    pass_b = _pass(
        view_path,
        view,
        tmp_path / "b.json",
        "B",
        overrides={(first, "routing.semantic_risk"): 1},
    )
    c_view_path = tmp_path / "c-view.json"
    export_oracle_dispute_view(view_path, pass_a, pass_b, c_view_path)
    c_view = json.loads(c_view_path.read_text(encoding="utf-8"))
    disputed = {
        item["case_id"]: set(item["disputed_decision_ids"])
        for item in c_view["cases"]
    }
    pass_c = _pass(
        c_view_path,
        c_view,
        tmp_path / "c.json",
        "C",
        overrides={(first, "routing.semantic_risk"): 2},
        disputed=disputed,
    )
    with pytest.raises(WorkflowError, match="three-way conflict requires recorded"):
        freeze_oracle_bundle(
            view_path,
            pass_a,
            pass_b,
            tmp_path / "blocked.json",
            oracle_version="routing-semantic-oracle-v1.0.0",
            c_view_path=c_view_path,
            pass_c_path=pass_c,
        )

    resolutions = {
        "schema": RESOLUTIONS_SCHEMA,
        "study_id": view["study_id"],
        "dataset_version": view["dataset_version"],
        "protocol_version": view["oracle_policy"]["protocol_version"],
        "authoring_view_sha256": _sha(view_path),
        "records": [
            {
                "case_id": first,
                "decision_id": "routing.semantic_risk",
                "status": "unresolved",
                "rationale": "Frozen rubric did not resolve the 0/1/2 split.",
                "participants": ["A", "B", "C"],
            }
        ],
    }
    resolutions_path = tmp_path / "resolutions.json"
    _write_json(resolutions_path, resolutions)
    result = freeze_oracle_bundle(
        view_path,
        pass_a,
        pass_b,
        tmp_path / "oracle.json",
        oracle_version="routing-semantic-oracle-v1.0.0",
        c_view_path=c_view_path,
        pass_c_path=pass_c,
        resolutions_path=resolutions_path,
    )
    assert result["unresolved"] == 1
    assert result["labels"] == 359
    oracle = json.loads((tmp_path / "oracle.json").read_text(encoding="utf-8"))
    record = next(item for item in oracle["records"] if item["case_id"] == first)
    assert "routing.semantic_risk" not in record["labels"]
    assert (
        record["adjudication"]["routing.semantic_risk"]["status"]
        == "oracle_conflict_unresolved"
    )
    freeze_manifest = json.loads(
        (tmp_path / "oracle.json.manifest.json").read_text(encoding="utf-8")
    )
    assert freeze_manifest["adjudication"]["resolutions_sha256"] == _sha(
        resolutions_path
    )
    assert freeze_manifest["counts"]["unresolved"] == 1

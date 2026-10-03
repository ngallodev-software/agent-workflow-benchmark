from __future__ import annotations

import csv
import hashlib
import json
from importlib import resources
from pathlib import Path

from agent_workflow_benchmark.benchmarking.agentic_jev_decision_v6 import (
    decision_skill_path,
    source_manifest,
)
from agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_v2_study import (
    COHORT_SALT,
    STUDY_ID,
    STUDY_VERSION,
    load_observed_manager_ids,
    parse_manager_decision_record,
    select_fresh_manager_tasks,
)
from agent_workflow_benchmark.benchmarking.agentic_jev_swe_manager_v2_publication import (
    PUBLICATION_SCHEMA,
)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    fields = ["question_id", "variant", "set", "title"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_observed_manager_registry_freezes_all_known_official_manager_exposure() -> None:
    registry = load_observed_manager_ids()
    ids = registry["ids"]
    assert registry["unique_ids"] == 36
    assert len(ids) == len(set(ids)) == 36

    # Earlier six-task trace audit.
    for sample_id in (
        "16946-manager-0",
        "17073-manager-0",
        "17387-manager-0",
        "18207-manager-0",
        "19232-manager-0",
        "27538-manager-0",
    ):
        assert sample_id in ids

    # Live qualification task is already contained in the completed v1 cohort.
    assert "18796-manager-0" in ids


def test_v2_selection_is_gold_blind_deterministic_and_uses_new_salt(tmp_path: Path) -> None:
    registry = load_observed_manager_ids()
    rows = [
        {
            "question_id": sample_id,
            "variant": "swe_manager",
            "set": "diamond",
            "title": f"Task {sample_id}",
        }
        for sample_id in [
            "18796-manager-0",  # excluded
            "fresh-a-manager-0",
            "fresh-b-manager-0",
            "fresh-c-manager-0",
            "fresh-d-manager-0",
        ]
    ]
    rows += [
        {
            "question_id": "not-manager",
            "variant": "swe_bench",
            "set": "diamond",
            "title": "wrong variant",
        },
        {
            "question_id": "wrong-split-manager-0",
            "variant": "swe_manager",
            "set": "other",
            "title": "wrong split",
        },
    ]
    csv_path = _write_csv(tmp_path / "tasks.csv", rows)

    first = select_fresh_manager_tasks(
        csv_path,
        excluded_ids=registry["ids"],
        count=3,
    )
    second = select_fresh_manager_tasks(
        csv_path,
        excluded_ids=registry["ids"],
        count=3,
    )
    assert first == second
    assert len(first) == 3
    assert all(item["id"].startswith("fresh-") for item in first)
    assert COHORT_SALT == STUDY_ID == "agentic-jev-swe-manager-v2"
    for item in first:
        expected = hashlib.sha256(
            f"{COHORT_SALT}:{item['id']}".encode()
        ).hexdigest()
        assert item["selection_digest"] == expected
        assert item["first_arm"] in {"control", "treatment"}


def test_visible_decision_record_normalizes_structured_evidence_refs() -> None:
    record = parse_manager_decision_record(
        json.dumps(
            {
                "selected_proposal_id": 2,
                "justification": (
                    "Repository inspection shows the proposal matches the observed "
                    "state boundary and preserves the required behavior."
                ),
                "evidence_refs": [
                    {
                        "source": "src/example.py:10-20",
                        "fact": "The existing helper owns the behavior.",
                    },
                    "requirement: preserve backwards compatibility",
                ],
                "tradeoff": (
                    "The selected proposal changes less shared behavior while still "
                    "covering the observed failure mode."
                ),
                "semantic_evidence_reconciliation": (
                    "Semantic evidence was treated as advisory and reconciled against "
                    "the cited repository facts before final selection."
                ),
                "remaining_uncertainty": None,
            }
        )
    )
    assert record["selected_proposal_id"] == "2"
    assert record["evidence_refs"] == [
        "src/example.py:10-20: The existing helper owns the behavior.",
        "requirement: preserve backwards compatibility",
    ]


def test_v6_skill_freezes_manager_checkpoint_contract() -> None:
    text = decision_skill_path().read_text(encoding="utf-8")
    assert "jev_manager_decision" in text
    assert "Do not recreate or summarize the" in text
    assert "official task title, description, or proposal text" in text
    assert "repository_evidence" in text
    assert "verification" in text
    assert "at most one revised semantic request" in text
    manifest = source_manifest()
    assert manifest["host_tool"] == "jev_manager_decision"
    assert manifest["authoritative_task_context_host_injected"] is True
    assert manifest["max_changed_revisions_documented"] == 1


def test_live_qualification_lock_is_pre_effectiveness_and_complete() -> None:
    path = Path(
        str(
            resources.files("agent_workflow_benchmark").joinpath(
                "assets/agentic-jev-request-v2/live-qualification-lock.json"
            )
        )
    )
    lock = json.loads(path.read_text(encoding="utf-8"))
    assert lock["sample_id"] == "18796-manager-0"
    assert lock["sample_is_previously_observed"] is True
    assert lock["effectiveness_case_consumed"] is False
    assert lock["all_completeness_checks_passed"] is True
    assert lock["no_redactions"] is True
    assert lock["no_silent_truncation"] is True
    assert lock["request_builder_version"] == "2.0.0"
    assert lock["policy_id"] == "swe-manager-choice-v2"


def test_v2_publication_and_study_identities_are_versioned() -> None:
    assert STUDY_VERSION == "2.0.0-preregistered"
    assert PUBLICATION_SCHEMA == (
        "agent-workflow-benchmark/agentic-jev-swe-manager-publication/v2"
    )

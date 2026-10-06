from __future__ import annotations

import copy

import pytest

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.agentic_jev_right_seam import (
    MANIFEST_SCHEMA,
    M0,
    M1,
    M2,
    M3,
    build_m0,
    build_m1,
    build_m2,
    build_m3,
    compose_m2,
    compose_m3,
    counterbalanced_ids,
    dispatch_sha256,
    reorder_mechanism_request,
    validate_replay_manifest,
)
from agent_workflow_benchmark.benchmarking.agentic_jev_request_v2 import sha256_json


def entry():
    return {
        "sample_id": "sample-1",
        "purpose": "bounded manager decision",
        "request": {
            "state": {
                "authoritative_task": {
                    "sample_id": "sample-1",
                    "title": "T",
                    "description": "D",
                    "proposals": {
                        "proposal_1": "first",
                        "proposal_2": "second",
                        "proposal_3": "third",
                    },
                },
                "repository_evidence": [{"source": "a", "fact": "b"}],
                "verification": {"ran": ["x"], "not_exercised": ["y"]},
            },
            "questions": {
                "best_proposal": {
                    "type": "choice",
                    "instructions": "old broad question",
                    "criteria": {
                        "proposal_1": "Official task proposal 1",
                        "proposal_2": "Official task proposal 2",
                        "proposal_3": "Official task proposal 3",
                        "insufficient_evidence": "not enough",
                    },
                },
                "evidence_sufficient": {
                    "type": "noul",
                    "instructions": "enough?",
                    "criteria": {"true": "yes", "false": "no"},
                },
            },
            "model": "pinned-model",
        },
    }


def test_manifest_recomputes_both_hash_identities_and_rejects_gold():
    item = entry()
    request = item["request"]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "entries": [{
            "sample_id": item["sample_id"],
            "request": request,
            "semantic_sha256": sha256_json(request),
            "dispatch_sha256": dispatch_sha256(request),
        }],
    }
    validated = validate_replay_manifest(manifest)
    assert validated["entries"][0]["dispatch_sha256"] == dispatch_sha256(request)

    leaked = copy.deepcopy(manifest)
    leaked["entries"][0]["correct_proposal"] = "proposal_2"
    with pytest.raises(WorkflowError, match="gold-bearing"):
        validate_replay_manifest(leaked)


def test_dispatch_hash_preserves_order_while_semantic_hash_is_canonical():
    a = {"x": 1, "y": 2}
    b = {"y": 2, "x": 1}
    assert sha256_json(a) == sha256_json(b)
    assert dispatch_sha256(a) != dispatch_sha256(b)


def test_m0_is_exact_and_m1_only_describes_existing_proposal_paths():
    item = entry()
    m0 = build_m0(item)
    assert m0["mechanism"] == M0
    assert m0["request"] == item["request"]
    assert m0["dispatch_body_sha256"] == dispatch_sha256(item["request"])

    m1 = build_m1(item)
    assert m1["mechanism"] == M1
    criteria = m1["request"]["questions"]["best_proposal"]["criteria"]
    assert "authoritative_task.proposals.proposal_2" in criteria["proposal_2"]
    assert "insufficient_evidence" in criteria


def test_m2_separates_selection_from_sufficiency_and_never_retries():
    built = build_m2(entry())
    assert built["mechanism"] == M2
    criteria = built["request"]["questions"]["best_proposal"]["criteria"]
    assert "insufficient_evidence" not in criteria

    low = compose_m2(selection="proposal_2", sufficiency=0.2, threshold=0.5)
    assert low["candidate"] == "proposal_2"
    assert low["workflow_action"] == "review_required"
    assert low["second_same_agent_jev_call"] is False

    high = compose_m2(selection="proposal_2", sufficiency=0.8, threshold=0.5)
    assert high["candidate"] == "proposal_2"
    assert high["workflow_action"] == "candidate_selection"


def test_m3_uses_parallel_common_scale_and_code_owned_ranking():
    built = build_m3(entry())
    assert built["mechanism"] == M3
    questions = built["request"]["questions"]
    assert set(questions) == {
        "support_for_proposal_1",
        "support_for_proposal_2",
        "support_for_proposal_3",
    }
    scales = [q["criteria"] for q in questions.values()]
    assert scales[0] == scales[1] == scales[2]

    ranked = compose_m3({"proposal_1": 2, "proposal_2": 4, "proposal_3": 3})
    assert ranked["candidate"] == "proposal_2"
    assert ranked["workflow_action"] == "candidate_selection"

    tied = compose_m3({"proposal_1": 4, "proposal_2": 3.9}, tie_epsilon=0.1)
    assert tied["workflow_action"] == "review_required"
    assert tied["second_same_agent_jev_call"] is False


def test_counterbalanced_order_is_deterministic_and_not_source_order():
    ids = ["proposal_1", "proposal_2", "proposal_3"]
    first = counterbalanced_ids(ids, mechanism=M2, sample_id="sample-1")
    second = counterbalanced_ids(ids, mechanism=M2, sample_id="sample-1")
    assert first == second
    assert first != ids
    assert sorted(first) == sorted(ids)


def test_order_variant_changes_only_dispatch_order():
    built = build_m2(entry())
    source = built["request"]
    order = ["proposal_3", "proposal_1", "proposal_2"]
    variant = reorder_mechanism_request(built, proposal_order=order)

    assert sha256_json(variant["request"]) == sha256_json(source)
    assert variant["semantic_content_sha256"] == built["semantic_content_sha256"]
    assert variant["dispatch_body_sha256"] != built["dispatch_body_sha256"]

    proposals = variant["request"]["state"]["authoritative_task"]["proposals"]
    criteria = variant["request"]["questions"]["best_proposal"]["criteria"]
    assert list(proposals) == order
    assert list(criteria) == order

    with pytest.raises(WorkflowError, match="every proposal exactly once"):
        reorder_mechanism_request(
            built,
            proposal_order=["proposal_1", "proposal_2"],
        )


def test_replay_uses_retained_resolved_model_when_source_model_is_null():
    item = entry()
    item["request"]["model"] = None
    item["recorded"] = {"resolved_model": "jev-1.13.0"}

    built = build_m2(item)
    assert built["request"]["model"] == "jev-1.13.0"

    m0 = build_m0(item)
    assert m0["request"]["model"] is None

#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

ds_require_executable "$PYTHON"
ds_verify_source_corpus
ds_require_file "$P1_SELECTION"
ds_require_file "$P1_CORPUS"
ds_require_file "$P1_RUN/run-manifest.json"
ds_require_file "$P1_RUN/observations.jsonl"
ds_require_file "$P1_RUN/provider-requests.jsonl"
ds_require_file "$P1_RUN/exclusions.jsonl"

"$PYTHON" -   "$SOURCE_CORPUS"   "$P1_SELECTION"   "$P1_CORPUS"   "$P1_RUN"   "$P1_VERIFICATION"   "$DS_EXPECTED_CORPUS_SHA256"   "${TYPESAFE_API_KEY:-}" <<'PY'
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

source_path=Path(sys.argv[1])
selection_path=Path(sys.argv[2])
smoke_path=Path(sys.argv[3])
run=Path(sys.argv[4])
verification_path=Path(sys.argv[5])
expected_sha=sys.argv[6]
secret=sys.argv[7]

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def jsonl(path):
    rows=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

source_sha=hashlib.sha256(source_path.read_bytes()).hexdigest()
assert source_sha == expected_sha
source=load(source_path)
selection=load(selection_path)
smoke=load(smoke_path)
manifest=load(run/"run-manifest.json")
observations=jsonl(run/"observations.jsonl")
requests=jsonl(run/"provider-requests.jsonl")
exclusions=jsonl(run/"exclusions.jsonl")

selected_ids=selection["selected_case_ids"]
assert selection["development_only"] is True
assert selection["source_corpus_sha256"] == source_sha
assert selection["sample_size"] == len(selected_ids)
assert len(selected_ids) < 100
assert [case["case_id"] for case in smoke["cases"]] == selected_ids
assert smoke["study_id"] == source["study_id"] == "routing-semantic-v1"
assert smoke["dataset_version"] == source["dataset_version"] == "routing-semantic-corpus-v1.0.0"

assert manifest["oracle_seen_during_inference"] is False
assert "oracle" not in manifest.get("files", {})
assert manifest["counts"]["cases"] == len(selected_ids)
assert manifest["counts"]["observations"] == len(observations)
assert manifest["counts"]["provider_requests"] == len(requests)
assert manifest["counts"]["exclusions"] == len(exclusions)
assert manifest["identity"]["question_set_version"] == "routing/v2"
assert manifest["identity"]["projector_version"] == "routing-state/v2"

expected_files={
    "corpus.json",
    "exclusions.jsonl",
    "observations.jsonl",
    "provider-requests.jsonl",
    "run-manifest.json",
    "study-spec.json",
}
actual_files={p.name for p in run.iterdir() if p.is_file()}
assert actual_files == expected_files, (actual_files, expected_files)

request_by_id={}
for req in requests:
    rid=req["request_id"]
    assert rid not in request_by_id
    request_by_id[rid]=req
    assert req["privacy"]["raw_content_stored"] is False
    assert req["privacy"]["secret_values_stored"] is False
    assert set(req["decisions"]) == {
        "routing.task_class",
        "routing.interaction_required",
        "routing.semantic_risk",
    }
    assert req["status"] in {"success","error","timeout"}
    assert isinstance(req.get("usage"), dict)

by_case=defaultdict(list)
successful_semantic_types=set()
for obs in observations:
    case_id=obs["input"]["case_id"]
    by_case[case_id].append(obs)
    assert obs["mode"] == "static"
    assert obs["identity"]["question_set_version"] == "routing/v2"
    assert obs["identity"]["projector_version"] == "routing-state/v2"
    assert obs["privacy"]["raw_content_stored"] is False
    assert obs["privacy"]["secret_values_stored"] is False
    assert obs["input"]["raw_input_persisted"] is False
    assert obs["control"]["usage"] == {}
    assert obs["candidate"]["usage"] == {}

    result=obs["candidate"]["result"]
    assert isinstance(result, dict)
    rid=result["request_id"]
    assert rid in request_by_id
    semantic_type=result["semantic_type"]
    if result["semantic_status"] == "success":
        successful_semantic_types.add(semantic_type)
        if semantic_type == "noul":
            assert isinstance(result.get("probability"), (int,float))
        elif semantic_type in {"choice","score"}:
            probabilities=result.get("probabilities")
            assert isinstance(probabilities, dict) and probabilities

expected_features={
    "routing.task-class/v1",
    "routing.interaction-required/v1",
    "routing.semantic-risk/v1",
}
for case_id, rows in by_case.items():
    assert len(rows) == 3, (case_id, len(rows))
    assert {row["feature_id"] for row in rows} == expected_features
    assert len({row["candidate"]["result"]["request_id"] for row in rows}) == 1

excluded_ids={row["case_id"] for row in exclusions}
assert set(by_case).isdisjoint(excluded_ids)
assert set(by_case) | excluded_ids == set(selected_ids)
assert len(requests) == len(by_case)
assert successful_semantic_types == {"choice","noul","score"}, successful_semantic_types

encoded_observations=(run/"observations.jsonl").read_text(encoding="utf-8")
for case in smoke["cases"]:
    assert case["task"] not in encoded_observations

if secret:
    needle=secret.encode()
    for path in run.iterdir():
        if path.is_file() and needle in path.read_bytes():
            raise AssertionError(f"TYPESAFE_API_KEY leaked into {path.name}")

verification={
    "format": "agent-workflow-benchmark/decision-study-p1-verification/v1",
    "status": "pass",
    "verified_at": datetime.now(timezone.utc).isoformat(),
    "study_id": "routing-semantic-v1",
    "dataset_version": "routing-semantic-corpus-v1.0.0",
    "development_only": True,
    "source_corpus_sha256": source_sha,
    "selected_case_ids": selected_ids,
    "counts": {
        "cases": len(selected_ids),
        "observed_cases": len(by_case),
        "observations": len(observations),
        "provider_requests": len(requests),
        "exclusions": len(exclusions),
    },
    "checks": {
        "one_request_per_observed_case": True,
        "three_observations_per_observed_case": True,
        "unique_request_ids": True,
        "semantic_probability_evidence_persisted": True,
        "failures_explicit": True,
        "oracle_absent_during_inference": True,
        "privacy_boundary_preserved": True,
        "request_level_usage_not_tripled": True,
        "question_set_routing_v2": True,
        "projector_routing_state_v2": True,
    },
}
tmp=verification_path.with_name(verification_path.name+".tmp")
tmp.write_text(json.dumps(verification, indent=2, sort_keys=True)+"\n", encoding="utf-8")
tmp.replace(verification_path)

print(json.dumps(verification["counts"], sort_keys=True))
print("P1 verification: PASS")
print(verification_path)
PY

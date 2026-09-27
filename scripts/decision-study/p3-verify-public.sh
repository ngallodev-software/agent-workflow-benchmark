#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

ds_require_executable "$PYTHON"
ds_require_file "$P3_PUBLIC/publication.json"
ds_require_file "$P3_PUBLIC/MANIFEST.sha256"
ds_require_file "$P3_PUBLIC/metrics/decision-study-report.json"
ds_require_file "$P3_PUBLIC/datasets/corpus.json"
ds_require_file "$P3_PUBLIC/datasets/oracle.json"
ds_require_file "$P3_PUBLIC/evidence/provider-requests.jsonl"
ds_require_file "$P3_PUBLIC/evidence/observations.jsonl"
ds_require_file "$P3_PUBLIC/evidence/exclusions.jsonl"
ds_require_file "$P3_PUBLIC/evidence/outcomes.jsonl"

"$PYTHON" - "$P3_PUBLIC" "$P3_VERIFICATION" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root=Path(sys.argv[1])
verification_path=Path(sys.argv[2])

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

expected_files={
    "MANIFEST.sha256",
    "README.md",
    "analysis/decision-study-report.md",
    "datasets/corpus.json",
    "datasets/oracle.json",
    "evidence/exclusions.jsonl",
    "evidence/observations.jsonl",
    "evidence/outcomes.jsonl",
    "evidence/provider-requests.jsonl",
    "evidence/run-manifest.json",
    "metrics/decision-study-report.json",
    "publication.json",
    "study-spec.json",
}
actual_files={
    p.relative_to(root).as_posix()
    for p in root.rglob("*")
    if p.is_file()
}
assert actual_files == expected_files, {
    "missing": sorted(expected_files-actual_files),
    "extra": sorted(actual_files-expected_files),
}
assert not any(p.is_symlink() for p in root.rglob("*"))

manifest={}
for number,line in enumerate((root/"MANIFEST.sha256").read_text(encoding="utf-8").splitlines(),1):
    if not line:
        continue
    digest,sep,relative=line.partition("  ")
    assert sep and len(digest)==64, (number,line)
    manifest[relative]=digest
actual_manifest={
    p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in root.rglob("*")
    if p.is_file() and p.name!="MANIFEST.sha256"
}
assert manifest == actual_manifest

publication=load(root/"publication.json")
assert publication["study_eligible"] is True
privacy=publication["privacy"]
assert privacy["oracle_projection"]=="public-labels-resolution-method/v1"
for key in (
    "raw_provider_http_included",
    "reasoning_summaries_included",
    "private_adjudicator_votes_included",
    "human_resolution_rationale_included",
    "human_participant_identity_included",
):
    assert privacy[key] is False, (key,privacy[key])
assert privacy["checks"]
assert all(value is True for key,value in privacy["checks"].items() if key!="typesafe_api_key_scan")

corpus=load(root/"datasets/corpus.json")
oracle=load(root/"datasets/oracle.json")
report=load(root/"metrics/decision-study-report.json")
requests=jsonl(root/"evidence/provider-requests.jsonl")
observations=jsonl(root/"evidence/observations.jsonl")
exclusions=jsonl(root/"evidence/exclusions.jsonl")
outcomes=jsonl(root/"evidence/outcomes.jsonl")

assert len(corpus["cases"]) == 120
assert len(oracle["records"]) == 120
assert len(requests) == 120
assert len(observations) == 360
assert len(exclusions) == 0
assert len(outcomes) == 360
assert report["eligibility"]["study_eligible"] is True
assert report["counts"]["exclusions"] == 0
assert report["counts"]["observations"] == 360
assert report["counts"]["oracle_outcomes"] == 360
assert all(
    seam["counts"]["oracle_eligible"] == 120
    for seam in report["seams"].values()
)

for record in oracle["records"]:
    for detail in record.get("adjudication", {}).values():
        assert set(detail) <= {"status","method"}
    provenance=record.get("provenance", {})
    assert set(provenance) <= {
        "protocol_version",
        "authoring_view_sha256",
        "frozen_at",
        "public_projection",
    }

verification={
    "format":"agent-workflow-benchmark/decision-study-p3-verification/v1",
    "status":"pass",
    "verified_at":datetime.now(timezone.utc).isoformat(),
    "study_id":publication["study_id"],
    "study_version":publication["study_version"],
    "dataset_version":publication["dataset_version"],
    "oracle_version":publication["oracle_version"],
    "counts":{
        "cases":len(corpus["cases"]),
        "oracle_records":len(oracle["records"]),
        "provider_requests":len(requests),
        "observations":len(observations),
        "outcomes":len(outcomes),
        "exclusions":len(exclusions),
    },
    "checks":{
        "exact_file_allowlist":True,
        "manifest_integrity":True,
        "study_eligible":True,
        "oracle_public_projection":True,
        "no_private_adjudicator_votes":True,
        "no_human_resolution_rationale":True,
        "no_human_participant_identity":True,
        "no_reasoning_summaries":True,
        "privacy_contract":True,
        "full_frozen_sample":True,
    },
}
verification_path.parent.mkdir(parents=True, exist_ok=True)
tmp=verification_path.with_name(verification_path.name+".tmp")
tmp.write_text(json.dumps(verification,indent=2,sort_keys=True)+"\n",encoding="utf-8")
tmp.replace(verification_path)
print(json.dumps(verification["counts"],sort_keys=True))
print("P3 publication verification: PASS")
print(verification_path)
PY

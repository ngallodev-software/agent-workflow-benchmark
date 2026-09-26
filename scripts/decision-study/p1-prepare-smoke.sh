#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

ds_require_executable "$PYTHON"
ds_verify_source_corpus

[[ "$P1_SAMPLE_SIZE" =~ ^[0-9]+$ ]] || ds_die "P1_SAMPLE_SIZE must be an integer"
(( P1_SAMPLE_SIZE >= 1 )) || ds_die "P1_SAMPLE_SIZE must be >= 1"
(( P1_SAMPLE_SIZE < 100 )) || ds_die "P1 smoke must remain below the frozen minimum oracle n=100"

if [[ -e "$P1_CORPUS" || -e "$P1_SELECTION" || -e "$P1_RUN" ]]; then
  ds_die "P1 output already exists under $P1_ROOT; preserve it and choose a new P1_ROOT for another smoke run"
fi

mkdir -p "$P1_ROOT"
chmod 700 "$P1_ROOT"

"$PYTHON" - "$SOURCE_CORPUS" "$P1_CORPUS" "$P1_SELECTION" "$P1_SAMPLE_SIZE" "$DS_EXPECTED_CORPUS_SHA256" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

source_path=Path(sys.argv[1])
corpus_path=Path(sys.argv[2])
selection_path=Path(sys.argv[3])
sample_size=int(sys.argv[4])
expected_sha=sys.argv[5]

raw=source_path.read_bytes()
source_sha=hashlib.sha256(raw).hexdigest()
if source_sha != expected_sha:
    raise SystemExit("source corpus changed during P1 preparation")
source=json.loads(raw)
if source.get("study_id") != "routing-semantic-v1":
    raise SystemExit("unexpected study_id")
if source.get("dataset_version") != "routing-semantic-corpus-v1.0.0":
    raise SystemExit("unexpected dataset_version")
cases=source.get("cases")
if not isinstance(cases, list) or sample_size > len(cases):
    raise SystemExit("invalid P1 sample size")

def rank(case):
    case_id=str(case["case_id"])
    digest=hashlib.sha256(f"{source_sha}:{case_id}".encode()).hexdigest()
    return digest, case_id

selected=sorted(cases, key=rank)[:sample_size]
selected_ids=[str(case["case_id"]) for case in selected]
smoke={
    "schema": source["schema"],
    "study_id": source["study_id"],
    "dataset_version": source["dataset_version"],
    "cases": selected,
}
selection={
    "format": "agent-workflow-benchmark/decision-study-p1-selection/v1",
    "study_id": source["study_id"],
    "dataset_version": source["dataset_version"],
    "development_only": True,
    "source_corpus_sha256": source_sha,
    "source_case_count": len(cases),
    "sample_size": sample_size,
    "selection_algorithm": "ascending sha256(source_corpus_sha256 + ':' + case_id)",
    "selected_case_ids": selected_ids,
}

for path,value in ((corpus_path,smoke),(selection_path,selection)):
    tmp=path.with_name(path.name+".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    tmp.replace(path)

print("P1 selected cases:")
for case_id in selected_ids:
    print(f"  {case_id}")
print(f"source_corpus_sha256: {source_sha}")
PY

echo "P1 smoke corpus: $P1_CORPUS"
echo "P1 selection:    $P1_SELECTION"

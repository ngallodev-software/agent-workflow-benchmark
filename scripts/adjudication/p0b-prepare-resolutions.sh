#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

A_PASS="$ORACLE_RUN/a/output/adjudication.json"
B_PASS="$ORACLE_RUN/b/output/adjudication.json"
C_PASS="$ORACLE_RUN/c/output/adjudication.json"

aw_require_executable "$PYTHON"
aw_require_file "$ORACLE_VIEW"
aw_require_file "$DISPUTE_VIEW"
aw_require_file "$A_PASS"
aw_require_file "$B_PASS"
aw_require_file "$C_PASS"

if [[ -e "$RESOLUTIONS" || -e "$RESOLUTION_REVIEW" ]]; then
  aw_die "resolution artifacts already exist; preserve/edit them rather than regenerating: $RESOLUTIONS / $RESOLUTION_REVIEW"
fi

"$PYTHON" -   "$ORACLE_VIEW"   "$DISPUTE_VIEW"   "$A_PASS"   "$B_PASS"   "$C_PASS"   "$RESOLUTIONS"   "$RESOLUTION_REVIEW" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

(
    authoring_path,
    dispute_path,
    a_path,
    b_path,
    c_path,
    resolutions_path,
    review_path,
) = map(Path, sys.argv[1:])

def load(path: Path):
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value

def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)

def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

authoring = load(authoring_path)
dispute = load(dispute_path)
a_pass = load(a_path)
b_pass = load(b_path)
c_pass = load(c_path)

if dispute.get("source_authoring_view_sha256") != sha256(authoring_path):
    raise SystemExit("dispute view does not belong to the supplied authoring view")

for name, value in (("A", a_pass), ("B", b_pass)):
    if value.get("input_view_sha256") != sha256(authoring_path):
        raise SystemExit(f"{name} pass does not belong to the supplied authoring view")
if c_pass.get("input_view_sha256") != sha256(dispute_path):
    raise SystemExit("C pass does not belong to the supplied dispute view")

def records_by_case(value):
    result = {}
    for record in value.get("records", []):
        cid = record.get("case_id")
        if not isinstance(cid, str) or cid in result:
            raise SystemExit("invalid or duplicate adjudication case ID")
        result[cid] = record
    return result

a_records = records_by_case(a_pass)
b_records = records_by_case(b_pass)
c_records = records_by_case(c_pass)

authoring_cases = {
    str(item["case_id"]): item
    for item in authoring.get("cases", [])
}
decision_seams = {
    str(item["decision_id"]): item
    for item in authoring.get("decision_seams", [])
}

oracle_questions = {
    "routing.task_class": "What is the primary requested deliverable of this case?",
    "routing.interaction_required": (
        "Is a material user decision, authorization, or preference missing from "
        "the supplied state and required before the requested action can be "
        "completed responsibly?"
    ),
    "routing.semantic_risk": (
        "What is the consequence of acting on a materially wrong interpretation "
        "of this request?"
    ),
}

conflicts = []
for case in dispute.get("cases", []):
    case_id = str(case["case_id"])
    for decision_id in case.get("disputed_decision_ids", []):
        decision_id = str(decision_id)
        try:
            a = a_records[case_id]["labels"][decision_id]
            b = b_records[case_id]["labels"][decision_id]
            c = c_records[case_id]["labels"][decision_id]
        except KeyError as exc:
            raise SystemExit(
                f"missing A/B/C label for {case_id}:{decision_id}: {exc}"
            ) from exc

        votes = [a, b, c]
        if any(votes.count(value) >= 2 for value in votes):
            continue

        source = authoring_cases.get(case_id) or {}
        seam = decision_seams.get(decision_id) or {}
        allowed = seam.get("labels")
        if allowed is None:
            allowed = seam.get("levels")
        if allowed is None and seam.get("oracle_type") == "boolean":
            allowed = [False, True]

        conflicts.append(
            {
                "case_id": case_id,
                "decision_id": decision_id,
                "oracle_question": oracle_questions.get(
                    decision_id,
                    f"What is the correct frozen-oracle label for {decision_id}?",
                ),
                "task": source.get("task"),
                "metadata": source.get("metadata"),
                "oracle_eligible": source.get("oracle_eligible"),
                "decision_seam": seam,
                "allowed_labels": allowed,
                "votes": {"a": a, "b": b, "c": c},
            }
        )

resolutions = {
    "schema": "agent-workflow-benchmark/decision-study-adjudication-resolutions/v1",
    "study_id": authoring["study_id"],
    "dataset_version": authoring["dataset_version"],
    "protocol_version": dispute["protocol_version"],
    "authoring_view_sha256": sha256(authoring_path),
    "records": [
        {
            "case_id": item["case_id"],
            "decision_id": item["decision_id"],
            "status": "unresolved",
            "rationale": "TODO: record the adjudication rationale for this three-way conflict.",
            "participants": [],
        }
        for item in conflicts
    ],
}

review = {
    "format": "agent-workflow-benchmark/three-way-resolution-review/v1",
    "study_id": authoring["study_id"],
    "dataset_version": authoring["dataset_version"],
    "authoring_view_sha256": sha256(authoring_path),
    "dispute_view_sha256": sha256(dispute_path),
    "pass_sha256": {
        "a": sha256(a_path),
        "b": sha256(b_path),
        "c": sha256(c_path),
    },
    "three_way_conflicts": conflicts,
}

atomic_json(resolutions_path, resolutions)
atomic_json(review_path, review)

print(f"three_way_conflicts: {len(conflicts)}")
print(f"resolutions: {resolutions_path}")
print(f"review: {review_path}")
PY

bash "$SCRIPT_DIR/p0b-render-resolution-review.sh"

conflicts="$("$PYTHON" - "$RESOLUTIONS" <<'PY'
import json
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
print(len(value.get("records", [])))
PY
)"

if [[ "$conflicts" -eq 0 ]]; then
  echo "No three-way conflicts require recorded discussion."
else
  echo
  echo "$conflicts three-way conflict(s) require recorded adjudication."
  echo "Human review: $RESOLUTION_REVIEW_MD"
  echo "Machine review: $RESOLUTION_REVIEW"
  echo "Edit: $RESOLUTIONS"
  echo
  echo "For each record, choose either:"
  echo "  resolved   -> add a valid label, replace the TODO rationale, and record participants"
  echo "  unresolved -> keep label absent, replace the TODO rationale, and record participants"
  echo
  echo "Then rerun:"
  echo "  bash scripts/adjudication/p0b-freeze.sh"
fi

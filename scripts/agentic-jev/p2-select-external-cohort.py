#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STUDY_ID = "agentic-jev-external-eval-scout-v1"
INSPECT_EVALS_REPOSITORY = "UKGovernmentBEIS/inspect_evals"
INSPECT_EVALS_COMMIT = "b49df6bc9e30b2d24571084bc710b9439b9ffa77"
SWE_BENCH_DATASET = "MariusHobbhahn/swe-bench-verified-mini"
SWE_BENCH_REVISION = "b316c349947c29963fce3f4a65967c9807a4b673"
MANAGER_SELECTION_SALT = "agentic-jev-external-manager-v1"
MANAGER_COUNT = 6

# Development-only semantic-opportunity scouting from public issue/problem text
# and discussion/hints. No gold patch, hidden-test, FAIL_TO_PASS/PASS_TO_PASS,
# or correctness fields are used to choose these IDs.
SWE_BENCH_CANDIDATES = (
    {
        "id": "django__django-12273",
        "jev_seam": "behavior-intent",
        "rationale": (
            "Issue discussion explicitly disputes whether the observed primary-key "
            "reset behavior is a bug and what behavior the user is actually seeking."
        ),
    },
    {
        "id": "django__django-12308",
        "jev_seam": "implementation-strategy",
        "rationale": (
            "Maintainer discussion contrasts brittle special-casing with waiting for "
            "a broader type boundary, creating a strategy/authority choice."
        ),
    },
    {
        "id": "django__django-12406",
        "jev_seam": "interaction-policy",
        "rationale": (
            "The issue turns on UI semantics: whether a required RadioSelect should "
            "offer a blank option even though Select commonly does."
        ),
    },
    {
        "id": "django__django-9296",
        "jev_seam": "feature-value",
        "rationale": (
            "The feature discussion weighs expected Python behavior against whether "
            "the functionality is common enough to justify API surface."
        ),
    },
    {
        "id": "sphinx-doc__sphinx-10323",
        "jev_seam": "composition-semantics",
        "rationale": (
            "The issue discusses competing interpretations of dedent behavior when "
            "literalinclude is combined with prepend/append content."
        ),
    },
    {
        "id": "sphinx-doc__sphinx-8551",
        "jev_seam": "ambiguity-resolution",
        "rationale": (
            "The issue is about ambiguous symbol lookup, balancing false ambiguity "
            "warnings against silently resolving the wrong cross-reference."
        ),
    },
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_manager_tasks(csv_path: Path) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"question_id", "variant", "set", "title"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise SystemExit(
                "SWE-Lancer CSV missing selection fields: " + ", ".join(sorted(missing))
            )
        for row in reader:
            if row["variant"] != "swe_manager":
                continue
            if row["set"] != "diamond":
                continue
            question_id = row["question_id"].strip()
            if not question_id:
                continue
            candidates.append(
                {
                    "id": question_id,
                    "title": row["title"].strip(),
                    "selection_digest": hashlib.sha256(
                        f"{MANAGER_SELECTION_SALT}:{question_id}".encode("utf-8")
                    ).hexdigest(),
                }
            )
    if len(candidates) < MANAGER_COUNT:
        raise SystemExit(
            f"expected at least {MANAGER_COUNT} SWE-Lancer manager candidates; "
            f"observed {len(candidates)}"
        )
    candidates.sort(key=lambda item: (item["selection_digest"], item["id"]))
    return candidates[:MANAGER_COUNT]


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: p2-select-external-cohort.py "
            "<inspect_evals_checkout> <output_manifest> <prior_pilot_manifest>"
        )

    checkout = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    prior_manifest = Path(sys.argv[3]).resolve()
    if output.exists():
        raise SystemExit(f"external-eval cohort manifest already exists: {output}")

    csv_path = (
        checkout
        / "src"
        / "inspect_evals"
        / "swe_lancer"
        / "data"
        / "all_swelancer_tasks.csv"
    )
    if not csv_path.is_file():
        raise SystemExit(f"missing pinned SWE-Lancer CSV: {csv_path}")
    if not prior_manifest.is_file():
        raise SystemExit(f"missing completed pilot manifest: {prior_manifest}")

    prior = json.loads(prior_manifest.read_text(encoding="utf-8"))
    if prior.get("study_id") != "agentic-jev-pilot-v1":
        raise SystemExit("prior manifest is not agentic-jev-pilot-v1")
    arms = prior.get("arms")
    c_arm = arms.get("C-skill-plus-jev") if isinstance(arms, dict) else None
    if not isinstance(c_arm, dict) or c_arm.get("samples") != 24:
        raise SystemExit("prior pilot does not contain the completed 24-sample C arm")
    if c_arm.get("jev_tool_calls") != 0:
        raise SystemExit(
            "external uptake scout is defined as the follow-up to the zero-call pilot"
        )

    manager = select_manager_tasks(csv_path)
    record = {
        "schema": "agent-workflow-benchmark/agentic-jev-external-eval-cohort/v1",
        "study_id": STUDY_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "development_only": True,
        "purpose": (
            "stress-test spontaneous Jev uptake on established public evaluations "
            "before any new A/B/C effectiveness study"
        ),
        "lineage": {
            "prior_study_id": prior["study_id"],
            "prior_manifest_sha256": sha256_file(prior_manifest),
            "prior_c_arm_samples": c_arm["samples"],
            "prior_c_arm_jev_calls": c_arm["jev_tool_calls"],
        },
        "sources": {
            "inspect_evals": {
                "repository": INSPECT_EVALS_REPOSITORY,
                "commit": INSPECT_EVALS_COMMIT,
                "swe_lancer_csv_sha256": sha256_file(csv_path),
            },
            "swe_bench_verified_mini": {
                "dataset": SWE_BENCH_DATASET,
                "revision": SWE_BENCH_REVISION,
            },
        },
        "selection_contract": {
            "gold_fields_used_for_selection": False,
            "manager_selection": {
                "variant": "swe_manager",
                "split": "diamond",
                "count": MANAGER_COUNT,
                "method": "ascending sha256(salt + ':' + question_id)",
                "salt": MANAGER_SELECTION_SALT,
                "fields_read": ["question_id", "variant", "set", "title"],
            },
            "swe_bench_selection": {
                "count": len(SWE_BENCH_CANDIDATES),
                "method": (
                    "manual development-only semantic-opportunity scout from "
                    "problem_statement and public issue discussion/hints"
                ),
                "warning": (
                    "The public dataset viewer exposes gold columns alongside prompt "
                    "columns. This cohort is exploratory and must not be represented "
                    "as a blinded or confirmatory selection."
                ),
            },
        },
        "cohorts": {
            "swe_lancer_manager_choice": manager,
            "swe_bench_semantic_ambiguity": list(SWE_BENCH_CANDIDATES),
        },
        "execution_gate": {
            "first_run": "C-skill-plus-jev only",
            "samples": MANAGER_COUNT + len(SWE_BENCH_CANDIDATES),
            "reason": (
                "establish nonzero live-Jev treatment exposure before spending on "
                "another matched A/B/C matrix"
            ),
            "after_run": (
                "stop and inspect call locations, primitives, receipts, and decisions "
                "before designing any comparative outcome study"
            ),
        },
        "claim_boundary": {
            "exploratory_only": True,
            "effectiveness_claim_allowed": False,
            "selection_is_confirmatory": False,
        },
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("Agentic Jev external-eval cohort frozen")
    print("SWE-Lancer manager IDs:")
    for item in manager:
        print(" ", item["id"], "-", item["title"])
    print("SWE-bench semantic-ambiguity IDs:")
    for item in SWE_BENCH_CANDIDATES:
        print(" ", item["id"], "-", item["jev_seam"])
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

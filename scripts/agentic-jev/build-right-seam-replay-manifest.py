#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_workflow_benchmark.benchmarking.agentic_jev_right_seam import (
    MANIFEST_SCHEMA,
    dispatch_sha256,
    validate_replay_manifest,
)
from agent_workflow_benchmark.benchmarking.agentic_jev_request_v2 import sha256_json


def first_record(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise SystemExit(f"{path}: first record is not an object")
                return value
    raise SystemExit(f"{path}: empty request history")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=30)
    args = parser.parse_args()

    samples = args.run_root / "paired-run" / "samples"
    histories = sorted(samples.glob("*/treatment/jev-request-history-v2.jsonl"))
    if len(histories) != args.expected_count:
        raise SystemExit(
            f"expected {args.expected_count} histories; found {len(histories)}"
        )

    entries = []
    study_ids = set()
    for history in histories:
        sample_id = history.parents[1].name
        record = first_record(history)
        request = record.get("request")
        if not isinstance(request, dict):
            raise SystemExit(f"{sample_id}: missing request object")

        recorded_hash = str(record.get("request_sha256") or "")
        semantic_hash = sha256_json(request)
        if not recorded_hash:
            raise SystemExit(f"{sample_id}: missing recorded request_sha256")
        if recorded_hash != semantic_hash:
            raise SystemExit(
                f"{sample_id}: recorded/recomputed request hash mismatch"
            )

        study_id = record.get("study_id")
        if study_id:
            study_ids.add(str(study_id))

        entries.append(
            {
                "sample_id": sample_id,
                "request": request,
                "semantic_sha256": semantic_hash,
                "dispatch_sha256": dispatch_sha256(request),
                "recorded": {
                    "request_sha256": recorded_hash,
                    "decision_sha256": record.get("decision_sha256"),
                    "state_sha256": record.get("state_sha256"),
                    "questions_sha256": record.get("questions_sha256"),
                    "builder_version": record.get("builder_version"),
                    "policy_id": record.get("policy_id"),
                    "resolved_model": record.get("resolved_model"),
                    "provider_request_id": record.get("provider_request_id"),
                    "status": record.get("status"),
                },
            }
        )

    manifest = validate_replay_manifest(
        {"schema": MANIFEST_SCHEMA, "entries": entries}
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summary = {
        "schema": "agent-workflow-benchmark/jev-right-seam-replay-qualification/v1",
        "qualified": True,
        "sample_count": len(entries),
        "study_ids": sorted(study_ids),
        "unique_semantic_hashes": len({e["semantic_sha256"] for e in entries}),
        "unique_dispatch_hashes": len({e["dispatch_sha256"] for e in entries}),
        "all_recorded_request_hashes_match": True,
        "provider_calls_made": 0,
        "fresh_evaluation_tasks_consumed": 0,
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

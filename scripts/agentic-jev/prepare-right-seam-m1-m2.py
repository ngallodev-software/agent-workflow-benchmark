#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_workflow_benchmark.benchmarking.agentic_jev_right_seam import (
    M1,
    M2,
    build_m1,
    build_m2,
    counterbalanced_ids,
    reorder_mechanism_request,
    validate_replay_manifest,
)
from agent_workflow_benchmark.benchmarking.agentic_jev_request_v2 import sha256_json


def proposal_ids(entry: dict) -> list[str]:
    request = entry["request"]
    proposals = request["state"]["authoritative_task"]["proposals"]
    return [str(k) for k in proposals]


def pack_variant(
    *,
    sample_id: str,
    mechanism: str,
    arm: str,
    built: dict,
    source_semantic_sha256: str,
    source_dispatch_sha256: str,
) -> dict:
    return {
        "sample_id": sample_id,
        "mechanism": mechanism,
        "order_arm": arm,
        "source_first_call_semantic_sha256": source_semantic_sha256,
        "source_first_call_dispatch_sha256": source_dispatch_sha256,
        "proposal_order": list(
            built["request"]["state"]["authoritative_task"]["proposals"]
        ),
        "semantic_content_sha256": built["semantic_content_sha256"],
        "dispatch_body_sha256": built["dispatch_body_sha256"],
        "request": built["request"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=30)
    args = parser.parse_args()

    raw = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest = validate_replay_manifest(raw)
    entries = manifest["entries"]
    if len(entries) != args.expected_count:
        raise SystemExit(
            f"expected {args.expected_count} replay entries; found {len(entries)}"
        )

    variants: list[dict] = []
    replay_models: set[str] = set()
    per_mechanism: dict[str, dict[str, int]] = {
        M1: {
            "samples": 0,
            "source_counterbalanced_semantic_equal": 0,
            "source_counterbalanced_dispatch_different": 0,
        },
        M2: {
            "samples": 0,
            "source_counterbalanced_semantic_equal": 0,
            "source_counterbalanced_dispatch_different": 0,
        },
    }

    for entry in entries:
        sample_id = entry["sample_id"]
        source_request = entry["request"]
        source_semantic = entry["semantic_sha256"]
        source_dispatch = entry["dispatch_sha256"]
        ids = proposal_ids(entry)

        if sha256_json(source_request["state"]) != sha256_json(
            build_m1(entry)["request"]["state"]
        ):
            raise SystemExit(f"{sample_id}: M1 changed source semantic state")
        if sha256_json(source_request["state"]) != sha256_json(
            build_m2(entry)["request"]["state"]
        ):
            raise SystemExit(f"{sample_id}: M2 changed source semantic state")

        for mechanism, builder in ((M1, build_m1), (M2, build_m2)):
            source_built = builder(entry)
            cb_order = counterbalanced_ids(
                ids,
                mechanism=mechanism,
                sample_id=sample_id,
            )
            cb_built = reorder_mechanism_request(
                source_built,
                proposal_order=cb_order,
            )

            replay_model = source_built["request"].get("model")
            if not isinstance(replay_model, str) or not replay_model.strip():
                raise SystemExit(
                    f"{sample_id}/{mechanism}: replay model is not explicitly pinned"
                )
            replay_models.add(replay_model.strip())

            source_hash = source_built["semantic_content_sha256"]
            cb_hash = cb_built["semantic_content_sha256"]
            if source_hash != cb_hash:
                raise SystemExit(
                    f"{sample_id}/{mechanism}: counterbalance changed semantic content"
                )
            if source_built["dispatch_body_sha256"] == cb_built["dispatch_body_sha256"]:
                raise SystemExit(
                    f"{sample_id}/{mechanism}: counterbalance did not change dispatch identity"
                )

            best_criteria = source_built["request"]["questions"]["best_proposal"][
                "criteria"
            ]
            if mechanism == M1 and "insufficient_evidence" not in best_criteria:
                raise SystemExit(
                    f"{sample_id}: M1 unexpectedly removed insufficient_evidence"
                )
            if mechanism == M2 and "insufficient_evidence" in best_criteria:
                raise SystemExit(
                    f"{sample_id}: M2 retained insufficient_evidence in Choice"
                )

            variants.append(
                pack_variant(
                    sample_id=sample_id,
                    mechanism=mechanism,
                    arm="source_order",
                    built=source_built,
                    source_semantic_sha256=source_semantic,
                    source_dispatch_sha256=source_dispatch,
                )
            )
            variants.append(
                pack_variant(
                    sample_id=sample_id,
                    mechanism=mechanism,
                    arm="counterbalanced_order",
                    built=cb_built,
                    source_semantic_sha256=source_semantic,
                    source_dispatch_sha256=source_dispatch,
                )
            )

            stats = per_mechanism[mechanism]
            stats["samples"] += 1
            stats["source_counterbalanced_semantic_equal"] += 1
            stats["source_counterbalanced_dispatch_different"] += 1

    private_pack = {
        "schema": "agent-workflow-benchmark/jev-right-seam-m1-m2-request-pack/v1",
        "source_manifest_schema": manifest["schema"],
        "sample_count": len(entries),
        "variant_count": len(variants),
        "variants": variants,
    }

    summary = {
        "schema": "agent-workflow-benchmark/jev-right-seam-m1-m2-preparation/v1",
        "qualified": True,
        "sample_count": len(entries),
        "mechanisms": per_mechanism,
        "variants_per_sample": 4,
        "variant_count": len(variants),
        "provider_calls_made": 0,
        "fresh_evaluation_tasks_consumed": 0,
        "gold_fields_loaded": False,
        "replay_models": sorted(replay_models),
        "all_replay_requests_model_pinned": True,
        "private_request_pack": str(args.output),
    }

    if len(variants) != args.expected_count * 4:
        raise SystemExit(
            f"expected {args.expected_count * 4} request variants; found {len(variants)}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(private_pack, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

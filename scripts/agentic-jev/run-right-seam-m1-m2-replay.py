#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow_benchmark.benchmarking.agentic_jev import execute_jev_request
from agent_workflow_benchmark.benchmarking.agentic_jev_request_v2 import sha256_json
from agent_workflow_benchmark.benchmarking.agentic_jev_right_seam import (
    M1,
    M2,
    dispatch_sha256,
)

PACK_SCHEMA = "agent-workflow-benchmark/jev-right-seam-m1-m2-request-pack/v1"
RESULT_SCHEMA = "agent-workflow-benchmark/jev-right-seam-m1-m2-replay-result/v1"
SUMMARY_SCHEMA = "agent-workflow-benchmark/jev-right-seam-m1-m2-replay-summary/v1"
STUDY_ID = "agentic-jev-right-seam-m1-m2-replay"



def _variant_key(value: dict[str, Any]) -> str:
    return "::".join(
        (
            str(value["sample_id"]),
            str(value["mechanism"]),
            str(value["order_arm"]),
        )
    )


def _load_success_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    success: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if (
                isinstance(record, dict)
                and record.get("schema") == RESULT_SCHEMA
                and record.get("status") == "success"
            ):
                success.add(str(record.get("variant_key") or ""))
    return success


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def _select(
    variants: list[dict[str, Any]],
    *,
    mechanisms: set[str],
    order_arms: set[str],
    limit_samples: int | None,
) -> list[dict[str, Any]]:
    sample_ids = sorted({str(v["sample_id"]) for v in variants})
    if limit_samples is not None:
        sample_ids = sample_ids[:limit_samples]
    allowed_samples = set(sample_ids)
    return [
        v
        for v in variants
        if str(v["sample_id"]) in allowed_samples
        and str(v["mechanism"]) in mechanisms
        and str(v["order_arm"]) in order_arms
    ]


def _validate_variant(variant: dict[str, Any]) -> None:
    request = variant.get("request")
    if not isinstance(request, dict):
        raise WorkflowError("replay variant missing request object")
    if set(request) != {"state", "questions", "model"}:
        raise WorkflowError("replay request must contain exactly state/questions/model")
    model = request.get("model")
    if not isinstance(model, str) or not model.strip():
        raise WorkflowError("replay request model must be explicitly pinned")

    semantic = sha256_json(request)
    dispatch = dispatch_sha256(request)
    if semantic != variant.get("semantic_content_sha256"):
        raise WorkflowError(
            f"{_variant_key(variant)}: semantic request identity mismatch"
        )
    if dispatch != variant.get("dispatch_body_sha256"):
        raise WorkflowError(
            f"{_variant_key(variant)}: dispatch request identity mismatch"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--expected-pack-sha256")
    parser.add_argument("--mechanism", action="append", choices=[M1, M2])
    parser.add_argument(
        "--order-arm",
        action="append",
        choices=["source_order", "counterbalanced_order"],
    )
    parser.add_argument("--limit-samples", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    pack_bytes = args.pack.read_bytes()
    pack_sha = hashlib.sha256(pack_bytes).hexdigest()
    if args.expected_pack_sha256 and pack_sha != args.expected_pack_sha256:
        raise SystemExit(
            f"private request pack SHA-256 mismatch: {pack_sha} != "
            f"{args.expected_pack_sha256}"
        )

    pack = json.loads(pack_bytes)
    if not isinstance(pack, dict) or pack.get("schema") != PACK_SCHEMA:
        raise SystemExit(f"request pack schema must be {PACK_SCHEMA}")
    raw_variants = pack.get("variants")
    if not isinstance(raw_variants, list) or not raw_variants:
        raise SystemExit("request pack requires variants")

    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_variants:
        if not isinstance(raw, dict):
            raise SystemExit("request pack variant must be an object")
        _validate_variant(raw)
        key = _variant_key(raw)
        if key in seen:
            raise SystemExit(f"duplicate request-pack variant: {key}")
        seen.add(key)
        variants.append(raw)

    mechanisms = set(args.mechanism or [M1, M2])
    order_arms = set(
        args.order_arm or ["source_order", "counterbalanced_order"]
    )
    if args.limit_samples is not None and args.limit_samples < 1:
        raise SystemExit("--limit-samples must be >= 1")

    selected = _select(
        variants,
        mechanisms=mechanisms,
        order_arms=order_arms,
        limit_samples=args.limit_samples,
    )
    if not selected:
        raise SystemExit("selection produced no replay variants")

    completed = set() if args.no_resume else _load_success_keys(args.results)
    pending = [v for v in selected if _variant_key(v) not in completed]

    summary: dict[str, Any] = {
        "schema": SUMMARY_SCHEMA,
        "study_id": STUDY_ID,
        "pack_sha256": pack_sha,
        "pack_variant_count": len(variants),
        "selected_variant_count": len(selected),
        "already_successful_count": len(selected) - len(pending),
        "pending_variant_count": len(pending),
        "mechanisms": sorted(mechanisms),
        "order_arms": sorted(order_arms),
        "limit_samples": args.limit_samples,
        "dry_run": args.dry_run,
        "provider_calls_attempted": 0,
        "provider_calls_succeeded": 0,
        "provider_calls_failed": 0,
        "fresh_evaluation_tasks_consumed": 0,
    }

    if args.dry_run:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return

    for variant in pending:
        key = _variant_key(variant)
        request = variant["request"]
        assert isinstance(request, dict)
        receipt_name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".jsonl"
        receipt_path = args.receipts_dir / receipt_name

        base = {
            "schema": RESULT_SCHEMA,
            "study_id": STUDY_ID,
            "variant_key": key,
            "sample_id": variant["sample_id"],
            "mechanism": variant["mechanism"],
            "order_arm": variant["order_arm"],
            "semantic_content_sha256": variant["semantic_content_sha256"],
            "dispatch_body_sha256": variant["dispatch_body_sha256"],
            "requested_model": request["model"],
            "receipt_path": str(receipt_path),
        }
        summary["provider_calls_attempted"] += 1

        try:
            result = execute_jev_request(
                state=request["state"],
                questions=request["questions"],
                purpose=(
                    "Exploratory retained-cohort right-seam mechanism replay; "
                    "no fresh effectiveness task."
                ),
                model=request["model"],
                receipt_path=receipt_path,
                study_id=STUDY_ID,
            )
            if result.get("request_sha256") != variant["semantic_content_sha256"]:
                raise WorkflowError(
                    f"{key}: provider executor request identity differs from frozen pack"
                )
            resolved_model = result.get("model")
            if resolved_model != request["model"]:
                raise WorkflowError(
                    f"{key}: resolved model {resolved_model!r} differs from "
                    f"requested model {request['model']!r}"
                )

            record = {
                **base,
                "status": "success",
                "provider_request_id": result.get("request_id"),
                "resolved_model": resolved_model,
                "answers": result.get("answers"),
                "usage": result.get("usage"),
                "duration_ms": result.get("duration_ms"),
            }
            _append_jsonl(args.results, record)
            summary["provider_calls_succeeded"] += 1
        except Exception as exc:
            _append_jsonl(
                args.results,
                {
                    **base,
                    "status": "failure",
                    "error_class": type(exc).__name__,
                },
            )
            summary["provider_calls_failed"] += 1
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(
                json.dumps(summary, indent=2) + "\n",
                encoding="utf-8",
            )
            raise

    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

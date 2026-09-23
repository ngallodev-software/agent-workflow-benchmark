#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

PUBLIC_ARMS = {
    "control_raw": "structured-direct",
    "workflow_full": "agent-workflow-slimmed",
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(source: Path, destination: Path) -> None:
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            ".git", ".agent-workflow-benchmark", ".pytest_cache",
            "__pycache__", "*.pyc",
        ),
    )


def selected_attempt(plan: dict[str, Any], run_dir: Path, pair: dict[str, Any]):
    state = load(
        run_dir / "pair-state" / str(pair["case_id"])
        / f"r{int(pair['repetition']):02d}" / "pair.json"
    )
    selected = int(state["selected_attempt"])
    attempt = next(
        item for item in pair["attempts"] if int(item["attempt"]) == selected
    )
    return state, attempt


def timing_summary(arm: dict[str, Any]) -> dict[str, Any]:
    phases = arm.get("phases", [])
    wall = active = host = 0.0
    amplification = {
        "model_turn_count": 0,
        "tool_call_count": 0,
        "command_execution_count": 0,
        "launch_prompt_bytes": 0,
        "injected_context_bytes": 0,
        "injected_context_estimated_tokens": 0,
    }
    observed = False
    phase_rows = []
    for phase in phases:
        breakdown = phase.get("timing_breakdown") or {}
        phase_wall = phase.get("phase_wall_seconds")
        phase_active = phase.get("active_process_seconds")
        phase_host = breakdown.get("host_overhead_seconds")
        if isinstance(phase_wall, (int, float)) and not isinstance(phase_wall, bool):
            wall += float(phase_wall)
        if isinstance(phase_active, (int, float)) and not isinstance(phase_active, bool):
            active += float(phase_active)
        if isinstance(phase_host, (int, float)) and not isinstance(phase_host, bool):
            host += float(phase_host)

        if breakdown.get("runner_kind") == "direct-executor":
            amp = breakdown.get("amplification") or {}
            launch = breakdown.get("prompt_bytes")
            injected = 0
            injected_tokens = 0
        else:
            amp = breakdown.get("executor_context") or {}
            launch = breakdown.get("agent_workflow_launch_prompt_bytes")
            injected = amp.get("injected_context_bytes")
            injected_tokens = amp.get("injected_context_estimated_tokens")

        for key in ("model_turn_count", "tool_call_count", "command_execution_count"):
            value = amp.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                amplification[key] += int(value)
                observed = True
        if isinstance(launch, (int, float)) and not isinstance(launch, bool):
            amplification["launch_prompt_bytes"] += int(launch)
            observed = True
        if isinstance(injected, (int, float)) and not isinstance(injected, bool):
            amplification["injected_context_bytes"] += int(injected)
        if isinstance(injected_tokens, (int, float)) and not isinstance(injected_tokens, bool):
            amplification["injected_context_estimated_tokens"] += int(injected_tokens)

        phase_rows.append({
            "phase_id": phase.get("phase_id"),
            "phase_wall_seconds": phase_wall,
            "active_process_seconds": phase_active,
            "host_overhead_seconds": phase_host,
            "runner_kind": breakdown.get("runner_kind"),
            "conditional_model_invocation_skipped": breakdown.get(
                "conditional_model_invocation_skipped"
            ),
            "conditional_skip_reason": breakdown.get("conditional_skip_reason"),
            "conditional_skip_acceptance_command_ids": breakdown.get(
                "conditional_skip_acceptance_command_ids"
            ),
            "conditional_skip_evidence_source": breakdown.get(
                "conditional_skip_evidence_source"
            ),
        })

    return {
        "phase_wall_seconds": round(wall, 6),
        "executor_active_seconds": round(active, 6),
        "host_overhead_seconds": round(host, 6),
        "amplification": amplification if observed else None,
        "protocol": {
            "command_families": [
                (phase.get("timing_breakdown") or {}).get("executor_context", {}).get("command_families")
                for phase in phases
                if (phase.get("timing_breakdown") or {}).get("executor_context", {}).get("command_families")
            ],
            "protocol_command_counts": [
                (phase.get("timing_breakdown") or {}).get("executor_context", {}).get("protocol_command_counts")
                for phase in phases
                if (phase.get("timing_breakdown") or {}).get("executor_context", {}).get("protocol_command_counts")
            ],
            "message_kind_counts": [
                (phase.get("timing_breakdown") or {}).get("executor_context", {}).get("message_kind_counts")
                for phase in phases
                if (phase.get("timing_breakdown") or {}).get("executor_context", {}).get("message_kind_counts")
            ],
            "verification_cache_hits": sum(
                int((phase.get("timing_breakdown") or {}).get("executor_context", {}).get("verification_cache_hits", 0) or 0)
                for phase in phases
            ),
            "verification_cache_misses": sum(
                int((phase.get("timing_breakdown") or {}).get("executor_context", {}).get("verification_cache_misses", 0) or 0)
                for phase in phases
            ),
            "finish_invocations": sum(
                int((phase.get("timing_breakdown") or {}).get("executor_context", {}).get("finish_invocations", 0) or 0)
                for phase in phases
            ),
            "finish_incomplete_invocations": sum(
                int((phase.get("timing_breakdown") or {}).get("executor_context", {}).get("finish_incomplete_invocations", 0) or 0)
                for phase in phases
            ),
            "finish_outcomes": {
                outcome: sum(
                    int((phase.get("timing_breakdown") or {}).get("executor_context", {}).get("finish_outcomes", {}).get(outcome, 0) or 0)
                    for phase in phases
                )
                for outcome in sorted({
                    str(outcome)
                    for phase in phases
                    for outcome in (
                        (phase.get("timing_breakdown") or {}).get("executor_context", {}).get("finish_outcomes", {}) or {}
                    )
                })
            },
        },
        "phases": phase_rows,
    }


def public_environment(plan: dict[str, Any]) -> dict[str, Any]:
    environment = plan.get("environment") or {}
    keys = (
        "platform", "python", "machine", "processor", "git", "locale",
        "timezone", "codebase_memory_mode", "toolchain", "executor", "sha256",
    )
    return {key: environment.get(key) for key in keys}


def sanitize_visual(stage: Path, destination: Path) -> None:
    visual = stage / "visual"
    assessment = visual / "assessment.json"
    if assessment.is_file():
        value = load(assessment)
        value["url"] = "<local-live-url-redacted>"
        for screenshot in value.get("screenshots", []):
            if isinstance(screenshot, dict) and isinstance(screenshot.get("path"), str):
                screenshot["path"] = Path(screenshot["path"]).name
        write_json(destination / "assessment.json", value)
    for name in ("desktop.png", "tablet.png", "mobile.png"):
        copy_file(visual / name, destination / name)


def sanitize_typesafe(root: Path, destination: Path) -> dict[str, Any]:
    audit = root / "typesafe-api-audit.jsonl"
    qualification = root / "typesafe-semantic-qualification.json"
    value = {
        "schema": "agent-workflow/bm5-typesafe-public-summary/v1",
        "raw_audit_published": False,
        "raw_audit_sha256": sha256(audit) if audit.is_file() else None,
        "audit_records": 0,
        "qualification_calls": None,
        "treatment_includes_semantic_routing": False,
        "contexts": [],
    }
    if audit.is_file():
        value["audit_records"] = sum(
            1 for line in audit.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    if qualification.is_file():
        source = load(qualification)
        value["qualification_calls"] = source.get("qualification_calls")
        value["treatment_includes_semantic_routing"] = bool(
            source.get("treatment_includes_semantic_routing")
        )
        for context in source.get("contexts", []):
            if isinstance(context, dict):
                value["contexts"].append({
                    "phase_id": context.get("phase_id"),
                    "phase_name": context.get("phase_name"),
                    "deterministic_control": context.get("deterministic_control"),
                    "counterfactual_candidate": context.get("counterfactual_candidate"),
                    "applied": context.get("applied"),
                    "decision_timing": context.get("decision_timing"),
                })
    write_json(destination, value)
    return value


def number(value: Any, digits: int = 3) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "n/a"
    if digits == 0:
        return f"{int(value):,}"
    return f"{float(value):,.{digits}f}"


def metric_delta(control: dict[str, Any], candidate: dict[str, Any], key: str):
    left = control.get(key)
    right = candidate.get(key)
    if (
        isinstance(left, (int, float)) and not isinstance(left, bool)
        and isinstance(right, (int, float)) and not isinstance(right, bool)
    ):
        return round(float(right) - float(left), 6)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a sanitized BM5 publication tree for benchmark-results."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--private-archive", type=Path)
    args = parser.parse_args()

    plan_path = args.plan.expanduser().resolve()
    root = args.root.expanduser().resolve()
    destination = args.destination.expanduser().resolve()
    plan = load(plan_path)
    run_dir = Path(plan["coordinator"]["run_dir"]).resolve()
    suite = Path(plan["coordinator"]["suite_dir"]).resolve()
    report = load(run_dir / "report.json")
    run_state = load(run_dir / "run.json")

    if len(plan.get("pairs", [])) != 1:
        raise SystemExit(
            "current BM5 public projection expects the development n=1 study"
        )

    destination.mkdir(parents=True, exist_ok=True)
    generated_entries = (
        "README.md",
        "result.json",
        "PUBLICATION-MANIFEST.json",
        "task",
        "structured-direct",
        "agent-workflow-slimmed",
        "analysis",
        "evidence",
        "methodology",
    )
    for name in generated_entries:
        target = destination / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    pair = plan["pairs"][0]
    pair_state, attempt = selected_attempt(plan, run_dir, pair)

    task = destination / "task"
    for name in (
        "benchmark-spec.json", "canonical-task.md",
        "scoring-contract.json", "product-scoring-contract.json", "visual-rubric.json",
    ):
        copy_file(suite / name, task / name)
    for name in ("phases", "profiles"):
        copy_tree(suite / name, task / name)
    spec = load(suite / "benchmark-spec.json")
    runtime_lock = str(
        spec.get("visual", {}).get(
            "runtime_lock_path", "visual-runtime-lock.effective.json"
        )
    )
    copy_file(suite / runtime_lock, task / "visual-runtime-lock.json")
    copy_tree(root / "fixture", task / "starting-fixture")

    public_arms = {}
    for arm_name in ("control_raw", "workflow_full"):
        arm_plan = attempt["arms"][arm_name]
        stage = Path(arm_plan["stage_dir"]).resolve()
        worktree = Path(arm_plan["worktree"]).resolve()
        arm = load(stage / "arm.json")
        score = load(stage / "score.json")
        product_path = stage / "product-score.json"
        product_score = load(product_path) if product_path.is_file() else None
        usage = arm.get("usage") or {}
        timing = timing_summary(arm)
        public_name = PUBLIC_ARMS[arm_name]
        arm_root = destination / public_name

        copy_tree(worktree, arm_root / "final-project")
        write_json(arm_root / "score.json", score)
        if product_score is not None:
            write_json(arm_root / "product-score.json", product_score)
        write_json(arm_root / "timing.json", timing)
        write_json(arm_root / "usage.json", usage)
        sanitize_visual(stage, arm_root / "visual")

        treatment = (plan.get("treatments") or {}).get(arm_name, {})
        public_arms[public_name] = {
            "arm": arm_name,
            "treatment_id": treatment.get("treatment_id"),
            "runner_kind": treatment.get("runner_kind"),
            "machine_score": score.get("machine_score"),
            "product_score": product_score.get("score") if product_score else None,
            "product_score_id": product_score.get("id") if product_score else None,
            "eligibility": (score.get("eligibility") or {}).get("state"),
            "provider_total_tokens": usage.get("provider_total_tokens"),
            "input_tokens": usage.get("input_tokens"),
            "cached_input_tokens": usage.get("cached_input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "reasoning_output_tokens": usage.get("reasoning_output_tokens"),
            "wall_seconds": timing["phase_wall_seconds"],
            "executor_active_seconds": timing["executor_active_seconds"],
            "host_overhead_seconds": timing["host_overhead_seconds"],
            "amplification": timing["amplification"],
            "protocol": timing["protocol"],
            "final_project_path": f"{public_name}/final-project",
            "visual_path": f"{public_name}/visual",
        }

    control = public_arms["structured-direct"]
    candidate = public_arms["agent-workflow-slimmed"]
    metric_keys = (
        "machine_score", "product_score", "provider_total_tokens", "input_tokens",
        "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
        "wall_seconds", "executor_active_seconds", "host_overhead_seconds",
    )
    deltas = {
        key: metric_delta(control, candidate, key) for key in metric_keys
    }

    evidence = destination / "evidence"
    evidence.mkdir(parents=True)
    typesafe = sanitize_typesafe(
        root, evidence / "typesafe-qualification-summary.json"
    )

    substitution_candidates = sorted(root.rglob("harness-substitution.json"))
    visual_correction = False
    if substitution_candidates:
        source = load(substitution_candidates[-1])
        write_json(
            evidence / "visual-harness-correction.json",
            {
                "schema": source.get("schema"),
                "run_id": source.get("run_id"),
                "benchmark_id": source.get("benchmark_id"),
                "claim_level": source.get("claim_level"),
                "scope": source.get("scope"),
                "reason": source.get("reason"),
                "frozen_evaluator_sha256": source.get("frozen_evaluator_sha256"),
                "replacement_evaluator_sha256": source.get("replacement_evaluator_sha256"),
                "model_execution_modified": source.get("model_execution_modified"),
            },
        )
        visual_correction = True

    private_receipts = {}
    for name in (
        "run-plan.json",
        "machine-scores.json",
        "consolidation-receipt.json",
        "report.json",
        "report.md",
        "environment.json",
        "experiment-manifest.json",
        "operating-policy.json",
    ):
        source = run_dir / name
        if source.is_file():
            private_receipts[name] = {
                "sha256": sha256(source),
                "published_raw": False,
            }
    write_json(
        evidence / "private-receipt-hashes.json",
        {
            "schema": "agent-workflow/bm5-private-receipt-hashes/v1",
            "run_id": plan.get("run_id"),
            "receipts": private_receipts,
        },
    )

    private_archive = (
        args.private_archive.expanduser().resolve()
        if args.private_archive is not None else None
    )
    result = {
        "schema": "agent-workflow/public-benchmark-result/v1",
        "study_id": "bm5",
        "benchmark_id": plan.get("benchmark_id"),
        "benchmark_version": plan.get("benchmark_version"),
        "run_id": plan.get("run_id"),
        "claim_level": plan.get("claim_level"),
        "status": report.get("state") or run_state.get("state"),
        "execution_state": run_state.get("state"),
        "repetitions": len(plan.get("pairs", [])),
        "eligible_pairs": report.get("eligible_pairs"),
        "human_complete_pairs": report.get("human_complete_pairs"),
        "winner": report.get("winner"),
        "treatments": public_arms,
        "deltas_candidate_minus_control": deltas,
        "pair": {
            "case_id": pair.get("case_id"),
            "pair_id": pair.get("pair_id"),
            "selected_attempt": pair_state.get("selected_attempt"),
            "pair_start_skew_seconds": pair_state.get("pair_start_skew_seconds"),
        },
        "identity": plan.get("identities"),
        "private_evidence": {
            "raw_archive_sha256": (
                sha256(private_archive)
                if private_archive is not None and private_archive.is_file()
                else None
            ),
            "raw_archive_published": False,
            "raw_typesafe_audit_published": False,
            "typesafe_audit_sha256": typesafe.get("raw_audit_sha256"),
        },
        "visual_harness_correction": visual_correction,
        "limitations": [
            "Single paired development run (n=1); descriptive only.",
            "Human visual review may remain incomplete; no generalized winner claim is made.",
            "Development visual-runtime verification is not publication-runtime verification.",
            "Raw TypeSafe API audit records and the complete evidence archive are retained privately.",
        ],
    }
    write_json(destination / "result.json", result)
    write_json(
        destination / "methodology" / "environment.json",
        public_environment(plan),
    )

    methodology = (
        "# BM5 treatment definition\n\n"
        "BM5 compares the same structured task, phase prompts, fixture, model, "
        "reasoning effort, and paired schedule under two execution treatments.\n\n"
        f"- Control: {control.get('treatment_id')} via {control.get('runner_kind')}.\n"
        f"- Candidate: {candidate.get('treatment_id')} via {candidate.get('runner_kind')}.\n\n"
        "The candidate adds the Agent-Workflow lifecycle plus OPT-001 through "
        "OPT-015 context/execution optimizations. This n=1 development result "
        "is descriptive rather than a generalized treatment-effect claim.\n"
    )
    (destination / "methodology").mkdir(parents=True, exist_ok=True)
    (destination / "methodology" / "treatment-definition.md").write_text(
        methodology, encoding="utf-8"
    )

    rows = [
        ("Machine score", "machine_score", 1),
        ("Supplementary product score", "product_score", 1),
        ("Task wall time (s)", "wall_seconds", 3),
        ("Executor active (s)", "executor_active_seconds", 3),
        ("Measured host overhead (s)", "host_overhead_seconds", 3),
        ("Provider tokens", "provider_total_tokens", 0),
        ("Input tokens", "input_tokens", 0),
        ("Cached input tokens", "cached_input_tokens", 0),
        ("Output tokens", "output_tokens", 0),
        ("Reasoning output tokens", "reasoning_output_tokens", 0),
    ]
    table = [
        "| Metric | Structured direct | Agent-Workflow slimmed | Candidate delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, key, digits in rows:
        table.append(
            f"| {label} | {number(control.get(key), digits)} | "
            f"{number(candidate.get(key), digits)} | "
            f"{number(deltas.get(key), digits)} |"
        )

    (destination / "analysis").mkdir(parents=True, exist_ok=True)
    comparison = [
        "# BM5 comparison analysis", "",
        "BM5 is the post-optimization development study comparing structured direct execution with the steering-first Agent-Workflow treatment.",
        "", *table, "",
        "## Amplification telemetry", "",
        "Per-arm timing.json files preserve available model-turn, tool-call, command-execution, launch-prompt, and injected-context diagnostics.",
        "", "## Visual evidence", "",
        "Per-arm visual directories contain the sanitized assessment plus desktop, tablet, and mobile screenshots. Application failures are scored as solution failures rather than benchmark harness failures.",
        "", "## Interpretation boundary", "",
        "This is a single paired development run. Treat the measurements as descriptive evidence for the optimization loop, not as a generalized winner claim.",
    ]
    (destination / "analysis" / "comparison.md").write_text(
        "\n".join(comparison) + "\n", encoding="utf-8"
    )

    readme = [
        "# BM5 — Structured Direct vs Agent-Workflow Slimmed", "",
        "**Status: development benchmark finalized; human visual review may remain pending.**",
        "",
        "BM5 measures the same structured Priority Picker task after Agent-Workflow OPT-001 through OPT-015 context/execution optimizations.",
        "", "## Result at a glance", "", *table, "",
        "## Published artifacts", "",
        "- task/ — canonical task, prompts, official and supplementary scoring contracts, visual contract, runtime lock, and starting fixture;",
        "- structured-direct/ — control final project, score, timing, usage, and visual evidence;",
        "- agent-workflow-slimmed/ — candidate final project, score, timing, usage, and visual evidence;",
        "- analysis/comparison.md — descriptive comparison;",
        "- evidence/ — sanitized TypeSafe summary, benchmark receipts, and visual-harness correction provenance when applicable;",
        "- methodology/ — environment and treatment definition.",
        "",
        "Raw TypeSafe audit records and the full evidence archive are intentionally not published. Their hashes are recorded in result.json.",
    ]
    (destination / "README.md").write_text(
        "\n".join(readme) + "\n", encoding="utf-8"
    )

    print(f"BM5 publication tree: {destination}")
    print(f"result: {destination / 'result.json'}")
    print(f"comparison: {destination / 'analysis' / 'comparison.md'}")


if __name__ == "__main__":
    main()

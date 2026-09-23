"""Dispatch for the ``agent-workflow benchmark`` command domain."""

from __future__ import annotations

import argparse
from typing import Any

from .benchmarking import (
    attest_benchmark_runtime,
    benchmark_readiness,
    check_benchmark_auth,
    cleanup_benchmark,
    consolidate_benchmark,
    create_fixture as create_benchmark_fixture,
    create_plan as create_benchmark_plan,
    export_builtin_suite as export_benchmark_suite,
    export_bm4_optimized_suite,
    export_value_smoke_suite,
    export_structured_value_smoke_suite,
    prepare_or_submit_review as benchmark_review,
    prepare_target as prepare_benchmark_target,
    render_benchmark_report as render_comparative_benchmark_report,
    resume_benchmark,
    run_benchmark,
    score_benchmark,
    seal_benchmark_runtime,
    status_benchmark,
    start_live_benchmark,
    stop_live_benchmark,
    validate_benchmark as validate_comparative_benchmark,
    verify_benchmark,
    visual_capture_benchmark,
)
from .benchmarking.code_review import quality_review
from agent_workflow.config import Settings
from agent_workflow.errors import WorkflowError


def handle_benchmark_command(
    settings: Settings,
    args: argparse.Namespace,
) -> Any:
    """Dispatch one parsed comparative-benchmark command."""
    command = args.benchmark_command
    if command == "validate":
        return validate_comparative_benchmark(args.spec, args.executor)
    if command == "auth-check":
        return check_benchmark_auth(args.executor)
    if command == "readiness":
        return benchmark_readiness(
            args.spec,
            args.executor,
            policy=args.policy,
            runtime_lock=args.runtime_lock,
            settings=settings,
            execution_only=bool(getattr(args, "execution_only", False)),
        )
    if command == "runtime-attest":
        return attest_benchmark_runtime(args.runtime_lock, claim_level=args.claim_level)
    if command == "runtime-seal":
        return seal_benchmark_runtime(
            args.base_lock,
            args.output,
            container_image=args.container_image,
        )
    if command == "suite-export":
        return export_benchmark_suite(
            args.destination,
            benchmark_id=args.benchmark_id,
            force=args.force,
        )
    if command == "value-smoke-export":
        return export_value_smoke_suite(
            args.destination,
            force=args.force,
            agent_class=args.agent_class,
        )
    if command == "structured-value-smoke-export":
        return export_structured_value_smoke_suite(
            args.destination,
            force=args.force,
            agent_class=args.agent_class,
        )
    if command == "bm4-export":
        return export_bm4_optimized_suite(
            args.destination,
            force=args.force,
            agent_class=args.agent_class,
        )
    if command == "code-review":
        return quality_review(
            settings,
            args.left,
            args.right,
            args.output,
            requirements_path=args.requirements,
            model=args.model,
        )
    if command == "fixture-create":
        return create_benchmark_fixture(
            args.spec,
            args.destination,
            force=args.force,
        )
    if command == "target-prepare":
        return prepare_benchmark_target(args.manifest, args.destination)
    if command == "plan":
        return create_benchmark_plan(
            settings,
            spec=args.spec,
            executor=args.executor,
            repo=args.repo,
            base_ref=args.base_ref,
            run_id=args.run_id,
            repetitions=args.repetitions,
            worktree_root=args.worktree_root,
            allow_dirty=args.allow_dirty,
            assistance_cohort=args.assistance_cohort,
            policy=args.policy,
            runtime_lock=args.runtime_lock,
            codebase_memory_mode=args.codebase_memory_mode,
        )
    if command == "run":
        return run_benchmark(
            settings,
            args.run,
            execution_only=bool(getattr(args, "execution_only", False)),
        )
    if command == "resume":
        return resume_benchmark(settings, args.run)
    if command == "status":
        return status_benchmark(settings, args.run)
    if command == "live-start":
        return start_live_benchmark(settings, args.run)
    if command == "live-stop":
        return stop_live_benchmark(settings, args.run)
    if command == "visual-capture":
        return visual_capture_benchmark(settings, args.run)
    if command == "score":
        return score_benchmark(settings, args.run)
    if command == "consolidate":
        return consolidate_benchmark(settings, args.run)
    if command == "review":
        return benchmark_review(
            settings,
            args.run,
            reviewer=args.reviewer,
            input_path=args.input,
        )
    if command == "report":
        return render_comparative_benchmark_report(settings, args.run)
    if command == "verify":
        return verify_benchmark(settings, args.run)
    if command == "cleanup":
        kwargs = {"remove_worktrees": args.remove_worktrees}
        if bool(getattr(args, "stop_live_apps", False)):
            kwargs["stop_live_apps"] = True
        return cleanup_benchmark(settings, args.run, **kwargs)
    raise WorkflowError(f"unhandled benchmark command: {command}")

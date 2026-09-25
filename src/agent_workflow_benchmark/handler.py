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
    export_bm5_slimmed_suite,
    export_bm6_blind_suite,
    export_value_smoke_suite,
    export_structured_value_smoke_suite,
    prepare_or_submit_review as benchmark_review,
    prepare_target as prepare_benchmark_target,
    render_benchmark_report as render_comparative_benchmark_report,
    resume_benchmark,
    run_benchmark,
    score_benchmark,
    seal_benchmark_execution,
    verify_benchmark_execution_seal,
    seal_benchmark_runtime,
    status_benchmark,
    start_live_benchmark,
    stop_live_benchmark,
    validate_benchmark as validate_comparative_benchmark,
    verify_benchmark,
    visual_capture_benchmark,
)
from .benchmarking.code_review import quality_review
from .benchmarking.decision_study import (
    prepare_decision_study_publication,
    report_decision_study,
    run_decision_study,
    validate_decision_study,
)
from .benchmarking.scoring_bundle_tools import initialize_scoring_bundle, validate_scoring_bundle
from agent_workflow.config import Settings
from agent_workflow.errors import WorkflowError


def handle_benchmark_command(
    settings: Settings,
    args: argparse.Namespace,
) -> Any:
    """Dispatch one parsed comparative-benchmark command."""
    command = args.benchmark_command
    if command == "decision-study-validate":
        return validate_decision_study(
            args.corpus,
            study=args.study,
            oracle_path=args.oracle,
        )
    if command == "decision-study-run":
        return run_decision_study(
            settings,
            args.corpus,
            args.output,
            study=args.study,
            force=args.force,
        )
    if command == "decision-study-report":
        return report_decision_study(args.run, args.oracle)
    if command == "decision-study-publish-prepare":
        return prepare_decision_study_publication(
            args.run,
            args.oracle,
            args.destination,
            force=args.force,
        )
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
    if command == "seal":
        return seal_benchmark_execution(settings, args.run)
    if command == "seal-verify":
        return verify_benchmark_execution_seal(settings, args.run)
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
    if command == "bm5-export":
        return export_bm5_slimmed_suite(
            args.destination,
            force=args.force,
            agent_class=args.agent_class,
        )
    if command == "bm6-export":
        return export_bm6_blind_suite(
            args.destination,
            force=args.force,
            agent_class=args.agent_class,
        )
    if command == "scoring-bundle-init":
        return initialize_scoring_bundle(args.destination, force=args.force)
    if command == "scoring-bundle-validate":
        return validate_scoring_bundle(args.bundle)
    if command == "code-review":
        return quality_review(
            settings,
            args.left,
            args.right,
            args.output,
            requirements_path=args.requirements,
            base_review_path=args.base_review,
            context_scope=args.context_scope,
            candidate_order=args.candidate_order,
            question_set=args.question_set,
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
        return score_benchmark(
            settings,
            args.run,
            scoring_bundle=getattr(args, "scoring_bundle", None),
        )
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

"""Paired comparative benchmark services.

The package intentionally depends on small core ports (contracts, process, Git
worktrees, and atomic writers) so it can later move behind the trusted plugin
boundary without changing its public contracts.
"""

from .contracts import (
    BENCHMARK_EXECUTOR_SCHEMA,
    BENCHMARK_SPEC_SCHEMA,
    BENCHMARK_OPERATING_POLICY_SCHEMA,
    validate_executor_config,
    validate_spec,
)
from .service import (
    attest_benchmark_runtime,
    benchmark_readiness,
    check_benchmark_auth,
    cleanup_benchmark,
    consolidate_benchmark,
    create_fixture,
    create_plan,
    export_builtin_suite,
    prepare_or_submit_review,
    render_benchmark_report,
    resume_benchmark,
    run_benchmark,
    score_benchmark,
    seal_benchmark_runtime,
    status_benchmark,
    start_live_benchmark,
    stop_live_benchmark,
    validate_benchmark,
    verify_benchmark,
    visual_capture_benchmark,
)
from .targets import prepare_target

__all__ = [
    "BENCHMARK_EXECUTOR_SCHEMA",
    "BENCHMARK_SPEC_SCHEMA",
    "BENCHMARK_OPERATING_POLICY_SCHEMA",
    "attest_benchmark_runtime",
    "benchmark_readiness",
    "check_benchmark_auth",
    "cleanup_benchmark",
    "consolidate_benchmark",
    "create_fixture",
    "create_plan",
    "export_builtin_suite",
    "prepare_or_submit_review",
    "render_benchmark_report",
    "resume_benchmark",
    "run_benchmark",
    "score_benchmark",
    "seal_benchmark_runtime",
    "status_benchmark",
    "start_live_benchmark",
    "stop_live_benchmark",
    "validate_benchmark",
    "validate_executor_config",
    "validate_spec",
    "verify_benchmark",
    "visual_capture_benchmark",
    "prepare_target",
]

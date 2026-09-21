from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Mapping

from agent_workflow.config import Settings
from agent_workflow.errors import WorkflowError

AGENT_WORKFLOW_EXECUTOR_ALIASES = {
    "codex-cli": "codex",
    "claude-code-cli": "claude",
}


def agent_workflow_executor_name(benchmark_executor: str) -> str:
    return AGENT_WORKFLOW_EXECUTOR_ALIASES.get(benchmark_executor, benchmark_executor)


def _binary_name(argv: object) -> str | None:
    if not isinstance(argv, (list, tuple)) or not argv:
        return None
    first = argv[0]
    return Path(str(first)).name if first is not None else None


def uses_agent_workflow(spec: Mapping[str, Any]) -> bool:
    arms = spec.get("arms")
    return isinstance(arms, Mapping) and any(
        isinstance(profile, Mapping)
        and isinstance(profile.get("runner"), Mapping)
        and profile["runner"].get("kind") == "agent-workflow"
        for profile in arms.values()
    )


def treatment_runtime_checks(
    settings: Settings,
    spec: Mapping[str, Any],
    executor: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return comparability checks for v3 Agent-Workflow treatments.

    These checks establish that the runtime treatment resolves to the same
    provider executable/model family as the direct benchmark executor. They do
    not require a provider call and therefore belong in readiness/planning.
    """
    if not uses_agent_workflow(spec):
        return []

    benchmark_executor = str(executor["executor"])
    aw_executor = agent_workflow_executor_name(benchmark_executor)
    benchmark_binary = _binary_name(executor.get("argv_template"))
    aw_argv = settings.executors.get(aw_executor)
    aw_binary = _binary_name(aw_argv)
    model = str(executor["model"])
    effort = executor.get("effort")
    provider = str(executor.get("provider") or "")

    checks: list[dict[str, Any]] = []

    checks.append({
        "id": "agent-workflow-executor-binding",
        "passed": aw_argv is not None,
        "detail": (
            f"benchmark_executor={benchmark_executor}; "
            f"agent_workflow_executor={aw_executor}; configured={aw_argv is not None}"
        ),
    })
    if aw_argv is None:
        return checks

    expected_provider = {"codex": "openai", "claude": "anthropic"}.get(aw_executor)
    checks.append({
        "id": "agent-workflow-provider-family",
        "passed": expected_provider is None or provider == expected_provider,
        "detail": (
            f"benchmark_provider={provider}; agent_workflow_executor={aw_executor}; "
            f"expected_provider={expected_provider or 'custom'}"
        ),
    })
    checks.append({
        "id": "agent-workflow-executable",
        "passed": benchmark_binary is not None and benchmark_binary == aw_binary,
        "detail": (
            f"benchmark_binary={benchmark_binary or 'missing'}; "
            f"agent_workflow_binary={aw_binary or 'missing'}"
        ),
    })

    policy = settings.executor_policies.get(aw_executor)
    policy_models = tuple(policy.models) if policy is not None else ()
    model_allowed = not policy_models or model in policy_models
    no_go = bool(
        policy is not None
        and any(fnmatch.fnmatchcase(model, pattern) for pattern in policy.no_go_models)
    )
    checks.append({
        "id": "agent-workflow-model",
        "passed": model_allowed and not no_go,
        "detail": (
            f"model={model}; allowed={model_allowed}; no_go={no_go}; "
            f"configured_models={list(policy_models)}"
        ),
    })

    if aw_executor == "codex":
        effort_ok = effort in {"low", "medium", "high"}
    else:
        effort_ok = effort in {None, "default"}
    checks.append({
        "id": "agent-workflow-effort",
        "passed": effort_ok,
        "detail": f"executor={aw_executor}; benchmark_effort={effort!r}",
    })

    for role, profile in spec.get("arms", {}).items():
        if not isinstance(profile, Mapping):
            continue
        runner = profile.get("runner")
        if not isinstance(runner, Mapping) or runner.get("kind") != "agent-workflow":
            continue
        agent_class = runner.get("agent_class")
        class_policy = (
            settings.agent_classes.get(str(agent_class))
            if isinstance(agent_class, str) and agent_class
            else None
        )
        class_allowed = (
            class_policy.allowed_models.get(aw_executor, ())
            if class_policy is not None
            else ()
        )
        class_model_ok = class_policy is not None and (
            not class_allowed or model in class_allowed
        )
        checks.append({
            "id": f"agent-workflow-agent-class:{role}",
            "passed": class_policy is not None and class_model_ok,
            "detail": (
                f"role={role}; agent_class={agent_class!r}; "
                f"configured={class_policy is not None}; model={model}; "
                f"allowed_models={list(class_allowed)}"
            ),
        })

    return checks


def require_treatment_runtime_compatibility(
    settings: Settings,
    spec: Mapping[str, Any],
    executor: Mapping[str, Any],
) -> list[dict[str, Any]]:
    checks = treatment_runtime_checks(settings, spec, executor)
    failed = [item for item in checks if not bool(item["passed"])]
    if failed:
        details = "; ".join(f"{item['id']}: {item['detail']}" for item in failed)
        raise WorkflowError(f"benchmark treatment runtime is not comparable: {details}")
    return checks

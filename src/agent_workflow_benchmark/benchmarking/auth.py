from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.process import EnvironmentPolicy, run
from agent_workflow.util import utc_now

SUBSCRIPTION_MODE = "subscription-session"
SYNTHETIC_MODE = "synthetic-none"
FORBIDDEN_API_MODE = "forbidden-api-credential"

_SUPPORTED_SUBSCRIPTION_EXECUTORS = {
    ("openai", "codex-cli"),
    ("anthropic", "claude-code-cli"),
}


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _classify_status(provider: str, output: str) -> str | None:
    lowered = output.lower()
    if provider == "openai":
        if "chatgpt" in lowered or "oauth" in lowered:
            return SUBSCRIPTION_MODE
        if "api key" in lowered or "api-key" in lowered or "access token" in lowered:
            return FORBIDDEN_API_MODE
    if provider == "anthropic":
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            value = None
        flattened = lowered
        if isinstance(value, dict):
            flattened = json.dumps(value, sort_keys=True).lower()
        if "claude.ai" in flattened or re.search(
            r"\b(subscription|oauth|pro|max|team|enterprise)\b", flattened
        ):
            return SUBSCRIPTION_MODE
        if "anthropic_api_key" in flattened or "anthropic_auth_token" in flattened or re.search(
            r"\b(api|console|api[-_ ]?key|access[-_ ]?token)\b", flattened
        ):
            return FORBIDDEN_API_MODE
    return None


def validate_authentication_config(executor: Mapping[str, Any]) -> None:
    authentication = executor.get("authentication")
    if not isinstance(authentication, Mapping):
        raise WorkflowError("benchmark executor requires an authentication policy")
    mode = authentication.get("mode")
    if mode not in {SUBSCRIPTION_MODE, SYNTHETIC_MODE}:
        raise WorkflowError(
            f"unsupported benchmark authentication mode: {mode!r}; "
            "0.9 supports Codex/Claude subscription sessions only"
        )
    credential_environment = authentication.get("credential_environment", [])
    if not isinstance(credential_environment, list) or not all(
        isinstance(item, str) and item for item in credential_environment
    ):
        raise WorkflowError("authentication credential_environment must be a string list")

    provider = str(executor.get("provider") or "")
    executor_name = str(executor.get("executor") or "")
    if mode == SYNTHETIC_MODE:
        if provider != "synthetic":
            raise WorkflowError("synthetic-none authentication is reserved for the synthetic test executor")
        return

    if (provider, executor_name) not in _SUPPORTED_SUBSCRIPTION_EXECUTORS:
        raise WorkflowError(
            "supported subscription benchmark executors are openai/codex-cli and "
            "anthropic/claude-code-cli"
        )
    if not credential_environment:
        raise WorkflowError(
            "subscription-session authentication must list provider API credential environment "
            "variables so ambient API billing can be rejected"
        )


def preflight_authentication(executor: Mapping[str, Any]) -> dict[str, Any]:
    validate_authentication_config(executor)
    authentication = dict(executor["authentication"])
    mode = str(authentication["mode"])
    provider = str(executor["provider"])
    credential_names = [str(item) for item in authentication.get("credential_environment", [])]
    present = sorted(name for name in credential_names if os.environ.get(name))

    if mode == SYNTHETIC_MODE:
        return {
            "checked_at": utc_now(),
            "requested_mode": mode,
            "observed_mode": mode,
            "authenticated": True,
            "credential_environment_present": [],
            "status_command": None,
            "status_output_sha256": None,
            "status_returncode": 0,
            "detail": "synthetic executor requires no external authentication",
        }

    if present:
        return {
            "checked_at": utc_now(),
            "requested_mode": mode,
            "observed_mode": FORBIDDEN_API_MODE,
            "authenticated": False,
            "credential_environment_present": present,
            "status_command": [str(item) for item in authentication.get("status_argv", [])],
            "status_output_sha256": None,
            "status_returncode": None,
            "detail": (
                "subscription benchmark refused because an API credential environment variable is present: "
                + ", ".join(present)
            ),
        }

    status_argv = authentication.get("status_argv")
    if not isinstance(status_argv, list) or not status_argv:
        raise WorkflowError("subscription-session authentication requires status_argv")
    result = run(
        [str(item) for item in status_argv],
        check=False,
        timeout_seconds=float(authentication.get("status_timeout_seconds", 30)),
        max_stdout_bytes=256 * 1024,
        max_stderr_bytes=256 * 1024,
        environment=EnvironmentPolicy(
            allowlist=tuple(str(item) for item in executor.get("environment_allowlist", [])),
            values={},
            unsafe_inherit=False,
        ),
        probe_version=True,
        digest_executable=True,
    )
    output = "\n".join((str(result.stdout), str(result.stderr))).strip()
    observed = _classify_status(provider, output)
    authenticated = result.returncode == 0 and observed == SUBSCRIPTION_MODE
    return {
        "checked_at": utc_now(),
        "requested_mode": mode,
        "observed_mode": observed,
        "authenticated": authenticated,
        "credential_environment_present": present,
        "status_command": list(result.argv),
        "status_output_sha256": _digest_text(output),
        "status_returncode": result.returncode,
        "status_process": result.as_dict(include_output=False),
        "detail": (
            "authenticated subscription session confirmed"
            if authenticated
            else "subscription session was not confirmed; run the Codex or Claude CLI login flow before benchmarking"
        ),
    }


def require_authentication(executor: Mapping[str, Any]) -> dict[str, Any]:
    evidence = preflight_authentication(executor)
    if not evidence["authenticated"]:
        raise WorkflowError(str(evidence["detail"]))
    return evidence

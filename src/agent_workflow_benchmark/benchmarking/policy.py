from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .schema_contracts import read_contract
from agent_workflow.errors import WorkflowError

BENCHMARK_OPERATING_POLICY_SCHEMA = "agent-workflow/benchmark-operating-policy/v1"


def load_operating_policy(path: Path) -> dict[str, Any]:
    return read_contract(path.expanduser().resolve(), BENCHMARK_OPERATING_POLICY_SCHEMA)


def implicit_operating_policy(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Represent legacy/base-spec settings as a sealed development policy."""
    return {
        "schema": BENCHMARK_OPERATING_POLICY_SCHEMA,
        "policy_id": "spec-default/v1",
        "claim_level": str(spec["claim_level"]),
        "repetitions": int(spec["scheduling"]["default_repetitions"]),
        "infrastructure_retries": int(spec["scheduling"]["infrastructure_retries"]),
        "assistance_cohort": "unassisted",
        "cache_policy": {
            "mode": "provider-managed-recorded",
            "mixing_prohibited": True,
            "record_cached_tokens": True,
        },
        "retry_policy": {
            "classification": "infrastructure-only",
            "fresh_pair_worktrees": True,
            "retain_all_attempts": True,
        },
        "interrupted_pair_policy": "discard-pair-and-retry-fresh",
        "authentication_default": "subscription-session",
        "allowed_authentication_modes": (
            ["subscription-session", "synthetic-none"]
            if str(spec["claim_level"]) == "development"
            else ["subscription-session"]
        ),
        "winner_policy": deepcopy(spec["winner_policy"]),
    }


def apply_operating_policy(
    spec: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    authentication_mode: str,
) -> dict[str, Any]:
    allowed = {str(item) for item in policy["allowed_authentication_modes"]}
    if authentication_mode not in allowed:
        raise WorkflowError(
            f"authentication mode {authentication_mode!r} is not allowed by operating policy "
            f"{policy['policy_id']!r}"
        )
    value = deepcopy(dict(spec))
    value["claim_level"] = str(policy["claim_level"])
    value["scheduling"]["default_repetitions"] = int(policy["repetitions"])
    value["scheduling"]["infrastructure_retries"] = int(
        policy["infrastructure_retries"]
    )
    value["winner_policy"] = deepcopy(dict(policy["winner_policy"]))
    return value

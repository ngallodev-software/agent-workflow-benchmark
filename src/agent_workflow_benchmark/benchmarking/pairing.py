from __future__ import annotations

from typing import Any, Mapping

from agent_workflow.errors import WorkflowError


def attempts_for(pair: Mapping[str, Any]) -> list[dict[str, Any]]:
    attempts = pair.get("attempts")
    if isinstance(attempts, list) and attempts:
        return [dict(item) for item in attempts]
    return [
        {
            "attempt": 1,
            "attempt_id": f"{pair['pair_id']}-a01",
            "pair_nonce": pair["pair_nonce"],
            "slot_order": pair["slot_order"],
            "arms": pair["arms"],
        }
    ]


def attempt_for(pair: Mapping[str, Any], number: int) -> dict[str, Any]:
    for attempt in attempts_for(pair):
        if int(attempt["attempt"]) == int(number):
            return attempt
    raise WorkflowError(f"pair {pair['pair_id']} has no attempt {number}")


def selected_attempt(pair: Mapping[str, Any], pair_state: Mapping[str, Any]) -> dict[str, Any]:
    number = int(pair_state.get("selected_attempt", 1))
    return attempt_for(pair, number)


def selected_arms(pair: Mapping[str, Any], pair_state: Mapping[str, Any]) -> dict[str, Any]:
    return dict(selected_attempt(pair, pair_state)["arms"])

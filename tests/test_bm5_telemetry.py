from __future__ import annotations

import json
from pathlib import Path

from agent_workflow_benchmark.benchmarking.runner import _executor_context_diagnostics


def test_executor_context_diagnostics_surfaces_bm5_protocol_attribution(tmp_path: Path) -> None:
    value = {
        "context_id": "ctx-test",
        "projection_sha256": "a" * 64,
        "measurements": {
            "launch_prompt": {"bytes": 100, "estimated_tokens": 25},
            "injected_context": {"bytes": 40, "estimated_tokens": 10},
            "command_card": {"bytes": 20},
        },
        "runtime": {
            "model_turn_count": 1,
            "tool_call_count": 4,
            "command_execution_count": 3,
            "tool_call_types": {"command_execution": 3, "function_call": 1},
            "command_families": {
                "agent-workflow agent finish": 1,
                "git": 2,
            },
            "protocol_command_counts": {"finish": 1},
            "message_kind_counts": {"steer": 1, "ack": 1},
            "acceptance_command_executions": 2,
            "verification_cache_hits": 1,
            "verification_cache_misses": 1,
            "finish_invocations": 2,
            "finish_incomplete_invocations": 1,
            "finish_outcomes": {"completed": 1},
            "input_tokens_per_turn": 1000,
            "cached_input_tokens_per_turn": 900,
            "cached_input_ratio": 0.9,
        },
    }
    (tmp_path / "executor-context.json").write_text(
        json.dumps(value), encoding="utf-8"
    )

    result = _executor_context_diagnostics(tmp_path)
    assert result is not None
    assert result["protocol_command_counts"] == {"finish": 1}
    assert result["command_families"]["agent-workflow agent finish"] == 1
    assert result["message_kind_counts"] == {"steer": 1, "ack": 1}
    assert result["acceptance_command_executions"] == 2
    assert result["verification_cache_hits"] == 1
    assert result["verification_cache_misses"] == 1
    assert result["finish_invocations"] == 2
    assert result["finish_incomplete_invocations"] == 1
    assert result["finish_outcomes"] == {"completed": 1}

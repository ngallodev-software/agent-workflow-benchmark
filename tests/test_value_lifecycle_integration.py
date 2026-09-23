from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from agent_workflow.config import defaults

from agent_workflow_benchmark.benchmarking.common import read_object
from agent_workflow_benchmark.benchmarking.planning import (
    create_run_plan,
    materialize_fixture,
)
from agent_workflow_benchmark.benchmarking.service import export_value_smoke_suite, run_benchmark


FAKE_CODEX = r"""#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if "login" in sys.argv and "status" in sys.argv:
    print("Logged in with ChatGPT OAuth")
    raise SystemExit(0)
if "--version" in sys.argv:
    print("codex-cli 0.0.0-benchmark-test")
    raise SystemExit(0)
if "--help" in sys.argv:
    print("usage: codex [exec] [--json] [--model MODEL]")
    raise SystemExit(0)

if os.environ.get("AGENT_WORKFLOW_AGENT_RUN_ID"):
    _ = sys.stdin.read()
    handoff = Path(os.environ["AGENT_WORKFLOW_HANDOFF_DIR"])
    handoff.mkdir(parents=True, exist_ok=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    completion = {
        "schema": "agent-workflow/completion/v1",
        "agent_run_id": os.environ["AGENT_WORKFLOW_AGENT_RUN_ID"],
        "ticket_id": os.environ.get("AGENT_WORKFLOW_TICKET_ID"),
        "pack_id": os.environ.get("AGENT_WORKFLOW_PACK_ID"),
        "result": "completed",
        "base_revision": head,
        "head_revision": head,
        "changed_files": [],
        "criteria": [
            {
                "id": "fixture-executor-finished",
                "result": "pass",
                "evidence": ["deterministic benchmark Agent-Workflow executor completed"],
            }
        ],
        "commands": [
            {
                "argv": ["codex", "benchmark-test"],
                "cwd": str(Path.cwd()),
                "exit_code": 0,
                "receipt": "deterministic benchmark lifecycle evidence",
            }
        ],
        "unresolved": [],
        "usage": None,
    }
    (handoff / "completion.json").write_text(
        json.dumps(completion),
        encoding="utf-8",
    )
    print("deterministic Agent-Workflow executor completed")
    raise SystemExit(0)

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--direct-worktree", type=Path, required=True)
parser.add_argument("--direct-phase", required=True)
parser.add_argument("--direct-usage", type=Path, required=True)
args, _unknown = parser.parse_known_args()
_ = sys.stdin.read()
args.direct_usage.parent.mkdir(parents=True, exist_ok=True)
args.direct_usage.write_text(
    json.dumps(
        {
            "input_tokens": 10,
            "cached_input_tokens": 0,
            "cache_write_input_tokens": 0,
            "output_tokens": 5,
            "reasoning_output_tokens": 1,
            "provider_total_tokens": 15,
            "retry_count": 0,
            "provider_billed_cost": 0.001,
            "local_estimated_cost": 0.001,
            "currency": "USD",
            "price_catalog_id": "benchmark-test",
            "provider_elapsed_seconds": 0.01,
            "first_output_latency_seconds": 0.001,
        }
    ) + "\n",
    encoding="utf-8",
)
print(json.dumps({"phase": args.direct_phase, "state": "completed"}))
"""


def _write_fake_codex(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE_CODEX, encoding="utf-8")
    path.chmod(0o755)


def _write_fake_codex_executor(source: Path, destination: Path, fake_codex: Path) -> None:
    value = json.loads(source.read_text(encoding="utf-8"))
    value["executor_version"] = "0.0.0-benchmark-test"
    value["argv_template"] = [
        str(fake_codex),
        "--direct-worktree",
        "{worktree}",
        "--direct-phase",
        "{phase_id}",
        "--direct-usage",
        "{usage_file}",
    ]
    value["timeout_seconds"] = 20
    value["authentication"]["status_argv"] = [str(fake_codex), "login", "status"]
    value["authentication"]["status_timeout_seconds"] = 5
    destination.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_value_smoke_executes_real_agent_workflow_lifecycle(tmp_path: Path) -> None:
    fake_codex = tmp_path / "bin" / "codex"
    _write_fake_codex(fake_codex)

    suite = tmp_path / "suite"
    exported = export_value_smoke_suite(suite)
    spec = Path(exported["spec"])

    fixture = tmp_path / "fixture"
    materialize_fixture(spec, fixture)

    executor = tmp_path / "codex-synthetic.json"
    _write_fake_codex_executor(
        suite / "executors" / "codex-subscription.json",
        executor,
        fake_codex,
    )

    base = defaults(tmp_path / "config.toml")
    settings = replace(
        base,
        worktree_root=tmp_path / "worktrees",
        state_root=tmp_path / "state",
        require_clean_source=False,
        executors={**base.executors, "codex": [str(fake_codex)]},
    )

    planned = create_run_plan(
        settings,
        spec_path=spec,
        executor_path=executor,
        repo=fixture,
        base_ref="HEAD",
        repetitions=1,
        worktree_root=None,
        allow_dirty=False,
        assistance_cohort="unassisted",
        policy_path=suite / "policies" / "development.json",
        runtime_lock_path=None,
        codebase_memory_mode="none",
    )
    plan_path = Path(planned["run_plan"])
    plan = read_object(plan_path)
    assert all(item["passed"] for item in plan["treatment_runtime_checks"])

    coordinator = Path(plan["coordinator"]["worktree"])
    assert coordinator.name == "c"
    assert Path(plan["coordinator"]["run_dir"]) == coordinator / ".awb" / "run"
    pair = plan["pairs"][0]
    attempt = pair["attempts"][0]
    root = coordinator.parent
    for arm_name, short_name in (("control_raw", "c"), ("workflow_full", "w")):
        arm = attempt["arms"][arm_name]
        worktree = Path(arm["worktree"])
        assert worktree.relative_to(root).parts == ("p001", "a01", short_name)
        stage = Path(arm["stage_dir"])
        assert stage == worktree / ".awb"
        prompt_names = [Path(item["path"]).name for item in arm["prompts"]]
        assert prompt_names == ["01.md", "02.md", "03.md"]

    executed = run_benchmark(settings, plan_path, execution_only=True)
    assert executed["state"] == "executed"
    assert executed["pairs_terminal"] == 1
    assert executed["execution_only"] is True
    assert executed["execution_complete"] is True
    assert executed["benchmark_complete"] is False
    assert executed["score_eligible"] is False
    assert "visual-capture" in executed["pending_stages"]
    assert executed["report"] is None

    pair = plan["pairs"][0]
    pair_state_path = (
        Path(plan["coordinator"]["run_dir"])
        / "pair-state"
        / str(pair["case_id"])
        / f"r{int(pair['repetition']):02d}"
        / "pair.json"
    )
    pair_state = read_object(pair_state_path)
    candidate_path = Path(pair_state["arms"]["workflow_full"])
    candidate = read_object(candidate_path)
    assert candidate["state"] == "completed"
    assert candidate["phases"]
    assert all(phase["state"] == "completed" for phase in candidate["phases"])

    candidate_stage = Path(candidate["stage_dir"])
    for phase in candidate["phases"]:
        phase_dir = candidate_stage / "phases" / str(phase["phase_id"])
        aw_evidence = read_object(phase_dir / "agent-workflow-run.json")
        assert aw_evidence["status"] == "completed"
        assert aw_evidence["delegate_error"] is None
        metrics = phase_dir / "agent-workflow-execution-metrics.json"
        assert metrics.is_file()
        metrics_value = read_object(metrics)
        assert metrics_value["schema"] == "agent-workflow/execution-metrics/v1"
        assert any(item["stage"] == "total" for item in metrics_value["stages"])
        diagnostics = phase["timing_breakdown"]
        assert diagnostics["prompt_bytes"] > 0
        assert diagnostics["stdout_bytes"] >= 0
        assert "provider_evidence" in diagnostics

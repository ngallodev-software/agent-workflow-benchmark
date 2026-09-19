from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def copy_solution(source: Path, worktree: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        destination = worktree / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--usage", type=Path, required=True)
    args = parser.parse_args()
    arm = os.environ.get("AGENT_WORKFLOW_BENCHMARK_ARM", "control_raw")
    suite = Path(__file__).resolve().parent.parent
    started = time.monotonic()
    if args.phase == "analyze-plan":
        plan = args.worktree / "BENCHMARK_PLAN.md"
        if arm == "workflow_full":
            plan.write_text(
                "# Synthetic workflow plan\n\nTrace every requirement to priority.py, the labeled controls, responsive layouts, public tests, and README. Verify strict validation, scale, keyboard detail, export, and scope. Preserve data/backlog.json and add no dependencies.\n",
                encoding="utf-8",
            )
        else:
            plan.write_text(
                "# Synthetic control plan\n\nImplement scoring and a usable page, then run the public tests.\n",
                encoding="utf-8",
            )
    elif args.phase == "implement":
        source = suite / "executors" / "solutions" / ("workflow" if arm == "workflow_full" else "control")
        copy_solution(source, args.worktree)
    elif args.phase == "verify-repair":
        subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests/public", "-v"],
            cwd=args.worktree,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        print(f"unknown phase: {args.phase}", file=sys.stderr)
        return 2
    phase_factor = {"analyze-plan": 1, "implement": 3, "verify-repair": 2}.get(args.phase, 1)
    workflow_factor = 1.45 if arm == "workflow_full" else 1.0
    input_tokens = int(550 * phase_factor * workflow_factor)
    output_tokens = int(180 * phase_factor * workflow_factor)
    elapsed = round(time.monotonic() - started, 6)
    args.usage.parent.mkdir(parents=True, exist_ok=True)
    args.usage.write_text(
        json.dumps(
            {
                "input_tokens": input_tokens,
                "cached_input_tokens": 0,
                "cache_write_input_tokens": 0,
                "output_tokens": output_tokens,
                "reasoning_output_tokens": int(output_tokens * 0.25),
                "provider_total_tokens": input_tokens + output_tokens,
                "retry_count": 0,
                "provider_billed_cost": round((input_tokens * 0.000002) + (output_tokens * 0.000006), 8),
                "local_estimated_cost": round((input_tokens * 0.000002) + (output_tokens * 0.000006), 8),
                "currency": "USD",
                "price_catalog_id": "synthetic-fixed-v1",
                "provider_elapsed_seconds": elapsed,
                "first_output_latency_seconds": min(elapsed, 0.01)
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"phase": args.phase, "arm": arm, "state": "completed"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

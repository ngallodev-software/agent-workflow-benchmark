from __future__ import annotations

import argparse, json, os, shutil, subprocess, sys, time
from pathlib import Path

def copy_solution(source: Path, worktree: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative=path.relative_to(source); destination=worktree/relative
        if path.is_dir(): destination.mkdir(parents=True,exist_ok=True)
        else: destination.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,destination)

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--worktree",type=Path,required=True); parser.add_argument("--prompt",type=Path,required=True); parser.add_argument("--phase",required=True); parser.add_argument("--usage",type=Path,required=True); args=parser.parse_args()
    if args.phase != "build-verify": return 2
    arm=os.environ.get("AGENT_WORKFLOW_BENCHMARK_ARM","control_raw")
    suite=Path(__file__).resolve().parent.parent; started=time.monotonic()
    source=suite/"executors"/"solutions"/("workflow" if arm=="workflow_full" else "control")
    copy_solution(source,args.worktree)
    if not (args.worktree/"BENCHMARK_PLAN.md").is_file():
        (args.worktree/"BENCHMARK_PLAN.md").write_text("# Fast benchmark plan\n\nTrace formula, validation, filtering, focus, export, tests, verification, and non-targets.\n",encoding="utf-8")
    subprocess.run([sys.executable,"-m","unittest","discover","-s","tests/public","-v"],cwd=args.worktree,check=False)
    input_tokens=700 if arm=="control_raw" else 950; output_tokens=260 if arm=="control_raw" else 360
    elapsed=round(time.monotonic()-started,6); args.usage.parent.mkdir(parents=True,exist_ok=True)
    args.usage.write_text(json.dumps({"input_tokens":input_tokens,"cached_input_tokens":0,"cache_write_input_tokens":0,"output_tokens":output_tokens,"reasoning_output_tokens":80,"provider_total_tokens":input_tokens+output_tokens,"retry_count":0,"provider_billed_cost":round(input_tokens*0.000002+output_tokens*0.000006,8),"local_estimated_cost":round(input_tokens*0.000002+output_tokens*0.000006,8),"currency":"USD","price_catalog_id":"synthetic-fast-v1","provider_elapsed_seconds":elapsed,"first_output_latency_seconds":min(elapsed,0.01)},indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"phase":args.phase,"arm":arm,"state":"completed"}),flush=True); return 0

if __name__=="__main__": raise SystemExit(main())

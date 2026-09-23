from __future__ import annotations
import argparse, hashlib
from importlib.resources import files
from pathlib import Path
from typing import Any
from agent_workflow.plugin_api import PluginCommand, PluginDescriptor, PluginPackageResource
from agent_workflow.util import atomic_write_bytes, atomic_write_json
from .handler import handle_benchmark_command
from .legacy import build_benchmark_report, render_benchmark_markdown, validate_benchmark_manifest

__version__="0.3.2"

def configure(parser: argparse.ArgumentParser) -> None:
    c = parser.add_subparsers(dest="benchmark_command", required=True)
    v = c.add_parser("validate", help="validate a comparative benchmark suite"); v.add_argument("spec", type=Path); v.add_argument("--executor", type=Path)
    a = c.add_parser("auth-check", help="verify benchmark executor authentication"); a.add_argument("executor", type=Path)
    r = c.add_parser("readiness", help="validate benchmark readiness"); r.add_argument("spec", type=Path); r.add_argument("--executor", type=Path, required=True); r.add_argument("--policy", type=Path); r.add_argument("--runtime-lock", type=Path); r.add_argument("--execution-only", action="store_true", help="skip visual-runtime attestation for execution smoke validation")
    a = c.add_parser("runtime-attest", help="attest a benchmark runtime lock for a claim level"); a.add_argument("runtime_lock", type=Path); a.add_argument("--claim-level", choices=("development", "internal", "publication"), default="development")
    a = c.add_parser("runtime-seal", help="seal a runtime lock to an immutable container image"); a.add_argument("base_lock", type=Path); a.add_argument("output", type=Path); a.add_argument("--container-image", required=True)
    a = c.add_parser("suite-export", help="materialize a built-in benchmark suite"); a.add_argument("destination", type=Path); a.add_argument("--benchmark-id", default="priority-picker-v1"); a.add_argument("--force", action="store_true")
    a = c.add_parser("value-smoke-export", help="materialize the raw-direct vs Agent-Workflow value smoke suite"); a.add_argument("destination", type=Path); a.add_argument("--agent-class", default="implementation"); a.add_argument("--force", action="store_true")
    a = c.add_parser("structured-value-smoke-export", help="materialize structured-direct vs Agent-Workflow BM3 study"); a.add_argument("destination", type=Path); a.add_argument("--agent-class", default="implementation"); a.add_argument("--force", action="store_true")
    a = c.add_parser("bm4-export", help="materialize GPT-6 Luna BM4 optimized Agent-Workflow study"); a.add_argument("destination", type=Path); a.add_argument("--agent-class", default="implementation"); a.add_argument("--force", action="store_true")
    a = c.add_parser("fixture-create", help="create an isolated benchmark fixture from a suite spec"); a.add_argument("spec", type=Path); a.add_argument("destination", type=Path); a.add_argument("--force", action="store_true")
    a = c.add_parser("target-prepare", help="prepare and verify an external benchmark target checkout"); a.add_argument("manifest", type=Path); a.add_argument("destination", type=Path)
    a = c.add_parser("plan", help="create a paired benchmark run plan"); a.add_argument("spec", type=Path); a.add_argument("--executor", type=Path, required=True); a.add_argument("--repo", type=Path, required=True); a.add_argument("--base-ref", default="HEAD"); a.add_argument("--run-id"); a.add_argument("--repetitions", type=int); a.add_argument("--worktree-root", type=Path); a.add_argument("--allow-dirty", action="store_true"); a.add_argument("--assistance-cohort", choices=("unassisted", "assisted")); a.add_argument("--policy", type=Path); a.add_argument("--runtime-lock", type=Path); a.add_argument("--codebase-memory-mode", choices=("none", "mcp", "cli"), default="none")
    helps = {
        "run": "execute a planned benchmark",
        "resume": "resume an interrupted benchmark run",
        "status": "show benchmark run status",
        "live-start": "start live application processes for benchmark review",
        "live-stop": "stop live application processes for benchmark review",
        "visual-capture": "capture configured visual benchmark evidence",
        "score": "run benchmark machine scoring",
        "consolidate": "consolidate and verify benchmark evidence",
        "report": "render the benchmark comparison report",
        "verify": "verify consolidated benchmark evidence",
        "cleanup": "clean benchmark worktrees/live processes after evidence verification",
    }
    for name in ("run", "resume", "status", "live-start", "live-stop", "visual-capture", "score", "consolidate", "report", "verify", "cleanup"):
        a = c.add_parser(name, help=helps[name]); a.add_argument("run")
        if name == "run":
            a.add_argument("--execution-only", action="store_true", help="execute planned pairs without visual/review finalization")
        if name == "cleanup":
            a.add_argument("--remove-worktrees", action="store_true"); a.add_argument("--stop-live-apps", action="store_true")
    a = c.add_parser("review", help="record a benchmark human review"); a.add_argument("run"); a.add_argument("--reviewer", required=True); a.add_argument("--input", type=Path)
    a = c.add_parser("legacy-validate", help="validate the former eval benchmark manifest"); a.add_argument("source", type=Path)
    a = c.add_parser("legacy-report", help="render the former eval matched-cohort benchmark report"); a.add_argument("manifest", type=Path); a.add_argument("baseline", type=Path); a.add_argument("candidate", type=Path); a.add_argument("--output", type=Path, required=True); a.add_argument("--markdown", type=Path)

def execute(args: argparse.Namespace, context: Any) -> Any:
    if args.benchmark_command=="legacy-validate":
        value=validate_benchmark_manifest(args.source); return {"path":str(args.source),"schema":value["schema"],"benchmark_id":value["benchmark_id"],"case_ids":[x["case_id"] for x in value["cases"]]}
    if args.benchmark_command=="legacy-report":
        report=build_benchmark_report(args.manifest,args.baseline,args.candidate); atomic_write_json(args.output,report)
        if args.markdown: atomic_write_bytes(args.markdown,render_benchmark_markdown(report).encode())
        return {"output":str(args.output),"benchmark_id":report["benchmark_id"],"paired_n":report["aggregate_metrics"]["paired_n"]}
    return handle_benchmark_command(context.settings,args)

def _digest(name: str) -> str: return hashlib.sha256(files("agent_workflow_benchmark").joinpath("schemas",name).read_bytes()).hexdigest()

def plugin() -> PluginDescriptor:
    resources=[]
    for item in files("agent_workflow_benchmark").joinpath("schemas").iterdir():
        if item.name.endswith(".json"):
            data=__import__("json").loads(item.read_text()); sid=data.get("$id")
            if sid: resources.append(PluginPackageResource("schema",sid,"agent_workflow_benchmark",f"schemas/{item.name}",_digest(item.name)))
    return PluginDescriptor(name="agent-workflow-benchmark",version=__version__,commands=(PluginCommand("benchmark","comparative benchmark capability",configure,execute),),package_resources=tuple(resources),metadata={"capability":"benchmarking","authority":"evaluation-only"})

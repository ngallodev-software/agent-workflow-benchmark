from __future__ import annotations
import argparse, hashlib
from importlib.resources import files
from pathlib import Path
from typing import Any
from agent_workflow.plugin_api import PluginCommand, PluginDescriptor, PluginPackageResource
from agent_workflow.util import atomic_write_bytes, atomic_write_json
from .handler import handle_benchmark_command
from .legacy import build_benchmark_report, render_benchmark_markdown, validate_benchmark_manifest

__version__="0.4.0"

def configure(parser: argparse.ArgumentParser) -> None:
    c = parser.add_subparsers(dest="benchmark_command", required=True)
    a = c.add_parser("decision-study-corpus-export", help="export the frozen public-safe routing decision corpus"); a.add_argument("destination", type=Path); a.add_argument("--study", default="routing-semantic-v1"); a.add_argument("--force", action="store_true")
    a = c.add_parser("decision-study-oracle-view-export", help="export a blinded oracle-authoring view with no construction tags or treatment outputs"); a.add_argument("destination", type=Path); a.add_argument("--study", default="routing-semantic-v1"); a.add_argument("--force", action="store_true")
    a = c.add_parser("decision-study-oracle-validate", help="validate one complete blinded oracle adjudication"); a.add_argument("corpus", type=Path); a.add_argument("adjudication", type=Path); a.add_argument("--study", default="routing-semantic-v1")
    a = c.add_parser("decision-study-oracle-compare", help="compare independent A/B adjudications without exposing their votes"); a.add_argument("corpus", type=Path); a.add_argument("left", type=Path); a.add_argument("right", type=Path); a.add_argument("output", type=Path); a.add_argument("--study", default="routing-semantic-v1"); a.add_argument("--force", action="store_true")
    a = c.add_parser("decision-study-oracle-tiebreak-view", help="build C's blind view for A/B disagreements"); a.add_argument("corpus", type=Path); a.add_argument("disagreements", type=Path); a.add_argument("output", type=Path); a.add_argument("--study", default="routing-semantic-v1"); a.add_argument("--force", action="store_true")
    a = c.add_parser("decision-study-oracle-freeze", help="freeze the final oracle from independent A/B, optional C, and optional consensus resolution"); a.add_argument("corpus", type=Path); a.add_argument("a", type=Path); a.add_argument("b", type=Path); a.add_argument("output", type=Path); a.add_argument("--c", type=Path); a.add_argument("--consensus", type=Path); a.add_argument("--oracle-version", required=True); a.add_argument("--study", default="routing-semantic-v1"); a.add_argument("--force", action="store_true")
    a = c.add_parser("decision-study-validate", help="validate a frozen comparative-decision corpus and optional separate oracle"); a.add_argument("corpus", type=Path); a.add_argument("--oracle", type=Path); a.add_argument("--study", default="routing-semantic-v1")
    a = c.add_parser("decision-study-run", help="run the frozen comparative-decision inference corpus without loading the oracle"); a.add_argument("corpus", type=Path); a.add_argument("output", type=Path); a.add_argument("--study", default="routing-semantic-v1"); a.add_argument("--force", action="store_true")
    a = c.add_parser("decision-study-report", help="join a separately frozen oracle after inference and build the study report"); a.add_argument("run", type=Path); a.add_argument("oracle", type=Path)
    a = c.add_parser("decision-study-publish-prepare", help="prepare a sanitized public decision-study evidence tree"); a.add_argument("run", type=Path); a.add_argument("oracle", type=Path); a.add_argument("destination", type=Path); a.add_argument("--force", action="store_true")
    v = c.add_parser("validate", help="validate a comparative benchmark suite"); v.add_argument("spec", type=Path); v.add_argument("--executor", type=Path)
    a = c.add_parser("auth-check", help="verify benchmark executor authentication"); a.add_argument("executor", type=Path)
    r = c.add_parser("readiness", help="validate benchmark readiness"); r.add_argument("spec", type=Path); r.add_argument("--executor", type=Path, required=True); r.add_argument("--policy", type=Path); r.add_argument("--runtime-lock", type=Path); r.add_argument("--execution-only", action="store_true", help="skip visual-runtime attestation for execution smoke validation")
    a = c.add_parser("runtime-attest", help="attest a benchmark runtime lock for a claim level"); a.add_argument("runtime_lock", type=Path); a.add_argument("--claim-level", choices=("development", "internal", "publication"), default="development")
    a = c.add_parser("runtime-seal", help="seal a runtime lock to an immutable container image"); a.add_argument("base_lock", type=Path); a.add_argument("output", type=Path); a.add_argument("--container-image", required=True)
    a = c.add_parser("seal", help="cryptographically seal completed execution before scoring"); a.add_argument("run")
    a = c.add_parser("seal-verify", help="verify a benchmark execution seal"); a.add_argument("run")
    a = c.add_parser("suite-export", help="materialize a built-in benchmark suite"); a.add_argument("destination", type=Path); a.add_argument("--benchmark-id", default="priority-picker-v1"); a.add_argument("--force", action="store_true")
    a = c.add_parser("value-smoke-export", help="materialize the raw-direct vs Agent-Workflow value smoke suite"); a.add_argument("destination", type=Path); a.add_argument("--agent-class", default="implementation"); a.add_argument("--force", action="store_true")
    a = c.add_parser("structured-value-smoke-export", help="materialize structured-direct vs Agent-Workflow BM3 study"); a.add_argument("destination", type=Path); a.add_argument("--agent-class", default="implementation"); a.add_argument("--force", action="store_true")
    a = c.add_parser("bm4-export", help="materialize GPT-6 Luna BM4 optimized Agent-Workflow study"); a.add_argument("destination", type=Path); a.add_argument("--agent-class", default="implementation"); a.add_argument("--force", action="store_true")
    a = c.add_parser("bm5-export", help="materialize GPT-6 Luna BM5 steering-first Agent-Workflow study"); a.add_argument("destination", type=Path); a.add_argument("--agent-class", default="implementation"); a.add_argument("--force", action="store_true")
    a = c.add_parser("bm6-export", help="materialize blind Change Window BM6 execution suite"); a.add_argument("destination", type=Path); a.add_argument("--agent-class", default="implementation"); a.add_argument("--force", action="store_true")
    a = c.add_parser("scoring-bundle-init", help="create a universal post-seal scoring bundle template"); a.add_argument("destination", type=Path); a.add_argument("--force", action="store_true")
    a = c.add_parser("scoring-bundle-validate", help="validate a universal post-seal scoring bundle"); a.add_argument("bundle", type=Path)
    a = c.add_parser("code-review", help="append optional TypeSafe advisory scores to a deterministic review"); a.add_argument("left", type=Path); a.add_argument("right", type=Path); a.add_argument("--requirements", type=Path); a.add_argument("--base-review", type=Path, required=True); a.add_argument("--question-set", choices=("v1", "v2"), default="v1"); a.add_argument("--context-scope", choices=("full-tree", "matched-file"), default="full-tree"); a.add_argument("--candidate-order", choices=("balanced", "reversed"), default="balanced"); a.add_argument("--output", type=Path, required=True); a.add_argument("--model")
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
        if name == "score":
            a.add_argument("--scoring-bundle", type=Path, help="external post-seal scorer bundle directory")
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

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_bytes, atomic_write_json

from .common import tree_sha256
from .universal_scoring import load_bundle_manifest

WRAPPER = """from pathlib import Path
import sys

from agent_workflow_benchmark.benchmarking.universal_scoring import main

if __name__ == "__main__":
    bundle = Path(__file__).resolve().parent
    raise SystemExit(main(["--bundle", str(bundle), *sys.argv[1:]]))
"""

README = """# Universal scoring bundle

This directory is a post-seal scoring bundle. It is intentionally separate from
the benchmark execution package.

The evaluator is driven by bundle.json. It can compose:

- command probes for hidden tests, browser checks, linters, custom scripts, or any
  deterministic JSON-producing evaluator;
- TypeSafe batch probes: one system_one request may contain many Score questions;
- additional TypeSafe batches by adding more probes;
- LLM command probes with JSON prompts/context and JSON responses;
- arbitrary JSON parameters available to probes through parameters.json and
  scalar {param_NAME} command placeholders.

Probe results are cached per bundle digest and sealed worktree digest so an
expensive semantic batch can feed several dimensions without repeated calls.

Command probes support result_mode values: exit-code, json-file, json-stdout.
For json-file mode, write JSON to {probe_result}.

TypeSafe/LLM context accepts worktree_globs, exclude_globs, bundle_files,
include_probe_outputs, max_files, max_total_bytes, and static JSON.

Dimension components read probe values with JSON Pointer and score them with
boolean, fraction, linear, threshold, or mapping modes.

score.py is generic. Task-specific tests, prompts, parameters and scoring weights
belong in bundle.json and sibling files, and should be introduced only after the
benchmark execution seal exists.
"""

EXAMPLE = {
    "schema": "agent-workflow/universal-scoring-bundle/v1",
    "bundle_id": "replace-me",
    "version": "1.0.0",
    "parameters": {},
    "runtime": {
        "environment_allowlist": ["TYPESAFE_API_KEY"],
        "default_timeout_seconds": 120,
    },
    "probes": {
        "deterministic": {
            "kind": "command",
            "argv": [
                "python",
                "{bundle}/tests/example.py",
                "--worktree",
                "{worktree}",
                "--output",
                "{probe_result}",
            ],
            "result_mode": "json-file",
        },
        "semantic-core": {
            "kind": "typesafe-batch",
            "depends_on": ["deterministic"],
            "context": {
                "worktree_globs": ["**/*.py", "**/*.js", "**/*.html", "**/*.css", "README.md"],
                "bundle_files": ["requirements.md"],
                "include_probe_outputs": ["deterministic"],
                "max_files": 64,
                "max_total_bytes": 524288,
            },
            "questions": [
                {
                    "id": "task_fit",
                    "instructions": "Score source-visible task fit using only supplied evidence.",
                    "criteria": [
                        "0 - fundamentally misses the stated task",
                        "1 - major task gaps are evident",
                        "2 - main task is present with material gaps",
                        "3 - strong task fit with localized weaknesses",
                        "4 - complete task fit with no material source-visible gap",
                    ],
                }
            ],
        },
        "optional-llm": {
            "kind": "llm-command",
            "depends_on": ["deterministic"],
            "argv": ["python", "{bundle}/helpers/llm_adapter.py"],
            "prompt_file": "prompts/review.md",
            "response_mode": "json-stdout",
            "context": {
                "include_probe_outputs": ["deterministic"],
                "bundle_files": ["requirements.md"],
            },
        },
    },
    "dimensions": {
        "replace_dimension": {
            "contract_checks": {
                "replace-check": {
                    "components": [
                        {
                            "id": "deterministic-fraction",
                            "probe": "deterministic",
                            "weight": 4,
                            "value": {
                                "path": "/payload/fraction",
                                "mode": "fraction",
                            },
                        },
                        {
                            "id": "semantic-fit",
                            "probe": "semantic-core",
                            "weight": 1,
                            "value": {
                                "path": "/answers/task_fit/score",
                                "mode": "linear",
                                "min": 0,
                                "max": 4,
                            },
                        },
                    ]
                }
            }
        }
    },
}


def initialize_scoring_bundle(destination: Path, *, force: bool = False) -> dict[str, Any]:
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not force:
            raise WorkflowError(f"scoring bundle destination already exists: {destination}")
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.mkdir(parents=True)
    (destination / "tests").mkdir()
    (destination / "prompts").mkdir()
    (destination / "helpers").mkdir()
    atomic_write_bytes(destination / "score.py", WRAPPER.encode("utf-8"))
    atomic_write_bytes(destination / "README.md", README.encode("utf-8"))
    atomic_write_json(destination / "bundle.json", EXAMPLE)
    atomic_write_bytes(
        destination / "requirements.md",
        b"# Scoring requirements\n\nReplace this file with the frozen task/rubric evidence.\n",
    )
    atomic_write_bytes(
        destination / "prompts" / "review.md",
        b"Return one JSON object containing only evidence-grounded review fields.\n",
    )
    return {
        "destination": str(destination),
        "manifest": str(destination / "bundle.json"),
        "score": str(destination / "score.py"),
        "tree_sha256": tree_sha256(destination),
    }


def validate_scoring_bundle(bundle: Path) -> dict[str, Any]:
    bundle = bundle.expanduser().resolve()
    manifest = load_bundle_manifest(bundle)
    score = bundle / "score.py"
    if not score.is_file():
        raise WorkflowError(f"scoring bundle score.py not found: {score}")
    return {
        "bundle": str(bundle),
        "bundle_id": manifest["bundle_id"],
        "version": manifest["version"],
        "probes": sorted(manifest["probes"]),
        "dimensions": sorted(manifest["dimensions"]),
        "tree_sha256": tree_sha256(bundle),
    }

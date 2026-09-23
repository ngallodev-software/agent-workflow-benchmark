#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AW_BIN="${AGENT_WORKFLOW_BIN:-agent-workflow}"
TARGET=""
ROOT_ARG="${BM4_ROOT:-}"
RESULTS_REPO_ARG=""
PRIVATE_ARCHIVE_ARG=""
COMMIT_RESULTS=0
PUSH_RESULTS=0

usage() {
  cat <<'USAGE'
Usage: bash scripts/finalize-bm4.sh RUN_ID_OR_PLAN --root PATH [options]

Finalize an already executed BM4 run after visual capture is complete.

This command does NOT rerun model execution. It:
  1. verifies visual capture completed without harness failures;
  2. runs/caches machine scoring, consolidation, and report generation;
  3. creates a private full evidence archive;
  4. builds a sanitized public bm4/ publication tree;
  5. copies that tree into the sibling agent-workflow-benchmark-results repo.

Options:
  --root PATH             BM4 artifact root (required unless BM4_ROOT is set)
  --results-repo PATH     results repo (default: sibling agent-workflow-benchmark-results)
  --private-archive PATH  full private archive path (default: <root>/bm4-private-evidence.tar.gz)
  --commit-results        commit only the bm4/ path in the results repo
  --push-results          push the results repo after committing (implies --commit-results)
  -h, --help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      shift; [[ $# -gt 0 ]] || { echo "--root requires a path" >&2; exit 2; }
      ROOT_ARG="$1"
      ;;
    --results-repo)
      shift; [[ $# -gt 0 ]] || { echo "--results-repo requires a path" >&2; exit 2; }
      RESULTS_REPO_ARG="$1"
      ;;
    --private-archive)
      shift; [[ $# -gt 0 ]] || { echo "--private-archive requires a path" >&2; exit 2; }
      PRIVATE_ARCHIVE_ARG="$1"
      ;;
    --commit-results)
      COMMIT_RESULTS=1
      ;;
    --push-results)
      COMMIT_RESULTS=1
      PUSH_RESULTS=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -n "$TARGET" ]]; then
        echo "unexpected argument: $1" >&2
        usage >&2
        exit 2
      fi
      TARGET="$1"
      ;;
  esac
  shift
done

[[ -n "$TARGET" ]] || { usage >&2; exit 2; }
[[ -n "$ROOT_ARG" ]] || {
  echo "BM4 root is required; pass --root PATH or set BM4_ROOT" >&2
  exit 2
}

if [[ "$AW_BIN" == */* ]]; then
  AW_PATH="$AW_BIN"
else
  AW_PATH="$(command -v "$AW_BIN" 2>/dev/null || true)"
fi
[[ -n "$AW_PATH" && -x "$AW_PATH" ]] || {
  echo "Agent-Workflow launcher not found: $AW_BIN" >&2
  exit 1
}

PYTHON="$(dirname "$AW_PATH")/python"
[[ -x "$PYTHON" ]] || PYTHON="$(dirname "$AW_PATH")/python3"
[[ -x "$PYTHON" ]] || { echo "Python not found beside $AW_PATH" >&2; exit 1; }

ROOT="$("$PYTHON" - "$ROOT_ARG" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
[[ -d "$ROOT" ]] || { echo "BM4 root not found: $ROOT" >&2; exit 1; }

PLAN="$("$PYTHON" - "$TARGET" <<'PY'
from pathlib import Path
import sys
from agent_workflow.config import load_settings

value = Path(sys.argv[1]).expanduser()
if value.exists():
    if value.is_dir():
        value = value / "run-plan.json"
    plan = value.resolve()
else:
    settings = load_settings()
    run_id = sys.argv[1]
    plan = (
        settings.worktree_root / "benchmarks" / run_id / "coordinator"
        / "benchmarks" / "runs" / run_id / "run-plan.json"
    ).resolve()
if not plan.is_file():
    raise SystemExit(f"benchmark run plan not found: {plan}")
print(plan)
PY
)"

RUN_ID="$("$PYTHON" - "$PLAN" <<'PY'
import json, sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["run_id"])
PY
)"

RUN_DIR="$("$PYTHON" - "$PLAN" <<'PY'
import json, sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["coordinator"]["run_dir"])
PY
)"

[[ -d "$RUN_DIR" ]] || { echo "benchmark run directory not found: $RUN_DIR" >&2; exit 1; }

"$PYTHON" - "$RUN_DIR/visual-capture-summary.json" "$PLAN" <<'PY'
import json, sys
from pathlib import Path
summary_path = Path(sys.argv[1])
plan = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if not summary_path.is_file():
    raise SystemExit("visual capture summary is missing; run recover-benchmark-visual.sh first")
value = json.loads(summary_path.read_text(encoding="utf-8"))
expected = len(plan.get("pairs", [])) * 2
complete = int(value.get("complete", 0))
failures = int(value.get("harness_failures", 0))
if failures or complete != expected:
    raise SystemExit(
        f"visual capture is not ready for finalization: complete={complete}/{expected}; "
        f"harness_failures={failures}"
    )
print(f"visual capture verified: {complete}/{expected} complete; 0 harness failures")
PY

mkdir -p "$ROOT/finalize"
"$AW_PATH" --json benchmark score "$PLAN"   | tee "$ROOT/finalize/score.json"
"$AW_PATH" --json benchmark consolidate "$PLAN"   | tee "$ROOT/finalize/consolidate.json"
"$AW_PATH" --json benchmark report "$PLAN"   | tee "$ROOT/finalize/report-command.json"
"$AW_PATH" --json benchmark live-stop "$PLAN"   > "$ROOT/finalize/live-stop.json" 2>/dev/null || true

PRIVATE_ARCHIVE="$PRIVATE_ARCHIVE_ARG"
if [[ -z "$PRIVATE_ARCHIVE" ]]; then
  PRIVATE_ARCHIVE="$ROOT/bm4-private-evidence.tar.gz"
fi
PRIVATE_ARCHIVE="$("$PYTHON" - "$PRIVATE_ARCHIVE" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"

export AGENT_WORKFLOW_TYPESAFE_API_CALL_LOG="$ROOT/typesafe-api-audit.jsonl"
"$PYTHON" "$REPO_ROOT/scripts/collect-value-smoke-evidence.py"   "$ROOT"   --run-dir "$RUN_DIR"   --output "$PRIVATE_ARCHIVE"

if [[ -n "$RESULTS_REPO_ARG" ]]; then
  RESULTS_REPO="$("$PYTHON" - "$RESULTS_REPO_ARG" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
else
  RESULTS_REPO="$(cd "$REPO_ROOT/.." && pwd)/agent-workflow-benchmark-results"
fi

[[ -d "$RESULTS_REPO/.git" ]] || {
  echo "benchmark results repository not found: $RESULTS_REPO" >&2
  exit 1
}

PUBLIC_DEST="$RESULTS_REPO/bm4"
"$PYTHON" "$REPO_ROOT/scripts/prepare-bm4-publication.py"   --plan "$PLAN"   --root "$ROOT"   --destination "$PUBLIC_DEST"   --private-archive "$PRIVATE_ARCHIVE"

cp "$PUBLIC_DEST/result.json" "$ROOT/bm4-publication-result.json"

"$PYTHON" - "$PUBLIC_DEST" <<'PY'
from pathlib import Path
import hashlib, json, sys
root = Path(sys.argv[1])
records = []
for path in sorted(root.rglob("*")):
    if path.is_file():
        records.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        })
manifest = {
    "schema": "agent-workflow/bm4-publication-manifest/v1",
    "files": records,
    "file_count": len(records),
}
(root / "PUBLICATION-MANIFEST.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"public files: {len(records)}")
PY

if [[ "$COMMIT_RESULTS" -eq 1 ]]; then
  git -C "$RESULTS_REPO" add -- bm4
  if git -C "$RESULTS_REPO" diff --cached --quiet -- bm4; then
    echo "benchmark results repo: no bm4 changes to commit"
  else
    git -C "$RESULTS_REPO" commit       -m "Publish BM4 optimized Agent-Workflow benchmark"       -- bm4
  fi
fi

if [[ "$PUSH_RESULTS" -eq 1 ]]; then
  git -C "$RESULTS_REPO" push
fi

echo
echo "BM4 finalization complete"
echo "  run_id:          $RUN_ID"
echo "  run_plan:        $PLAN"
echo "  run_dir:         $RUN_DIR"
echo "  private archive: $PRIVATE_ARCHIVE"
echo "  public results:  $PUBLIC_DEST"
echo "  result:          $PUBLIC_DEST/result.json"
echo "  analysis:        $PUBLIC_DEST/analysis/comparison.md"
echo
echo "The private archive contains raw evidence and must not be published."

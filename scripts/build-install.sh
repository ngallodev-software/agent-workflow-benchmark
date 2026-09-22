#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_ARG=""
COMPARATIVE_EVAL_SOURCE_ARG=""
VERIFY_ONLY=0
BOOTSTRAP_BUILD=1

usage() {
  cat <<'USAGE'
Usage: scripts/build-install.sh [--venv PATH] [--comparative-eval-source PATH] [--verify-only] [--no-bootstrap-build]

Build and install agent-workflow-benchmark into the same shared virtualenv that
owns the Agent-Workflow wheel/launcher, then verify there are no stale benchmark
package files, schemas, metadata directories, or obsolete benchmark launchers.

Virtualenv selection, in priority order:
  1. --venv PATH
  2. AGENT_WORKFLOW_VENV
  3. the virtualenv inferred from the resolved agent-workflow launcher

Options:
  --venv PATH            Explicit shared Agent-Workflow virtualenv.
  --comparative-eval-source PATH
                         Local agent-workflow-comparative-eval checkout to install if needed.
  --verify-only          Skip build/install and only verify the existing install.
  --no-bootstrap-build   Do not install the Python 'build' package if missing.
  -h, --help             Show this help.

The script deliberately does not install or replace Agent-Workflow itself.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv)
      shift
      [[ $# -gt 0 ]] || { echo "--venv requires a value" >&2; exit 2; }
      VENV_ARG="$1"
      ;;
    --comparative-eval-source)
      shift
      [[ $# -gt 0 ]] || { echo "--comparative-eval-source requires a value" >&2; exit 2; }
      COMPARATIVE_EVAL_SOURCE_ARG="$1"
      ;;
    --verify-only) VERIFY_ONLY=1 ;;
    --no-bootstrap-build) BOOTSTRAP_BUILD=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to resolve the Agent-Workflow installation" >&2
  exit 127
}

resolve_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
}

infer_venv_from_launcher() {
  local launcher="$1" resolved parent candidate interpreter
  resolved="$(resolve_path "$launcher")"
  parent="$(dirname "$resolved")"
  candidate="$(dirname "$parent")"
  if [[ -x "$candidate/bin/python" || -x "$candidate/bin/python3" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  # A user-local console script can run an editable Agent-Workflow checkout;
  # its own path is not the venv. Follow that interpreter's import to the
  # checkout and use the checkout's standard .venv.
  interpreter="$(sed -n '1s/^#!//p' "$resolved" | awk '{print $1}')"
  if [[ -x "$interpreter" ]]; then
    candidate="$($interpreter - <<'PY'
from pathlib import Path
import agent_workflow

for parent in Path(agent_workflow.__file__).resolve().parents:
    venv = parent / ".venv"
    if (venv / "bin" / "agent-workflow").is_file() and (venv / "bin" / "python").is_file():
        print(venv)
        break
PY
    )"
    if [[ -n "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi
  return 1
}

prepare_dev_config() {
  local target_config="$XDG_CONFIG_HOME/agent-workflow/config.toml"
  mkdir -p "$(dirname "$target_config")"
  "$PYTHON" - "$target_config" "$VENV" <<'PY'
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import sys
import tempfile
import tomllib

target = Path(sys.argv[1])
venv = Path(sys.argv[2]).resolve()

if target.is_file():
    existing = target.read_text(encoding="utf-8")
    try:
        tomllib.loads(existing)
    except tomllib.TOMLDecodeError:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = target.with_name(f"{target.name}.invalid-{stamp}")
        backup.write_text(existing, encoding="utf-8")
        print(
            f"recovered invalid benchmark config; backup preserved at {backup}",
            file=sys.stderr,
        )

def q(value: str) -> str:
    return json.dumps(value)

rendered = "\n".join(
    [
        "schema_version = 1",
        "",
        "[paths]",
        f"worktree_root = {q(str(venv / '.xdg' / 'data' / 'agent-workflow' / 'worktrees'))}",
        f"state_root = {q(str(venv / '.xdg' / 'state' / 'agent-workflow'))}",
        "",
        "[plugins]",
        'enabled = ["agent-workflow-benchmark"]',
        "",
        "[semantic]",
        'provider = "typesafe"',
        "",
        "[semantic.typesafe]",
        f"api_call_log = {q(str(venv / '.xdg' / 'state' / 'agent-workflow' / 'typesafe-api-calls.jsonl'))}",
        "",
        "[decision_policy]",
        'mode = "comparative"',
        'profile = "default"',
        "",
    ]
)

try:
    parsed = tomllib.loads(rendered)
except tomllib.TOMLDecodeError as exc:
    raise SystemExit(f"internal benchmark config generation produced invalid TOML: {exc}") from exc

assert parsed["plugins"]["enabled"] == ["agent-workflow-benchmark"]
assert parsed["semantic"]["provider"] == "typesafe"
assert parsed["semantic"]["typesafe"]["api_call_log"].endswith("typesafe-api-calls.jsonl")
assert parsed["decision_policy"]["mode"] == "comparative"

target.parent.mkdir(parents=True, exist_ok=True)
with tempfile.NamedTemporaryFile(
    "w",
    encoding="utf-8",
    dir=target.parent,
    prefix=target.name + ".",
    suffix=".tmp",
    delete=False,
) as handle:
    handle.write(rendered)
    temp = Path(handle.name)
os.replace(temp, target)
print(f"benchmark runtime config: {target}")
PY
}

if [[ -n "$VENV_ARG" ]]; then
  VENV="$(resolve_path "$VENV_ARG")"
elif [[ -n "${AGENT_WORKFLOW_VENV:-}" ]]; then
  VENV="$(resolve_path "$AGENT_WORKFLOW_VENV")"
else
  AW_ON_PATH="${AGENT_WORKFLOW_BIN:-$(command -v agent-workflow 2>/dev/null || true)}"
  [[ -n "$AW_ON_PATH" ]] || {
    echo "agent-workflow was not found on PATH; pass --venv PATH or set AGENT_WORKFLOW_VENV" >&2
    exit 1
  }
  VENV="$(infer_venv_from_launcher "$AW_ON_PATH" || true)"
  [[ -n "$VENV" ]] || {
    echo "could not infer a virtualenv from agent-workflow launcher: $AW_ON_PATH" >&2
    echo "pass --venv PATH explicitly" >&2
    exit 1
  }
fi

if [[ -x "$VENV/bin/python" ]]; then
  PYTHON="$VENV/bin/python"
elif [[ -x "$VENV/bin/python3" ]]; then
  PYTHON="$VENV/bin/python3"
else
  echo "shared virtualenv has no Python interpreter: $VENV" >&2
  exit 1
fi

AW_LAUNCHER="$VENV/bin/agent-workflow"
[[ -x "$AW_LAUNCHER" ]] || {
  echo "Agent-Workflow launcher is not installed in the selected virtualenv: $AW_LAUNCHER" >&2
  exit 1
}
export VIRTUAL_ENV="$VENV"
export AGENT_WORKFLOW_VENV="$VENV"
export AGENT_WORKFLOW_BIN="$AW_LAUNCHER"
export PATH="$VENV/bin:$PATH"
export XDG_CONFIG_HOME="$VENV/.xdg/config"
export XDG_STATE_HOME="$VENV/.xdg/state"
export XDG_DATA_HOME="$VENV/.xdg/data"
mkdir -p "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_DATA_HOME"
prepare_dev_config

echo "shared Agent-Workflow virtualenv: $VENV"
echo "target Python: $PYTHON"
echo "Agent-Workflow launcher: $AW_LAUNCHER"

"$PYTHON" - "$VENV" "$ROOT" <<'PY'
from importlib import metadata
from pathlib import Path
import json
import re
import sys
import sysconfig
import tomllib

venv = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
prefix = Path(sys.prefix).resolve()
if prefix != venv:
    raise SystemExit(f"selected interpreter prefix mismatch: expected {venv}, observed {prefix}")
if sys.prefix == sys.base_prefix:
    raise SystemExit(f"selected interpreter is not a virtualenv: {sys.executable}")

try:
    dist = metadata.distribution("agent-workflow")
except metadata.PackageNotFoundError as exc:
    raise SystemExit("agent-workflow is not installed in the selected virtualenv") from exc

purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
dist_root = Path(dist.locate_file("")).resolve()
try:
    dist_root.relative_to(purelib)
except ValueError as exc:
    raise SystemExit(
        f"agent-workflow distribution is not owned by the selected virtualenv: {dist_root}"
    ) from exc

direct_url_raw = dist.read_text("direct_url.json")
if direct_url_raw:
    direct_url = json.loads(direct_url_raw)
    if direct_url.get("dir_info", {}).get("editable") is True:
        raise SystemExit(
            "agent-workflow is installed editable in the selected virtualenv; "
            "install the qualified Agent-Workflow wheel before installing the benchmark plugin"
        )

project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
requirement = next(
    (item for item in project.get("dependencies", []) if item.startswith("agent-workflow>=")),
    None,
)
match = re.fullmatch(
    r"agent-workflow>=(\d+)\.(\d+)\.(\d+),<(\d+)\.(\d+)",
    requirement or "",
)
if match:
    lower = tuple(int(value) for value in match.groups()[:3])
    upper = tuple(int(value) for value in match.groups()[3:]) + (0,)
    version_match = re.match(r"^(\d+)\.(\d+)\.(\d+)", dist.version)
    if not version_match:
        raise SystemExit(f"cannot interpret Agent-Workflow version: {dist.version}")
    observed = tuple(int(value) for value in version_match.groups())
    if not (lower <= observed < upper):
        raise SystemExit(
            f"Agent-Workflow {dist.version} does not satisfy benchmark requirement {requirement}"
        )

print(f"Agent-Workflow distribution: {dist.metadata['Name']} {dist.version}")
print(f"Agent-Workflow site-packages: {purelib}")
PY

EXPECTED_VERSION="$("$PYTHON" - "$ROOT/pyproject.toml" <<'PY'
from pathlib import Path
import sys
import tomllib
value = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(value["project"]["version"])
PY
)"

resolve_comparative_eval_source() {
  local candidate=""
  if [[ -n "$COMPARATIVE_EVAL_SOURCE_ARG" ]]; then
    candidate="$COMPARATIVE_EVAL_SOURCE_ARG"
  elif [[ -n "${AGENT_WORKFLOW_COMPARATIVE_EVAL_SOURCE:-}" ]]; then
    candidate="$AGENT_WORKFLOW_COMPARATIVE_EVAL_SOURCE"
  elif [[ -f "$ROOT/../agent-workflow-comparative-eval/pyproject.toml" ]]; then
    candidate="$ROOT/../agent-workflow-comparative-eval"
  fi
  if [[ -n "$candidate" ]]; then
    resolve_path "$candidate"
  fi
}

semantic_dependency_versions_ok() {
  "$PYTHON" - <<'PY'
from importlib import metadata

required = {
    "typesafe-sdk": "0.6.0",
    "agent-workflow-comparative-eval": "0.1.0",
}
for name, expected in required.items():
    try:
        observed = metadata.version(name)
    except metadata.PackageNotFoundError:
        raise SystemExit(1)
    if observed != expected:
        raise SystemExit(1)
PY
}

verify_semantic_runtime() {
  [[ -n "${TYPESAFE_API_KEY:-}" ]] || {
    echo "benchmark comparative mode requires TYPESAFE_API_KEY in the environment" >&2
    return 1
  }
  "$PYTHON" - <<'PY'
from importlib import metadata

from agent_workflow.config import load_settings
from agent_workflow.decisions import require_decision_runtime_ready

required = {
    "typesafe-sdk": "0.6.0",
    "agent-workflow-comparative-eval": "0.1.0",
}
for name, expected in required.items():
    try:
        observed = metadata.version(name)
    except metadata.PackageNotFoundError as exc:
        raise SystemExit(f"required semantic dependency is not installed: {name}=={expected}") from exc
    if observed != expected:
        raise SystemExit(
            f"semantic dependency version mismatch: {name} {observed}; expected {expected}"
        )

settings = load_settings()
if settings.decision_mode != "comparative":
    raise SystemExit(
        f"benchmark runtime must use decision_policy.mode='comparative'; observed {settings.decision_mode!r}"
    )
status = require_decision_runtime_ready(settings)
if status.get("ready") is not True:
    raise SystemExit(f"comparative semantic runtime is not ready: {status}")
print(
    "semantic runtime verified: mode=comparative; typesafe_sdk=0.6.0; "
    "comparative_eval=0.1.0; typesafe_api_key=configured"
)
PY
}

ensure_semantic_dependencies() {
  [[ -n "${TYPESAFE_API_KEY:-}" ]] || {
    echo "benchmark comparative mode requires TYPESAFE_API_KEY in the environment" >&2
    exit 1
  }

  if "$PYTHON" - <<'PY'
from importlib import metadata
try:
    raise SystemExit(0 if metadata.version("typesafe-sdk") == "0.6.0" else 1)
except metadata.PackageNotFoundError:
    raise SystemExit(1)
PY
  then
    echo "TypeSafe SDK already installed: 0.6.0"
  else
    echo "installing TypeSafe SDK 0.6.0 into shared virtualenv"
    "$PYTHON" -m pip install --upgrade "typesafe-sdk==0.6.0"
  fi

  if "$PYTHON" - <<'PY'
from importlib import metadata
try:
    raise SystemExit(
        0 if metadata.version("agent-workflow-comparative-eval") == "0.1.0" else 1
    )
except metadata.PackageNotFoundError:
    raise SystemExit(1)
PY
  then
    echo "comparative-eval library already installed: 0.1.0"
  else
    local source
    source="$(resolve_comparative_eval_source)"
    if [[ -n "$source" && -f "$source/pyproject.toml" ]]; then
      echo "installing comparative-eval 0.1.0 from local source: $source"
      "$PYTHON" -m pip install --no-deps --force-reinstall "$source"
    else
      echo "local comparative-eval source not found; installing distribution agent-workflow-comparative-eval==0.1.0"
      "$PYTHON" -m pip install --no-deps --force-reinstall "agent-workflow-comparative-eval==0.1.0"
    fi
  fi

  semantic_dependency_versions_ok || {
    echo "semantic dependency installation did not produce the required versions" >&2
    exit 1
  }
}
verify_path_shadowing() {
  local active resolved_active resolved_expected
  active="$(command -v agent-workflow 2>/dev/null || true)"
  if [[ -n "$active" ]]; then
    resolved_active="$(resolve_path "$active")"
    resolved_expected="$(resolve_path "$AW_LAUNCHER")"
    if [[ "$resolved_active" != "$resolved_expected" ]]; then
      echo "stale/shadowing agent-workflow launcher detected:" >&2
      echo "  PATH resolves: $active -> $resolved_active" >&2
      echo "  expected:      $AW_LAUNCHER -> $resolved_expected" >&2
      exit 1
    fi
  fi

  local stale=()
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    stale+=("$candidate")
  done < <(type -a -p agent-workflow-benchmark 2>/dev/null | awk '!seen[$0]++' || true)
  if (( ${#stale[@]} > 0 )); then
    echo "obsolete agent-workflow-benchmark launcher(s) found on PATH:" >&2
    printf '  %s\n' "${stale[@]}" >&2
    echo "the plugin is contributed through agent-workflow.plugins and should not own a standalone binary" >&2
    exit 1
  fi
}

verify_core_share_artifacts() {
  "$PYTHON" - "$VENV" <<'PY'
from importlib import metadata
from pathlib import Path
import sys

prefix = Path(sys.argv[1]).resolve()
schema_dir = prefix / "share" / "agent-workflow" / "schemas"
if not schema_dir.is_dir():
    raise SystemExit(0)

dist = metadata.distribution("agent-workflow")
owned = {
    Path(dist.locate_file(item)).resolve()
    for item in (dist.files or ())
}
conflicts = []
orphans = []
for path in sorted(schema_dir.glob("benchmark-*.schema.json")):
    if path.resolve() in owned:
        conflicts.append(path)
    else:
        orphans.append(path)
if conflicts:
    raise SystemExit(
        "current Agent-Workflow distribution still owns benchmark schemas that "
        "must belong to the benchmark plugin: "
        + ", ".join(str(path) for path in conflicts)
    )
if orphans:
    raise SystemExit(
        "stale unowned benchmark schemas remain in shared virtualenv data: "
        + ", ".join(str(path) for path in orphans)
    )
PY
}

cleanup_core_share_artifacts() {
  "$PYTHON" - "$VENV" <<'PY'
from importlib import metadata
from pathlib import Path
import sys

prefix = Path(sys.argv[1]).resolve()
schema_dir = prefix / "share" / "agent-workflow" / "schemas"
if not schema_dir.is_dir():
    raise SystemExit(0)

dist = metadata.distribution("agent-workflow")
owned = {
    Path(dist.locate_file(item)).resolve()
    for item in (dist.files or ())
}
for path in sorted(schema_dir.glob("benchmark-*.schema.json")):
    if path.resolve() in owned:
        raise SystemExit(
            "refusing to remove benchmark schema still owned by the current "
            f"Agent-Workflow distribution: {path}"
        )
    print(f"removing stale unowned shared-venv benchmark schema: {path}")
    path.unlink()
PY
  verify_core_share_artifacts
}

verify_host_artifacts() {
  local data_home host_schema_dir path
  data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
  host_schema_dir="$data_home/agent-workflow/schemas"

  if [[ -d "$host_schema_dir" ]]; then
    local stale_schema_found=0 schema_name
    while IFS= read -r schema_name; do
      [[ -n "$schema_name" ]] || continue
      path="$host_schema_dir/$schema_name"
      if [[ -f "$path" || -L "$path" ]]; then
        echo "stale core-era benchmark schema remains: $path" >&2
        stale_schema_found=1
      fi
    done < <(
      find "$ROOT/src/agent_workflow_benchmark/schemas" -maxdepth 1 -type f -name '*.json' -exec basename {} \; | sort
    )
    while IFS= read -r path; do
      [[ -n "$path" ]] || continue
      echo "unrecognized stale benchmark schema remains in Agent-Workflow host data: $path" >&2
      stale_schema_found=1
    done < <(
      find "$host_schema_dir" -maxdepth 1 \( -type f -o -type l \) -name 'benchmark-*.schema.json' -print | sort
    )
    [[ "$stale_schema_found" -eq 0 ]] || return 1
  fi

  local candidate
  for candidate in "$VENV/bin/agent-workflow-benchmark" "$HOME/.local/bin/agent-workflow-benchmark"; do
    if [[ -e "$candidate" || -L "$candidate" ]]; then
      echo "obsolete standalone benchmark launcher remains: $candidate" >&2
      return 1
    fi
  done

  verify_core_share_artifacts
}

cleanup_stale_host_artifacts() {
  local data_home host_schema_dir path
  data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
  host_schema_dir="$data_home/agent-workflow/schemas"

  if [[ -d "$host_schema_dir" ]]; then
    while IFS= read -r path; do
      [[ -n "$path" ]] || continue
      echo "removing stale core-era benchmark schema: $path"
      rm -f "$path"
    done < <(
      find "$host_schema_dir" -maxdepth 1 \( -type f -o -type l \) -name 'benchmark-*.schema.json' -print | sort
    )
  fi

  cleanup_core_share_artifacts

  local candidate content
  for candidate in "$VENV/bin/agent-workflow-benchmark" "$HOME/.local/bin/agent-workflow-benchmark"; do
    [[ -e "$candidate" || -L "$candidate" ]] || continue
    if [[ -L "$candidate" ]]; then
      content="$(readlink "$candidate" || true)"
      if [[ "$content" == *agent-workflow-benchmark* || "$content" == *agent_workflow_benchmark* ]]; then
        echo "removing obsolete benchmark launcher symlink: $candidate"
        rm -f "$candidate"
        continue
      fi
    elif [[ -f "$candidate" ]]; then
      if grep -q 'agent_workflow_benchmark' "$candidate" 2>/dev/null; then
        echo "removing obsolete benchmark launcher: $candidate"
        rm -f "$candidate"
        continue
      fi
    fi
    echo "refusing to remove unrelated path matching obsolete benchmark launcher name: $candidate" >&2
    exit 1
  done

  verify_host_artifacts
}

verify_installed_state() {
  "$PYTHON" - "$ROOT" "$EXPECTED_VERSION" <<'PY'
from __future__ import annotations

from importlib import metadata, resources
from pathlib import Path
import hashlib
import json
import sys
import sysconfig
import tomllib

root = Path(sys.argv[1]).resolve()
expected_version = sys.argv[2]
purelib = Path(sysconfig.get_paths()["purelib"]).resolve()

try:
    aw = metadata.distribution("agent-workflow")
    benchmark = metadata.distribution("agent-workflow-benchmark")
except metadata.PackageNotFoundError as exc:
    raise SystemExit(f"required distribution missing from shared virtualenv: {exc}") from exc

def within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False

for dist in (aw, benchmark):
    location = Path(dist.locate_file("")).resolve()
    if not within(location, purelib):
        raise SystemExit(
            f"{dist.metadata['Name']} resolves outside shared virtualenv site-packages: {location}"
        )

if benchmark.version != expected_version:
    raise SystemExit(
        f"benchmark version mismatch: expected {expected_version}, installed {benchmark.version}"
    )
direct_url_raw = benchmark.read_text("direct_url.json")
if direct_url_raw:
    direct_url = json.loads(direct_url_raw)
    if direct_url.get("dir_info", {}).get("editable") is True:
        raise SystemExit("benchmark package is unexpectedly installed editable; wheel install required")

source_schema_root = root / "src" / "agent_workflow_benchmark" / "schemas"
source = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(source_schema_root.glob("*.json"))
}
installed_root = resources.files("agent_workflow_benchmark").joinpath("schemas")
installed = {
    item.name: hashlib.sha256(item.read_bytes()).hexdigest()
    for item in installed_root.iterdir()
    if item.name.endswith(".json")
}
if source != installed:
    missing = sorted(set(source) - set(installed))
    extra = sorted(set(installed) - set(source))
    changed = sorted(
        name for name in set(source) & set(installed) if source[name] != installed[name]
    )
    raise SystemExit(
        "installed benchmark schema manifest differs from source; "
        f"missing={missing}, extra={extra}, changed={changed}"
    )

source_ids = {}
for path in sorted(source_schema_root.glob("*.json")):
    value = json.loads(path.read_text(encoding="utf-8"))
    schema_id = value.get("$id")
    if schema_id:
        source_ids[schema_id] = path.name

from agent_workflow_benchmark.plugin import __version__, plugin
if __version__ != expected_version:
    raise SystemExit(
        f"plugin module version mismatch: expected {expected_version}, module {__version__}"
    )
descriptor = plugin()
if descriptor.version != expected_version:
    raise SystemExit(
        f"plugin descriptor version mismatch: expected {expected_version}, descriptor {descriptor.version}"
    )
resource_ids = {
    item.identifier
    for item in descriptor.package_resources
    if item.kind == "schema"
}
if resource_ids != set(source_ids):
    raise SystemExit(
        "plugin schema resource registration differs from installed/source schemas; "
        f"missing={sorted(set(source_ids) - resource_ids)}, "
        f"extra={sorted(resource_ids - set(source_ids))}"
    )

entry_points = [
    item
    for item in metadata.entry_points(group="agent_workflow.plugins")
    if item.name == "agent-workflow-benchmark"
]
if len(entry_points) != 1:
    raise SystemExit(
        f"expected exactly one agent-workflow-benchmark plugin entry point, found {len(entry_points)}"
    )
entry = entry_points[0]
if entry.value != "agent_workflow_benchmark.plugin:plugin":
    raise SystemExit(f"unexpected benchmark plugin entry point: {entry.value}")
if getattr(entry, "dist", None) is not None and entry.dist.version != expected_version:
    raise SystemExit(
        f"entry-point distribution version mismatch: {entry.dist.version} != {expected_version}"
    )

console_scripts = [
    item.name
    for item in metadata.entry_points(group="console_scripts")
    if getattr(item, "dist", None) is not None
    and item.dist.metadata.get("Name", "").lower().replace("_", "-")
    == "agent-workflow-benchmark"
]
if console_scripts:
    raise SystemExit(
        f"agent-workflow-benchmark unexpectedly owns console scripts: {sorted(console_scripts)}"
    )

dist_infos = sorted(purelib.glob("agent_workflow_benchmark-*.dist-info"))
egg_infos = sorted(purelib.glob("agent_workflow_benchmark*.egg-info"))
if len(dist_infos) != 1:
    raise SystemExit(
        "stale benchmark dist-info detected: "
        + ", ".join(str(path) for path in dist_infos)
    )
if egg_infos:
    raise SystemExit(
        "stale benchmark egg-info detected: "
        + ", ".join(str(path) for path in egg_infos)
    )

print(
    f"verified shared install: agent-workflow={aw.version}, "
    f"agent-workflow-benchmark={benchmark.version}, schemas={len(installed)}"
)
PY

  verify_path_shadowing

  local tmp_config plugins_json
  tmp_config="$(mktemp "${TMPDIR:-/tmp}/aw-benchmark-plugin-list.XXXXXX")"
  cat >"$tmp_config" <<'EOF'
schema_version = 1

[plugins]
enabled = ["agent-workflow-benchmark"]
EOF
  plugins_json="$("$AW_LAUNCHER" --config "$tmp_config" --json plugins list)"
  "$AW_LAUNCHER" --config "$tmp_config" benchmark --help >/dev/null
  rm -f "$tmp_config"
  PLUGINS_JSON="$plugins_json" "$PYTHON" - "$EXPECTED_VERSION" <<'PY'
import json
import os
import sys

expected = sys.argv[1]
payload = json.loads(os.environ["PLUGINS_JSON"])
rows = [
    row for row in payload.get("plugins", [])
    if row.get("name") == "agent-workflow-benchmark"
]
if len(rows) != 1:
    raise SystemExit(
        f"Agent-Workflow plugin inventory expected one benchmark candidate, found {len(rows)}"
    )
row = rows[0]
if row.get("distribution") != "agent-workflow-benchmark":
    raise SystemExit(f"unexpected plugin distribution: {row.get('distribution')}")
if row.get("distribution_version") != expected:
    raise SystemExit(
        f"plugin inventory version mismatch: {row.get('distribution_version')} != {expected}"
    )
if row.get("enabled") is not True or row.get("loaded") is not True:
    raise SystemExit(
        "benchmark plugin entry point was discovered but did not load when explicitly enabled"
    )
print(
    "verified Agent-Workflow plugin discovery and command registration: "
    f"enabled={row.get('enabled')} loaded={row.get('loaded')} version={expected}"
)
PY

  verify_semantic_runtime
}

if [[ "$VERIFY_ONLY" -eq 1 ]]; then
  verify_semantic_runtime
  verify_host_artifacts
  verify_installed_state
  exit 0
fi

ensure_semantic_dependencies

if ! "$PYTHON" -c 'import build' >/dev/null 2>&1; then
  if [[ "$BOOTSTRAP_BUILD" -ne 1 ]]; then
    echo "Python package 'build' is missing from $VENV; rerun without --no-bootstrap-build" >&2
    exit 1
  fi
  echo "installing build tooling into shared virtualenv"
  "$PYTHON" -m pip install --upgrade 'build>=1,<2'
fi

echo "cleaning repository build artifacts"
rm -rf "$ROOT/build" "$ROOT/dist" "$ROOT/src/agent_workflow_benchmark.egg-info"

echo "building benchmark wheel"
(
  cd "$ROOT"
  "$PYTHON" -m build --wheel
)

WHEELS=()
while IFS= read -r wheel_path; do
  [[ -n "$wheel_path" ]] || continue
  WHEELS+=("$wheel_path")
done < <(find "$ROOT/dist" -maxdepth 1 -type f -name 'agent_workflow_benchmark-*.whl' -print | sort)
if [[ "${#WHEELS[@]}" -ne 1 ]]; then
  echo "expected exactly one benchmark wheel, found ${#WHEELS[@]}" >&2
  printf '  %s\n' "${WHEELS[@]}" >&2
  exit 1
fi
WHEEL="${WHEELS[0]}"
echo "built wheel: $WHEEL"

"$PYTHON" - "$ROOT" "$WHEEL" "$EXPECTED_VERSION" <<'PY'
from pathlib import Path
from zipfile import ZipFile
from email.parser import Parser
import configparser
import hashlib
import io
import sys

root = Path(sys.argv[1]).resolve()
wheel = Path(sys.argv[2]).resolve()
expected_version = sys.argv[3]
source_root = root / "src" / "agent_workflow_benchmark" / "schemas"
source = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(source_root.glob("*.json"))
}

with ZipFile(wheel) as archive:
    names = archive.namelist()
    metadata_name = next(
        name for name in names
        if name.endswith(".dist-info/METADATA")
    )
    metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
    if metadata["Name"] != "agent-workflow-benchmark":
        raise SystemExit(f"unexpected wheel project name: {metadata['Name']}")
    if metadata["Version"] != expected_version:
        raise SystemExit(
            f"wheel version mismatch: {metadata['Version']} != {expected_version}"
        )
    installed = {}
    prefix = "agent_workflow_benchmark/schemas/"
    for name in names:
        if name.startswith(prefix) and name.endswith(".json"):
            installed[Path(name).name] = hashlib.sha256(archive.read(name)).hexdigest()
    if source != installed:
        raise SystemExit(
            "wheel schema manifest differs from source; "
            f"missing={sorted(set(source)-set(installed))}, "
            f"extra={sorted(set(installed)-set(source))}"
        )

    entry_name = next(
        (name for name in names if name.endswith(".dist-info/entry_points.txt")),
        None,
    )
    if entry_name is None:
        raise SystemExit("wheel is missing entry_points.txt")
    parser = configparser.ConfigParser()
    parser.read_file(io.StringIO(archive.read(entry_name).decode("utf-8")))
    plugin_entries = dict(parser["agent_workflow.plugins"]) if parser.has_section("agent_workflow.plugins") else {}
    if plugin_entries != {
        "agent-workflow-benchmark": "agent_workflow_benchmark.plugin:plugin"
    }:
        raise SystemExit(f"unexpected plugin entry points in wheel: {plugin_entries}")
    console_entries = dict(parser["console_scripts"]) if parser.has_section("console_scripts") else {}
    if console_entries:
        raise SystemExit(f"benchmark wheel unexpectedly contains console scripts: {console_entries}")

print(f"verified wheel before install: version={expected_version}, schemas={len(source)}")
PY

echo "removing previous benchmark distribution from shared virtualenv"
"$PYTHON" -m pip uninstall -y agent-workflow-benchmark >/dev/null 2>&1 || true

cleanup_stale_host_artifacts

"$PYTHON" - <<'PY'
from pathlib import Path
import shutil
import sys
import sysconfig

purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
bin_dir = Path(sys.executable).resolve().parent

owned = [purelib / "agent_workflow_benchmark"]
owned.extend(sorted(purelib.glob("agent_workflow_benchmark-*.dist-info")))
owned.extend(sorted(purelib.glob("agent_workflow_benchmark*.egg-info")))
for path in owned:
    if not path.exists() and not path.is_symlink():
        continue
    print(f"removing stale benchmark-owned path: {path}")
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()

for name in ("agent-workflow-benchmark", "agent-workflow-benchmark.exe", "agent-workflow-benchmark-script.py"):
    path = bin_dir / name
    if path.exists() or path.is_symlink():
        print(f"removing obsolete benchmark launcher: {path}")
        path.unlink()
PY

echo "installing benchmark wheel into shared Agent-Workflow virtualenv"
"$PYTHON" -m pip install --no-deps --force-reinstall "$WHEEL"

verify_host_artifacts
verify_installed_state

echo
echo "agent-workflow-benchmark install verified"
echo "  virtualenv: $VENV"
echo "  Agent-Workflow: $("$AW_LAUNCHER" --version)"
echo "  benchmark: $EXPECTED_VERSION"
echo "  wheel: $WHEEL"
echo "  config: $XDG_CONFIG_HOME/agent-workflow/config.toml"
echo "  state: $XDG_STATE_HOME/agent-workflow"
echo "  data: $XDG_DATA_HOME/agent-workflow"

#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
source "$SCRIPT_DIR/lib.sh"

aj_require_executable "$PYTHON"

label="${1:-${AGENTIC_JEV_ARCHIVE_LABEL:-}}"
if [[ -z "$label" ]]; then
  label="$(date -u +%Y%m%dT%H%M%SZ)"
fi
if [[ ! "$label" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$ ]]; then
  echo "invalid archive label: $label" >&2
  exit 2
fi

archive_root="${AGENTIC_JEV_ARCHIVE_ROOT:-$AGENTIC_JEV_ROOT/archive}"

"$PYTHON" - \
  "$AGENTIC_JEV_ROOT" \
  "$AGENTIC_JEV_RUNTIME_LOCK" \
  "$AGENTIC_JEV_QUAL_ROOT" \
  "$AGENTIC_JEV_RUN" \
  "$archive_root" \
  "$label" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

root_s, lock_s, qual_s, run_s, archive_root_s, label = sys.argv[1:]
root = Path(root_s).expanduser().resolve()
lock = Path(lock_s).expanduser().resolve()
qual = Path(qual_s).expanduser().resolve()
pilot_run = Path(run_s).expanduser().resolve()
archive_root = Path(archive_root_s).expanduser().resolve()

def under_root(path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

for name, path in (("runtime lock", lock), ("qualification root", qual), ("archive root", archive_root)):
    if not under_root(path):
        raise SystemExit(f"{name} must remain under AGENTIC_JEV_ROOT: {path}")

if pilot_run.exists():
    raise SystemExit(
        "refusing Phase-0 archive because pilot-run evidence already exists; "
        "this command is only for pre-pilot qualification attempts"
    )

qualification_path = qual / "qualification.json"
qualification_state: bool | None = None
if qualification_path.is_file():
    try:
        qualification_value = json.loads(qualification_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"unable to read qualification state before archive: {qualification_path}: {exc}"
        ) from exc
    observed = qualification_value.get("qualified") if isinstance(qualification_value, dict) else None
    if isinstance(observed, bool):
        qualification_state = observed

if qualification_state is True and os.environ.get("AGENTIC_JEV_ARCHIVE_PASSING") != "1":
    raise SystemExit(
        "refusing to archive a passing Phase-0 qualification; it is the live "
        "authorization for Phase 1. Set AGENTIC_JEV_ARCHIVE_PASSING=1 only when "
        "a passing qualification is intentionally superseded by a runtime/code change."
    )

lock_exists = lock.is_file()
qual_exists = qual.is_dir() and any(qual.iterdir())
if not lock_exists and not qual_exists:
    raise SystemExit("no Phase-0 runtime lock or qualification evidence exists to archive")

archive_root.mkdir(parents=True, exist_ok=True)
os.chmod(archive_root, 0o700)
target = archive_root / label
if target.exists():
    raise SystemExit(f"archive target already exists: {target}")

tmp = archive_root / f".{label}.tmp-{os.getpid()}"
if tmp.exists():
    raise SystemExit(f"temporary archive path already exists: {tmp}")
tmp.mkdir(mode=0o700)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

try:
    manifest: dict[str, object] = {
        "schema": "agent-workflow-benchmark/agentic-jev-phase0-archive/v1",
        "study_id": "agentic-jev-pilot-v1",
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "sources": {},
    }

    if lock_exists:
        dst = tmp / "runtime-lock.json"
        shutil.copy2(lock, dst)
        manifest["sources"]["runtime_lock"] = {
            "source": str(lock),
            "sha256": sha256_file(dst),
        }

    if qual_exists:
        dst = tmp / "tool-qualification"
        shutil.copytree(qual, dst, symlinks=False)
        qjson = dst / "qualification.json"
        manifest["sources"]["qualification"] = {
            "source": str(qual),
            "qualification_sha256": sha256_file(qjson) if qjson.is_file() else None,
            "qualified": qualification_state,
            "files": sum(1 for item in dst.rglob("*") if item.is_file()),
        }

    manifest_path = tmp / "archive-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Publish the complete archive before removing live Phase-0 paths. If later
    # cleanup fails, duplicate evidence is safer than lost evidence.
    os.replace(tmp, target)

    if lock_exists:
        lock.unlink()
    if qual_exists:
        shutil.rmtree(qual)

except BaseException:
    if tmp.exists():
        shutil.rmtree(tmp)
    raise

print("Agentic Jev Phase-0 evidence archived")
print(target)
print(target / "archive-manifest.json")
PY

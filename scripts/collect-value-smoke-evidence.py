#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import tempfile


ARCHIVE_ROOT = "agent-workflow-value-smoke-evidence"


def _load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _resolve_run_dir(smoke: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve()
    for name in ("run.json", "plan.json"):
        value = _load_object(smoke / name)
        run_dir = value.get("run_dir")
        if isinstance(run_dir, str) and run_dir:
            return Path(run_dir).expanduser().resolve()
        coordinator = value.get("coordinator")
        if isinstance(coordinator, dict):
            run_dir = coordinator.get("run_dir")
            if isinstance(run_dir, str) and run_dir:
                return Path(run_dir).expanduser().resolve()
    plan = _load_object(smoke / "plan.json")
    run_plan = plan.get("run_plan")
    if isinstance(run_plan, str) and run_plan:
        path = Path(run_plan).expanduser()
        if not path.is_absolute():
            path = smoke / path
        value = _load_object(path)
        coordinator = value.get("coordinator")
        if isinstance(coordinator, dict):
            run_dir = coordinator.get("run_dir")
            if isinstance(run_dir, str) and run_dir:
                return Path(run_dir).expanduser().resolve()
    return None


def _latest_smoke(tmp_root: Path) -> Path:
    candidates = [p for p in tmp_root.glob("agent-workflow-value-smoke.*") if p.is_dir()]
    if not candidates:
        raise SystemExit(f"no value-smoke directory found under {tmp_root}")
    return max(candidates, key=lambda p: p.stat().st_mtime_ns).resolve()


def _dist_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "NOT INSTALLED"


def _command(name: str) -> str:
    value = shutil.which(name)
    return str(Path(value).resolve()) if value else "NOT FOUND"


def _environment_text() -> str:
    lines = [
        "=== COLLECTION TIME ===",
        datetime.now(timezone.utc).isoformat(),
        "",
        "=== PLATFORM ===",
        platform.platform(),
        "",
        "=== PYTHON ===",
        f"executable={Path(sys.executable).resolve()}",
        f"prefix={Path(sys.prefix).resolve()}",
        "",
        "=== COMMANDS ===",
        f"agent-workflow={_command('agent-workflow')}",
        f"codex={_command('codex')}",
        "",
        "=== PACKAGES ===",
        f"agent-workflow={_dist_version('agent-workflow')}",
        f"agent-workflow-benchmark={_dist_version('agent-workflow-benchmark')}",
        f"agent-workflow-comparative-eval={_dist_version('agent-workflow-comparative-eval')}",
        "",
        "=== CREDENTIAL PRESENCE ===",
        f"TYPESAFE_API_KEY={'configured' if os.environ.get('TYPESAFE_API_KEY') else 'missing'}",
        "",
        "=== RUNTIME PATHS ===",
    ]
    for name in (
        "VIRTUAL_ENV",
        "AGENT_WORKFLOW_VENV",
        "AGENT_WORKFLOW_BIN",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "XDG_DATA_HOME",
    ):
        lines.append(f"{name}={os.environ.get(name, 'unset')}")
    return "\n".join(lines) + "\n"


def _contains_secret(path: Path, secret: bytes) -> bool:
    overlap = max(0, len(secret) - 1)
    tail = b""
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    return False
                data = tail + chunk
                if secret in data:
                    return True
                tail = data[-overlap:] if overlap else b""
    except OSError:
        return False


def _iter_regular_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            yield path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect a completed or failed value-smoke run into one durable archive."
    )
    parser.add_argument("smoke_root", nargs="?", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--tmp-root",
        type=Path,
        default=Path(os.environ.get("TMPDIR", "/tmp")),
        help="directory used for automatic latest-smoke discovery",
    )
    args = parser.parse_args()

    smoke = (
        args.smoke_root.expanduser().resolve()
        if args.smoke_root is not None
        else _latest_smoke(args.tmp_root.expanduser().resolve())
    )
    if not smoke.is_dir():
        raise SystemExit(f"smoke root does not exist: {smoke}")
    run_dir = _resolve_run_dir(smoke, args.run_dir)
    if run_dir is not None and not run_dir.is_dir():
        print(f"warning: resolved run directory does not exist: {run_dir}", file=sys.stderr)
        run_dir = None

    run = _load_object(smoke / "run.json")
    plan = _load_object(smoke / "plan.json")
    run_id = run.get("run_id") or plan.get("run_id") or smoke.name
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (
        args.output.expanduser().resolve()
        if args.output is not None
        else (Path.cwd() / f"agent-workflow-value-smoke-evidence-{run_id}-{timestamp}.tar.gz").resolve()
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    secret = os.environ.get("TYPESAFE_API_KEY", "").encode()
    sources: list[tuple[str, Path]] = [("smoke", smoke)]
    if run_dir is not None and not _inside(run_dir, smoke):
        sources.append(("run", run_dir))

    if secret:
        hits: list[str] = []
        for label, root in sources:
            for path in _iter_regular_files(root):
                if _contains_secret(path, secret):
                    hits.append(f"{label}/{path.relative_to(root).as_posix()}")
        if hits:
            print(
                "refusing to archive: current TYPESAFE_API_KEY value appears in collected files:",
                file=sys.stderr,
            )
            for hit in hits:
                print(f"  - {hit}", file=sys.stderr)
            raise SystemExit(3)

    manifest = {
        "schema": "agent-workflow-benchmark/value-smoke-evidence-collection/v1",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "source": {
            "smoke_root": str(smoke),
            "run_dir": str(run_dir) if run_dir is not None else None,
            "run_dir_in_smoke_root": bool(run_dir is not None and _inside(run_dir, smoke)),
        },
        "files_present": {
            name: (smoke / name).is_file()
            for name in ("readiness.json", "plan.json", "run.json")
        },
        "summary": {
            "readiness_ready": _load_object(smoke / "readiness.json").get("ready"),
            "run_state": run.get("state"),
            "execution_only": run.get("execution_only"),
            "report": run.get("report"),
        },
        "collection_environment": {
            "typesafe_api_key_configured": bool(secret),
            "virtual_env": os.environ.get("VIRTUAL_ENV"),
            "agent_workflow_venv": os.environ.get("AGENT_WORKFLOW_VENV"),
            "xdg_config_home": os.environ.get("XDG_CONFIG_HOME"),
            "xdg_state_home": os.environ.get("XDG_STATE_HOME"),
            "xdg_data_home": os.environ.get("XDG_DATA_HOME"),
        },
    }

    with tempfile.TemporaryDirectory(prefix="aw-value-evidence-") as temp:
        meta = Path(temp)
        manifest_path = meta / "manifest.json"
        environment_path = meta / "environment.txt"
        sums_path = meta / "SHA256SUMS"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        environment_path.write_text(_environment_text(), encoding="utf-8")

        sums: list[str] = []
        for label, root in sources:
            for path in _iter_regular_files(root):
                rel = Path(label) / path.relative_to(root)
                sums.append(f"{_sha256(path)}  {rel.as_posix()}")
        sums.append(f"{_sha256(manifest_path)}  manifest.json")
        sums.append(f"{_sha256(environment_path)}  environment.txt")
        sums_path.write_text("\n".join(sums) + "\n", encoding="utf-8")

        with tarfile.open(output, "w:gz", dereference=False) as archive:
            archive.add(manifest_path, arcname=f"{ARCHIVE_ROOT}/manifest.json")
            archive.add(environment_path, arcname=f"{ARCHIVE_ROOT}/environment.txt")
            archive.add(sums_path, arcname=f"{ARCHIVE_ROOT}/SHA256SUMS")
            for label, root in sources:
                archive.add(root, arcname=f"{ARCHIVE_ROOT}/{label}", recursive=True)

    print("value-smoke evidence collection complete")
    print(f"  smoke:   {smoke}")
    print(f"  run_dir: {run_dir or 'not resolved'}")
    print(f"  archive: {output}")
    print(f"  sha256:  {_sha256(output)}")
    print(f"  bytes:   {output.stat().st_size}")


if __name__ == "__main__":
    main()

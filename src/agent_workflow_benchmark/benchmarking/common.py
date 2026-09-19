from __future__ import annotations

import json
import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.util import (
    atomic_write_bytes,
    atomic_write_json,
    canonical_json_sha256 as _canonical_json_sha256,
    sha256_file,
    sha256_text as text_sha256,
)


def canonical_json_sha256(value: Any) -> str:
    return _canonical_json_sha256(value, ensure_ascii=False)


def safe_relative(value: str, label: str = "path") -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise WorkflowError(f"{label} must be a normalized relative path: {value!r}")
    return value


def child(root: Path, relative: str, label: str = "path") -> Path:
    safe_relative(relative, label)
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkflowError(f"{label} escapes root: {relative!r}") from exc
    return candidate


def require_child(root: Path, candidate: Path, label: str = "path") -> Path:
    root = root.resolve()
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkflowError(f"{label} escapes root: {candidate}") from exc
    return candidate


def copy_tree(source: Path, destination: Path, *, ignore: Iterable[str] = ()) -> None:
    source = source.resolve()
    ignored = set(ignore)
    if not source.is_dir():
        raise WorkflowError(f"source directory not found: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    for current, directories, files in os.walk(source, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(source)
        directories[:] = sorted(
            name
            for name in directories
            if name not in ignored and not (current_path / name).is_symlink()
        )
        target_dir = destination / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            if name in ignored:
                continue
            item = current_path / name
            if item.is_symlink() or not item.is_file():
                raise WorkflowError(f"benchmark suite contains unsupported entry: {item}")
            target = target_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def tree_sha256(root: Path, *, exclude: Iterable[str] = ()) -> str:
    return canonical_json_sha256(file_inventory(root, exclude=exclude))


def file_inventory(root: Path, *, exclude: Iterable[str] = ()) -> list[dict[str, Any]]:
    root = root.resolve()
    excluded = tuple(PurePosixPath(item) for item in exclude)
    records: list[dict[str, Any]] = []
    if not root.exists():
        return records
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise WorkflowError(f"symlink is not permitted in benchmark evidence: {path}")
        if not path.is_file():
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if "__pycache__" in relative.parts or relative.suffix == ".pyc":
            continue
        if any(relative == item or item in relative.parents for item in excluded):
            continue
        records.append(
            {
                "path": relative.as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    return records


def write_manifest(root: Path, *, filename: str = "MANIFEST.sha256") -> Path:
    inventory = file_inventory(root, exclude=(filename,))
    lines = [f"{item['sha256']}  {item['path']}" for item in inventory]
    path = root / filename
    atomic_write_bytes(path, (("\n".join(lines) + "\n") if lines else "").encode("utf-8"))
    return path


def verify_manifest(root: Path, *, filename: str = "MANIFEST.sha256") -> dict[str, Any]:
    path = root / filename
    if not path.is_file():
        raise WorkflowError(f"benchmark manifest is missing: {path}")
    expected: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != 64:
            raise WorkflowError(f"invalid benchmark manifest line {number}")
        safe_relative(relative, "manifest path")
        expected[relative] = digest
    actual = {
        item["path"]: item["sha256"]
        for item in file_inventory(root, exclude=(filename,))
    }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(
        relative for relative in set(expected) & set(actual) if expected[relative] != actual[relative]
    )
    return {
        "valid": not (missing or extra or changed),
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "files": len(expected),
    }


def format_argv(template: Iterable[str], values: Mapping[str, str]) -> list[str]:
    result: list[str] = []
    for item in template:
        try:
            rendered = str(item).format_map(values)
        except KeyError as exc:
            raise WorkflowError(f"unknown benchmark command placeholder: {exc.args[0]}") from exc
        if not rendered:
            raise WorkflowError("benchmark command rendered an empty argv item")
        result.append(rendered)
    if not result:
        raise WorkflowError("benchmark command cannot be empty")
    return result


def write_contract(path: Path, value: dict[str, Any]) -> None:
    atomic_write_json(path, value)


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkflowError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"expected JSON object in {path}")
    return value

from __future__ import annotations

import importlib.metadata
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.process import run
from agent_workflow.util import atomic_write_json, sha256_file, utc_now
from .common import read_object

VISUAL_EVIDENCE_SCHEMA = "agent-workflow/benchmark-visual-evidence/v1"
_BROWSER_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){3}\b")


def _find_font(filename: str) -> Path | None:
    roots = (
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".local/share/fonts",
        Path.home() / ".fonts",
    )
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in root.rglob(filename):
            if candidate.is_file():
                return candidate.resolve()
    return None


def _browser_version(executable: Path | None) -> str | None:
    if executable is None:
        return None
    result = run([str(executable), "--version"], check=False, timeout_seconds=30)
    text = str(result.stdout or result.stderr or "")
    match = _BROWSER_VERSION_RE.search(text)
    return match.group(0) if result.returncode == 0 and match else None


def validate_runtime_lock(lock: Mapping[str, Any], *, claim_level: str) -> None:
    required = (
        "schema", "reproducibility_state", "playwright_version", "browser_product",
        "browser_version", "browser_executable_candidates", "font_manifest", "container_image",
    )
    missing = [key for key in required if key not in lock]
    if missing:
        raise WorkflowError("visual runtime lock is missing: " + ", ".join(missing))
    if claim_level == "publication":
        image = lock.get("container_image")
        if not isinstance(image, str) or "@sha256:" not in image:
            raise WorkflowError("publication visual runtime requires a content-addressed container image")
        digest = image.rsplit("@sha256:", 1)[-1]
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise WorkflowError("publication visual container image digest is invalid")
        if not lock.get("browser_executable_sha256"):
            raise WorkflowError("publication visual runtime requires browser_executable_sha256")
        for item in lock.get("font_manifest", []):
            if not isinstance(item, Mapping) or not item.get("sha256"):
                raise WorkflowError("publication visual runtime requires SHA-256 for every font")


def attest_runtime(lock_path: Path, *, claim_level: str) -> dict[str, Any]:
    lock_path = lock_path.resolve()
    lock = read_object(lock_path)
    validate_runtime_lock(lock, claim_level=claim_level)
    executable: Path | None = None
    for candidate in lock.get("browser_executable_candidates", []):
        path = Path(str(candidate))
        if path.is_file():
            executable = path.resolve()
            break
    if executable is None:
        for name in ("chromium", "chromium-browser", "google-chrome"):
            found = shutil.which(name)
            if found:
                executable = Path(found).resolve()
                break
    browser_digest = sha256_file(executable) if executable and executable.is_file() else None
    browser_version = _browser_version(executable)
    fonts: list[dict[str, Any]] = []
    for item in lock.get("font_manifest", []):
        filename = str(item.get("resolved_file", ""))
        resolved = _find_font(filename) if filename else None
        fonts.append(
            {
                "family": item.get("family"),
                "resolved_file": filename,
                "resolved_path": str(resolved) if resolved else None,
                "sha256": sha256_file(resolved) if resolved else None,
                "expected_sha256": item.get("sha256"),
            }
        )
    try:
        playwright_version = importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        playwright_version = None
    checks = {
        "playwright_version": playwright_version == lock.get("playwright_version"),
        "browser_executable_present": executable is not None,
        "browser_version": browser_version == lock.get("browser_version"),
        "browser_executable_sha256": (
            not lock.get("browser_executable_sha256")
            or browser_digest == lock.get("browser_executable_sha256")
        ),
        "font_manifest": all(
            item["resolved_path"] is not None
            and (not item["expected_sha256"] or item["sha256"] == item["expected_sha256"])
            for item in fonts
        ),
        "content_addressed_container": isinstance(lock.get("container_image"), str)
        and "@sha256:" in str(lock.get("container_image")),
    }
    development_verified = all(
        checks[key]
        for key in ("playwright_version", "browser_executable_present", "browser_version", "font_manifest")
    )
    publication_verified = development_verified and all(checks.values())
    state = (
        "publication-verified" if publication_verified
        else "development-verified" if development_verified
        else "not-verified"
    )
    return {
        "schema": "agent-workflow/visual-runtime-attestation/v1",
        "attested_at": utc_now(),
        "claim_level": claim_level,
        "runtime_lock": str(lock_path),
        "runtime_lock_sha256": sha256_file(lock_path),
        "playwright_version": playwright_version,
        "browser_executable": str(executable) if executable else None,
        "browser_version": browser_version,
        "browser_executable_sha256": browser_digest,
        "fonts": fonts,
        "container_image": lock.get("container_image"),
        "checks": checks,
        "runtime_state": state,
    }


def seal_runtime_lock(
    base_lock_path: Path,
    output_path: Path,
    *,
    container_image: str,
) -> dict[str, Any]:
    """Seal a publication runtime lock from inside the exact browser container."""
    if "@sha256:" not in container_image:
        raise WorkflowError("runtime seal requires a content-addressed container image reference")
    base = read_object(base_lock_path.resolve())
    attestation = attest_runtime(base_lock_path, claim_level="development")
    executable = attestation.get("browser_executable")
    if not executable or not attestation.get("browser_executable_sha256"):
        raise WorkflowError("cannot seal runtime without a resolved browser executable")
    if not all(item.get("sha256") for item in attestation.get("fonts", [])):
        raise WorkflowError("cannot seal runtime until every declared font resolves to a digest")
    version_result = run([str(executable), "--version"], check=False, timeout_seconds=30)
    version_text = str(version_result.stdout or version_result.stderr).strip()
    browser_version = version_text.split()[-1] if version_result.returncode == 0 and version_text else base.get("browser_version")
    sealed = {
        **base,
        "reproducibility_state": "publication-content-addressed",
        "browser_version": browser_version,
        "browser_executable_candidates": [str(executable)],
        "browser_executable_sha256": attestation["browser_executable_sha256"],
        "font_manifest": [
            {
                "family": item.get("family"),
                "resolved_file": item.get("resolved_file"),
                "resolved_path": item.get("resolved_path"),
                "sha256": item.get("sha256"),
            }
            for item in attestation["fonts"]
        ],
        "container_image": container_image,
        "publication_blocker": None,
        "sealed_at": utc_now(),
    }
    validate_runtime_lock(sealed, claim_level="publication")
    output_path = output_path.expanduser().resolve()
    atomic_write_json(output_path, sealed)
    return {
        "runtime_lock": str(output_path),
        "runtime_lock_sha256": sha256_file(output_path),
        "container_image": container_image,
        "browser_executable_sha256": sealed["browser_executable_sha256"],
        "fonts": len(sealed["font_manifest"]),
        "state": "publication-content-addressed",
    }

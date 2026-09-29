from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import inspect
from pathlib import Path
from typing import Any

INSPECT_SWE_VERSION = "0.2.71"
UPSTREAM_CODEX_CLI_GIT_BLOB_SHA1 = "a5c5f21207d2fee496b8ef775c07757e2c524725"
CAPABILITY_ID = "agent-workflow-benchmark/inspect-swe-codex-output-schema/v1"
PATCH_MARKER = f'AW_CODEX_OUTPUT_SCHEMA_COMPAT = "{CAPABILITY_ID}"'


class InspectSweOutputSchemaPatchError(RuntimeError):
    pass


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _source_path() -> Path:
    spec = importlib.util.find_spec("inspect_swe._codex_cli.codex_cli")
    if spec is None or spec.origin is None:
        raise InspectSweOutputSchemaPatchError(
            "unable to locate inspect_swe._codex_cli.codex_cli"
        )
    return Path(spec.origin)


def patch_source_text(text: str) -> str:
    if PATCH_MARKER in text:
        return text

    observed_blob = _git_blob_sha1(text.encode("utf-8"))
    if observed_blob != UPSTREAM_CODEX_CLI_GIT_BLOB_SHA1:
        raise InspectSweOutputSchemaPatchError(
            "refusing to patch unexpected inspect-swe codex_cli.py bytes: "
            f"expected git blob {UPSTREAM_CODEX_CLI_GIT_BLOB_SHA1}, "
            f"observed {observed_blob}"
        )

    replacements: list[tuple[str, str]] = [
        (
            "import mimetypes\nimport shlex\n",
            "import json\nimport mimetypes\nimport shlex\n",
        ),
        (
            'logger = getLogger(__file__)\n',
            'logger = getLogger(__file__)\n\n'
            f'{PATCH_MARKER}\n',
        ),
        (
            '    config_overrides: dict[str, str] | None = None,\n'
            '    debug: bool | None = None,\n',
            '    config_overrides: dict[str, str] | None = None,\n'
            '    output_schema: dict[str, Any] | None = None,\n'
            '    debug: bool | None = None,\n',
        ),
        (
            '        config_overrides: Additional Codex CLI configuration overrides.\n'
            '            Each key-value pair is passed as `-c key=value` to the CLI, except\n',
            '        config_overrides: Additional Codex CLI configuration overrides.\n'
            '            Each key-value pair is passed as `-c key=value` to the CLI, except\n',
        ),
        (
            '            effective value rather than silently disagreeing with the raw flag.\n'
            '        debug: Trace all debug output.\n',
            '            effective value rather than silently disagreeing with the raw flag.\n'
            '        output_schema: Optional JSON Schema for the final Codex response. When\n'
            '            provided in headless mode, the schema is written into CODEX_HOME and\n'
            '            passed to native Codex via `--output-schema`. Unsupported in centaur\n'
            '            mode because there is no single unattended final-response boundary.\n'
            '        debug: Trace all debug output.\n',
        ),
        (
            '    if centaur is True:\n'
            '        centaur = CentaurOptions()\n',
            '    if centaur is True:\n'
            '        centaur = CentaurOptions()\n'
            '    if output_schema is not None and centaur is not False:\n'
            '        raise ValueError("output_schema is only supported for headless codex exec")\n',
        ),
        (
            '            await sandbox_exec(sbox, cmd=f"mkdir -p {codex_home}", user=user)\n\n'
            '            # location for agents_md\n',
            '            await sandbox_exec(sbox, cmd=f"mkdir -p {codex_home}", user=user)\n\n'
            '            output_schema_path: str | None = None\n'
            '            if output_schema is not None:\n'
            '                output_schema_path = join_path(\n'
            '                    codex_home, "final-output.schema.json"\n'
            '                )\n'
            '                await sbox.write_file(\n'
            '                    output_schema_path,\n'
            '                    json.dumps(\n'
            '                        output_schema,\n'
            '                        sort_keys=True,\n'
            '                        separators=(",", ":"),\n'
            '                    ),\n'
            '                )\n\n'
            '            # location for agents_md\n',
        ),
        (
            '            cmd.extend(\n'
            '                [\n'
            '                    # the real model is served via the bridge; this slug only\n'
            '                    # selects Codex\'s system prompt + tool set (see codex_model above)\n'
            '                    "--model",\n'
            '                    codex_model,\n'
            '                ]\n'
            '            )\n',
            '            cmd.extend(\n'
            '                [\n'
            '                    # the real model is served via the bridge; this slug only\n'
            '                    # selects Codex\'s system prompt + tool set (see codex_model above)\n'
            '                    "--model",\n'
            '                    codex_model,\n'
            '                ]\n'
            '            )\n'
            '            if output_schema_path is not None:\n'
            '                cmd.extend(["--output-schema", output_schema_path])\n',
        ),
    ]

    patched = text
    for old, new in replacements:
        if old == new:
            continue
        if old not in patched:
            raise InspectSweOutputSchemaPatchError(
                "inspect-swe compatibility patch sentinel missing; "
                "upstream source layout changed"
            )
        patched = patched.replace(old, new, 1)

    if PATCH_MARKER not in patched or "--output-schema" not in patched:
        raise InspectSweOutputSchemaPatchError(
            "inspect-swe output-schema patch did not install expected capability"
        )
    return patched


def apply_installed_patch() -> dict[str, Any]:
    version = importlib.metadata.version("inspect-swe")
    if version != INSPECT_SWE_VERSION:
        raise InspectSweOutputSchemaPatchError(
            f"expected inspect-swe {INSPECT_SWE_VERSION}, found {version}"
        )
    path = _source_path()
    original = path.read_text(encoding="utf-8")
    patched = patch_source_text(original)
    changed = patched != original
    if changed:
        path.write_text(patched, encoding="utf-8")
    return installed_capability_info(path=path)


def installed_capability_info(*, path: Path | None = None) -> dict[str, Any]:
    version = importlib.metadata.version("inspect-swe")
    path = path or _source_path()
    text = path.read_text(encoding="utf-8")
    enabled = PATCH_MARKER in text and "--output-schema" in text
    return {
        "capability": CAPABILITY_ID,
        "enabled": enabled,
        "inspect_swe_version": version,
        "source_path": str(path),
        "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "upstream_git_blob_sha1": UPSTREAM_CODEX_CLI_GIT_BLOB_SHA1,
    }


def assert_runtime_capability() -> dict[str, Any]:
    info = installed_capability_info()
    if info["inspect_swe_version"] != INSPECT_SWE_VERSION:
        raise InspectSweOutputSchemaPatchError(
            f"expected inspect-swe {INSPECT_SWE_VERSION}, "
            f"found {info['inspect_swe_version']}"
        )
    if not info["enabled"]:
        raise InspectSweOutputSchemaPatchError(
            "inspect-swe Codex output-schema compatibility patch is not installed"
        )

    import inspect_swe

    signature = inspect.signature(inspect_swe.codex_cli)
    if "output_schema" not in signature.parameters:
        raise InspectSweOutputSchemaPatchError(
            "inspect_swe.codex_cli does not expose output_schema after patch"
        )
    return info

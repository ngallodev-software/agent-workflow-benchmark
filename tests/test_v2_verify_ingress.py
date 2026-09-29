import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "adjudication" / "v2-verify-ingress.py"


def _schema(path: Path, *, name: str) -> str:
    value = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "records": {
                "type": "array",
                "items": {"type": "object", "properties": {"name": {"const": name}}},
            }
        },
        "required": ["records"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _record(schema_sha256: str, *, strict: bool = True) -> dict:
    return {
        "method": "POST",
        "path": "/v1/responses",
        "model": "deepseek-flash",
        "text_format": {
            "type": "json_schema",
            "strict": strict,
            "schema_sha256": schema_sha256,
        },
    }


def _run(capture: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFY), "--capture", str(capture), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_v2_ingress_verifier_accepts_exact_strict_schema(tmp_path: Path):
    schema = tmp_path / "codex-output-schema.json"
    schema_sha = _schema(schema, name="primary")
    capture = tmp_path / "capture.jsonl"
    capture.write_text(json.dumps(_record(schema_sha)) + "\n", encoding="utf-8")

    result = _run(capture, "--schema", str(schema))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "structured_requests: 1" in result.stdout
    assert "json_schema_strict: pass" in result.stdout


def test_v2_ingress_verifier_rejects_non_strict_request(tmp_path: Path):
    schema = tmp_path / "codex-output-schema.json"
    schema_sha = _schema(schema, name="primary")
    capture = tmp_path / "capture.jsonl"
    capture.write_text(
        json.dumps(_record(schema_sha, strict=False)) + "\n",
        encoding="utf-8",
    )

    result = _run(capture, "--schema", str(schema))

    assert result.returncode != 0
    assert "json_schema_strict: fail" in result.stdout
    assert "strict=False" in result.stdout


def test_v2_ingress_verifier_rejects_unknown_schema_hash(tmp_path: Path):
    schema = tmp_path / "codex-output-schema.json"
    _schema(schema, name="primary")
    capture = tmp_path / "capture.jsonl"
    capture.write_text(json.dumps(_record("0" * 64)) + "\n", encoding="utf-8")

    result = _run(capture, "--schema", str(schema))

    assert result.returncode != 0
    assert "not a persisted stage schema" in result.stdout


def test_v2_ingress_verifier_requires_every_persisted_stage_schema(tmp_path: Path):
    root = tmp_path / "evidence"
    primary = root / "primary" / "codex-output-schema.json"
    c_schema = root / "tiebreaker" / "codex-output-schema.json"
    primary_sha = _schema(primary, name="primary")
    c_sha = _schema(c_schema, name="c")
    capture = tmp_path / "capture.jsonl"
    capture.write_text(
        "\n".join(
            [
                json.dumps(_record(primary_sha)),
                json.dumps(_record(c_sha)),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run(capture, "--schema-root", str(root))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "persisted_schema_hashes: 2" in result.stdout
    assert "observed_schema_hashes: 2" in result.stdout

    capture.write_text(json.dumps(_record(primary_sha)) + "\n", encoding="utf-8")
    result = _run(capture, "--schema-root", str(root))
    assert result.returncode != 0
    assert "persisted stage schema was not observed" in result.stdout

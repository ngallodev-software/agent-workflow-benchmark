from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect-value-smoke-evidence.py"


def test_collect_value_smoke_evidence_archives_smoke_and_run(tmp_path: Path) -> None:
    smoke = tmp_path / "agent-workflow-value-smoke.example"
    smoke.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "artifact.txt").write_text("evidence\n", encoding="utf-8")
    (smoke / "readiness.json").write_text(
        json.dumps({"ready": True}) + "\n",
        encoding="utf-8",
    )
    (smoke / "plan.json").write_text(
        json.dumps({"run_id": "run-1", "coordinator": {"run_dir": str(run_dir)}}) + "\n",
        encoding="utf-8",
    )
    (smoke / "run.json").write_text(
        json.dumps({"run_id": "run-1", "state": "executed", "execution_only": True}) + "\n",
        encoding="utf-8",
    )

    output = tmp_path / "evidence.tar.gz"
    env = os.environ.copy()
    env["TYPESAFE_API_KEY"] = "collector-test-secret-not-in-files"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(smoke),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.is_file()
    with tarfile.open(output, "r:gz") as archive:
        names = set(archive.getnames())
        assert "agent-workflow-value-smoke-evidence/manifest.json" in names
        assert "agent-workflow-value-smoke-evidence/environment.txt" in names
        assert "agent-workflow-value-smoke-evidence/SHA256SUMS" in names
        assert "agent-workflow-value-smoke-evidence/smoke/run.json" in names
        assert "agent-workflow-value-smoke-evidence/run/artifact.txt" in names
        manifest = json.load(
            archive.extractfile("agent-workflow-value-smoke-evidence/manifest.json")
        )
        environment = archive.extractfile(
            "agent-workflow-value-smoke-evidence/environment.txt"
        ).read().decode("utf-8")

    assert manifest["run_id"] == "run-1"
    assert manifest["summary"]["run_state"] == "executed"
    assert manifest["collection_environment"]["typesafe_api_key_configured"] is True
    assert "collector-test-secret-not-in-files" not in environment
    assert "TYPESAFE_API_KEY=configured" in environment


def test_collect_value_smoke_evidence_refuses_embedded_typesafe_key(
    tmp_path: Path,
) -> None:
    smoke = tmp_path / "smoke"
    smoke.mkdir()
    secret = "collector-embedded-secret"
    (smoke / "run.json").write_text(secret, encoding="utf-8")
    output = tmp_path / "evidence.tar.gz"
    env = os.environ.copy()
    env["TYPESAFE_API_KEY"] = secret

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(smoke), "--output", str(output)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3
    assert "refusing to archive" in result.stderr
    assert not output.exists()

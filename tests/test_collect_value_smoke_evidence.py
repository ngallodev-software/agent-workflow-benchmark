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
    arm_dir = tmp_path / "arm-control"
    arm_dir.mkdir()
    (arm_dir / "arm.json").write_text(
        json.dumps({"usage": {"token_evidence_complete": True}}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "run-plan.json").write_text(
        json.dumps(
            {
                "pairs": [
                    {
                        "pair_id": "case-r01",
                        "attempts": [
                            {
                                "attempt": 1,
                                "arms": {
                                    "control_raw": {"stage_dir": str(arm_dir)}
                                },
                            }
                        ],
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
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
    (smoke / "typesafe-api-audit.jsonl").write_text(
        json.dumps({
            "schema": "agent-workflow/typesafe-api-call/v2",
            "status": "success",
            "capture": {"raw_http_available": True, "credentials_redacted": True},
            "request": {"logical_body": {"questions": {
                "task_class": {"type": "choice"},
                "interaction_needed": {"type": "noul"},
                "semantic_risk": {"type": "score"},
            }}},
        }) + "\n",
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
        assert (
            "agent-workflow-value-smoke-evidence/arms/case-r01/attempt-01/control_raw/arm.json"
            in names
        )
        manifest = json.load(
            archive.extractfile("agent-workflow-value-smoke-evidence/manifest.json")
        )
        environment = archive.extractfile(
            "agent-workflow-value-smoke-evidence/environment.txt"
        ).read().decode("utf-8")

    assert manifest["run_id"] == "run-1"
    assert manifest["summary"]["run_state"] == "executed"
    assert manifest["summary"]["arm_evidence_roots"] == 1
    assert len(manifest["source"]["arm_evidence_roots"]) == 1
    assert manifest["collection_environment"]["typesafe_api_key_configured"] is True
    assert manifest["typesafe_audit"]["present"] is True
    assert manifest["typesafe_audit"]["records"] == 1
    assert manifest["typesafe_audit"]["schema_v2_records"] == 1
    assert manifest["typesafe_audit"]["raw_http_records"] == 1
    assert manifest["typesafe_audit"]["primitive_counts"] == {"choice": 1, "noul": 1, "score": 1}
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

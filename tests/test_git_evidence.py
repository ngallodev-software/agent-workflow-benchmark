from __future__ import annotations

from pathlib import Path
import subprocess

from agent_workflow_benchmark.benchmarking.runner import _git_evidence


def test_git_evidence_ignores_external_diff_and_captures_patch(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Benchmark"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "benchmark@example.invalid"],
        check=True,
    )
    target = repo / "example.txt"
    target.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "example.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    target.write_text("after\n", encoding="utf-8")
    stage = repo / ".agent-workflow-benchmark" / "case" / "arm"
    stage.mkdir(parents=True)

    marker = tmp_path / "external-diff-ran"
    helper = tmp_path / "external-diff.sh"
    helper.write_text(
        "#!/usr/bin/env bash\nprintf x > \"$1\"\nexit 0\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", f"{helper} {marker}")
    subprocess.run(
        ["git", "-C", str(repo), "config", "diff.external", f"{helper} {marker}"],
        check=True,
    )

    evidence = _git_evidence(
        {"base_revision": base},
        {"worktree": str(repo), "stage_dir": str(stage)},
    )

    patch = (stage / "patch.diff").read_text(encoding="utf-8")
    assert evidence["patch_bytes"] > 0
    assert evidence["patch_sha256"] != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert "example.txt" in patch
    assert "--no-ext-diff" in evidence["patch_argv"]
    assert "--no-textconv" in evidence["patch_argv"]
    assert not marker.exists()


def test_git_evidence_captures_committed_and_untracked_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Benchmark"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "benchmark@example.invalid"],
        check=True,
    )
    tracked = repo / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    tracked.write_text("committed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "task change"], check=True)
    (repo / "untracked.txt").write_text("new file\n", encoding="utf-8")
    stage = repo / ".agent-workflow-benchmark" / "case" / "arm"
    stage.mkdir(parents=True)

    evidence = _git_evidence(
        {"base_revision": base},
        {"worktree": str(repo), "stage_dir": str(stage)},
    )

    patch = (stage / "patch.diff").read_text(encoding="utf-8")
    assert evidence["head_revision"] != base
    assert evidence["tracked_changed_paths"] == ["tracked.txt"]
    assert evidence["untracked_paths"] == ["untracked.txt"]
    assert evidence["changed_paths"] == ["tracked.txt", "untracked.txt"]
    assert "tracked.txt" in patch
    assert "untracked.txt" in patch
    assert evidence["patch_bytes"] > 0

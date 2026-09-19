"""Durable live-web runtime for comparative benchmark human review.

Live servers are deliberately kept outside the sealed evidence directory.  Their
URLs are review conveniences, while screenshots, assessments, scores, and
receipts remain immutable benchmark evidence.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from agent_workflow.errors import WorkflowError
from agent_workflow.util import atomic_write_json, utc_now
from .common import format_argv, read_object
from .contracts import validate_spec
from .events import append_event
from .pairing import selected_arms


DEFAULT_HOST = "0.0.0.0"
LOOPBACK_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


def runtime_dir(plan: Mapping[str, Any]) -> Path:
    return (
        Path(plan["coordinator"]["worktree"])
        / ".agent-workflow-benchmark-runtime"
        / str(plan["run_id"])
    )


def summary_path(plan: Mapping[str, Any]) -> Path:
    return runtime_dir(plan) / "live-review.json"



def _pid_alive(pid: object) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # EPERM proves the process exists even though this principal cannot
        # signal it. Treat it as alive so cleanup never removes its worktree.
        return True
    # A terminated child can remain in /proc briefly as a zombie while its
    # reaper catches up.  It has no running process group to preserve, so do
    # not let that transient state block safe benchmark cleanup.
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        if len(fields) > 2 and fields[2] == "Z":
            return False
    except OSError:
        # Non-Linux hosts and restricted /proc mounts still have the portable
        # kill(0) answer above.
        pass
    return True


def _reachable(url: str, timeout: float = 0.75) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _free_port(host: str, *, excluded: set[int] | None = None) -> int:
    excluded = excluded or set()
    for _ in range(32):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, 0))
            port = int(probe.getsockname()[1])
        if port not in excluded:
            return port
    raise WorkflowError("unable to allocate a distinct live-review port")


def _probe_host(bind_host: str) -> str:
    return "127.0.0.1" if bind_host in {"0.0.0.0", ""} else bind_host


def _lan_host() -> str:
    configured = os.environ.get("AGENT_WORKFLOW_BENCHMARK_ADVERTISE_HOST", "").strip()
    if configured:
        return configured
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect selects the host's routed interface without sending a
        # packet. This gives human reviewers a usable LAN URL when the server
        # is bound to all interfaces.
        probe.connect(("10.255.255.255", 1))
        address = probe.getsockname()[0]
        if address:
            return address
    except OSError:
        pass
    finally:
        probe.close()
    try:
        address = socket.gethostbyname(socket.gethostname())
        if address not in LOOPBACK_HOSTS:
            return address
    except OSError:
        pass
    return "127.0.0.1"


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _server_config(spec: Mapping[str, Any]) -> dict[str, Any]:
    configured = spec.get("live_review")
    if isinstance(configured, Mapping):
        return {
            "server_argv": [str(item) for item in configured["server_argv"]],
            "host": str(configured.get("host", DEFAULT_HOST)),
            "advertise_host": str(configured.get("advertise_host", "")),
            "ready_path": str(configured.get("ready_path", "/")),
            "startup_timeout_seconds": float(configured.get("startup_timeout_seconds", 15)),
        }
    # Operational compatibility for the legacy Priority Picker suite.  This does
    # not reinterpret v1 scoring or historical evidence.
    return {
        "server_argv": [
            "{python}",
            "-m",
            "priority_picker.server",
            "--host",
            "{host}",
            "--port",
            "{port}",
            "--data",
            "{worktree}/data/backlog.json",
        ],
        "host": DEFAULT_HOST,
        "advertise_host": "",
        "ready_path": "/api/items",
        "startup_timeout_seconds": 15.0,
    }


def _terminate(entry: Mapping[str, Any]) -> bool:
    pid = entry.get("pid")
    if not _pid_alive(pid):
        return True
    assert isinstance(pid, int)
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return not _pid_alive(pid)
    deadline = time.monotonic() + 3.0
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return not _pid_alive(pid)


def _entry_state(entry: Mapping[str, Any]) -> dict[str, Any]:
    alive = _pid_alive(entry.get("pid"))
    ready_url = str(entry.get("ready_url") or entry.get("url") or "")
    reachable = alive and bool(ready_url) and _reachable(ready_url)
    raw_state = str(entry.get("state") or "")
    if reachable:
        state = "ready"
    elif alive:
        state = "degraded"
    elif raw_state == "failed":
        state = "failed"
    else:
        state = "stopped"
    return {**dict(entry), "alive": alive, "reachable": reachable, "state": state}


def live_review_status(plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path.resolve())
    path = summary_path(plan)
    if not path.is_file():
        return {
            "run_id": plan["run_id"],
            "state": "not_started",
            "runtime_dir": str(runtime_dir(plan)),
            "apps": [],
            "ready": 0,
            "total": 0,
        }
    value = read_object(path)
    apps = [_entry_state(item) for item in value.get("apps", []) if isinstance(item, Mapping)]
    ready = sum(1 for item in apps if item["state"] == "ready")
    states = {str(item["state"]) for item in apps}
    if apps and ready == len(apps):
        runtime_state = "ready"
    elif apps and states <= {"stopped"}:
        runtime_state = "stopped"
    elif apps and states <= {"failed", "stopped"} and "failed" in states:
        runtime_state = "failed"
    else:
        runtime_state = "degraded"
    return {
        **value,
        "apps": apps,
        "ready": ready,
        "total": len(apps),
        "state": runtime_state,
    }


def _launch_one(
    plan: Mapping[str, Any],
    spec: Mapping[str, Any],
    pair: Mapping[str, Any],
    arm: Mapping[str, Any],
    *,
    host: str,
    port: int,
    root: Path,
) -> dict[str, Any]:
    config = _server_config(spec)
    pair_id = str(pair["pair_id"])
    arm_name = str(arm["arm"])
    app_dir = root / pair_id / arm_name
    app_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = app_dir / "server.stdout.log"
    stderr_path = app_dir / "server.stderr.log"
    values = {
        "python": sys.executable,
        "run_id": str(plan["run_id"]),
        "benchmark_id": str(plan["benchmark_id"]),
        "pair_id": pair_id,
        "case_id": str(pair["case_id"]),
        "arm": arm_name,
        "host": host,
        "port": str(port),
        "worktree": str(arm["worktree"]),
        "stage_dir": str(arm["stage_dir"]),
        "suite": str(plan["coordinator"]["suite_dir"]),
        "runtime_dir": str(app_dir),
    }
    argv = format_argv(config["server_argv"], values)
    advertise_host = str(config.get("advertise_host") or "").strip() or (
        _lan_host() if host in {"0.0.0.0", ""} else host
    )
    base_url = f"http://{_url_host(advertise_host)}:{port}"
    ready_path = str(config["ready_path"])
    local_url = f"http://{_url_host(_probe_host(host))}:{port}"
    ready_url = local_url + (ready_path if ready_path.startswith("/") else "/" + ready_path)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "AGENT_WORKFLOW_BENCHMARK_RUN_ID": str(plan["run_id"]),
        "AGENT_WORKFLOW_BENCHMARK_PAIR_ID": pair_id,
        "AGENT_WORKFLOW_BENCHMARK_ARM": arm_name,
        "AGENT_WORKFLOW_BENCHMARK_LIVE_URL": base_url,
    }
    started_at = utc_now()
    with stdout_path.open("ab", buffering=0) as stdout_file, stderr_path.open("ab", buffering=0) as stderr_file:
        process = subprocess.Popen(
            argv,
            cwd=str(arm["worktree"]),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
        )
    deadline = time.monotonic() + float(config["startup_timeout_seconds"])
    while process.poll() is None and time.monotonic() < deadline:
        if _reachable(ready_url):
            break
        time.sleep(0.1)
    ready = process.poll() is None and _reachable(ready_url)
    entry = {
        "pair_id": pair_id,
        "case_id": str(pair["case_id"]),
        "repetition": int(pair["repetition"]),
        "arm": arm_name,
        "attempt": int(arm.get("attempt", 1)),
        "url": base_url,
        "lan_url": base_url,
        "local_url": local_url,
        "ready_url": ready_url,
        "host": host,
        "advertise_host": advertise_host,
        "port": port,
        "pid": process.pid,
        "argv": argv,
        "worktree": str(arm["worktree"]),
        "stage_dir": str(arm["stage_dir"]),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "started_at": started_at,
        "state": "ready" if ready else "failed",
    }
    atomic_write_json(app_dir / "server.json", entry)
    if not ready:
        _terminate(entry)
        detail = ""
        if stderr_path.is_file():
            detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        entry["detail"] = detail or f"server exited with returncode={process.poll()}"
        atomic_write_json(app_dir / "server.json", entry)
    return entry



def start_live_review(plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path.resolve())
    existing = live_review_status(plan_path)
    if existing["total"] and existing["ready"] == existing["total"]:
        return {**existing, "existing": True}

    # Stop a partial or stale runtime. Reuse its assigned ports where possible so
    # previously displayed operator URLs remain stable across an explicit restart.
    prior_ports: dict[tuple[str, str], int] = {}
    if existing["apps"]:
        for item in existing["apps"]:
            pair_id = item.get("pair_id")
            arm_name = item.get("arm")
            port = item.get("port")
            if isinstance(pair_id, str) and isinstance(arm_name, str) and isinstance(port, int):
                prior_ports[(pair_id, arm_name)] = port
            _terminate(item)

    spec = validate_spec(Path(plan["coordinator"]["spec_path"]))
    config = _server_config(spec)
    root = runtime_dir(plan)
    root.mkdir(parents=True, exist_ok=True)
    append_event(Path(plan["coordinator"]["run_dir"]), event_type="live_review_started", run_id=str(plan["run_id"]))
    apps: list[dict[str, Any]] = []
    allocated_ports: set[int] = set()
    runtime_started_at = str(existing.get("started_at") or utc_now())

    def persist() -> None:
        atomic_write_json(
            summary_path(plan),
            {
                "schema": "agent-workflow/benchmark-live-review-runtime/v1",
                "run_id": plan["run_id"],
                "benchmark_id": plan["benchmark_id"],
                "runtime_dir": str(root),
                "started_at": runtime_started_at,
                "updated_at": utc_now(),
                "apps": apps,
            },
        )

    persist()
    try:
        for pair in plan["pairs"]:
            pair_state_path = (
                Path(plan["coordinator"]["run_dir"])
                / "pair-state"
                / str(pair["case_id"])
                / f"r{int(pair['repetition']):02d}"
                / "pair.json"
            )
            pair_state = read_object(pair_state_path)
            arms = selected_arms(pair, pair_state)
            for arm_name in ("control_raw", "workflow_full"):
                arm = {**arms[arm_name], "attempt": pair_state["selected_attempt"]}
                launched: dict[str, Any] | None = None
                preferred = prior_ports.get((str(pair["pair_id"]), arm_name))
                candidates = ([preferred] if preferred is not None else []) + [None, None, None]
                attempted: set[int] = set()
                for candidate in candidates:
                    port = (
                        int(candidate)
                        if candidate is not None and int(candidate) not in allocated_ports
                        else _free_port(str(config["host"]), excluded=allocated_ports)
                    )
                    if port in attempted:
                        continue
                    attempted.add(port)
                    launched = _launch_one(
                        plan,
                        spec,
                        pair,
                        arm,
                        host=str(config["host"]),
                        port=port,
                        root=root,
                    )
                    if launched["state"] == "ready":
                        allocated_ports.add(port)
                        break
                assert launched is not None
                apps.append(launched)
                persist()
    except Exception:
        persist()
        raise

    status = live_review_status(plan_path)
    append_event(
        Path(plan["coordinator"]["run_dir"]),
        event_type="live_review_terminal",
        run_id=str(plan["run_id"]),
        payload={"ready": status["ready"], "total": status["total"]},
    )
    if status["ready"] != status["total"]:
        failures = [f"{item['pair_id']}:{item['arm']}" for item in status["apps"] if item["state"] != "ready"]
        raise WorkflowError("benchmark live review server failed: " + ", ".join(failures))
    return status


def stop_live_review(plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path.resolve())
    path = summary_path(plan)
    if not path.is_file():
        return {"run_id": plan["run_id"], "stopped": 0, "already_stopped": 0, "runtime_dir": str(runtime_dir(plan))}
    value = read_object(path)
    stopped = 0
    already = 0
    failed = 0
    apps: list[dict[str, Any]] = []
    for raw in value.get("apps", []):
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        was_alive = _pid_alive(item.get("pid"))
        if _terminate(item):
            stopped += int(was_alive)
            already += int(not was_alive)
            item["state"] = "stopped"
            item["stopped_at"] = utc_now()
        else:
            failed += 1
            item["state"] = "degraded"
            item["stop_error"] = "process remained alive after TERM/KILL teardown"
        apps.append(item)
    value["apps"] = apps
    value["stopped_at"] = utc_now()
    atomic_write_json(path, value)
    append_event(
        Path(plan["coordinator"]["run_dir"]),
        event_type="live_review_stopped",
        run_id=str(plan["run_id"]),
        payload={"stopped": stopped, "already_stopped": already, "failed": failed},
    )
    return {
        "run_id": plan["run_id"],
        "stopped": stopped,
        "already_stopped": already,
        "failed": failed,
        "remaining": failed,
        "runtime_dir": str(runtime_dir(plan)),
    }


def live_url_for(plan: Mapping[str, Any], pair_id: str, arm: str) -> str | None:
    path = summary_path(plan)
    if not path.is_file():
        return None
    value = read_object(path)
    for item in value.get("apps", []):
        if isinstance(item, Mapping) and item.get("pair_id") == pair_id and item.get("arm") == arm:
            state = _entry_state(item)
            return str(state["url"]) if state["state"] == "ready" else None
    return None

"""JSON-RPC 2.0 over stdio.

One newline-delimited JSON object per line in each direction.
Designed for the Bubble Tea TUI front-end (or any other client) to drive
GemCoder without re-implementing the core in another language.

Methods:
  info()                         -> {model, root, project, initialized, approvals_apply}
  init(force?)                   -> {written: [...]}
  doctor()                       -> {checks: [...]}
  list_runs()                    -> [run_id, ...]
  get_run(run_id)                -> {record, summary, patch}
  get_events(run_id)             -> [event, ...]
  start_run(task)                -> {run_id, summary, patch}
  apply(run_id?, dry_run?)       -> {ok, files, stderr, dry_run, run_id}
  verify(run_id?)                -> [{command, returncode, stdout, stderr}, ...]
  shell(command)                  -> {command, returncode, stdout, stderr}

Errors use JSON-RPC error codes:
  -32600 invalid request
  -32601 method not found
  -32602 invalid params
  -32603 internal error (with `data.type` = class name)
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gemcoder.config import CONFIG_FILE, load_config
from gemcoder.events import RunStore
from gemcoder.harness import HarnessRunner
from gemcoder.managed import ManagedAgentError
from gemcoder.orchestrator import Backend, OrchestratorEvent
from gemcoder.patcher import apply_patch
from gemcoder.shell import run_shell_command
from gemcoder.smoke import smoke_test
from gemcoder.templates import scaffold

# Module-level cancellation event. SIGINT trips it so the in-flight run can
# bail out without crashing the serve loop. Cleared at the start of each
# `_start_run` so successive runs aren't auto-cancelled.
_CANCEL = threading.Event()


def _sigint_handler(signum, frame) -> None:  # noqa: ARG001
    """Set the cancel event. Must NOT raise; the serve loop keeps running.

    The default Python SIGINT handler raises KeyboardInterrupt, which would
    crash the JSON-RPC loop. Instead we just flip an event so the worker
    thread can react in a controlled way and the serve loop survives.
    """
    _CANCEL.set()


def _install_signal_handler() -> None:
    try:
        signal.signal(signal.SIGINT, _sigint_handler)
        # Make blocking syscalls return EINTR so urlopen/socket reads wake up.
        signal.siginterrupt(signal.SIGINT, True)
    except (ValueError, OSError):
        # signal.signal raises ValueError if not on the main thread (e.g.
        # when serve() is driven from inside a test runner thread). Skip
        # silently in that case so unit tests still work.
        pass


def _doctor(root: Path) -> dict[str, Any]:
    config_path = root / CONFIG_FILE
    config = load_config(root)
    checks = [
        {"name": "config", "ok": config_path.exists(), "detail": str(config_path)},
        {
            "name": "instructions",
            "ok": (root / config.harness.instructions).exists(),
            "detail": config.harness.instructions,
        },
        {
            "name": "skills",
            "ok": (root / config.harness.skills_dir).exists(),
            "detail": config.harness.skills_dir,
        },
        _auth_check(config),
        {
            "name": "verification",
            "ok": bool(config.verification.commands),
            "detail": ", ".join(config.verification.commands) or "none",
        },
    ]
    return {"checks": checks}


def _auth_check(config) -> dict[str, Any]:
    env_name = (
        config.managed_agent.access_token_env
        if config.managed_agent.auth_type == "bearer"
        else config.managed_agent.api_key_env
    )
    return {
        "name": "provider_auth",
        "ok": bool(os.getenv(env_name)),
        "detail": f"{env_name} env",
    }


def _list_runs(root: Path) -> list[dict[str, Any]]:
    return RunStore(root).list_run_summaries()


def _get_events(root: Path, run_id: str) -> list[dict[str, Any]]:
    return [asdict(e) for e in RunStore(root).read_events(run_id)]


def _get_run(root: Path, run_id: str) -> dict[str, Any]:
    run_dir = root / ".gemcoder" / "runs" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"No such run: {run_id}")
    record = json.loads((run_dir / "record.json").read_text())
    patch = (run_dir / "patch.diff").read_text() if (run_dir / "patch.diff").exists() else ""
    summary = ""
    result_path = run_dir / "managed-result.json"
    if result_path.exists():
        summary = json.loads(result_path.read_text()).get("summary", "")
    run_summary: dict[str, Any] = {}
    summary_path = run_dir / "run-summary.json"
    if summary_path.exists():
        run_summary = json.loads(summary_path.read_text())
    return {
        "run_id": run_id,
        "record": record,
        "summary": summary,
        "patch": patch,
        "backend": run_summary.get("backend"),
        "status": run_summary.get("status") or record.get("status"),
        "diagnostics": run_summary,
    }


# Per-server-process conversation history. Cleared by `reset_session`.
_SESSION_HISTORY: list[dict[str, str]] = []
_SESSION_HISTORY_MAX_TURNS = 10  # cap to keep token budget bounded


def _notify(method: str, params: dict[str, Any]) -> None:
    sys.stdout.write(
        json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
    )
    sys.stdout.flush()


def _start_run(root: Path, task: str, backend: str = "") -> dict[str, Any]:
    def on_chunk(delta: str) -> None:
        _notify("run.chunk", {"delta": delta})

    def on_event(event: OrchestratorEvent) -> None:
        _notify(
            "run.event",
            {
                "kind": event.kind,
                "backend": event.backend.value,
                "text": event.text,
                "data": event.data,
            },
        )

    backend_choice: Backend | None
    try:
        backend_choice = Backend.parse(backend) if backend else None
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    history = _SESSION_HISTORY[-(_SESSION_HISTORY_MAX_TURNS * 2):] or None
    _CANCEL.clear()

    # Run the harness on a worker thread so the main thread stays free to
    # receive SIGINT and run the signal handler (which sets _CANCEL). On
    # CPython the signal handler can only execute on the main thread, and
    # only between bytecode instructions — so the main thread must NOT be
    # blocked in a C-level read while the user wants to cancel.
    holder: dict[str, Any] = {"result": None, "error": None}

    def worker() -> None:
        try:
            holder["result"] = HarnessRunner(root).run(
                task,
                on_chunk=on_chunk,
                history=history,
                backend=backend_choice,
                on_event=on_event,
                cancel_event=_CANCEL,
            )
        except BaseException as exc:  # noqa: BLE001
            holder["error"] = exc

    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()
    # Poll-join so the main thread can receive signals between bytecodes.
    while worker_thread.is_alive():
        worker_thread.join(timeout=0.1)

    error = holder["error"]
    if isinstance(error, ManagedAgentError):
        # SIGINT-driven cancellation: do not crash the serve loop. Return a
        # well-formed JSON-RPC result so the TUI can render it normally.
        if str(error) == "cancelled by user":
            run_id = HarnessRunner(root).latest_run_id() or ""
            return {
                "run_id": run_id,
                "summary": "cancelled",
                "patch": "",
                "cancelled": True,
                "backend": (error.diagnostics or {}).get("provider"),
            }
        raise error
    if error is not None:
        raise error
    result = holder["result"]
    _SESSION_HISTORY.append({"role": "user", "content": task})
    _SESSION_HISTORY.append({"role": "assistant", "content": result.summary})
    patch = ""
    if result.patch_path:
        patch_file = root / result.patch_path
        if patch_file.exists():
            patch = patch_file.read_text()
    return {
        "run_id": result.run_id,
        "summary": result.summary,
        "patch": patch,
        "backend": (result.diagnostics or {}).get("backend"),
        "status": (result.diagnostics or {}).get("status", "completed"),
        "diagnostics": result.diagnostics or {},
        "cancelled": False,
    }


def _reset_session() -> dict[str, Any]:
    cleared = len(_SESSION_HISTORY) // 2
    _SESSION_HISTORY.clear()
    return {"cleared_turns": cleared}


def _cancel_run(run_id: str | None = None) -> dict[str, Any]:
    _CANCEL.set()
    return {"ok": True, "reason": "cancel requested", "run_id": run_id}


def _apply(root: Path, run_id: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    store = RunStore(root)
    selected = run_id or store.latest_run_id()
    if selected is None:
        raise ValueError("No runs found.")
    patch_path = root / ".gemcoder" / "runs" / selected / "patch.diff"
    if not patch_path.exists():
        raise FileNotFoundError(f"No patch.diff for run {selected}")
    patch_text = patch_path.read_text()
    store.append(selected, "patch.apply.started", {"dry_run": dry_run})
    result = apply_patch(root, patch_text, dry_run=dry_run)
    event = "patch.apply.checked" if dry_run else "patch.apply.applied"
    if not result.ok:
        event = "patch.apply.failed"
    store.append(
        selected, event, {"files": result.files, "stderr": result.stderr.strip()[:500]}
    )
    return asdict(result) | {"run_id": selected}


def _verify(root: Path, run_id: str | None = None) -> list[dict[str, Any]]:
    results = HarnessRunner(root).verify(run_id)
    return [asdict(r) for r in results]


def _shell(root: Path, command: str) -> dict[str, object]:
    return run_shell_command(root, command).asdict()


def _smoke(
    root: Path,
    prompt: str = "Say hello in five words.",
    backend: str = "remote",
    timeout: int = 30,
) -> list[dict[str, Any]]:
    if not isinstance(timeout, int):
        raise ValueError("timeout must be an integer")
    backend_choice = Backend.parse(backend)
    config = load_config(root)
    config.managed_agent.timeout_seconds = timeout
    return smoke_test(config, root, prompt, backend_choice)


def _info(root: Path) -> dict[str, Any]:
    config = load_config(root)
    return {
        "model": config.managed_agent.agent_id
        or config.managed_agent.base_agent
        or "managed-agent",
        "root": str(root.resolve()),
        "project": config.project.name,
        "initialized": (root / CONFIG_FILE).exists(),
        "approvals_apply": config.approvals.apply_patch,
    }


def _init(root: Path, force: bool = False) -> dict[str, Any]:
    written = scaffold(root, force=force)
    return {"written": [str(p.relative_to(root)) for p in written]}


def _build_dispatch(root: Path) -> dict[str, Callable[..., Any]]:
    return {
        "info": lambda: _info(root),
        "init": lambda force=False: _init(root, force),
        "doctor": lambda: _doctor(root),
        "list_runs": lambda: _list_runs(root),
        "get_events": lambda run_id: _get_events(root, run_id),
        "get_run": lambda run_id: _get_run(root, run_id),
        "start_run": lambda task, backend="": _start_run(root, task, backend),
        "apply": lambda run_id=None, dry_run=False: _apply(root, run_id, dry_run),
        "verify": lambda run_id=None: _verify(root, run_id),
        "shell": lambda command: _shell(root, command),
        "smoke": lambda prompt="Say hello in five words.", backend="remote", timeout=30: _smoke(
            root, prompt, backend, timeout
        ),
        "reset_session": lambda: _reset_session(),
        "cancel_run": lambda run_id=None: _cancel_run(run_id),
    }


def _make_error(code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


def handle_request(
    req: dict[str, Any], dispatch: dict[str, Callable[..., Any]]
) -> dict[str, Any]:
    """Pure function — easy to unit test."""
    req_id = req.get("id")
    response: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
    method = req.get("method")
    if not isinstance(method, str) or method not in dispatch:
        response["error"] = _make_error(-32601, f"Method not found: {method}")
        return response
    params = req.get("params") or {}
    if not isinstance(params, dict):
        response["error"] = _make_error(-32602, "params must be an object")
        return response
    try:
        result = dispatch[method](**params)
    except TypeError as exc:
        response["error"] = _make_error(-32602, str(exc))
        return response
    except ValueError as exc:
        response["error"] = _make_error(-32602, str(exc))
        return response
    except Exception as exc:
        response["error"] = _make_error(
            -32603,
            str(exc),
            data={"type": type(exc).__name__, "trace": traceback.format_exc()},
        )
        return response
    response["result"] = result
    return response


def serve(root: str | Path = ".") -> None:
    base = Path(root)
    _install_signal_handler()
    dispatch = _build_dispatch(base)
    sys.stderr.write(f"gemcoder serve: root={base.resolve()}\n")
    sys.stderr.flush()
    while True:
        try:
            line = sys.stdin.readline()
        except InterruptedError:
            # SIGINT during a stdin read between requests — just resume.
            continue
        if line == "":
            return  # EOF
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            err = {
                "jsonrpc": "2.0",
                "id": None,
                "error": _make_error(-32700, f"Parse error: {exc}"),
            }
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_request(req, dispatch)
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

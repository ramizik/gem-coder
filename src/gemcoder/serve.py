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
import sys
import traceback
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gemcoder.config import CONFIG_FILE, load_config
from gemcoder.events import RunStore
from gemcoder.harness import HarnessRunner
from gemcoder.patcher import apply_patch
from gemcoder.shell import run_shell_command
from gemcoder.templates import scaffold


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
        {
            "name": "gemini_api_key",
            "ok": bool(os.getenv("GEMINI_API_KEY")),
            "detail": "GEMINI_API_KEY env",
        },
        {
            "name": "verification",
            "ok": bool(config.verification.commands),
            "detail": ", ".join(config.verification.commands) or "none",
        },
    ]
    return {"checks": checks}


def _list_runs(root: Path) -> list[str]:
    return RunStore(root).list_runs()


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
    return {"record": record, "summary": summary, "patch": patch}


def _start_run(root: Path, task: str) -> dict[str, Any]:
    result = HarnessRunner(root).run(task)
    patch = ""
    if result.patch_path:
        patch_file = root / result.patch_path
        if patch_file.exists():
            patch = patch_file.read_text()
    return {"run_id": result.run_id, "summary": result.summary, "patch": patch}


def _apply(root: Path, run_id: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    store = RunStore(root)
    selected = run_id or (store.list_runs()[-1] if store.list_runs() else None)
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
        "start_run": lambda task: _start_run(root, task),
        "apply": lambda run_id=None, dry_run=False: _apply(root, run_id, dry_run),
        "verify": lambda run_id=None: _verify(root, run_id),
        "shell": lambda command: _shell(root, command),
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
    dispatch = _build_dispatch(base)
    sys.stderr.write(f"gemcoder serve: root={base.resolve()}\n")
    sys.stderr.flush()
    for line in sys.stdin:
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

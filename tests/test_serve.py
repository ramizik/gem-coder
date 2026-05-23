import json
from pathlib import Path

from gemcoder.serve import _build_dispatch, handle_request
from gemcoder.templates import scaffold


def _do(dispatch, method, **params):
    req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return handle_request(req, dispatch)


def test_method_not_found(tmp_path: Path) -> None:
    dispatch = _build_dispatch(tmp_path)
    resp = _do(dispatch, "nope")
    assert resp["error"]["code"] == -32601


def test_doctor_runs(tmp_path: Path) -> None:
    scaffold(tmp_path)
    dispatch = _build_dispatch(tmp_path)
    resp = _do(dispatch, "doctor")
    assert "result" in resp
    names = {c["name"] for c in resp["result"]["checks"]}
    assert {"config", "instructions", "skills", "provider_auth", "verification"} <= names


def test_list_runs_empty(tmp_path: Path) -> None:
    dispatch = _build_dispatch(tmp_path)
    resp = _do(dispatch, "list_runs")
    assert resp["result"] == []


def test_list_runs_returns_newest_first(tmp_path: Path) -> None:
    scaffold(tmp_path)
    store = __import__("gemcoder.events", fromlist=["RunStore"]).RunStore(tmp_path)
    older = store.create_run("older task")
    newer = store.create_run("newer task")
    older_dir = tmp_path / ".gemcoder" / "runs" / older / "record.json"
    newer_dir = tmp_path / ".gemcoder" / "runs" / newer / "record.json"
    older_record = json.loads(older_dir.read_text())
    newer_record = json.loads(newer_dir.read_text())
    older_record["created_at"] = "2020-01-01T00:00:00+00:00"
    newer_record["created_at"] = "2026-01-01T00:00:00+00:00"
    older_dir.write_text(json.dumps(older_record, indent=2) + "\n")
    newer_dir.write_text(json.dumps(newer_record, indent=2) + "\n")

    dispatch = _build_dispatch(tmp_path)
    resp = _do(dispatch, "list_runs")

    assert resp["result"][0]["run_id"] == newer
    assert resp["result"][1]["run_id"] == older


def test_smoke_rejects_invalid_backend(tmp_path: Path) -> None:
    scaffold(tmp_path)
    dispatch = _build_dispatch(tmp_path)

    resp = _do(dispatch, "smoke", backend="cloud")

    assert resp["error"]["code"] == -32602
def test_invalid_params_type() -> None:
    dispatch = _build_dispatch(Path("."))
    req = {"jsonrpc": "2.0", "id": 1, "method": "doctor", "params": "not-a-dict"}
    resp = handle_request(req, dispatch)
    assert resp["error"]["code"] == -32602


def test_apply_missing_run(tmp_path: Path) -> None:
    dispatch = _build_dispatch(tmp_path)
    resp = _do(dispatch, "apply")
    assert resp["error"]["code"] == -32602
    assert "No runs" in resp["error"]["message"]


def test_shell_runs_safe_command(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello")
    dispatch = _build_dispatch(tmp_path)

    resp = _do(dispatch, "shell", command="ls")

    assert resp["result"]["returncode"] == 0
    assert "hello.txt" in resp["result"]["stdout"]


def test_shell_rejects_unsafe_command(tmp_path: Path) -> None:
    dispatch = _build_dispatch(tmp_path)

    resp = _do(dispatch, "shell", command="cat .env")

    assert resp["error"]["code"] == -32602
    assert "Only safe local inspection commands" in resp["error"]["message"]


def test_smoke_dispatches_backend(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path)
    calls = []

    def fake_smoke_test(config, root, prompt, backend):
        calls.append((root, prompt, backend.value))
        return [{"backend": backend.value, "status": "ok", "preview": "hello"}]

    monkeypatch.setattr("gemcoder.serve.smoke_test", fake_smoke_test)
    dispatch = _build_dispatch(tmp_path)

    resp = _do(dispatch, "smoke", prompt="hi", backend="remote", timeout=7)

    assert resp["result"][0]["status"] == "ok"
    assert calls == [(tmp_path, "hi", "remote")]

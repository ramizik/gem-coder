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


def test_invalid_params_type() -> None:
    dispatch = _build_dispatch(Path("."))
    req = {"jsonrpc": "2.0", "id": 1, "method": "doctor", "params": "not-a-dict"}
    resp = handle_request(req, dispatch)
    assert resp["error"]["code"] == -32602


def test_apply_missing_run(tmp_path: Path) -> None:
    dispatch = _build_dispatch(tmp_path)
    resp = _do(dispatch, "apply")
    assert resp["error"]["code"] == -32603
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

    assert resp["error"]["code"] == -32603
    assert "Only safe local inspection commands" in resp["error"]["message"]

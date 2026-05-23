"""Orchestrator routing + event-stream tests (no live API calls)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from gemcoder.config import GemCoderConfig, OrchestratorConfig
from gemcoder.managed import ManagedAgentResult
from gemcoder.orchestrator import Backend, Orchestrator, OrchestratorEvent
from gemcoder.templates import scaffold


def _make_config(**orch_overrides: Any) -> GemCoderConfig:
    config = GemCoderConfig()
    config.orchestrator = OrchestratorConfig(**orch_overrides)
    return config


def test_backend_parse_accepts_known_values() -> None:
    assert Backend.parse("local") is Backend.LOCAL
    assert Backend.parse("REMOTE") is Backend.REMOTE
    assert Backend.parse("auto") is Backend.AUTO
    assert Backend.parse(None) is Backend.AUTO
    assert Backend.parse("") is Backend.AUTO


def test_backend_parse_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        Backend.parse("cloud")


def test_resolve_backend_explicit_local_skips_heuristic(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = _make_config()
    orch = Orchestrator(config, tmp_path)
    assert orch.resolve_backend("local") is Backend.LOCAL
    assert orch.resolve_backend("remote") is Backend.REMOTE


def test_auto_routes_to_remote_when_too_many_files(tmp_path: Path) -> None:
    scaffold(tmp_path)
    for i in range(30):
        (tmp_path / f"file_{i}.py").write_text(f"# small file {i}\n")
    config = _make_config(max_files_local=10, max_bytes_local=10**9)
    config.context.include = ["**/*.py"]
    orch = Orchestrator(config, tmp_path)
    assert orch.resolve_backend("auto", task="hi") is Backend.REMOTE


def test_auto_routes_to_remote_when_task_too_long(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = _make_config(max_task_chars_local=50)
    orch = Orchestrator(config, tmp_path)
    long_task = "x" * 500
    assert orch.resolve_backend("auto", task=long_task) is Backend.REMOTE


def test_auto_falls_back_to_remote_when_local_sdk_missing(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = _make_config(
        max_files_local=10_000, max_bytes_local=10**9, max_task_chars_local=10**6
    )
    orch = Orchestrator(config, tmp_path)
    # google-antigravity isn't installed in this test environment.
    assert orch._local_available() is False
    assert orch.resolve_backend("auto", task="hi") is Backend.REMOTE


def test_orchestrator_emits_events_in_order(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path)
    config = _make_config()
    orch = Orchestrator(config, tmp_path)

    class FakeRemoteClient:
        last_diagnostics: dict[str, Any] = {}

        def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
            pass

        def run_task(
            self,
            packet: str,
            on_chunk=None,
        ) -> ManagedAgentResult:
            for delta in ("hello ", "world"):
                if on_chunk is not None:
                    on_chunk(delta)
            return ManagedAgentResult(
                summary="hello world",
                patch="",
                raw="hello world",
                request=packet,
                diagnostics={"status": "success", "mode": "test"},
            )

    monkeypatch.setattr("gemcoder.orchestrator.ManagedAgentClient", FakeRemoteClient)

    events: list[OrchestratorEvent] = []
    result, resolved = orch.run(
        "task packet",
        task="fix",
        backend=Backend.REMOTE,
        on_event=events.append,
        on_chunk=lambda _delta: None,
    )

    assert resolved is Backend.REMOTE
    assert result.summary == "hello world"
    kinds = [e.kind for e in events]
    # backend.selected first, then 2 tokens, diagnostic, complete
    assert kinds[0] == "backend.selected"
    assert kinds.count("token") == 2
    assert "diagnostic" in kinds
    assert kinds[-1] == "complete"


def test_orchestrator_remote_error_emits_error_event(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path)
    config = _make_config()
    orch = Orchestrator(config, tmp_path)

    from gemcoder.managed import ManagedAgentError

    class FailingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run_task(self, packet: str, on_chunk=None) -> ManagedAgentResult:
            raise ManagedAgentError("simulated 503", {"http_status": 503})

    monkeypatch.setattr("gemcoder.orchestrator.ManagedAgentClient", FailingClient)

    events: list[OrchestratorEvent] = []
    with pytest.raises(ManagedAgentError):
        orch.run(
            "packet",
            task="fix",
            backend=Backend.REMOTE,
            on_event=events.append,
        )
    kinds = [e.kind for e in events]
    assert "error" in kinds
    error_event = next(e for e in events if e.kind == "error")
    assert error_event.backend is Backend.REMOTE
    assert "simulated 503" in error_event.text

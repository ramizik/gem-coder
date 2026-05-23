"""Tests for the `gemcoder smoke` one-shot ping (no live network)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gemcoder.config import GemCoderConfig
from gemcoder.managed import ManagedAgentResult
from gemcoder.orchestrator import Backend
from gemcoder.smoke import smoke_test
from gemcoder.templates import scaffold


def test_smoke_remote_reports_missing_key(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path)
    config = GemCoderConfig()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    results = smoke_test(config, tmp_path, "ping", Backend.REMOTE)

    assert len(results) == 1
    assert results[0]["backend"] == "remote"
    assert results[0]["status"] == "missing_credentials"


def test_smoke_local_reports_missing_key(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path)
    config = GemCoderConfig()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    results = smoke_test(config, tmp_path, "ping", Backend.LOCAL)

    assert results[0]["backend"] == "local"
    assert results[0]["status"] == "missing_credentials"


def test_smoke_both_pings_both_backends(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path)
    config = GemCoderConfig()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    results = smoke_test(config, tmp_path, "ping", Backend.BOTH)

    backends = {r["backend"] for r in results}
    assert backends == {"local", "remote"}


def test_smoke_remote_returns_ok_when_client_succeeds(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path)
    config = GemCoderConfig()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run_task(self, prompt: str) -> ManagedAgentResult:
            return ManagedAgentResult(
                summary="hello from fake gemini",
                diagnostics={"status": "success"},
            )

    monkeypatch.setattr("gemcoder.smoke.ManagedAgentClient", FakeClient)
    results = smoke_test(config, tmp_path, "say hi", Backend.REMOTE)

    assert results[0]["status"] == "ok"
    assert "hello from fake gemini" in results[0]["preview"]
    assert results[0]["elapsed_seconds"] >= 0

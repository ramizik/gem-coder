"""Cancellation tests for the streaming managed-agent path and serve layer."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from gemcoder.config import GemCoderConfig
from gemcoder.managed import ManagedAgentClient, ManagedAgentError
from gemcoder.serve import _build_dispatch, handle_request


class _FakeResponse:
    """Iterable stand-in for urllib's HTTPResponse."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)
        self.closed = False

    def __iter__(self):
        yield from self._lines

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def close(self) -> None:
        self.closed = True


def _client(api_key: str = "fake-key") -> ManagedAgentClient:
    config = GemCoderConfig()
    config.managed_agent.mode = "generate_content"
    return ManagedAgentClient(config, Path("."), api_key=api_key)


def test_stream_cancel_before_any_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    """If cancel_event is set BEFORE the request fires, raise immediately
    and don't consume any SSE lines from the fake response."""
    client = _client()
    fake = _FakeResponse(
        [
            b'data: {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}\n',
            b"\n",
        ]
    )
    urlopen_mock = MagicMock(return_value=fake)
    monkeypatch.setattr("gemcoder.managed.urlopen", urlopen_mock)

    cancel = threading.Event()
    cancel.set()  # cancel BEFORE the call

    chunks: list[str] = []

    with pytest.raises(ManagedAgentError) as exc_info:
        client._stream_generate_content(
            body={"contents": []},
            on_chunk=chunks.append,
            cancel_event=cancel,
        )

    assert str(exc_info.value) == "cancelled by user"
    assert chunks == []  # nothing streamed
    # The pre-check should have bailed before opening the URL at all.
    urlopen_mock.assert_not_called()


def test_start_run_catches_cancel_and_returns_cancelled_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled run should produce a normal JSON-RPC result, not crash."""
    from gemcoder.templates import scaffold

    scaffold(tmp_path)

    def fake_run(self, *args: Any, **kwargs: Any):
        # Pretend SIGINT fired mid-stream.
        raise ManagedAgentError(
            "cancelled by user",
            {"status": "cancelled", "provider": "test"},
        )

    monkeypatch.setattr("gemcoder.harness.HarnessRunner.run", fake_run)

    dispatch = _build_dispatch(tmp_path)
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "start_run",
        "params": {"task": "anything"},
    }
    resp = handle_request(req, dispatch)

    assert "error" not in resp, resp
    assert resp["result"]["cancelled"] is True
    assert resp["result"]["summary"] == "cancelled"
    assert resp["result"]["patch"] == ""

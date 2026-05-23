"""Routing layer between the local Antigravity SDK and remote Managed Agents.

Both backends receive the same task packet and return a `ManagedAgentResult`.
The orchestrator picks the backend (explicit or by heuristic) and emits a
unified `OrchestratorEvent` stream so callers — CLI stdout, JSON-RPC notifs,
or the TUI — can render progress live.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from gemcoder.config import GemCoderConfig
from gemcoder.local_agent import LocalAgentClient
from gemcoder.managed import ManagedAgentClient, ManagedAgentError, ManagedAgentResult
from gemcoder.task_packet import collect_context_files


class Backend(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"
    AUTO = "auto"

    @classmethod
    def parse(cls, value: str | None) -> Backend:
        if value is None or value == "":
            return cls.AUTO
        try:
            return cls(value.lower())
        except ValueError as exc:
            raise ValueError(
                f"Unknown backend: {value!r}. Expected one of: local, remote, auto."
            ) from exc


@dataclass(slots=True)
class OrchestratorEvent:
    """Unified event emitted while a task is running.

    `kind` is one of:
      - `backend.selected` — routing decision finalized (`backend` set)
      - `token`            — text delta from the model
      - `thought`          — reasoning delta (local backend only today)
      - `tool_call`        — agent invoked a tool (local backend only today)
      - `diagnostic`       — provider metadata (latency, status, …)
      - `error`            — backend raised
      - `complete`         — final summary/patch ready
    """

    kind: str
    backend: Backend
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


EventCallback = Callable[[OrchestratorEvent], None]


class Orchestrator:
    """Picks a backend and runs the task, streaming events to a callback."""

    def __init__(
        self,
        config: GemCoderConfig,
        root: str | Path = ".",
    ) -> None:
        self.config = config
        self.root = Path(root)

    # --- Routing -----------------------------------------------------------

    def resolve_backend(
        self,
        requested: Backend | str | None,
        task: str = "",
    ) -> Backend:
        """Translate a requested backend (or auto) into a concrete LOCAL/REMOTE."""
        backend = (
            requested if isinstance(requested, Backend) else Backend.parse(requested)
        )
        if backend is Backend.AUTO:
            backend = self._auto_route(task)
        return backend

    def _auto_route(self, task: str) -> Backend:
        """Heuristic: small repo + short task → local; larger → remote.

        Counts files (and total bytes) in the would-be context. Falls back to
        REMOTE if the local SDK is not importable so users get *something*.
        """
        cfg = self.config.orchestrator
        files = collect_context_files(self.root, self.config)
        if len(files) > cfg.max_files_local:
            return Backend.REMOTE

        total_bytes = 0
        for rel in files:
            path = self.root / rel
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
            if total_bytes > cfg.max_bytes_local:
                return Backend.REMOTE

        if len(task) > cfg.max_task_chars_local:
            return Backend.REMOTE

        if not self._local_available():
            return Backend.REMOTE
        return Backend.LOCAL

    def _local_available(self) -> bool:
        try:
            import google.antigravity  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return False
        return True

    # --- Execution ---------------------------------------------------------

    def run(
        self,
        task_packet: str,
        task: str = "",
        *,
        backend: Backend | str | None = None,
        on_event: EventCallback | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> tuple[ManagedAgentResult, Backend]:
        """Run a task packet on the resolved backend.

        `on_chunk` keeps backwards compatibility with the existing remote
        SSE streaming callback. `on_event` is the unified stream — preferred.
        """
        requested = (
            backend
            if backend is not None
            else self.config.orchestrator.default_backend
        )
        resolved = self.resolve_backend(requested, task)

        def emit(event: OrchestratorEvent) -> None:
            if on_event is not None:
                on_event(event)

        emit(
            OrchestratorEvent(
                kind="backend.selected",
                backend=resolved,
                data={"requested": str(requested)},
            )
        )

        if resolved is Backend.LOCAL:
            return self._run_local(task_packet, emit, on_chunk), resolved
        return self._run_remote(task_packet, emit, on_chunk), resolved

    def _run_local(
        self,
        task_packet: str,
        emit: Callable[[OrchestratorEvent], None],
        on_chunk: Callable[[str], None] | None,
    ) -> ManagedAgentResult:
        client = LocalAgentClient(self.config, self.root)

        def local_event(kind: str, data: dict[str, Any]) -> None:
            text = data.get("text", "") if kind == "token" else ""
            if kind == "token" and on_chunk is not None and isinstance(text, str):
                on_chunk(text)
            emit(OrchestratorEvent(kind=kind, backend=Backend.LOCAL, text=text, data=data))

        result = client.run_task(task_packet, on_event=local_event)
        emit(
            OrchestratorEvent(
                kind="diagnostic",
                backend=Backend.LOCAL,
                data=result.diagnostics or {},
            )
        )
        emit(
            OrchestratorEvent(
                kind="complete",
                backend=Backend.LOCAL,
                text=result.summary,
                data={"patch_present": bool(result.patch)},
            )
        )
        return result

    def _run_remote(
        self,
        task_packet: str,
        emit: Callable[[OrchestratorEvent], None],
        on_chunk: Callable[[str], None] | None,
    ) -> ManagedAgentResult:
        client = ManagedAgentClient(self.config, self.root)

        def remote_chunk(delta: str) -> None:
            if on_chunk is not None:
                on_chunk(delta)
            emit(
                OrchestratorEvent(
                    kind="token",
                    backend=Backend.REMOTE,
                    text=delta,
                    data={"text": delta},
                )
            )

        # Only force the streaming path when the caller actually wants chunks.
        # This keeps the non-stream `transport=...` injection point usable.
        chunk_handler = remote_chunk if on_chunk is not None else None
        try:
            result = client.run_task(task_packet, on_chunk=chunk_handler)
        except ManagedAgentError as exc:
            emit(
                OrchestratorEvent(
                    kind="error",
                    backend=Backend.REMOTE,
                    text=str(exc),
                    data=exc.diagnostics,
                )
            )
            raise

        emit(
            OrchestratorEvent(
                kind="diagnostic",
                backend=Backend.REMOTE,
                data=result.diagnostics or {},
            )
        )
        emit(
            OrchestratorEvent(
                kind="complete",
                backend=Backend.REMOTE,
                text=result.summary,
                data={"patch_present": bool(result.patch)},
            )
        )
        return result


__all__ = ["Backend", "EventCallback", "Orchestrator", "OrchestratorEvent"]

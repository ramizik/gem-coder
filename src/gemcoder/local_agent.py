"""Antigravity SDK adapter — local backend for the orchestrator.

Wraps `google-antigravity` so the harness can run the same task packet on
the developer's machine instead of dispatching to Managed Agents. The SDK
is async-only; this module bridges it to GemCoder's sync surface.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from gemcoder.config import GemCoderConfig
from gemcoder.managed import ManagedAgentResult, _extract_unified_diff

LocalEventCallback = Callable[[str, dict[str, Any]], None]


class LocalAgentUnavailable(RuntimeError):
    """Raised when `google-antigravity` is not installed."""


@dataclass(slots=True)
class _SDKHandles:
    Agent: Any
    LocalAgentConfig: Any
    CapabilitiesConfig: Any | None


def _load_sdk() -> _SDKHandles:
    try:
        from google.antigravity import (  # type: ignore[import-not-found]
            Agent,
            LocalAgentConfig,
        )
    except ImportError as exc:
        raise LocalAgentUnavailable(
            "google-antigravity is not installed. Install with: "
            "uv sync --extra local"
        ) from exc
    CapabilitiesConfig: Any | None = None
    try:
        from google.antigravity import (  # type: ignore[import-not-found]
            CapabilitiesConfig as _Caps,
        )

        CapabilitiesConfig = _Caps
    except ImportError:
        CapabilitiesConfig = None
    return _SDKHandles(
        Agent=Agent,
        LocalAgentConfig=LocalAgentConfig,
        CapabilitiesConfig=CapabilitiesConfig,
    )


class LocalAgentClient:
    """Runs a task packet through the Antigravity SDK's local agent loop."""

    def __init__(
        self,
        config: GemCoderConfig,
        root: str | Path = ".",
        *,
        api_key: str | None = None,
    ) -> None:
        self.config = config
        self.root = Path(root)
        self.api_key = api_key if api_key is not None else os.getenv(
            config.managed_agent.api_key_env
        )
        self.last_diagnostics: dict[str, Any] = {}

    def request_diagnostics(self) -> dict[str, Any]:
        return {
            "provider": "antigravity-sdk",
            "mode": "local",
            "model": self.config.managed_agent.base_agent,
            "endpoint": "local://antigravity",
        }

    def run_task(
        self,
        task_packet: str,
        on_event: LocalEventCallback | None = None,
    ) -> ManagedAgentResult:
        diagnostics = self.request_diagnostics()
        if not self.api_key:
            diagnostics.update({"status": "skipped", "error_type": "missing_api_key"})
            self.last_diagnostics = diagnostics
            return ManagedAgentResult(
                summary=(
                    f"{self.config.managed_agent.api_key_env} is not set, so the local "
                    "Antigravity SDK backend was skipped."
                ),
                raw=task_packet,
                diagnostics=diagnostics,
            )

        try:
            sdk = _load_sdk()
        except LocalAgentUnavailable as exc:
            diagnostics.update({"status": "failed", "error_type": "sdk_unavailable"})
            self.last_diagnostics = diagnostics
            return ManagedAgentResult(
                summary=str(exc),
                raw=task_packet,
                diagnostics=diagnostics,
            )

        started = perf_counter()
        try:
            output_text = asyncio.run(self._run_async(sdk, task_packet, on_event))
        except Exception as exc:  # noqa: BLE001 — surface every failure mode
            diagnostics.update(
                {
                    "status": "failed",
                    "elapsed_seconds": round(perf_counter() - started, 3),
                    "error_type": type(exc).__name__,
                }
            )
            self.last_diagnostics = diagnostics
            return ManagedAgentResult(
                summary=f"Antigravity SDK run failed: {exc}",
                raw=task_packet,
                diagnostics=diagnostics,
            )

        diagnostics.update(
            {"status": "success", "elapsed_seconds": round(perf_counter() - started, 3)}
        )
        self.last_diagnostics = diagnostics
        return ManagedAgentResult(
            summary=output_text or "Local agent returned no output text.",
            patch=_extract_unified_diff(output_text),
            raw=output_text,
            request=task_packet,
            diagnostics=diagnostics,
        )

    async def _run_async(
        self,
        sdk: _SDKHandles,
        task_packet: str,
        on_event: LocalEventCallback | None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "system_instructions": self.config.managed_agent.system_instruction,
            "api_key": self.api_key,
        }
        write_mode = self.config.orchestrator.local_capabilities == "write"
        if sdk.CapabilitiesConfig is not None and write_mode:
            kwargs["capabilities"] = sdk.CapabilitiesConfig()

        config = sdk.LocalAgentConfig(**kwargs)
        async with sdk.Agent(config) as agent:
            response = await agent.chat(task_packet)
            tokens: list[str] = []
            token_iter = aiter(response)
            async for token in token_iter:
                tokens.append(token)
                if on_event is not None:
                    on_event("token", {"text": token})
            asyncio.create_task(self._drain_thoughts(response, on_event))
            asyncio.create_task(self._drain_tool_calls(response, on_event))
            text = "".join(tokens)
            if not text:
                # Some SDK versions expose a final `.text()` coroutine.
                getter = getattr(response, "text", None)
                if callable(getter):
                    try:
                        text = await getter()
                    except TypeError:
                        text = str(getter())
            return text

    @staticmethod
    async def _drain_thoughts(response: Any, on_event: LocalEventCallback | None) -> None:
        thoughts = getattr(response, "thoughts", None)
        if thoughts is None or on_event is None:
            return
        try:
            async for thought in thoughts:
                on_event("thought", {"text": str(thought)})
        except Exception:  # noqa: BLE001 — auxiliary stream
            return

    @staticmethod
    async def _drain_tool_calls(response: Any, on_event: LocalEventCallback | None) -> None:
        calls = getattr(response, "tool_calls", None)
        if calls is None or on_event is None:
            return
        try:
            async for call in calls:
                on_event(
                    "tool_call",
                    {
                        "name": getattr(call, "name", "unknown"),
                        "args": getattr(call, "args", None),
                    },
                )
        except Exception:  # noqa: BLE001
            return


def serialize_diagnostics(diagnostics: dict[str, Any]) -> str:
    return json.dumps(diagnostics, indent=2) + "\n"


__all__ = [
    "LocalAgentClient",
    "LocalAgentUnavailable",
    "LocalEventCallback",
    "serialize_diagnostics",
]

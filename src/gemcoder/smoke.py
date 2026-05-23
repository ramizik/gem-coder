"""One-shot live API ping for verifying credentials + reachability.

Used by `gemcoder smoke`. Intentionally bypasses the task-packet/orchestrator
flow so the latency and behaviour reflect the raw round-trip floor of each
backend, not the full repo-aware harness.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from gemcoder.config import GemCoderConfig
from gemcoder.managed import ManagedAgentClient, ManagedAgentError
from gemcoder.orchestrator import Backend


def smoke_test(
    config: GemCoderConfig,
    root: Path,
    prompt: str,
    backend: Backend,
) -> list[dict[str, Any]]:
    """Run a smoke ping against one or both backends. Returns one dict per backend."""
    targets: list[Backend]
    if backend is Backend.BOTH:
        targets = [Backend.LOCAL, Backend.REMOTE]
    elif backend is Backend.AUTO:
        # smoke is for verification — always explicit
        targets = [Backend.REMOTE]
    else:
        targets = [backend]

    return [_ping_one(config, root, prompt, target) for target in targets]


def _ping_one(
    config: GemCoderConfig,
    root: Path,
    prompt: str,
    backend: Backend,
) -> dict[str, Any]:
    if backend is Backend.REMOTE:
        return _ping_remote(config, root, prompt)
    return _ping_local(config, prompt)


def _ping_remote(config: GemCoderConfig, root: Path, prompt: str) -> dict[str, Any]:
    api_key = os.getenv(config.managed_agent.api_key_env)
    if not api_key:
        return {
            "backend": "remote",
            "status": "missing_credentials",
            "error": f"{config.managed_agent.api_key_env} is not set.",
        }
    client = ManagedAgentClient(config, root, api_key=api_key)
    started = perf_counter()
    try:
        result = client.run_task(prompt)
    except ManagedAgentError as exc:
        return {
            "backend": "remote",
            "status": "failed",
            "elapsed_seconds": round(perf_counter() - started, 3),
            "error": str(exc),
            **(exc.diagnostics or {}),
        }
    return {
        "backend": "remote",
        "status": "ok",
        "elapsed_seconds": round(perf_counter() - started, 3),
        "model": config.managed_agent.base_agent,
        "preview": _preview(result.summary),
    }


def _ping_local(config: GemCoderConfig, prompt: str) -> dict[str, Any]:
    api_key = os.getenv(config.managed_agent.api_key_env)
    if not api_key:
        return {
            "backend": "local",
            "status": "missing_credentials",
            "error": f"{config.managed_agent.api_key_env} is not set.",
        }
    try:
        from google.antigravity import (  # type: ignore[import-not-found]
            Agent,
            LocalAgentConfig,
        )
    except ImportError:
        return {
            "backend": "local",
            "status": "sdk_missing",
            "error": "google-antigravity not installed. uv sync --extra local",
        }

    async def _run() -> str:
        async with Agent(LocalAgentConfig(api_key=api_key)) as agent:
            response = await agent.chat(prompt)
            chunks: list[str] = []
            async for token in response:
                chunks.append(token)
            text = "".join(chunks)
            if not text:
                getter = getattr(response, "text", None)
                if callable(getter):
                    try:
                        text = await getter()
                    except TypeError:
                        text = str(getter())
            return text

    started = perf_counter()
    try:
        text = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — every failure mode surfaces here
        return {
            "backend": "local",
            "status": "failed",
            "elapsed_seconds": round(perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "backend": "local",
        "status": "ok",
        "elapsed_seconds": round(perf_counter() - started, 3),
        "model": config.managed_agent.base_agent,
        "preview": _preview(text),
    }


def _preview(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


__all__ = ["smoke_test"]

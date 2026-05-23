"""Gemini Managed Agent REST adapter."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from gemcoder.config import GemCoderConfig
from gemcoder.google_sources import build_google_sources


class ManagedAgentError(RuntimeError):
    """Raised when the Managed Agents API request fails."""


@dataclass(slots=True)
class ManagedAgentResult:
    summary: str
    patch: str = ""
    raw: str = ""
    request: str = ""


class JsonTransport(Protocol):
    def __call__(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]: ...


class ManagedAgentClient:
    def __init__(
        self,
        config: GemCoderConfig,
        root: str | Path = ".",
        *,
        api_key: str | None = None,
        transport: JsonTransport | None = None,
    ) -> None:
        self.config = config
        self.root = Path(root)
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY")
        self.transport = transport or _urllib_transport

    def create_agent(self) -> str:
        if not self.api_key:
            return self.config.managed_agent.agent_id or "managed-agent-placeholder"

        body = self.build_create_agent_payload()
        response = self._post("agents", body)
        return str(response.get("id") or response.get("name") or body["id"])

    def run_task(self, task_packet: str) -> ManagedAgentResult:
        if not self.api_key:
            return ManagedAgentResult(
                summary=(
                    "GEMINI_API_KEY is not set, so GemCoder built the task packet "
                    "but did not call the Managed Agents API."
                ),
                raw=task_packet,
            )

        body = self.build_interaction_payload(task_packet)
        response = self._post("interactions", body)
        output_text = _extract_output_text(response)
        return ManagedAgentResult(
            summary=output_text or "Managed Agent returned no output text.",
            patch=_extract_unified_diff(output_text),
            raw=json.dumps(response, indent=2) + "\n",
            request=json.dumps(body, indent=2) + "\n",
        )

    def build_create_agent_payload(self) -> dict[str, Any]:
        agent_id = self.config.managed_agent.agent_id or self.config.project.name
        payload: dict[str, Any] = {
            "id": agent_id,
            "base_agent": self.config.managed_agent.base_agent,
            "system_instruction": self.config.managed_agent.system_instruction,
            "base_environment": {
                "type": "remote",
                "sources": build_google_sources(self.root, self.config),
            },
        }
        tools = _normalize_tools(self.config.managed_agent.tools)
        if tools:
            payload["tools"] = tools
        return payload

    def build_interaction_payload(self, task_packet: str) -> dict[str, Any]:
        agent = self.config.managed_agent.base_agent
        if self.config.managed_agent.mode in {"persisted", "agent"}:
            agent = self.config.managed_agent.agent_id or agent

        payload: dict[str, Any] = {
            "agent": agent,
            "input": task_packet,
            "system_instruction": self.config.managed_agent.system_instruction,
        }
        if self.config.managed_agent.mode not in {"persisted", "agent"}:
            payload["environment"] = {
                "type": "remote",
                "sources": build_google_sources(self.root, self.config),
            }
        tools = _normalize_tools(self.config.managed_agent.tools)
        if tools:
            payload["tools"] = tools
        return payload

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key or "",
            "Api-Revision": self.config.managed_agent.api_revision,
        }
        url = f"{self.config.managed_agent.api_base.rstrip('/')}/{endpoint.lstrip('/')}"
        return self.transport(
            method="POST",
            url=url,
            headers=headers,
            payload=payload,
            timeout=self.config.managed_agent.timeout_seconds,
        )


def antigravity_sdk_available() -> bool:
    """Return whether the optional Google Antigravity SDK is installed."""
    try:
        return find_spec("google.antigravity") is not None
    except ModuleNotFoundError:
        return False


def _urllib_transport(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url=url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise ManagedAgentError(f"Managed Agents API returned {exc.code}: {details}") from exc
    except URLError as exc:
        raise ManagedAgentError(f"Managed Agents API request failed: {exc.reason}") from exc

    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManagedAgentError(f"Managed Agents API returned non-JSON response: {raw}") from exc
    if not isinstance(decoded, dict):
        raise ManagedAgentError("Managed Agents API returned an unexpected JSON shape.")
    return decoded


def _extract_output_text(response: dict[str, Any]) -> str:
    direct = response.get("output_text") or response.get("outputText")
    if isinstance(direct, str):
        return direct

    output = response.get("output")
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        nested = output.get("text") or output.get("output_text") or output.get("outputText")
        if isinstance(nested, str):
            return nested

    candidates = response.get("candidates")
    if isinstance(candidates, list):
        texts: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if isinstance(content, dict):
                parts = content.get("parts")
                if isinstance(parts, list):
                    for part in parts:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            texts.append(part["text"])
        if texts:
            return "\n".join(texts)

    steps = response.get("steps")
    if isinstance(steps, list):
        for step in reversed(steps):
            if not isinstance(step, dict) or step.get("type") != "model_output":
                continue
            content = step.get("content")
            if not isinstance(content, list):
                continue
            texts = [
                part["text"]
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
            if texts:
                return "\n".join(texts)

    return json.dumps(response, indent=2)


def _normalize_tools(tools: list[str | dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, str):
            normalized.append({"type": tool})
        elif isinstance(tool, dict):
            normalized.append(tool)
    return normalized


def _extract_unified_diff(text: str) -> str:
    if "```diff" in text:
        after = text.split("```diff", 1)[1]
        return after.split("```", 1)[0].strip() + "\n"
    if "\ndiff --git " in text or text.startswith("diff --git "):
        start = text.find("diff --git ")
        return text[start:].strip() + "\n"
    return ""

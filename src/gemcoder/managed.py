"""Gemini Managed Agent REST adapter."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

from gemcoder.config import GemCoderConfig
from gemcoder.google_sources import build_google_sources

# google_sources.py mounts files at "/workspace/repo/<rel_path>", so the
# Managed Agent generates diffs against those paths. Strip this prefix
# before handing the diff to `git apply` locally.
WORKSPACE_PREFIX = "workspace/repo/"


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

        if self.config.managed_agent.mode in {"generate_content", "generate-content", "direct"}:
            return self._run_generate_content(task_packet)

        body = self.build_interaction_payload(task_packet)
        response = self._post("interactions", body)
        output_text = _extract_output_text(response)
        return ManagedAgentResult(
            summary=output_text or "Managed Agent returned no output text.",
            patch=_extract_unified_diff(output_text),
            raw=json.dumps(response, indent=2) + "\n",
            request=json.dumps(body, indent=2) + "\n",
        )

    def _run_generate_content(self, task_packet: str) -> ManagedAgentResult:
        body = self.build_generate_content_payload(task_packet)
        response = self._post(f"models/{self._model_name()}:generateContent", body)
        output_text = _extract_output_text(response)
        return ManagedAgentResult(
            summary=output_text or "Gemini returned no output text.",
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

    def build_generate_content_payload(self, task_packet: str) -> dict[str, Any]:
        return {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "You are GemCoder using the Gemini generateContent API. "
                            "You do not have tool or function access. Answer in plain text. "
                            "When code changes are needed, return a concise summary and a "
                            "unified diff."
                        )
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": self._render_generate_content_prompt(task_packet)}],
                }
            ],
        }

    def _render_generate_content_prompt(self, task_packet: str) -> str:
        sections = [
            "Task packet:\n```yaml\n" + _strip_tool_oriented_sections(task_packet) + "\n```",
            "Repository context:",
        ]
        for source in build_google_sources(self.root, self.config):
            target = source.get("target", "unknown")
            if target.startswith(".agents/skills/"):
                continue
            content = source.get("content", "")
            sections.append(f"\n--- {target} ---\n```\n{content}\n```")
        return "\n".join(sections)

    def _model_name(self) -> str:
        return self.config.managed_agent.base_agent.removeprefix("models/")

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
    except TimeoutError as exc:
        raise ManagedAgentError(
            f"Managed Agents API request timed out after {timeout} seconds."
        ) from exc

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


def _strip_tool_oriented_sections(task_packet: str) -> str:
    try:
        packet = yaml.safe_load(task_packet)
    except yaml.YAMLError:
        return task_packet.strip()
    if not isinstance(packet, dict):
        return task_packet.strip()
    packet.pop("skills", None)
    return yaml.safe_dump(packet, sort_keys=False).strip()


def _extract_unified_diff(text: str) -> str:
    """Pull a unified diff out of the Managed Agent's text output.

    The return_contract asks for YAML with a `patch:` field, so the model
    typically wraps the diff in a ```yaml fence. Falls back to ```diff
    fences and raw `--- a/`/`diff --git` markers.
    """
    if not text:
        return ""

    for fence in ("```yaml", "```yml"):
        if fence in text:
            block = text.split(fence, 1)[1].split("```", 1)[0]
            try:
                data = yaml.safe_load(block)
            except yaml.YAMLError:
                data = None
            if isinstance(data, dict) and isinstance(data.get("patch"), str):
                patch = data["patch"].strip()
                if patch:
                    return _normalize_workspace_paths(patch) + "\n"

    if "```diff" in text:
        after = text.split("```diff", 1)[1]
        body = after.split("```", 1)[0].strip()
        if body:
            return _normalize_workspace_paths(body) + "\n"

    if "diff --git " in text:
        return _normalize_workspace_paths(text[text.find("diff --git "):].strip()) + "\n"
    # Raw `--- ` marker — works for both `--- a/X` and `--- workspace/repo/X` forms.
    for line in text.splitlines():
        if line.startswith("--- "):
            idx = text.find(line)
            return _normalize_workspace_paths(text[idx:].strip()) + "\n"
    return ""


def _normalize_workspace_paths(patch: str) -> str:
    """Force diff headers into local `a/<path>` / `b/<path>` form."""
    lines: list[str] = []
    for line in patch.splitlines():
        if line.startswith("--- ") and not line.startswith("--- /dev/null"):
            lines.append("--- a/" + _strip_path_prefix(line[4:]))
        elif line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            lines.append("+++ b/" + _strip_path_prefix(line[4:]))
        elif line.startswith("diff --git "):
            line = line.replace("a/" + WORKSPACE_PREFIX, "a/").replace(
                "b/" + WORKSPACE_PREFIX, "b/"
            )
            lines.append(line)
        else:
            lines.append(line)
    return "\n".join(lines) + ("\n" if patch.endswith("\n") else "")


def _strip_path_prefix(path: str) -> str:
    path = path.strip()
    for prefix in ("a/", "b/", "/"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    if path.startswith(WORKSPACE_PREFIX):
        path = path[len(WORKSPACE_PREFIX):]
    return path

"""Gemini Managed Agent REST adapter."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

from gemcoder.config import GemCoderConfig
from gemcoder.google_sources import build_google_sources

ChunkCallback = Callable[[str], None]

# google_sources.py mounts files at "/workspace/repo/<rel_path>", so the
# Managed Agent generates diffs against those paths. Strip this prefix
# before handing the diff to `git apply` locally.
WORKSPACE_PREFIX = "workspace/repo/"


class ManagedAgentError(RuntimeError):
    """Raised when the Managed Agents API request fails."""

    def __init__(self, message: str, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or {}


@dataclass(slots=True)
class ManagedAgentResult:
    summary: str
    patch: str = ""
    raw: str = ""
    request: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


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
        self.api_key = api_key if api_key is not None else self._load_credential()
        self.transport = transport or _urllib_transport
        self.last_diagnostics: dict[str, Any] = {}

    def create_agent(self) -> str:
        if not self.api_key:
            return self.config.managed_agent.agent_id or "managed-agent-placeholder"

        body = self.build_create_agent_payload()
        response = self._post("agents", body)
        return str(response.get("id") or response.get("name") or body["id"])

    def run_task(
        self,
        task_packet: str,
        on_chunk: ChunkCallback | None = None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> ManagedAgentResult:
        if not self.api_key:
            return ManagedAgentResult(
                summary=(
                    "GEMINI_API_KEY is not set, so GemCoder built the task packet "
                    "but did not call the Managed Agents API."
                ),
                raw=task_packet,
                diagnostics=self.request_diagnostics(self.request_endpoint()),
            )

        if self.config.managed_agent.mode in {"generate_content", "generate-content", "direct"}:
            return self._run_generate_content(
                task_packet, on_chunk=on_chunk, cancel_event=cancel_event
            )

        body = self.build_interaction_payload(task_packet)
        response = self._post("interactions", body)
        output_text = _extract_output_text(response)
        return ManagedAgentResult(
            summary=output_text or "Managed Agent returned no output text.",
            patch=_extract_unified_diff(output_text),
            raw=json.dumps(response, indent=2) + "\n",
            request=json.dumps(body, indent=2) + "\n",
            diagnostics=self.last_diagnostics,
        )

    def _run_generate_content(
        self,
        task_packet: str,
        on_chunk: ChunkCallback | None = None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> ManagedAgentResult:
        body = self.build_generate_content_payload(task_packet)
        if on_chunk is not None:
            output_text, raw_chunks = self._stream_generate_content(
                body, on_chunk, cancel_event=cancel_event
            )
            return ManagedAgentResult(
                summary=output_text or "Gemini returned no output text.",
                patch=_extract_unified_diff(output_text),
                raw=raw_chunks,
                request=json.dumps(body, indent=2) + "\n",
                diagnostics=self.last_diagnostics,
            )
        response = self._post(f"models/{self._model_name()}:generateContent", body)
        output_text = _extract_output_text(response)
        return ManagedAgentResult(
            summary=output_text or "Gemini returned no output text.",
            patch=_extract_unified_diff(output_text),
            raw=json.dumps(response, indent=2) + "\n",
            request=json.dumps(body, indent=2) + "\n",
            diagnostics=self.last_diagnostics,
        )

    def _stream_generate_content(
        self,
        body: dict[str, Any],
        on_chunk: ChunkCallback,
        *,
        cancel_event: threading.Event | None = None,
    ) -> tuple[str, str]:
        """Stream generateContent via SSE and invoke on_chunk for each text delta."""
        endpoint = f"models/{self._model_name()}:streamGenerateContent"
        url = (
            f"{self.config.managed_agent.api_base.rstrip('/')}"
            f"/{endpoint}?alt=sse"
        )
        headers = {
            "Content-Type": "application/json",
            "Api-Revision": self.config.managed_agent.api_revision,
            **self._auth_headers(),
        }
        request = Request(
            url=url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        started = perf_counter()
        diagnostics = self.request_diagnostics(endpoint)
        full_text: list[str] = []
        raw_lines: list[str] = []
        # Pre-check: if cancel was requested before we even started, bail.
        if cancel_event is not None and cancel_event.is_set():
            diagnostics.update(
                {
                    "status": "cancelled",
                    "elapsed_seconds": round(perf_counter() - started, 3),
                    "error_type": "cancelled",
                }
            )
            raise ManagedAgentError("cancelled by user", diagnostics)
        # Holder so the watcher thread can reach the live response object.
        response_holder: dict[str, Any] = {"response": None, "done": threading.Event()}

        def cancel_watcher() -> None:
            if cancel_event is None:
                return
            # Block until cancel fires or the request finishes naturally.
            while not response_holder["done"].is_set():
                if cancel_event.wait(timeout=0.1):
                    resp = response_holder["response"]
                    if resp is not None:
                        # Closing the underlying socket unblocks the read
                        # loop with an OSError, which our handler converts
                        # into a clean ManagedAgentError("cancelled by user").
                        try:
                            # Hard-shutdown the underlying socket so any
                            # pending recv() returns immediately.
                            sock = getattr(getattr(resp, "fp", None), "raw", None)
                            if sock is None:
                                sock = getattr(resp, "fp", None)
                            try:
                                import socket as _socket  # noqa: PLC0415

                                if sock is not None and hasattr(sock, "_sock"):
                                    sock._sock.shutdown(_socket.SHUT_RDWR)
                            except Exception:  # noqa: BLE001
                                pass
                            resp.close()
                        except Exception:  # noqa: BLE001
                            pass
                    return

        watcher: threading.Thread | None = None
        if cancel_event is not None:
            watcher = threading.Thread(target=cancel_watcher, daemon=True)
            watcher.start()

        try:
            with urlopen(  # noqa: S310
                request, timeout=self.config.managed_agent.timeout_seconds
            ) as response:
                response_holder["response"] = response
                for line_bytes in response:
                    if cancel_event is not None and cancel_event.is_set():
                        try:
                            response.close()
                        except Exception:  # noqa: BLE001
                            pass
                        diagnostics.update(
                            {
                                "status": "cancelled",
                                "elapsed_seconds": round(perf_counter() - started, 3),
                                "error_type": "cancelled",
                            }
                        )
                        raise ManagedAgentError("cancelled by user", diagnostics)
                    line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
                    if not line:
                        continue
                    raw_lines.append(line)
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: "):].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    delta = _extract_output_text(event)
                    if delta:
                        full_text.append(delta)
                        on_chunk(delta)
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            diagnostics.update(
                {
                    "status": "failed",
                    "elapsed_seconds": round(perf_counter() - started, 3),
                    "http_status": exc.code,
                    "error_type": "http",
                }
            )
            raise ManagedAgentError(
                f"streamGenerateContent returned {exc.code}: {details}",
                diagnostics,
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            # If cancel fired, the watcher thread closed the underlying
            # socket — that surfaces as an OSError / URLError here. Convert
            # any error raised after cancellation into a clean cancel.
            if cancel_event is not None and cancel_event.is_set():
                diagnostics.update(
                    {
                        "status": "cancelled",
                        "elapsed_seconds": round(perf_counter() - started, 3),
                        "error_type": "cancelled",
                    }
                )
                raise ManagedAgentError("cancelled by user", diagnostics) from exc
            if isinstance(exc, TimeoutError):
                error_type = "timeout"
            elif isinstance(exc, URLError):
                error_type = (
                    "timeout"
                    if isinstance(exc.reason, TimeoutError)
                    else "network"
                )
            else:
                error_type = "network"
            diagnostics.update(
                {
                    "status": "failed",
                    "elapsed_seconds": round(perf_counter() - started, 3),
                    "error_type": error_type,
                }
            )
            raise ManagedAgentError(
                f"streamGenerateContent failed: {exc}",
                diagnostics,
            ) from exc
        finally:
            # Always wake the watcher so it can exit promptly.
            response_holder["done"].set()
        diagnostics.update(
            {"status": "success", "elapsed_seconds": round(perf_counter() - started, 3)}
        )
        self.last_diagnostics = diagnostics
        return "".join(full_text), "\n".join(raw_lines) + "\n"

    def build_request_payload(self, task_packet: str) -> dict[str, Any]:
        if self.config.managed_agent.mode in {"generate_content", "generate-content", "direct"}:
            return self.build_generate_content_payload(task_packet)
        return self.build_interaction_payload(task_packet)

    def request_endpoint(self) -> str:
        if self.config.managed_agent.mode in {"generate_content", "generate-content", "direct"}:
            return f"models/{self._model_name()}:generateContent"
        return "interactions"

    def request_diagnostics(self, endpoint: str) -> dict[str, Any]:
        return {
            "provider": self.config.managed_agent.provider,
            "mode": self.config.managed_agent.mode,
            "model": self._provider_target(),
            "endpoint": endpoint,
        }

    def build_create_agent_payload(self) -> dict[str, Any]:
        agent_id = self.config.managed_agent.agent_id or self.config.project.name
        payload: dict[str, Any] = {
            "id": agent_id,
            "base_agent": self.config.managed_agent.base_agent,
            "system_instruction": self.config.managed_agent.system_instruction,
            "base_environment": self._remote_environment(),
        }
        if self.config.managed_agent.description:
            payload["description"] = self.config.managed_agent.description
        tools = _normalize_tools(self.config.managed_agent.tools)
        if tools:
            payload["tools"] = tools
        return payload

    def build_interaction_payload(self, task_packet: str) -> dict[str, Any]:
        agent = self.config.managed_agent.base_agent
        if self.config.managed_agent.mode in {"persisted", "agent"}:
            agent = self.config.managed_agent.agent_id or agent

        payload: dict[str, Any] = {
            "stream": self.config.managed_agent.stream,
            "background": self.config.managed_agent.background,
            "store": self.config.managed_agent.store,
            "agent": agent,
            "input": [
                {
                    "type": "user_input",
                    "content": [{"type": "text", "text": task_packet}],
                }
            ],
        }
        if self.config.managed_agent.mode not in {"persisted", "agent"}:
            payload["environment"] = self._remote_environment()
        tools = _normalize_tools(self.config.managed_agent.tools)
        if tools:
            payload["tools"] = tools
        return payload

    def _remote_environment(self) -> dict[str, Any]:
        environment: dict[str, Any] = {
            "type": "remote",
            "sources": build_google_sources(self.root, self.config),
        }
        allowlist = [
            {"domain": domain.strip()}
            for domain in self.config.managed_agent.network_allowlist
            if domain.strip()
        ]
        if allowlist:
            environment["network"] = {"allowlist": allowlist}
        return environment

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

    def _provider_target(self) -> str:
        if self.config.managed_agent.mode in {"persisted", "agent"}:
            return self.config.managed_agent.agent_id or self.config.managed_agent.base_agent
        return self._model_name()

    def _load_credential(self) -> str | None:
        if self.config.managed_agent.auth_type == "bearer":
            return os.getenv(self.config.managed_agent.access_token_env)
        return os.getenv(self.config.managed_agent.api_key_env)

    def _auth_headers(self) -> dict[str, str]:
        if self.config.managed_agent.auth_type == "bearer":
            return {"Authorization": f"Bearer {self.api_key or ''}"}
        return {"x-goog-api-key": self.api_key or ""}

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Api-Revision": self.config.managed_agent.api_revision,
            **self._auth_headers(),
        }
        url = f"{self.config.managed_agent.api_base.rstrip('/')}/{endpoint.lstrip('/')}"
        started = perf_counter()
        diagnostics = self.request_diagnostics(endpoint)
        try:
            response = self.transport(
                method="POST",
                url=url,
                headers=headers,
                payload=payload,
                timeout=self.config.managed_agent.timeout_seconds,
            )
        except TimeoutError as exc:
            elapsed = round(perf_counter() - started, 3)
            diagnostics.update(
                {
                    "status": "failed",
                    "elapsed_seconds": elapsed,
                    "error_type": "timeout",
                }
            )
            raise ManagedAgentError(
                "Managed Agents API request timed out after "
                f"{self.config.managed_agent.timeout_seconds} seconds.",
                diagnostics,
            ) from exc
        except ManagedAgentError as exc:
            elapsed = round(perf_counter() - started, 3)
            diagnostics.update(exc.diagnostics)
            diagnostics.setdefault("status", "failed")
            diagnostics["elapsed_seconds"] = elapsed
            exc.diagnostics = diagnostics
            raise

        diagnostics.update(
            {"status": "success", "elapsed_seconds": round(perf_counter() - started, 3)}
        )
        self.last_diagnostics = diagnostics
        return response


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
        raise ManagedAgentError(
            f"Managed Agents API returned {exc.code}: {details}",
            {"http_status": exc.code, "error_type": "http"},
        ) from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ManagedAgentError(
                f"Managed Agents API request timed out after {timeout} seconds.",
                {"error_type": "timeout"},
            ) from exc
        raise ManagedAgentError(
            f"Managed Agents API request failed: {exc.reason}",
            {"error_type": "network"},
        ) from exc
    except TimeoutError as exc:
        raise ManagedAgentError(
            f"Managed Agents API request timed out after {timeout} seconds.",
            {"error_type": "timeout"},
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

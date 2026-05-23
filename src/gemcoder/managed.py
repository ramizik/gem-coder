"""Gemini Managed Agents adapter.

Wraps the google-genai SDK with structured output so the harness gets back
a typed (summary, patch) pair instead of free-form text.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import BaseModel, Field

from gemcoder.config import GemCoderConfig

DEFAULT_MODEL = "gemini-flash-latest"

SYSTEM_INSTRUCTION = """You are GemCoder, a careful coding agent.

You receive a YAML task packet with the user goal, repository instructions, and
reusable skills. Respond with a small, safe change.

Rules:
- Make the smallest patch that solves the goal.
- Avoid unrelated refactors.
- Patch must be a valid unified diff with `--- a/<path>` and `+++ b/<path>` headers,
  applicable from the repository root with `git apply`.
- If no change is needed, return an empty patch and explain why in the summary.
- Summary is one short paragraph: what you changed and why.
"""


class _AgentJSON(BaseModel):
    summary: str = Field(description="Short summary of what changed and why.")
    patch: str = Field(description="Unified diff, or empty string if no change.")


@dataclass(slots=True)
class ManagedAgentResult:
    summary: str
    patch: str = ""
    raw: str = ""


class ManagedAgentError(RuntimeError):
    pass


class ManagedAgentClient:
    def __init__(self, config: GemCoderConfig) -> None:
        self.config = config
        self._model = config.managed_agent.agent_id or DEFAULT_MODEL

    def create_agent(self) -> str:
        return self._model

    def run_task(self, task_packet: str) -> ManagedAgentResult:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ManagedAgentError(
                "GEMINI_API_KEY is not set. Export it before running tasks."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ManagedAgentError(
                "google-genai is not installed. Run `uv sync` or `pip install google-genai`."
            ) from exc

        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(
                model=self._model,
                contents=task_packet,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=_AgentJSON,
                ),
            )
        except Exception as exc:
            raise ManagedAgentError(f"Gemini API call failed: {exc}") from exc

        raw = response.text or ""
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, _AgentJSON):
            return ManagedAgentResult(summary=parsed.summary, patch=parsed.patch, raw=raw)

        try:
            data = _AgentJSON.model_validate_json(raw)
        except Exception as exc:
            raise ManagedAgentError(
                f"Could not parse model response as JSON: {exc}\n{raw[:500]}"
            ) from exc
        return ManagedAgentResult(summary=data.summary, patch=data.patch, raw=raw)

"""Managed Agent adapter skeleton.

The hackathon implementation should replace this stub with the Gemini Managed
Agents API calls. Keeping the adapter boundary explicit lets the CLI and TUI
develop independently from the API wiring.
"""

from __future__ import annotations

from dataclasses import dataclass

from gemcoder.config import GemCoderConfig


@dataclass(slots=True)
class ManagedAgentResult:
    summary: str
    patch: str = ""
    raw: str = ""


class ManagedAgentClient:
    def __init__(self, config: GemCoderConfig) -> None:
        self.config = config

    def create_agent(self) -> str:
        agent_id = self.config.managed_agent.agent_id or "managed-agent-placeholder"
        return agent_id

    def run_task(self, task_packet: str) -> ManagedAgentResult:
        return ManagedAgentResult(
            summary=(
                "Managed Agent API integration is not wired yet. "
                "Task packet was built and stored for this run."
            ),
            raw=task_packet,
        )

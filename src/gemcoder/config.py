"""Project configuration for GemCoder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

CONFIG_FILE = "gemcoder.yaml"


class ProjectConfig(BaseModel):
    name: str = "gemcoder-project"


class ManagedAgentConfig(BaseModel):
    provider: str = "google"
    mode: str = "default"
    reuse_sessions: bool = True
    agent_id: str | None = None


class HarnessConfig(BaseModel):
    instructions: str = "AGENTS.md"
    skills_dir: str = ".gemcoder/skills"
    patch_format: str = "unified_diff"


class VerificationConfig(BaseModel):
    commands: list[str] = Field(default_factory=list)
    require_pass: bool = True


class ApprovalConfig(BaseModel):
    apply_patch: bool = True
    shell_commands: bool = False


class OptimizationConfig(BaseModel):
    enabled: bool = True
    objective: list[str] = Field(
        default_factory=lambda: ["tests_pass", "minimal_diff", "low_latency"]
    )


class GemCoderConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    managed_agent: ManagedAgentConfig = Field(default_factory=ManagedAgentConfig)
    harness: HarnessConfig = Field(default_factory=HarnessConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    approvals: ApprovalConfig = Field(default_factory=ApprovalConfig)
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)


def load_config(root: str | Path = ".") -> GemCoderConfig:
    path = Path(root) / CONFIG_FILE
    if not path.exists():
        return GemCoderConfig()
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_FILE} must contain a YAML mapping.")
    return GemCoderConfig.model_validate(data)


def dump_config(config: GemCoderConfig) -> str:
    data: dict[str, Any] = config.model_dump(exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False)

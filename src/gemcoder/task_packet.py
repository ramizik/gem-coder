"""Task packet construction."""

from __future__ import annotations

from pathlib import Path

import yaml

from gemcoder.config import GemCoderConfig


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(errors="replace")


def load_skills(root: Path, config: GemCoderConfig) -> dict[str, str]:
    skills_dir = root / config.harness.skills_dir
    if not skills_dir.exists():
        return {}
    skills: dict[str, str] = {}
    for path in sorted(skills_dir.glob("*.md")):
        skills[path.stem] = path.read_text(errors="replace")
    return skills


def build_task_packet(root: str | Path, task: str, config: GemCoderConfig) -> str:
    base = Path(root)
    instructions = read_text_if_exists(base / config.harness.instructions)
    skills = load_skills(base, config)
    payload = {
        "goal": task,
        "repo": {
            "name": config.project.name,
            "test_commands": config.verification.commands,
        },
        "instructions": instructions,
        "skills": skills,
        "constraints": [
            "Make the smallest safe patch.",
            "Avoid unrelated refactors.",
            "Return a unified diff.",
            "Summarize commands run and verification status.",
        ],
        "return_contract": {
            "patch": config.harness.patch_format,
            "changed_files": "list",
            "commands_run": "list",
            "test_result": "summary",
            "final_summary": "short",
        },
    }
    return yaml.safe_dump(payload, sort_keys=False)

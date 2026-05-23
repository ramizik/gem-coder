"""Project scaffold templates."""

from __future__ import annotations

from pathlib import Path

from gemcoder.config import GemCoderConfig, ProjectConfig, dump_config

DEFAULT_AGENTS_MD = """# AGENTS.md

You are GemCoder, a coding agent working inside this repository.

Follow these rules:

- Understand the relevant files before editing.
- Make the smallest safe patch that solves the task.
- Prefer tests or verification commands before finalizing.
- Return changes as a unified diff when requested.
- Do not make destructive changes unless explicitly approved.
"""


DEFAULT_SKILLS = {
    "repo-navigation.md": """# repo-navigation

Use this skill to inspect a repository efficiently.

1. Identify the language, package manager, and test command.
2. Read the smallest set of files needed for the task.
3. Summarize the architecture before proposing changes.
""",
    "safe-patch.md": """# safe-patch

Use this skill when editing code.

1. Keep the patch focused.
2. Avoid unrelated refactors.
3. Preserve public behavior unless the task requires a change.
4. Return a unified diff and a short summary.
""",
    "test-driven-fix.md": """# test-driven-fix

Use this skill for bugs and failing tests.

1. Reproduce or inspect the failing test.
2. Patch the smallest relevant implementation area.
3. Add or update a regression test when appropriate.
4. Run the configured verification command.
""",
}


def default_config(project_name: str) -> str:
    config = GemCoderConfig(project=ProjectConfig(name=project_name))
    return dump_config(config)


def scaffold(root: str | Path = ".", *, force: bool = False) -> list[Path]:
    base = Path(root)
    project_name = base.resolve().name
    files: dict[Path, str] = {
        base / "AGENTS.md": DEFAULT_AGENTS_MD,
        base / "gemcoder.yaml": default_config(project_name),
    }
    for filename, content in DEFAULT_SKILLS.items():
        files[base / ".gemcoder" / "skills" / filename] = content

    dirs = [
        base / ".gemcoder" / "runs",
        base / ".gemcoder" / "sessions",
        base / ".gemcoder" / "evals",
        base / ".gemcoder" / "cache",
    ]

    written: list[Path] = []
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not force:
            continue
        path.write_text(content)
        written.append(path)
    return written

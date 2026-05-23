"""Task packet construction."""

from __future__ import annotations

from pathlib import Path

import yaml

from gemcoder.config import GemCoderConfig

SENSITIVE_CONTEXT_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}

SENSITIVE_CONTEXT_SUFFIXES = {
    ".pem",
    ".key",
    ".crt",
    ".p12",
    ".pfx",
}


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


def _is_excluded(path: Path, patterns: list[str]) -> bool:
    normalized = path.as_posix()
    if _is_sensitive_context_path(path):
        return True
    for pattern in patterns:
        if path.match(pattern):
            return True
        if pattern.endswith("/**") and normalized.startswith(pattern.removesuffix("/**")):
            return True
    return False


def _is_sensitive_context_path(path: Path) -> bool:
    name = path.name.lower()
    normalized = path.as_posix().lower()
    if name in SENSITIVE_CONTEXT_NAMES:
        return True
    if name.startswith(".env."):
        return True
    if path.suffix.lower() in SENSITIVE_CONTEXT_SUFFIXES:
        return True
    return any(token in normalized for token in ("secret", "credential", "token"))


def collect_context_files(root: Path, config: GemCoderConfig) -> list[str]:
    files: list[str] = []
    for pattern in config.context.include:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if _is_excluded(relative, config.context.exclude):
                continue
            rendered = relative.as_posix()
            if rendered not in files:
                files.append(rendered)
            if len(files) >= config.context.max_files:
                return files
    return files


def build_task_packet(
    root: str | Path,
    task: str,
    config: GemCoderConfig,
    *,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    base = Path(root)
    instructions = read_text_if_exists(base / config.harness.instructions)
    skills = load_skills(base, config)
    context_files = collect_context_files(base, config)
    payload: dict[str, object] = {
        "goal": task,
        "repo": {
            "name": config.project.name,
            "test_commands": config.verification.commands,
            "context_files": context_files,
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
    if conversation_history:
        payload["conversation_history"] = conversation_history
    return yaml.safe_dump(payload, sort_keys=False)

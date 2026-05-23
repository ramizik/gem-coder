"""Compile GemCoder harness files into Google Managed Agent sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gemcoder.config import CONFIG_FILE, GemCoderConfig
from gemcoder.task_packet import collect_context_files, load_skills


@dataclass(slots=True)
class GoogleInlineSource:
    target: str
    content: str
    type: str = "inline"

    def as_payload(self) -> dict[str, str]:
        return {"type": self.type, "target": self.target, "content": self.content}


def build_google_sources(root: str | Path, config: GemCoderConfig) -> list[dict[str, str]]:
    """Build inline Managed Agent sources from local harness and repo context."""
    base = Path(root)
    sources: list[GoogleInlineSource] = []

    instructions_path = base / config.harness.instructions
    if instructions_path.exists():
        sources.append(
            GoogleInlineSource(
                target=".agents/AGENTS.md",
                content=instructions_path.read_text(errors="replace"),
            )
        )

    for name, content in sorted(load_skills(base, config).items()):
        sources.append(
            GoogleInlineSource(
                target=f".agents/skills/{_source_name(name)}/SKILL.md",
                content=content,
            )
        )

    skipped = {
        CONFIG_FILE,
        config.harness.instructions,
    }
    for rel_path in collect_context_files(base, config):
        if rel_path in skipped:
            continue
        path = base / rel_path
        if not path.is_file() or _looks_binary(path):
            continue
        sources.append(
            GoogleInlineSource(
                target=f"/workspace/repo/{rel_path}",
                content=path.read_text(errors="replace"),
            )
        )

    return [source.as_payload() for source in sources]


def _source_name(name: str) -> str:
    return Path(name).stem.replace(" ", "-").lower()


def _looks_binary(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:1024]
    except OSError:
        return True
    return b"\0" in sample

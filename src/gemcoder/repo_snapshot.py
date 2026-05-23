"""Collect a bounded snapshot of repo text files for the task packet."""

from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_MAX_FILES = 60
DEFAULT_MAX_PER_FILE = 30_000
DEFAULT_MAX_TOTAL = 200_000


def _looks_text(data: bytes) -> bool:
    return b"\x00" not in data[:8192]


def collect_repo_snapshot(
    root: str | Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_per_file: int = DEFAULT_MAX_PER_FILE,
    max_total: int = DEFAULT_MAX_TOTAL,
) -> dict[str, str]:
    """Return {relative_path: content} for git-tracked text files under size limits.

    Returns an empty dict if the directory is not a git repo.
    """
    base = Path(root)
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=base,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}

    files: dict[str, str] = {}
    total = 0
    for rel in result.stdout.splitlines():
        if not rel or len(files) >= max_files:
            continue
        path = base / rel
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if len(data) > max_per_file or not _looks_text(data):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if total + len(text) > max_total:
            continue
        files[rel] = text
        total += len(text)
    return files

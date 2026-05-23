"""Apply unified-diff patches via `git apply`."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_FILE_HEADER = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


@dataclass(slots=True)
class ApplyResult:
    ok: bool
    files: list[str] = field(default_factory=list)
    stderr: str = ""
    dry_run: bool = False


def parse_changed_files(patch_text: str) -> list[str]:
    return _FILE_HEADER.findall(patch_text)


def apply_patch(root: str | Path, patch_text: str, *, dry_run: bool = False) -> ApplyResult:
    if not patch_text.strip():
        return ApplyResult(ok=True, files=[], dry_run=dry_run)

    files = parse_changed_files(patch_text)
    args = ["git", "apply", "--check"] if dry_run else ["git", "apply"]
    completed = subprocess.run(
        args,
        cwd=Path(root),
        input=patch_text,
        text=True,
        capture_output=True,
        check=False,
    )
    return ApplyResult(
        ok=completed.returncode == 0,
        files=files,
        stderr=completed.stderr,
        dry_run=dry_run,
    )

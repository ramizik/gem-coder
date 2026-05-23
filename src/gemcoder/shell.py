"""Small, safe local shell surface for the TUI."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class ShellResult:
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""

    def asdict(self) -> dict[str, object]:
        return asdict(self)


def run_shell_command(root: str | Path, command: str) -> ShellResult:
    args = _parse_allowed_command(command)
    completed = subprocess.run(
        args,
        cwd=Path(root),
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return ShellResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout[-12000:],
        stderr=completed.stderr[-4000:],
    )


def _parse_allowed_command(command: str) -> list[str]:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"Could not parse command: {exc}") from exc
    if not parts:
        raise ValueError("Command is empty.")

    if parts[0] in {"pwd", "ls"}:
        return parts

    if parts[0] == "git" and len(parts) >= 2 and parts[1] in {"status", "branch", "log"}:
        return parts

    raise ValueError(
        "Only safe local inspection commands are supported here: "
        "ls, pwd, git status, git branch, git log."
    )

"""Local verification commands."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class VerificationResult:
    command: str
    returncode: int
    stdout: str
    stderr: str


def run_verification(root: str | Path, commands: list[str]) -> list[VerificationResult]:
    results: list[VerificationResult] = []
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=Path(root),
            shell=True,
            text=True,
            capture_output=True,
            check=False,
        )
        results.append(
            VerificationResult(
                command=command,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        )
    return results

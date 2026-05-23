"""Local verification commands."""

from __future__ import annotations

import os
import signal
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
        proc = subprocess.Popen(
            command,
            cwd=Path(root),
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            proc.communicate()
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            results.append(
                VerificationResult(
                    command=command,
                    returncode=124,
                    stdout=stdout,
                    stderr=stderr + "\nVerification command timed out after 60 seconds.",
                )
            )
        else:
            results.append(
                VerificationResult(
                    command=command,
                    returncode=proc.returncode or 0,
                    stdout=stdout,
                    stderr=stderr,
                )
            )
    return results

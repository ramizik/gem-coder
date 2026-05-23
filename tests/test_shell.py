from pathlib import Path

import pytest

from gemcoder.shell import run_shell_command


def test_run_shell_command_allows_ls(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello")

    result = run_shell_command(tmp_path, "ls")

    assert result.returncode == 0
    assert "hello.txt" in result.stdout


def test_run_shell_command_rejects_arbitrary_commands(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Only safe local inspection commands"):
        run_shell_command(tmp_path, "cat .env")

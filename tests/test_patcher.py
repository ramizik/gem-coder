import subprocess
from pathlib import Path

from gemcoder.patcher import apply_patch, parse_changed_files


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(root: Path, file_path: str, content: str) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    (root / file_path).write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")


PATCH = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""


def test_parse_changed_files() -> None:
    assert parse_changed_files(PATCH) == ["hello.txt"]


def test_apply_patch_dry_run(tmp_path: Path) -> None:
    _init_repo(tmp_path, "hello.txt", "hello\n")
    result = apply_patch(tmp_path, PATCH, dry_run=True)
    assert result.ok
    assert result.files == ["hello.txt"]
    assert (tmp_path / "hello.txt").read_text() == "hello\n"  # unchanged


def test_apply_patch_writes(tmp_path: Path) -> None:
    _init_repo(tmp_path, "hello.txt", "hello\n")
    result = apply_patch(tmp_path, PATCH)
    assert result.ok
    assert (tmp_path / "hello.txt").read_text() == "hello world\n"


def test_apply_patch_empty(tmp_path: Path) -> None:
    result = apply_patch(tmp_path, "")
    assert result.ok
    assert result.files == []


def test_apply_patch_bad_diff(tmp_path: Path) -> None:
    _init_repo(tmp_path, "hello.txt", "hello\n")
    result = apply_patch(tmp_path, "not a real patch\n")
    assert not result.ok
    assert result.stderr

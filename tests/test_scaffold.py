from pathlib import Path

from gemcoder.config import load_config
from gemcoder.task_packet import build_task_packet
from gemcoder.templates import scaffold


def test_scaffold_creates_project_files(tmp_path: Path) -> None:
    written = scaffold(tmp_path)

    assert tmp_path / "AGENTS.md" in written
    assert tmp_path / "gemcoder.yaml" in written
    assert (tmp_path / ".gemcoder" / "skills" / "safe-patch.md").exists()
    assert (tmp_path / ".gemcoder" / "runs").exists()


def test_load_config_from_scaffold(tmp_path: Path) -> None:
    scaffold(tmp_path)

    config = load_config(tmp_path)

    assert config.project.name == tmp_path.name
    assert config.harness.instructions == "AGENTS.md"


def test_build_task_packet_includes_task_and_skills(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)

    packet = build_task_packet(tmp_path, "Fix tests", config)

    assert "Fix tests" in packet
    assert "safe-patch" in packet
    assert "unified_diff" in packet

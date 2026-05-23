from pathlib import Path

from gemcoder.config import load_config
from gemcoder.google_sources import build_google_sources
from gemcoder.harness import HarnessRunner
from gemcoder.managed import ManagedAgentClient, _extract_output_text, _extract_unified_diff
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


def test_context_collection_excludes_env_and_secret_files(tmp_path: Path) -> None:
    scaffold(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=secret")
    (tmp_path / "service.pem").write_text("secret")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')")
    config = load_config(tmp_path)

    packet = build_task_packet(tmp_path, "Inspect context", config)
    sources = build_google_sources(tmp_path, config)
    targets = {source["target"] for source in sources}

    assert ".env" not in packet
    assert "service.pem" not in packet
    assert "/workspace/repo/.env" not in targets
    assert "/workspace/repo/service.pem" not in targets
    assert "/workspace/repo/src/app.py" in targets


def test_harness_runner_records_harness_loaded(tmp_path: Path) -> None:
    scaffold(tmp_path)
    runner = HarnessRunner(tmp_path)

    result = runner.run("Fix tests")
    events = runner.store.read_events(result.run_id)

    assert any(event.type == "harness.loaded" for event in events)
    assert any(event.type == "task.packet.created" for event in events)


def test_harness_inspection_includes_skills(tmp_path: Path) -> None:
    scaffold(tmp_path)
    details = HarnessRunner(tmp_path).inspect_harness()

    assert "safe-patch" in details["skills"]
    assert details["instructions_exists"] is True


def test_harness_build_creates_artifacts(tmp_path: Path) -> None:
    scaffold(tmp_path)
    runner = HarnessRunner(tmp_path)

    result = runner.build()

    assert result.manifest_path.exists()
    assert result.harness_path.exists()
    assert result.task_template_path.exists()
    assert result.instructions_path.exists()
    assert result.skills_bundle_path.exists()
    assert result.google_sources_path.exists()
    assert (tmp_path / ".gemcoder" / "build" / "current.json").exists()


def test_run_records_current_build(tmp_path: Path) -> None:
    scaffold(tmp_path)
    runner = HarnessRunner(tmp_path)
    runner.build()

    result = runner.run("Fix tests")
    events = runner.store.read_events(result.run_id)

    assert any(event.type == "harness.build.loaded" for event in events)


def test_google_sources_map_harness_files_to_agent_layout(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)

    sources = build_google_sources(tmp_path, config)
    targets = {source["target"] for source in sources}

    assert ".agents/AGENTS.md" in targets
    assert ".agents/skills/safe-patch/SKILL.md" in targets


def test_managed_agent_interaction_payload_uses_inline_sources(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    client = ManagedAgentClient(config, tmp_path, api_key="test-key")

    payload = client.build_interaction_payload("goal: Fix tests")

    assert payload["agent"] == "antigravity-preview-05-2026"
    assert payload["input"] == "goal: Fix tests"
    assert payload["environment"]["type"] == "remote"
    assert any(
        source["target"] == ".agents/AGENTS.md"
        for source in payload["environment"]["sources"]
    )
    assert "tools" not in payload


def test_managed_agent_payload_normalizes_configured_tools(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.managed_agent.tools = ["google_search", {"type": "url_context"}]
    client = ManagedAgentClient(config, tmp_path, api_key="test-key")

    payload = client.build_interaction_payload("goal: Research docs")

    assert payload["tools"] == [{"type": "google_search"}, {"type": "url_context"}]


def test_managed_agent_client_uses_rest_transport(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    calls = []

    def fake_transport(**kwargs):
        calls.append(kwargs)
        return {"output_text": "done"}

    client = ManagedAgentClient(
        config,
        tmp_path,
        api_key="test-key",
        transport=fake_transport,
    )

    result = client.run_task("goal: Fix tests")

    assert result.summary == "done"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/interactions")
    assert calls[0]["headers"]["x-goog-api-key"] == "test-key"


def test_extract_output_text_reads_managed_agent_model_output() -> None:
    response = {
        "steps": [
            {"type": "thought", "summary": [{"text": "internal"}]},
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "final summary"}],
            },
        ]
    }

    assert _extract_output_text(response) == "final summary"


def test_extract_unified_diff_normalizes_workspace_paths() -> None:
    text = """```diff
diff --git a/workspace/repo/src/app.py b/workspace/repo/src/app.py
--- a/workspace/repo/src/app.py
+++ b/workspace/repo/src/app.py
@@ -1 +1 @@
-old
+new
```"""

    patch = _extract_unified_diff(text)

    assert "workspace/repo" not in patch
    assert "diff --git a/src/app.py b/src/app.py" in patch
    assert "+++ b/src/app.py" in patch

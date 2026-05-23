import os
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

from gemcoder.cli.main import _failure_guidance, _load_dotenv
from gemcoder.config import load_config
from gemcoder.google_sources import build_google_sources
from gemcoder.harness import HarnessRunner
from gemcoder.managed import (
    ManagedAgentClient,
    ManagedAgentError,
    _extract_output_text,
    _extract_unified_diff,
    _strip_tool_oriented_sections,
    _urllib_transport,
)
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


def test_load_dotenv_accepts_export_syntax(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text('export GEMINI_API_KEY="test-key"\n')

    _load_dotenv(tmp_path)

    assert os.environ["GEMINI_API_KEY"] == "test-key"


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


def test_harness_runner_records_harness_loaded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
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


def test_run_records_current_build(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    scaffold(tmp_path)
    runner = HarnessRunner(tmp_path)
    runner.build()

    result = runner.run("Fix tests")
    events = runner.store.read_events(result.run_id)

    assert any(event.type == "harness.build.loaded" for event in events)


def test_fix_failing_tests_returns_when_verification_already_passes(
    tmp_path: Path, monkeypatch
) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.verification.commands = ["echo ok"]

    def fake_run_verification(root, commands):
        from gemcoder.verify import VerificationResult

        return [VerificationResult(command=commands[0], returncode=0, stdout="ok\n", stderr="")]

    monkeypatch.setattr("gemcoder.harness.run_verification", fake_run_verification)

    result = HarnessRunner(tmp_path, config).run("Fix the failing tests")
    events = HarnessRunner(tmp_path, config).store.read_events(result.run_id)

    assert "already pass" in result.summary
    assert any(event.type == "verification.preflight.passed" for event in events)
    assert not any(event.type == "managed.interaction.started" for event in events)


def test_run_records_managed_agent_error(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.orchestrator.default_backend = "remote"

    def fake_run_task(self, task_packet, **kwargs):
        raise ManagedAgentError("boom")

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("gemcoder.managed.ManagedAgentClient.run_task", fake_run_task)

    runner = HarnessRunner(tmp_path, config)
    result = runner.run("hello")
    events = runner.store.read_events(result.run_id)

    assert result.summary == "Managed Agent request failed: boom"
    assert any(event.type == "managed.interaction.failed" for event in events)


def test_google_sources_map_harness_files_to_agent_layout(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)

    sources = build_google_sources(tmp_path, config)
    targets = {source["target"] for source in sources}

    assert ".agents/AGENTS.md" in targets
    assert ".agents/skills/safe-patch/SKILL.md" in targets


def test_interaction_payload_uses_inline_sources(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.managed_agent.mode = "managed_agent"
    client = ManagedAgentClient(config, tmp_path, api_key="test-key")

    payload = client.build_interaction_payload("goal: Fix tests")

    assert payload["agent"] == "gemini-flash-latest"
    assert payload["stream"] is True
    assert payload["background"] is True
    assert payload["store"] is True
    assert payload["input"] == [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": "goal: Fix tests"}],
        }
    ]
    assert payload["environment"]["type"] == "remote"
    assert any(
        source["target"] == ".agents/AGENTS.md"
        for source in payload["environment"]["sources"]
    )
    assert "tools" not in payload


def test_create_agent_payload_supports_managed_agents_environment_options(
    tmp_path: Path,
) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.managed_agent.base_agent = "antigravity-preview-05-2026"
    config.managed_agent.description = "GemCoder managed coding agent"
    config.managed_agent.network_allowlist = ["pypi.org", "files.pythonhosted.org"]
    client = ManagedAgentClient(config, tmp_path, api_key="test-key")

    payload = client.build_create_agent_payload()

    assert payload["base_agent"] == "antigravity-preview-05-2026"
    assert payload["description"] == "GemCoder managed coding agent"
    assert payload["base_environment"]["network"] == {
        "allowlist": [{"domain": "pypi.org"}, {"domain": "files.pythonhosted.org"}]
    }
    assert any(
        source["target"] == ".agents/AGENTS.md"
        for source in payload["base_environment"]["sources"]
    )


def test_bearer_auth_uses_authorization_header(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.managed_agent.mode = "managed_agent"
    config.managed_agent.auth_type = "bearer"
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "access-token")
    calls = []

    def fake_transport(**kwargs):
        calls.append(kwargs)
        return {"output_text": "done"}

    client = ManagedAgentClient(config, tmp_path, transport=fake_transport)

    result = client.run_task("goal: Fix tests")

    assert result.summary == "done"
    assert calls[0]["headers"]["Authorization"] == "Bearer access-token"
    assert "x-goog-api-key" not in calls[0]["headers"]


def test_interaction_payload_normalizes_configured_tools(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.managed_agent.mode = "managed_agent"
    config.managed_agent.tools = ["google_search", {"type": "url_context"}]
    client = ManagedAgentClient(config, tmp_path, api_key="test-key")

    payload = client.build_interaction_payload("goal: Research docs")

    assert payload["tools"] == [{"type": "google_search"}, {"type": "url_context"}]


def test_generate_content_client_uses_rest_transport(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    calls = []

    def fake_transport(**kwargs):
        calls.append(kwargs)
        return {"candidates": [{"content": {"parts": [{"text": "done"}]}}]}

    client = ManagedAgentClient(
        config,
        tmp_path,
        api_key="test-key",
        transport=fake_transport,
    )

    result = client.run_task("goal: Fix tests")

    assert result.summary == "done"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/models/gemini-flash-latest:generateContent")
    assert calls[0]["headers"]["x-goog-api-key"] == "test-key"
    assert result.diagnostics["mode"] == "generate_content"
    assert result.diagnostics["model"] == "gemini-flash-latest"
    assert result.diagnostics["endpoint"] == "models/gemini-flash-latest:generateContent"
    assert result.diagnostics["status"] == "success"
    assert "elapsed_seconds" in result.diagnostics


def test_generate_content_mode_uses_model_endpoint(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.managed_agent.mode = "generate_content"
    config.managed_agent.base_agent = "gemini-flash-latest"
    calls = []

    def fake_transport(**kwargs):
        calls.append(kwargs)
        return {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}

    client = ManagedAgentClient(
        config,
        tmp_path,
        api_key="test-key",
        transport=fake_transport,
    )

    result = client.run_task("goal: Say hello")

    assert result.summary == "hello"
    assert calls[0]["url"].endswith("/models/gemini-flash-latest:generateContent")
    assert "contents" in calls[0]["payload"]
    assert "systemInstruction" in calls[0]["payload"]


def test_stream_generate_content_records_success_diagnostics(
    tmp_path: Path, monkeypatch
) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.managed_agent.mode = "generate_content"

    class FakeStream:
        def __enter__(self):
            return iter(
                [
                    b'data: {"candidates":[{"content":{"parts":[{"text":"hi"}]}}]}\n',
                ]
            )

        def __exit__(self, exc_type, exc, tb):
            return None

    def fake_urlopen(request, timeout):
        return FakeStream()

    monkeypatch.setattr("gemcoder.managed.urlopen", fake_urlopen)
    client = ManagedAgentClient(config, tmp_path, api_key="test-key")
    chunks: list[str] = []

    result = client.run_task("goal: Say hi", on_chunk=chunks.append)

    assert result.summary == "hi"
    assert chunks == ["hi"]
    assert result.diagnostics["status"] == "success"
    assert result.diagnostics["endpoint"] == "models/gemini-flash-latest:streamGenerateContent"


def test_stream_generate_content_records_failure_diagnostics(
    tmp_path: Path, monkeypatch
) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.managed_agent.mode = "generate_content"

    class FakeResponse(BytesIO):
        def close(self):
            pass

    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=FakeResponse(b'{"error":"bad key"}'),
        )

    monkeypatch.setattr("gemcoder.managed.urlopen", fake_urlopen)
    client = ManagedAgentClient(config, tmp_path, api_key="test-key")

    try:
        client.run_task("goal: Say hi", on_chunk=lambda _chunk: None)
    except ManagedAgentError as exc:
        assert exc.diagnostics["status"] == "failed"
        assert exc.diagnostics["http_status"] == 401
        assert exc.diagnostics["error_type"] == "http"
    else:
        raise AssertionError("expected ManagedAgentError")


def test_transport_normalizes_socket_timeout(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr("gemcoder.managed.urlopen", fake_urlopen)

    try:
        _urllib_transport(
            method="POST",
            url="https://example.invalid",
            headers={},
            payload={},
            timeout=3,
        )
    except ManagedAgentError as exc:
        assert "timed out after 3 seconds" in str(exc)
        assert exc.diagnostics["error_type"] == "timeout"
    else:
        raise AssertionError("expected ManagedAgentError")


def test_transport_records_http_status_without_secrets(monkeypatch) -> None:
    class FakeResponse(BytesIO):
        def close(self):
            pass

    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=FakeResponse(b'{"error":"bad key"}'),
        )

    monkeypatch.setattr("gemcoder.managed.urlopen", fake_urlopen)

    try:
        _urllib_transport(
            method="POST",
            url="https://example.invalid",
            headers={"x-goog-api-key": "secret-key"},
            payload={},
            timeout=3,
        )
    except ManagedAgentError as exc:
        assert exc.diagnostics["http_status"] == 401
        assert "secret-key" not in str(exc)
        assert "secret-key" not in repr(exc.diagnostics)
    else:
        raise AssertionError("expected ManagedAgentError")


def test_failure_guidance_is_actionable() -> None:
    assert "GEMINI_API_KEY" in _failure_guidance({"http_status": 401})
    assert "timeout_seconds" in _failure_guidance({"error_type": "timeout"})
    assert "base_agent" in _failure_guidance({"http_status": 404})


def test_harness_records_provider_events_and_run_summary(tmp_path: Path, monkeypatch) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.orchestrator.default_backend = "remote"

    def fake_transport(**kwargs):
        return {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "gemcoder.orchestrator.ManagedAgentClient",
        lambda config, root: ManagedAgentClient(
            config,
            root,
            api_key="test-key",
            transport=fake_transport,
        ),
    )

    runner = HarnessRunner(tmp_path, config)
    result = runner.run("hello")
    events = runner.store.read_events(result.run_id)
    summary = (tmp_path / ".gemcoder" / "runs" / result.run_id / "run-summary.json").read_text()

    assert any(event.type == "provider.request.started" for event in events)
    assert any(event.type == "provider.request.finished" for event in events)
    assert '"status": "success"' in summary
    assert '"patch_present": false' in summary
    assert "test-key" not in summary


def test_generate_content_prompt_strips_skills(tmp_path: Path) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.managed_agent.mode = "generate_content"
    client = ManagedAgentClient(config, tmp_path, api_key="test-key")

    payload = client.build_generate_content_payload(
        "goal: hello\nskills:\n  repo-navigation: call tools\n"
    )
    prompt = payload["contents"][0]["parts"][0]["text"]

    assert "repo-navigation" not in prompt
    assert ".agents/skills/" not in prompt


def test_strip_tool_oriented_sections_removes_skills() -> None:
    packet = _strip_tool_oriented_sections("goal: hello\nskills:\n  safe-patch: tools\n")

    assert "goal: hello" in packet
    assert "skills" not in packet


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

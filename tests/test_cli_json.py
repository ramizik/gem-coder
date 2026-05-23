import json

from typer.testing import CliRunner

from gemcoder.cli.main import app
from gemcoder.config import dump_config, load_config
from gemcoder.templates import scaffold

runner = CliRunner()


def test_doctor_json_is_secret_safe(tmp_path, monkeypatch) -> None:
    scaffold(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")

    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["provider"]["auth_present"] is True
    assert payload["provider"]["mode"] == "generate_content"
    assert "secret-key" not in result.output


def test_verify_json_returns_results(tmp_path, monkeypatch) -> None:
    scaffold(tmp_path)
    config = load_config(tmp_path)
    config.verification.commands = ["echo ok"]
    (tmp_path / "gemcoder.yaml").write_text(dump_config(config))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["verify", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["run_id"] == "manual"
    assert payload["results"][0]["command"] == "echo ok"
    assert payload["results"][0]["returncode"] == 0

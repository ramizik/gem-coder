"""GemCoder command line interface."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from gemcoder.config import CONFIG_FILE, load_config
from gemcoder.events import RunStore
from gemcoder.harness import HarnessRunner
from gemcoder.managed import ManagedAgentClient
from gemcoder.orchestrator import Backend, OrchestratorEvent
from gemcoder.patcher import apply_patch
from gemcoder.templates import scaffold

app = typer.Typer(
    help="GemCoder — chat-style coding agent for Gemini. Run `gemcoder` to launch the TUI.",
    invoke_without_command=True,
    no_args_is_help=False,
)
agent_app = typer.Typer(help="Managed Agent commands.")
harness_app = typer.Typer(help="Harness inspection commands.")
app.add_typer(agent_app, name="agent")
app.add_typer(harness_app, name="harness")
console = Console()


def _print_json(payload: dict[str, object] | list[object]) -> None:
    typer.echo(json.dumps(payload, indent=2) + "\n")


def _doctor_payload(root: Path) -> dict[str, object]:
    config_path = root / CONFIG_FILE
    config = load_config(root)
    checks = [
        {
            "name": "config",
            "status": "ok" if config_path.exists() else "missing",
            "details": str(config_path),
        },
        {
            "name": "instructions",
            "status": "ok" if (root / config.harness.instructions).exists() else "missing",
            "details": config.harness.instructions,
        },
        {
            "name": "skills",
            "status": "ok" if (root / config.harness.skills_dir).exists() else "missing",
            "details": config.harness.skills_dir,
        },
        {
            "name": "gemini_api_key",
            "status": "ok" if os.getenv("GEMINI_API_KEY") else "missing",
            "details": "required for Managed Agents",
        },
        {
            "name": "verification",
            "status": "ok" if config.verification.commands else "not configured",
            "details": ", ".join(config.verification.commands) or "none",
        },
    ]
    return {
        "checks": checks,
        "provider": {
            "name": config.managed_agent.provider,
            "mode": config.managed_agent.mode,
            "model": config.managed_agent.base_agent,
            "api_base": config.managed_agent.api_base,
            "auth_type": config.managed_agent.auth_type,
            "timeout_seconds": config.managed_agent.timeout_seconds,
            "auth_present": bool(os.getenv(config.managed_agent.api_key_env))
            if config.managed_agent.auth_type == "api_key"
            else bool(os.getenv(config.managed_agent.access_token_env)),
        },
        "verification": {"commands": config.verification.commands},
    }


def _load_dotenv(root: Path) -> None:
    """Populate os.environ from .env (KEY=VALUE per line). Does not override existing vars."""
    env_path = root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@app.callback()
def _default(ctx: typer.Context) -> None:
    """Launch the chat TUI when no subcommand is given."""
    _load_dotenv(Path.cwd())
    if ctx.invoked_subcommand is None:
        tui()


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing scaffold files."),
) -> None:
    """Initialize GemCoder in the current repository."""
    written = scaffold(Path.cwd(), force=force)
    if written:
        console.print("[green]Initialized GemCoder files:[/green]")
        for path in written:
            console.print(f"- {path.relative_to(Path.cwd())}")
    else:
        console.print("[yellow]GemCoder files already exist. Pass --force to overwrite.[/yellow]")


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Check local project and Managed Agent readiness."""
    root = Path.cwd()
    payload = _doctor_payload(root)
    if json_output:
        _print_json(payload)
        return

    table = Table(title="GemCoder Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    for check in payload["checks"]:
        table.add_row(str(check["name"]), str(check["status"]), str(check["details"]))
    provider = payload["provider"]
    table.add_row("Provider mode", str(provider["mode"]), str(provider["name"]))
    table.add_row("Model/agent", "configured", str(provider["model"]))
    console.print(table)


@agent_app.command("create")
def agent_create() -> None:
    """Create or configure the project Managed Agent."""
    root = Path.cwd()
    config = load_config(root)
    client = ManagedAgentClient(config, root)
    agent_id = client.create_agent()
    console.print(f"[green]Managed Agent ready:[/green] {agent_id}")


@app.command()
def run(
    task: str = typer.Argument(..., help="Coding task to run."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
    backend: str = typer.Option(
        "",
        "--backend",
        "-b",
        help="local | remote | auto (default = orchestrator.default_backend).",
    ),
    stream: bool = typer.Option(
        True,
        "--stream/--no-stream",
        help="Print token deltas to stdout as they arrive.",
    ),
) -> None:
    """Run a coding task through GemCoder."""
    root = Path.cwd()
    config = load_config(root)
    backend_choice: Backend | None
    try:
        backend_choice = Backend.parse(backend) if backend else None
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    resolved = backend_choice or Backend.parse(config.orchestrator.default_backend)
    auth_env = (
        config.managed_agent.access_token_env
        if config.managed_agent.auth_type == "bearer"
        else config.managed_agent.api_key_env
    )
    if not json_output:
        console.print(
            "[dim]Provider: "
            f"{config.managed_agent.provider} "
            f"mode={config.managed_agent.mode} "
            f"model={config.managed_agent.base_agent} "
            f"backend={resolved.value} "
            f"auth={'present' if os.getenv(auth_env) else 'missing'}[/dim]"
        )

    def on_chunk(delta: str) -> None:
        if stream and not json_output:
            typer.echo(delta, nl=False)

    def on_event(event: OrchestratorEvent) -> None:
        if json_output or not stream:
            return
        if event.kind == "backend.selected":
            console.print(f"[dim]→ backend: {event.backend.value}[/dim]")
        elif event.kind == "tool_call":
            name = event.data.get("name", "tool")
            console.print(f"[cyan]· tool {name}[/cyan]")
        elif event.kind == "thought":
            # thoughts can be noisy; only show first line
            line = (event.text or "").splitlines()[0] if event.text else ""
            if line:
                console.print(f"[magenta]· {line}[/magenta]")
        elif event.kind == "error":
            console.print(f"[red]error: {event.text}[/red]")

    chunk_callback = on_chunk if stream and not json_output else None
    result = HarnessRunner(root, config).run(
        task, on_chunk=chunk_callback, backend=backend_choice, on_event=on_event
    )
    if stream and not json_output:
        typer.echo("")
    diagnostics = result.diagnostics or {}
    artifacts_dir = f".gemcoder/runs/{result.run_id}"
    if json_output:
        _print_json(
            {
                "run_id": result.run_id,
                "summary": result.summary,
                "patch_path": result.patch_path,
                "diagnostics": diagnostics,
                "artifacts_dir": artifacts_dir,
            }
        )
        return

    if diagnostics.get("status") == "failed":
        console.print(
            Panel(
                result.summary + "\n\n" + _failure_guidance(diagnostics),
                title=f"[red]Run {result.run_id} failed[/red]",
            )
        )
    else:
        elapsed = diagnostics.get("elapsed_seconds")
        backend_value = diagnostics.get("backend", "?")
        subtitle = f" · {backend_value}"
        if elapsed is not None:
            subtitle += f" · {elapsed}s"
        console.print(Panel(result.summary, title=f"Run {result.run_id}{subtitle}"))
    console.print(f"Artifacts: {artifacts_dir}")


def _failure_guidance(diagnostics: dict[str, object]) -> str:
    error_type = diagnostics.get("error_type")
    http_status = diagnostics.get("http_status")
    if error_type == "timeout":
        return "Next steps: retry, increase managed_agent.timeout_seconds, or use a smaller task."
    if http_status in {401, 403}:
        return "Next steps: check GEMINI_API_KEY and confirm the key has access to this model/API."
    if http_status == 404:
        return "Next steps: check managed_agent.base_agent and api_base in gemcoder.yaml."
    if error_type == "network":
        return "Next steps: check network access and the managed_agent.api_base URL."
    return "Next steps: inspect managed-result.json and run `gemcoder doctor`."


@app.command()
def graph(
    run_id: str | None = typer.Argument(None, help="Run id. Defaults to latest run."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Show a text graph for a run."""
    store = RunStore(Path.cwd())
    selected = run_id
    if selected is None:
        runs = store.list_runs()
        if not runs:
            raise typer.BadParameter("No runs found.")
        selected = runs[-1]
    events = store.read_events(selected)
    if json_output:
        _print_json({"run_id": selected, "events": [asdict(event) for event in events]})
        return

    console.print(f"[bold]GemCoder run graph: {selected}[/bold]")
    for event in events:
        console.print(f"- {event.timestamp}  [cyan]{event.type}[/cyan] {event.data}")


@app.command()
def apply(
    run_id: str | None = typer.Argument(None, help="Run id. Defaults to latest run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate only, do not write."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip approval prompt."),
) -> None:
    """Apply a run's patch to the working tree via `git apply`."""
    root = Path.cwd()
    config = load_config(root)
    store = RunStore(root)
    selected = run_id
    if selected is None:
        runs = store.list_runs()
        if not runs:
            raise typer.BadParameter("No runs found.")
        selected = runs[-1]
    patch_path = root / ".gemcoder" / "runs" / selected / "patch.diff"
    if not patch_path.exists():
        raise typer.BadParameter(f"No patch.diff for run {selected}.")
    patch_text = patch_path.read_text()
    if not patch_text.strip():
        console.print("[yellow]Patch is empty. Nothing to apply.[/yellow]")
        return

    if config.approvals.apply_patch and not dry_run and not yes:
        if not typer.confirm(f"Apply patch from {selected} to working tree?"):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(code=1)

    store.append(selected, "patch.apply.started", {"dry_run": dry_run})
    result = apply_patch(root, patch_text, dry_run=dry_run)
    event = "patch.apply.checked" if dry_run else "patch.apply.applied"
    if not result.ok:
        event = "patch.apply.failed"
    store.append(
        selected,
        event,
        {"files": result.files, "stderr": result.stderr.strip()[:500]},
    )
    if result.ok:
        verb = "Would apply" if dry_run else "Applied"
        console.print(f"[green]{verb}[/green] {len(result.files)} file(s):")
        for path in result.files:
            console.print(f"  - {path}")
    else:
        console.print(f"[red]git apply failed:[/red]\n{result.stderr}")
        raise typer.Exit(code=1)


@app.command()
def verify(
    run_id: str | None = typer.Argument(None, help="Run id to verify."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Run configured local verification commands."""
    runner = HarnessRunner(Path.cwd())
    selected = run_id or runner.latest_run_id() or "manual"
    results = runner.verify(run_id)
    if json_output:
        _print_json({"run_id": selected, "results": [asdict(result) for result in results]})
        return

    for result in results:
        status = "pass" if result.returncode == 0 else "fail"
        console.print(f"[bold]{result.command}[/bold]: {status}")
    if not results:
        console.print("[yellow]No verification commands configured.[/yellow]")


@harness_app.command("show")
def harness_show() -> None:
    """Show the user-defined harness loaded for this repository."""
    details = HarnessRunner(Path.cwd()).inspect_harness()
    table = Table(title="GemCoder Harness")
    table.add_column("Field")
    table.add_column("Value")
    for key, value in details.items():
        if isinstance(value, list):
            rendered = "\n".join(str(item) for item in value) or "none"
        else:
            rendered = str(value)
        table.add_row(key, rendered)
    console.print(table)


@harness_app.command("build")
def harness_build() -> None:
    """Build the editable harness files into runtime artifacts."""
    result = HarnessRunner(Path.cwd()).build()
    console.print(f"[green]Built harness:[/green] {result.build_id}")
    console.print(f"Build directory: {result.build_dir.relative_to(Path.cwd())}")
    console.print(f"Manifest: {result.manifest_path.relative_to(Path.cwd())}")


@app.command()
def tui() -> None:
    """Launch the Bubble Tea TUI (requires `make tui` to build the Go binary)."""
    import shutil
    candidates = [
        Path(__file__).resolve().parent.parent / "_bin" / "gemcoder-tui",
        Path.cwd() / "src" / "gemcoder" / "_bin" / "gemcoder-tui",
    ]
    on_path = shutil.which("gemcoder-tui")
    if on_path:
        candidates.insert(0, Path(on_path))
    for path in candidates:
        if path.exists() and os.access(path, os.X_OK):
            os.execvp(str(path), [str(path)])
    console.print(
        Panel(
            "Bubble Tea TUI binary not found.\n\n"
            "Build it with:\n"
            "  [bold]brew install go[/bold]   (one-time)\n"
            "  [bold]make tui[/bold]          (from the gemcoder checkout)\n\n"
            "Then re-run [bold]gemcoder tui[/bold].",
            title="GemCoder TUI",
        )
    )


@app.command()
def serve() -> None:
    """Serve GemCoder over JSON-RPC 2.0 on stdio (used by the TUI)."""
    from gemcoder.serve import serve as _serve
    _serve(Path.cwd())


@app.command()
def eval() -> None:  # noqa: A001
    """Run benchmark evaluation placeholder."""
    console.print("[yellow]Evaluation harness placeholder. Benchmarks will be wired next.[/yellow]")


@app.command()
def optimize() -> None:
    """Run harness optimization placeholder."""
    console.print(
        "[yellow]Optimization placeholder. Candidate harness loop will be wired next.[/yellow]"
    )

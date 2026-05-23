"""GemCoder command line interface."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from gemcoder.config import CONFIG_FILE, load_config
from gemcoder.events import RunStore
from gemcoder.harness import HarnessRunner
from gemcoder.managed import ManagedAgentClient, antigravity_sdk_available
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


@app.callback()
def _default(ctx: typer.Context) -> None:
    """Launch the chat TUI when no subcommand is given."""
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
def doctor() -> None:
    """Check local project and Managed Agent readiness."""
    root = Path.cwd()
    config_path = root / CONFIG_FILE
    config = load_config(root)
    table = Table(title="GemCoder Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    table.add_row("Config", "ok" if config_path.exists() else "missing", str(config_path))
    table.add_row(
        "Instructions",
        "ok" if (root / config.harness.instructions).exists() else "missing",
        config.harness.instructions,
    )
    table.add_row(
        "Skills",
        "ok" if (root / config.harness.skills_dir).exists() else "missing",
        config.harness.skills_dir,
    )
    table.add_row(
        "GEMINI_API_KEY",
        "ok" if os.getenv("GEMINI_API_KEY") else "missing",
        "required for Managed Agents",
    )
    table.add_row(
        "Antigravity SDK",
        "ok" if antigravity_sdk_available() else "optional",
        "install with: uv sync --extra antigravity",
    )
    table.add_row(
        "Verification",
        "ok" if config.verification.commands else "not configured",
        ", ".join(config.verification.commands) or "none",
    )
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
def run(task: str = typer.Argument(..., help="Coding task to run.")) -> None:
    """Run a coding task through GemCoder."""
    result = HarnessRunner(Path.cwd()).run(task)
    console.print(Panel(result.summary, title=f"Run {result.run_id}"))
    console.print(f"Artifacts: .gemcoder/runs/{result.run_id}")


@app.command()
def graph(
    run_id: str | None = typer.Argument(None, help="Run id. Defaults to latest run."),
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
def verify(run_id: str | None = typer.Argument(None, help="Run id to verify.")) -> None:
    """Run configured local verification commands."""
    results = HarnessRunner(Path.cwd()).verify(run_id)
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

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
from gemcoder.managed import ManagedAgentClient
from gemcoder.task_packet import build_task_packet
from gemcoder.templates import scaffold
from gemcoder.verify import run_verification

app = typer.Typer(help="Optimisable CLI/TUI coding harness for Gemini Managed Agents.")
agent_app = typer.Typer(help="Managed Agent commands.")
app.add_typer(agent_app, name="agent")
console = Console()


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
        "Verification",
        "ok" if config.verification.commands else "not configured",
        ", ".join(config.verification.commands) or "none",
    )
    console.print(table)


@agent_app.command("create")
def agent_create() -> None:
    """Create or configure the project Managed Agent."""
    config = load_config(Path.cwd())
    client = ManagedAgentClient(config)
    agent_id = client.create_agent()
    console.print(f"[green]Managed Agent ready:[/green] {agent_id}")


@app.command()
def run(task: str = typer.Argument(..., help="Coding task to run.")) -> None:
    """Run a coding task through GemCoder."""
    root = Path.cwd()
    config = load_config(root)
    store = RunStore(root)
    run_id = store.create_run(task)
    store.append(run_id, "task.packet.created")
    packet = build_task_packet(root, task, config)
    store.write_artifact(run_id, "task-packet.yaml", packet)

    client = ManagedAgentClient(config)
    store.append(run_id, "managed.interaction.started", {"provider": config.managed_agent.provider})
    result = client.run_task(packet)
    store.append(run_id, "managed.result.received", {"summary": result.summary})
    store.write_artifact(run_id, "managed-result.json", json.dumps(asdict(result), indent=2) + "\n")

    if result.patch:
        store.write_artifact(run_id, "patch.diff", result.patch)
        store.append(run_id, "patch.received")
    else:
        store.append(run_id, "patch.empty")

    console.print(Panel(result.summary, title=f"Run {run_id}"))
    console.print(f"Artifacts: .gemcoder/runs/{run_id}")


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
def verify(run_id: str | None = typer.Argument(None, help="Run id to verify.")) -> None:
    """Run configured local verification commands."""
    root = Path.cwd()
    config = load_config(root)
    store = RunStore(root)
    selected = run_id
    if selected is None:
        runs = store.list_runs()
        selected = runs[-1] if runs else "manual"
    store.append(selected, "verification.started", {"commands": config.verification.commands})
    results = run_verification(root, config.verification.commands)
    for result in results:
        status = "pass" if result.returncode == 0 else "fail"
        store.append(
            selected,
            "verification.command",
            {"command": result.command, "status": status},
        )
        console.print(f"[bold]{result.command}[/bold]: {status}")
    if results and all(result.returncode == 0 for result in results):
        store.append(selected, "verification.passed")
    elif results:
        store.append(selected, "verification.failed")


@app.command()
def tui() -> None:
    """Launch the GemCoder TUI placeholder."""
    console.print(
        Panel(
            "TUI implementation placeholder.\n\n"
            "MVP layout: timeline, chat/output, patch preview, verification status.",
            title="GemCoder TUI",
        )
    )


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

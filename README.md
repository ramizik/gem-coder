# GemCoder

GemCoder is an optimisable CLI and TUI coding harness for Gemini Managed Agents.

It turns Managed Agents into a repo-aware developer workflow with project
instructions, skills, structured task packets, patch previews, local
verification, run graphs, and harness evaluation.

## Why GemCoder

Gemini Managed Agents provide a powerful cloud execution runtime. Developers
still need a practical coding workflow around that runtime:

- initialize a repo for agentic coding
- define project instructions and reusable skills
- package a coding task with the right files and constraints
- ask for patches instead of prose
- apply and verify changes locally
- inspect what happened after the run
- improve the harness over time with evaluations

GemCoder provides that workflow.

## Core Experience

```bash
gemcoder init
gemcoder doctor
gemcoder agent create
gemcoder run "Fix the failing tests and add a regression test"
gemcoder graph
```

For interactive work:

```bash
gemcoder tui
```

The TUI is the main developer surface. It shows the task, Managed Agent status,
run timeline, patch preview, changed files, and local verification result.

## Development Setup

From a source checkout:

```bash
uv sync --extra dev
uv run gemcoder --help
uv run --extra dev pytest
uv run ruff check .
```

To run the local package from another repository while developing:

```bash
uv run --project /path/to/gemcoder gemcoder init
```

## What GemCoder Does

- Creates a repeatable coding harness for a repository.
- Loads `AGENTS.md` and `.gemcoder/skills/*.md`.
- Builds structured task packets for Managed Agents.
- Streams and stores run events.
- Requests patch-first results from the agent.
- Previews and applies patches locally.
- Runs local verification commands.
- Shows a graph/timeline of the full run.
- Evaluates and optimizes harness behavior over time.

## Project Layout

`gemcoder init` creates:

```text
AGENTS.md
gemcoder.yaml
.gemcoder/
  skills/
    repo-navigation.md
    safe-patch.md
    test-driven-fix.md
  runs/
  sessions/
  evals/
  cache/
```

## Example Config

```yaml
project:
  name: my-project

managed_agent:
  provider: google
  mode: default
  reuse_sessions: true

harness:
  instructions: AGENTS.md
  skills_dir: .gemcoder/skills
  patch_format: unified_diff

verification:
  commands:
    - pytest
  require_pass: true

approvals:
  apply_patch: true
  shell_commands: false

optimization:
  enabled: true
  objective:
    - tests_pass
    - minimal_diff
    - low_latency
```

## Hackathon MVP

The first version focuses on the Managed Agents API:

- CLI commands: `init`, `doctor`, `agent create`, `run`, `graph`, `apply`,
  `verify`
- TUI with prompt input, run timeline, patch preview, and verification status
- Managed Agent integration
- task packet builder
- skill loading
- patch parser and local apply flow
- local verification
- run store and graph
- basic eval command

## Roadmap

After the Managed-Agents-first MVP:

- richer TUI
- web/docs context connectors
- benchmark-driven harness optimization
- local Gemma runtime support
- hybrid local/cloud routing
- advanced connector policies
- multi-agent workflows

## Product Statement

GemCoder is an optimisable CLI/TUI coding harness for Gemini Managed Agents.
It makes Managed Agents useful as a disciplined developer coding workflow.

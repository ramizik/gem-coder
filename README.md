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
- exclude secrets and local-only artifacts from remote context
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
gemcoder harness build
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

Create a local `.env` for the Gemini key. `.env` is ignored by git; keep real
keys out of commits and shell history.

```bash
cp .env.example .env
# edit .env and set GEMINI_API_KEY
uv run gemcoder doctor
uv run gemcoder run "Hello"
```

To run the local package from another repository while developing:

```bash
uv run --project /path/to/gemcoder gemcoder init
```

## What GemCoder Does

- Creates a repeatable coding harness for a repository.
- Loads `AGENTS.md` and `.gemcoder/skills/*.md`.
- Builds editable harness files into `.gemcoder/build/` artifacts.
- Builds structured task packets for Managed Agents.
- Streams and stores run events.
- Requests patch-first results from the agent.
- Previews and applies patches locally.
- Runs local verification commands.
- Shows a graph/timeline of the full run.
- Evaluates and optimizes harness behavior over time.

Read [Defining A GemCoder Harness](docs/harness.md) for the user-owned harness
format.

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
  mode: generate_content
  base_agent: gemini-flash-latest
  api_base: https://generativelanguage.googleapis.com/v1beta
  api_revision: "2026-05-20"
  reuse_sessions: true
  tools: []

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

## Managed Agent API Flow

GemCoder supports two Managed Agent modes:

- `inline`: `gemcoder run` calls `POST /v1beta/interactions` with the current
  harness mounted inline. This is the fastest hackathon loop.
- `persisted`: `gemcoder agent create` calls `POST /v1beta/agents`, then
  `gemcoder run` invokes the configured `managed_agent.agent_id`.

Set `GEMINI_API_KEY` before calling the remote API, either in your shell or in a
local `.env` file:

```bash
export GEMINI_API_KEY="..."
gemcoder harness build
gemcoder run "Fix the failing tests"
```

For each run, GemCoder stores `managed-request.json`, `managed-response.json`,
`task-packet.yaml`, and the event graph under `.gemcoder/runs/<run-id>/`.

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

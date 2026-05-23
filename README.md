# GemCoder

GemCoder is an optimisable CLI and TUI coding harness for Gemini Managed Agents.

It turns Managed Agents into a repo-aware developer workflow with project
instructions, skills, structured task packets, patch previews, local
verification, run graphs, and harness evaluation.

**Two backends, one harness.** GemCoder uses the Google agent stack at the right
layer for each task: the **Antigravity SDK** runs the harness **locally** (the
agentic loop on your machine) for lighter tasks, and **ADK 2.0 + Managed Agents**
run it in the **cloud** for bigger ones — two engines, one shared harness
definition. GemCoder's **orchestrator** routes each task (small/quick → local,
big → cloud), or pin it with `gemcoder run --backend local|remote|auto` (default
from `orchestrator.default_backend`). See [`docs/orchestrator.md`](docs/orchestrator.md)
and [`docs/platform-decision.md`](docs/platform-decision.md).

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

## 1-Minute Demo

The shortest path to the "wow": type one plain sentence, hand off the keyboard,
and watch a verified fix land. No heavy setup, no dozen tools — the value is the
hands-off loop, not the toolbox.

```bash
gemcoder tui
# then type: Fix the failing test and add a regression test.
```

Type once → it reads the repo, writes the fix, you approve, it verifies locally,
tests go green. See [`docs/DEMO.md`](docs/DEMO.md) for the full 60-second
run-of-show and talk track.

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
  description: GemCoder managed coding agent
  api_base: https://generativelanguage.googleapis.com/v1beta
  api_revision: "2026-05-20"
  reuse_sessions: true
  auth_type: api_key
  api_key_env: GEMINI_API_KEY
  access_token_env: GOOGLE_OAUTH_ACCESS_TOKEN
  tools: []
  stream: true
  background: true
  store: true
  network_allowlist: []

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

## Google Managed Agents Flow

GemCoder supports both the lightweight Gemini `generateContent` path and the
Google Managed Agents `interactions`/`agents` path.

- `generate_content`: calls Gemini `models/<model>:generateContent` with inline
  repository context. This is the easiest local smoke-test path.
- `managed_agent` or `inline`: calls Managed Agents `POST /interactions` with
  `stream`, `background`, `store`, structured user input, and the current
  `AGENTS.md`, skills, and repository context mounted into a remote sandbox.
- `persisted`: `gemcoder agent create` calls `POST /agents` with the same remote
  sandbox configuration, then `gemcoder run` invokes the configured
  `managed_agent.agent_id`.

Set `GEMINI_API_KEY` before calling the remote API, either in your shell or in a
local `.env` file:

```bash
export GEMINI_API_KEY="..."
gemcoder harness build
gemcoder run "Fix the failing tests"
```

For Gemini Enterprise Agent Platform / Vertex AI Managed Agents, use the Agent
Platform endpoint and bearer auth:

```yaml
managed_agent:
  mode: managed_agent
  base_agent: antigravity-preview-05-2026
  api_base: https://aiplatform.googleapis.com/v1beta1/projects/PROJECT_ID/locations/global
  auth_type: bearer
  access_token_env: GOOGLE_OAUTH_ACCESS_TOKEN
  network_allowlist:
    - pypi.org
    - files.pythonhosted.org
```

Then provide a short-lived access token:

```bash
export GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"
gemcoder run "Fix the failing tests"
```

Leave `network_allowlist` empty unless the managed sandbox needs internet access
for package downloads or external APIs.

For each run, GemCoder stores `managed-request.json`, `managed-response.json`,
`managed-result.json`, `run-summary.json`, `task-packet.yaml`, and the event
graph under `.gemcoder/runs/<run-id>/`.

### Troubleshooting runs

Start with the local readiness check:

```bash
uv run gemcoder doctor
```

Then run a small live smoke test:

```bash
uv run gemcoder run "Hello"
```

A healthy run prints the configured provider mode/model, returns a short
assistant response, and writes artifacts under `.gemcoder/runs/<run-id>/`.
Inspect the timeline with:

```bash
uv run gemcoder graph <run-id>
```

If a run fails, GemCoder records safe diagnostics such as provider mode, model,
endpoint, elapsed seconds, HTTP status, and error type in `run-summary.json`.
It does not store or print `GEMINI_API_KEY`. Common fixes:

- `401` or `403`: rotate/check `GEMINI_API_KEY` or
  `GOOGLE_OAUTH_ACCESS_TOKEN`, and confirm model/API access.
- `404`: check `managed_agent.base_agent` and `managed_agent.api_base`.
- `timeout`: retry, reduce the task/context size, or increase
  `managed_agent.timeout_seconds`.
- `network`: check connectivity and the configured API base URL.

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

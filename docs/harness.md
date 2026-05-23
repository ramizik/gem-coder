# Defining A GemCoder Harness

A GemCoder harness is user-owned repository configuration. It tells GemCoder how
to package a task, what instructions and skills to use, what context can be
included, how changes should be returned, and how success is verified.

The core harness files are:

```text
gemcoder.yaml
AGENTS.md
.gemcoder/skills/*.md
```

## Mental Model

```text
gemcoder.yaml = policy and wiring
AGENTS.md = global project instructions
skills/*.md = reusable task workflows
runs/ = evidence from previous executions
evals/ = benchmark tasks for optimization
```

## `gemcoder.yaml`

Example:

```yaml
project:
  name: checkout-service

managed_agent:
  provider: google
  mode: inline
  base_agent: antigravity-preview-05-2026
  api_base: https://generativelanguage.googleapis.com/v1beta
  api_revision: "2026-05-20"
  reuse_sessions: true
  # Optional. Leave empty to use the Antigravity defaults.
  tools: []

harness:
  instructions: AGENTS.md
  skills_dir: .gemcoder/skills
  patch_format: unified_diff

context:
  include:
    - src/**/*.py
    - tests/**/*.py
    - pyproject.toml
  exclude:
    - .venv/**
    - node_modules/**
    - secrets/**
  max_files: 40

verification:
  commands:
    - uv run pytest
    - uv run ruff check .
  require_pass: true

approvals:
  apply_patch: true
  shell_commands: true

optimization:
  enabled: true
  objective:
    - tests_pass
    - minimal_diff
    - low_latency
```

## `AGENTS.md`

Example:

```md
# AGENTS.md

You are GemCoder working on this repository.

Rules:
- Read relevant files before editing.
- Make minimal changes.
- Add tests when fixing bugs.
- Run verification before final response.
- Return a unified diff.
- Do not touch secrets, generated files, or unrelated modules unless asked.
```

## Skills

Skills are reusable workflows stored in `.gemcoder/skills`.

Example:

```text
.gemcoder/skills/test-driven-fix.md
.gemcoder/skills/frontend-bug.md
.gemcoder/skills/api-change.md
.gemcoder/skills/security-review.md
```

Example skill:

```md
# test-driven-fix

Use this when a test is failing.

Steps:
1. Inspect the failing test output.
2. Identify the smallest implementation area.
3. Patch only relevant files.
4. Add or update a regression test.
5. Run the configured verification command.
6. Return a summary and unified diff.
```

## Inspecting The Harness

```bash
gemcoder harness show
```

This shows the loaded instructions, skills, context files, verification commands,
and patch format for the current repository.

## Building The Harness

Before running or deploying a harness, build it into a stable runtime artifact:

```bash
gemcoder harness build
```

This writes:

```text
.gemcoder/build/
  current.json
  hbuild_<timestamp>/
    manifest.json
    harness.json
    task-template.yaml
    managed-agent-instructions.md
    skills-bundle.md
    google-sources.json
```

The build step gives GemCoder a reproducible artifact for local runs, future
cloud deployment, evaluation, and optimization.

## Running The Harness

```bash
gemcoder harness build
gemcoder run "Fix the failing tests and add regression coverage"
gemcoder graph
gemcoder verify
```

Every run records the harness definition, task packet, managed-agent result,
patch artifacts, and verification events under `.gemcoder/runs/<run-id>/`.

## Remote Managed Agent Mapping

When `GEMINI_API_KEY` is set, GemCoder connects to the Gemini Managed Agents API.
The harness build is mounted into the remote environment as inline sources:

```text
AGENTS.md                         -> .agents/AGENTS.md
.gemcoder/skills/safe-patch.md    -> .agents/skills/safe-patch/SKILL.md
selected repository files         -> /workspace/repo/<path>
```

Secret-like files such as `.env`, private keys, token files, credential files,
and common local caches are blocked from context mounting even if an include
pattern matches them.

In `inline` mode, each `gemcoder run` sends these sources directly to the
Interactions API. In `persisted` mode, `gemcoder agent create` saves the sources
as a reusable Managed Agent configuration and future runs invoke
`managed_agent.agent_id`.

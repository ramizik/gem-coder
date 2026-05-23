# GemCoder PRD

## 1. Product Summary

GemCoder is an optimisable CLI and TUI coding harness for Gemini Managed Agents.

It gives developers a repo-aware workflow for using Managed Agents as practical
coding agents. GemCoder packages project context, instructions, skills, and
verification rules into repeatable coding runs. It sends tasks to Managed
Agents, receives patches, applies them locally, verifies the result, and shows
the full run in an observable CLI/TUI experience.

Short positioning:

> GemCoder is an optimisable CLI/TUI coding harness for Gemini Managed Agents.

Long positioning:

> GemCoder turns Managed Agents into a repo-aware developer workflow with
> skills, task packets, patch previews, local verification, event graphs, and
> optimisable harnesses.

## 2. Product Thesis

Managed Agents provide the cloud execution engine. GemCoder provides the
developer coding workflow.

## 3. Problem

Managed Agents are powerful, but developers still need a disciplined workflow
for real repository work:

- project initialization
- project instructions
- reusable coding skills
- structured task packaging
- patch-first outputs
- patch preview and approval
- local verification
- observable runs
- repeatable evaluation
- harness optimization

Without GemCoder, developers must manually shape prompts, copy context, inspect
responses, apply patches, and track results.

## 4. Target Users

### Hackathon Builders

Builders with Gemini API access who want to quickly use Managed Agents on real
repositories.

### Application Developers

Developers who want an agent to fix bugs, add tests, implement small features,
and explain changes while preserving local control.

### Agent Developers

Developers building coding-agent workflows who need a configurable and
inspectable harness.

### Teams Evaluating Agentic Coding

Teams that want auditable runs, local verification, and repeatable evaluation
instead of one-off prompt experiments.

### Future Local-Model Users

Developers who want local Gemma workflows with cloud escalation. This is a
post-MVP roadmap user segment.

## 5. Core User Experience

A developer works inside an existing repository:

```bash
cd my-project
gemcoder init
gemcoder doctor
gemcoder tui
```

Inside the TUI, they type:

```text
Fix the failing tests and add a regression test.
```

GemCoder:

1. Builds a structured task packet.
2. Starts or reuses a Managed Agent.
3. Sends repo context, instructions, and skills.
4. Streams progress into the TUI.
5. Receives a patch and test summary.
6. Shows patch preview.
7. Applies patch with approval.
8. Runs local verification.
9. Shows final result and graph.

## 6. CLI Experience

The CLI supports automation, quick runs, and demos.

```bash
gemcoder init
gemcoder doctor
gemcoder agent create
gemcoder run "add input validation and tests"
gemcoder graph
gemcoder apply <run-id>
gemcoder verify <run-id>
gemcoder eval
gemcoder optimize
```

### MVP CLI Commands

| Command | Purpose |
| --- | --- |
| `gemcoder init` | Create GemCoder project files. |
| `gemcoder doctor` | Check API key, repo, config, test commands, and local environment. |
| `gemcoder agent create` | Create or configure a Managed Agent for the project. |
| `gemcoder run "task"` | Run a coding task. |
| `gemcoder graph [run-id]` | Show the run timeline. |
| `gemcoder apply <run-id>` | Apply a returned patch. |
| `gemcoder verify <run-id>` | Run local verification commands. |
| `gemcoder eval` | Run benchmark tasks against the current harness. |

## 7. TUI Experience

The TUI is the main developer surface.

```bash
gemcoder tui
```

### TUI Layout

```text
Left:   run timeline / graph
Center: chat and agent output
Right:  changed files / patch preview / test status
Bottom: prompt input and commands
```

### TUI Commands

```text
/run Fix the bug
/graph
/patch
/apply
/verify
/agent status
/skills
/eval
/optimize
```

### TUI Must Show

- active Managed Agent
- current session
- task status
- files included
- patch returned
- approval prompts
- verification result
- event timeline
- errors and retry state

## 8. Core Concepts

### Harness

The harness is the repeatable contract for how GemCoder runs coding tasks.

It defines:

- instructions
- skills
- allowed files
- test commands
- patch format
- verification policy
- approval policy
- optimization targets

### Managed Agent Runtime

The Managed Agent is the remote execution backend.

GemCoder uses it to:

- run sandboxed coding tasks
- inspect files
- execute commands
- produce patches
- verify changes in a cloud environment

### Task Packet

Each run sends a structured task packet, not a vague prompt.

```yaml
goal: "Fix failing tests and add regression coverage"
repo:
  language: python
  test_command: pytest
instructions:
  - make the smallest safe patch
  - run tests before final response
  - return a unified diff
skills:
  - repo-navigation
  - test-driven-fix
  - safe-patch
return_contract:
  patch: unified_diff
  changed_files: list
  commands_run: list
  test_result: summary
  final_summary: short
```

### Optimisable Harness

GemCoder must be optimisable from the start.

Every run stores:

```text
task
task packet
instructions used
skills used
agent response
patch
verification result
timeline
score
cost/latency if available
```

This enables:

```bash
gemcoder eval
gemcoder optimize
```

## 9. Managed Agent Integration

GemCoder integrates with Managed Agents as a first-class runtime.

Required integration capabilities:

- create or reuse a custom Managed Agent
- compile project instructions into agent instructions
- compile skills into agent skills
- create session/environment per run
- send structured task packet
- stream interaction output
- request patch-first result
- normalize managed events into GemCoder events
- apply and verify returned changes locally

### Managed Run Flow

```text
User task
  -> load config
  -> load AGENTS.md
  -> load skills
  -> inspect repo
  -> build task packet
  -> start managed session
  -> run managed interaction
  -> receive patch/result
  -> preview patch
  -> apply patch after approval
  -> run local verification
  -> store score and graph
```

## 10. Project Files

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

### Config Example

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

## 11. Events And Graph

Every run records events:

```text
run.started
doctor.checked
agent.created
task.packet.created
managed.session.started
managed.interaction.started
managed.output.delta
patch.received
patch.previewed
patch.approved
patch.applied
verification.started
verification.passed
run.completed
```

`gemcoder graph` and the TUI graph view show:

```text
Task
 ├─ Context packaged
 ├─ Managed Agent session
 │   ├─ Read files
 │   ├─ Ran tests
 │   └─ Produced patch
 ├─ Patch preview
 ├─ Local apply
 └─ Verification passed
```

## 12. Connectors And External Context

GemCoder supports controlled context connectors.

MVP connectors:

- repository files
- local test output
- optional web/docs fetch

Later connectors:

- GitHub issues and pull requests
- MCP tools
- remote agents
- cloud docs/search
- ticketing systems

Connector rules:

- read-only by default
- citations for web/docs context
- approval for writes
- all connector use appears in the event graph

## 13. Evaluation

`gemcoder eval` runs benchmark tasks against the current harness.

Example:

```bash
gemcoder eval benchmarks/basic-python
```

Scores:

- task completed
- tests passed
- patch applied cleanly
- changed files are minimal
- no forbidden files changed
- no destructive commands
- time to result
- manual approval count

## 14. Optimization

`gemcoder optimize` proposes and tests harness improvements.

Optimisable artifacts:

```text
AGENTS.md
gemcoder.yaml
.gemcoder/skills/*.md
verification rules
task packet template
routing policy
return contract
```

Example:

```bash
gemcoder optimize --benchmark benchmarks/basic-python --budget 5
```

It should produce:

```text
candidate harness versions
score comparison
best candidate
diff of harness changes
approval before adopting
```

## 15. MVP Scope

### Must Have

- CLI: `init`, `doctor`, `agent create`, `run`, `graph`, `apply`, `verify`
- TUI: prompt input, timeline, patch preview, verification status
- Managed Agent API integration
- task packet builder
- skill loading
- patch parser/apply flow
- local verification
- run store
- basic eval command

### Should Have

- session reuse
- web/docs fetch
- optimization command stub
- benchmark demo task

### Later

- local Gemma runtime
- hybrid local/cloud routing
- advanced connector system
- richer optimizer
- multi-agent workflows
- hosted dashboard

## 16. Hackathon Demo (1-Minute Run-of-Show)

The demo's job is **demo effect + felt value in 60 seconds**, not a feature tour.
We show one relatable, dev-focused scenario and let the autonomous loop be the
"wow": a human types one plain sentence, walks away, and a verified fix lands.
**Do not** demo eval, optimize, connectors, agent-create, or the long command
list — they dilute the magic moment. Keep tooling invisible; show the outcome.

**Stage before you present** (off-camera, so the demo is pre-warmed and never
stalls on setup):

```bash
export GEMINI_API_KEY=...
gemcoder init        # repo already has a small, relatable failing test
gemcoder tui         # land here, prompt empty, ready to type
```

Pick a repo a regular person recognizes — e.g. a tiny budget/todo CLI with one
obviously broken behavior and a red test. The value reads instantly: "my little
app was broken; one sentence fixed it."

**The 60 seconds (talk track lives in `docs/DEMO.md`):**

| ~Time | On screen | What you say |
| --- | --- | --- |
| 0:00 | Type one sentence in the TUI: *"Fix the failing test and add a regression test."* | "I just tell it what I want — in plain English." |
| 0:05 | Hit enter, hands off the keyboard | "Now I do nothing. It runs the whole loop itself." |
| 0:10 | Run timeline streams; patch preview builds | "It reads the repo, finds the bug, writes the fix — I see every step." |
| 0:30 | Approve the patch (one keypress) | "I stay in control — nothing touches my code until I say so." |
| 0:40 | Local verification runs, tests go green | "It applied the fix and verified it locally. Green." |
| 0:50 | Graph snaps to the full run | "One sentence in, a verified fix out. That's GemCoder." |

The two beats that must land: **(1) hands-off autonomy** (type once, walk away)
and **(2) trustworthy control** (you approve, it verifies). Everything else is
cut for time.

## 17. Success Criteria

Hackathon success:

- developer can run GemCoder in a repo
- TUI can submit a coding task
- Managed Agent returns a patch
- patch applies locally
- verification runs
- graph is visible
- run artifacts are saved
- harness can be evaluated

Post-MVP success:

- repeated benchmark tasks improve over time
- lower manual intervention
- fewer invalid patches
- better task completion rate
- measurable reduction in time to verified fix
- harness candidates can be compared and adopted safely

## 18. Platform & Backends (updated 2026-05-23)

GemCoder runs the **same** harness definition on two backends, chosen by task size
(decision record: `docs/platform-decision.md` — "use both"). An **orchestrator**
(`src/gemcoder/orchestrator.py`, `docs/orchestrator.md`) picks the backend per run —
`auto` by heuristic (context files/bytes + task length, + whether the local SDK is
installed), or pinned via `gemcoder run --backend local|remote|auto` /
`orchestrator.default_backend`. Every run emits a unified live event stream
(`backend.selected`, `token`, `tool_call`, `diagnostic`, `complete`) to the CLI, the
TUI (with `/backend` + a live step trail), and `.gemcoder/runs/<id>/events.jsonl`.

- **Local backend — Antigravity SDK.** For lighter tasks, the harness runs on the
  developer's machine via the `google-antigravity` SDK's local runtime
  (`Agent` + `LocalAgentConfig`): the SDK owns the agentic loop, multi-turn state,
  history, thought preservation, and built-in file/shell tools; GemCoder adds
  custom tools and governance (hooks/policies). The model is Gemini via
  `GEMINI_API_KEY` ("local" = the loop runs locally, not an on-device model).
- **Cloud backend — ADK 2.0 + Managed Agents.** For bigger tasks, the harness is
  built as an **ADK 2.0** agent and deployed to **Managed Agents** (Interactions
  API) — an isolated cloud Linux sandbox. What works end-to-end today (commit
  `c9fcc0e`) is the *direct-HTTP* Managed Agents path in `src/gemcoder/managed.py`;
  rebuilding it on ADK 2.0 is **Phase 1** in `docs/platform-decision.md`. **A2A** is
  the roadmap transport for subagents.

The two backends are **different engines** (Antigravity SDK local, ADK 2.0 cloud);
the **same harness definition** runs on both ⇒ local↔cloud parity at the definition
layer. The patch is the interchange contract and `apply`/`verify` stay the gated
local steps regardless of backend.

# Orchestrator

GemCoder runs each task on **one** of two backends, picked by the orchestrator:

| Backend | What it is | When it's used |
|---|---|---|
| `local`  | [`google-antigravity` SDK][sdk] running the same harness on this machine. | Small tasks, fast iteration, when the dev wants to stay local. |
| `remote` | Managed Agents (Interactions API) — Antigravity harness in a Google-hosted Linux sandbox. | Big tasks, multi-file work, anything needing the sandbox. |
| `auto`   | Heuristic — counts context files/bytes and task length, plus checks whether the local SDK is installed. | Default. |

[sdk]: https://github.com/google-antigravity/antigravity-sdk-python

## Pick a backend

```bash
gemcoder run "fix the failing test" --backend local
gemcoder run "refactor the auth flow" --backend remote
gemcoder run "rename a variable" --backend auto      # = config default
```

Default comes from `gemcoder.yaml`:

```yaml
orchestrator:
  default_backend: auto         # local | remote | auto
  max_files_local: 20           # >  this → remote
  max_bytes_local: 200000       # >  this → remote
  max_task_chars_local: 4000    # >  this → remote
  local_capabilities: read_only # read_only | write
```

`auto` falls back to `remote` if `google-antigravity` is not installed.

## Install the local backend

```bash
uv sync --extra local
```

## Real-time output

Both backends stream into the same unified `OrchestratorEvent` stream:

| Kind | Meaning |
|---|---|
| `backend.selected` | Routing decision finalized. |
| `token`            | Text delta from the model. |
| `thought`          | Reasoning delta (local only). |
| `tool_call`        | Agent invoked a tool (local only). |
| `diagnostic`       | Provider metadata (latency, status, …). |
| `error`            | Backend raised. |
| `complete`         | Final summary/patch ready. |

The events land in three places:

- **stdout** (CLI) — `gemcoder run` prints token deltas inline and tags each
  non-token event (`→ backend: remote`, `· tool view_file`, …).
- **JSON-RPC** (`gemcoder serve`) — every event becomes a `run.event`
  notification; chunks also fire as `run.chunk` for backward compat. The
  Bubble Tea TUI reads both.
- **Event log** (`.gemcoder/runs/<run-id>/events.jsonl`) — every event is
  persisted as `orchestrator.<kind>`.

## Adding a new backend

1. Implement a `*Client` class with the same `run_task(packet, on_event)` →
   `ManagedAgentResult` contract as `LocalAgentClient`/`ManagedAgentClient`.
2. Extend `Backend` and the `Orchestrator._run_*` dispatch.
3. Add routing inputs to `OrchestratorConfig` if the auto heuristic needs them.
4. Cover the new path in `tests/test_orchestrator.py`.

## Related docs

- `docs/platform-decision.md` — why both backends exist (the "use both" decision).
- `docs/PRD.md` §18 — product-level framing of local vs cloud parity.

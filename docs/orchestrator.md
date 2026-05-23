# Orchestrator

GemCoder runs each task on **one** of two backends, picked by the orchestrator:

| Backend | What it is | When it's used |
|---|---|---|
| `local`  | [`google-antigravity` SDK][sdk] running the same harness on this machine. | Small tasks, fast iteration, when the dev wants to stay local. |
| `remote` | Managed Agents (Interactions API) — Antigravity harness in a Google-hosted Linux sandbox. | Big tasks, multi-file work, anything needing the sandbox. |
| `auto`   | Heuristic — counts context files/bytes and task length, plus checks whether the local SDK is installed. | Default. |
| `both`   | Fans local + remote in parallel threads. First non-error result wins; both are stored as artifacts. | Comparing backends, picking the faster one per task, evaluation. |

[sdk]: https://github.com/google-antigravity/antigravity-sdk-python

## Pick a backend

```bash
gemcoder run "fix the failing test" --backend local
gemcoder run "refactor the auth flow" --backend remote
gemcoder run "rename a variable" --backend auto      # = config default
gemcoder run "small refactor" --backend both         # parallel, picks winner
```

## Verify your credentials are wired (`gemcoder smoke`)

```bash
gemcoder smoke "Say hello in five words."             # remote, fastest path
gemcoder smoke "ping" --backend local                 # local SDK
gemcoder smoke "ping" --backend both                  # both, side-by-side
```

`smoke` bypasses the task-packet flow — it sends `prompt` directly so latency
reflects the raw round-trip floor of each backend. Use it after `gemcoder init`
to confirm `GEMINI_API_KEY` works and the API is reachable.

## Parallel mode (`--backend both`)

Both backends run concurrently in worker threads. Token streams from each are
suppressed in `stdout` (interleaved deltas would be unreadable) but every event
still lands in the event log + `run.event` notifications, tagged with the
originating backend. After both finish, the orchestrator picks a winner (first
non-error result; ties broken by completion order). Artifacts:

```text
.gemcoder/runs/<run-id>/
  managed-result-local.json      # full local result
  managed-result-remote.json     # full remote result
  patch-local.diff               # if local produced a patch
  patch-remote.diff              # if remote produced a patch
  patch.diff                     # = winner's patch (used by `gemcoder apply`)
```

Each backend also emits a `parallel.result` event with `is_winner: true|false`
so the TUI can render a side-by-side comparison.

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
| `backend.selected`   | Routing decision finalized. |
| `token`              | Text delta from the model. |
| `thought`            | Reasoning delta (local only). |
| `tool_call`          | Agent invoked a tool (local only). |
| `diagnostic`         | Provider metadata (latency, status, …). |
| `error`              | Backend raised. |
| `complete`           | Final summary/patch ready. |
| `parallel.complete`  | Both backends finished (BOTH mode); `data.winner` set. |
| `parallel.result`    | Per-backend summary in BOTH mode; `data.is_winner` set. |

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

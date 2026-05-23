# TUI

GemCoder ships with a Bubble Tea TUI for interactive sessions. It is the default
front end when no subcommand is given.

## Launch

```bash
gemcoder tui     # explicit
gemcoder         # same — TUI is the default
```

The TUI spawns `gemcoder serve` as a subprocess and talks to it over JSON-RPC on
stdio. All model calls, tool invocations, and patch generation happen in the
server process; the TUI is purely a render + input loop.

## Layout

- **Header** — model id, repo root, current backend (`local` / `remote` / `auto` / `both`).
- **Viewport** — scrolling chat. Assistant messages are rendered as markdown.
  Diffs are syntax-highlighted. Orchestrator events appear above the in-flight
  message as a dim italic step trail.
- **Prompt input** — single- or multi-line input at the bottom of the viewport.
- **Status bar** — bottom row: connection state, in-flight indicator, last
  command result, key hints.

## Slash commands

| Command | What it does |
|---|---|
| `/init [force]` | Scaffold `.gemcoder/` in the current repo. `force` overwrites. |
| `/apply` | Apply the last patch produced by the agent. |
| `/patch` | Preview the last patch without applying it. |
| `/verify` | Run the configured verification command. |
| `/runs` | List recent runs from `.gemcoder/runs/`. |
| `/show <run-id>` | Load a previous run into the viewport. |
| `/reset` | Clear conversation history for this session. |
| `/shell <cmd>` | Run a local shell command. `!<cmd>` is shorthand. |
| `/backend [local\|remote\|auto\|both]` | Show or set the backend for new runs. |
| `/help` | Show the in-TUI help panel. |
| `/quit` | Exit the TUI. |

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl+A` | Apply last patch |
| `Ctrl+P` | Preview last patch |
| `Ctrl+E` | Run verification |
| `Ctrl+B` | Cycle backend: `auto` → `local` → `remote` → `both` → `auto` |
| `Ctrl+R` | Reset session |
| `Ctrl+L` | Clear screen |
| `Ctrl+H` | Help |
| `Ctrl+C` / `Ctrl+D` | Quit |

## Step trail

The TUI subscribes to `run.event` JSON-RPC notifications from `serve.py` and
renders each orchestrator event as a dim italic line above the in-flight agent
message. Event kinds: `backend.selected`, `thought`, `tool_call`, `diagnostic`,
`parallel.complete`, `error`, `complete`. Token deltas arrive over `run.chunk`
and stream inline into the message body.

## Backends in the TUI

Pick a backend per run with `/backend` or cycle through with `Ctrl+B`. With
`both`, the orchestrator runs `local` and `remote` in parallel; the TUI shows
interleaved step events tagged with the originating backend. The chat message
itself stays single — only the winner's summary is rendered — but both patches
are stored as artifacts. See `docs/orchestrator.md` for the selection rules.

## Logging

The server's stderr is teed to `.gemcoder/tui.log` so the render loop stays
clean. Tail that file when debugging RPC or backend issues.

## See also

- [`docs/orchestrator.md`](./orchestrator.md) — backend selection, parallel runs, artifacts.
- [`docs/PRD.md`](./PRD.md) — product scope and goals.

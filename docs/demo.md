# 60-Second Demo

Two scripts. Pick one. Both assume `GEMINI_API_KEY` is set.

## Setup (one-time, outside the 60 seconds)

```bash
git clone https://github.com/ramizik/gem-coder && cd gem-coder
uv sync --extra dev --extra local
make tui
export GEMINI_API_KEY=...
```

`--extra local` installs the Antigravity SDK so the orchestrator can route
locally too. Skip it to demo remote-only.

---

## Script A — CLI, parallel dispatch (the headline feature)

Shows the orchestrator running **local + remote at the same time** and picking
a winner. This is the demo if you only have one shot.

```bash
# 0:00 — fresh repo with one obviously broken function
mkdir /tmp/demo && cd /tmp/demo
cat > broken.py <<'PY'
def add(a, b):
    return a - b   # bug
PY
cat > test_broken.py <<'PY'
from broken import add
def test_add(): assert add(2, 3) == 5
PY
uv run --project ~/path/to/gem-coder gemcoder init

# 0:10 — prove the API is wired
uv run --project ~/path/to/gem-coder gemcoder smoke "Say hi in 4 words."

# 0:20 — the headline shot: race local vs remote
uv run --project ~/path/to/gem-coder gemcoder run \
  "fix the failing test in broken.py" --backend both

# 0:45 — apply the winner's patch, run the test
uv run --project ~/path/to/gem-coder gemcoder apply --yes
uv run pytest -q
```

What the audience sees:

| Time | On screen |
|---|---|
| 0:10 | `gemcoder smoke` → two panels: `local · ok · 0.8s`, `remote · ok · 1.2s` |
| 0:20 | live token stream, then **two side-by-side panels** with a ★ on the winner |
| 0:45 | `Applied 1 file(s): broken.py` |
| 0:55 | `1 passed in 0.03s` |

---

## Script B — TUI, full keyboard flow

Shows the chat TUI + the new shortcuts. Same broken repo as Script A.

```bash
cd /tmp/demo
uv run --project ~/path/to/gem-coder gemcoder        # TUI is the default
```

Then, inside the TUI:

| Time | Keys | What happens |
|---|---|---|
| 0:00 | type: `fix the failing test in broken.py` `<Enter>` | tokens stream into the chat; step trail shows `backend.selected [auto]`, `tool_call`, `complete` |
| 0:30 | `Ctrl+P` | the unified diff renders inline with syntax highlighting |
| 0:40 | `Ctrl+A` | patch applied; status bar updates to show the apply event |
| 0:50 | `Ctrl+E` | verification runs; pass/fail per command appears in the chat |
| 0:58 | `Ctrl+B` | cycles `auto → local → remote → both → auto` for the next task |

Status bar at the bottom shows project · model · backend · run id · last event the whole time.

---

## Script C — 30 seconds, no setup

If you don't have a broken repo handy:

```bash
cd ~/path/to/gem-coder
uv run gemcoder smoke "Reply with only the number 42." --backend both
```

Both backends ping live, you see latency and the first ~240 chars per backend.
That's the smallest demo that still proves the orchestrator is real.

---

## Recording

```bash
# asciinema
asciinema rec gemcoder-demo.cast -c "bash demo.sh"

# vhs (gif)
vhs demo.tape
```

A minimal `demo.tape`:

```
Output gemcoder-demo.gif
Set FontSize 14
Set Width 1200
Set Height 700
Type "gemcoder run 'fix the failing test' --backend both"
Enter
Sleep 30s
```

---

## What to call out while demoing

1. **One harness, two runtimes.** Same task packet, same skills, same patch
   format — only the runtime differs. Local SDK on your machine, Managed
   Agents in Google's sandbox.
2. **`--backend both` is real parallelism.** Two threads, two providers, one
   winner. Both patches are kept as artifacts under `.gemcoder/runs/<id>/`.
3. **Patch-first contract.** The agent always returns a unified diff. You
   preview it (`Ctrl+P`), then apply it (`Ctrl+A`). Nothing touches your
   working tree without your approval.
4. **Real-time event stream.** `backend.selected → tool_call → complete`
   shows up live in the CLI step lines, in the TUI step trail, and in the
   event log at `.gemcoder/runs/<id>/events.jsonl` — same stream, three
   sinks.

## Related

- `docs/orchestrator.md` — backends, routing, parallel mode
- `docs/tui.md` — TUI reference (commands + shortcuts)
- `docs/platform-decision.md` — why both backends exist
- `docs/PRD.md` — product framing

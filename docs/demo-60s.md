# GemCoder · 60-Second Demo Storyboard

**Theme:** "Two Gemini backends. One harness. Race them."

**Format:** Terminal screencast, 60s flat. One presenter, no cuts inside scenes.
**Resolution:** 1920×1080, 16pt monospace, dark terminal, ≥80 cols.

## Pre-flight checklist

- [ ] `GEMINI_API_KEY` exported in the recording shell.
- [ ] Working dir is a clean GemCoder-initialized repo (`gemcoder init` already run).
- [ ] `gemcoder.yaml` visible at the project root (used in Scene 2).
- [ ] Terminal cleared, `PS1` shortened to `$ ` (no clutter).
- [ ] No background runs in `.gemcoder/runs/` (clears the panel-list noise).

---

## Shot list

| # | Time | Length | Shot | On-screen | Voiceover / lower-third caption |
|---|------|--------|------|-----------|--------------------------------|
| 1 | 0:00 | 5s | **Title card** | Black slide → fade to terminal. Centered text: **GemCoder** · *one harness, two Gemini backends.* | VO: *"Gemini has two ways to code for you — local SDK or managed cloud. Which wins on your task?"* |
| 2 | 0:05 | 8s | **The config** | `bat gemcoder.yaml` highlighting `managed_agent.base_agent` + `orchestrator.default_backend`. Cursor lingers on the `backend:` field. | Caption: **One config. Two engines.** |
| 3 | 0:13 | 12s | **Smoke ping, both backends** | `gemcoder smoke --backend both "Say hello in five words."` <br>→ Two side-by-side Rich panels appear: `local · ok · 0.4s` / `remote · ok · 1.1s`. | VO: *"Smoke check first — credentials, reachability, latency floor."* Caption: **smoke = round-trip in <2s.** |
| 4 | 0:25 | 18s | **Real coding task, both backends** | `gemcoder run --backend both "Add a CHANGELOG.md entry for v0.2"` <br>Stream shows two parallel progress trails (`[local]` / `[remote]`). End frame: two panels, one with **★** marker — `local ★ · ok · 3.2s` (green) / `remote · ok · 4.8s` (blue). | VO: *"Same task, in parallel. Winner is whichever returns a valid patch first."* Caption: **★ = winner.** |
| 5 | 0:43 | 10s | **Artifacts** | `ls .gemcoder/runs/<run-id>/` shows `managed-result-local.json`, `managed-result-remote.json`, `run-summary.json`, `task-packet.yaml`. Quick `cat run-summary.json \| jq '.winner, .elapsed_seconds'`. | Caption: **Every run, both sides, on disk.** |
| 6 | 0:53 | 5s | **Switch flag** | Clear screen. Type slowly: `gemcoder run --backend local "…"` → backspace `local` → type `remote` → backspace → type `auto`. | VO: *"One flag flips the engine. `auto` lets the harness decide."* |
| 7 | 0:58 | 2s | **End card** | Black slide. Centered: **`pip install gemcoder` · github.com/…/gem-coder** | (silent) |

**Total: 60.0 s.**

---

## Delivery notes

- **Pacing:** Scene 4 is the hero shot — let the parallel stream visibly race for ~3s before cutting to the winner panel. Don't speed it up in post.
- **Color:** Rich panels render `green` for the winner, `blue` for the runner-up, `red` for failures. Keep terminal background dark enough that blue stays readable (avoid Solarized Light).
- **Typing:** Pre-type the long commands and paste them — typing live wastes seconds. The one exception is Scene 6 (the flag-flip cycle is the whole point of the shot).
- **Audio:** If recording VO, two lines total — Scenes 1 and 4. Captions carry the rest.
- **Fallback path:** if the remote backend rate-limits during the take, swap Scene 3's prompt to something shorter and re-record only Scenes 3 and 4. Scene 5 reads from disk so it tolerates either backend winning.

## Asset checklist (post)

1. Title card PNG (Scene 1) — 1920×1080, brand purple `#7D56F4` accent.
2. End card PNG (Scene 7) — same template, different copy.
3. Lower-third caption track (`.srt`) — five captions, timed to scenes 2, 3, 4, 5, 6.
4. Source `.mov` from `screencapture -v` or OBS at 60fps.
5. Optional: extract Scene 4 alone as a 12s looping GIF for social.

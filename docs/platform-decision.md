# Platform Decision: ADK 2.0 + Managed Agents

**Status:** Decided · 2026-05-23
**Owner:** GemCoder maintainers

## TL;DR

Build with **ADK 2.0 (Python)**. Deploy to **Managed Agents (Interactions API)**. Adopt **A2A** when GemCoder needs subagents. Skip everything else for now.

> **Update — 2026-05-23 (team decision): use both.** The **Antigravity SDK** is
> adopted as GemCoder's **local backend** (the "embed the harness / self-host"
> layer in the table below): run the same harness on the developer's machine for
> lighter tasks. **ADK 2.0 + Managed Agents** remain the build + cloud path for
> bigger tasks. They are **complementary layers, not alternatives** — same engine,
> so local↔cloud parity. The "Direct dependency on Antigravity SDK" rejection
> below is **superseded** (see the amended note there).

## How the 6 Google agent pieces actually layer

| Layer | Product | Role |
|---|---|---|
| IDE / desktop | Antigravity 2.0 | Standalone agent-first desktop app + CLI. *A product to compete with, not depend on.* |
| **Build the agent** | **ADK 2.0** (GA May 19, 2026) | Code-first framework. Python/TS/Go/Java/Kotlin. Graph workflows, tools, Task API. |
| **Agent-to-agent transport** | **A2A v1.0.0** (Linux Foundation, Mar 2026) | JSON-RPC over HTTP between opaque agents. Agent Cards, streaming, tasks. |
| Embed the harness | Antigravity SDK | Programmatic access to the same harness powering Antigravity 2.0 + Managed Agents. Self-host. |
| **Hosted runtime** | **Managed Agents API** (Gemini API preview) | One call → isolated Linux sandbox + Antigravity harness on Gemini 3.5 Flash. Interactions API. *GemCoder already targets this.* |
| Distributed runtime | Agent Executor (`github.com/google/ax`, preview) | Open-source durable runtime for long-running agents on your own infra. Harness-agnostic. |

## Stack picks for GemCoder

1. **Build with ADK 2.0 (Python)** — replaces the bespoke prompt+patch flow in `src/gemcoder/managed.py` with a real agent loop. Graph workflows + Task API map cleanly onto GemCoder's run timeline/skills.
2. **Run on Managed Agents (Interactions API)** — already on `generativelanguage.googleapis.com/v1beta`; the Antigravity harness inside Managed Agents gives the isolated Linux sandbox + persistent files per session that the TUI already pretends to have.
3. **Adopt A2A for inter-agent calls** — sets up the multi-agent roadmap item (subagents, scheduled tasks) without locking us in to Google. Use `a2a-sdk` (Python).
4. **Skip Agent Executor for now** — preview and overkill until GemCoder needs durable hour-long runs on our own k8s. Note as eventual "self-hosted enterprise" deploy target.
5. **Skip the Antigravity desktop app** — it *is* the competitor.
6. **Antigravity SDK is optional** — only pull it in if GemCoder needs to also run *without* Google hosting the sandbox.

**One-line pick:** ADK 2.0, deployed to Managed Agents.

## Migration cost & sequencing

These decisions are *direction*, not a single PR. Concrete plan:

| Phase | Work | Est. effort | Blocks |
|---|---|---|---|
| **0 — Current state** | `ManagedAgentClient` posts directly to `/v1beta/interactions` or `/v1beta/models/{m}:generateContent` (SSE). Multi-turn context kept in `serve.py`. | — | shipped (commit `88a5326`) |
| **1 — ADK adoption (real cost)** | Rewrite `managed.py` around `google-adk` agents/tools. Map the existing `goal/repo/instructions/skills/return_contract` packet into an ADK agent config. Keep the SSE streaming + JSON-RPC notification path. | 1–2 focused days | None — current code keeps working until cut over |
| **2 — Multi-agent (A2A)** | Define second agent (e.g. test-writer, verifier) as a separate ADK agent; wire `a2a-sdk` for calls between them. | 1–2 days | Phase 1 |
| **3 — Enterprise self-host (Agent Executor)** | Package the ADK agents for Agent Executor; add deploy docs. | 2+ days | Phase 1 |

**Do NOT do Phase 1 in the same PR as another feature.** It will touch every file in `src/gemcoder/managed.py`, `harness.py`, and likely `task_packet.py`, and risk regressing the streaming/diff/apply loop we just shipped.

## What this decision rejects

- **Antigravity desktop app / CLI as a dependency.** They're the competitor product surface, not a building block.
- ~~**Direct dependency on Antigravity SDK.**~~ **Superseded (2026-05-23, "use both"):** the Antigravity SDK is now adopted for the **local backend** — running the harness on the dev's machine with the same engine as Managed Agents (local↔cloud parity). Managed Agents stays the cloud runtime; the SDK is the local-runtime layer, not a redundant copy.
- **Agent Executor short-term.** Preview status, infra investment, no user pull yet.

## Open questions

- ADK Python lacks some of the harness niceties our `harness.py` builds (build manifests, skill loading, context snapshots). On migration, do we keep those wrappers around ADK or rewrite them as ADK tools/state?
- Managed Agents' SSE stream shape matches what GemCoder already parses. Confirm this stays stable across ADK adoption — if ADK wraps it, may need to re-parse.
- A2A: which transport (HTTP vs gRPC) for our use case? Defer until Phase 2.

## Sources

- [Agent Executor announcement (Google Cloud)](https://cloud.google.com/blog/products/ai-machine-learning/agent-executor-googles-distributed-agent-runtime)
- [A2A on GitHub](https://github.com/a2aproject/A2A)
- [ADK docs](https://adk.dev/get-started/) · [adk-python](https://github.com/google/adk-python) · [ADK on Gemini Enterprise](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk)
- [Managed Agents quickstart](https://ai.google.dev/gemini-api/docs/managed-agents-quickstart) · [Managed Agents API (Enterprise)](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents)
- [Introducing Managed Agents in the Gemini API](https://blog.google/innovation-and-ai/technology/developers-tools/managed-agents-gemini-api/)
- [Antigravity 2.0 launch (TechCrunch)](https://techcrunch.com/2026/05/19/google-launches-antigravity-2-0-with-an-updated-desktop-app-and-cli-tool-at-io-2026/) · [I/O 2026 developer highlights](https://blog.google/innovation-and-ai/technology/developers-tools/google-io-2026-developer-highlights/)

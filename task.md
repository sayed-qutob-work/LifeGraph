# LifeGraph — Project Plan & Working Memory

> Read this when resuming work. It contains every settled decision so you don't re-derive anything.
> Last strategy review: 2026-06-05.

---

## 1. Project Summary

LifeGraph is a fully-local personal knowledge graph (Flask + SQLite + Vis.js + Ollama) that stores typed entities and relationships about *you* — your tools, models, hardware, projects, decisions, and constraints. It exists to solve the **re-explanation problem**: every new AI conversation (Claude, ChatGPT, Cursor) starts cold, and you waste effort re-typing the same personal context. LifeGraph captures that context once, keeps it as a queryable graph, and lets you pull the relevant connected slice into any AI conversation. Target user is one specific person: the AI tinkerer/developer who runs local LLMs and repeatedly re-states their setup across tools — initially **you, the builder, as the sole dogfooder.** It is not a notes app and not a second brain; it is a context feeder for AI.

---

## 2. Validated Decisions (settled — do not revisit)

1. **Target user is "User B": the local-LLM developer/tinkerer.** Not journalers, not PKM hobbyists, not the general public. You are the first and primary user.
2. **The value prop is a context engine for AI conversations**, not a thinking tool or a graph-visualization toy. The graph is the engine; the *output* (context injected into AI) is the product.
3. **Manual sentence-by-sentence entry is the fatal flaw.** Nobody narrates their life into a box. Input cost must drop to near-zero or the tool never reaches useful scale.
4. **The moat only exists above ~300 facts.** Below that scale a markdown file wins. Reaching that scale requires low-friction (passive) input. This is the whole ballgame.
5. **Format is roughly neutral.** Raw JSON/XML does NOT meaningfully beat prose/markdown for LLM consumption. Do not spend time on format aesthetics. The real problems are **relevance** and **verbosity**, solved by *sending less*, not by *structuring more*.
6. **The defensible niche is local-first, user-owned, cross-tool, portable memory.** This is the ONLY ground not already owned by Mem0/Zep (infra-for-app-builders) or native memory (ChatGPT/Claude, inside their walls). If LifeGraph ever drifts toward "memory infrastructure other devs integrate," it becomes a worse, unfunded Mem0 — that framing is forbidden.
7. **Passive extraction must be gated by a salience filter and a per-session review queue.** Pure auto-extract = noise collapse = a graph you can't trust. Human-in-the-loop moves from *per-fact* to *per-session*, it is never fully removed.
8. **"Real-time connect to ChatGPT/Claude web history" does not exist** and is not a dependency. Viable input channels are: (a) MCP tool calls during conversation, (b) local Claude Code session logs (JSONL on disk), (c) export-file import. Build around (a) and (b).
9. **Build order is fixed:** fix input cost (passive via MCP) → close the capture→retrieve→inject loop → measure whether it changes AI answers. One input channel at a time.

---

## 3. The Core Value Prop

LifeGraph is the **one personal context layer you own that follows you across every AI tool.** Native memory (ChatGPT Memory, Claude projects) solves ~80% of this *inside each vendor's walls* — but it doesn't travel with you, and you don't own or control the data. A markdown file travels and is owned, but can't pull a *relevant connected subset* — at scale it forces all-or-nothing pasting or tedious manual line-hunting. LifeGraph's only durable advantage is **pulling the connected subgraph relevant to what you're doing right now**, from data captured passively so you never had to type it, owned locally so it crosses tool boundaries. That combination — passive capture + relevance-filtered retrieval + local ownership + cross-tool portability — is what neither a flat file nor native memory provides.

---

## 4. What NOT to Build (rejected — do not re-litigate)

- **Manual sentence entry as the primary input** — fatal flaw; nobody will do it at scale.
- **Elegant JSON/XML export schemas** — format is neutral; LLMs read prose fine. Wasted effort.
- **Intent-based auto-filtering ("declare what you're doing → surface subgraph") as an early feature** — it's a second relevance-guessing layer as hard as parsing; one wrong surface kills trust. It must *emerge from* observed selection patterns later, not be guessed up front.
- **Vis.js lasso/canvas multi-select UX as a near-term priority** — fiddly, only pays off above a scale you haven't reached, and it's the *output* side when the *input* side is the bottleneck.
- **ChatGPT / web-history connectors** — no clean API exists; integration sprawl that turns a 3-month dogfood into a 12-month slog.
- **Multi-tool support before the loop works in ONE tool** — earn portability by proving the loop in Claude Code first.
- **Framing LifeGraph as memory infrastructure for other developers' apps** — that's Mem0's turf; you lose on resources and funding.
- **More node/edge types** — already over-engineered (17 node / 23 edge types) for a tool with zero validated daily users; more types make 7B extraction worse and review more tedious.
- **GraphRAG-style batch community summarization as the model** — wrong shape (document-corpus QA, expensive, non-incremental). Borrow only the hierarchical-retrieval idea if ever needed.

---

## 5. Architecture Overview

### Exists today (reuse as-is)
- **SQLite graph store** (`store.py`) — dedup-by-identity `(normalize(label), type)`, WAL, transactional writes, versioned migrations.
- **Domain model** (`domain.py`) — Node/Edge/Graph + Proposed* types + enums. The single source of truth for types.
- **Parser** (`parser.py`) — validates input pre-LLM, validates types post-LLM → `ProposedGraph`.
- **Ollama gateway** (`ollama_client.py`) — sole LLM gateway, loopback-guarded, few-shot extraction prompt, `temperature=0`. This is your extractor; reuse it.
- **MCP server** (`mcp_server.py`) — already exposes `add_observation` (parse+persist) and `get_context`. **This is the spine of the passive pipeline.**
- **Subgraph serializer** (`serializer.py`) — bounded BFS → deterministic text. This is the output/injection side.
- **Flask API + factory wiring** (`api.py`, `factory.py`) — shared construction for both front doors.

### Needs building (this is the actual project — mostly *quality*, not plumbing)
1. **Salience filter** — gate before anything enters the graph: "is this a stable fact about the user (setup/preference/project/decision) vs. a transient question/hypothetical/code snippet?" Cheap heuristics first, LLM-judged second. **Single most important new component.**
2. **Per-session review queue** — "here's what I learned today: keep / drop / merge." Moves human-in-the-loop from per-fact to per-day. Cheap UI, existential for trust.
3. **Claude Code log ingestor** — parse `~/.claude/projects/**/*.jsonl` → candidate facts → salience filter → review queue. Fully local, no API. Highest-value input because the data is already on disk.
4. **Relevance-ranked retrieval** — upgrade `get_context` to rank by relevance and support **saved named bundles** (e.g. "extraction-pipeline", "hardware"). The payoff side of the loop.
5. **Conflict / decay handling** — new fact contradicts old; unused facts fade. Borrow from Zep's temporal model. Crude v1 is fine; build only if noise actually hurts.

---

## 6. The Three-Month Roadmap

> Constraint: ~8–12 hrs/week, intermittent (internship + grad apps). Optimize for a dogfoodable loop fast; ONE input channel; no integration sprawl.

### Month 1 — Make the MCP passive path genuinely good
`add_observation` already exists; make it trustworthy.
- Add the **salience filter** so it stops eating noise.
- Harden **dedup-on-write**.
- Build a **dead-simple review view** (keep/drop).
- **Dogfood daily** inside Claude Code / Claude Desktop.
- **Deliverable:** your real conversations populate a clean-ish graph with zero manual typing.

### Month 2 — Close the loop (retrieval + backfill)
- Make `get_context` **relevance-ranked**; add **saved bundles**.
- Build the **Claude Code JSONL ingestor** to backfill everything already on disk.
- **Deliverable:** a working capture → store → retrieve → inject loop you use every day.

### Month 3 — Measure, then decide (do NOT add features)
- Instrument and answer the single validation question (below).
- Add conflict/decay **only if** noise is measurably hurting.
- **Deliverable:** an honest continue-or-shelve verdict from real usage.

### THE Month-3 Validation Question
> **Does injected context actually change the AI's answers, and is the graph clean enough that I trust the bundle I'm pasting?**
> If yes → cross-tool portability is worth building next. If "I could've kept this in a markdown file" → shelve cheaply. This is the cheap failure; discovering it now beats discovering it in 18 months.

---

## 7. Current Task (start here, right now)

**Build the salience filter and wire it in front of `add_observation` in the MCP server.**

Why this first: passive capture is the unlock, but without a salience gate the graph fills with noise and becomes untrustworthy — which kills the whole value prop. `add_observation` already parses and persists; right now it persists *everything* it's told. You're inserting a decision step before persistence.

Concrete starting steps:
1. Open `backend/lifegraph/mcp_server.py`, find `add_observation`, trace the path into `parser.py` → `store.apply_proposal`.
2. Add a salience check between parse and persist. v1 = cheap heuristics: does the proposed content describe a *stable* fact about the user (their tools/models/hardware/projects/decisions/preferences) vs. a transient one-off (a question, a hypothetical, a code snippet, something about a third party with no relation to the user)? Reject or hold the transient ones.
3. Anything that passes but is uncertain → route to a **hold/review** state rather than auto-persisting (this is the seed of the Month-1 review queue).
4. Dogfood: run a few real Claude Code sessions through it and eyeball precision/recall of what got kept.

Do NOT start with the log ingestor, retrieval ranking, or any UI polish. Salience gate first — everything downstream depends on the graph being clean.

---

## 8. Open Questions (decide later — don't answer now)

- **Salience implementation:** pure heuristics, a dedicated LLM judge call, or hybrid? What precision/recall is "good enough" to trust auto-keep vs. force review?
- **Review cadence:** real-time per-observation, end-of-session, or daily digest? What's least annoying while still maintaining trust?
- **Conflict resolution semantics:** when a new fact contradicts an old one, replace / version / flag for review? Do we keep history (Zep-style temporal) or overwrite?
- **Decay policy:** do unused facts fade/archive automatically, and after how long? Or is the graph append-only with manual pruning?
- **Bundle definition:** are saved bundles a fixed node set, a root-node + N-hop rule, or a saved query? How do they stay fresh as the graph grows?
- **Retrieval relevance signal:** graph proximity only, embeddings, recency, or a blend? Where do embeddings live given the local-only constraint?
- **Injection mechanism for non-MCP tools:** clipboard copy, a file the tool reads, or a browser extension? (Deferred until cross-tool is proven worth it.)
- **De-dupe across paraphrases:** identity is `(normalize(label), type)`, but passive extraction will produce many near-synonyms ("3090" vs "RTX 3090" vs "my GPU"). Do we need entity resolution beyond exact-normalized match?
- **Privacy boundary for log ingestion:** do we extract from *all* Claude Code sessions, or let the user scope which projects/sessions are eligible?
- **Salience ground truth:** how do you build a test set to know if your salience filter is working? Without this, Month 1's "dogfood and eyeball" has no exit criterion.
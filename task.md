# LifeGraph — Project Plan & Working Memory

> Read this when resuming work. It contains every settled decision so you don't re-derive anything.
> Last strategy review: 2026-06-06.

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
- Add the **salience filter** so it stops eating noise. ✅ *done — `salience.py`, 479 tests, 100% precision/recall on the corpus.*
- Build a **dry-run JSONL ingestor** (report-only): walk `~/.claude/projects/**/*.jsonl` through the existing parser + `salience.classify` and print a KEEP/HOLD/DROP report **without writing to the DB.** This validates the salience exit criterion against hundreds of real sentences at once (instead of slow hand-fed dogfood), sizes the backlog against the ~300-fact moat threshold, and is ~80% of the real ingestor.
- **Then let the dry-run numbers pick the next move** (resolves the ingestor-vs-review-UI ordering tension):
  - auto-KEEP trustworthy **and** HOLD pile small → flip persistence on, harden **dedup-on-write**, defer the review view.
  - HOLD pile large → build the **dead-simple review view** (keep/drop) *first*, because clearing the pile one-by-one via MCP `review_held` won't scale.
- **Dogfood daily** inside Claude Code / Claude Desktop.
- **Deliverable:** your real conversations + on-disk backlog populate a clean-ish graph with zero manual typing.

### Month 2 — Close the loop (retrieval)
- Make `get_context` **relevance-ranked**; add **saved bundles**.
- (Backfill moved up to Month 1: the ingestor that started as a dry-run gets persistence flipped on.)
- **Deliverable:** a working capture → store → retrieve → inject loop you use every day.

### Month 3 — Measure, then decide (do NOT add features)
- Instrument and answer the single validation question (below).
- Add conflict/decay **only if** noise is measurably hurting.
- **Deliverable:** an honest continue-or-shelve verdict from real usage.

### THE Month-3 Validation Question
> **Does injected context actually change the AI's answers, and is the graph clean enough that I trust the bundle I'm pasting?**
> If yes → cross-tool portability is worth building next. If "I could've kept this in a markdown file" → shelve cheaply. This is the cheap failure; discovering it now beats discovering it in 18 months.

---

## 7. Current Task

**Build the dry-run (report-only) Claude Code JSONL ingestor: `backend/lifegraph/ingest.py`.**

Walk `~/.claude/projects/**/*.jsonl`, pull candidate sentences out of each session, push every one through the **existing** `parser.parse` + `salience.classify`, and print a KEEP/HOLD/DROP confusion report **without writing a single row to the DB.** Count the verdicts, sample a handful of each, and stop. No persistence, no review UI, no schema change.

**Why this is next (it threads the one open disagreement instead of guessing):**
The remaining tension is *ordering* — does the JSONL ingestor come before the review view, or after? The plan says clean-first (review UI is a prerequisite, because a backfill dumps a HOLD pile only clearable one-by-one via `review_held`). The earlier assessment says volume-first (you can't answer the Month-3 question on an empty graph, and live MCP capture is too slow to reach the ~300-fact moat). A dry-run settles it with data:

1. **It IS the Step-C exit criterion, at ~100× the data.** Step C's bar is "zero false auto-KEEPs on real traffic." A dry-run over your on-disk backlog tests that against hundreds of real sentences in one pass — far better than slowly hand-feeding live dogfood.
2. **It answers the ordering question with numbers, not a guess.** Trustworthy auto-KEEP + small HOLD pile → flip persistence on and defer the review UI (assessment's order). Huge HOLD pile → build the review view first (plan's order). Let the report decide.
3. **It sizes the opportunity before you invest.** Does your backlog even clear ~300 quality facts? If not, the moat thesis needs rethinking — cheap to learn now.
4. **It's not throwaway.** Log-walking + extraction is ~80% of the real ingestor. You flip persistence on once the dry-run looks clean.

### Status: scaffolded and green. **493 tests pass** (479 baseline + 14 new). One step remains: the real-backlog run, which is gated on Ollama.

**Scaffolded (`backend/lifegraph/ingest.py`):**
- `iter_session_files` / `iter_file_candidates` — walks `~/.claude/projects/**/*.jsonl`; keeps only `type=="user"` / `role=="user"` / **string** content; skips tool-result lists and `<command-name>` / `<local-command-caveat>` machinery; tolerates malformed lines.
- `classify_candidate` — calls the real `parser.parse` then `salience.classify`, with the same error handling `add_observation` uses: parse/input errors → `dropped`; Ollama errors propagate and abort the run with an actionable message. No fork, no reimplementation.
- `format_report` — prints KEEP/HOLD/DROP counts + share, drop-reason breakdown, and N sampled sentences per verdict (ASCII-only; Unicode caused a cp1252 crash on Windows that was caught and fixed).
- CLI: `python -m lifegraph.ingest` with `--root`, `--sample`, `--limit` (quick smoke cap), and `--project` (the §8 privacy-scoping hook — moot for a dry-run, live once persistence flips on).
- `tests/test_ingest.py` — 14 fixture-based tests (synthetic JSONL + keyword-driven fake parser; no network, no real `~/.claude`).

**Remaining step — real-backlog run (Ollama-gated):**
Start Ollama (`ollama serve`, `127.0.0.1:11434`, `LIFEGRAPH_MODEL` pulled), then:
```
cd backend
python -m lifegraph.ingest --limit 50    # fast smoke pass first
python -m lifegraph.ingest               # full backlog
```
Eyeball the KEEP sample for false auto-KEEPs. Feed any misclassified sentence back into `salience_corpus.py`. The run also answers the two structural questions (ingestor-vs-review-UI ordering; does the backlog clear ~300 quality facts):
- **auto-KEEP trustworthy + HOLD pile small** → flip persistence on next, defer review view.
- **HOLD pile large** → build the review view first.
- **KEEP count well below ~300** → revisit the moat thesis before investing in persistence.

Note: KEEP count is sentences-that-would-keep, not unique facts (repeated pasted prompts inflate it). Treat it as an upper bound on quality facts until dedup-across-paraphrases (§8) is solved.

---

### Prior steps (DONE — historical record)

The salience filter and its measurable exit criterion are built and green. Recap so nothing gets re-derived:

**Salience filter (`salience.py`).** Pure classifier `classify(sentence, ProposedGraph) -> SalienceVerdict` returning KEEP / HOLD / DROP. v1 = cheap heuristics:
- **DROP**: empty extraction; questions (`?` or interrogative opener); hypotheticals (`what if`, `suppose`…); assistant commands (`can you`, `please fix`…); code (fences or dense punctuation); **no first-person reference at all** (third-party/general claims like "Ollama is a popular runtime").
- **KEEP**: first-person stative (`I use`, `my setup`…) **and** a user-relevant node type (Tool/Model/Hardware/Project/Skill/Goal/Habit/Technology/Program).
- **HOLD**: first-person reference and parsed into something, but not a clear stative user fact (e.g. "I tried Ollama briefly"). Conservative on purpose — ambiguous goes to HOLD, never auto-KEEP. Contract is transport-agnostic so an LLM judge can replace it later without touching callers.

**Store/MCP wiring.** `store.py` + `domain.py` — `held_observations` table (migration `_migrate_3`, `SCHEMA_VERSION` 3→4); `hold_observation` / `list_held` / `get_held` / `resolve_held`; `proposal_to_dict` / `proposal_from_dict` so a held proposal is stored verbatim and re-appliable. `mcp_server.py` — `add_observation` classifies before persisting and returns `{status: kept|held|dropped|error, …}`; KEEP persists + records provenance, HOLD queues, DROP discards, failures return a structured status. `list_held` + `review_held(held_id, "keep"|"drop")` MCP tools are the seed of the review queue.

**Step A — DONE.** Committed the first-person-gating refinement (`feat: drop third-party observations lacking a first-person reference`).

**Step B — DONE.** Committed `e8956bc`. `salience_corpus.py`: 54 hand-labeled examples across 8 categories. `test_salience_corpus.py`: confusion matrix, zero-false-KEEP invariant, KEEP recall ≥ 0.80, DROP recall ≥ 0.90. Baseline (**479 tests pass**): 100% precision/recall on all three classes.

**Step C — SUBSUMED by the dry-run ingestor above.** The original plan was slow hand-fed live dogfooding through `add_observation`. The dry-run ingestor tests the *same* exit criterion (zero false auto-KEEPs on real traffic) against the whole on-disk backlog at once, so it replaces Step C rather than waiting behind it. Live `add_observation` dogfooding still happens continuously in the background once Ollama is up; it's no longer the gating exit path.

**Deferred decisions (do NOT act on these yet — they wait for the dry-run's evidence):** heuristics-only vs. LLM judge (§8); review cadence (§8); whether to also gate the HTTP `/api/parse` path (currently MCP-only, since the web path already has per-parse human confirmation); ingestor persistence + dedup-on-write (flip on *after* the dry-run report is clean).

Do NOT flip on persistence, build retrieval ranking, or build the review UI yet — the dry-run report decides which of those comes first.

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
- **Privacy boundary for log ingestion:** do we extract from *all* Claude Code sessions, or let the user scope which projects/sessions are eligible? *(Moot for the local dry-run; becomes live the moment ingestor persistence is flipped on — leave a scoping hook.)*
- **Salience ground truth:** ~~how do you build a test set to know if your salience filter is working?~~ *Largely answered: Step B's hand-labeled `salience_corpus.py` is the ground-truth set; the dry-run ingestor extends it with real-traffic samples. Remaining open part: when is the corpus "big/representative enough" to trust auto-KEEP unsupervised?*
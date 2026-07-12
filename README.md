# LifeGraph

A fully local personal knowledge graph that turns plain-English sentences about you — your tools, hardware, projects, goals, preferences — into a typed, deduplicated graph you can query, visualize, and paste into any AI conversation as a compact context snapshot.

**Status: on hold.** The tool works end-to-end and the codebase is healthy (500+ tests). Development is paused after the passive-capture experiment returned its verdict — see [The experiment](#the-experiment-passive-capture) below for the honest numbers and what they mean.

## The idea

Every new AI conversation starts cold: you re-explain your setup, your stack, your constraints. LifeGraph was built to solve that **re-explanation problem**:

1. **Capture** — you (or a passive pipeline) feed it sentences: *"I use VS Code as my main editor."*
2. **Extract** — a locally-running LLM (Ollama, loopback-only, nothing leaves your machine) parses each sentence into typed nodes and edges.
3. **Store** — SQLite, with hard deduplication by `(normalized label, type)` identity, so "VS Code" is one node no matter how many times it's mentioned.
4. **Retrieve** — click any node and get a bounded-BFS plain-text snapshot of its neighborhood, sized for pasting into an AI chat.

Everything is local: the LLM gateway refuses any non-loopback address, the database is a file on your disk, and the graph DB / ingest results are gitignored — personal data never leaves the machine.

## What's inside

```
NL sentence
  → OllamaClient.parse_sentence()   (sole LLM gateway; loopback-guarded, temperature=0)
  → InputParser.parse()             (validation → ProposedGraph)
  → salience.classify()             (KEEP / HOLD / DROP — the noise gate for passive capture)
  → GraphStore.apply_proposal()     (dedup + persist, single transaction)
```

- **Web app** (`python -m lifegraph`) — Flask + Vis.js. Parse-and-confirm flow (nothing is written without human confirmation), graph editing, search, dashboard, and the one-click context snapshot panel. Dark, minimal UI; every node is a circle, colored by semantic family.
- **MCP server** (`python -m lifegraph.mcp_server`) — the same core exposed to Claude Desktop / Claude Code as tools: `add_observation` (parse → salience gate → keep/hold/drop), `get_context`, `search_graph`, `list_held` / `review_held` (the review queue), `upsert_node`, `create_edge`.
- **Salience filter** (`salience.py`) — pure heuristics deciding whether a sentence is a *stable fact about the user* (KEEP), ambiguous (HOLD → review queue), or transient noise (DROP). 100% precision/recall on a hand-labeled corpus; conservative by design — ambiguity is never auto-kept.
- **Batch ingestor** (`ingest.py`) — walks Claude Code session logs and claude.ai `conversations.json` exports, classifies every user sentence through the same pipeline (read-only, resumable), and can persist a hand-reviewed sentence list with `--persist`.

## Running it

Requirements: Python 3.12+, Node (tests only), [Ollama](https://ollama.com) with a model pulled (default `llama3`).

```bash
# backend
cd backend
pip install -e ".[dev]"
ollama serve                       # 127.0.0.1:11434
python -m lifegraph                # http://127.0.0.1:5000

# tests
cd backend && pytest               # 550+ tests, many property-based (Hypothesis)
cd frontend && npm install && npm test   # Vitest over the real static/js modules

# batch-classify your own AI conversation history (read-only dry run)
cd backend && python -m lifegraph.ingest --export path/to/conversations.json --output export_results.jsonl
cd backend && python -m lifegraph.ingest --report-only export_results.jsonl

# persist a hand-reviewed list of facts
cd backend && python -m lifegraph.ingest --persist curated.txt
```

Configuration via `LIFEGRAPH_*` env vars: `LIFEGRAPH_MODEL` (default `llama3`), `LIFEGRAPH_PORT` (5000), `LIFEGRAPH_DB_PATH` (`lifegraph.db`), `LIFEGRAPH_HOP_DISTANCE` (2), `LIFEGRAPH_TIMEOUT` (60s).

## The experiment: passive capture

Manual sentence-by-sentence entry was identified early as the fatal flaw — nobody narrates their life into a box. The bet was that **passive extraction from AI conversation history** (Claude Code session logs + claude.ai exports) could populate the graph to a useful scale (~300 stable facts) with near-zero input cost, gated by the salience filter to keep noise out.

The ingestor was built to test that bet honestly, as a read-only classification pass over the entire on-disk backlog before any persistence was wired. The results:

| Source | Candidate sentences | KEEP | HOLD | DROP |
|---|---|---|---|---|
| Claude Code session logs (33 sessions) | 1,656 | 37 (2.2%) | 109 (6.6%) | 1,510 (91.2%) |
| claude.ai export (192 conversations) | 3,866 | 54 (1.4%) | 686 (17.7%) | 3,126 (80.9%) |

Hand-reviewing every KEEP and HOLD verdict (740 unique sentences) distilled the entire ~5,500-sentence backlog into **~50 genuine, stable personal facts** — versus the ~300-fact threshold where a graph starts beating a flat file. A twist worth recording: most KEEPs from the Claude Code logs weren't even real — they were LifeGraph's *own test sentences* echoed back from dogfooding sessions, indistinguishable from genuine facts ("I use an RTX 3090" was a pasted demo example; the real GPU is a 4060 Ti). A tool that ingests conversations about building itself poisons its own well.

**The verdict:** what people type at AI assistants is overwhelmingly task-directed — instructions, questions, pasted code and logs — not self-describing facts. The genuine-fact yield of the entire backlog is roughly two orders of magnitude below the scale where a graph beats a well-kept markdown file. That's not a filter-tuning problem; it's the nature of the source. The salience gate did its job (near-zero false auto-keeps on real traffic after tuning); the data just isn't there.

So the project is paused rather than pushed: the loop works, the graph is populated with the curated facts the experiment surfaced, and the honest conclusion is recorded here instead of being rediscovered in six months. If a richer passive source appears (or the fact count changes the calculus), the pipeline is ready.

## What would revive it

- A passive source that's actually dense in personal facts (e.g. a journaling habit, meeting notes, or an assistant that asks about you).
- Entity resolution across paraphrases ("3090" vs "RTX 3090" vs "my GPU") — identity-by-normalized-label is exact-match only.
- Relevance-ranked retrieval and saved context bundles (designed, never built — the capture side never reached the scale to need them).

## License / privacy

Personal project. The graph database (`backend/lifegraph.db*`) and ingest verdict files (`*_results.jsonl`) contain personal data and are gitignored — if you fork this, keep it that way.

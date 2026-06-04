# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What LifeGraph is

A fully local, web-based personal knowledge graph. The user types plain-English sentences; a locally-running LLM (via Ollama) parses each into typed nodes and edges; the graph is stored in SQLite, rendered in the browser with Vis.js, edited manually, and exported as a compact text "context snapshot" for pasting into AI conversations.

Hard product constraints baked into the architecture (see `.kiro/specs/lifegraph/requirements.md` for the full spec):
- **Fully local / loopback-only.** All LLM traffic goes to Ollama on `127.0.0.1:11434`. `OllamaClient.verify_loopback` resolves the host and refuses any non-loopback address before every request — do not weaken this.
- **Human-in-the-loop parsing.** Parsed output is non-deterministic, so it is *never* written automatically. A parse produces a `ProposedGraph` held server-side under a token; nothing is persisted until the user confirms.
- **Deduplication by identity.** A node's identity is `(normalize(label), type)` where `normalize = casefold(strip(label))`. Same identity = same node, enforced by a UNIQUE index and reused on upsert.

## Commands

All Python commands run from `backend/`. Tests require the dev extras (`pip install -e ".[dev]"`).

```bash
# Run the web app (requires Ollama running with the configured model pulled)
cd backend && python -m lifegraph            # serves http://127.0.0.1:5000

# Run the MCP server (stdio; for Claude Desktop etc.)
cd backend && python -m lifegraph.mcp_server

# Backend tests (pytest config lives in backend/pyproject.toml)
cd backend && pytest                          # all tests, verbose
cd backend && pytest tests/test_store.py      # one file
cd backend && pytest tests/test_store.py::test_name   # one test
cd backend && pytest -k "proposal"            # by keyword
cd backend && pytest --cov=lifegraph          # with coverage

# Frontend property tests (Vitest + fast-check)
cd frontend && npm install                    # first time
cd frontend && npm test                       # vitest run
cd frontend && npm run test:watch
```

There is no build step or linter configured. Many tests are **property-based** (Hypothesis in Python, fast-check in JS) — files ending `_property.py` / using `fc.assert`.

## Configuration

Read from `LIFEGRAPH_`-prefixed environment variables in `config.py`, validated at startup (invalid values abort with a named error):

- `LIFEGRAPH_MODEL` (default `llama3`) · `LIFEGRAPH_PORT` (5000) · `LIFEGRAPH_DB_PATH` (`lifegraph.db`) · `LIFEGRAPH_HOP_DISTANCE` (2) · `LIFEGRAPH_TIMEOUT` (60s)

`server.py` runs ordered startup checks before binding: dependencies importable → config valid → DB readable-or-creatable (never overwrites an invalid file) → Ollama reachable → port free. Each failure aborts with a specific message and serves nothing.

## Architecture

The backend is a layered pipeline. Each layer is a separate module with one responsibility, and dependencies point inward toward the domain:

```
NL sentence
  → OllamaClient.parse_sentence()   (ollama_client.py — the SOLE LLM gateway; loopback-guarded)
  → InputParser.parse()             (parser.py — validates input pre-LLM, validates types post-LLM → ProposedGraph)
  → [held under a token, awaiting user confirmation]
  → GraphStore.apply_proposal()     (store.py — dedup + persist in one transaction)
```

- **`domain.py`** — the core data model and the *only* place node/edge types are defined: `NodeType` / `EdgeType` enums, their string-value frozensets (`NODE_TYPE_VALUES` / `EDGE_TYPE_VALUES`), persisted `Node`/`Edge`/`Graph`, pre-confirmation `ProposedNode`/`ProposedEdge`/`ProposedGraph`, and `normalize()` / `identity()`. **Proposed edges reference endpoints by `(label, type)`, not id** — ids only exist after persistence.

- **`store.py` (`GraphStore`)** — SQLite persistence. Autocommit connection with explicit `BEGIN`/`COMMIT`/`ROLLBACK` per write; WAL mode; `PRAGMA foreign_keys = ON`. Edges cascade-delete with their nodes. Schema constraints (type CHECKs, label length, the `(normalized_label, type)` UNIQUE index) are generated from the domain enums, so **CHECK constraints and the migration that rebuilds them stay in sync with `domain.py` automatically**. `apply_proposal` upserts every node, then resolves each edge's endpoints by identity (creating missing ones with `origin="parsed"`), all in a single transaction.

- **Schema migrations** — versioned via `PRAGMA user_version` against `SCHEMA_VERSION`. To change the schema: append a migration function to the `_MIGRATIONS` list and bump `SCHEMA_VERSION`. `_migrate_0` rebuilds the nodes/edges tables whenever the type CHECK constraints drift from the enums (this is how adding a `NodeType`/`EdgeType` propagates to existing DBs).

- **`parser.py` (`InputParser`)** — validates the sentence (1–1000 chars, non-blank) *before* any LLM call, then converts the raw LLM dict into a validated `ProposedGraph`. Invalid types raise `InvalidTypeError`; malformed structure raises `UnparseableResponse`. Drops self-reference labels (`I`, `me`, `my`, …) and normalizes the backwards-`referred_by` direction the LLM commonly emits. Counts are capped (≤100 nodes, ≤200 edges) by truncation, not rejection.

- **`ollama_client.py` (`OllamaClient`)** — the single LLM gateway. Holds the large few-shot extraction prompt (`_PARSE_PROMPT_TEMPLATE`); calls Ollama's `/api/generate` with `format=json`, `temperature=0` (determinism). Distinct errors: `OllamaUnavailableError` (down / model missing / bad JSON), `OllamaTimeoutError`, `ExternalConnectionError` (non-loopback).

- **`serializer.py` (`ContextSerializer`)** — pure function: bounded BFS from a root node (max hops/nodes/chars) → deterministic plain text. Ordering is by `(hop distance, node id)` so output is stable.

- **`search.py`** (`filter_graph`), **`dashboard.py`** (`aggregate_dashboard`), **`validation.py`** (label/attribute/date validators raising `*ValidationError`).

### Two front doors share one core

`api.py` (Flask HTTP) and `mcp_server.py` (MCP over stdio) are both thin transport layers over the same store + parser. **`factory.py` is the shared wiring** (`make_store`, `make_parser`) so both surfaces read config and construct objects identically — put shared construction logic there, not in either entry point.

- **`api.py`** — `create_app(config)` factory. Maps every domain exception to an HTTP status via registered error handlers, returning a standard envelope `{"error": {"code", "message", "details?}}`. Pending proposals live in `app.config["PENDING_PROPOSALS"]` keyed by a per-request token (so concurrent browsers don't collide); `/api/parse` issues the token, `/api/parse/confirm` consumes it and persists, `/api/parse/reject` discards it. The DB write and the provenance `record_capture` are deliberately decoupled — a capture failure never rolls back the graph.
- **`mcp_server.py`** — exposes `search_graph`, `get_context`, `add_observation` (parse+persist in one call), `upsert_node`, `create_edge` as MCP tools with lazily-initialized store/parser singletons.

### Frontend

Vanilla ES5 IIFE modules (no framework, no bundler) served by Flask from `backend/lifegraph/static/js/` with `templates/index.html`. `app.js` wires four components — `graphView` (Vis.js), `graphEditor`, `dashboard`, `search` — and routes every store mutation through a single `handleGraphChanged` callback so the view always re-renders to match the store. The `frontend/` directory holds **only the Vitest property tests**, which load the real `static/js/*.js` files from the backend via `fs` + `vm` — so the JS under test physically lives in `backend/`, not `frontend/`.

## Conventions

- The node/edge type sets are defined once in `domain.py` and mirrored in three other places that must be kept consistent when types change: the SQLite CHECK constraints (auto-generated, so fine), the LLM prompt's allowed-type lists in `ollama_client.py`, and the `NODE_TYPES`/`EDGE_TYPES` arrays in `static/js/app.js`.
- Timestamps are ISO-8601 UTC strings (`YYYY-MM-DDTHH:MM:SSZ`); pre-migration rows have empty timestamp strings and are excluded from "recent" queries.
- Nodes/edges carry `origin` = `"manual"` or `"parsed"`.
- Source files carry `Requirements: N.N` references back to `.kiro/specs/lifegraph/requirements.md` — consult it for the rationale behind a behavior.

## Working Plan
See `task.md` for full strategy, validated decisions, and current task.
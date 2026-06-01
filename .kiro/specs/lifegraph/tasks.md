# Implementation Plan: LifeGraph

## Overview

This plan builds LifeGraph incrementally from the inside out: domain types and configuration first,
then the `Graph_Store` (identity, dedup, referential integrity, cascade delete), then the language
core (`Ollama_Client`, `Input_Parser`, proposal application), the pure logic components
(`Context_Serializer`, dashboard aggregation, search/filter), the `Graph_API` transport layer, the
browser UI, and finally the startup sequence that wires everything together.

Backend is Python 3.10+ with Flask and `sqlite3`; property-based tests use Hypothesis. The two pure
front-end transforms (Properties 16, 17) are tested with fast-check under the browser test runner.
Each of the 31 correctness properties from the design becomes its own property-test sub-task placed
next to the implementation it validates. Test sub-tasks are marked optional with `*`.

## Tasks

- [x] 1. Set up project structure and core domain model
  - [x] 1.1 Initialize project structure, dependencies, and test frameworks
    - Create `backend/lifegraph/` package and `backend/tests/` directories, plus `backend/lifegraph/static/js/` and `backend/lifegraph/templates/`
    - Add Python dependencies (Flask, Hypothesis, pytest) via `requirements.txt`/`pyproject.toml`; add a `package.json` with fast-check and a JS test runner for the front-end pure transforms
    - Configure pytest and the JS test runner so both backend and front-end tests are runnable
    - _Requirements: 2.3_

  - [x] 1.2 Define domain types, type sets, and normalization helper
    - In `backend/lifegraph/domain.py` define `NodeType`/`EdgeType` enumerations for the Node_Type_Set and Edge_Type_Set, and `Node`, `Edge`, `Graph`, `ProposedNode`, `ProposedEdge`, `ProposedGraph` data structures
    - Implement `normalize(label) = casefold(strip(label))` and `identity(node) = (normalize(label), type)`
    - _Requirements: 4.5, 11.2_

  - [x] 1.3 Implement validation helpers
    - In `backend/lifegraph/validation.py` implement validators: storage label (1–200 chars), manual label (trimmed 1–100 chars), attribute set (≤50 entries, keys/values 1–255 chars), and Event `date` (`YYYY-MM-DD` format AND real calendar date, rejecting e.g. `2025-02-30`)
    - Define the domain error types used by validation (`LabelValidationError`, `DateValidationError`, attribute bound errors)
    - _Requirements: 5.2, 6.1, 6.3, 8.1, 8.4, 8.5_

- [x] 2. Implement configuration loading
  - [x] 2.1 Implement configuration module with defaults and validation
    - In `backend/lifegraph/config.py` read model name, localhost port, SQLite path, default context hop distance, and Ollama timeout; apply documented defaults for omitted settings; raise a startup error naming any invalid value
    - _Requirements: 15.1, 15.2, 15.3_

  - [x] 2.2 Write property test for configuration defaulting
    - **Property 31: Configuration defaulting**
    - **Validates: Requirements 15.2**

- [x] 3. Implement Graph_Store persistence, identity, and integrity
  - [x] 3.1 Implement schema creation, connection management, reads, and reload
    - In `backend/lifegraph/store.py` create the `nodes`/`edges` schema with `PRAGMA foreign_keys = ON`, CHECK constraints, the `UNIQUE(normalized_label, type)` index, and `ON DELETE CASCADE`; create an empty DB when the file is absent; detect an existing-but-invalid DB and raise a storage error without overwriting it
    - Implement read methods: `get_graph`, `get_node`, `find_node`, `incident_edges`, `nodes_by_type`; injected `id_factory` for deterministic ids
    - _Requirements: 5.1, 5.7, 5.8_

  - [x] 3.2 Implement node write path with deduplication and validation
    - Implement `upsert_node` (normalize, reuse existing `(normalized_label, type)` node keeping its id/label/attributes, else create with fresh UUID) and `update_node` (label/type/attributes); validate label and attribute bounds before writing; run each write in a single transaction; invoke Event `date` validation when applicable
    - _Requirements: 4.1, 4.2, 4.3, 4.5, 5.2, 6.1, 6.4_

  - [x] 3.3 Write property test for node identity
    - **Property 7: Node identity is unique, stable, and never reused**
    - **Validates: Requirements 4.1**

  - [x] 3.4 Write property test for deduplication
    - **Property 8: Deduplication by normalized label and type**
    - **Validates: Requirements 4.2, 4.3, 4.5**

  - [x] 3.5 Write property test for node and attribute validation bounds
    - **Property 13: Node and attribute validation bounds**
    - **Validates: Requirements 5.2, 6.1**

  - [x] 3.6 Write property test for attribute edit round-trip
    - **Property 15: Attribute edit round-trip**
    - **Validates: Requirements 6.4**

  - [x] 3.15 Write property test for Event date validation and persistence
    - **Property 14: Event date validation and persistence**
    - **Validates: Requirements 6.2, 6.3**

  - [x] 3.7 Implement edge write path with referential integrity and self-edge rejection
    - Implement `create_edge` (reject when source/target id absent, reporting the missing id, leaving both tables unchanged; reject self-edges; validate edge type), `update_edge` (type), and `delete_edge` (remove edge, keep endpoints); all inside transactions
    - _Requirements: 5.3, 5.4, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 3.8 Write property test for referential integrity on edge creation
    - **Property 10: Referential integrity on edge creation**
    - **Validates: Requirements 5.4**

  - [x] 3.9 Write property test for edge creation and type validation
    - **Property 20: Edge creation and type validation**
    - **Validates: Requirements 9.1, 9.3, 9.4**

  - [x] 3.10 Write property test for edge type edit round-trip
    - **Property 21: Edge type edit round-trip**
    - **Validates: Requirements 9.2**

  - [x] 3.11 Write property test for edge deletion preserving endpoints
    - **Property 22: Edge deletion preserves endpoints**
    - **Validates: Requirements 9.5**

  - [x] 3.12 Implement node deletion with cascade
    - Implement `delete_node` to remove the node and all incident edges in one transaction (via `ON DELETE CASCADE`) and return the removed edge ids
    - _Requirements: 5.5, 8.6_

  - [x] 3.13 Write property test for cascade delete
    - **Property 11: Cascade delete removes all incident edges**
    - **Validates: Requirements 5.5, 8.6**

  - [x] 3.14 Write property test for storage reload round-trip
    - **Property 12: Storage reload round-trip**
    - **Validates: Requirements 5.6**

- [ ] 4. Checkpoint - Graph_Store
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement Ollama_Client (sole LLM gateway)
  - [x] 5.1 Implement loopback guard and Ollama client
    - In `backend/lifegraph/ollama_client.py` implement the loopback guard (verify the resolved target is a loopback address before connecting; block and surface "external connection prevented" otherwise) and `parse_sentence(sentence) -> RawProposal` with a configurable timeout; raise distinct `OllamaUnavailableError` (service down / model missing) and `OllamaTimeoutError`
    - _Requirements: 1.2, 1.4, 14.1, 14.2, 14.4, 16.2, 16.3_

  - [x] 5.2 Write property test for the loopback guard
    - **Property 1: Loopback guard classification**
    - **Validates: Requirements 1.4**

  - [x] 5.3 Write unit tests for Ollama error handling
    - Cover service-unreachable, missing-model, and timeout paths with a faked transport
    - _Requirements: 14.1, 14.2, 14.4_

- [x] 6. Implement Input_Parser
  - [x] 6.1 Implement input validation gating
    - In `backend/lifegraph/parser.py` validate sentence length (1–1000) and non-blank BEFORE contacting `Ollama_Client`, raising `InputValidationError` with no LLM call on failure; obtain model responses exclusively through `Ollama_Client`
    - _Requirements: 3.1, 3.8, 16.1_

  - [x] 6.2 Write property test for length and blank-input gating
    - **Property 2: Length and blank-input gating of the parser**
    - **Validates: Requirements 3.1, 3.8**

  - [x] 6.3 Implement response validation into a ProposedGraph
    - Convert raw responses into a `ProposedGraph`, capping at 0–100 nodes / 0–200 edges, validating node/edge types against the type sets (rejecting and naming an invalid type), and raising `UnparseableResponse` when the output cannot be converted
    - _Requirements: 3.2, 3.3, 3.4_

  - [x] 6.4 Write property test for proposal bounds and type validity
    - **Property 3: Proposal bounds and type validity**
    - **Validates: Requirements 3.2**

  - [x] 6.5 Write property test for invalid type rejection
    - **Property 4: Invalid type rejection**
    - **Validates: Requirements 3.3**

  - [x] 6.6 Write property test for unparseable response leaving store unchanged
    - **Property 5: Unparseable response leaves store unchanged**
    - **Validates: Requirements 3.4**

- [ ] 7. Implement proposal application in Graph_Store
  - [x] 7.1 Implement apply_proposal with endpoint resolution and dedup
    - In `backend/lifegraph/store.py` implement `apply_proposal` to resolve or create each `(label, type)` endpoint (reusing identity-matched nodes) before creating edges, all in a single transaction; ensure a rejected/never-confirmed proposal performs no write
    - _Requirements: 3.6, 3.7, 4.4_

  - [ ] 7.2 Write property test for edge endpoint resolution
    - **Property 9: Edge endpoints resolve to identity-matched nodes**
    - **Validates: Requirements 4.4**

  - [ ] 7.3 Write property test for confirm-persists / reject-no-op
    - **Property 6: Confirm persists, reject is a no-op**
    - **Validates: Requirements 3.6, 3.7**

- [x] 8. Implement Context_Serializer
  - [x] 8.1 Implement deterministic BFS traversal, budget trimming, and rendering
    - In `backend/lifegraph/serializer.py` implement `serialize(graph, root_id)`: stable-ordered BFS (hop distance, then node id) up to `max_hops` (default 2), budget trimming that drops most-distant nodes when over node/char budget, and a fixed plain-text template including each node's type+label and each edge's type/source/target
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 8.2 Write property test for snapshot content completeness
    - **Property 23: Context snapshot content completeness**
    - **Validates: Requirements 10.2**

  - [x] 8.3 Write property test for hop-bound traversal
    - **Property 24: Context traversal respects the hop bound**
    - **Validates: Requirements 10.3**

  - [x] 8.4 Write property test for budget prioritizing nearer nodes
    - **Property 25: Context budget prioritizes nearer nodes**
    - **Validates: Requirements 10.4**

  - [x] 8.5 Write property test for deterministic serialization
    - **Property 26: Context serialization is deterministic**
    - **Validates: Requirements 10.5**

- [x] 9. Implement dashboard aggregation logic
  - [x] 9.1 Implement dashboard aggregation
    - In `backend/lifegraph/dashboard.py` produce skills, goals, upcoming events (date >= injected "today", ascending order, today included), and a separate undated-events group
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 9.2 Write property test for skill and goal completeness
    - **Property 28: Dashboard skill and goal completeness**
    - **Validates: Requirements 12.1**

  - [x] 9.3 Write property test for event partitioning and ordering
    - **Property 29: Dashboard event partitioning and ordering**
    - **Validates: Requirements 12.2, 12.3**

- [x] 10. Implement search and filter logic
  - [x] 10.1 Implement type/label filtering
    - In `backend/lifegraph/search.py` filter by selected node types and/or case-insensitive label term, include edges connecting two included nodes, return the full graph when no filter/term is active, and ensure order-independent results
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [x] 10.2 Write property test for filtering with order independence
    - **Property 30: Type and label filtering with order independence**
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.4**

- [ ] 11. Checkpoint - Logic core
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Implement Graph_API transport layer
  - [x] 12.1 Implement API core, error mapping, JSON serialization, and graph fetch
    - In `backend/lifegraph/api.py` create the Flask app factory, the standard error envelope and domain-error→HTTP-status mapping, JSON serialization of nodes/edges, `GET /` (HTML loading Vis.js + app JS), and `GET /api/graph`
    - _Requirements: 2.2, 7.1, 11.1, 11.2_

  - [x] 12.2 Write property test for JSON interchange round-trip
    - **Property 27: JSON interchange round-trip**
    - **Validates: Requirements 11.1, 11.2, 11.3**

  - [x] 12.3 Implement manual node and edge endpoints
    - Add `POST/PUT/DELETE /api/nodes`, `PUT/DELETE /api/edges`, `POST /api/edges`, and `GET /api/nodes/{id}/edges` (incident-edge count driving the delete warning); enforce manual node label bounds (trimmed 1–100), type validity, self-edge rejection, and referential integrity via the store
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ] 12.4 Write property test for manual node label and type validation
    - **Property 18: Manual node label and type validation**
    - **Validates: Requirements 8.1, 8.3, 8.4, 8.5**

  - [ ] 12.5 Write property test for the high-degree delete warning threshold
    - **Property 19: High-degree delete warning threshold**
    - **Validates: Requirements 8.7**

  - [ ] 12.6 Implement parse, confirm, and reject endpoints
    - Add `POST /api/parse` (validate + parse into a proposal with an in-progress indication), `POST /api/parse/confirm` (apply proposal), and `POST /api/parse/reject` (no write); map parser/Ollama errors to 400/422/502/504
    - _Requirements: 3.5, 3.6, 3.7, 14.3_

  - [ ] 12.7 Implement dashboard, context, and search endpoints
    - Add `GET /api/dashboard`, `POST /api/context`, and `GET /api/search` wired to the dashboard, serializer, and search components
    - _Requirements: 10.1, 12.1, 13.5_

  - [ ] 12.8 Write example and error-path tests for endpoints
    - Cover proposal-presented-before-write (3.5), store-unavailable during attribute edit (6.5), edge field read-back (5.3), and cancel-delete-keeps-data behavior at the API boundary
    - _Requirements: 3.5, 5.3, 6.5, 8.8_

- [ ] 13. Implement browser UI
  - [x] 13.1 Scaffold index.html and API client
    - Create `templates/index.html` loading the Vis.js library and app JS, and `static/js/api.js` as the fetch wrapper for all endpoints
    - _Requirements: 2.2_

  - [x] 13.2 Implement Graph_View
    - In `static/js/graphView.js` fetch `GET /api/graph`, transform nodes/edges into a Vis.js dataset (node labels, edge-type labels), apply per-type styling, highlight a selected node and its incident edges, render an empty network cleanly, and show an error with no partial network on fetch failure
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.7, 7.8, 7.9_

  - [x] 13.3 Write property test for the graph-to-view transform
    - **Property 16: Graph-to-view transform preserves labels**
    - **Validates: Requirements 7.2, 7.3**

  - [x] 13.4 Write property test for node type styling
    - **Property 17: Node type styling is injective**
    - **Validates: Requirements 7.7**

  - [x] 13.5 Implement Graph_Editor
    - In `static/js/graphEditor.js` build node/edge create/edit/delete forms with client-side validation mirroring backend rules (preserving submitted values on rejection) and the high-degree (≥5 edges) delete confirmation gate that issues no DELETE when cancelled
    - _Requirements: 8.3, 8.4, 8.5, 8.7, 8.8, 9.3, 9.4_

  - [x] 13.6 Implement Dashboard UI
    - In `static/js/dashboard.js` call `GET /api/dashboard` and render skills, goals, upcoming events (ascending), and the undated-events group
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x] 13.7 Implement Search_Filter UI
    - In `static/js/search.js` compose type filters and a label term into `GET /api/search`, hand results to Graph_View, and restore the full graph when cleared
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [ ] 13.8 Wire front-end components together
    - In `static/js/app.js` initialize and connect Graph_View, Graph_Editor, Dashboard, and Search_Filter so store changes re-render the view
    - _Requirements: 7.5_

  - [ ] 13.9 Write front-end example tests
    - Cover empty-store render (7.8), fetch-failure error indication (7.9), and cancel-delete-keeps-data in the editor (8.8)
    - _Requirements: 7.8, 7.9, 8.8_

- [ ] 14. Implement server startup and wiring
  - [ ] 14.1 Implement startup sequence and main entry point
    - In `backend/lifegraph/server.py` validate critical startup conditions in order (declared deps importable, config valid, DB readable/valid or created empty without overwriting an invalid file, Ollama reachable, port free) and bind Flask to `127.0.0.1` on the configured/default port; abort with a specific message naming any failed condition and serve no request
    - _Requirements: 1.1, 1.5, 2.1, 2.4, 2.5, 2.6, 5.7, 5.8, 15.3, 16.2_

  - [ ] 14.2 Write unit tests for startup failure conditions
    - Cover missing dependency, port in use, unreachable Ollama, invalid config value, and unreadable/invalid DB (not overwritten)
    - _Requirements: 2.4, 2.5, 2.6, 5.8, 15.3_

- [ ] 15. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP.
- Each task references specific requirements clauses for traceability; property test tasks reference both their design property number and the requirements they validate.
- Property tests use Hypothesis (backend) and fast-check (the two front-end pure transforms, Properties 16 and 17), each running a minimum of 100 generated examples, with one property-based test per property.
- Checkpoints provide incremental validation between major layers.
- The backend stays the source of truth; front-end validation mirrors backend rules only for immediate feedback.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["1.3", "2.2", "3.1", "5.1", "8.1", "9.1", "10.1"] },
    { "id": 3, "tasks": ["3.2", "5.2", "5.3", "6.1", "8.2", "8.3", "8.4", "8.5", "9.2", "9.3", "10.2", "12.1"] },
    { "id": 4, "tasks": ["3.3", "3.4", "3.5", "3.6", "3.15", "3.7", "6.2", "6.3", "12.2", "13.1"] },
    { "id": 5, "tasks": ["3.8", "3.9", "3.10", "3.11", "3.12", "3.14", "6.4", "6.5", "6.6", "13.2", "13.5", "13.6", "13.7"] },
    { "id": 6, "tasks": ["3.13", "7.1", "12.3", "13.3", "13.4"] },
    { "id": 7, "tasks": ["7.2", "7.3", "12.4", "12.5", "12.6", "13.8"] },
    { "id": 8, "tasks": ["12.7", "13.9"] },
    { "id": 9, "tasks": ["12.8", "14.1"] },
    { "id": 10, "tasks": ["14.2"] }
  ]
}
```

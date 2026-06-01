# Requirements Document

## Introduction

LifeGraph is a fully local, web-based personal knowledge graph system. It models a person's
life as a network of typed nodes (skills, goals, habits, projects, events, people, resources)
and typed edges (relationships such as `requires`, `supports`, `motivated_by`). Its purpose is
to act as a persistent, structured memory layer that can be serialized into a compact text
snapshot and pasted into any AI conversation.

The user types plain English sentences describing their life. A locally running LLM (via Ollama)
parses each sentence into structured graph data. The graph is stored in a local SQLite database,
rendered interactively in the browser with Vis.js, edited manually through the UI, queried by
type or label, and exported as a context snapshot.

This document defines requirements for the in-scope features only:
1. Natural language input parsed into nodes and edges
2. Interactive graph visualization
3. Manual create/edit/delete of nodes and edges
4. Context export (subgraph serialization to text)
5. Dashboard of active skills, goals, and upcoming events
6. Search and filter by type or label

Out-of-scope items (external AI providers, multi-user authentication, JSON graph import/export,
mobile-optimized UI) are not specified here, but two requirements (modular AI access and
structured JSON interchange) are included so the architecture can accommodate them later without
a rewrite.

### Decided Constraints and Opinionated Defaults

These positions resolve tradeoffs surfaced during requirements analysis. They are stated as
requirements below and summarized here for visibility:

- **Human-in-the-loop parsing.** Because LLM output is non-deterministic, parsed nodes and edges
  are presented for user confirmation before they are written to storage, rather than committed
  automatically.
- **Node deduplication by normalized label + type.** Repeated mentions of the same concept reuse
  one node instead of creating duplicates.
- **Cascade delete.** Deleting a node removes its connected edges to prevent dangling references.
- **Two-table model retained, plus optional node attributes.** Nodes carry an optional key-value
  attributes field (stored in the nodes table) so Event nodes can hold a date, enabling a
  meaningful "upcoming events" view without adding tables.
- **Deterministic, token-budgeted serializer.** Context export traverses a bounded number of hops
  and prioritizes by graph distance so output stays compact and reproducible.

## Glossary

- **LifeGraph_System**: The complete local application, comprising the backend, storage, AI
  integration, and browser UI.
- **Web_Server**: The Python (Flask) process that serves the web UI and exposes HTTP endpoints on
  a localhost port.
- **Graph_API**: The set of backend HTTP endpoints that mediate between the browser UI and the
  Graph_Store, Input_Parser, and Context_Serializer.
- **Input_Parser**: The backend component that converts a natural language sentence into proposed
  structured graph data by way of the Ollama_Client.
- **Ollama_Client**: The backend component that communicates with the locally running Ollama
  service to obtain language-model responses.
- **Graph_Store**: The SQLite-backed persistence layer holding nodes and edges.
- **Graph_View**: The browser component that renders the graph as an interactive Vis.js network.
- **Graph_Editor**: The browser-plus-backend component that performs manual create, edit, and
  delete operations on nodes and edges.
- **Context_Serializer**: The backend component that walks a subgraph and produces a plain-text
  context snapshot.
- **Dashboard**: The browser view summarizing Skill, Goal, and Event nodes.
- **Search_Filter**: The component that restricts the displayed graph by node type or label.
- **Node**: A graph vertex with a unique identifier, a type from the Node_Type_Set, a label, and
  an optional set of key-value attributes.
- **Edge**: A directed graph connection with a unique identifier, a source node identifier, a
  target node identifier, and a type from the Edge_Type_Set.
- **Node_Type_Set**: The fixed set of allowed node types: `Skill`, `Goal`, `Habit`, `Project`,
  `Event`, `Person`, `Resource`.
- **Edge_Type_Set**: The fixed set of allowed edge types: `requires`, `supports`,
  `conflicts_with`, `motivated_by`, `leads_to`, `part_of`, `owned_by`, `blocks`, `related_to`.
- **Normalized label**: A node label after trimming leading and trailing whitespace and applying
  case-insensitive comparison, used for node identity matching.
- **Subgraph**: A connected set of nodes and edges reachable from a selected node within a bounded
  hop distance.
- **Hop distance**: The number of edges traversed from a selected node when building a subgraph.
- **Context snapshot**: The plain-text output of the Context_Serializer.

## Requirements

### Requirement 1: Fully Local and Offline Operation

**User Story:** As a privacy-conscious user, I want the system to run entirely on my machine without accounts or cloud calls, so that my personal data never leaves my device and the app works offline.

#### Acceptance Criteria

1. THE LifeGraph_System SHALL start and provide all features without requiring any external API key, third-party account, or sign-in credential.
2. THE LifeGraph_System SHALL restrict all outbound network communication to the loopback (localhost) interface, connecting only to the locally running Web_Server and Ollama service.
3. WHILE the host machine has no internet connection, THE LifeGraph_System SHALL provide natural language input parsing, graph viewing, manual editing, context export, the dashboard, and search and filter using only locally running processes.
4. IF any component attempts a network connection to a non-loopback address, THEN THE LifeGraph_System SHALL block the connection, retain all user data locally without transmitting it externally, and surface an indication that an external connection was prevented.
5. THE LifeGraph_System SHALL store all persistent data of the Graph_Store in a single local SQLite database file.

### Requirement 2: Web Server and Runnability

**User Story:** As an open-source user, I want to launch the app with only Python and Ollama installed, so that I can run it without complex setup.

#### Acceptance Criteria

1. WHEN the user starts the backend process AND all critical startup conditions are satisfied, THE Web_Server SHALL serve the web UI over HTTP on the configured localhost port, applying the documented default port when none is configured.
2. WHEN a browser requests the application root, THE Web_Server SHALL return an HTML page that loads the Vis.js library and the application JavaScript.
3. THE Web_Server SHALL depend only on a Python runtime, the project's declared Python dependencies, and a running Ollama service.
4. IF a declared Python dependency is missing at startup, THEN THE Web_Server SHALL stop startup, emit an error message that names the missing dependency, and serve no HTTP request.
5. IF the configured localhost port is already in use at startup, THEN THE Web_Server SHALL stop startup, emit an error message that names the conflicting port, and not bind the port.
6. IF any critical startup condition fails, including a missing dependency, an unavailable port, an unreachable Ollama service, or an invalid configuration value, THEN THE Web_Server SHALL stop startup, emit an error message that identifies the failed condition, and serve no HTTP request.

### Requirement 3: Natural Language Input Parsing

**User Story:** As a user, I want to type plain English sentences about my life and have them converted into typed nodes and edges, so that I can build my graph quickly.

#### Acceptance Criteria

1. WHEN the user submits a natural language sentence of 1 to 1000 characters, THE Input_Parser SHALL send the sentence to the Ollama_Client and request structured graph data.
2. WHEN the Ollama_Client returns a response, THE Input_Parser SHALL produce proposed graph data consisting of 0 to 100 nodes and 0 to 200 edges, where each node has a type from the Node_Type_Set and each edge has a type from the Edge_Type_Set.
3. IF the response contains a node type absent from the Node_Type_Set or an edge type absent from the Edge_Type_Set, THEN THE Input_Parser SHALL reject the offending element and report a validation error that identifies the invalid type.
4. IF the response cannot be parsed into nodes and edges, THEN THE Input_Parser SHALL return a descriptive error and SHALL leave the Graph_Store unchanged.
5. WHEN the Input_Parser produces proposed graph data, THE Graph_API SHALL present the proposed nodes and edges to the user for confirmation before any write to the Graph_Store.
6. WHEN the user confirms the proposed graph data, THE Graph_Store SHALL persist the confirmed nodes and edges.
7. WHEN the user rejects the proposed graph data, THE Graph_Store SHALL not apply any write originating from that rejected proposal, while remaining available to other operations.
8. IF the submitted input is empty, contains only whitespace, or exceeds 1000 characters, THEN THE Input_Parser SHALL reject the input without contacting the Ollama_Client and SHALL leave the Graph_Store unchanged.
9. IF a parse request to the Ollama_Client exceeds the configured request timeout, THEN THE Input_Parser SHALL return a timeout error and SHALL leave the Graph_Store unchanged.
10. IF the Ollama_Client is unavailable or returns an error response, THEN THE Input_Parser SHALL return a descriptive error and SHALL leave the Graph_Store unchanged.

### Requirement 4: Node Identity and Deduplication

**User Story:** As a user, I want repeated mentions of the same thing to map to a single node, so that my graph stays coherent instead of accumulating duplicates.

#### Acceptance Criteria

1. THE Graph_Store SHALL assign each node an identifier that is unique among all nodes, that remains stable across edits to that node's label, type, or attributes, and that is not reused for any other node after the original node is deleted.
2. WHEN a node to be created has the same normalized label and the same type as an existing node, THE Graph_Store SHALL reuse the existing node, SHALL retain that existing node's identifier and stored label, and SHALL keep that existing node's current attributes unchanged.
3. WHEN a node to be created has no existing node sharing both its normalized label and its type, THE Graph_Store SHALL create a new node with a new unique identifier.
4. WHEN an edge references a node for which no existing node shares both the referenced normalized label and type, THE Graph_Store SHALL create the referenced node before creating the edge; otherwise THE Graph_Store SHALL reference the existing matching node.
5. THE Graph_Store SHALL treat two nodes as the same node when their labels are equal after trimming leading and trailing whitespace and applying case-insensitive comparison AND their types are identical values from the Node_Type_Set.

### Requirement 5: Graph Storage Schema

**User Story:** As a user, I want my graph stored durably in SQLite, so that my memory layer persists across restarts.

#### Acceptance Criteria

1. THE Graph_Store SHALL persist nodes in a nodes table and edges in an edges table within a single SQLite database file.
2. THE Graph_Store SHALL store for each node a unique identifier, a type from the Node_Type_Set, a label of 1 to 200 characters, and an optional set of up to 50 key-value attributes whose keys and values are each at most 500 characters.
3. THE Graph_Store SHALL store for each edge a unique identifier, a source node identifier, a target node identifier, and a type from the Edge_Type_Set.
4. IF an edge is created whose source node identifier or target node identifier is absent from the nodes table, THEN THE Graph_Store SHALL reject the edge, report a referential integrity error that identifies the missing node identifier, and leave the nodes table and edges table unchanged.
5. WHEN a node is deleted, THE Graph_Store SHALL delete every edge whose source or target is that node.
6. WHEN the backend restarts, THE Graph_Store SHALL load a node set and edge set equal to the previously persisted node set and edge set, with each node's and edge's stored fields retained.
7. WHEN the backend starts and no database file exists at the configured path, THE Graph_Store SHALL create a new database file with an empty nodes table and an empty edges table.
8. IF the database file at the configured path cannot be read or is not a valid Graph_Store database at startup, THEN THE Web_Server SHALL stop startup, report the storage error, and not overwrite the existing database file.

### Requirement 6: Node Attributes

**User Story:** As a user, I want certain nodes to carry extra detail such as an event date, so that the dashboard and exports can reflect time-sensitive information.

#### Acceptance Criteria

1. THE Graph_Store SHALL support an optional set of up to 50 key-value attributes for each node, stored within the nodes table, where each key and each value is 1 to 255 characters.
2. WHERE a node has type `Event`, THE Graph_Editor SHALL accept an optional `date` attribute expressed as an ISO 8601 calendar date in `YYYY-MM-DD` format and SHALL store the accepted value as that node's `date` attribute.
3. IF a node's `date` attribute is present and is not a valid `YYYY-MM-DD` date, where valid means both the `YYYY-MM-DD` format and a real calendar date with a valid month and day, THEN THE Graph_Editor SHALL reject the value, report the required format, and leave the node's previously stored attributes unchanged.
4. WHEN a node's attributes are edited, THE Graph_Store SHALL persist the updated attributes against that node's unique identifier before the Graph_Editor reports the edit as complete.
5. IF the Graph_Store is unavailable when a node's attributes are edited, THEN THE Graph_Editor SHALL not complete the edit, SHALL retain the node's previously stored attributes, and SHALL report the failure to the user.

### Requirement 7: Interactive Graph Visualization

**User Story:** As a user, I want to see my life graph rendered visually, so that I can understand how my skills, goals, and projects connect.

#### Acceptance Criteria

1. WHEN the web UI loads, THE Graph_View SHALL render all nodes and edges from the Graph_Store as an interactive Vis.js network.
2. THE Graph_View SHALL display each node with its label.
3. THE Graph_View SHALL display each edge with a label that indicates the edge type.
4. WHEN the user selects a node, THE Graph_View SHALL visually distinguish the selected node and its directly connected edges from all unselected nodes and edges.
5. WHEN the Graph_Store contents change through a create, edit, or delete operation, THE Graph_View SHALL update the rendered network to match the current Graph_Store contents.
6. WHILE the Graph_Store contains at least one node and up to 500 nodes and 1000 edges, THE Graph_View SHALL complete the initial render within 3 seconds on the reference development machine.
7. THE Graph_View SHALL render each node with a visual style that is distinct for each type in the Node_Type_Set.
8. WHEN the web UI loads and the Graph_Store contains no nodes, THE Graph_View SHALL render an empty network without error.
9. IF the Graph_View cannot fetch the graph data when the web UI loads, THEN THE Graph_View SHALL surface an error indication to the user and SHALL render no partial network.

### Requirement 8: Manual Node Management

**User Story:** As a user, I want to add, edit, and delete nodes manually, so that I can correct or extend the graph without natural language input.

#### Acceptance Criteria

1. WHEN the user submits a new node with a label of 1 to 100 characters after trimming whitespace and a type from the Node_Type_Set, THE Graph_Editor SHALL create the node in the Graph_Store.
2. WHEN the user edits an existing node's label, type, or attributes, THE Graph_Editor SHALL update that node in the Graph_Store.
3. IF the user submits a node with a type absent from the Node_Type_Set, THEN THE Graph_Editor SHALL reject the submission, report the allowed node types, and retain the submitted values for correction without modifying the Graph_Store.
4. IF the user submits a node whose label is empty or contains only whitespace after trimming, THEN THE Graph_Editor SHALL reject the submission, report that a label is required, and retain the submitted values for correction without modifying the Graph_Store.
5. IF the user submits a node whose label exceeds 100 characters after trimming whitespace, THEN THE Graph_Editor SHALL reject the submission, report the maximum allowed label length, and retain the submitted values for correction without modifying the Graph_Store.
6. WHEN the user deletes a node, THE Graph_Editor SHALL remove the node and its connected edges from the Graph_Store.
7. IF a node to be deleted has 5 or more connected edges, THEN THE Graph_Editor SHALL warn the user of the number of edges that will be removed and SHALL require user confirmation before deleting the node.
8. WHEN the user cancels the confirmation for deleting a node, THE Graph_Editor SHALL retain the node and its connected edges in the Graph_Store unchanged.

### Requirement 9: Manual Edge Management

**User Story:** As a user, I want to add, edit, and delete relationships between nodes manually, so that I can model connections precisely.

#### Acceptance Criteria

1. WHEN the user creates an edge by selecting a source node, a target node, and a type from the Edge_Type_Set, THE Graph_Editor SHALL create the edge in the Graph_Store.
2. WHEN the user edits an existing edge's type, THE Graph_Editor SHALL update that edge in the Graph_Store.
3. IF the user submits an edge with a type absent from the Edge_Type_Set, THEN THE Graph_Editor SHALL reject the submission and report the allowed edge types.
4. IF the user creates an edge whose source node and target node are the same node, THEN THE Graph_Editor SHALL reject the submission and report that self-referential edges are not permitted.
5. WHEN the user deletes an edge, THE Graph_Editor SHALL remove the edge from the Graph_Store while leaving its source and target nodes intact.

### Requirement 10: Context Export Serializer

**User Story:** As a user, I want to export a compact text snapshot of a relevant part of my graph, so that I can paste it into an AI conversation as structured memory.

#### Acceptance Criteria

1. WHEN the user requests a context export for a selected node, THE Context_Serializer SHALL produce a context snapshot describing the selected node and its subgraph.
2. THE Context_Serializer SHALL include in the context snapshot each included node's type and label and each included edge's type, source, and target.
3. THE Context_Serializer SHALL build the subgraph by traversing outward from the selected node up to a configured maximum hop distance, defaulting to 2 hops.
4. WHERE the subgraph exceeds the configured maximum size in nodes or characters, THE Context_Serializer SHALL retain nodes in ascending order of hop distance from the selected node and omit the most distant nodes.
5. WHEN invoked twice with the same Graph_Store state and the same selection parameters, THE Context_Serializer SHALL produce identical context snapshots.
6. THE Context_Serializer SHALL produce the context snapshot as plain text suitable for pasting into a text-based AI conversation.

### Requirement 11: Structured JSON Interchange

**User Story:** As a maintainer, I want the graph exchanged between backend and browser as structured JSON, so that the visual view stays faithful to stored data and a future import/export feature can reuse the format.

#### Acceptance Criteria

1. WHEN the Graph_API responds to a graph-fetch request, THE Graph_API SHALL serialize the current nodes and edges into a structured JSON document.
2. THE JSON document SHALL represent every node in the Graph_Store with its identifier, type, label, and attributes, and every edge with its identifier, source, target, and type.
3. WHEN the JSON document produced by the Graph_API is deserialized, THE resulting node set and edge set SHALL be equivalent to the Graph_Store contents at the time of serialization (round-trip property).

### Requirement 12: Dashboard

**User Story:** As a user, I want a dashboard summarizing my active skills, goals, and upcoming events, so that I get an at-a-glance overview of my life graph.

#### Acceptance Criteria

1. WHEN the user opens the dashboard, THE Dashboard SHALL display all nodes of type `Skill` and all nodes of type `Goal`.
2. WHEN the user opens the dashboard, THE Dashboard SHALL display all nodes of type `Event` whose `date` attribute is the current date or a later date, ordered by `date` in ascending order, and SHALL display an event dated the current date regardless of the time of day.
3. WHERE an `Event` node has no `date` attribute, THE Dashboard SHALL display that node in a separate undated-events group.
4. WHEN the Graph_Store contents change, THE Dashboard SHALL reflect the current Skill, Goal, and Event nodes on its next load.

### Requirement 13: Search and Filter

**User Story:** As a user, I want to search and filter nodes by type or label, so that I can find relevant parts of a large graph.

#### Acceptance Criteria

1. WHEN the user selects one or more node types as a filter, THE Search_Filter SHALL display only nodes whose type is in the selected set together with the edges connecting those nodes.
2. WHEN the user enters a label search term, THE Search_Filter SHALL display only nodes whose label contains the search term using case-insensitive matching.
3. WHILE both a type filter and a label search term are active, THE Search_Filter SHALL display only nodes that satisfy both conditions, regardless of the order in which the two filters were set.
4. WHEN the user clears all filters and search terms, THE Search_Filter SHALL display all nodes and edges.
5. WHEN a filter or search term is applied or cleared, THE Graph_View SHALL render the resulting set of nodes and edges.

### Requirement 14: Ollama Integration and Error Handling

**User Story:** As a user, I want clear feedback when the local model is unavailable or slow, so that I know how to fix the problem.

#### Acceptance Criteria

1. IF the Ollama service is not reachable when the Input_Parser submits a sentence, THEN THE Ollama_Client SHALL return an error stating that Ollama is unavailable and SHALL leave the Graph_Store unchanged.
2. IF the configured Ollama model is not installed, THEN THE Ollama_Client SHALL return an error that identifies the missing model.
3. WHILE the Input_Parser is awaiting a response from the Ollama_Client, THE Graph_API SHALL indicate to the user that parsing is in progress.
4. IF a parse request exceeds the configured request timeout, defaulting to 60 seconds, THEN THE Ollama_Client SHALL abort the request and return a timeout error.

### Requirement 15: Configuration

**User Story:** As an open-source user, I want to configure the model, port, and storage location, so that I can adapt the app to my environment.

#### Acceptance Criteria

1. THE LifeGraph_System SHALL read configuration values for the Ollama model name, the Web_Server localhost port, the SQLite database file path, the default context export hop distance, and the Ollama request timeout.
2. WHERE a configuration value is not provided, THE LifeGraph_System SHALL apply a documented default value for that setting.
3. IF a provided configuration value is invalid for its setting, THEN THE LifeGraph_System SHALL stop startup and report which configuration value is invalid.

### Requirement 16: Modular AI Access (Future-Proofing)

**User Story:** As a maintainer, I want all language-model access confined to one component, so that an external AI provider can be added later without rewriting the core.

#### Acceptance Criteria

1. THE Input_Parser SHALL obtain language-model responses exclusively through the Ollama_Client.
2. THE LifeGraph_System SHALL confine all language-model communication to the Ollama_Client component.
3. THE Ollama_Client SHALL expose a single defined interface for submitting a sentence and receiving structured graph data.

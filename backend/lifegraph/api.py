"""Graph_API — Flask transport layer for LifeGraph.

Creates the Flask application, registers error handlers that map domain errors
to HTTP status codes with a standard error envelope, provides JSON serialization
of nodes/edges, and implements the core endpoints.

Error envelope: {"error": {"code": <string>, "message": <string>, "details": <object?>}}

Error mapping:
    ValidationError / LabelValidationError / DateValidationError /
        AttributeValidationError → 400
    InputValidationError → 400
    StorageError → 500
    OllamaUnavailableError → 502
    OllamaTimeoutError → 504
    ExternalConnectionError → 403
    404 → not found

Requirements: 2.2, 7.1, 11.1, 11.2
"""

from __future__ import annotations

from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

from lifegraph.config import DEFAULT_DB_PATH, load_config
from lifegraph.dashboard import aggregate_dashboard
from lifegraph.domain import (
    Edge,
    EdgeType,
    Graph,
    Node,
    NodeType,
    ProposedGraph,
    ProposedEdge,
    ProposedNode,
    EDGE_TYPE_VALUES,
    NODE_TYPE_VALUES,
)
from lifegraph.ollama_client import (
    ExternalConnectionError,
    OllamaClient,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from lifegraph.parser import InputParser, InputValidationError, InvalidTypeError, UnparseableResponse
from lifegraph.search import filter_graph
from lifegraph.serializer import ContextSerializer
from lifegraph.store import (
    EdgeNotFoundError,
    GraphStore,
    NodeNotFoundError,
    ReferentialIntegrityError,
    SelfEdgeError,
    StorageError,
)
from lifegraph.validation import (
    AttributeValidationError,
    DateValidationError,
    LabelValidationError,
    ValidationError,
    validate_manual_label,
)


# ---------------------------------------------------------------------------
# JSON serialization helpers
# ---------------------------------------------------------------------------


def serialize_node(node: Node) -> Dict[str, Any]:
    """Serialize a Node to a JSON-compatible dict.

    Returns: {"id": ..., "type": ..., "label": ..., "attributes": {...}}
    """
    return {
        "id": node.id,
        "type": node.type.value,
        "label": node.label,
        "attributes": node.attributes,
    }


def serialize_edge(edge: Edge) -> Dict[str, Any]:
    """Serialize an Edge to a JSON-compatible dict.

    Returns: {"id": ..., "source": ..., "target": ..., "type": ...}
    """
    return {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "type": edge.type.value,
    }


def serialize_graph(graph: Graph) -> Dict[str, Any]:
    """Serialize a Graph to a JSON-compatible dict.

    Returns: {"nodes": [...], "edges": [...]}
    """
    return {
        "nodes": [serialize_node(n) for n in graph.nodes],
        "edges": [serialize_edge(e) for e in graph.edges],
    }


# ---------------------------------------------------------------------------
# Error envelope helper
# ---------------------------------------------------------------------------


def error_envelope(
    code: str, message: str, details: Any = None
) -> Dict[str, Any]:
    """Build the standard error response envelope.

    Returns: {"error": {"code": code, "message": message, "details": details}}
    """
    envelope: Dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details is not None:
        envelope["error"]["details"] = details
    return envelope


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(config: Dict[str, Any] | None = None) -> Flask:
    """Create and configure the Flask application.

    Parameters
    ----------
    config : dict or None
        Optional configuration overrides. Recognized keys:
        - "db_path": path to the SQLite database file
        - "TESTING": enable Flask test mode
        - "parser": an InputParser instance (for testing/injection)
        - "lifegraph_config": a LifeGraphConfig instance
        Any other keys are passed to Flask's config.

    Returns
    -------
    Flask
        The configured Flask application with error handlers and routes.
    """
    app = Flask(__name__)

    # Apply configuration
    if config:
        app.config.update(config)

    # Determine database path
    db_path = (config or {}).get("db_path", DEFAULT_DB_PATH)

    # Create the GraphStore instance and attach to app
    store = GraphStore(db_path)
    app.config["STORE"] = store

    # Load or use provided LifeGraph config
    lg_config = (config or {}).get("lifegraph_config")
    if lg_config is None:
        try:
            lg_config = load_config()
        except Exception:
            lg_config = None
    app.config["LIFEGRAPH_CONFIG"] = lg_config

    # Create or use provided InputParser
    parser = (config or {}).get("parser")
    if parser is None and lg_config is not None:
        ollama_url = f"http://127.0.0.1:11434"
        ollama = OllamaClient(
            base_url=ollama_url,
            model=lg_config.model,
            timeout_seconds=lg_config.timeout,
        )
        parser = InputParser(ollama)
    app.config["PARSER"] = parser

    # No pending proposal initially
    app.config["PENDING_PROPOSAL"] = None

    # Register error handlers
    _register_error_handlers(app)

    # Register routes
    _register_routes(app)

    return app


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


def _register_error_handlers(app: Flask) -> None:
    """Register domain-error → HTTP-status error handlers."""

    @app.errorhandler(LabelValidationError)
    def handle_label_validation(exc: LabelValidationError):
        return jsonify(error_envelope("LABEL_VALIDATION_ERROR", str(exc))), 400

    @app.errorhandler(DateValidationError)
    def handle_date_validation(exc: DateValidationError):
        return jsonify(error_envelope("DATE_VALIDATION_ERROR", str(exc))), 400

    @app.errorhandler(AttributeValidationError)
    def handle_attribute_validation(exc: AttributeValidationError):
        return jsonify(error_envelope("ATTRIBUTE_VALIDATION_ERROR", str(exc))), 400

    @app.errorhandler(ValidationError)
    def handle_validation(exc: ValidationError):
        return jsonify(error_envelope("VALIDATION_ERROR", str(exc))), 400

    @app.errorhandler(NodeNotFoundError)
    def handle_node_not_found(exc: NodeNotFoundError):
        return jsonify(error_envelope("NOT_FOUND", str(exc))), 404

    @app.errorhandler(EdgeNotFoundError)
    def handle_edge_not_found(exc: EdgeNotFoundError):
        return jsonify(error_envelope("NOT_FOUND", str(exc))), 404

    @app.errorhandler(ReferentialIntegrityError)
    def handle_referential_integrity(exc: ReferentialIntegrityError):
        return (
            jsonify(
                error_envelope(
                    "REFERENTIAL_INTEGRITY_ERROR",
                    str(exc),
                    {"missing_id": exc.missing_id},
                )
            ),
            409,
        )

    @app.errorhandler(SelfEdgeError)
    def handle_self_edge(exc: SelfEdgeError):
        return jsonify(error_envelope("SELF_EDGE_ERROR", str(exc))), 422

    @app.errorhandler(StorageError)
    def handle_storage(exc: StorageError):
        return jsonify(error_envelope("STORAGE_ERROR", str(exc))), 500

    @app.errorhandler(InputValidationError)
    def handle_input_validation(exc: InputValidationError):
        return jsonify(error_envelope("INPUT_VALIDATION_ERROR", str(exc))), 400

    @app.errorhandler(InvalidTypeError)
    def handle_invalid_type(exc: InvalidTypeError):
        return jsonify(error_envelope("INVALID_TYPE_ERROR", str(exc))), 422

    @app.errorhandler(UnparseableResponse)
    def handle_unparseable(exc: UnparseableResponse):
        return jsonify(error_envelope("UNPARSEABLE_RESPONSE", str(exc))), 422

    @app.errorhandler(OllamaUnavailableError)
    def handle_ollama_unavailable(exc: OllamaUnavailableError):
        return jsonify(error_envelope("OLLAMA_UNAVAILABLE", str(exc))), 502

    @app.errorhandler(OllamaTimeoutError)
    def handle_ollama_timeout(exc: OllamaTimeoutError):
        return jsonify(error_envelope("OLLAMA_TIMEOUT", str(exc))), 504

    @app.errorhandler(ExternalConnectionError)
    def handle_external_connection(exc: ExternalConnectionError):
        return jsonify(error_envelope("EXTERNAL_CONNECTION_BLOCKED", str(exc))), 403

    @app.errorhandler(404)
    def handle_not_found(exc):
        return jsonify(error_envelope("NOT_FOUND", "The requested resource was not found.")), 404


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _register_routes(app: Flask) -> None:
    """Register the application routes."""

    @app.route("/")
    def index():
        """Serve the HTML page that loads Vis.js and app JS (Req 2.2)."""
        return render_template("index.html")

    @app.route("/api/graph")
    def get_graph():
        """Fetch the full graph as JSON (Req 7.1, 11.1, 11.2).

        Returns: {"nodes": [...], "edges": [...]}
        """
        store: GraphStore = app.config["STORE"]
        graph = store.get_graph()
        return jsonify(serialize_graph(graph))

    # -------------------------------------------------------------------
    # Node endpoints (Req 8.1, 8.2, 8.3, 8.4, 8.5, 8.6)
    # -------------------------------------------------------------------

    @app.route("/api/nodes", methods=["POST"])
    def create_node():
        """Create a node manually (Req 8.1).

        Request body: {"label": str, "type": str, "attributes": {...}?}
        Returns: 201 with the created node JSON.
        Errors: 400 if label or type is invalid.
        """
        store: GraphStore = app.config["STORE"]
        body = request.get_json(force=True)

        label_raw = body.get("label", "")
        type_raw = body.get("type", "")
        attributes = body.get("attributes", None)

        # Validate manual label (trimmed 1–100 chars)
        label = validate_manual_label(label_raw)

        # Validate node type
        if type_raw not in NODE_TYPE_VALUES:
            raise ValidationError(
                f"Invalid node type '{type_raw}'. "
                f"Allowed types: {sorted(NODE_TYPE_VALUES)}"
            )

        node_type = NodeType(type_raw)
        node = store.upsert_node(label, node_type, attributes=attributes)
        return jsonify(serialize_node(node)), 201

    @app.route("/api/nodes/<node_id>", methods=["PUT"])
    def update_node(node_id: str):
        """Edit a node's label, type, or attributes (Req 8.2).

        Request body: {"label": str?, "type": str?, "attributes": {...}?}
        Returns: 200 with the updated node JSON.
        Errors: 400 validation, 404 not found.
        """
        store: GraphStore = app.config["STORE"]
        body = request.get_json(force=True)

        kwargs: Dict[str, Any] = {}

        if "label" in body:
            # Validate manual label (trimmed 1–100 chars)
            kwargs["label"] = validate_manual_label(body["label"])

        if "type" in body:
            type_raw = body["type"]
            if type_raw not in NODE_TYPE_VALUES:
                raise ValidationError(
                    f"Invalid node type '{type_raw}'. "
                    f"Allowed types: {sorted(NODE_TYPE_VALUES)}"
                )
            kwargs["type"] = NodeType(type_raw)

        if "attributes" in body:
            kwargs["attributes"] = body["attributes"]

        node = store.update_node(node_id, **kwargs)
        return jsonify(serialize_node(node)), 200

    @app.route("/api/nodes/<node_id>", methods=["DELETE"])
    def delete_node(node_id: str):
        """Delete a node and cascade-delete its edges (Req 8.6).

        Returns: 200 with {"deletedEdgeIds": [...]}
        Errors: 404 not found.
        """
        store: GraphStore = app.config["STORE"]
        deleted_edge_ids = store.delete_node(node_id)
        return jsonify({"deletedEdgeIds": deleted_edge_ids}), 200

    @app.route("/api/nodes/<node_id>/edges", methods=["GET"])
    def get_node_edges(node_id: str):
        """Get incident edge count for a node (drives delete warning, Req 8.7).

        Returns: 200 with {"count": int}
        Errors: 404 not found.
        """
        store: GraphStore = app.config["STORE"]
        # Verify node exists
        node = store.get_node(node_id)
        if node is None:
            raise NodeNotFoundError(node_id)
        edges = store.incident_edges(node_id)
        return jsonify({"count": len(edges)}), 200

    # -------------------------------------------------------------------
    # Edge endpoints (Req 9.1, 9.2, 9.3, 9.4, 9.5)
    # -------------------------------------------------------------------

    @app.route("/api/edges", methods=["POST"])
    def create_edge():
        """Create an edge (Req 9.1).

        Request body: {"source": str, "target": str, "type": str}
        Returns: 201 with the created edge JSON.
        Errors: 400 type invalid, 409 referential integrity, 422 self-edge.
        """
        store: GraphStore = app.config["STORE"]
        body = request.get_json(force=True)

        source_id = body.get("source", "")
        target_id = body.get("target", "")
        type_raw = body.get("type", "")

        # Validate edge type
        if type_raw not in EDGE_TYPE_VALUES:
            raise ValidationError(
                f"Invalid edge type '{type_raw}'. "
                f"Allowed types: {sorted(EDGE_TYPE_VALUES)}"
            )

        edge_type = EdgeType(type_raw)
        edge = store.create_edge(source_id, target_id, edge_type)
        return jsonify(serialize_edge(edge)), 201

    @app.route("/api/edges/<edge_id>", methods=["PUT"])
    def update_edge(edge_id: str):
        """Edit an edge's type (Req 9.2).

        Request body: {"type": str}
        Returns: 200 with the updated edge JSON.
        Errors: 400 type invalid, 404 not found.
        """
        store: GraphStore = app.config["STORE"]
        body = request.get_json(force=True)

        type_raw = body.get("type", "")

        # Validate edge type
        if type_raw not in EDGE_TYPE_VALUES:
            raise ValidationError(
                f"Invalid edge type '{type_raw}'. "
                f"Allowed types: {sorted(EDGE_TYPE_VALUES)}"
            )

        edge_type = EdgeType(type_raw)
        edge = store.update_edge(edge_id, edge_type)
        return jsonify(serialize_edge(edge)), 200

    @app.route("/api/edges/<edge_id>", methods=["DELETE"])
    def delete_edge(edge_id: str):
        """Delete an edge, keeping its endpoints (Req 9.5).

        Returns: 204 No Content.
        Errors: 404 not found.
        """
        store: GraphStore = app.config["STORE"]
        store.delete_edge(edge_id)
        return "", 204

    # -------------------------------------------------------------------
    # Parse / Confirm / Reject endpoints (Req 3.5, 3.6, 3.7, 14.3)
    # -------------------------------------------------------------------

    @app.route("/api/parse", methods=["POST"])
    def parse_sentence_endpoint():
        """Parse a natural-language sentence into a proposal (Req 3.5).

        Request body: {"sentence": str}
        Returns: 200 with the proposed graph JSON (nodes/edges).
        Errors: 400 input validation, 422 unparseable/invalid type,
                502 Ollama unavailable, 504 Ollama timeout.
        """
        parser: InputParser = app.config["PARSER"]
        body = request.get_json(force=True)

        sentence = body.get("sentence", "")
        proposed = parser.parse(sentence)

        # Store the pending proposal in app state for confirm/reject
        app.config["PENDING_PROPOSAL"] = proposed

        # Serialize the proposal for the client preview
        result = {
            "nodes": [
                {"label": n.label, "type": n.type.value, "attributes": n.attributes}
                for n in proposed.nodes
            ],
            "edges": [
                {
                    "source_label": e.source_label,
                    "source_type": e.source_type.value,
                    "target_label": e.target_label,
                    "target_type": e.target_type.value,
                    "type": e.type.value,
                }
                for e in proposed.edges
            ],
        }
        return jsonify(result), 200

    @app.route("/api/parse/confirm", methods=["POST"])
    def confirm_proposal():
        """Confirm and persist the pending proposal (Req 3.6).

        Applies the last parsed proposal to the store. The proposal is
        presented before any write occurs (Req 3.5).

        Returns: 200 with the resulting graph fragment (created/resolved nodes+edges).
        Errors: 400 if no pending proposal exists.
        """
        store: GraphStore = app.config["STORE"]
        pending = app.config.get("PENDING_PROPOSAL")

        if pending is None:
            return (
                jsonify(error_envelope("NO_PENDING_PROPOSAL", "No proposal to confirm.")),
                400,
            )

        result = store.apply_proposal(pending)
        app.config["PENDING_PROPOSAL"] = None

        return jsonify(serialize_graph(result)), 200

    @app.route("/api/parse/reject", methods=["POST"])
    def reject_proposal():
        """Reject the pending proposal — no write occurs (Req 3.7).

        Returns: 204 No Content.
        """
        app.config["PENDING_PROPOSAL"] = None
        return "", 204

    # -------------------------------------------------------------------
    # Dashboard, Context, and Search endpoints (Req 10.1, 12.1, 13.5)
    # -------------------------------------------------------------------

    @app.route("/api/dashboard", methods=["GET"])
    def get_dashboard():
        """Fetch dashboard data: skills, goals, upcoming/undated events (Req 12.1).

        Returns: 200 with {"skills": [...], "goals": [...],
                 "upcomingEvents": [...], "undatedEvents": [...]}
        """
        store: GraphStore = app.config["STORE"]
        graph = store.get_graph()
        data = aggregate_dashboard(graph)

        return jsonify({
            "skills": [serialize_node(n) for n in data.skills],
            "goals": [serialize_node(n) for n in data.goals],
            "upcomingEvents": [serialize_node(n) for n in data.upcoming_events],
            "undatedEvents": [serialize_node(n) for n in data.undated_events],
        }), 200

    @app.route("/api/context", methods=["POST"])
    def get_context():
        """Get a context snapshot for a given node (Req 10.1).

        Request body: {"node_id": str}
        Returns: 200 with {"snapshot": str}
        Errors: 400 if node_id missing, ValueError if node not found.
        """
        store: GraphStore = app.config["STORE"]
        body = request.get_json(force=True)

        node_id = body.get("node_id", "")
        if not node_id:
            return (
                jsonify(error_envelope("VALIDATION_ERROR", "node_id is required.")),
                400,
            )

        graph = store.get_graph()

        # Use configured hop distance or default
        config = app.config.get("LIFEGRAPH_CONFIG")
        max_hops = config.hop_distance if config else 2

        serializer = ContextSerializer(max_hops=max_hops)
        try:
            snapshot = serializer.serialize(graph, node_id)
        except ValueError as exc:
            return (
                jsonify(error_envelope("NOT_FOUND", str(exc))),
                404,
            )

        return jsonify({"snapshot": snapshot}), 200

    @app.route("/api/search", methods=["GET"])
    def search_graph_endpoint():
        """Search/filter the graph by type and/or label term (Req 13.5).

        Query params:
            types (repeated) - Node types to include
            q - Case-insensitive label search term

        Returns: 200 with {"nodes": [...], "edges": [...]}
        """
        store: GraphStore = app.config["STORE"]
        graph = store.get_graph()

        # Parse query parameters
        type_strs = request.args.getlist("types")
        term = request.args.get("q", "").strip()

        # Convert type strings to NodeType enum values (ignore invalid ones)
        types_set: set[NodeType] | None = None
        if type_strs:
            valid_types = set()
            for t in type_strs:
                if t in NODE_TYPE_VALUES:
                    valid_types.add(NodeType(t))
            if valid_types:
                types_set = valid_types

        filtered = filter_graph(
            graph,
            types=types_set,
            term=term if term else None,
        )

        return jsonify(serialize_graph(filtered)), 200

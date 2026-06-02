"""Tests for the Graph_API: app factory, error mapping, JSON serialization, and graph fetch.

Covers Requirements 2.2, 7.1, 11.1, 11.2.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from lifegraph.api import (
    create_app,
    error_envelope,
    serialize_edge,
    serialize_graph,
    serialize_node,
)
from lifegraph.domain import Edge, EdgeType, Graph, Node, NodeType, ProposedGraph, ProposedNode
from lifegraph.parser import InputParser
from lifegraph.ollama_client import (
    ExternalConnectionError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from lifegraph.store import StorageError
from lifegraph.validation import (
    AttributeValidationError,
    DateValidationError,
    LabelValidationError,
    ValidationError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    """Return a path to a temporary database file."""
    return str(tmp_path / "test.db")


@pytest.fixture
def app(tmp_db: str):
    """Create a Flask app configured for testing."""
    application = create_app({"db_path": tmp_db, "TESTING": True})
    return application


@pytest.fixture
def client(app):
    """Create a Flask test client."""
    return app.test_client()


class FakeOllama:
    def parse_sentence(self, sentence: str) -> dict:
        return {"nodes": [], "edges": []}


def _seed_store(app) -> None:
    """Insert test data into the store via direct SQL."""
    store = app.config["STORE"]
    conn = store._connection
    conn.execute(
        "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
        ("n1", "Skill", "Python", "python", "{}"),
    )
    conn.execute(
        "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
        ("n2", "Goal", "Learn Flask", "learn flask", '{"priority": "high"}'),
    )
    conn.execute(
        "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
        ("n3", "Event", "Conference", "conference", '{"date": "2025-09-15"}'),
    )
    conn.execute(
        "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
        ("e1", "n1", "n2", "supports"),
    )
    conn.execute(
        "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
        ("e2", "n2", "n3", "leads_to"),
    )


# ---------------------------------------------------------------------------
# App factory tests
# ---------------------------------------------------------------------------


class TestCreateApp:
    """Tests for the create_app factory."""

    def test_creates_flask_app(self, tmp_db: str) -> None:
        """create_app returns a Flask application."""
        from flask import Flask

        app = create_app({"db_path": tmp_db})
        assert isinstance(app, Flask)

    def test_store_is_attached(self, app) -> None:
        """The GraphStore is attached to app.config['STORE']."""
        from lifegraph.store import GraphStore

        assert "STORE" in app.config
        assert isinstance(app.config["STORE"], GraphStore)

    def test_testing_mode(self, app) -> None:
        """TESTING flag is passed through to Flask config."""
        assert app.config["TESTING"] is True

    def test_default_db_path_used_when_not_provided(self, tmp_path: Path, monkeypatch) -> None:
        """When no db_path is provided, the default is used."""
        # Change to tmp_path so the default db is created there
        monkeypatch.chdir(tmp_path)
        app = create_app({"TESTING": True})
        assert "STORE" in app.config


# ---------------------------------------------------------------------------
# JSON serialization tests
# ---------------------------------------------------------------------------


class TestSerializeNode:
    """Tests for serialize_node."""

    def test_basic_node(self) -> None:
        """A node serializes to {id, type, label, attributes}."""
        node = Node(id="n1", type=NodeType.SKILL, label="Python", attributes={})
        result = serialize_node(node)
        assert result == {
            "id": "n1",
            "type": "Skill",
            "label": "Python",
            "attributes": {},
        }

    def test_node_with_attributes(self) -> None:
        """Node attributes are included in serialization."""
        node = Node(
            id="n2",
            type=NodeType.EVENT,
            label="Conference",
            attributes={"date": "2025-09-15", "location": "NYC"},
        )
        result = serialize_node(node)
        assert result == {
            "id": "n2",
            "type": "Event",
            "label": "Conference",
            "attributes": {"date": "2025-09-15", "location": "NYC"},
        }

    def test_all_node_types_serialize(self) -> None:
        """Every NodeType serializes to its string value."""
        for nt in NodeType:
            node = Node(id="x", type=nt, label="test", attributes={})
            result = serialize_node(node)
            assert result["type"] == nt.value


class TestSerializeEdge:
    """Tests for serialize_edge."""

    def test_basic_edge(self) -> None:
        """An edge serializes to {id, source, target, type}."""
        edge = Edge(id="e1", source="n1", target="n2", type=EdgeType.SUPPORTS)
        result = serialize_edge(edge)
        assert result == {
            "id": "e1",
            "source": "n1",
            "target": "n2",
            "type": "supports",
        }

    def test_all_edge_types_serialize(self) -> None:
        """Every EdgeType serializes to its string value."""
        for et in EdgeType:
            edge = Edge(id="x", source="a", target="b", type=et)
            result = serialize_edge(edge)
            assert result["type"] == et.value


class TestSerializeGraph:
    """Tests for serialize_graph."""

    def test_empty_graph(self) -> None:
        """An empty graph serializes to empty lists."""
        graph = Graph(nodes=[], edges=[])
        result = serialize_graph(graph)
        assert result == {"nodes": [], "edges": []}

    def test_graph_with_data(self) -> None:
        """A graph with nodes and edges serializes correctly."""
        graph = Graph(
            nodes=[
                Node(id="n1", type=NodeType.SKILL, label="Python", attributes={}),
                Node(id="n2", type=NodeType.GOAL, label="Learn", attributes={}),
            ],
            edges=[
                Edge(id="e1", source="n1", target="n2", type=EdgeType.SUPPORTS),
            ],
        )
        result = serialize_graph(graph)
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1
        assert result["nodes"][0]["id"] == "n1"
        assert result["edges"][0]["source"] == "n1"


# ---------------------------------------------------------------------------
# Error envelope tests
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    """Tests for the error_envelope helper."""

    def test_basic_envelope(self) -> None:
        """Error envelope has the correct structure."""
        result = error_envelope("TEST_ERROR", "Something went wrong")
        assert result == {
            "error": {
                "code": "TEST_ERROR",
                "message": "Something went wrong",
            }
        }

    def test_envelope_with_details(self) -> None:
        """Error envelope includes details when provided."""
        result = error_envelope("TEST_ERROR", "Bad input", {"field": "label"})
        assert result == {
            "error": {
                "code": "TEST_ERROR",
                "message": "Bad input",
                "details": {"field": "label"},
            }
        }

    def test_envelope_without_details_omits_key(self) -> None:
        """Error envelope omits 'details' key when None."""
        result = error_envelope("CODE", "msg")
        assert "details" not in result["error"]


# ---------------------------------------------------------------------------
# Error handler tests
# ---------------------------------------------------------------------------


class TestErrorHandlers:
    """Tests for domain-error → HTTP-status mapping."""

    def test_validation_error_returns_400(self, app) -> None:
        """ValidationError maps to 400."""
        with app.test_request_context():

            @app.route("/test-validation-error")
            def trigger():
                raise ValidationError("test validation error")

            client = app.test_client()
            resp = client.get("/test-validation-error")
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_label_validation_error_returns_400(self, app) -> None:
        """LabelValidationError maps to 400."""

        @app.route("/test-label-error")
        def trigger():
            raise LabelValidationError("label too long")

        client = app.test_client()
        resp = client.get("/test-label-error")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"]["code"] == "LABEL_VALIDATION_ERROR"

    def test_date_validation_error_returns_400(self, app) -> None:
        """DateValidationError maps to 400."""

        @app.route("/test-date-error")
        def trigger():
            raise DateValidationError("invalid date")

        client = app.test_client()
        resp = client.get("/test-date-error")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"]["code"] == "DATE_VALIDATION_ERROR"

    def test_attribute_validation_error_returns_400(self, app) -> None:
        """AttributeValidationError maps to 400."""

        @app.route("/test-attr-error")
        def trigger():
            raise AttributeValidationError("too many attributes")

        client = app.test_client()
        resp = client.get("/test-attr-error")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"]["code"] == "ATTRIBUTE_VALIDATION_ERROR"

    def test_storage_error_returns_500(self, app) -> None:
        """StorageError maps to 500."""

        @app.route("/test-storage-error")
        def trigger():
            raise StorageError("disk full")

        client = app.test_client()
        resp = client.get("/test-storage-error")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["error"]["code"] == "STORAGE_ERROR"

    def test_ollama_unavailable_returns_502(self, app) -> None:
        """OllamaUnavailableError maps to 502."""

        @app.route("/test-ollama-unavailable")
        def trigger():
            raise OllamaUnavailableError("service down")

        client = app.test_client()
        resp = client.get("/test-ollama-unavailable")
        assert resp.status_code == 502
        data = resp.get_json()
        assert data["error"]["code"] == "OLLAMA_UNAVAILABLE"

    def test_ollama_timeout_returns_504(self, app) -> None:
        """OllamaTimeoutError maps to 504."""

        @app.route("/test-ollama-timeout")
        def trigger():
            raise OllamaTimeoutError("timed out")

        client = app.test_client()
        resp = client.get("/test-ollama-timeout")
        assert resp.status_code == 504
        data = resp.get_json()
        assert data["error"]["code"] == "OLLAMA_TIMEOUT"

    def test_external_connection_returns_403(self, app) -> None:
        """ExternalConnectionError maps to 403."""

        @app.route("/test-external-conn")
        def trigger():
            raise ExternalConnectionError("evil.com", "1.2.3.4")

        client = app.test_client()
        resp = client.get("/test-external-conn")
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"]["code"] == "EXTERNAL_CONNECTION_BLOCKED"

    def test_404_returns_standard_envelope(self, client) -> None:
        """A 404 returns the standard error envelope."""
        resp = client.get("/nonexistent-route")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Route tests: GET /
# ---------------------------------------------------------------------------


class TestIndexRoute:
    """Tests for GET / (Req 2.2)."""

    def test_returns_html(self, client) -> None:
        """GET / returns an HTML response."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/html")

    def test_html_contains_vis_js(self, client) -> None:
        """The HTML page loads the Vis.js library."""
        resp = client.get("/")
        html = resp.data.decode()
        assert "vis-network" in html

    def test_html_contains_app_js(self, client) -> None:
        """The HTML page loads the application JavaScript."""
        resp = client.get("/")
        html = resp.data.decode()
        assert "app.js" in html


# ---------------------------------------------------------------------------
# Route tests: GET /api/graph
# ---------------------------------------------------------------------------


class TestGetGraphRoute:
    """Tests for GET /api/graph (Req 7.1, 11.1, 11.2)."""

    def test_returns_json(self, client) -> None:
        """GET /api/graph returns a JSON response."""
        resp = client.get("/api/graph")
        assert resp.status_code == 200
        assert resp.content_type == "application/json"

    def test_empty_graph_structure(self, client) -> None:
        """An empty store returns {nodes: [], edges: []}."""
        resp = client.get("/api/graph")
        data = resp.get_json()
        assert data == {"nodes": [], "edges": []}

    def test_returns_all_nodes_and_edges(self, app, client) -> None:
        """GET /api/graph returns all nodes and edges from the store."""
        _seed_store(app)
        resp = client.get("/api/graph")
        data = resp.get_json()
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2

    def test_node_json_shape(self, app, client) -> None:
        """Each node has id, type, label, attributes fields (Req 11.2)."""
        _seed_store(app)
        resp = client.get("/api/graph")
        data = resp.get_json()
        node = next(n for n in data["nodes"] if n["id"] == "n1")
        assert set(node.keys()) == {"id", "type", "label", "attributes"}
        assert node["type"] == "Skill"
        assert node["label"] == "Python"
        assert node["attributes"] == {}

    def test_node_with_attributes_json(self, app, client) -> None:
        """Node attributes are included in the JSON response."""
        _seed_store(app)
        resp = client.get("/api/graph")
        data = resp.get_json()
        node = next(n for n in data["nodes"] if n["id"] == "n2")
        assert node["attributes"] == {"priority": "high"}

    def test_edge_json_shape(self, app, client) -> None:
        """Each edge has id, source, target, type fields (Req 11.2)."""
        _seed_store(app)
        resp = client.get("/api/graph")
        data = resp.get_json()
        edge = next(e for e in data["edges"] if e["id"] == "e1")
        assert set(edge.keys()) == {"id", "source", "target", "type"}
        assert edge["source"] == "n1"
        assert edge["target"] == "n2"
        assert edge["type"] == "supports"


class TestConfirmProposalRoute:
    def test_confirm_uses_edited_proposal_body(self, tmp_db: str) -> None:
        parser = InputParser(FakeOllama())
        app = create_app({"db_path": tmp_db, "TESTING": True, "parser": parser})
        app.config["PENDING_PROPOSAL"] = ProposedGraph(
            nodes=[ProposedNode(NodeType.SKILL, "Original", {})],
            edges=[],
        )

        client = app.test_client()
        resp = client.post(
            "/api/parse/confirm",
            json={
                "nodes": [
                    {
                        "label": "Ollama",
                        "type": "Tool",
                        "attributes": {"kind": "local runner"},
                    }
                ],
                "edges": [],
            },
        )

        assert resp.status_code == 200
        graph = app.config["STORE"].get_graph()
        assert [(n.label, n.type, n.attributes) for n in graph.nodes] == [
            ("Ollama", NodeType.TOOL, {"kind": "local runner"})
        ]

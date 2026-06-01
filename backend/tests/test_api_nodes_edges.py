"""Tests for manual node and edge API endpoints.

Covers Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.1, 9.2, 9.3, 9.4, 9.5.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lifegraph.api import create_app


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
    return create_app({"db_path": tmp_db, "TESTING": True})


@pytest.fixture
def client(app):
    """Create a Flask test client."""
    return app.test_client()


def _seed_nodes(app) -> None:
    """Insert test nodes directly into the store."""
    store = app.config["STORE"]
    conn = store._connection
    conn.execute(
        "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
        ("n1", "Skill", "Python", "python", "{}"),
    )
    conn.execute(
        "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
        ("n2", "Goal", "Learn Flask", "learn flask", "{}"),
    )
    conn.execute(
        "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
        ("n3", "Event", "Conference", "conference", '{"date": "2025-09-15"}'),
    )


def _seed_edges(app) -> None:
    """Insert test edges (requires nodes to exist)."""
    store = app.config["STORE"]
    conn = store._connection
    conn.execute(
        "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
        ("e1", "n1", "n2", "supports"),
    )
    conn.execute(
        "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
        ("e2", "n2", "n3", "leads_to"),
    )


# ---------------------------------------------------------------------------
# POST /api/nodes
# ---------------------------------------------------------------------------


class TestCreateNode:
    """Tests for POST /api/nodes (Req 8.1, 8.3, 8.4, 8.5)."""

    def test_create_valid_node(self, client) -> None:
        """A valid node is created and returned with 201."""
        resp = client.post("/api/nodes", json={"label": "Guitar", "type": "Skill"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["label"] == "Guitar"
        assert data["type"] == "Skill"
        assert "id" in data
        assert data["attributes"] == {}

    def test_create_node_with_attributes(self, client) -> None:
        """A node with attributes is created correctly."""
        resp = client.post(
            "/api/nodes",
            json={"label": "Meeting", "type": "Event", "attributes": {"date": "2025-06-15"}},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["attributes"] == {"date": "2025-06-15"}

    def test_create_node_trims_label(self, client) -> None:
        """Label whitespace is trimmed (Req 8.1)."""
        resp = client.post("/api/nodes", json={"label": "  Guitar  ", "type": "Skill"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["label"] == "Guitar"

    def test_reject_empty_label(self, client) -> None:
        """Empty label is rejected with 400 (Req 8.4)."""
        resp = client.post("/api/nodes", json={"label": "", "type": "Skill"})
        assert resp.status_code == 400

    def test_reject_whitespace_only_label(self, client) -> None:
        """Whitespace-only label is rejected with 400 (Req 8.4)."""
        resp = client.post("/api/nodes", json={"label": "   ", "type": "Skill"})
        assert resp.status_code == 400

    def test_reject_label_over_100_chars(self, client) -> None:
        """Label exceeding 100 chars after trim is rejected (Req 8.5)."""
        long_label = "x" * 101
        resp = client.post("/api/nodes", json={"label": long_label, "type": "Skill"})
        assert resp.status_code == 400

    def test_reject_invalid_type(self, client) -> None:
        """Invalid node type is rejected with 400 (Req 8.3)."""
        resp = client.post("/api/nodes", json={"label": "Test", "type": "InvalidType"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert "InvalidType" in data["error"]["message"]

    def test_label_exactly_100_chars_accepted(self, client) -> None:
        """A label of exactly 100 chars is accepted."""
        label = "a" * 100
        resp = client.post("/api/nodes", json={"label": label, "type": "Skill"})
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# PUT /api/nodes/{id}
# ---------------------------------------------------------------------------


class TestUpdateNode:
    """Tests for PUT /api/nodes/{id} (Req 8.2)."""

    def test_update_label(self, app, client) -> None:
        """Updating a node's label works."""
        _seed_nodes(app)
        resp = client.put("/api/nodes/n1", json={"label": "Python3"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["label"] == "Python3"
        assert data["id"] == "n1"

    def test_update_type(self, app, client) -> None:
        """Updating a node's type works."""
        _seed_nodes(app)
        resp = client.put("/api/nodes/n1", json={"type": "Habit"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["type"] == "Habit"

    def test_update_attributes(self, app, client) -> None:
        """Updating a node's attributes works."""
        _seed_nodes(app)
        resp = client.put("/api/nodes/n3", json={"attributes": {"date": "2025-10-01"}})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["attributes"] == {"date": "2025-10-01"}

    def test_update_nonexistent_node_returns_404(self, client) -> None:
        """Updating a non-existent node returns 404."""
        resp = client.put("/api/nodes/nonexistent", json={"label": "Test"})
        assert resp.status_code == 404

    def test_update_rejects_invalid_type(self, app, client) -> None:
        """Invalid type on update is rejected with 400."""
        _seed_nodes(app)
        resp = client.put("/api/nodes/n1", json={"type": "BadType"})
        assert resp.status_code == 400

    def test_update_rejects_empty_label(self, app, client) -> None:
        """Empty label on update is rejected with 400."""
        _seed_nodes(app)
        resp = client.put("/api/nodes/n1", json={"label": ""})
        assert resp.status_code == 400

    def test_update_rejects_label_over_100(self, app, client) -> None:
        """Label over 100 chars on update is rejected."""
        _seed_nodes(app)
        resp = client.put("/api/nodes/n1", json={"label": "x" * 101})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/nodes/{id}
# ---------------------------------------------------------------------------


class TestDeleteNode:
    """Tests for DELETE /api/nodes/{id} (Req 8.6)."""

    def test_delete_node_returns_deleted_edge_ids(self, app, client) -> None:
        """Deleting a node returns the cascade-deleted edge ids."""
        _seed_nodes(app)
        _seed_edges(app)
        resp = client.delete("/api/nodes/n2")
        assert resp.status_code == 200
        data = resp.get_json()
        assert set(data["deletedEdgeIds"]) == {"e1", "e2"}

    def test_delete_node_with_no_edges(self, app, client) -> None:
        """Deleting a node with no edges returns empty list."""
        _seed_nodes(app)
        resp = client.delete("/api/nodes/n3")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["deletedEdgeIds"] == []

    def test_delete_nonexistent_node_returns_404(self, client) -> None:
        """Deleting a non-existent node returns 404."""
        resp = client.delete("/api/nodes/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/nodes/{id}/edges
# ---------------------------------------------------------------------------


class TestGetNodeEdges:
    """Tests for GET /api/nodes/{id}/edges (Req 8.7 - delete warning)."""

    def test_returns_edge_count(self, app, client) -> None:
        """Returns the count of incident edges."""
        _seed_nodes(app)
        _seed_edges(app)
        resp = client.get("/api/nodes/n2/edges")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 2

    def test_node_with_no_edges(self, app, client) -> None:
        """A node with no edges returns count 0."""
        _seed_nodes(app)
        resp = client.get("/api/nodes/n3/edges")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0

    def test_nonexistent_node_returns_404(self, client) -> None:
        """A non-existent node returns 404."""
        resp = client.get("/api/nodes/nonexistent/edges")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/edges
# ---------------------------------------------------------------------------


class TestCreateEdge:
    """Tests for POST /api/edges (Req 9.1, 9.3, 9.4)."""

    def test_create_valid_edge(self, app, client) -> None:
        """A valid edge is created and returned with 201."""
        _seed_nodes(app)
        resp = client.post(
            "/api/edges",
            json={"source": "n1", "target": "n2", "type": "supports"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["source"] == "n1"
        assert data["target"] == "n2"
        assert data["type"] == "supports"
        assert "id" in data

    def test_reject_invalid_edge_type(self, app, client) -> None:
        """Invalid edge type is rejected with 400 (Req 9.3)."""
        _seed_nodes(app)
        resp = client.post(
            "/api/edges",
            json={"source": "n1", "target": "n2", "type": "invalid_type"},
        )
        assert resp.status_code == 400

    def test_reject_self_edge(self, app, client) -> None:
        """Self-referential edge is rejected with 422 (Req 9.4)."""
        _seed_nodes(app)
        resp = client.post(
            "/api/edges",
            json={"source": "n1", "target": "n1", "type": "supports"},
        )
        assert resp.status_code == 422

    def test_reject_missing_source_node(self, app, client) -> None:
        """Edge with non-existent source is rejected with 409."""
        _seed_nodes(app)
        resp = client.post(
            "/api/edges",
            json={"source": "nonexistent", "target": "n1", "type": "supports"},
        )
        assert resp.status_code == 409

    def test_reject_missing_target_node(self, app, client) -> None:
        """Edge with non-existent target is rejected with 409."""
        _seed_nodes(app)
        resp = client.post(
            "/api/edges",
            json={"source": "n1", "target": "nonexistent", "type": "supports"},
        )
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# PUT /api/edges/{id}
# ---------------------------------------------------------------------------


class TestUpdateEdge:
    """Tests for PUT /api/edges/{id} (Req 9.2, 9.3)."""

    def test_update_edge_type(self, app, client) -> None:
        """Updating an edge's type works."""
        _seed_nodes(app)
        _seed_edges(app)
        resp = client.put("/api/edges/e1", json={"type": "requires"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["type"] == "requires"
        assert data["id"] == "e1"

    def test_reject_invalid_edge_type(self, app, client) -> None:
        """Invalid edge type on update is rejected with 400."""
        _seed_nodes(app)
        _seed_edges(app)
        resp = client.put("/api/edges/e1", json={"type": "bad_type"})
        assert resp.status_code == 400

    def test_update_nonexistent_edge_returns_404(self, client) -> None:
        """Updating a non-existent edge returns 404."""
        resp = client.put("/api/edges/nonexistent", json={"type": "supports"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/edges/{id}
# ---------------------------------------------------------------------------


class TestDeleteEdge:
    """Tests for DELETE /api/edges/{id} (Req 9.5)."""

    def test_delete_edge_returns_204(self, app, client) -> None:
        """Deleting an edge returns 204 No Content."""
        _seed_nodes(app)
        _seed_edges(app)
        resp = client.delete("/api/edges/e1")
        assert resp.status_code == 204

    def test_delete_edge_preserves_nodes(self, app, client) -> None:
        """Deleting an edge leaves its endpoint nodes intact."""
        _seed_nodes(app)
        _seed_edges(app)
        client.delete("/api/edges/e1")
        # Both nodes should still exist
        resp = client.get("/api/graph")
        data = resp.get_json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert "n1" in node_ids
        assert "n2" in node_ids

    def test_delete_nonexistent_edge_returns_404(self, client) -> None:
        """Deleting a non-existent edge returns 404."""
        resp = client.delete("/api/edges/nonexistent")
        assert resp.status_code == 404

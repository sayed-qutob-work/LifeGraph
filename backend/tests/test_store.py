"""Tests for the Graph_Store: schema creation, connection management, reads, and reload.

Covers Requirements 5.1, 5.7, 5.8.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from lifegraph.domain import Edge, EdgeType, Graph, Node, NodeType, normalize
from lifegraph.store import GraphStore, StorageError, uuid4_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_path(tmp_path: Path, name: str = "test.db") -> str:
    """Return a path string for a test database."""
    return str(tmp_path / name)


def _deterministic_id_factory():
    """Return a factory that produces sequential ids for testing."""
    counter = [0]

    def factory() -> str:
        counter[0] += 1
        return f"id-{counter[0]:04d}"

    return factory


def _seed_store(store: GraphStore) -> None:
    """Insert some nodes and edges directly via SQL for read tests."""
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
        ("n3", "Project", "LifeGraph", "lifegraph", "{}"),
    )
    conn.execute(
        "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
        ("e1", "n1", "n2", "supports"),
    )
    conn.execute(
        "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
        ("e2", "n2", "n3", "motivated_by"),
    )
    conn.execute(
        "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
        ("e3", "n3", "n1", "requires"),
    )


# ---------------------------------------------------------------------------
# Schema creation and DB lifecycle (Req 5.1, 5.7)
# ---------------------------------------------------------------------------


class TestSchemaCreation:
    """Tests for database creation and schema setup."""

    def test_creates_new_db_when_absent(self, tmp_path: Path) -> None:
        """A new DB file is created with the correct schema when absent (Req 5.7)."""
        db_path = _make_db_path(tmp_path)
        assert not Path(db_path).exists()

        store = GraphStore(db_path, id_factory=uuid4_str)

        assert Path(db_path).exists()
        # Verify tables exist
        conn = sqlite3.connect(db_path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "nodes" in tables
        assert "edges" in tables
        conn.close()
        store.close()

    def test_new_db_is_empty(self, tmp_path: Path) -> None:
        """A freshly created DB has no nodes or edges."""
        db_path = _make_db_path(tmp_path)
        store = GraphStore(db_path)
        graph = store.get_graph()
        assert graph.nodes == []
        assert graph.edges == []
        store.close()

    def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        """PRAGMA foreign_keys is ON."""
        db_path = _make_db_path(tmp_path)
        store = GraphStore(db_path)
        result = store._connection.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1
        store.close()

    def test_unique_constraint_on_normalized_label_type(self, tmp_path: Path) -> None:
        """The UNIQUE(normalized_label, type) constraint is enforced."""
        db_path = _make_db_path(tmp_path)
        store = GraphStore(db_path)
        conn = store._connection
        conn.execute(
            "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
            ("n1", "Skill", "Python", "python", "{}"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
                ("n2", "Skill", "python", "python", "{}"),
            )
        store.close()

    def test_check_constraint_on_node_type(self, tmp_path: Path) -> None:
        """CHECK constraint rejects invalid node types."""
        db_path = _make_db_path(tmp_path)
        store = GraphStore(db_path)
        conn = store._connection
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
                ("n1", "InvalidType", "Test", "test", "{}"),
            )
        store.close()

    def test_check_constraint_on_edge_type(self, tmp_path: Path) -> None:
        """CHECK constraint rejects invalid edge types."""
        db_path = _make_db_path(tmp_path)
        store = GraphStore(db_path)
        conn = store._connection
        # Insert two nodes first
        conn.execute(
            "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
            ("n1", "Skill", "A", "a", "{}"),
        )
        conn.execute(
            "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
            ("n2", "Goal", "B", "b", "{}"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
                ("e1", "n1", "n2", "invalid_edge_type"),
            )
        store.close()

    def test_check_constraint_self_edge(self, tmp_path: Path) -> None:
        """CHECK constraint rejects self-edges (source_id == target_id)."""
        db_path = _make_db_path(tmp_path)
        store = GraphStore(db_path)
        conn = store._connection
        conn.execute(
            "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
            ("n1", "Skill", "A", "a", "{}"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
                ("e1", "n1", "n1", "requires"),
            )
        store.close()

    def test_on_delete_cascade(self, tmp_path: Path) -> None:
        """ON DELETE CASCADE removes edges when a node is deleted."""
        db_path = _make_db_path(tmp_path)
        store = GraphStore(db_path)
        conn = store._connection
        conn.execute(
            "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
            ("n1", "Skill", "A", "a", "{}"),
        )
        conn.execute(
            "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
            ("n2", "Goal", "B", "b", "{}"),
        )
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
            ("e1", "n1", "n2", "requires"),
        )
        conn.execute("DELETE FROM nodes WHERE id = ?", ("n1",))
        edges = conn.execute("SELECT * FROM edges").fetchall()
        assert len(edges) == 0
        store.close()

    def test_label_length_check_constraint(self, tmp_path: Path) -> None:
        """CHECK constraint rejects labels outside 1-200 chars."""
        db_path = _make_db_path(tmp_path)
        store = GraphStore(db_path)
        conn = store._connection
        # Empty label
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
                ("n1", "Skill", "", "", "{}"),
            )
        # Label too long (201 chars)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
                ("n2", "Skill", "x" * 201, "x" * 201, "{}"),
            )
        store.close()


# ---------------------------------------------------------------------------
# Invalid DB detection (Req 5.8)
# ---------------------------------------------------------------------------


class TestInvalidDBDetection:
    """Tests for detecting invalid/corrupt database files."""

    def test_raises_on_non_sqlite_file(self, tmp_path: Path) -> None:
        """StorageError raised for a non-SQLite file (Req 5.8)."""
        db_path = _make_db_path(tmp_path)
        # Write garbage to the file
        Path(db_path).write_text("this is not a sqlite database")

        with pytest.raises(StorageError) as exc_info:
            GraphStore(db_path)

        assert "not a valid SQLite database" in str(exc_info.value)

    def test_does_not_overwrite_invalid_file(self, tmp_path: Path) -> None:
        """An invalid DB file is NOT overwritten (Req 5.8)."""
        db_path = _make_db_path(tmp_path)
        content = "this is not a sqlite database"
        Path(db_path).write_text(content)

        with pytest.raises(StorageError):
            GraphStore(db_path)

        # File content should be unchanged
        assert Path(db_path).read_text() == content

    def test_raises_on_sqlite_without_required_tables(self, tmp_path: Path) -> None:
        """StorageError raised for a valid SQLite file missing nodes/edges tables."""
        db_path = _make_db_path(tmp_path)
        # Create a valid SQLite file with a different table
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE other (id TEXT)")
        conn.close()

        with pytest.raises(StorageError) as exc_info:
            GraphStore(db_path)

        assert "missing required tables" in str(exc_info.value)

    def test_does_not_overwrite_sqlite_without_tables(self, tmp_path: Path) -> None:
        """A valid SQLite file without required tables is NOT overwritten."""
        db_path = _make_db_path(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE other (id TEXT)")
        conn.execute("INSERT INTO other VALUES ('keep_me')")
        conn.commit()
        conn.close()

        with pytest.raises(StorageError):
            GraphStore(db_path)

        # Verify original data is still there
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM other").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "keep_me"
        conn.close()

    def test_opens_valid_existing_db(self, tmp_path: Path) -> None:
        """A valid existing DB with the correct schema opens without error."""
        db_path = _make_db_path(tmp_path)
        # Create a valid DB first
        store1 = GraphStore(db_path)
        store1.close()

        # Re-open it
        store2 = GraphStore(db_path)
        graph = store2.get_graph()
        assert graph.nodes == []
        assert graph.edges == []
        store2.close()


# ---------------------------------------------------------------------------
# Read methods
# ---------------------------------------------------------------------------


class TestGetGraph:
    """Tests for get_graph()."""

    def test_returns_empty_graph_for_new_db(self, tmp_path: Path) -> None:
        """get_graph returns an empty Graph for a fresh database."""
        store = GraphStore(_make_db_path(tmp_path))
        graph = store.get_graph()
        assert isinstance(graph, Graph)
        assert graph.nodes == []
        assert graph.edges == []
        store.close()

    def test_returns_all_nodes_and_edges(self, tmp_path: Path) -> None:
        """get_graph returns all persisted nodes and edges."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        graph = store.get_graph()
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 3

        node_ids = {n.id for n in graph.nodes}
        assert node_ids == {"n1", "n2", "n3"}

        edge_ids = {e.id for e in graph.edges}
        assert edge_ids == {"e1", "e2", "e3"}
        store.close()

    def test_node_fields_are_correct(self, tmp_path: Path) -> None:
        """Nodes returned by get_graph have correct field values."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        graph = store.get_graph()
        node_map = {n.id: n for n in graph.nodes}

        n2 = node_map["n2"]
        assert n2.type == NodeType.GOAL
        assert n2.label == "Learn Flask"
        assert n2.attributes == {"priority": "high"}
        store.close()

    def test_edge_fields_are_correct(self, tmp_path: Path) -> None:
        """Edges returned by get_graph have correct field values."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        graph = store.get_graph()
        edge_map = {e.id: e for e in graph.edges}

        e1 = edge_map["e1"]
        assert e1.source == "n1"
        assert e1.target == "n2"
        assert e1.type == EdgeType.SUPPORTS
        store.close()


class TestGetNode:
    """Tests for get_node()."""

    def test_returns_node_when_exists(self, tmp_path: Path) -> None:
        """get_node returns the node for a valid id."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        node = store.get_node("n1")
        assert node is not None
        assert node.id == "n1"
        assert node.type == NodeType.SKILL
        assert node.label == "Python"
        assert node.attributes == {}
        store.close()

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """get_node returns None for a non-existent id."""
        store = GraphStore(_make_db_path(tmp_path))
        assert store.get_node("nonexistent") is None
        store.close()

    def test_returns_node_with_attributes(self, tmp_path: Path) -> None:
        """get_node correctly deserializes attributes."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        node = store.get_node("n2")
        assert node is not None
        assert node.attributes == {"priority": "high"}
        store.close()


class TestFindNode:
    """Tests for find_node()."""

    def test_finds_by_normalized_label_and_type(self, tmp_path: Path) -> None:
        """find_node matches by normalized label and type."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        # Exact match
        node = store.find_node("Python", NodeType.SKILL)
        assert node is not None
        assert node.id == "n1"
        store.close()

    def test_case_insensitive_match(self, tmp_path: Path) -> None:
        """find_node is case-insensitive."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        node = store.find_node("PYTHON", NodeType.SKILL)
        assert node is not None
        assert node.id == "n1"
        store.close()

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        """find_node strips leading/trailing whitespace."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        node = store.find_node("  Python  ", NodeType.SKILL)
        assert node is not None
        assert node.id == "n1"
        store.close()

    def test_returns_none_for_wrong_type(self, tmp_path: Path) -> None:
        """find_node returns None when label matches but type doesn't."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        node = store.find_node("Python", NodeType.GOAL)
        assert node is None
        store.close()

    def test_returns_none_for_nonexistent_label(self, tmp_path: Path) -> None:
        """find_node returns None when no node matches."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        node = store.find_node("Nonexistent", NodeType.SKILL)
        assert node is None
        store.close()


class TestIncidentEdges:
    """Tests for incident_edges()."""

    def test_returns_edges_where_node_is_source(self, tmp_path: Path) -> None:
        """incident_edges includes edges where the node is the source."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        edges = store.incident_edges("n1")
        edge_ids = {e.id for e in edges}
        assert "e1" in edge_ids  # n1 -> n2
        store.close()

    def test_returns_edges_where_node_is_target(self, tmp_path: Path) -> None:
        """incident_edges includes edges where the node is the target."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        edges = store.incident_edges("n1")
        edge_ids = {e.id for e in edges}
        assert "e3" in edge_ids  # n3 -> n1
        store.close()

    def test_returns_all_incident_edges(self, tmp_path: Path) -> None:
        """incident_edges returns all edges connected to the node."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        # n2 is target of e1 and source of e2
        edges = store.incident_edges("n2")
        edge_ids = {e.id for e in edges}
        assert edge_ids == {"e1", "e2"}
        store.close()

    def test_returns_empty_for_isolated_node(self, tmp_path: Path) -> None:
        """incident_edges returns empty list for a node with no edges."""
        store = GraphStore(_make_db_path(tmp_path))
        conn = store._connection
        conn.execute(
            "INSERT INTO nodes (id, type, label, normalized_label, attributes) VALUES (?, ?, ?, ?, ?)",
            ("n_isolated", "Skill", "Isolated", "isolated", "{}"),
        )
        edges = store.incident_edges("n_isolated")
        assert edges == []
        store.close()

    def test_returns_empty_for_nonexistent_node(self, tmp_path: Path) -> None:
        """incident_edges returns empty list for a non-existent node id."""
        store = GraphStore(_make_db_path(tmp_path))
        edges = store.incident_edges("nonexistent")
        assert edges == []
        store.close()


class TestNodesByType:
    """Tests for nodes_by_type()."""

    def test_returns_nodes_of_given_type(self, tmp_path: Path) -> None:
        """nodes_by_type returns only nodes matching the given types."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        nodes = store.nodes_by_type({NodeType.SKILL})
        assert len(nodes) == 1
        assert nodes[0].id == "n1"
        store.close()

    def test_returns_nodes_of_multiple_types(self, tmp_path: Path) -> None:
        """nodes_by_type returns nodes matching any of the given types."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        nodes = store.nodes_by_type({NodeType.SKILL, NodeType.GOAL})
        node_ids = {n.id for n in nodes}
        assert node_ids == {"n1", "n2"}
        store.close()

    def test_returns_empty_for_no_match(self, tmp_path: Path) -> None:
        """nodes_by_type returns empty list when no nodes match."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        nodes = store.nodes_by_type({NodeType.PERSON})
        assert nodes == []
        store.close()

    def test_returns_empty_for_empty_type_set(self, tmp_path: Path) -> None:
        """nodes_by_type returns empty list for an empty type set."""
        store = GraphStore(_make_db_path(tmp_path))
        _seed_store(store)

        nodes = store.nodes_by_type(set())
        assert nodes == []
        store.close()


# ---------------------------------------------------------------------------
# Injected id_factory
# ---------------------------------------------------------------------------


class TestIdFactory:
    """Tests for the injected id_factory."""

    def test_default_factory_produces_uuid4(self, tmp_path: Path) -> None:
        """The default id_factory produces valid UUID4 strings."""
        id_val = uuid4_str()
        # UUID4 format: 8-4-4-4-12 hex chars
        parts = id_val.split("-")
        assert len(parts) == 5
        assert [len(p) for p in parts] == [8, 4, 4, 4, 12]

    def test_custom_factory_is_used(self, tmp_path: Path) -> None:
        """A custom id_factory is used for generating ids."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        # The factory should be stored and usable
        assert store._id_factory() == "id-0001"
        assert store._id_factory() == "id-0002"
        store.close()


# ---------------------------------------------------------------------------
# Reload / reopen (Req 5.6 partial — verifying data persists across reopen)
# ---------------------------------------------------------------------------


class TestReload:
    """Tests for reopening an existing database."""

    def test_data_persists_across_close_and_reopen(self, tmp_path: Path) -> None:
        """Data written to the store is available after close and reopen."""
        db_path = _make_db_path(tmp_path)
        store1 = GraphStore(db_path)
        _seed_store(store1)
        store1.close()

        store2 = GraphStore(db_path)
        graph = store2.get_graph()
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 3

        node_ids = {n.id for n in graph.nodes}
        assert node_ids == {"n1", "n2", "n3"}
        store2.close()

    def test_node_fields_preserved_after_reload(self, tmp_path: Path) -> None:
        """Node fields are preserved exactly after close and reopen."""
        db_path = _make_db_path(tmp_path)
        store1 = GraphStore(db_path)
        _seed_store(store1)
        store1.close()

        store2 = GraphStore(db_path)
        node = store2.get_node("n2")
        assert node is not None
        assert node.type == NodeType.GOAL
        assert node.label == "Learn Flask"
        assert node.attributes == {"priority": "high"}
        store2.close()

    def test_edge_fields_preserved_after_reload(self, tmp_path: Path) -> None:
        """Edge fields are preserved exactly after close and reopen."""
        db_path = _make_db_path(tmp_path)
        store1 = GraphStore(db_path)
        _seed_store(store1)
        store1.close()

        store2 = GraphStore(db_path)
        graph = store2.get_graph()
        edge_map = {e.id: e for e in graph.edges}
        e2 = edge_map["e2"]
        assert e2.source == "n2"
        assert e2.target == "n3"
        assert e2.type == EdgeType.MOTIVATED_BY
        store2.close()

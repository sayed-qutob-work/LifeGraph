"""Tests for Graph_Store delete_node with cascade delete.

Covers Requirements: 5.5, 8.6
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lifegraph.domain import EdgeType, NodeType
from lifegraph.store import GraphStore, NodeNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_path(tmp_path: Path, name: str = "test.db") -> str:
    return str(tmp_path / name)


def _deterministic_id_factory():
    counter = [0]

    def factory() -> str:
        counter[0] += 1
        return f"id-{counter[0]:04d}"

    return factory


# ---------------------------------------------------------------------------
# delete_node — success path (Req 5.5, 8.6)
# ---------------------------------------------------------------------------


class TestDeleteNodeSuccess:
    """Tests for delete_node when the node exists."""

    def test_deletes_node_with_no_edges(self, tmp_path: Path) -> None:
        """A node with no incident edges is deleted, returning empty list."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node = store.upsert_node("Python", NodeType.SKILL)

        deleted_edge_ids = store.delete_node(node.id)

        assert deleted_edge_ids == []
        graph = store.get_graph()
        assert graph.nodes == []
        store.close()

    def test_deletes_node_and_returns_incident_edge_ids(self, tmp_path: Path) -> None:
        """Deleting a node returns the ids of all removed incident edges."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node_a = store.upsert_node("Python", NodeType.SKILL)  # id-0001
        node_b = store.upsert_node("Learn Python", NodeType.GOAL)  # id-0002
        edge = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)  # id-0003

        deleted_edge_ids = store.delete_node(node_a.id)

        assert edge.id in deleted_edge_ids
        assert len(deleted_edge_ids) == 1
        store.close()

    def test_cascade_removes_all_incident_edges(self, tmp_path: Path) -> None:
        """All edges where the deleted node is source or target are removed."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node_a = store.upsert_node("Python", NodeType.SKILL)
        node_b = store.upsert_node("Learn Python", NodeType.GOAL)
        node_c = store.upsert_node("Web Dev", NodeType.PROJECT)

        # node_b is source in one edge, target in another
        e1 = store.create_edge(node_b.id, node_a.id, EdgeType.REQUIRES)
        e2 = store.create_edge(node_c.id, node_b.id, EdgeType.SUPPORTS)
        # An edge not involving node_b
        e3 = store.create_edge(node_a.id, node_c.id, EdgeType.LEADS_TO)

        deleted_edge_ids = store.delete_node(node_b.id)

        assert set(deleted_edge_ids) == {e1.id, e2.id}
        graph = store.get_graph()
        # node_b is gone, node_a and node_c remain
        assert len(graph.nodes) == 2
        node_ids = {n.id for n in graph.nodes}
        assert node_a.id in node_ids
        assert node_c.id in node_ids
        # Only e3 remains
        assert len(graph.edges) == 1
        assert graph.edges[0].id == e3.id
        store.close()

    def test_other_nodes_unaffected(self, tmp_path: Path) -> None:
        """Deleting a node does not affect other nodes."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node_a = store.upsert_node("Python", NodeType.SKILL)
        node_b = store.upsert_node("Learn Python", NodeType.GOAL)

        store.delete_node(node_a.id)

        graph = store.get_graph()
        assert len(graph.nodes) == 1
        assert graph.nodes[0].id == node_b.id
        store.close()

    def test_non_incident_edges_unaffected(self, tmp_path: Path) -> None:
        """Edges not connected to the deleted node remain intact."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node_a = store.upsert_node("Python", NodeType.SKILL)
        node_b = store.upsert_node("Learn Python", NodeType.GOAL)
        node_c = store.upsert_node("Web Dev", NodeType.PROJECT)

        store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)
        e_unrelated = store.create_edge(node_b.id, node_c.id, EdgeType.SUPPORTS)

        store.delete_node(node_a.id)

        graph = store.get_graph()
        assert len(graph.edges) == 1
        assert graph.edges[0].id == e_unrelated.id
        store.close()


# ---------------------------------------------------------------------------
# delete_node — error path
# ---------------------------------------------------------------------------


class TestDeleteNodeNotFound:
    """Tests for delete_node when the node does not exist."""

    def test_raises_node_not_found(self, tmp_path: Path) -> None:
        """delete_node raises NodeNotFoundError for a non-existent id."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(NodeNotFoundError) as exc_info:
            store.delete_node("nonexistent-node")

        assert exc_info.value.node_id == "nonexistent-node"
        store.close()

    def test_not_found_leaves_store_unchanged(self, tmp_path: Path) -> None:
        """A failed delete_node does not modify the store."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node = store.upsert_node("Python", NodeType.SKILL)

        with pytest.raises(NodeNotFoundError):
            store.delete_node("nonexistent-node")

        graph = store.get_graph()
        assert len(graph.nodes) == 1
        assert graph.nodes[0].id == node.id
        store.close()

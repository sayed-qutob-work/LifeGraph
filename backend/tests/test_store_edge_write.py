"""Tests for Graph_Store edge write path: create_edge, update_edge, delete_edge.

Covers Requirements: 5.3, 5.4, 9.1, 9.2, 9.3, 9.4, 9.5
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lifegraph.domain import Edge, EdgeType, NodeType
from lifegraph.store import (
    EdgeNotFoundError,
    GraphStore,
    ReferentialIntegrityError,
    SelfEdgeError,
)


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


def _store_with_two_nodes(tmp_path: Path):
    """Create a store with two nodes for edge testing."""
    factory = _deterministic_id_factory()
    store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
    node_a = store.upsert_node("Python", NodeType.SKILL)  # id-0001
    node_b = store.upsert_node("Learn Python", NodeType.GOAL)  # id-0002
    return store, node_a, node_b


# ---------------------------------------------------------------------------
# create_edge — success path (Req 9.1)
# ---------------------------------------------------------------------------


class TestCreateEdgeSuccess:
    """Tests for create_edge when inputs are valid."""

    def test_creates_edge_between_existing_nodes(self, tmp_path: Path) -> None:
        """A valid edge is created between two existing nodes."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)

        edge = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)

        assert edge.id == "id-0003"
        assert edge.source == node_a.id
        assert edge.target == node_b.id
        assert edge.type == EdgeType.REQUIRES
        store.close()

    def test_edge_persisted_in_db(self, tmp_path: Path) -> None:
        """The created edge is retrievable from the store."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)

        store.create_edge(node_a.id, node_b.id, EdgeType.SUPPORTS)
        graph = store.get_graph()

        assert len(graph.edges) == 1
        assert graph.edges[0].source == node_a.id
        assert graph.edges[0].target == node_b.id
        assert graph.edges[0].type == EdgeType.SUPPORTS
        store.close()

    def test_creates_multiple_edges_between_same_nodes(self, tmp_path: Path) -> None:
        """Multiple edges can exist between the same pair of nodes."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)

        e1 = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)
        e2 = store.create_edge(node_a.id, node_b.id, EdgeType.SUPPORTS)

        assert e1.id != e2.id
        graph = store.get_graph()
        assert len(graph.edges) == 2
        store.close()

    def test_creates_edge_with_all_edge_types(self, tmp_path: Path) -> None:
        """All EdgeType values are accepted."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)

        for edge_type in EdgeType:
            edge = store.create_edge(node_a.id, node_b.id, edge_type)
            assert edge.type == edge_type

        graph = store.get_graph()
        assert len(graph.edges) == len(EdgeType)
        store.close()

    def test_edge_appears_in_incident_edges(self, tmp_path: Path) -> None:
        """Created edge appears in incident_edges for both endpoints."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)

        edge = store.create_edge(node_a.id, node_b.id, EdgeType.LEADS_TO)

        source_edges = store.incident_edges(node_a.id)
        target_edges = store.incident_edges(node_b.id)
        assert any(e.id == edge.id for e in source_edges)
        assert any(e.id == edge.id for e in target_edges)
        store.close()


# ---------------------------------------------------------------------------
# create_edge — self-edge rejection (Req 9.4)
# ---------------------------------------------------------------------------


class TestCreateEdgeSelfEdge:
    """Tests for create_edge self-edge rejection."""

    def test_rejects_self_edge(self, tmp_path: Path) -> None:
        """An edge where source == target raises SelfEdgeError."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node = store.upsert_node("Python", NodeType.SKILL)

        with pytest.raises(SelfEdgeError) as exc_info:
            store.create_edge(node.id, node.id, EdgeType.REQUIRES)

        assert exc_info.value.node_id == node.id
        store.close()

    def test_self_edge_leaves_tables_unchanged(self, tmp_path: Path) -> None:
        """A rejected self-edge does not create any edge."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node = store.upsert_node("Python", NodeType.SKILL)

        with pytest.raises(SelfEdgeError):
            store.create_edge(node.id, node.id, EdgeType.REQUIRES)

        graph = store.get_graph()
        assert graph.edges == []
        assert len(graph.nodes) == 1  # Node still exists
        store.close()


# ---------------------------------------------------------------------------
# create_edge — referential integrity (Req 5.4)
# ---------------------------------------------------------------------------


class TestCreateEdgeReferentialIntegrity:
    """Tests for create_edge referential integrity enforcement."""

    def test_rejects_missing_source(self, tmp_path: Path) -> None:
        """An edge with a non-existent source raises ReferentialIntegrityError."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node_b = store.upsert_node("Learn Python", NodeType.GOAL)

        with pytest.raises(ReferentialIntegrityError) as exc_info:
            store.create_edge("nonexistent-source", node_b.id, EdgeType.REQUIRES)

        assert exc_info.value.missing_id == "nonexistent-source"
        store.close()

    def test_rejects_missing_target(self, tmp_path: Path) -> None:
        """An edge with a non-existent target raises ReferentialIntegrityError."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node_a = store.upsert_node("Python", NodeType.SKILL)

        with pytest.raises(ReferentialIntegrityError) as exc_info:
            store.create_edge(node_a.id, "nonexistent-target", EdgeType.REQUIRES)

        assert exc_info.value.missing_id == "nonexistent-target"
        store.close()

    def test_rejects_both_missing(self, tmp_path: Path) -> None:
        """An edge with both source and target missing raises ReferentialIntegrityError."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(ReferentialIntegrityError):
            store.create_edge("missing-a", "missing-b", EdgeType.REQUIRES)
        store.close()

    def test_missing_source_leaves_tables_unchanged(self, tmp_path: Path) -> None:
        """A rejected edge (missing source) leaves both tables unchanged."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node_b = store.upsert_node("Learn Python", NodeType.GOAL)

        with pytest.raises(ReferentialIntegrityError):
            store.create_edge("nonexistent", node_b.id, EdgeType.REQUIRES)

        graph = store.get_graph()
        assert graph.edges == []
        assert len(graph.nodes) == 1  # Only node_b exists
        store.close()

    def test_missing_target_leaves_tables_unchanged(self, tmp_path: Path) -> None:
        """A rejected edge (missing target) leaves both tables unchanged."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)
        node_a = store.upsert_node("Python", NodeType.SKILL)

        with pytest.raises(ReferentialIntegrityError):
            store.create_edge(node_a.id, "nonexistent", EdgeType.REQUIRES)

        graph = store.get_graph()
        assert graph.edges == []
        assert len(graph.nodes) == 1  # Only node_a exists
        store.close()


# ---------------------------------------------------------------------------
# update_edge (Req 9.2)
# ---------------------------------------------------------------------------


class TestUpdateEdge:
    """Tests for update_edge."""

    def test_updates_edge_type(self, tmp_path: Path) -> None:
        """update_edge changes the edge type."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)
        edge = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)

        updated = store.update_edge(edge.id, EdgeType.SUPPORTS)

        assert updated.id == edge.id
        assert updated.source == node_a.id
        assert updated.target == node_b.id
        assert updated.type == EdgeType.SUPPORTS
        store.close()

    def test_update_persists_in_db(self, tmp_path: Path) -> None:
        """Updated edge type is persisted in the database."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)
        edge = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)

        store.update_edge(edge.id, EdgeType.BLOCKS)

        graph = store.get_graph()
        assert len(graph.edges) == 1
        assert graph.edges[0].type == EdgeType.BLOCKS
        store.close()

    def test_update_preserves_source_and_target(self, tmp_path: Path) -> None:
        """update_edge does not change source or target."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)
        edge = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)

        updated = store.update_edge(edge.id, EdgeType.MOTIVATED_BY)

        assert updated.source == node_a.id
        assert updated.target == node_b.id
        store.close()

    def test_raises_edge_not_found(self, tmp_path: Path) -> None:
        """update_edge raises EdgeNotFoundError for non-existent id."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(EdgeNotFoundError) as exc_info:
            store.update_edge("nonexistent-edge", EdgeType.SUPPORTS)

        assert exc_info.value.edge_id == "nonexistent-edge"
        store.close()

    def test_updates_to_all_edge_types(self, tmp_path: Path) -> None:
        """An edge can be updated to any valid EdgeType."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)
        edge = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)

        for edge_type in EdgeType:
            updated = store.update_edge(edge.id, edge_type)
            assert updated.type == edge_type
        store.close()


# ---------------------------------------------------------------------------
# delete_edge (Req 9.5)
# ---------------------------------------------------------------------------


class TestDeleteEdge:
    """Tests for delete_edge."""

    def test_deletes_edge(self, tmp_path: Path) -> None:
        """delete_edge removes the edge from the store."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)
        edge = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)

        store.delete_edge(edge.id)

        graph = store.get_graph()
        assert graph.edges == []
        store.close()

    def test_keeps_endpoints_intact(self, tmp_path: Path) -> None:
        """delete_edge does not remove the source or target nodes."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)
        edge = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)

        store.delete_edge(edge.id)

        graph = store.get_graph()
        assert len(graph.nodes) == 2
        node_ids = {n.id for n in graph.nodes}
        assert node_a.id in node_ids
        assert node_b.id in node_ids
        store.close()

    def test_raises_edge_not_found(self, tmp_path: Path) -> None:
        """delete_edge raises EdgeNotFoundError for non-existent id."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(EdgeNotFoundError) as exc_info:
            store.delete_edge("nonexistent-edge")

        assert exc_info.value.edge_id == "nonexistent-edge"
        store.close()

    def test_deletes_only_specified_edge(self, tmp_path: Path) -> None:
        """delete_edge removes only the specified edge, not others."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)
        e1 = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)
        e2 = store.create_edge(node_a.id, node_b.id, EdgeType.SUPPORTS)

        store.delete_edge(e1.id)

        graph = store.get_graph()
        assert len(graph.edges) == 1
        assert graph.edges[0].id == e2.id
        store.close()

    def test_delete_edge_then_recreate(self, tmp_path: Path) -> None:
        """After deleting an edge, a new edge can be created between the same nodes."""
        store, node_a, node_b = _store_with_two_nodes(tmp_path)
        edge = store.create_edge(node_a.id, node_b.id, EdgeType.REQUIRES)

        store.delete_edge(edge.id)
        new_edge = store.create_edge(node_a.id, node_b.id, EdgeType.SUPPORTS)

        assert new_edge.id != edge.id
        graph = store.get_graph()
        assert len(graph.edges) == 1
        assert graph.edges[0].type == EdgeType.SUPPORTS
        store.close()

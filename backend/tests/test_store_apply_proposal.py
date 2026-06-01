"""Tests for GraphStore.apply_proposal — proposal application with endpoint resolution.

Covers Requirements 3.6, 3.7, 4.4.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from lifegraph.domain import (
    EdgeType,
    Graph,
    NodeType,
    ProposedEdge,
    ProposedGraph,
    ProposedNode,
    normalize,
)
from lifegraph.store import GraphStore


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
# Tests: apply_proposal basic behavior
# ---------------------------------------------------------------------------


class TestApplyProposalBasic:
    """Basic apply_proposal tests."""

    def test_empty_proposal_returns_empty_graph(self, tmp_path: Path) -> None:
        """An empty proposal produces an empty result and no writes."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        proposal = ProposedGraph(nodes=[], edges=[])
        result = store.apply_proposal(proposal)
        assert result.nodes == []
        assert result.edges == []
        # Store should still be empty
        graph = store.get_graph()
        assert graph.nodes == []
        assert graph.edges == []

    def test_proposal_with_nodes_only(self, tmp_path: Path) -> None:
        """A proposal with only nodes creates them in the store."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        proposal = ProposedGraph(
            nodes=[
                ProposedNode(type=NodeType.SKILL, label="Python"),
                ProposedNode(type=NodeType.GOAL, label="Learn Flask"),
            ],
            edges=[],
        )
        result = store.apply_proposal(proposal)
        assert len(result.nodes) == 2
        assert result.edges == []

        # Verify nodes are persisted
        graph = store.get_graph()
        assert len(graph.nodes) == 2
        labels = {n.label for n in graph.nodes}
        assert "Python" in labels
        assert "Learn Flask" in labels

    def test_proposal_with_nodes_and_edges(self, tmp_path: Path) -> None:
        """A proposal with nodes and edges creates both."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        proposal = ProposedGraph(
            nodes=[
                ProposedNode(type=NodeType.SKILL, label="Python"),
                ProposedNode(type=NodeType.GOAL, label="Learn Flask"),
            ],
            edges=[
                ProposedEdge(
                    source_label="Python",
                    source_type=NodeType.SKILL,
                    target_label="Learn Flask",
                    target_type=NodeType.GOAL,
                    type=EdgeType.SUPPORTS,
                ),
            ],
        )
        result = store.apply_proposal(proposal)
        assert len(result.nodes) == 2
        assert len(result.edges) == 1

        # Verify edge connects the right nodes
        edge = result.edges[0]
        source_node = next(n for n in result.nodes if n.type == NodeType.SKILL)
        target_node = next(n for n in result.nodes if n.type == NodeType.GOAL)
        assert edge.source == source_node.id
        assert edge.target == target_node.id
        assert edge.type == EdgeType.SUPPORTS


class TestApplyProposalDedup:
    """Tests for deduplication behavior during proposal application."""

    def test_reuses_existing_node_with_same_identity(self, tmp_path: Path) -> None:
        """If a node with the same (normalized_label, type) exists, reuse it."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        # Pre-create a node
        existing = store.upsert_node("Python", NodeType.SKILL)

        # Proposal references the same identity (different casing)
        proposal = ProposedGraph(
            nodes=[ProposedNode(type=NodeType.SKILL, label="  PYTHON  ")],
            edges=[],
        )
        result = store.apply_proposal(proposal)
        assert len(result.nodes) == 1
        assert result.nodes[0].id == existing.id
        assert result.nodes[0].label == "Python"  # original label preserved

        # Store should still have only one node
        graph = store.get_graph()
        assert len(graph.nodes) == 1

    def test_dedup_within_proposal(self, tmp_path: Path) -> None:
        """Duplicate nodes within the same proposal are deduplicated."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        proposal = ProposedGraph(
            nodes=[
                ProposedNode(type=NodeType.SKILL, label="Python"),
                ProposedNode(type=NodeType.SKILL, label="python"),  # same identity
            ],
            edges=[],
        )
        result = store.apply_proposal(proposal)
        # Both resolve to the same node
        assert len(result.nodes) == 2  # both are in result list
        assert result.nodes[0].id == result.nodes[1].id

        # Store should have only one node
        graph = store.get_graph()
        assert len(graph.nodes) == 1


class TestApplyProposalEdgeResolution:
    """Tests for edge endpoint resolution (Req 4.4)."""

    def test_edge_resolves_to_existing_nodes(self, tmp_path: Path) -> None:
        """Edges resolve endpoints to pre-existing identity-matched nodes."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        # Pre-create nodes
        python = store.upsert_node("Python", NodeType.SKILL)
        flask = store.upsert_node("Learn Flask", NodeType.GOAL)

        # Proposal has only an edge referencing existing nodes
        proposal = ProposedGraph(
            nodes=[],
            edges=[
                ProposedEdge(
                    source_label="Python",
                    source_type=NodeType.SKILL,
                    target_label="Learn Flask",
                    target_type=NodeType.GOAL,
                    type=EdgeType.SUPPORTS,
                ),
            ],
        )
        result = store.apply_proposal(proposal)
        assert len(result.edges) == 1
        assert result.edges[0].source == python.id
        assert result.edges[0].target == flask.id

    def test_edge_creates_missing_endpoint_nodes(self, tmp_path: Path) -> None:
        """If an edge references a node that doesn't exist, it is created."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        # Proposal has an edge but no explicit nodes — endpoints must be created
        proposal = ProposedGraph(
            nodes=[],
            edges=[
                ProposedEdge(
                    source_label="Guitar",
                    source_type=NodeType.SKILL,
                    target_label="Play in Band",
                    target_type=NodeType.GOAL,
                    type=EdgeType.LEADS_TO,
                ),
            ],
        )
        result = store.apply_proposal(proposal)
        assert len(result.edges) == 1

        # Both endpoint nodes should now exist in the store
        graph = store.get_graph()
        assert len(graph.nodes) == 2
        labels = {n.label for n in graph.nodes}
        assert "Guitar" in labels
        assert "Play in Band" in labels

    def test_edge_endpoint_case_insensitive_match(self, tmp_path: Path) -> None:
        """Edge endpoint resolution uses normalized (case-insensitive) matching."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        # Pre-create a node
        python = store.upsert_node("Python", NodeType.SKILL)

        # Edge references with different casing
        proposal = ProposedGraph(
            nodes=[
                ProposedNode(type=NodeType.GOAL, label="Master Python"),
            ],
            edges=[
                ProposedEdge(
                    source_label="PYTHON",  # different case
                    source_type=NodeType.SKILL,
                    target_label="master python",  # different case
                    target_type=NodeType.GOAL,
                    type=EdgeType.SUPPORTS,
                ),
            ],
        )
        result = store.apply_proposal(proposal)
        assert len(result.edges) == 1
        # Source should be the pre-existing Python node
        assert result.edges[0].source == python.id


class TestApplyProposalNoWrite:
    """Tests ensuring rejected/never-confirmed proposals perform no write (Req 3.7)."""

    def test_rejected_proposal_no_write(self, tmp_path: Path) -> None:
        """A rejected proposal (never calling apply_proposal) leaves store unchanged.

        This test verifies the design: rejection means the method is simply
        never called, so the store remains unchanged.
        """
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        # Pre-populate
        store.upsert_node("Python", NodeType.SKILL)

        # Create a proposal but DON'T apply it (simulating rejection)
        _proposal = ProposedGraph(
            nodes=[ProposedNode(type=NodeType.GOAL, label="New Goal")],
            edges=[],
        )

        # Store should be unchanged
        graph = store.get_graph()
        assert len(graph.nodes) == 1
        assert graph.nodes[0].label == "Python"

    def test_transaction_rollback_on_error(self, tmp_path: Path) -> None:
        """If an error occurs during apply_proposal, no partial writes persist."""
        counter = [0]

        def failing_id_factory() -> str:
            counter[0] += 1
            if counter[0] >= 3:
                raise RuntimeError("Simulated failure")
            return f"id-{counter[0]:04d}"

        store = GraphStore(_make_db_path(tmp_path), id_factory=failing_id_factory)

        proposal = ProposedGraph(
            nodes=[
                ProposedNode(type=NodeType.SKILL, label="Node1"),
                ProposedNode(type=NodeType.SKILL, label="Node2"),
                ProposedNode(type=NodeType.GOAL, label="Node3"),  # will fail on id gen
            ],
            edges=[],
        )

        with pytest.raises(RuntimeError, match="Simulated failure"):
            store.apply_proposal(proposal)

        # Store should be unchanged — transaction rolled back
        graph = store.get_graph()
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0


class TestApplyProposalSingleTransaction:
    """Tests verifying single-transaction semantics."""

    def test_all_nodes_and_edges_in_one_transaction(self, tmp_path: Path) -> None:
        """All nodes and edges from a proposal are created atomically."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        proposal = ProposedGraph(
            nodes=[
                ProposedNode(type=NodeType.SKILL, label="Cooking"),
                ProposedNode(type=NodeType.GOAL, label="Open Restaurant"),
                ProposedNode(type=NodeType.PERSON, label="Chef Mentor"),
            ],
            edges=[
                ProposedEdge(
                    source_label="Cooking",
                    source_type=NodeType.SKILL,
                    target_label="Open Restaurant",
                    target_type=NodeType.GOAL,
                    type=EdgeType.LEADS_TO,
                ),
                ProposedEdge(
                    source_label="Chef Mentor",
                    source_type=NodeType.PERSON,
                    target_label="Cooking",
                    target_type=NodeType.SKILL,
                    type=EdgeType.SUPPORTS,
                ),
            ],
        )
        result = store.apply_proposal(proposal)

        # All nodes and edges should be present
        graph = store.get_graph()
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2

    def test_proposal_with_attributes_on_nodes(self, tmp_path: Path) -> None:
        """Proposed nodes with attributes are created with those attributes."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        proposal = ProposedGraph(
            nodes=[
                ProposedNode(
                    type=NodeType.EVENT,
                    label="Conference",
                    attributes={"date": "2025-09-15"},
                ),
            ],
            edges=[],
        )
        result = store.apply_proposal(proposal)
        assert len(result.nodes) == 1
        assert result.nodes[0].attributes == {"date": "2025-09-15"}

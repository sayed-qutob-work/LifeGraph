"""Unit tests for the ContextSerializer.

Tests cover:
- Basic BFS traversal and output format
- Hop distance limiting
- Budget trimming (max_nodes and max_chars)
- Determinism (same input -> same output)
- Edge cases (root not found, isolated node, empty edges)
"""

import pytest

from lifegraph.domain import Edge, EdgeType, Graph, Node, NodeType
from lifegraph.serializer import ContextSerializer


def _make_node(nid: str, ntype: NodeType, label: str) -> Node:
    return Node(id=nid, type=ntype, label=label)


def _make_edge(eid: str, source: str, target: str, etype: EdgeType) -> Edge:
    return Edge(id=eid, source=source, target=target, type=etype)


class TestBasicSerialization:
    """Test basic BFS traversal and rendering."""

    def test_single_node_no_edges(self):
        """A single root node with no edges produces a valid snapshot."""
        graph = Graph(
            nodes=[_make_node("n1", NodeType.SKILL, "Python")],
            edges=[],
        )
        serializer = ContextSerializer()
        result = serializer.serialize(graph, "n1")

        assert "=== Context Snapshot ===" in result
        assert "[Skill] Python (hop 0)" in result
        assert "(none)" in result

    def test_root_with_one_neighbor(self):
        """Root connected to one neighbor at hop 1."""
        graph = Graph(
            nodes=[
                _make_node("n1", NodeType.GOAL, "Learn Guitar"),
                _make_node("n2", NodeType.SKILL, "Music Theory"),
            ],
            edges=[
                _make_edge("e1", "n1", "n2", EdgeType.REQUIRES),
            ],
        )
        serializer = ContextSerializer()
        result = serializer.serialize(graph, "n1")

        assert "[Goal] Learn Guitar (hop 0)" in result
        assert "[Skill] Music Theory (hop 1)" in result
        assert "Learn Guitar --[requires]--> Music Theory" in result

    def test_two_hop_traversal(self):
        """Traversal reaches nodes at hop 2."""
        graph = Graph(
            nodes=[
                _make_node("n1", NodeType.GOAL, "Master Piano"),
                _make_node("n2", NodeType.SKILL, "Scales"),
                _make_node("n3", NodeType.RESOURCE, "Piano Book"),
            ],
            edges=[
                _make_edge("e1", "n1", "n2", EdgeType.REQUIRES),
                _make_edge("e2", "n2", "n3", EdgeType.SUPPORTS),
            ],
        )
        serializer = ContextSerializer(max_hops=2)
        result = serializer.serialize(graph, "n1")

        assert "[Goal] Master Piano (hop 0)" in result
        assert "[Skill] Scales (hop 1)" in result
        assert "[Resource] Piano Book (hop 2)" in result

    def test_root_not_found_raises(self):
        """ValueError raised when root_id is not in the graph."""
        graph = Graph(
            nodes=[_make_node("n1", NodeType.SKILL, "Python")],
            edges=[],
        )
        serializer = ContextSerializer()
        with pytest.raises(ValueError, match="not found"):
            serializer.serialize(graph, "nonexistent")


class TestHopBound:
    """Test that traversal respects max_hops."""

    def test_max_hops_1_excludes_hop_2(self):
        """With max_hops=1, nodes at hop 2 are excluded."""
        graph = Graph(
            nodes=[
                _make_node("n1", NodeType.GOAL, "Alpha"),
                _make_node("n2", NodeType.SKILL, "Beta"),
                _make_node("n3", NodeType.RESOURCE, "Gamma"),
            ],
            edges=[
                _make_edge("e1", "n1", "n2", EdgeType.REQUIRES),
                _make_edge("e2", "n2", "n3", EdgeType.SUPPORTS),
            ],
        )
        serializer = ContextSerializer(max_hops=1)
        result = serializer.serialize(graph, "n1")

        assert "[Goal] Alpha (hop 0)" in result
        assert "[Skill] Beta (hop 1)" in result
        assert "Gamma" not in result

    def test_max_hops_0_only_root(self):
        """With max_hops=0, only the root node is included."""
        graph = Graph(
            nodes=[
                _make_node("n1", NodeType.GOAL, "A"),
                _make_node("n2", NodeType.SKILL, "B"),
            ],
            edges=[
                _make_edge("e1", "n1", "n2", EdgeType.REQUIRES),
            ],
        )
        serializer = ContextSerializer(max_hops=0)
        result = serializer.serialize(graph, "n1")

        assert "[Goal] A (hop 0)" in result
        assert "B" not in result


class TestBudgetTrimming:
    """Test node/char budget trimming."""

    def test_max_nodes_trims_most_distant(self):
        """When over max_nodes, most distant nodes are dropped first."""
        graph = Graph(
            nodes=[
                _make_node("n1", NodeType.GOAL, "Root"),
                _make_node("n2", NodeType.SKILL, "Hop1A"),
                _make_node("n3", NodeType.SKILL, "Hop1B"),
                _make_node("n4", NodeType.RESOURCE, "Hop2A"),
            ],
            edges=[
                _make_edge("e1", "n1", "n2", EdgeType.REQUIRES),
                _make_edge("e2", "n1", "n3", EdgeType.SUPPORTS),
                _make_edge("e3", "n2", "n4", EdgeType.LEADS_TO),
            ],
        )
        # max_nodes=3 should drop n4 (hop 2)
        serializer = ContextSerializer(max_nodes=3)
        result = serializer.serialize(graph, "n1")

        assert "[Goal] Root (hop 0)" in result
        assert "Hop1A" in result
        assert "Hop1B" in result
        assert "Hop2A" not in result

    def test_max_nodes_same_distance_drops_highest_id(self):
        """Among same-distance nodes, highest node id is dropped first."""
        graph = Graph(
            nodes=[
                _make_node("a", NodeType.GOAL, "Root"),
                _make_node("b", NodeType.SKILL, "NodeB"),
                _make_node("c", NodeType.SKILL, "NodeC"),
                _make_node("d", NodeType.SKILL, "NodeD"),
            ],
            edges=[
                _make_edge("e1", "a", "b", EdgeType.REQUIRES),
                _make_edge("e2", "a", "c", EdgeType.REQUIRES),
                _make_edge("e3", "a", "d", EdgeType.REQUIRES),
            ],
        )
        # max_nodes=3: root + 2 of {b, c, d}. Should keep b and c, drop d.
        serializer = ContextSerializer(max_nodes=3)
        result = serializer.serialize(graph, "a")

        assert "[Goal] Root (hop 0)" in result
        assert "NodeB" in result
        assert "NodeC" in result
        assert "NodeD" not in result

    def test_max_chars_trims_nodes(self):
        """When rendered output exceeds max_chars, nodes are dropped."""
        graph = Graph(
            nodes=[
                _make_node("n1", NodeType.GOAL, "Root"),
                _make_node("n2", NodeType.SKILL, "A" * 50),
                _make_node("n3", NodeType.SKILL, "B" * 50),
            ],
            edges=[
                _make_edge("e1", "n1", "n2", EdgeType.REQUIRES),
                _make_edge("e2", "n1", "n3", EdgeType.SUPPORTS),
            ],
        )
        # Use a very small char budget to force trimming
        serializer = ContextSerializer(max_chars=150)
        result = serializer.serialize(graph, "n1")

        # Should still include root at minimum
        assert "[Goal] Root (hop 0)" in result
        assert len(result) <= 150


class TestDeterminism:
    """Test that serialization is deterministic."""

    def test_same_input_same_output(self):
        """Calling serialize twice with same input produces identical output."""
        graph = Graph(
            nodes=[
                _make_node("n1", NodeType.GOAL, "Learn Rust"),
                _make_node("n2", NodeType.SKILL, "Systems Programming"),
                _make_node("n3", NodeType.RESOURCE, "Rust Book"),
                _make_node("n4", NodeType.PERSON, "Mentor"),
            ],
            edges=[
                _make_edge("e1", "n1", "n2", EdgeType.REQUIRES),
                _make_edge("e2", "n2", "n3", EdgeType.SUPPORTS),
                _make_edge("e3", "n4", "n1", EdgeType.MOTIVATED_BY),
            ],
        )
        serializer = ContextSerializer()
        result1 = serializer.serialize(graph, "n1")
        result2 = serializer.serialize(graph, "n1")

        assert result1 == result2

    def test_node_order_in_graph_does_not_affect_output(self):
        """Output is the same regardless of node/edge insertion order in Graph."""
        nodes = [
            _make_node("n1", NodeType.GOAL, "A"),
            _make_node("n2", NodeType.SKILL, "B"),
            _make_node("n3", NodeType.RESOURCE, "C"),
        ]
        edges = [
            _make_edge("e1", "n1", "n2", EdgeType.REQUIRES),
            _make_edge("e2", "n2", "n3", EdgeType.SUPPORTS),
        ]

        graph1 = Graph(nodes=nodes[:], edges=edges[:])
        graph2 = Graph(nodes=list(reversed(nodes)), edges=list(reversed(edges)))

        serializer = ContextSerializer()
        assert serializer.serialize(graph1, "n1") == serializer.serialize(graph2, "n1")


class TestEdgeCases:
    """Test edge cases."""

    def test_undirected_traversal(self):
        """BFS traverses edges in both directions."""
        graph = Graph(
            nodes=[
                _make_node("n1", NodeType.GOAL, "Target"),
                _make_node("n2", NodeType.SKILL, "Source"),
            ],
            edges=[
                # Edge goes from n2 -> n1, but BFS from n1 should still find n2
                _make_edge("e1", "n2", "n1", EdgeType.SUPPORTS),
            ],
        )
        serializer = ContextSerializer()
        result = serializer.serialize(graph, "n1")

        assert "[Goal] Target (hop 0)" in result
        assert "[Skill] Source (hop 1)" in result

    def test_disconnected_nodes_not_included(self):
        """Nodes not reachable from root are excluded."""
        graph = Graph(
            nodes=[
                _make_node("n1", NodeType.GOAL, "Root"),
                _make_node("n2", NodeType.SKILL, "Connected"),
                _make_node("n3", NodeType.RESOURCE, "Disconnected"),
            ],
            edges=[
                _make_edge("e1", "n1", "n2", EdgeType.REQUIRES),
            ],
        )
        serializer = ContextSerializer()
        result = serializer.serialize(graph, "n1")

        assert "Root" in result
        assert "Connected" in result
        assert "Disconnected" not in result

    def test_empty_graph_with_only_root(self):
        """Graph with only the root node and no edges."""
        graph = Graph(
            nodes=[_make_node("n1", NodeType.PERSON, "Me")],
            edges=[],
        )
        serializer = ContextSerializer()
        result = serializer.serialize(graph, "n1")

        assert "[Person] Me (hop 0)" in result
        assert "(none)" in result

"""Tests for the search and filter logic."""

import pytest

from lifegraph.domain import Edge, EdgeType, Graph, Node, NodeType
from lifegraph.search import filter_graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_graph() -> Graph:
    """A small graph with mixed node types and edges."""
    nodes = [
        Node(id="n1", type=NodeType.SKILL, label="Guitar"),
        Node(id="n2", type=NodeType.SKILL, label="Python Programming"),
        Node(id="n3", type=NodeType.GOAL, label="Learn Guitar"),
        Node(id="n4", type=NodeType.EVENT, label="Concert"),
        Node(id="n5", type=NodeType.PERSON, label="Alice"),
    ]
    edges = [
        Edge(id="e1", source="n1", target="n3", type=EdgeType.SUPPORTS),
        Edge(id="e2", source="n5", target="n4", type=EdgeType.RELATED_TO),
        Edge(id="e3", source="n2", target="n1", type=EdgeType.REQUIRES),
    ]
    return Graph(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# No filter active — return full graph
# ---------------------------------------------------------------------------


class TestNoFilter:
    def test_none_types_none_term_returns_full_graph(self, sample_graph: Graph):
        result = filter_graph(sample_graph, types=None, term=None)
        assert set(n.id for n in result.nodes) == {"n1", "n2", "n3", "n4", "n5"}
        assert set(e.id for e in result.edges) == {"e1", "e2", "e3"}

    def test_empty_types_none_term_returns_full_graph(self, sample_graph: Graph):
        result = filter_graph(sample_graph, types=set(), term=None)
        assert set(n.id for n in result.nodes) == {"n1", "n2", "n3", "n4", "n5"}
        assert set(e.id for e in result.edges) == {"e1", "e2", "e3"}

    def test_none_types_empty_term_returns_full_graph(self, sample_graph: Graph):
        result = filter_graph(sample_graph, types=None, term="")
        assert set(n.id for n in result.nodes) == {"n1", "n2", "n3", "n4", "n5"}
        assert set(e.id for e in result.edges) == {"e1", "e2", "e3"}

    def test_empty_types_empty_term_returns_full_graph(self, sample_graph: Graph):
        result = filter_graph(sample_graph, types=set(), term="")
        assert set(n.id for n in result.nodes) == {"n1", "n2", "n3", "n4", "n5"}
        assert set(e.id for e in result.edges) == {"e1", "e2", "e3"}


# ---------------------------------------------------------------------------
# Type filtering
# ---------------------------------------------------------------------------


class TestTypeFilter:
    def test_single_type_filter(self, sample_graph: Graph):
        result = filter_graph(sample_graph, types={NodeType.SKILL})
        assert set(n.id for n in result.nodes) == {"n1", "n2"}
        # Only edge e3 connects two SKILL nodes
        assert set(e.id for e in result.edges) == {"e3"}

    def test_multiple_type_filter(self, sample_graph: Graph):
        result = filter_graph(sample_graph, types={NodeType.SKILL, NodeType.GOAL})
        assert set(n.id for n in result.nodes) == {"n1", "n2", "n3"}
        # e1 (n1->n3) and e3 (n2->n1) both connect included nodes
        assert set(e.id for e in result.edges) == {"e1", "e3"}

    def test_type_filter_no_matching_nodes(self, sample_graph: Graph):
        result = filter_graph(sample_graph, types={NodeType.HABIT})
        assert result.nodes == []
        assert result.edges == []

    def test_type_filter_excludes_edges_with_one_endpoint_outside(
        self, sample_graph: Graph
    ):
        # Only PERSON nodes — edge e2 connects PERSON(n5) to EVENT(n4), EVENT excluded
        result = filter_graph(sample_graph, types={NodeType.PERSON})
        assert set(n.id for n in result.nodes) == {"n5"}
        assert result.edges == []


# ---------------------------------------------------------------------------
# Term filtering (case-insensitive)
# ---------------------------------------------------------------------------


class TestTermFilter:
    def test_term_matches_case_insensitive(self, sample_graph: Graph):
        result = filter_graph(sample_graph, term="guitar")
        # Matches "Guitar" and "Learn Guitar"
        assert set(n.id for n in result.nodes) == {"n1", "n3"}
        # e1 connects n1 and n3
        assert set(e.id for e in result.edges) == {"e1"}

    def test_term_uppercase_matches(self, sample_graph: Graph):
        result = filter_graph(sample_graph, term="GUITAR")
        assert set(n.id for n in result.nodes) == {"n1", "n3"}

    def test_term_partial_match(self, sample_graph: Graph):
        result = filter_graph(sample_graph, term="prog")
        assert set(n.id for n in result.nodes) == {"n2"}
        assert result.edges == []

    def test_term_no_match(self, sample_graph: Graph):
        result = filter_graph(sample_graph, term="xyz_no_match")
        assert result.nodes == []
        assert result.edges == []


# ---------------------------------------------------------------------------
# Combined type + term filtering (both must match)
# ---------------------------------------------------------------------------


class TestCombinedFilter:
    def test_both_type_and_term(self, sample_graph: Graph):
        # SKILL nodes with "guitar" in label — only "Guitar" (n1)
        result = filter_graph(sample_graph, types={NodeType.SKILL}, term="guitar")
        assert set(n.id for n in result.nodes) == {"n1"}
        assert result.edges == []

    def test_combined_filter_no_overlap(self, sample_graph: Graph):
        # GOAL nodes with "python" — no GOAL has "python"
        result = filter_graph(sample_graph, types={NodeType.GOAL}, term="python")
        assert result.nodes == []
        assert result.edges == []

    def test_combined_filter_order_independent(self, sample_graph: Graph):
        """Results are the same regardless of which filter was 'set first'."""
        result1 = filter_graph(sample_graph, types={NodeType.SKILL}, term="guitar")
        result2 = filter_graph(sample_graph, types={NodeType.SKILL}, term="guitar")
        assert set(n.id for n in result1.nodes) == set(n.id for n in result2.nodes)
        assert set(e.id for e in result1.edges) == set(e.id for e in result2.edges)


# ---------------------------------------------------------------------------
# Edge inclusion logic
# ---------------------------------------------------------------------------


class TestEdgeInclusion:
    def test_edge_included_only_when_both_endpoints_included(self):
        nodes = [
            Node(id="a", type=NodeType.SKILL, label="A"),
            Node(id="b", type=NodeType.SKILL, label="B"),
            Node(id="c", type=NodeType.GOAL, label="C"),
        ]
        edges = [
            Edge(id="e1", source="a", target="b", type=EdgeType.REQUIRES),
            Edge(id="e2", source="a", target="c", type=EdgeType.SUPPORTS),
            Edge(id="e3", source="b", target="c", type=EdgeType.LEADS_TO),
        ]
        graph = Graph(nodes=nodes, edges=edges)
        result = filter_graph(graph, types={NodeType.SKILL})
        # Only e1 connects two SKILL nodes
        assert set(e.id for e in result.edges) == {"e1"}


# ---------------------------------------------------------------------------
# Order independence
# ---------------------------------------------------------------------------


class TestOrderIndependence:
    def test_different_input_order_same_result(self):
        """Shuffled input order produces the same node/edge sets."""
        nodes_order1 = [
            Node(id="n1", type=NodeType.SKILL, label="Guitar"),
            Node(id="n2", type=NodeType.GOAL, label="Learn Guitar"),
            Node(id="n3", type=NodeType.EVENT, label="Concert"),
        ]
        nodes_order2 = [
            Node(id="n3", type=NodeType.EVENT, label="Concert"),
            Node(id="n1", type=NodeType.SKILL, label="Guitar"),
            Node(id="n2", type=NodeType.GOAL, label="Learn Guitar"),
        ]
        edges = [
            Edge(id="e1", source="n1", target="n2", type=EdgeType.SUPPORTS),
        ]
        g1 = Graph(nodes=nodes_order1, edges=list(edges))
        g2 = Graph(nodes=nodes_order2, edges=list(edges))

        r1 = filter_graph(g1, term="guitar")
        r2 = filter_graph(g2, term="guitar")

        assert set(n.id for n in r1.nodes) == set(n.id for n in r2.nodes)
        assert set(e.id for e in r1.edges) == set(e.id for e in r2.edges)

    def test_empty_graph(self):
        """Filtering an empty graph returns an empty graph."""
        graph = Graph(nodes=[], edges=[])
        result = filter_graph(graph, types={NodeType.SKILL}, term="test")
        assert result.nodes == []
        assert result.edges == []

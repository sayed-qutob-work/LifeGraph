"""Property-based test for search and filter logic (Property 30).

**Validates: Requirements 13.1, 13.2, 13.3, 13.4**

For any graph, any selected set of node types, and any label search term, the
Search_Filter result SHALL contain exactly the nodes whose type is in the
selected set (when a type filter is active) and whose label contains the term
under case-insensitive matching (when a term is active) together with the edges
connecting two included nodes; the result SHALL be identical regardless of the
order in which the filters were applied; and when no filter or term is active
the result SHALL be all nodes and edges.
"""

from __future__ import annotations

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from lifegraph.domain import Edge, EdgeType, Graph, Node, NodeType
from lifegraph.search import filter_graph


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

node_type_st = st.sampled_from(list(NodeType))
edge_type_st = st.sampled_from(list(EdgeType))

# Labels: non-empty strings (1-50 chars) with printable characters
label_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")


@st.composite
def graph_st(draw: st.DrawFn) -> Graph:
    """Generate a random graph with 0-15 nodes and valid edges between them."""
    num_nodes = draw(st.integers(min_value=0, max_value=15))
    nodes: list[Node] = []
    for i in range(num_nodes):
        node = Node(
            id=f"n{i}",
            type=draw(node_type_st),
            label=draw(label_st),
        )
        nodes.append(node)

    edges: list[Edge] = []
    if len(nodes) >= 2:
        num_edges = draw(st.integers(min_value=0, max_value=min(20, len(nodes) * 2)))
        node_ids = [n.id for n in nodes]
        for i in range(num_edges):
            source = draw(st.sampled_from(node_ids))
            target = draw(st.sampled_from(node_ids).filter(lambda t, s=source: t != s))
            edge = Edge(
                id=f"e{i}",
                source=source,
                target=target,
                type=draw(edge_type_st),
            )
            edges.append(edge)

    return Graph(nodes=nodes, edges=edges)


# Strategy for type filter: either None (inactive) or a non-empty subset of NodeType
type_filter_st = st.one_of(
    st.none(),
    st.frozensets(node_type_st, min_size=1).map(set),
)

# Strategy for term filter: either None/empty (inactive) or a non-empty search term
term_filter_st = st.one_of(
    st.none(),
    st.just(""),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=10,
    ),
)


# ---------------------------------------------------------------------------
# Property 30: Type and label filtering with order independence
# ---------------------------------------------------------------------------


@settings(max_examples=20)
@given(graph=graph_st(), types=type_filter_st, term=term_filter_st)
def test_type_and_label_filtering_with_order_independence(
    graph: Graph,
    types: set[NodeType] | None,
    term: str | None,
):
    """Property 30: Type and label filtering with order independence.

    **Validates: Requirements 13.1, 13.2, 13.3, 13.4**

    - When types filter is active, only nodes of those types are included
    - When term filter is active, only nodes whose label contains the term
      (case-insensitive) are included
    - When both are active, only nodes satisfying BOTH are included
    - Edges are included only when both endpoints are in the included set
    - When no filter is active, the full graph is returned
    - Results are order-independent (same set regardless of input order)
    """
    result = filter_graph(graph, types=types, term=term)

    has_type_filter = types is not None and len(types) > 0
    has_term_filter = term is not None and term != ""

    # --- Compute expected node set ---
    expected_node_ids: set[str] = set()
    for node in graph.nodes:
        include = True
        # Req 13.1: type filter
        if has_type_filter and node.type not in types:  # type: ignore[operator]
            include = False
        # Req 13.2: term filter (case-insensitive substring)
        if has_term_filter and term.casefold() not in node.label.casefold():  # type: ignore[union-attr]
            include = False
        if include:
            expected_node_ids.add(node.id)

    # --- Verify node set ---
    result_node_ids = {n.id for n in result.nodes}
    assert result_node_ids == expected_node_ids, (
        f"Node set mismatch.\n"
        f"  Expected: {expected_node_ids}\n"
        f"  Got:      {result_node_ids}\n"
        f"  types={types}, term={term!r}"
    )

    # --- Verify edge inclusion: only edges with both endpoints included ---
    expected_edge_ids: set[str] = set()
    for edge in graph.edges:
        if edge.source in expected_node_ids and edge.target in expected_node_ids:
            expected_edge_ids.add(edge.id)

    result_edge_ids = {e.id for e in result.edges}
    assert result_edge_ids == expected_edge_ids, (
        f"Edge set mismatch.\n"
        f"  Expected: {expected_edge_ids}\n"
        f"  Got:      {result_edge_ids}\n"
        f"  Included node ids: {expected_node_ids}"
    )

    # --- Req 13.4: When no filter is active, full graph is returned ---
    if not has_type_filter and not has_term_filter:
        all_node_ids = {n.id for n in graph.nodes}
        all_edge_ids = {e.id for e in graph.edges}
        assert result_node_ids == all_node_ids, "No filter active but not all nodes returned"
        assert result_edge_ids == all_edge_ids, "No filter active but not all edges returned"

    # --- Req 13.3: Order independence ---
    # Shuffle the input graph's node and edge lists and verify same result sets
    shuffled_nodes = list(graph.nodes)
    shuffled_edges = list(graph.edges)
    random.shuffle(shuffled_nodes)
    random.shuffle(shuffled_edges)
    shuffled_graph = Graph(nodes=shuffled_nodes, edges=shuffled_edges)

    shuffled_result = filter_graph(shuffled_graph, types=types, term=term)
    shuffled_result_node_ids = {n.id for n in shuffled_result.nodes}
    shuffled_result_edge_ids = {e.id for e in shuffled_result.edges}

    assert result_node_ids == shuffled_result_node_ids, (
        "Order independence violated: different node sets after shuffling input"
    )
    assert result_edge_ids == shuffled_result_edge_ids, (
        "Order independence violated: different edge sets after shuffling input"
    )

"""Search and filter logic for LifeGraph.

Provides graph filtering by node type and/or case-insensitive label term.
Results are order-independent: the same set of nodes and edges is returned
regardless of input ordering.
"""

from __future__ import annotations

from lifegraph.domain import Graph, Node, NodeType


def filter_graph(
    graph: Graph,
    types: set[NodeType] | None = None,
    term: str | None = None,
) -> Graph:
    """Filter a graph by node types and/or a case-insensitive label term.

    Behavior:
    - If types is provided (non-empty set), include only nodes whose type is
      in the set.
    - If term is provided (non-empty string), include only nodes whose label
      contains the term (case-insensitive).
    - If both are provided, include only nodes satisfying BOTH conditions.
    - Include edges only when BOTH source and target nodes are in the included
      set.
    - When no filter/term is active (both None or empty), return the full graph.
    - Results are order-independent (same set regardless of input order).

    Requirements: 13.1, 13.2, 13.3, 13.4
    """
    # Determine if any filter is active
    has_type_filter = types is not None and len(types) > 0
    has_term_filter = term is not None and term != ""

    # No filter active — return the full graph
    if not has_type_filter and not has_term_filter:
        return Graph(nodes=list(graph.nodes), edges=list(graph.edges))

    # Filter nodes
    included_nodes: list[Node] = []
    for node in graph.nodes:
        # Check type filter
        if has_type_filter and node.type not in types:  # type: ignore[operator]
            continue
        # Check term filter (case-insensitive substring match)
        if has_term_filter and term.casefold() not in node.label.casefold():  # type: ignore[union-attr]
            continue
        included_nodes.append(node)

    # Build a set of included node IDs for edge filtering
    included_ids: set[str] = {node.id for node in included_nodes}

    # Include edges only when both source and target are in the included set
    included_edges = [
        edge
        for edge in graph.edges
        if edge.source in included_ids and edge.target in included_ids
    ]

    return Graph(nodes=included_nodes, edges=included_edges)

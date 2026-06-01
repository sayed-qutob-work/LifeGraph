"""Property-based test for deterministic serialization (Property 26).

**Validates: Requirements 10.5**

For any graph, root node, and serialization parameters, two invocations of the
Context_Serializer SHALL produce identical snapshot strings. This holds even
when the node/edge order in the Graph is shuffled.
"""

from __future__ import annotations

import random
from typing import List

from hypothesis import given, settings
from hypothesis import strategies as st

from lifegraph.domain import Edge, EdgeType, Graph, Node, NodeType
from lifegraph.serializer import ContextSerializer


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

node_type_st = st.sampled_from(list(NodeType))
edge_type_st = st.sampled_from(list(EdgeType))

# Labels: printable, non-empty, 1-50 chars (kept short to avoid char-budget
# trimming dominating the test)
label_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")


@st.composite
def graph_with_root_st(draw):
    """Generate a random graph with at least one node and a valid root node id.

    Produces between 1 and 15 nodes and 0 to 20 edges (no self-edges,
    endpoints always valid).
    """
    num_nodes = draw(st.integers(min_value=1, max_value=15))

    nodes: List[Node] = []
    for i in range(num_nodes):
        node = Node(
            id=f"node-{i:04d}",
            type=draw(node_type_st),
            label=draw(label_st),
        )
        nodes.append(node)

    node_ids = [n.id for n in nodes]

    # Generate edges between distinct existing nodes
    num_edges = draw(st.integers(min_value=0, max_value=min(20, num_nodes * (num_nodes - 1))))
    edges: List[Edge] = []
    seen_pairs = set()
    for i in range(num_edges):
        if num_nodes < 2:
            break
        source = draw(st.sampled_from(node_ids))
        target = draw(st.sampled_from(node_ids).filter(lambda t, s=source: t != s))
        pair = (source, target)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        edges.append(
            Edge(
                id=f"edge-{i:04d}",
                source=source,
                target=target,
                type=draw(edge_type_st),
            )
        )

    # Pick a root from the generated nodes
    root_id = draw(st.sampled_from(node_ids))

    return Graph(nodes=nodes, edges=edges), root_id


# Serializer parameters strategy
max_hops_st = st.integers(min_value=0, max_value=5)
max_nodes_st = st.integers(min_value=1, max_value=50)
max_chars_st = st.integers(min_value=100, max_value=10000)


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@settings(max_examples=20)
@given(
    graph_and_root=graph_with_root_st(),
    max_hops=max_hops_st,
    max_nodes=max_nodes_st,
    max_chars=max_chars_st,
)
def test_context_serialization_is_deterministic(
    graph_and_root, max_hops, max_nodes, max_chars
):
    """Property 26: Context serialization is deterministic.

    **Validates: Requirements 10.5**

    WHEN invoked twice with the same Graph_Store state and the same selection
    parameters, THE Context_Serializer SHALL produce identical context snapshots.

    Also verifies order-independence: shuffling the node/edge lists in the Graph
    does not change the output.
    """
    graph, root_id = graph_and_root

    serializer = ContextSerializer(
        max_hops=max_hops,
        max_nodes=max_nodes,
        max_chars=max_chars,
    )

    # --- Same invocation twice produces identical output ---
    result1 = serializer.serialize(graph, root_id)
    result2 = serializer.serialize(graph, root_id)

    assert result1 == result2, (
        "Two invocations with the same graph state and parameters produced "
        "different outputs.\n"
        f"First:  {result1!r}\n"
        f"Second: {result2!r}"
    )

    # --- Shuffled node/edge order produces identical output ---
    shuffled_nodes = list(graph.nodes)
    shuffled_edges = list(graph.edges)
    random.shuffle(shuffled_nodes)
    random.shuffle(shuffled_edges)

    shuffled_graph = Graph(nodes=shuffled_nodes, edges=shuffled_edges)

    result_shuffled = serializer.serialize(shuffled_graph, root_id)

    assert result1 == result_shuffled, (
        "Serialization output changed when node/edge order in the Graph was "
        "shuffled — the serializer is not order-independent.\n"
        f"Original order: {result1!r}\n"
        f"Shuffled order:  {result_shuffled!r}"
    )


# ---------------------------------------------------------------------------
# Property 24: Context traversal respects the hop bound
# ---------------------------------------------------------------------------

import re
from collections import deque
from typing import Dict, Set, Tuple


@st.composite
def connected_graph_with_root_and_hops(draw: st.DrawFn) -> Tuple[Graph, str, int]:
    """Generate a random connected graph with a designated root node and max_hops.

    Strategy:
    - Generate 2-15 nodes with unique ids
    - Build a spanning tree to ensure connectivity from the root
    - Add extra random edges for variety
    - Pick a max_hops value between 0 and 5
    """
    num_nodes = draw(st.integers(min_value=2, max_value=15))
    max_hops = draw(st.integers(min_value=0, max_value=5))

    # Generate nodes with unique ids
    node_ids = [f"n{i}" for i in range(num_nodes)]
    nodes: List[Node] = []
    for nid in node_ids:
        ntype = draw(node_type_st)
        label = f"Label_{nid}"
        nodes.append(Node(id=nid, type=ntype, label=label))

    # Root is always the first node
    root_id = node_ids[0]

    # Build a spanning tree to guarantee connectivity from root
    edges: List[Edge] = []
    edge_counter = 0
    connected: Set[str] = {root_id}
    remaining = list(node_ids[1:])
    draw(st.randoms()).shuffle(remaining)

    for nid in remaining:
        # Connect to a random already-connected node
        source = draw(st.sampled_from(sorted(connected)))
        etype = draw(edge_type_st)
        # Randomly choose direction
        if draw(st.booleans()):
            edges.append(Edge(id=f"e{edge_counter}", source=source, target=nid, type=etype))
        else:
            edges.append(Edge(id=f"e{edge_counter}", source=nid, target=source, type=etype))
        edge_counter += 1
        connected.add(nid)

    # Add some extra random edges for variety (0 to num_nodes extra edges)
    num_extra = draw(st.integers(min_value=0, max_value=num_nodes))
    for _ in range(num_extra):
        src = draw(st.sampled_from(node_ids))
        tgt = draw(st.sampled_from(node_ids))
        if src != tgt:
            etype = draw(edge_type_st)
            edges.append(Edge(id=f"e{edge_counter}", source=src, target=tgt, type=etype))
            edge_counter += 1

    graph = Graph(nodes=nodes, edges=edges)
    return graph, root_id, max_hops


def _compute_shortest_distances(graph: Graph, root_id: str) -> Dict[str, int]:
    """Compute shortest hop distances from root using BFS (undirected traversal)."""
    adjacency: Dict[str, Set[str]] = {node.id: set() for node in graph.nodes}
    for edge in graph.edges:
        if edge.source in adjacency and edge.target in adjacency:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)

    distances: Dict[str, int] = {root_id: 0}
    queue: deque[str] = deque([root_id])

    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor not in distances:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)

    return distances


def _parse_hop_annotations(output: str) -> List[Tuple[str, int]]:
    """Extract (label, hop_distance) pairs from the serializer output.

    Matches lines like: "  [Skill] Label_n2 (hop 1)"
    """
    pattern = re.compile(r"\[(\w+)\]\s+(.+?)\s+\(hop\s+(\d+)\)")
    results = []
    for match in pattern.finditer(output):
        label = match.group(2)
        hop = int(match.group(3))
        results.append((label, hop))
    return results


@settings(max_examples=20)
@given(data=connected_graph_with_root_and_hops())
def test_no_node_exceeds_max_hops(data: Tuple[Graph, str, int]) -> None:
    """Property 24: Context traversal respects the hop bound.

    **Validates: Requirements 10.3**

    For any graph, root node, and maximum hop distance, every node included in
    the snapshot SHALL have a shortest-path distance from the root no greater
    than the maximum hop distance.

    No node in the output has a hop annotation greater than max_hops.
    """
    graph, root_id, max_hops = data

    serializer = ContextSerializer(max_hops=max_hops, max_nodes=1000, max_chars=100000)
    output = serializer.serialize(graph, root_id)

    # Parse hop annotations from output
    annotations = _parse_hop_annotations(output)

    # Every annotated hop distance must be <= max_hops
    for label, hop in annotations:
        assert hop <= max_hops, (
            f"Node '{label}' has hop {hop} which exceeds max_hops={max_hops}"
        )


@settings(max_examples=20)
@given(data=connected_graph_with_root_and_hops())
def test_hop_annotations_match_true_shortest_path(
    data: Tuple[Graph, str, int],
) -> None:
    """Property 24 (supplementary): Hop annotations reflect true shortest paths.

    **Validates: Requirements 10.3**

    Each node's annotated hop distance equals its true shortest path distance
    from the root, confirming the BFS traversal is correct.
    """
    graph, root_id, max_hops = data

    serializer = ContextSerializer(max_hops=max_hops, max_nodes=1000, max_chars=100000)
    output = serializer.serialize(graph, root_id)

    # Compute true shortest distances
    true_distances = _compute_shortest_distances(graph, root_id)

    # Build a label -> node_id map
    label_to_id = {node.label: node.id for node in graph.nodes}

    # Parse hop annotations from output
    annotations = _parse_hop_annotations(output)

    for label, annotated_hop in annotations:
        node_id = label_to_id.get(label)
        assert node_id is not None, f"Label '{label}' not found in graph nodes"
        true_hop = true_distances.get(node_id)
        assert true_hop is not None, f"Node '{label}' not reachable from root"
        assert annotated_hop == true_hop, (
            f"Node '{label}' annotated as hop {annotated_hop} "
            f"but true shortest path is {true_hop}"
        )


@settings(max_examples=20)
@given(data=connected_graph_with_root_and_hops())
def test_all_reachable_within_hops_are_included(
    data: Tuple[Graph, str, int],
) -> None:
    """Property 24 (completeness): All reachable nodes within max_hops are included.

    **Validates: Requirements 10.3**

    When the budget is large enough to not trim, every node whose true
    shortest-path distance from root is <= max_hops must appear in output.
    """
    graph, root_id, max_hops = data

    # Use very large budget so no trimming occurs
    serializer = ContextSerializer(max_hops=max_hops, max_nodes=1000, max_chars=100000)
    output = serializer.serialize(graph, root_id)

    # Compute true shortest distances
    true_distances = _compute_shortest_distances(graph, root_id)

    # Parse hop annotations from output
    annotations = _parse_hop_annotations(output)
    included_labels = {label for label, _ in annotations}

    # Every node within max_hops should be included
    for node in graph.nodes:
        dist = true_distances.get(node.id)
        if dist is not None and dist <= max_hops:
            assert node.label in included_labels, (
                f"Node '{node.label}' (id={node.id}) is at distance {dist} "
                f"from root (max_hops={max_hops}) but was not included in output"
            )

"""Property-based test for JSON interchange round-trip (Property 27).

**Validates: Requirements 11.1, 11.2, 11.3**

When the JSON document produced by the Graph_API is deserialized, the resulting
node set and edge set SHALL be equivalent to the Graph_Store contents at the
time of serialization.
"""

from __future__ import annotations

import json
from typing import Dict, List, Set, Tuple

from hypothesis import given, settings
from hypothesis import strategies as st

from lifegraph.api import serialize_edge, serialize_graph, serialize_node
from lifegraph.domain import Edge, EdgeType, Graph, Node, NodeType


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

node_type_st = st.sampled_from(list(NodeType))
edge_type_st = st.sampled_from(list(EdgeType))

# Labels: printable, non-empty, 1-50 chars
label_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

# Attribute keys and values: 1-20 chars (kept short for test efficiency)
attr_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")

attr_value_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip() != "")

# Attributes: 0-5 entries for test efficiency
attributes_st = st.dictionaries(
    keys=attr_key_st,
    values=attr_value_st,
    min_size=0,
    max_size=5,
)


@st.composite
def graph_st(draw: st.DrawFn) -> Graph:
    """Generate a random Graph with valid nodes and edges.

    Produces 0-15 nodes and 0-20 edges (no self-edges, endpoints always valid).
    """
    num_nodes = draw(st.integers(min_value=0, max_value=15))

    nodes: List[Node] = []
    for i in range(num_nodes):
        node = Node(
            id=f"node-{i:04d}",
            type=draw(node_type_st),
            label=draw(label_st),
            attributes=draw(attributes_st),
        )
        nodes.append(node)

    node_ids = [n.id for n in nodes]

    # Generate edges between distinct existing nodes
    edges: List[Edge] = []
    if num_nodes >= 2:
        num_edges = draw(st.integers(min_value=0, max_value=min(20, num_nodes * (num_nodes - 1))))
        seen_pairs: Set[Tuple[str, str]] = set()
        for i in range(num_edges):
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

    return Graph(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Deserialization helper (reconstructs domain objects from JSON dict)
# ---------------------------------------------------------------------------


def deserialize_node(data: Dict) -> Node:
    """Reconstruct a Node from a serialized JSON dict."""
    return Node(
        id=data["id"],
        type=NodeType(data["type"]),
        label=data["label"],
        attributes=data["attributes"],
    )


def deserialize_edge(data: Dict) -> Edge:
    """Reconstruct an Edge from a serialized JSON dict."""
    return Edge(
        id=data["id"],
        source=data["source"],
        target=data["target"],
        type=EdgeType(data["type"]),
    )


def deserialize_graph(data: Dict) -> Graph:
    """Reconstruct a Graph from a serialized JSON dict."""
    return Graph(
        nodes=[deserialize_node(n) for n in data["nodes"]],
        edges=[deserialize_edge(e) for e in data["edges"]],
    )


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@settings(max_examples=20)
@given(graph=graph_st())
def test_json_interchange_round_trip(graph: Graph) -> None:
    """Property 27: JSON interchange round-trip.

    **Validates: Requirements 11.1, 11.2, 11.3**

    When the JSON document produced by the Graph_API is deserialized, the
    resulting node set and edge set SHALL be equivalent to the Graph_Store
    contents at the time of serialization.

    Steps:
    1. Serialize the graph using serialize_graph (same as GET /api/graph)
    2. Round-trip through JSON (serialize to string, parse back)
    3. Deserialize back into domain objects
    4. Verify equivalence of node sets and edge sets
    """
    # Step 1: Serialize using the API serialization functions
    serialized = serialize_graph(graph)

    # Step 2: Round-trip through actual JSON encoding/decoding
    json_str = json.dumps(serialized)
    deserialized_dict = json.loads(json_str)

    # Step 3: Reconstruct domain objects from the deserialized JSON
    reconstructed = deserialize_graph(deserialized_dict)

    # Step 4: Verify equivalence — node sets match
    original_nodes = {n.id: n for n in graph.nodes}
    reconstructed_nodes = {n.id: n for n in reconstructed.nodes}

    assert set(original_nodes.keys()) == set(reconstructed_nodes.keys()), (
        f"Node id sets differ.\n"
        f"Original: {sorted(original_nodes.keys())}\n"
        f"Reconstructed: {sorted(reconstructed_nodes.keys())}"
    )

    for node_id in original_nodes:
        orig = original_nodes[node_id]
        recon = reconstructed_nodes[node_id]
        assert orig.id == recon.id, f"Node id mismatch for {node_id}"
        assert orig.type == recon.type, (
            f"Node type mismatch for {node_id}: {orig.type} != {recon.type}"
        )
        assert orig.label == recon.label, (
            f"Node label mismatch for {node_id}: {orig.label!r} != {recon.label!r}"
        )
        assert orig.attributes == recon.attributes, (
            f"Node attributes mismatch for {node_id}: "
            f"{orig.attributes} != {recon.attributes}"
        )

    # Step 4b: Verify equivalence — edge sets match
    original_edges = {e.id: e for e in graph.edges}
    reconstructed_edges = {e.id: e for e in reconstructed.edges}

    assert set(original_edges.keys()) == set(reconstructed_edges.keys()), (
        f"Edge id sets differ.\n"
        f"Original: {sorted(original_edges.keys())}\n"
        f"Reconstructed: {sorted(reconstructed_edges.keys())}"
    )

    for edge_id in original_edges:
        orig = original_edges[edge_id]
        recon = reconstructed_edges[edge_id]
        assert orig.id == recon.id, f"Edge id mismatch for {edge_id}"
        assert orig.source == recon.source, (
            f"Edge source mismatch for {edge_id}: {orig.source} != {recon.source}"
        )
        assert orig.target == recon.target, (
            f"Edge target mismatch for {edge_id}: {orig.target} != {recon.target}"
        )
        assert orig.type == recon.type, (
            f"Edge type mismatch for {edge_id}: {orig.type} != {recon.type}"
        )


@settings(max_examples=20)
@given(graph=graph_st())
def test_json_document_contains_all_required_fields(graph: Graph) -> None:
    """Property 27 (supplementary): JSON document structure completeness.

    **Validates: Requirements 11.2**

    THE JSON document SHALL represent every node with its identifier, type,
    label, and attributes, and every edge with its identifier, source, target,
    and type.
    """
    serialized = serialize_graph(graph)

    # Verify top-level structure
    assert "nodes" in serialized, "Serialized graph missing 'nodes' key"
    assert "edges" in serialized, "Serialized graph missing 'edges' key"
    assert len(serialized["nodes"]) == len(graph.nodes), (
        f"Node count mismatch: {len(serialized['nodes'])} != {len(graph.nodes)}"
    )
    assert len(serialized["edges"]) == len(graph.edges), (
        f"Edge count mismatch: {len(serialized['edges'])} != {len(graph.edges)}"
    )

    # Verify each node has all required fields
    for node_dict in serialized["nodes"]:
        assert "id" in node_dict, f"Node missing 'id' field: {node_dict}"
        assert "type" in node_dict, f"Node missing 'type' field: {node_dict}"
        assert "label" in node_dict, f"Node missing 'label' field: {node_dict}"
        assert "attributes" in node_dict, f"Node missing 'attributes' field: {node_dict}"

    # Verify each edge has all required fields
    for edge_dict in serialized["edges"]:
        assert "id" in edge_dict, f"Edge missing 'id' field: {edge_dict}"
        assert "source" in edge_dict, f"Edge missing 'source' field: {edge_dict}"
        assert "target" in edge_dict, f"Edge missing 'target' field: {edge_dict}"
        assert "type" in edge_dict, f"Edge missing 'type' field: {edge_dict}"

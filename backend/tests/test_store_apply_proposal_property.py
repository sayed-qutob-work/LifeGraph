"""Property-based test for edge endpoint resolution during proposal application.

Property 9: Edge endpoints resolve to identity-matched nodes.

**Validates: Requirements 4.4**

For any proposal, after it is applied every resulting edge's source and target
SHALL reference nodes whose normalized label and type match the edge's
referenced endpoints, reusing a pre-existing identity-matched node when one
exists and creating it beforehand when none exists.
"""

from __future__ import annotations

import os
import tempfile
import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from lifegraph.domain import (
    EdgeType,
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


def _make_fresh_store() -> GraphStore:
    """Create a fresh GraphStore backed by a temp file that does not yet exist."""
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.db")
    return GraphStore(db_path=db_path)


def _identity(label: str, node_type: NodeType) -> tuple[str, NodeType]:
    """Compute the deduplication identity used by the store: (normalize, type)."""
    return (normalize(label), node_type)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

node_type_st = st.sampled_from(list(NodeType))
edge_type_st = st.sampled_from(list(EdgeType))


@st.composite
def label_st(draw) -> str:
    """Generate short labels that frequently collide after normalization.

    Uses a tiny alphabet plus random casing and surrounding whitespace so that
    distinct generated labels often share the same normalized identity. This
    exercises both the "reuse existing identity-matched node" and the
    "create a new node" branches of endpoint resolution. The result is always
    non-blank after stripping.
    """
    base = draw(st.text(alphabet="abcxyz", min_size=1, max_size=4))
    if draw(st.booleans()):
        base = base.upper()
    lead = draw(st.sampled_from(["", " ", "  "]))
    trail = draw(st.sampled_from(["", " ", "  "]))
    return lead + base + trail


# A node spec is a (label, type) pair.
node_spec_st = st.tuples(label_st(), node_type_st)

# An edge spec references its endpoints by (label, type) and carries a type.
edge_spec_st = st.tuples(
    label_st(),  # source label
    node_type_st,  # source type
    label_st(),  # target label
    node_type_st,  # target type
    edge_type_st,  # edge type
)


@st.composite
def scenario_st(draw):
    """Generate a (pre_existing_nodes, proposed_nodes, proposed_edges) scenario."""
    pre_existing = draw(st.lists(node_spec_st, max_size=5))
    proposed_nodes = draw(st.lists(node_spec_st, max_size=5))
    proposed_edges = draw(st.lists(edge_spec_st, max_size=6))
    return pre_existing, proposed_nodes, proposed_edges


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@settings(max_examples=20, deadline=None)
@given(scenario=scenario_st())
def test_edge_endpoints_resolve_to_identity_matched_nodes(scenario):
    """Property 9: Edge endpoints resolve to identity-matched nodes.

    For any proposal, after it is applied every resulting edge's source and
    target SHALL reference nodes whose normalized label and type match the
    edge's referenced endpoints, reusing a pre-existing identity-matched node
    when one exists and creating it beforehand when none exists.

    **Validates: Requirements 4.4**
    """
    pre_existing, proposed_node_specs, proposed_edge_specs = scenario

    store = _make_fresh_store()
    try:
        # 1. Seed the store with pre-existing nodes so some edge endpoints will
        #    resolve by reusing them.
        for label, node_type in pre_existing:
            store.upsert_node(label, node_type)

        # Record the identity -> id map of nodes that exist BEFORE applying the
        # proposal. Endpoints matching these identities must reuse the same id.
        pre_ids: dict[tuple[str, NodeType], str] = {}
        for node in store.get_graph().nodes:
            pre_ids[_identity(node.label, node.type)] = node.id

        # 2. Build the proposal.
        proposal = ProposedGraph(
            nodes=[
                ProposedNode(type=node_type, label=label)
                for (label, node_type) in proposed_node_specs
            ],
            edges=[
                ProposedEdge(
                    source_label=s_label,
                    source_type=s_type,
                    target_label=t_label,
                    target_type=t_type,
                    type=e_type,
                )
                for (s_label, s_type, t_label, t_type, e_type) in proposed_edge_specs
            ],
        )

        # 3. Apply the proposal.
        result = store.apply_proposal(proposal)

        # The store implementation skips an edge whose source and target resolve
        # to the same node (identity collision). The non-skipped proposed edges,
        # in order, correspond one-to-one with the result edges.
        expected_edges = [
            e
            for e in proposal.edges
            if _identity(e.source_label, e.source_type)
            != _identity(e.target_label, e.target_type)
        ]
        assert len(result.edges) == len(expected_edges), (
            f"Expected {len(expected_edges)} resulting edges, "
            f"got {len(result.edges)}"
        )

        # 4. Every endpoint identity referenced by the proposal must exist in the
        #    store after application (created beforehand when none existed).
        for proposed_edge in proposal.edges:
            src = store.find_node(proposed_edge.source_label, proposed_edge.source_type)
            tgt = store.find_node(proposed_edge.target_label, proposed_edge.target_type)
            assert src is not None, (
                f"Source endpoint ({proposed_edge.source_label!r}, "
                f"{proposed_edge.source_type}) was not resolved/created"
            )
            assert tgt is not None, (
                f"Target endpoint ({proposed_edge.target_label!r}, "
                f"{proposed_edge.target_type}) was not resolved/created"
            )

        # 5. For each resulting edge (paired with its proposed edge by order),
        #    verify the referenced nodes' identities match and that pre-existing
        #    identities were reused.
        for result_edge, proposed_edge in zip(result.edges, expected_edges):
            src_node = store.get_node(result_edge.source)
            tgt_node = store.get_node(result_edge.target)

            assert src_node is not None, (
                f"Edge source id {result_edge.source!r} not found in store"
            )
            assert tgt_node is not None, (
                f"Edge target id {result_edge.target!r} not found in store"
            )

            src_identity = _identity(src_node.label, src_node.type)
            tgt_identity = _identity(tgt_node.label, tgt_node.type)

            # Source/target identities must match the proposed endpoints.
            assert src_identity == _identity(
                proposed_edge.source_label, proposed_edge.source_type
            ), (
                f"Source identity {src_identity} does not match proposed "
                f"({normalize(proposed_edge.source_label)!r}, "
                f"{proposed_edge.source_type})"
            )
            assert tgt_identity == _identity(
                proposed_edge.target_label, proposed_edge.target_type
            ), (
                f"Target identity {tgt_identity} does not match proposed "
                f"({normalize(proposed_edge.target_label)!r}, "
                f"{proposed_edge.target_type})"
            )

            # The edge type is preserved.
            assert result_edge.type == proposed_edge.type

            # Reuse: if a node with this identity existed before applying, the
            # resolved endpoint must reuse that exact identifier.
            if src_identity in pre_ids:
                assert result_edge.source == pre_ids[src_identity], (
                    f"Source identity {src_identity} should reuse pre-existing "
                    f"node {pre_ids[src_identity]!r}, got {result_edge.source!r}"
                )
            if tgt_identity in pre_ids:
                assert result_edge.target == pre_ids[tgt_identity], (
                    f"Target identity {tgt_identity} should reuse pre-existing "
                    f"node {pre_ids[tgt_identity]!r}, got {result_edge.target!r}"
                )
    finally:
        store.close()

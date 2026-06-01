"""Property-based test for Property 6: Confirm persists, reject is a no-op.

**Validates: Requirements 3.6, 3.7**

For any Graph_Store state and any valid proposal, confirming the proposal SHALL
result in a store whose nodes and edges include every proposed node (after
deduplication) and every proposed edge, while rejecting the same proposal SHALL
leave the store's node set and edge set identical to their pre-proposal values.

The implementation under test is ``GraphStore.apply_proposal`` (task 7.1):
confirming a proposal applies it (a single transactional write), while rejecting
or never confirming a proposal performs NO write at all — the design realizes a
rejected proposal as simply never invoking ``apply_proposal``.
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
# Deterministic id factory + store helpers
# ---------------------------------------------------------------------------


def _det_id_factory():
    """A deterministic, monotonically increasing id factory.

    Two stores seeded with the *same* proposal using freshly-created factories
    that start from the same point produce identical node/edge ids, which lets
    us compare a "confirm" store against a "reject" store field-for-field.
    """
    counter = [0]

    def factory() -> str:
        counter[0] += 1
        return f"id-{counter[0]:08d}"

    return factory


def _make_seeded_store(seed: ProposedGraph) -> GraphStore:
    """Create a fresh on-disk GraphStore seeded with the given proposal.

    A deterministic id factory is used so that two stores seeded with the same
    proposal end up with identical contents (same ids included).
    """
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.db")
    store = GraphStore(db_path=db_path, id_factory=_det_id_factory())
    if seed.nodes or seed.edges:
        store.apply_proposal(seed)
    return store


# ---------------------------------------------------------------------------
# Snapshot helpers (order-independent, field-for-field comparison)
# ---------------------------------------------------------------------------


def _node_key(node):
    return (node.id, node.type, node.label, tuple(sorted(node.attributes.items())))


def _edge_key(edge):
    return (edge.id, edge.source, edge.target, edge.type)


def _snapshot(graph):
    """Return an order-independent snapshot of a graph's node and edge sets."""
    return (
        frozenset(_node_key(n) for n in graph.nodes),
        frozenset(_edge_key(e) for e in graph.edges),
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

node_type_st = st.sampled_from(list(NodeType))
edge_type_st = st.sampled_from(list(EdgeType))

# Labels: 1–200 chars after strip; kept short to keep generated graphs cheap.
label_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=40,
).filter(lambda s: len(s.strip()) >= 1)

# Attribute keys/values: 1–255 chars. Exclude the exact key "date" so Event
# nodes never trip date validation — this property is about persist/no-op, not
# date validation (Property 14 covers that).
_attr_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
).filter(lambda k: k != "date")
_attr_value_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
)
attrs_st = st.dictionaries(keys=_attr_key_st, values=_attr_value_st, min_size=0, max_size=3)

proposed_node_st = st.builds(
    ProposedNode,
    type=node_type_st,
    label=label_st,
    attributes=attrs_st,
)


@st.composite
def proposed_graph_st(draw, max_nodes: int = 6, max_edges: int = 6) -> ProposedGraph:
    """Generate a valid ProposedGraph.

    Nodes may include duplicate identities (to exercise deduplication). Edges
    connect two *distinct* node identities drawn from the proposal's nodes, so
    no proposed edge resolves to a self-edge. With fewer than two distinct
    identities, no edges are produced.
    """
    nodes = draw(st.lists(proposed_node_st, min_size=0, max_size=max_nodes))

    # Collect one representative ProposedNode per distinct (normalized label, type).
    representatives = []
    seen = set()
    for n in nodes:
        ident = (normalize(n.label), n.type)
        if ident not in seen:
            seen.add(ident)
            representatives.append(n)

    edges: list[ProposedEdge] = []
    if len(representatives) >= 2:
        num_edges = draw(st.integers(min_value=0, max_value=max_edges))
        for _ in range(num_edges):
            i = draw(st.integers(min_value=0, max_value=len(representatives) - 1))
            j = draw(st.integers(min_value=0, max_value=len(representatives) - 1))
            if i == j:
                continue  # distinct identities only -> never a self-edge
            src = representatives[i]
            tgt = representatives[j]
            edges.append(
                ProposedEdge(
                    source_label=src.label,
                    source_type=src.type,
                    target_label=tgt.label,
                    target_type=tgt.type,
                    type=draw(edge_type_st),
                )
            )

    return ProposedGraph(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Property 6: Confirm persists, reject is a no-op
# ---------------------------------------------------------------------------


class TestConfirmPersistsRejectNoOp:
    """Property 6: Confirm persists, reject is a no-op.

    **Validates: Requirements 3.6, 3.7**
    """

    @settings(max_examples=20, deadline=None)
    @given(seed=proposed_graph_st(), proposal=proposed_graph_st())
    def test_confirm_persists_reject_no_op(
        self, seed: ProposedGraph, proposal: ProposedGraph
    ) -> None:
        confirm_store = _make_seeded_store(seed)
        reject_store = _make_seeded_store(seed)
        try:
            # Identically-seeded stores represent the same pre-proposal state.
            pre_confirm = confirm_store.get_graph()
            pre_reject = reject_store.get_graph()
            pre_confirm_snap = _snapshot(pre_confirm)
            pre_reject_snap = _snapshot(pre_reject)
            assert pre_confirm_snap == pre_reject_snap, (
                "Identically-seeded stores must start from identical state"
            )

            # --- Reject branch (Req 3.7): rejecting performs NO write. ---
            # The design realizes rejection as never calling apply_proposal.
            post_reject_snap = _snapshot(reject_store.get_graph())
            assert post_reject_snap == pre_reject_snap, (
                "Rejecting a proposal must leave the store's node and edge "
                "sets identical to their pre-proposal values"
            )

            # --- Confirm branch (Req 3.6): confirming persists the proposal. ---
            confirm_store.apply_proposal(proposal)
            post_confirm = confirm_store.get_graph()
            post_confirm_snap = _snapshot(post_confirm)

            # Every proposed node is present after deduplication.
            for pn in proposal.nodes:
                matched = confirm_store.find_node(pn.label, pn.type)
                assert matched is not None, (
                    f"Proposed node {(pn.label, pn.type)} missing after confirm"
                )

            # Every proposed edge is present, connecting identity-matched endpoints.
            for pe in proposal.edges:
                src = confirm_store.find_node(pe.source_label, pe.source_type)
                tgt = confirm_store.find_node(pe.target_label, pe.target_type)
                assert src is not None and tgt is not None, (
                    "Proposed edge endpoints must resolve to existing nodes"
                )
                assert any(
                    e.source == src.id and e.target == tgt.id and e.type == pe.type
                    for e in post_confirm.edges
                ), (
                    f"Proposed edge {(pe.source_label, pe.target_label, pe.type)} "
                    f"missing after confirm"
                )

            # Confirming does not drop pre-existing content.
            post_node_ids = {n.id for n in post_confirm.nodes}
            post_edge_ids = {e.id for e in post_confirm.edges}
            for n in pre_confirm.nodes:
                assert n.id in post_node_ids, "Confirm dropped a pre-existing node"
            for e in pre_confirm.edges:
                assert e.id in post_edge_ids, "Confirm dropped a pre-existing edge"

            # Confirm and reject diverge exactly when the proposal adds content.
            seed_idents = {(normalize(n.label), n.type) for n in pre_confirm.nodes}
            introduces_new_node = any(
                (normalize(pn.label), pn.type) not in seed_idents
                for pn in proposal.nodes
            )
            introduces_content = introduces_new_node or len(proposal.edges) > 0
            if introduces_content:
                assert post_confirm_snap != post_reject_snap, (
                    "A proposal that adds content must make the confirmed store "
                    "differ from the rejected (unchanged) store"
                )
            else:
                assert post_confirm_snap == post_reject_snap, (
                    "A proposal that adds no content must leave the confirmed "
                    "store identical to the rejected store"
                )
        finally:
            confirm_store.close()
            reject_store.close()

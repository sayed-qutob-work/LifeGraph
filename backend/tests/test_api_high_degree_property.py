"""Property-based test for the high-degree delete warning threshold (Property 19).

**Validates: Requirements 8.7**

Property 19: For any node, the Graph_Editor SHALL require a delete confirmation
warning if and only if the node has 5 or more connected edges.

The delete-warning gate is driven by ``GET /api/nodes/{id}/edges``, which returns
the count of incident edges for a node. The Graph_Editor warns *iff* that count is
5 or more. This test exercises the backend endpoint (task 12.3) directly via the
Flask test client and verifies that:

1. The reported incident-edge count equals the true number of connected edges
   (independent of edges elsewhere in the graph), and
2. The warning decision derived from the count (``count >= 5``) holds *if and only
   if* the node actually has 5 or more connected edges.
"""

from __future__ import annotations

from typing import List, Tuple

from hypothesis import example, given, settings
from hypothesis import strategies as st

from lifegraph.api import create_app


# Threshold from Requirement 8.7 / Property 19: warn iff >= 5 connected edges.
WARNING_THRESHOLD = 5


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

edge_type_st = st.sampled_from(
    [
        "requires",
        "supports",
        "conflicts_with",
        "motivated_by",
        "leads_to",
        "part_of",
        "owned_by",
        "blocks",
        "related_to",
    ]
)


@st.composite
def center_graph_plan(draw: st.DrawFn) -> Tuple[int, List[bool], List[str], int]:
    """Generate a build plan for a star graph around a center node.

    Returns
    -------
    (degree, directions, edge_types, noise_edges)
        - ``degree``: number of edges connecting the center node to a distinct
          peripheral node (0–12, spanning both sides of the threshold of 5).
        - ``directions``: per center-edge orientation flag (center as source when
          True, else center as target). Length == ``degree``.
        - ``edge_types``: per center-edge type. Length == ``degree``.
        - ``noise_edges``: number of additional edges between *other* node pairs
          that do NOT touch the center, used to confirm the count reflects only
          the center's incident edges.
    """
    degree = draw(st.integers(min_value=0, max_value=12))
    directions = draw(st.lists(st.booleans(), min_size=degree, max_size=degree))
    edge_types = draw(st.lists(edge_type_st, min_size=degree, max_size=degree))
    noise_edges = draw(st.integers(min_value=0, max_value=4))
    return degree, directions, edge_types, noise_edges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_node(client, label: str, node_type: str = "Skill") -> str:
    """Create a node via the API and return its id."""
    resp = client.post("/api/nodes", json={"label": label, "type": node_type})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["id"]


def _create_edge(client, source: str, target: str, edge_type: str) -> None:
    """Create an edge via the API, asserting success."""
    resp = client.post(
        "/api/edges", json={"source": source, "target": target, "type": edge_type}
    )
    assert resp.status_code == 201, resp.get_json()


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@settings(max_examples=24)
@given(plan=center_graph_plan())
# Pin the threshold boundary so degrees 4, 5, and the empty case are always tried.
@example(plan=(4, [True, False, True, False], ["supports"] * 4, 0))
@example(plan=(5, [True, False, True, False, True], ["supports"] * 5, 0))
@example(plan=(0, [], [], 3))
def test_high_degree_delete_warning_threshold(
    plan: Tuple[int, List[bool], List[str], int],
) -> None:
    """Property 19: High-degree delete warning threshold.

    **Validates: Requirements 8.7**

    The warning is required if and only if the node has 5 or more connected edges.
    """
    degree, directions, edge_types, noise_edges = plan

    # Fresh in-memory store per example.
    app = create_app({"db_path": ":memory:", "TESTING": True})
    client = app.test_client()

    # Center node whose incident-edge count drives the warning.
    center_id = _create_node(client, "center")

    # Build exactly `degree` edges between the center and distinct peripheral nodes.
    for i in range(degree):
        peripheral_id = _create_node(client, f"peripheral-{i}")
        if directions[i]:
            _create_edge(client, center_id, peripheral_id, edge_types[i])
        else:
            _create_edge(client, peripheral_id, center_id, edge_types[i])

    # Add noise edges between *other* node pairs that never touch the center,
    # to confirm the count reflects only the center's incident edges.
    for j in range(noise_edges):
        a_id = _create_node(client, f"noise-a-{j}")
        b_id = _create_node(client, f"noise-b-{j}")
        _create_edge(client, a_id, b_id, "related_to")

    # Query the endpoint that drives the delete-warning gate.
    resp = client.get(f"/api/nodes/{center_id}/edges")
    assert resp.status_code == 200, resp.get_json()
    reported_count = resp.get_json()["count"]

    # (1) The endpoint count equals the true number of connected edges, regardless
    #     of unrelated noise edges elsewhere in the graph.
    assert reported_count == degree, (
        f"Reported incident-edge count {reported_count} != actual degree {degree} "
        f"(noise_edges={noise_edges})"
    )

    # (2) The warning is required if and only if the node has >= 5 connected edges.
    warning_required = reported_count >= WARNING_THRESHOLD
    actually_high_degree = degree >= WARNING_THRESHOLD
    assert warning_required == actually_high_degree, (
        f"Warning decision ({warning_required}) does not match the high-degree "
        f"condition ({actually_high_degree}) for degree {degree}"
    )

    app.config["STORE"].close()

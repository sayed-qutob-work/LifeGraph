"""Property-based test for manual node label and type validation (Property 18).

**Validates: Requirements 8.1, 8.3, 8.4, 8.5**

For any manual node submission to POST /api/nodes, the Graph_API SHALL create the
node when its trimmed label is 1–100 characters and its type is in the
Node_Type_Set, and SHALL otherwise reject the submission (retaining nothing in the
Graph_Store, leaving it unchanged) when the type is invalid, the trimmed label is
empty, or the trimmed label exceeds 100 characters.

This test drives the real Flask app (in-memory SQLite store) via its test client.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from lifegraph.api import create_app
from lifegraph.domain import NODE_TYPE_VALUES, NodeType, normalize
from lifegraph.validation import MANUAL_LABEL_MAX, MANUAL_LABEL_MIN


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Text safe to ship through JSON: exclude surrogates ("Cs") and control chars
# ("Cc", which also removes \t, \n, \r). Space (Zs) is retained so that
# whitespace-only and surrounding-whitespace cases are still exercised.
_safe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    min_size=0,
    max_size=130,
)

# A label strategy that intentionally spans every classification branch:
# empty, whitespace-only, valid (with and without surrounding whitespace),
# and over-the-limit (>100 trimmed).
label_st = st.one_of(
    st.just(""),  # empty -> reject (8.4)
    st.text(alphabet=" ", min_size=1, max_size=6),  # whitespace only -> reject (8.4)
    st.text(  # likely valid trimmed length 1..100 (8.1)
        alphabet=st.characters(blacklist_categories=("Cs", "Cc", "Zs")),
        min_size=1,
        max_size=100,
    ),
    # valid content padded with surrounding spaces (trimming required, 8.1)
    st.builds(
        lambda core, lpad, rpad: " " * lpad + core + " " * rpad,
        st.text(
            alphabet=st.characters(blacklist_categories=("Cs", "Cc", "Zs")),
            min_size=1,
            max_size=80,
        ),
        st.integers(min_value=0, max_value=5),
        st.integers(min_value=0, max_value=5),
    ),
    st.text(  # likely too long -> reject (8.5)
        alphabet=st.characters(blacklist_categories=("Cs", "Cc", "Zs")),
        min_size=101,
        max_size=130,
    ),
    _safe_text,  # fully general fallback
)

# A type strategy spanning valid and invalid values, including case variants
# (e.g. "skill" != "Skill") which must be rejected (8.3).
type_st = st.one_of(
    st.sampled_from(sorted(NODE_TYPE_VALUES)),  # valid
    st.sampled_from(
        ["InvalidType", "skill", "SKILL", "Node", "", "goal", "person ", "Tasks"]
    ),  # invalid
    st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=12),
)


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@settings(max_examples=40)
@given(label=label_st, node_type=type_st)
def test_manual_node_label_and_type_validation(label: str, node_type: str) -> None:
    """Property 18: Manual node label and type validation.

    **Validates: Requirements 8.1, 8.3, 8.4, 8.5**

    Submitting a manual node:
    - is accepted (201) and persisted iff the trimmed label is 1–100 chars AND
      the type is in the Node_Type_Set (Req 8.1);
    - is otherwise rejected (400) with the Graph_Store left unchanged when the
      type is invalid (Req 8.3), the trimmed label is empty (Req 8.4), or the
      trimmed label exceeds 100 chars (Req 8.5).
    """
    # Fresh, isolated in-memory store per example.
    app = create_app({"db_path": ":memory:", "TESTING": True})
    client = app.test_client()
    store = app.config["STORE"]

    # Seed an anchor node so "store unchanged" is a meaningful assertion and
    # not merely "store still empty".
    store.upsert_node("Anchor", NodeType.PERSON)
    initial_nodes = {
        (n.id, n.label, n.type, tuple(sorted(n.attributes.items())))
        for n in store.get_graph().nodes
    }

    # Mirror the endpoint's validation logic exactly (validate_manual_label
    # trims then bounds-checks; the type is checked against NODE_TYPE_VALUES).
    trimmed = label.strip()
    label_ok = MANUAL_LABEL_MIN <= len(trimmed) <= MANUAL_LABEL_MAX
    type_ok = node_type in NODE_TYPE_VALUES
    should_create = label_ok and type_ok

    resp = client.post("/api/nodes", json={"label": label, "type": node_type})

    if should_create:
        assert resp.status_code == 201, (
            f"Expected 201 for valid submission "
            f"(label={label!r}, type={node_type!r}), got {resp.status_code}: "
            f"{resp.get_json()}"
        )
        data = resp.get_json()
        # The created node stores the trimmed label and the submitted type.
        assert data["label"] == trimmed
        assert data["type"] == node_type

        nodes = store.get_graph().nodes
        # The submitted node now exists by identity (normalized label + type).
        assert any(
            normalize(n.label) == normalize(trimmed) and n.type.value == node_type
            for n in nodes
        ), "Created node not found in the store by identity"
        # The pre-existing anchor node is still present.
        assert any(
            n.label == "Anchor" and n.type is NodeType.PERSON for n in nodes
        ), "Pre-existing node disappeared after a valid create"
    else:
        # Rejected: a client validation error (400) and no write occurred.
        assert resp.status_code == 400, (
            f"Expected 400 for invalid submission "
            f"(label={label!r}, type={node_type!r}), got {resp.status_code}: "
            f"{resp.get_json()}"
        )
        final_nodes = {
            (n.id, n.label, n.type, tuple(sorted(n.attributes.items())))
            for n in store.get_graph().nodes
        }
        assert final_nodes == initial_nodes, (
            "Graph_Store changed after a rejected submission "
            f"(label={label!r}, type={node_type!r})"
        )

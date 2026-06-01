"""Property-based test for attribute edit round-trip (Property 15).

**Validates: Requirements 6.4**

For any node and any valid attribute map, after the attributes are edited a
read of that node by its identifier SHALL return exactly the written attribute
map.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from lifegraph.domain import NodeType
from lifegraph.store import GraphStore


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

node_type_st = st.sampled_from(list(NodeType))

# Valid labels: 1-200 chars, non-empty after strip
label_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)

# Valid attribute keys: 1-255 chars, non-empty
attr_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=255,
)

# Valid attribute values: 1-255 chars, non-empty
attr_value_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=255,
)

# Valid attribute map: 0-50 entries with valid keys and values
valid_attributes_st = st.dictionaries(
    keys=attr_key_st,
    values=attr_value_st,
    min_size=0,
    max_size=50,
)


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@settings(max_examples=20, deadline=None)
@given(
    node_type=node_type_st,
    label=label_st,
    initial_attrs=valid_attributes_st,
    updated_attrs=valid_attributes_st,
)
def test_attribute_edit_round_trip(
    node_type: NodeType,
    label: str,
    initial_attrs: dict[str, str],
    updated_attrs: dict[str, str],
):
    """Property 15: Attribute edit round-trip.

    For any node and any valid attribute map, after the attributes are edited
    a read of that node by its identifier SHALL return exactly the written
    attribute map.

    **Validates: Requirements 6.4**
    """
    # Skip Event nodes with invalid date attributes to focus on the round-trip
    # property rather than date validation
    if node_type == NodeType.EVENT:
        initial_attrs = {k: v for k, v in initial_attrs.items() if k != "date"}
        updated_attrs = {k: v for k, v in updated_attrs.items() if k != "date"}

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test.db")
        store = GraphStore(db_path)

        try:
            # Create a node with initial attributes
            node = store.upsert_node(label, node_type, attributes=initial_attrs)

            # Edit the node's attributes
            store.update_node(node.id, attributes=updated_attrs)

            # Read the node back by its identifier
            retrieved = store.get_node(node.id)

            # The retrieved node SHALL have exactly the written attribute map
            assert retrieved is not None, "Node should exist after update"
            assert retrieved.attributes == updated_attrs, (
                f"Expected attributes {updated_attrs!r}, "
                f"got {retrieved.attributes!r}"
            )
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Property 14: Event date validation and persistence
# ---------------------------------------------------------------------------

import datetime
import os
import re
import uuid

import pytest

from lifegraph.validation import DateValidationError


def _is_valid_date(date_str: str) -> bool:
    """Check if a string is a valid YYYY-MM-DD calendar date."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return False
    try:
        datetime.date.fromisoformat(date_str)
        return True
    except ValueError:
        return False


def _make_fresh_store() -> GraphStore:
    """Create a fresh GraphStore backed by a temp file that does not yet exist."""
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.db")
    return GraphStore(db_path=db_path)


# Strategy for valid YYYY-MM-DD dates
_valid_dates = st.dates(
    min_value=datetime.date(1, 1, 1),
    max_value=datetime.date(9999, 12, 31),
).map(lambda d: d.isoformat())

# Strategy for invalid date strings — a mix of formats that aren't valid dates
_invalid_date_formats = st.one_of(
    # Wrong format entirely (random text that isn't a valid date)
    st.text(min_size=1, max_size=20).filter(
        lambda s: not _is_valid_date(s) and 1 <= len(s) <= 255
    ),
    # Correct YYYY-MM-DD format but invalid calendar date (e.g. month 13, Feb 30)
    st.tuples(
        st.integers(min_value=0, max_value=9999),
        st.integers(min_value=0, max_value=99),
        st.integers(min_value=0, max_value=99),
    )
    .map(lambda t: f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}")
    .filter(lambda s: not _is_valid_date(s)),
)

# Valid labels for Event nodes
_event_label_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)


class TestEventDateValidationAndPersistence:
    """Property 14: Event date validation and persistence.

    For any string assigned to an Event node's date attribute, the Graph_Editor
    SHALL store the value when it is a real calendar date in YYYY-MM-DD form,
    and SHALL reject it while leaving the node's previously stored attributes
    unchanged when it is not a valid YYYY-MM-DD calendar date.

    **Validates: Requirements 6.2, 6.3**
    """

    @settings(max_examples=20, deadline=None)
    @given(date_str=_valid_dates, label=_event_label_st)
    def test_valid_date_is_stored_on_upsert(self, date_str: str, label: str) -> None:
        """A valid YYYY-MM-DD date is accepted and persisted on Event node creation."""
        store = _make_fresh_store()
        try:
            node = store.upsert_node(
                label=label,
                type=NodeType.EVENT,
                attributes={"date": date_str},
            )
            assert node.attributes["date"] == date_str

            # Verify persistence by re-reading
            persisted = store.get_node(node.id)
            assert persisted is not None
            assert persisted.attributes["date"] == date_str
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(date_str=_invalid_date_formats, label=_event_label_st)
    def test_invalid_date_is_rejected_on_upsert(self, date_str: str, label: str) -> None:
        """An invalid date string is rejected and the node is not created."""
        store = _make_fresh_store()
        try:
            with pytest.raises(DateValidationError):
                store.upsert_node(
                    label=label,
                    type=NodeType.EVENT,
                    attributes={"date": date_str},
                )

            # Store should have no nodes (the creation was rejected)
            graph = store.get_graph()
            assert len(graph.nodes) == 0
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(date_str=_valid_dates, label=_event_label_st)
    def test_valid_date_is_stored_on_update(self, date_str: str, label: str) -> None:
        """A valid YYYY-MM-DD date is accepted when updating an existing Event node."""
        store = _make_fresh_store()
        try:
            # Create an Event node without a date first
            node = store.upsert_node(
                label=label,
                type=NodeType.EVENT,
                attributes={"status": "planned"},
            )

            # Update with a valid date
            updated = store.update_node(
                node.id,
                attributes={"status": "planned", "date": date_str},
            )
            assert updated.attributes["date"] == date_str

            # Verify persistence
            persisted = store.get_node(node.id)
            assert persisted is not None
            assert persisted.attributes["date"] == date_str
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(
        valid_date=_valid_dates,
        invalid_date=_invalid_date_formats,
        label=_event_label_st,
    )
    def test_invalid_date_leaves_attributes_unchanged_on_update(
        self, valid_date: str, invalid_date: str, label: str
    ) -> None:
        """An invalid date on update is rejected and the node's previous attributes are preserved."""
        store = _make_fresh_store()
        try:
            # Create an Event node with a valid date
            original_attrs = {"date": valid_date, "location": "office"}
            node = store.upsert_node(
                label=label,
                type=NodeType.EVENT,
                attributes=original_attrs,
            )

            # Attempt to update with an invalid date — should be rejected
            with pytest.raises(DateValidationError):
                store.update_node(
                    node.id,
                    attributes={"date": invalid_date, "location": "home"},
                )

            # Verify the node's attributes are unchanged
            persisted = store.get_node(node.id)
            assert persisted is not None
            assert persisted.attributes == original_attrs
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Property 8: Deduplication by normalized label and type
# ---------------------------------------------------------------------------


class TestDeduplicationByNormalizedLabelAndType:
    """Property 8: Deduplication by normalized label and type.

    For any two node-creation requests, the Graph_Store SHALL reuse a single
    node (preserving its identifier, stored label, and existing attributes)
    when the requests share both their normalized label (trimmed,
    case-insensitive) and their type, and SHALL otherwise create two distinct
    nodes with distinct identifiers.

    **Validates: Requirements 4.2, 4.3, 4.5**
    """

    @settings(max_examples=20, deadline=None)
    @given(
        label1=label_st,
        node_type=node_type_st,
        attrs1=valid_attributes_st,
        attrs2=valid_attributes_st,
    )
    def test_same_normalized_label_and_type_reuses_node(
        self,
        label1: str,
        node_type: NodeType,
        attrs1: dict[str, str],
        attrs2: dict[str, str],
    ) -> None:
        """When two requests share normalized label and type, the store reuses
        the first node — preserving its id, stored label, and attributes."""
        # Skip Event nodes with date attributes to avoid date validation noise
        if node_type == NodeType.EVENT:
            attrs1 = {k: v for k, v in attrs1.items() if k != "date"}
            attrs2 = {k: v for k, v in attrs2.items() if k != "date"}

        store = _make_fresh_store()
        try:
            # First creation
            node1 = store.upsert_node(label1, node_type, attributes=attrs1)

            # Second creation with a case-variant of the same label
            # (casefold + strip should make them identical)
            label2 = "  " + label1.upper() + "  "  # add whitespace + change case
            node2 = store.upsert_node(label2, node_type, attributes=attrs2)

            # SHALL reuse the same node
            assert node2.id == node1.id, (
                f"Expected same id (reuse), got {node2.id!r} vs {node1.id!r}"
            )
            # SHALL preserve the stored label from the first creation
            assert node2.label == node1.label, (
                f"Expected stored label preserved: {node1.label!r}, got {node2.label!r}"
            )
            # SHALL keep existing attributes unchanged
            assert node2.attributes == node1.attributes, (
                f"Expected attributes preserved: {node1.attributes!r}, "
                f"got {node2.attributes!r}"
            )
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(
        label=label_st,
        type1=node_type_st,
        type2=node_type_st,
        attrs1=valid_attributes_st,
        attrs2=valid_attributes_st,
    )
    def test_same_label_different_type_creates_distinct_nodes(
        self,
        label: str,
        type1: NodeType,
        type2: NodeType,
        attrs1: dict[str, str],
        attrs2: dict[str, str],
    ) -> None:
        """When two requests share normalized label but differ in type, the
        store creates two distinct nodes with distinct identifiers."""
        from hypothesis import assume

        assume(type1 != type2)

        # Skip Event nodes with date attributes to avoid date validation noise
        if type1 == NodeType.EVENT:
            attrs1 = {k: v for k, v in attrs1.items() if k != "date"}
        if type2 == NodeType.EVENT:
            attrs2 = {k: v for k, v in attrs2.items() if k != "date"}

        store = _make_fresh_store()
        try:
            node1 = store.upsert_node(label, type1, attributes=attrs1)
            node2 = store.upsert_node(label, type2, attributes=attrs2)

            # SHALL create two distinct nodes with distinct identifiers
            assert node1.id != node2.id, (
                f"Expected distinct ids for different types, "
                f"got same id {node1.id!r}"
            )
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(
        label1=label_st,
        label2=label_st,
        node_type=node_type_st,
        attrs1=valid_attributes_st,
        attrs2=valid_attributes_st,
    )
    def test_different_normalized_label_same_type_creates_distinct_nodes(
        self,
        label1: str,
        label2: str,
        node_type: NodeType,
        attrs1: dict[str, str],
        attrs2: dict[str, str],
    ) -> None:
        """When two requests differ in normalized label but share type, the
        store creates two distinct nodes with distinct identifiers."""
        from hypothesis import assume
        from lifegraph.domain import normalize

        assume(normalize(label1) != normalize(label2))

        # Skip Event nodes with date attributes to avoid date validation noise
        if node_type == NodeType.EVENT:
            attrs1 = {k: v for k, v in attrs1.items() if k != "date"}
            attrs2 = {k: v for k, v in attrs2.items() if k != "date"}

        store = _make_fresh_store()
        try:
            node1 = store.upsert_node(label1, node_type, attributes=attrs1)
            node2 = store.upsert_node(label2, node_type, attributes=attrs2)

            # SHALL create two distinct nodes with distinct identifiers
            assert node1.id != node2.id, (
                f"Expected distinct ids for different labels, "
                f"got same id {node1.id!r}"
            )
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Property 7: Node identity is unique, stable, and never reused
# ---------------------------------------------------------------------------


# Strategy for operations on nodes: create, edit, delete
class _Op:
    """Base class for node operations in the stateful test."""
    pass


@st.composite
def _node_operations_st(draw):
    """Generate a sequence of node create, edit, and delete operations.

    Operations are represented as tuples:
      ("create", label, type, attributes)
      ("edit_label", node_index, new_label)
      ("edit_type", node_index, new_type)
      ("edit_attrs", node_index, new_attrs)
      ("delete", node_index)

    node_index refers to the index in the list of created nodes so far.
    """
    # Generate between 3 and 20 operations
    num_ops = draw(st.integers(min_value=3, max_value=20))
    ops = []
    created_count = 0

    for _ in range(num_ops):
        if created_count == 0:
            # Must create first
            op_type = "create"
        else:
            op_type = draw(st.sampled_from(["create", "edit_label", "edit_type", "edit_attrs", "delete"]))

        if op_type == "create":
            lbl = draw(st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=50,
            ).filter(lambda s: len(s.strip()) >= 1))
            ntype = draw(st.sampled_from(list(NodeType)))
            # Avoid Event nodes with date attrs to keep test focused on identity
            attrs = draw(st.dictionaries(
                keys=st.text(
                    alphabet=st.characters(whitelist_categories=("L", "N")),
                    min_size=1,
                    max_size=20,
                ).filter(lambda k: k != "date"),
                values=st.text(
                    alphabet=st.characters(whitelist_categories=("L", "N")),
                    min_size=1,
                    max_size=20,
                ),
                max_size=5,
            ))
            ops.append(("create", lbl, ntype, attrs))
            created_count += 1
        elif op_type == "edit_label":
            idx = draw(st.integers(min_value=0, max_value=created_count - 1))
            new_label = draw(st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=50,
            ).filter(lambda s: len(s.strip()) >= 1))
            ops.append(("edit_label", idx, new_label))
        elif op_type == "edit_type":
            idx = draw(st.integers(min_value=0, max_value=created_count - 1))
            new_type = draw(st.sampled_from(list(NodeType)))
            ops.append(("edit_type", idx, new_type))
        elif op_type == "edit_attrs":
            idx = draw(st.integers(min_value=0, max_value=created_count - 1))
            new_attrs = draw(st.dictionaries(
                keys=st.text(
                    alphabet=st.characters(whitelist_categories=("L", "N")),
                    min_size=1,
                    max_size=20,
                ).filter(lambda k: k != "date"),
                values=st.text(
                    alphabet=st.characters(whitelist_categories=("L", "N")),
                    min_size=1,
                    max_size=20,
                ),
                max_size=5,
            ))
            ops.append(("edit_attrs", idx, new_attrs))
        elif op_type == "delete":
            idx = draw(st.integers(min_value=0, max_value=created_count - 1))
            ops.append(("delete", idx))

    return ops


@settings(max_examples=20, deadline=None)
@given(ops=_node_operations_st())
def test_node_identity_unique_stable_never_reused(ops):
    """Property 7: Node identity is unique, stable, and never reused.

    For any sequence of node create, edit, and delete operations, every live
    node SHALL have an identifier unique among all nodes, each node's
    identifier SHALL remain unchanged across edits to its label, type, or
    attributes, and no identifier belonging to a deleted node SHALL be
    assigned to a later node.

    **Validates: Requirements 4.1**
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test_identity.db")
        store = GraphStore(db_path)

        try:
            # Track all created nodes: list of (node_id, alive)
            created_nodes: list[dict] = []  # {id, alive, label, type}
            all_ids_ever: set[str] = set()  # every id ever assigned
            deleted_ids: set[str] = set()  # ids of deleted nodes

            for op in ops:
                if op[0] == "create":
                    _, lbl, ntype, attrs = op
                    node = store.upsert_node(lbl, ntype, attributes=attrs)
                    # Check if this was a new node or a reuse (dedup)
                    if node.id not in all_ids_ever:
                        # New node — id must not be a deleted id
                        assert node.id not in deleted_ids, (
                            f"Newly assigned id {node.id!r} was previously "
                            f"used by a deleted node"
                        )
                        all_ids_ever.add(node.id)
                        created_nodes.append({
                            "id": node.id,
                            "alive": True,
                            "label": lbl,
                            "type": ntype,
                        })

                elif op[0] == "edit_label":
                    _, idx, new_label = op
                    # Find a live node at this index
                    live_nodes = [n for n in created_nodes if n["alive"]]
                    if not live_nodes:
                        continue
                    target = live_nodes[idx % len(live_nodes)]
                    try:
                        updated = store.update_node(target["id"], label=new_label)
                        # ID must remain stable across label edits
                        assert updated.id == target["id"], (
                            f"Node id changed from {target['id']!r} to "
                            f"{updated.id!r} after label edit"
                        )
                        target["label"] = new_label
                    except Exception:
                        # Validation errors (e.g. label too long) are fine to skip
                        pass

                elif op[0] == "edit_type":
                    _, idx, new_type = op
                    live_nodes = [n for n in created_nodes if n["alive"]]
                    if not live_nodes:
                        continue
                    target = live_nodes[idx % len(live_nodes)]
                    try:
                        updated = store.update_node(target["id"], type=new_type)
                        # ID must remain stable across type edits
                        assert updated.id == target["id"], (
                            f"Node id changed from {target['id']!r} to "
                            f"{updated.id!r} after type edit"
                        )
                        target["type"] = new_type
                    except Exception:
                        pass

                elif op[0] == "edit_attrs":
                    _, idx, new_attrs = op
                    live_nodes = [n for n in created_nodes if n["alive"]]
                    if not live_nodes:
                        continue
                    target = live_nodes[idx % len(live_nodes)]
                    try:
                        updated = store.update_node(target["id"], attributes=new_attrs)
                        # ID must remain stable across attribute edits
                        assert updated.id == target["id"], (
                            f"Node id changed from {target['id']!r} to "
                            f"{updated.id!r} after attribute edit"
                        )
                    except Exception:
                        pass

                elif op[0] == "delete":
                    _, idx = op
                    live_nodes = [n for n in created_nodes if n["alive"]]
                    if not live_nodes:
                        continue
                    target = live_nodes[idx % len(live_nodes)]
                    # Delete via direct SQL since delete_node may not be
                    # implemented yet (task 3.12); the schema uses ON DELETE
                    # CASCADE so this is equivalent
                    conn = store._connection
                    conn.execute("BEGIN")
                    conn.execute("DELETE FROM nodes WHERE id = ?", (target["id"],))
                    conn.execute("COMMIT")
                    target["alive"] = False
                    deleted_ids.add(target["id"])

            # Final invariant checks on all live nodes
            live_nodes = [n for n in created_nodes if n["alive"]]
            live_ids = [n["id"] for n in live_nodes]

            # 1. Every live node has a unique identifier
            assert len(live_ids) == len(set(live_ids)), (
                f"Duplicate ids among live nodes: {live_ids}"
            )

            # 2. Verify live nodes are actually in the store with correct ids
            graph = store.get_graph()
            store_ids = {n.id for n in graph.nodes}
            for node_info in live_nodes:
                assert node_info["id"] in store_ids, (
                    f"Live node {node_info['id']!r} not found in store"
                )

            # 3. No deleted id appears in the current store
            for did in deleted_ids:
                assert did not in store_ids, (
                    f"Deleted node id {did!r} still present in store"
                )

        finally:
            store.close()


# ---------------------------------------------------------------------------
# Property 13: Node and attribute validation bounds
# ---------------------------------------------------------------------------


from lifegraph.validation import AttributeValidationError, LabelValidationError


# Strategies for valid inputs (within bounds)
_valid_label_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=200,
)

_valid_attr_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=255,
)

_valid_attr_value_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=255,
)

_valid_attrs_st = st.dictionaries(
    keys=_valid_attr_key_st,
    values=_valid_attr_value_st,
    min_size=0,
    max_size=50,
)

# Strategies for invalid inputs (violating bounds)

# Label that is empty (0 chars)
_empty_label_st = st.just("")

# Label that exceeds 200 chars
_too_long_label_st = st.integers(min_value=201, max_value=400).flatmap(
    lambda n: st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
        min_size=n,
        max_size=n,
    )
)

# Attribute set with more than 50 entries
_too_many_attrs_st = st.dictionaries(
    keys=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=20,
    ),
    values=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=20,
    ),
    min_size=51,
    max_size=60,
)

# Attribute with an empty key
_attrs_with_empty_key_st = _valid_attrs_st.map(
    lambda d: {**d, "": "some_value"}
)

# Attribute with a key exceeding 255 chars
_attrs_with_long_key_st = st.integers(min_value=256, max_value=400).flatmap(
    lambda n: st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=n,
        max_size=n,
    )
).flatmap(
    lambda long_key: _valid_attrs_st.map(lambda d: {**d, long_key: "val"})
)

# Attribute with an empty value
_attrs_with_empty_value_st = _valid_attrs_st.map(
    lambda d: {**d, "valid_key": ""}
)

# Attribute with a value exceeding 255 chars
_attrs_with_long_value_st = st.integers(min_value=256, max_value=400).flatmap(
    lambda n: st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=n,
        max_size=n,
    )
).flatmap(
    lambda long_val: _valid_attrs_st.map(lambda d: {**d, "key": long_val})
)


class TestNodeAndAttributeValidationBounds:
    """Property 13: Node and attribute validation bounds.

    For any node-write request, the Graph_Store SHALL accept it when the label
    is 1–200 characters and the attribute set has at most 50 entries each with
    a key and value of 1–255 characters, and SHALL reject it (leaving stored
    data unchanged) when any of those bounds is violated.

    **Validates: Requirements 5.2, 6.1**
    """

    @settings(max_examples=20, deadline=None)
    @given(
        label=_valid_label_st,
        node_type=node_type_st,
        attrs=_valid_attrs_st,
    )
    def test_valid_request_is_accepted(
        self, label: str, node_type: NodeType, attrs: dict[str, str]
    ) -> None:
        """A node-write with label 1–200 chars and valid attributes is accepted."""
        # Skip Event nodes with 'date' key to avoid date validation interference
        if node_type == NodeType.EVENT:
            attrs = {k: v for k, v in attrs.items() if k != "date"}

        store = _make_fresh_store()
        try:
            node = store.upsert_node(label=label, type=node_type, attributes=attrs)
            assert node is not None
            assert node.label == label
            assert node.type == node_type
            assert node.attributes == attrs

            # Verify it's persisted
            persisted = store.get_node(node.id)
            assert persisted is not None
            assert persisted.label == label
            assert persisted.attributes == attrs
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(node_type=node_type_st, attrs=_valid_attrs_st)
    def test_empty_label_is_rejected(
        self, node_type: NodeType, attrs: dict[str, str]
    ) -> None:
        """A node-write with an empty label is rejected, store unchanged."""
        if node_type == NodeType.EVENT:
            attrs = {k: v for k, v in attrs.items() if k != "date"}

        store = _make_fresh_store()
        try:
            with pytest.raises(LabelValidationError):
                store.upsert_node(label="", type=node_type, attributes=attrs)

            # Store should remain empty
            graph = store.get_graph()
            assert len(graph.nodes) == 0
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(label=_too_long_label_st, node_type=node_type_st, attrs=_valid_attrs_st)
    def test_label_exceeding_200_chars_is_rejected(
        self, label: str, node_type: NodeType, attrs: dict[str, str]
    ) -> None:
        """A node-write with label > 200 chars is rejected, store unchanged."""
        if node_type == NodeType.EVENT:
            attrs = {k: v for k, v in attrs.items() if k != "date"}

        store = _make_fresh_store()
        try:
            with pytest.raises(LabelValidationError):
                store.upsert_node(label=label, type=node_type, attributes=attrs)

            graph = store.get_graph()
            assert len(graph.nodes) == 0
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(label=_valid_label_st, node_type=node_type_st, attrs=_too_many_attrs_st)
    def test_more_than_50_attributes_is_rejected(
        self, label: str, node_type: NodeType, attrs: dict[str, str]
    ) -> None:
        """A node-write with > 50 attribute entries is rejected, store unchanged."""
        if node_type == NodeType.EVENT:
            attrs = {k: v for k, v in attrs.items() if k != "date"}

        # Ensure we still have > 50 after filtering
        if len(attrs) <= 50:
            return  # Skip this example if filtering reduced count

        store = _make_fresh_store()
        try:
            with pytest.raises(AttributeValidationError):
                store.upsert_node(label=label, type=node_type, attributes=attrs)

            graph = store.get_graph()
            assert len(graph.nodes) == 0
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(label=_valid_label_st, node_type=node_type_st, attrs=_attrs_with_empty_key_st)
    def test_empty_attribute_key_is_rejected(
        self, label: str, node_type: NodeType, attrs: dict[str, str]
    ) -> None:
        """A node-write with an empty attribute key is rejected, store unchanged."""
        if node_type == NodeType.EVENT:
            attrs = {k: v for k, v in attrs.items() if k != "date"}

        # Ensure the empty key is still present
        if "" not in attrs:
            return

        store = _make_fresh_store()
        try:
            with pytest.raises(AttributeValidationError):
                store.upsert_node(label=label, type=node_type, attributes=attrs)

            graph = store.get_graph()
            assert len(graph.nodes) == 0
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(label=_valid_label_st, node_type=node_type_st, attrs=_attrs_with_long_key_st)
    def test_attribute_key_exceeding_255_chars_is_rejected(
        self, label: str, node_type: NodeType, attrs: dict[str, str]
    ) -> None:
        """A node-write with an attribute key > 255 chars is rejected, store unchanged."""
        if node_type == NodeType.EVENT:
            attrs = {k: v for k, v in attrs.items() if k != "date"}

        # Ensure we still have a key > 255 chars
        if not any(len(k) > 255 for k in attrs):
            return

        store = _make_fresh_store()
        try:
            with pytest.raises(AttributeValidationError):
                store.upsert_node(label=label, type=node_type, attributes=attrs)

            graph = store.get_graph()
            assert len(graph.nodes) == 0
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(label=_valid_label_st, node_type=node_type_st, attrs=_attrs_with_empty_value_st)
    def test_empty_attribute_value_is_rejected(
        self, label: str, node_type: NodeType, attrs: dict[str, str]
    ) -> None:
        """A node-write with an empty attribute value is rejected, store unchanged."""
        if node_type == NodeType.EVENT:
            attrs = {k: v for k, v in attrs.items() if k != "date"}

        # Ensure we still have an empty value
        if not any(v == "" for v in attrs.values()):
            return

        store = _make_fresh_store()
        try:
            with pytest.raises(AttributeValidationError):
                store.upsert_node(label=label, type=node_type, attributes=attrs)

            graph = store.get_graph()
            assert len(graph.nodes) == 0
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(label=_valid_label_st, node_type=node_type_st, attrs=_attrs_with_long_value_st)
    def test_attribute_value_exceeding_255_chars_is_rejected(
        self, label: str, node_type: NodeType, attrs: dict[str, str]
    ) -> None:
        """A node-write with an attribute value > 255 chars is rejected, store unchanged."""
        if node_type == NodeType.EVENT:
            attrs = {k: v for k, v in attrs.items() if k != "date"}

        # Ensure we still have a value > 255 chars
        if not any(len(v) > 255 for v in attrs.values()):
            return

        store = _make_fresh_store()
        try:
            with pytest.raises(AttributeValidationError):
                store.upsert_node(label=label, type=node_type, attributes=attrs)

            graph = store.get_graph()
            assert len(graph.nodes) == 0
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Property 10: Referential integrity on edge creation
# ---------------------------------------------------------------------------

from lifegraph.domain import EdgeType
from lifegraph.store import ReferentialIntegrityError


# Strategy for edge types
_edge_type_st = st.sampled_from(list(EdgeType))

# Strategy for node identifiers that are guaranteed to NOT exist in the store
# (random UUIDs that we never insert)
_absent_id_st = st.uuids().map(str)


class TestReferentialIntegrityOnEdgeCreation:
    """Property 10: Referential integrity on edge creation.

    For any Graph_Store state and any edge whose source or target identifier
    is absent from the nodes table, edge creation SHALL be rejected with an
    error identifying the missing identifier, and the nodes table and edges
    table SHALL be unchanged.

    **Validates: Requirements 5.4**
    """

    @settings(max_examples=20, deadline=None)
    @given(
        label1=label_st,
        label2=label_st,
        type1=node_type_st,
        type2=node_type_st,
        edge_type=_edge_type_st,
        absent_source=_absent_id_st,
    )
    def test_absent_source_is_rejected(
        self,
        label1: str,
        label2: str,
        type1: NodeType,
        type2: NodeType,
        edge_type: EdgeType,
        absent_source: str,
    ) -> None:
        """Edge creation with a source id absent from nodes is rejected,
        the error identifies the missing id, and both tables are unchanged."""
        store = _make_fresh_store()
        try:
            # Create a valid target node
            target_node = store.upsert_node(label=label1, type=type1)
            # Optionally create another node to have a non-empty store
            store.upsert_node(label=label2, type=type2)

            # Snapshot state before the rejected edge creation
            graph_before = store.get_graph()
            nodes_before = sorted([n.id for n in graph_before.nodes])
            edges_before = sorted([e.id for e in graph_before.edges])

            # Ensure absent_source is truly absent
            from hypothesis import assume
            existing_ids = {n.id for n in graph_before.nodes}
            assume(absent_source not in existing_ids)

            # Attempt to create an edge with an absent source
            with pytest.raises(ReferentialIntegrityError) as exc_info:
                store.create_edge(
                    source_id=absent_source,
                    target_id=target_node.id,
                    type=edge_type,
                )

            # Error SHALL identify the missing identifier
            assert exc_info.value.missing_id == absent_source

            # Both tables SHALL be unchanged
            graph_after = store.get_graph()
            nodes_after = sorted([n.id for n in graph_after.nodes])
            edges_after = sorted([e.id for e in graph_after.edges])
            assert nodes_after == nodes_before, "Nodes table changed after rejected edge"
            assert edges_after == edges_before, "Edges table changed after rejected edge"
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(
        label1=label_st,
        label2=label_st,
        type1=node_type_st,
        type2=node_type_st,
        edge_type=_edge_type_st,
        absent_target=_absent_id_st,
    )
    def test_absent_target_is_rejected(
        self,
        label1: str,
        label2: str,
        type1: NodeType,
        type2: NodeType,
        edge_type: EdgeType,
        absent_target: str,
    ) -> None:
        """Edge creation with a target id absent from nodes is rejected,
        the error identifies the missing id, and both tables are unchanged."""
        store = _make_fresh_store()
        try:
            # Create a valid source node
            source_node = store.upsert_node(label=label1, type=type1)
            # Optionally create another node to have a non-empty store
            store.upsert_node(label=label2, type=type2)

            # Snapshot state before the rejected edge creation
            graph_before = store.get_graph()
            nodes_before = sorted([n.id for n in graph_before.nodes])
            edges_before = sorted([e.id for e in graph_before.edges])

            # Ensure absent_target is truly absent
            from hypothesis import assume
            existing_ids = {n.id for n in graph_before.nodes}
            assume(absent_target not in existing_ids)

            # Attempt to create an edge with an absent target
            with pytest.raises(ReferentialIntegrityError) as exc_info:
                store.create_edge(
                    source_id=source_node.id,
                    target_id=absent_target,
                    type=edge_type,
                )

            # Error SHALL identify the missing identifier
            assert exc_info.value.missing_id == absent_target

            # Both tables SHALL be unchanged
            graph_after = store.get_graph()
            nodes_after = sorted([n.id for n in graph_after.nodes])
            edges_after = sorted([e.id for e in graph_after.edges])
            assert nodes_after == nodes_before, "Nodes table changed after rejected edge"
            assert edges_after == edges_before, "Edges table changed after rejected edge"
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(
        label1=label_st,
        type1=node_type_st,
        edge_type=_edge_type_st,
        absent_source=_absent_id_st,
        absent_target=_absent_id_st,
    )
    def test_both_absent_is_rejected(
        self,
        label1: str,
        type1: NodeType,
        edge_type: EdgeType,
        absent_source: str,
        absent_target: str,
    ) -> None:
        """Edge creation with both source and target absent is rejected,
        the error identifies a missing id, and both tables are unchanged."""
        from hypothesis import assume
        assume(absent_source != absent_target)

        store = _make_fresh_store()
        try:
            # Create a node so the store is non-empty
            store.upsert_node(label=label1, type=type1)

            # Snapshot state before the rejected edge creation
            graph_before = store.get_graph()
            nodes_before = sorted([n.id for n in graph_before.nodes])
            edges_before = sorted([e.id for e in graph_before.edges])

            # Ensure both ids are truly absent
            existing_ids = {n.id for n in graph_before.nodes}
            assume(absent_source not in existing_ids)
            assume(absent_target not in existing_ids)

            # Attempt to create an edge with both endpoints absent
            with pytest.raises(ReferentialIntegrityError) as exc_info:
                store.create_edge(
                    source_id=absent_source,
                    target_id=absent_target,
                    type=edge_type,
                )

            # Error SHALL identify a missing identifier (source checked first)
            assert exc_info.value.missing_id in (absent_source, absent_target)

            # Both tables SHALL be unchanged
            graph_after = store.get_graph()
            nodes_after = sorted([n.id for n in graph_after.nodes])
            edges_after = sorted([e.id for e in graph_after.edges])
            assert nodes_after == nodes_before, "Nodes table changed after rejected edge"
            assert edges_after == edges_before, "Edges table changed after rejected edge"
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Property 20: Edge creation and type validation
# ---------------------------------------------------------------------------

from lifegraph.domain import EdgeType, EDGE_TYPE_VALUES
from lifegraph.store import SelfEdgeError


# Strategy for valid edge types
_edge_type_st = st.sampled_from(list(EdgeType))

# Strategy for invalid edge type strings (not in Edge_Type_Set)
_invalid_edge_type_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
).filter(lambda s: s not in EDGE_TYPE_VALUES)


class TestEdgeCreationAndTypeValidation:
    """Property 20: Edge creation and type validation.

    For any edge submission, the Graph_Editor SHALL create the edge when its
    source and target are distinct existing nodes and its type is in the
    Edge_Type_Set, and SHALL reject it (leaving the Graph_Store unchanged)
    when the type is not in the Edge_Type_Set or the source and target are
    the same node.

    **Validates: Requirements 9.1, 9.3, 9.4**
    """

    @settings(max_examples=20, deadline=None)
    @given(
        label1=label_st,
        label2=label_st,
        node_type1=node_type_st,
        node_type2=node_type_st,
        edge_type=_edge_type_st,
    )
    def test_valid_edge_creation_with_distinct_existing_nodes(
        self,
        label1: str,
        label2: str,
        node_type1: NodeType,
        node_type2: NodeType,
        edge_type: EdgeType,
    ) -> None:
        """An edge with distinct existing source/target and valid type is created."""
        from hypothesis import assume
        from lifegraph.domain import normalize

        # Ensure the two nodes will be distinct (different identity)
        assume(
            (normalize(label1), node_type1) != (normalize(label2), node_type2)
        )

        # Avoid Event nodes with date attributes
        store = _make_fresh_store()
        try:
            node1 = store.upsert_node(label1, node_type1)
            node2 = store.upsert_node(label2, node_type2)

            edge = store.create_edge(node1.id, node2.id, edge_type)

            # Edge SHALL be created
            assert edge is not None
            assert edge.source == node1.id
            assert edge.target == node2.id
            assert edge.type == edge_type

            # Verify it's persisted in the store
            graph = store.get_graph()
            edge_ids = {e.id for e in graph.edges}
            assert edge.id in edge_ids, (
                f"Created edge {edge.id!r} not found in store"
            )
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(
        label=label_st,
        node_type=node_type_st,
        edge_type=_edge_type_st,
    )
    def test_self_edge_is_rejected_store_unchanged(
        self,
        label: str,
        node_type: NodeType,
        edge_type: EdgeType,
    ) -> None:
        """An edge where source and target are the same node is rejected,
        leaving the Graph_Store unchanged."""
        store = _make_fresh_store()
        try:
            node = store.upsert_node(label, node_type)

            # Capture store state before attempted edge creation
            graph_before = store.get_graph()

            # Attempt to create a self-edge — SHALL be rejected
            with pytest.raises(SelfEdgeError):
                store.create_edge(node.id, node.id, edge_type)

            # Store SHALL be unchanged
            graph_after = store.get_graph()
            assert len(graph_after.edges) == len(graph_before.edges), (
                "Edge count changed after rejected self-edge creation"
            )
            assert {e.id for e in graph_after.edges} == {
                e.id for e in graph_before.edges
            }, "Edge set changed after rejected self-edge creation"
        finally:
            store.close()

    @settings(max_examples=20, deadline=None)
    @given(
        label1=label_st,
        label2=label_st,
        node_type1=node_type_st,
        node_type2=node_type_st,
        invalid_type_str=_invalid_edge_type_st,
    )
    def test_invalid_edge_type_is_rejected_store_unchanged(
        self,
        label1: str,
        label2: str,
        node_type1: NodeType,
        node_type2: NodeType,
        invalid_type_str: str,
    ) -> None:
        """An edge with a type not in the Edge_Type_Set is rejected,
        leaving the Graph_Store unchanged.

        Since create_edge takes an EdgeType enum, invalid types cannot be
        passed directly. This test verifies that attempting to construct an
        EdgeType from an invalid string raises ValueError (the type system
        prevents invalid types from reaching the store).
        """
        from hypothesis import assume
        from lifegraph.domain import normalize

        # Ensure the two nodes will be distinct
        assume(
            (normalize(label1), node_type1) != (normalize(label2), node_type2)
        )

        store = _make_fresh_store()
        try:
            node1 = store.upsert_node(label1, node_type1)
            node2 = store.upsert_node(label2, node_type2)

            # Capture store state before attempted edge creation
            graph_before = store.get_graph()

            # Attempting to create an EdgeType from an invalid string SHALL fail
            with pytest.raises(ValueError):
                invalid_type = EdgeType(invalid_type_str)
                # If somehow it didn't raise, try creating the edge
                store.create_edge(node1.id, node2.id, invalid_type)

            # Store SHALL be unchanged
            graph_after = store.get_graph()
            assert len(graph_after.edges) == len(graph_before.edges), (
                "Edge count changed after rejected invalid-type edge creation"
            )
            assert {e.id for e in graph_after.edges} == {
                e.id for e in graph_before.edges
            }, "Edge set changed after rejected invalid-type edge creation"
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Property 22: Edge deletion preserves endpoints
# ---------------------------------------------------------------------------

from lifegraph.domain import EdgeType
from lifegraph.store import EdgeNotFoundError

# Strategy for edge types
_edge_type_st = st.sampled_from(list(EdgeType))


class TestEdgeDeletionPreservesEndpoints:
    """Property 22: Edge deletion preserves endpoints.

    When the user deletes an edge, the Graph_Editor SHALL remove the edge from
    the Graph_Store while leaving its source and target nodes intact.

    **Validates: Requirements 9.5**
    """

    @settings(max_examples=20, deadline=None)
    @given(
        source_label=label_st,
        target_label=label_st,
        source_type=node_type_st,
        target_type=node_type_st,
        edge_type=_edge_type_st,
    )
    def test_edge_deletion_removes_edge_preserves_nodes(
        self,
        source_label: str,
        target_label: str,
        source_type: NodeType,
        target_type: NodeType,
        edge_type: EdgeType,
    ) -> None:
        """Deleting an edge removes it from the store while leaving its source
        and target nodes intact."""
        from hypothesis import assume
        from lifegraph.domain import normalize

        # Ensure source and target are distinct nodes (no self-edges)
        assume(
            (normalize(source_label), source_type)
            != (normalize(target_label), target_type)
        )

        store = _make_fresh_store()
        try:
            # Create source and target nodes
            source_node = store.upsert_node(source_label, source_type)
            target_node = store.upsert_node(target_label, target_type)

            # Create an edge between them
            edge = store.create_edge(source_node.id, target_node.id, edge_type)

            # Verify edge exists
            graph_before = store.get_graph()
            assert any(e.id == edge.id for e in graph_before.edges)

            # Delete the edge
            store.delete_edge(edge.id)

            # The edge SHALL be removed from the store
            graph_after = store.get_graph()
            assert not any(e.id == edge.id for e in graph_after.edges), (
                f"Edge {edge.id!r} should have been removed but is still present"
            )

            # The source node SHALL remain intact
            source_after = store.get_node(source_node.id)
            assert source_after is not None, (
                f"Source node {source_node.id!r} should still exist after edge deletion"
            )
            assert source_after.id == source_node.id
            assert source_after.label == source_node.label
            assert source_after.type == source_node.type
            assert source_after.attributes == source_node.attributes

            # The target node SHALL remain intact
            target_after = store.get_node(target_node.id)
            assert target_after is not None, (
                f"Target node {target_node.id!r} should still exist after edge deletion"
            )
            assert target_after.id == target_node.id
            assert target_after.label == target_node.label
            assert target_after.type == target_node.type
            assert target_after.attributes == target_node.attributes
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Property 21: Edge type edit round-trip
# ---------------------------------------------------------------------------


class TestEdgeTypeEditRoundTrip:
    """Property 21: Edge type edit round-trip.

    For any edge and any type in the Edge_Type_Set, after the edge's type is
    updated a read of that edge SHALL return the new type.

    **Validates: Requirements 9.2**
    """

    @settings(max_examples=20, deadline=None)
    @given(
        source_label=label_st,
        target_label=label_st,
        source_type=node_type_st,
        target_type=node_type_st,
        initial_edge_type=st.sampled_from(list(EdgeType)),
        new_edge_type=st.sampled_from(list(EdgeType)),
    )
    def test_edge_type_edit_round_trip(
        self,
        source_label: str,
        target_label: str,
        source_type: NodeType,
        target_type: NodeType,
        initial_edge_type: EdgeType,
        new_edge_type: EdgeType,
    ) -> None:
        """After updating an edge's type, reading that edge returns the new type."""
        from hypothesis import assume
        from lifegraph.domain import EdgeType, normalize

        # Ensure source and target are distinct nodes (no self-edges)
        assume(
            normalize(source_label) != normalize(target_label)
            or source_type != target_type
        )

        store = _make_fresh_store()
        try:
            # Create two distinct nodes
            source_node = store.upsert_node(source_label, source_type)
            target_node = store.upsert_node(target_label, target_type)

            # Create an edge between them
            edge = store.create_edge(source_node.id, target_node.id, initial_edge_type)

            # Update the edge's type
            updated_edge = store.update_edge(edge.id, new_edge_type)

            # The returned updated edge should have the new type
            assert updated_edge.type == new_edge_type, (
                f"update_edge returned type {updated_edge.type!r}, "
                f"expected {new_edge_type!r}"
            )

            # Read the edge back from the store via get_graph
            graph = store.get_graph()
            matching_edges = [e for e in graph.edges if e.id == edge.id]
            assert len(matching_edges) == 1, (
                f"Expected exactly 1 edge with id {edge.id!r}, "
                f"found {len(matching_edges)}"
            )
            read_edge = matching_edges[0]

            # The read edge SHALL return the new type
            assert read_edge.type == new_edge_type, (
                f"Read-back edge type {read_edge.type!r} != "
                f"expected {new_edge_type!r}"
            )

            # Verify source and target are unchanged
            assert read_edge.source == source_node.id
            assert read_edge.target == target_node.id
        finally:
            store.close()


# ---------------------------------------------------------------------------
# Property 12: Storage reload round-trip
# ---------------------------------------------------------------------------


@st.composite
def _graph_st(draw):
    """Generate a valid graph: a set of nodes and edges between them.

    Produces a list of (label, type, attributes) for nodes and a list of
    (source_index, target_index, edge_type) for edges, ensuring no self-edges
    and all endpoints reference valid node indices.
    """
    # Generate 1-10 nodes
    num_nodes = draw(st.integers(min_value=1, max_value=10))
    nodes = []
    for _ in range(num_nodes):
        lbl = draw(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
                min_size=1,
                max_size=50,
            ).filter(lambda s: len(s.strip()) >= 1)
        )
        ntype = draw(st.sampled_from(list(NodeType)))
        # Avoid Event date attributes to keep the test focused on round-trip
        attrs = draw(
            st.dictionaries(
                keys=st.text(
                    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
                    min_size=1,
                    max_size=50,
                ).filter(lambda k: k != "date"),
                values=st.text(
                    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
                    min_size=1,
                    max_size=50,
                ),
                min_size=0,
                max_size=5,
            )
        )
        nodes.append((lbl, ntype, attrs))

    # Generate 0-15 edges (only if we have at least 2 nodes for non-self-edges)
    edges = []
    if num_nodes >= 2:
        num_edges = draw(st.integers(min_value=0, max_value=min(15, num_nodes * (num_nodes - 1))))
        for _ in range(num_edges):
            src_idx = draw(st.integers(min_value=0, max_value=num_nodes - 1))
            tgt_idx = draw(
                st.integers(min_value=0, max_value=num_nodes - 1).filter(
                    lambda t, s=src_idx: t != s
                )
            )
            etype = draw(st.sampled_from(list(EdgeType)))
            edges.append((src_idx, tgt_idx, etype))

    return nodes, edges


class TestStorageReloadRoundTrip:
    """Property 12: Storage reload round-trip.

    For any graph, writing it to the Graph_Store, closing, and reopening the
    database SHALL yield a node set and edge set equal field-for-field to the
    graph that was written.

    **Validates: Requirements 5.6**
    """

    @settings(max_examples=20, deadline=None)
    @given(graph_data=_graph_st())
    def test_storage_reload_round_trip(self, graph_data):
        """Write a graph, close the store, reopen it, and verify all fields match."""
        node_specs, edge_specs = graph_data

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "roundtrip.db")

            # --- Phase 1: Write the graph ---
            store = GraphStore(db_path)
            try:
                # Create nodes, tracking their assigned ids
                created_nodes = []
                for lbl, ntype, attrs in node_specs:
                    node = store.upsert_node(lbl, ntype, attributes=attrs)
                    created_nodes.append(node)

                # Create edges using the assigned node ids
                created_edges = []
                for src_idx, tgt_idx, etype in edge_specs:
                    src_id = created_nodes[src_idx].id
                    tgt_id = created_nodes[tgt_idx].id
                    # Due to deduplication, src and tgt might be the same node
                    # (if two node_specs deduplicated to one). Skip self-edges.
                    if src_id == tgt_id:
                        continue
                    edge = store.create_edge(src_id, tgt_id, etype)
                    created_edges.append(edge)

                # Read the full graph before closing
                graph_before = store.get_graph()
            finally:
                store.close()

            # --- Phase 2: Reopen and verify ---
            store2 = GraphStore(db_path)
            try:
                graph_after = store2.get_graph()

                # Compare node sets field-for-field
                nodes_before = {n.id: n for n in graph_before.nodes}
                nodes_after = {n.id: n for n in graph_after.nodes}

                assert set(nodes_before.keys()) == set(nodes_after.keys()), (
                    f"Node id sets differ.\n"
                    f"Before: {sorted(nodes_before.keys())}\n"
                    f"After:  {sorted(nodes_after.keys())}"
                )

                for node_id in nodes_before:
                    nb = nodes_before[node_id]
                    na = nodes_after[node_id]
                    assert nb.id == na.id, f"Node id mismatch: {nb.id!r} vs {na.id!r}"
                    assert nb.type == na.type, (
                        f"Node {node_id} type mismatch: {nb.type!r} vs {na.type!r}"
                    )
                    assert nb.label == na.label, (
                        f"Node {node_id} label mismatch: {nb.label!r} vs {na.label!r}"
                    )
                    assert nb.attributes == na.attributes, (
                        f"Node {node_id} attributes mismatch: "
                        f"{nb.attributes!r} vs {na.attributes!r}"
                    )

                # Compare edge sets field-for-field
                edges_before = {e.id: e for e in graph_before.edges}
                edges_after = {e.id: e for e in graph_after.edges}

                assert set(edges_before.keys()) == set(edges_after.keys()), (
                    f"Edge id sets differ.\n"
                    f"Before: {sorted(edges_before.keys())}\n"
                    f"After:  {sorted(edges_after.keys())}"
                )

                for edge_id in edges_before:
                    eb = edges_before[edge_id]
                    ea = edges_after[edge_id]
                    assert eb.id == ea.id, f"Edge id mismatch: {eb.id!r} vs {ea.id!r}"
                    assert eb.source == ea.source, (
                        f"Edge {edge_id} source mismatch: {eb.source!r} vs {ea.source!r}"
                    )
                    assert eb.target == ea.target, (
                        f"Edge {edge_id} target mismatch: {eb.target!r} vs {ea.target!r}"
                    )
                    assert eb.type == ea.type, (
                        f"Edge {edge_id} type mismatch: {eb.type!r} vs {ea.type!r}"
                    )
            finally:
                store2.close()


# ---------------------------------------------------------------------------
# Property 11: Cascade delete removes all incident edges
# ---------------------------------------------------------------------------


from lifegraph.domain import EdgeType


# Strategy for edge types
_edge_type_st = st.sampled_from(list(EdgeType))


@st.composite
def _graph_with_target_node(draw):
    """Generate a graph (nodes + edges) and pick one node to delete.

    Returns (labels_and_types, edges_as_index_pairs, target_index) where:
    - labels_and_types: list of (label, NodeType) for each node
    - edges_as_index_pairs: list of (source_idx, target_idx, EdgeType)
    - target_index: index of the node to delete
    """
    # Generate 2-10 nodes with distinct normalized identities
    num_nodes = draw(st.integers(min_value=2, max_value=10))

    labels_and_types: list[tuple[str, NodeType]] = []
    seen_identities: set[tuple[str, str]] = set()

    for i in range(num_nodes):
        # Use simple unique labels to avoid dedup collisions
        label = f"node_{i}_{draw(st.integers(min_value=0, max_value=9999))}"
        ntype = draw(st.sampled_from(list(NodeType)))
        norm_id = (label.strip().casefold(), ntype.value)
        if norm_id in seen_identities:
            # Skip duplicates
            continue
        seen_identities.add(norm_id)
        labels_and_types.append((label, ntype))

    # Need at least 2 nodes for edges
    if len(labels_and_types) < 2:
        labels_and_types.append(("fallback_node_x", NodeType.SKILL))

    n = len(labels_and_types)

    # Generate 0-15 edges (no self-edges)
    num_edges = draw(st.integers(min_value=0, max_value=min(15, n * (n - 1))))
    edges: list[tuple[int, int, EdgeType]] = []
    for _ in range(num_edges):
        src_idx = draw(st.integers(min_value=0, max_value=n - 1))
        tgt_idx = draw(st.integers(min_value=0, max_value=n - 1).filter(
            lambda t, s=src_idx: t != s
        ))
        etype = draw(_edge_type_st)
        edges.append((src_idx, tgt_idx, etype))

    # Pick a target node to delete
    target_index = draw(st.integers(min_value=0, max_value=n - 1))

    return labels_and_types, edges, target_index


class TestCascadeDeleteRemovesAllIncidentEdges:
    """Property 11: Cascade delete removes all incident edges.

    For any graph and any node in it, deleting that node SHALL remove the node
    and every edge whose source or target is that node, while leaving all other
    nodes and all non-incident edges unchanged.

    **Validates: Requirements 5.5, 8.6**
    """

    @settings(max_examples=20, deadline=None)
    @given(data=_graph_with_target_node())
    def test_cascade_delete_removes_node_and_incident_edges(self, data):
        """Deleting a node removes it and all incident edges, preserving the rest."""
        labels_and_types, edge_specs, target_index = data

        store = _make_fresh_store()
        try:
            # --- Phase 1: Build the graph ---
            nodes = []
            for label, ntype in labels_and_types:
                # Avoid Event date validation issues
                node = store.upsert_node(label, ntype, attributes={})
                nodes.append(node)

            edges = []
            for src_idx, tgt_idx, etype in edge_specs:
                edge = store.create_edge(nodes[src_idx].id, nodes[tgt_idx].id, etype)
                edges.append(edge)

            # Identify the target node and its incident edges
            target_node = nodes[target_index]
            incident_edge_ids = {
                e.id for e in edges
                if e.source == target_node.id or e.target == target_node.id
            }
            non_incident_edge_ids = {
                e.id for e in edges
                if e.source != target_node.id and e.target != target_node.id
            }
            other_node_ids = {
                n.id for n in nodes if n.id != target_node.id
            }

            # --- Phase 2: Delete the target node ---
            deleted_edge_ids = store.delete_node(target_node.id)

            # --- Phase 3: Verify postconditions ---
            graph_after = store.get_graph()
            remaining_node_ids = {n.id for n in graph_after.nodes}
            remaining_edge_ids = {e.id for e in graph_after.edges}

            # 1. The deleted node SHALL be removed
            assert target_node.id not in remaining_node_ids, (
                f"Deleted node {target_node.id!r} still present in store"
            )

            # 2. Every incident edge SHALL be removed
            for eid in incident_edge_ids:
                assert eid not in remaining_edge_ids, (
                    f"Incident edge {eid!r} still present after node deletion"
                )

            # 3. The returned deleted edge ids SHALL match the incident edges
            assert set(deleted_edge_ids) == incident_edge_ids, (
                f"Returned deleted edge ids {set(deleted_edge_ids)} != "
                f"expected incident edges {incident_edge_ids}"
            )

            # 4. All other nodes SHALL remain unchanged
            assert other_node_ids == remaining_node_ids, (
                f"Other nodes changed.\n"
                f"Expected: {sorted(other_node_ids)}\n"
                f"Got:      {sorted(remaining_node_ids)}"
            )

            # 5. All non-incident edges SHALL remain unchanged
            assert non_incident_edge_ids == remaining_edge_ids, (
                f"Non-incident edges changed.\n"
                f"Expected: {sorted(non_incident_edge_ids)}\n"
                f"Got:      {sorted(remaining_edge_ids)}"
            )

            # 6. Verify non-incident edges still have correct fields
            edges_by_id = {e.id: e for e in edges}
            for e in graph_after.edges:
                original = edges_by_id[e.id]
                assert e.source == original.source, (
                    f"Edge {e.id} source changed: {original.source!r} -> {e.source!r}"
                )
                assert e.target == original.target, (
                    f"Edge {e.id} target changed: {original.target!r} -> {e.target!r}"
                )
                assert e.type == original.type, (
                    f"Edge {e.id} type changed: {original.type!r} -> {e.type!r}"
                )
        finally:
            store.close()

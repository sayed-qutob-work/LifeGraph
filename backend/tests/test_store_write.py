"""Tests for Graph_Store node write path: upsert_node and update_node.

Covers Requirements: 4.1, 4.2, 4.3, 4.5, 5.2, 6.1, 6.4
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lifegraph.domain import Node, NodeType, normalize
from lifegraph.store import GraphStore, NodeNotFoundError
from lifegraph.validation import (
    AttributeValidationError,
    DateValidationError,
    LabelValidationError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_path(tmp_path: Path, name: str = "test.db") -> str:
    return str(tmp_path / name)


def _deterministic_id_factory():
    counter = [0]

    def factory() -> str:
        counter[0] += 1
        return f"id-{counter[0]:04d}"

    return factory


# ---------------------------------------------------------------------------
# upsert_node — creation path
# ---------------------------------------------------------------------------


class TestUpsertNodeCreation:
    """Tests for upsert_node when no matching node exists (creation)."""

    def test_creates_new_node_with_fresh_id(self, tmp_path: Path) -> None:
        """A new node is created with an id from id_factory."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)

        node = store.upsert_node("Python", NodeType.SKILL)

        assert node.id == "id-0001"
        assert node.type == NodeType.SKILL
        assert node.label == "Python"
        assert node.attributes == {}
        store.close()

    def test_creates_node_with_attributes(self, tmp_path: Path) -> None:
        """A new node is created with the provided attributes."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        node = store.upsert_node("Birthday", NodeType.EVENT, {"date": "2025-06-15"})

        assert node.attributes == {"date": "2025-06-15"}
        store.close()

    def test_node_persisted_in_db(self, tmp_path: Path) -> None:
        """The created node is retrievable from the store."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        store.upsert_node("Python", NodeType.SKILL)
        retrieved = store.get_node("id-0001")

        assert retrieved is not None
        assert retrieved.label == "Python"
        assert retrieved.type == NodeType.SKILL
        store.close()

    def test_creates_distinct_nodes_for_different_types(self, tmp_path: Path) -> None:
        """Same label but different types creates distinct nodes."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)

        n1 = store.upsert_node("Python", NodeType.SKILL)
        n2 = store.upsert_node("Python", NodeType.PROJECT)

        assert n1.id != n2.id
        assert n1.type == NodeType.SKILL
        assert n2.type == NodeType.PROJECT
        store.close()

    def test_creates_distinct_nodes_for_different_labels(self, tmp_path: Path) -> None:
        """Same type but different labels creates distinct nodes."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)

        n1 = store.upsert_node("Python", NodeType.SKILL)
        n2 = store.upsert_node("JavaScript", NodeType.SKILL)

        assert n1.id != n2.id
        store.close()


# ---------------------------------------------------------------------------
# upsert_node — deduplication path (Req 4.2, 4.3, 4.5)
# ---------------------------------------------------------------------------


class TestUpsertNodeDeduplication:
    """Tests for upsert_node when a matching node already exists."""

    def test_reuses_existing_node_exact_match(self, tmp_path: Path) -> None:
        """Exact same label and type reuses the existing node."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)

        n1 = store.upsert_node("Python", NodeType.SKILL)
        n2 = store.upsert_node("Python", NodeType.SKILL)

        assert n2.id == n1.id
        assert n2.label == n1.label
        store.close()

    def test_reuses_existing_node_case_insensitive(self, tmp_path: Path) -> None:
        """Case-different label with same type reuses the existing node (Req 4.5)."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)

        n1 = store.upsert_node("Python", NodeType.SKILL)
        n2 = store.upsert_node("PYTHON", NodeType.SKILL)

        assert n2.id == n1.id
        assert n2.label == "Python"  # Keeps original stored label
        store.close()

    def test_reuses_existing_node_whitespace_trimmed(self, tmp_path: Path) -> None:
        """Whitespace-padded label with same type reuses the existing node."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)

        n1 = store.upsert_node("Python", NodeType.SKILL)
        n2 = store.upsert_node("  Python  ", NodeType.SKILL)

        assert n2.id == n1.id
        assert n2.label == "Python"  # Keeps original stored label
        store.close()

    def test_preserves_existing_attributes_on_dedup(self, tmp_path: Path) -> None:
        """When deduplicating, the existing node's attributes are preserved."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)

        n1 = store.upsert_node("Birthday", NodeType.EVENT, {"date": "2025-06-15"})
        # Try to upsert with different attributes — should be ignored
        n2 = store.upsert_node("birthday", NodeType.EVENT, {"date": "2026-01-01"})

        assert n2.id == n1.id
        assert n2.attributes == {"date": "2025-06-15"}  # Original preserved
        store.close()

    def test_preserves_existing_id_on_dedup(self, tmp_path: Path) -> None:
        """When deduplicating, the existing node's id is preserved (Req 4.2)."""
        factory = _deterministic_id_factory()
        store = GraphStore(_make_db_path(tmp_path), id_factory=factory)

        n1 = store.upsert_node("Python", NodeType.SKILL)
        n2 = store.upsert_node("python", NodeType.SKILL)

        assert n2.id == "id-0001"  # Same id, no new id generated
        store.close()


# ---------------------------------------------------------------------------
# upsert_node — validation
# ---------------------------------------------------------------------------


class TestUpsertNodeValidation:
    """Tests for upsert_node validation of label and attributes."""

    def test_rejects_empty_label(self, tmp_path: Path) -> None:
        """Empty label raises LabelValidationError."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(LabelValidationError):
            store.upsert_node("", NodeType.SKILL)
        store.close()

    def test_rejects_label_over_200_chars(self, tmp_path: Path) -> None:
        """Label exceeding 200 characters raises LabelValidationError."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(LabelValidationError):
            store.upsert_node("x" * 201, NodeType.SKILL)
        store.close()

    def test_accepts_label_at_200_chars(self, tmp_path: Path) -> None:
        """Label of exactly 200 characters is accepted."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        node = store.upsert_node("x" * 200, NodeType.SKILL)
        assert len(node.label) == 200
        store.close()

    def test_rejects_too_many_attributes(self, tmp_path: Path) -> None:
        """More than 50 attributes raises AttributeValidationError."""
        store = GraphStore(_make_db_path(tmp_path))
        attrs = {f"key{i}": f"val{i}" for i in range(51)}

        with pytest.raises(AttributeValidationError):
            store.upsert_node("Test", NodeType.SKILL, attrs)
        store.close()

    def test_rejects_empty_attribute_key(self, tmp_path: Path) -> None:
        """Empty attribute key raises AttributeValidationError."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(AttributeValidationError):
            store.upsert_node("Test", NodeType.SKILL, {"": "value"})
        store.close()

    def test_rejects_attribute_key_over_255(self, tmp_path: Path) -> None:
        """Attribute key over 255 chars raises AttributeValidationError."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(AttributeValidationError):
            store.upsert_node("Test", NodeType.SKILL, {"k" * 256: "value"})
        store.close()

    def test_rejects_empty_attribute_value(self, tmp_path: Path) -> None:
        """Empty attribute value raises AttributeValidationError."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(AttributeValidationError):
            store.upsert_node("Test", NodeType.SKILL, {"key": ""})
        store.close()

    def test_rejects_attribute_value_over_255(self, tmp_path: Path) -> None:
        """Attribute value over 255 chars raises AttributeValidationError."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(AttributeValidationError):
            store.upsert_node("Test", NodeType.SKILL, {"key": "v" * 256})
        store.close()

    def test_rejects_invalid_event_date(self, tmp_path: Path) -> None:
        """Invalid Event date raises DateValidationError."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(DateValidationError):
            store.upsert_node("Birthday", NodeType.EVENT, {"date": "2025-02-30"})
        store.close()

    def test_rejects_malformed_event_date(self, tmp_path: Path) -> None:
        """Malformed Event date raises DateValidationError."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(DateValidationError):
            store.upsert_node("Birthday", NodeType.EVENT, {"date": "not-a-date"})
        store.close()

    def test_accepts_valid_event_date(self, tmp_path: Path) -> None:
        """Valid Event date is accepted."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        node = store.upsert_node("Birthday", NodeType.EVENT, {"date": "2025-06-15"})
        assert node.attributes["date"] == "2025-06-15"
        store.close()

    def test_non_event_node_skips_date_validation(self, tmp_path: Path) -> None:
        """Non-Event nodes with a 'date' attribute skip date validation."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())

        # A Skill with a 'date' attribute that isn't a valid date — should be fine
        node = store.upsert_node("Test", NodeType.SKILL, {"date": "not-a-date"})
        assert node.attributes["date"] == "not-a-date"
        store.close()

    def test_validation_failure_leaves_store_unchanged(self, tmp_path: Path) -> None:
        """Failed validation does not create a node in the store."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(LabelValidationError):
            store.upsert_node("x" * 201, NodeType.SKILL)

        graph = store.get_graph()
        assert graph.nodes == []
        store.close()


# ---------------------------------------------------------------------------
# update_node
# ---------------------------------------------------------------------------


class TestUpdateNode:
    """Tests for update_node."""

    def test_updates_label(self, tmp_path: Path) -> None:
        """update_node changes the label."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL)

        updated = store.update_node("id-0001", label="Python 3")

        assert updated.id == "id-0001"
        assert updated.label == "Python 3"
        assert updated.type == NodeType.SKILL
        store.close()

    def test_updates_type(self, tmp_path: Path) -> None:
        """update_node changes the type."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL)

        updated = store.update_node("id-0001", type=NodeType.PROJECT)

        assert updated.type == NodeType.PROJECT
        store.close()

    def test_updates_attributes(self, tmp_path: Path) -> None:
        """update_node changes the attributes."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL)

        updated = store.update_node("id-0001", attributes={"level": "advanced"})

        assert updated.attributes == {"level": "advanced"}
        store.close()

    def test_updates_multiple_fields(self, tmp_path: Path) -> None:
        """update_node can change multiple fields at once."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL)

        updated = store.update_node(
            "id-0001", label="Birthday", type=NodeType.EVENT, attributes={"date": "2025-12-25"}
        )

        assert updated.label == "Birthday"
        assert updated.type == NodeType.EVENT
        assert updated.attributes == {"date": "2025-12-25"}
        store.close()

    def test_preserves_unchanged_fields(self, tmp_path: Path) -> None:
        """update_node preserves fields not specified."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL, {"level": "beginner"})

        updated = store.update_node("id-0001", label="Python 3")

        assert updated.type == NodeType.SKILL
        assert updated.attributes == {"level": "beginner"}
        store.close()

    def test_persists_update_in_db(self, tmp_path: Path) -> None:
        """Updated node is retrievable with new values."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL)
        store.update_node("id-0001", label="Python 3")

        retrieved = store.get_node("id-0001")
        assert retrieved is not None
        assert retrieved.label == "Python 3"
        store.close()

    def test_raises_node_not_found(self, tmp_path: Path) -> None:
        """update_node raises NodeNotFoundError for non-existent id."""
        store = GraphStore(_make_db_path(tmp_path))

        with pytest.raises(NodeNotFoundError) as exc_info:
            store.update_node("nonexistent", label="Test")

        assert exc_info.value.node_id == "nonexistent"
        store.close()

    def test_id_remains_stable_across_edits(self, tmp_path: Path) -> None:
        """Node id does not change when label/type/attributes are edited (Req 4.1)."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL)

        updated = store.update_node("id-0001", label="JavaScript", type=NodeType.GOAL)

        assert updated.id == "id-0001"
        store.close()


# ---------------------------------------------------------------------------
# update_node — validation
# ---------------------------------------------------------------------------


class TestUpdateNodeValidation:
    """Tests for update_node validation."""

    def test_rejects_empty_label(self, tmp_path: Path) -> None:
        """Empty new label raises LabelValidationError."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL)

        with pytest.raises(LabelValidationError):
            store.update_node("id-0001", label="")
        store.close()

    def test_rejects_label_over_200(self, tmp_path: Path) -> None:
        """New label over 200 chars raises LabelValidationError."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL)

        with pytest.raises(LabelValidationError):
            store.update_node("id-0001", label="x" * 201)
        store.close()

    def test_rejects_invalid_attributes(self, tmp_path: Path) -> None:
        """Invalid attributes raise AttributeValidationError."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL)

        with pytest.raises(AttributeValidationError):
            store.update_node("id-0001", attributes={"": "value"})
        store.close()

    def test_rejects_invalid_event_date_on_update(self, tmp_path: Path) -> None:
        """Invalid Event date on update raises DateValidationError."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Birthday", NodeType.EVENT, {"date": "2025-06-15"})

        with pytest.raises(DateValidationError):
            store.update_node("id-0001", attributes={"date": "2025-02-30"})
        store.close()

    def test_validates_date_when_type_changed_to_event(self, tmp_path: Path) -> None:
        """Date validation triggers when type is changed to Event and date exists."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Meeting", NodeType.SKILL, {"date": "invalid"})

        with pytest.raises(DateValidationError):
            store.update_node("id-0001", type=NodeType.EVENT)
        store.close()

    def test_validation_failure_leaves_node_unchanged(self, tmp_path: Path) -> None:
        """Failed validation does not modify the node."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL, {"level": "beginner"})

        with pytest.raises(LabelValidationError):
            store.update_node("id-0001", label="x" * 201)

        node = store.get_node("id-0001")
        assert node is not None
        assert node.label == "Python"
        assert node.attributes == {"level": "beginner"}
        store.close()

    def test_updates_normalized_label_on_label_change(self, tmp_path: Path) -> None:
        """Changing the label updates the normalized_label in the DB."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.upsert_node("Python", NodeType.SKILL)
        store.update_node("id-0001", label="JavaScript")

        # Should be findable by new normalized label
        found = store.find_node("javascript", NodeType.SKILL)
        assert found is not None
        assert found.id == "id-0001"

        # Should NOT be findable by old normalized label
        not_found = store.find_node("python", NodeType.SKILL)
        assert not_found is None
        store.close()

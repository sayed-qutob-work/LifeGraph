"""Tests for the domain types, normalization, and identity helpers."""

import pytest

from lifegraph.domain import (
    EDGE_TYPE_VALUES,
    NODE_TYPE_VALUES,
    Edge,
    EdgeType,
    Graph,
    Node,
    NodeType,
    ProposedEdge,
    ProposedGraph,
    ProposedNode,
    identity,
    normalize,
)


# ---------------------------------------------------------------------------
# NodeType enumeration
# ---------------------------------------------------------------------------


class TestNodeType:
    def test_all_members_present(self):
        expected = {
            "Skill",
            "Goal",
            "Habit",
            "Project",
            "Event",
            "Person",
            "Organization",
            "Program",
            "Tool",
            "Technology",
            "Model",
            "Hardware",
            "Topic",
            "Recipe",
            "Issue",
            "Place",
            "Resource",
        }
        assert {nt.value for nt in NodeType} == expected

    def test_node_type_values_frozenset(self):
        assert NODE_TYPE_VALUES == frozenset(
            [
                "Skill",
                "Goal",
                "Habit",
                "Project",
                "Event",
                "Person",
                "Organization",
                "Program",
                "Tool",
                "Technology",
                "Model",
                "Hardware",
                "Topic",
                "Recipe",
                "Issue",
                "Place",
                "Resource",
            ]
        )

    def test_lookup_by_value(self):
        assert NodeType("Skill") is NodeType.SKILL
        assert NodeType("Event") is NodeType.EVENT

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            NodeType("InvalidType")


# ---------------------------------------------------------------------------
# EdgeType enumeration
# ---------------------------------------------------------------------------


class TestEdgeType:
    def test_all_members_present(self):
        expected = {
            "uses",
            "runs_model",
            "current_model",
            "considering_model",
            "compared_with",
            "for",
            "has_issue",
            "possible_cause",
            "at",
            "referred_by",
            "focuses_on",
            "practices_on",
            "status",
            "deadline",
            "requires",
            "supports",
            "conflicts_with",
            "motivated_by",
            "leads_to",
            "part_of",
            "owned_by",
            "blocks",
            "related_to",
        }
        assert {et.value for et in EdgeType} == expected

    def test_edge_type_values_frozenset(self):
        assert EDGE_TYPE_VALUES == frozenset(
            [
                "uses",
                "runs_model",
                "current_model",
                "considering_model",
                "compared_with",
                "for",
                "has_issue",
                "possible_cause",
                "at",
                "referred_by",
                "focuses_on",
                "practices_on",
                "status",
                "deadline",
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

    def test_lookup_by_value(self):
        assert EdgeType("requires") is EdgeType.REQUIRES
        assert EdgeType("conflicts_with") is EdgeType.CONFLICTS_WITH

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            EdgeType("unknown_edge")


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_strips_whitespace(self):
        assert normalize("  hello  ") == "hello"

    def test_casefolds(self):
        assert normalize("Guitar") == "guitar"

    def test_strip_then_casefold(self):
        assert normalize("  Python Programming  ") == "python programming"

    def test_unicode_casefold(self):
        # German sharp s: ß casefolds to ss
        assert normalize("Straße") == "straße".casefold()
        assert normalize("Straße") == "strasse"

    def test_empty_string(self):
        assert normalize("") == ""

    def test_only_whitespace(self):
        assert normalize("   ") == ""

    def test_tabs_and_newlines_stripped(self):
        assert normalize("\t  Data Science \n") == "data science"


# ---------------------------------------------------------------------------
# identity()
# ---------------------------------------------------------------------------


class TestIdentity:
    def test_identity_of_node(self):
        node = Node(id="abc-123", type=NodeType.SKILL, label="  Guitar  ")
        assert identity(node) == ("guitar", NodeType.SKILL)

    def test_identity_of_proposed_node(self):
        pn = ProposedNode(type=NodeType.GOAL, label="Learn Python")
        assert identity(pn) == ("learn python", NodeType.GOAL)

    def test_same_label_different_type_different_identity(self):
        n1 = Node(id="1", type=NodeType.SKILL, label="Python")
        n2 = Node(id="2", type=NodeType.PROJECT, label="Python")
        assert identity(n1) != identity(n2)

    def test_same_normalized_label_same_type_equal_identity(self):
        n1 = Node(id="1", type=NodeType.SKILL, label="Guitar")
        n2 = Node(id="2", type=NodeType.SKILL, label="  guitar  ")
        assert identity(n1) == identity(n2)

    def test_identity_preserves_type_enum(self):
        node = Node(id="x", type=NodeType.EVENT, label="Birthday")
        _, node_type = identity(node)
        assert node_type is NodeType.EVENT


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class TestNode:
    def test_creation_with_defaults(self):
        node = Node(id="uuid-1", type=NodeType.SKILL, label="Guitar")
        assert node.id == "uuid-1"
        assert node.type == NodeType.SKILL
        assert node.label == "Guitar"
        assert node.attributes == {}

    def test_creation_with_attributes(self):
        attrs = {"date": "2025-06-15", "location": "NYC"}
        node = Node(id="uuid-2", type=NodeType.EVENT, label="Concert", attributes=attrs)
        assert node.attributes == {"date": "2025-06-15", "location": "NYC"}

    def test_frozen(self):
        node = Node(id="uuid-1", type=NodeType.SKILL, label="Guitar")
        with pytest.raises(AttributeError):
            node.label = "Piano"  # type: ignore[misc]


class TestEdge:
    def test_creation(self):
        edge = Edge(id="e-1", source="n-1", target="n-2", type=EdgeType.REQUIRES)
        assert edge.id == "e-1"
        assert edge.source == "n-1"
        assert edge.target == "n-2"
        assert edge.type == EdgeType.REQUIRES

    def test_frozen(self):
        edge = Edge(id="e-1", source="n-1", target="n-2", type=EdgeType.SUPPORTS)
        with pytest.raises(AttributeError):
            edge.type = EdgeType.BLOCKS  # type: ignore[misc]


class TestGraph:
    def test_empty_graph(self):
        g = Graph()
        assert g.nodes == []
        assert g.edges == []

    def test_graph_with_data(self):
        n = Node(id="n1", type=NodeType.PERSON, label="Alice")
        e = Edge(id="e1", source="n1", target="n2", type=EdgeType.RELATED_TO)
        g = Graph(nodes=[n], edges=[e])
        assert len(g.nodes) == 1
        assert len(g.edges) == 1


class TestProposedNode:
    def test_creation(self):
        pn = ProposedNode(type=NodeType.HABIT, label="Meditation")
        assert pn.type == NodeType.HABIT
        assert pn.label == "Meditation"
        assert pn.attributes == {}

    def test_no_id_field(self):
        pn = ProposedNode(type=NodeType.RESOURCE, label="Book")
        assert not hasattr(pn, "id")


class TestProposedEdge:
    def test_creation(self):
        pe = ProposedEdge(
            source_label="Guitar",
            source_type=NodeType.SKILL,
            target_label="Practice Daily",
            target_type=NodeType.HABIT,
            type=EdgeType.REQUIRES,
        )
        assert pe.source_label == "Guitar"
        assert pe.source_type == NodeType.SKILL
        assert pe.target_label == "Practice Daily"
        assert pe.target_type == NodeType.HABIT
        assert pe.type == EdgeType.REQUIRES


class TestProposedGraph:
    def test_empty(self):
        pg = ProposedGraph()
        assert pg.nodes == []
        assert pg.edges == []

    def test_with_data(self):
        pn = ProposedNode(type=NodeType.SKILL, label="Cooking")
        pe = ProposedEdge(
            source_label="Cooking",
            source_type=NodeType.SKILL,
            target_label="Healthy Eating",
            target_type=NodeType.GOAL,
            type=EdgeType.SUPPORTS,
        )
        pg = ProposedGraph(nodes=[pn], edges=[pe])
        assert len(pg.nodes) == 1
        assert len(pg.edges) == 1

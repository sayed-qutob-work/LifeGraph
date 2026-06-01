"""Domain types, type sets, and normalization helpers for LifeGraph.

Defines the core data model: NodeType/EdgeType enumerations, Node/Edge/Graph
data structures, their Proposed* counterparts for pre-confirmation proposals,
and the normalize/identity functions used for node deduplication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Type enumerations (Node_Type_Set and Edge_Type_Set)
# ---------------------------------------------------------------------------


class NodeType(Enum):
    """Allowed node types (Node_Type_Set)."""

    SKILL = "Skill"
    GOAL = "Goal"
    HABIT = "Habit"
    PROJECT = "Project"
    EVENT = "Event"
    PERSON = "Person"
    RESOURCE = "Resource"


class EdgeType(Enum):
    """Allowed edge types (Edge_Type_Set)."""

    REQUIRES = "requires"
    SUPPORTS = "supports"
    CONFLICTS_WITH = "conflicts_with"
    MOTIVATED_BY = "motivated_by"
    LEADS_TO = "leads_to"
    PART_OF = "part_of"
    OWNED_BY = "owned_by"
    BLOCKS = "blocks"
    RELATED_TO = "related_to"


# Convenience frozen sets of the string values for validation
NODE_TYPE_VALUES: frozenset[str] = frozenset(nt.value for nt in NodeType)
EDGE_TYPE_VALUES: frozenset[str] = frozenset(et.value for et in EdgeType)


# ---------------------------------------------------------------------------
# Normalization and identity
# ---------------------------------------------------------------------------


def normalize(label: str) -> str:
    """Normalize a label: strip whitespace then casefold for comparison.

    normalize(label) = casefold(strip(label))
    """
    return label.strip().casefold()


def identity(node: "Node | ProposedNode") -> Tuple[str, NodeType]:
    """Compute the deduplication identity of a node.

    identity(node) = (normalize(node.label), node.type)

    Two nodes are the same node iff their identities are equal (Req 4.5).
    """
    return (normalize(node.label), node.type)


# ---------------------------------------------------------------------------
# Persisted data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    """A persisted graph node with a stable UUIDv4 identifier."""

    id: str
    type: NodeType
    label: str  # 1..200 chars stored
    attributes: Dict[str, str] = field(default_factory=dict)  # 0..50 entries


@dataclass(frozen=True)
class Edge:
    """A persisted directed edge between two nodes."""

    id: str
    source: str  # Node.id (must exist, != target)
    target: str  # Node.id (must exist, != source)
    type: EdgeType


@dataclass
class Graph:
    """A complete graph snapshot: nodes and edges."""

    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Proposed (pre-confirmation) data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposedNode:
    """A node proposed by the Input_Parser, not yet persisted.

    Has no id — the id is assigned at persistence time after deduplication.
    """

    type: NodeType
    label: str
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProposedEdge:
    """An edge proposed by the Input_Parser.

    References endpoints by (label, type) rather than id, because ids are
    assigned only at persistence time after deduplication (Req 4.4).
    """

    source_label: str
    source_type: NodeType
    target_label: str
    target_type: NodeType
    type: EdgeType


@dataclass
class ProposedGraph:
    """A proposal produced by the Input_Parser awaiting user confirmation.

    Contains 0..100 proposed nodes and 0..200 proposed edges.
    """

    nodes: List[ProposedNode] = field(default_factory=list)
    edges: List[ProposedEdge] = field(default_factory=list)

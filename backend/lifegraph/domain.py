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
    ORGANIZATION = "Organization"
    PROGRAM = "Program"
    TOOL = "Tool"
    TECHNOLOGY = "Technology"
    MODEL = "Model"
    HARDWARE = "Hardware"
    TOPIC = "Topic"
    RECIPE = "Recipe"
    ISSUE = "Issue"
    PLACE = "Place"
    RESOURCE = "Resource"


class EdgeType(Enum):
    """Allowed edge types (Edge_Type_Set)."""

    USES = "uses"
    RUNS_MODEL = "runs_model"
    CURRENT_MODEL = "current_model"
    CONSIDERING_MODEL = "considering_model"
    COMPARED_WITH = "compared_with"
    FOR = "for"
    HAS_ISSUE = "has_issue"
    POSSIBLE_CAUSE = "possible_cause"
    AT = "at"
    REFERRED_BY = "referred_by"
    FOCUSES_ON = "focuses_on"
    PRACTICES_ON = "practices_on"
    STATUS = "status"
    DEADLINE = "deadline"
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
    created_at: str = ""   # ISO-8601 UTC; empty for pre-migration rows
    updated_at: str = ""   # ISO-8601 UTC; empty for pre-migration rows
    origin: str = "manual" # "manual" | "parsed"


@dataclass(frozen=True)
class Edge:
    """A persisted directed edge between two nodes."""

    id: str
    source: str  # Node.id (must exist, != target)
    target: str  # Node.id (must exist, != source)
    type: EdgeType
    created_at: str = ""   # ISO-8601 UTC; empty for pre-migration rows
    updated_at: str = ""   # ISO-8601 UTC; empty for pre-migration rows
    origin: str = "manual" # "manual" | "parsed"


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


# ---------------------------------------------------------------------------
# Held observations (salience review queue)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeldObservation:
    """An observation the salience filter held back from auto-persisting.

    Stored verbatim (the original sentence plus the parsed proposal) so the
    user can later review it and either keep (re-apply the proposal) or drop it.
    """

    id: str
    sentence: str
    proposal: "ProposedGraph"
    reason: str
    signals: List[str] = field(default_factory=list)
    held_at: str = ""
    status: str = "pending"  # "pending" | "kept" | "dropped"


def proposal_to_dict(proposal: ProposedGraph) -> Dict:
    """Serialize a ProposedGraph to a JSON-safe dict (for held-observation storage)."""
    return {
        "nodes": [
            {"type": n.type.value, "label": n.label, "attributes": dict(n.attributes)}
            for n in proposal.nodes
        ],
        "edges": [
            {
                "source_label": e.source_label,
                "source_type": e.source_type.value,
                "target_label": e.target_label,
                "target_type": e.target_type.value,
                "type": e.type.value,
            }
            for e in proposal.edges
        ],
    }


def proposal_from_dict(data: Dict) -> ProposedGraph:
    """Reconstruct a ProposedGraph from a dict produced by proposal_to_dict."""
    nodes = [
        ProposedNode(
            type=NodeType(n["type"]),
            label=n["label"],
            attributes=dict(n.get("attributes", {})),
        )
        for n in data.get("nodes", [])
    ]
    edges = [
        ProposedEdge(
            source_label=e["source_label"],
            source_type=NodeType(e["source_type"]),
            target_label=e["target_label"],
            target_type=NodeType(e["target_type"]),
            type=EdgeType(e["type"]),
        )
        for e in data.get("edges", [])
    ]
    return ProposedGraph(nodes=nodes, edges=edges)

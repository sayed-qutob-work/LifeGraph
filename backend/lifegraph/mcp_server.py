"""MCP server for LifeGraph — exposes graph tools over stdio.

Run via:
    python -m lifegraph.mcp_server

or configure in Claude Desktop's MCP settings:
    {
        "command": "python",
        "args": ["-m", "lifegraph.mcp_server"],
        "cwd": "/path/to/LifeGraph/backend"
    }

Tools exposed:
    search_graph    — filter nodes/edges by label term and/or type
    get_context     — BFS neighbourhood snapshot for an LLM prompt
    add_observation — parse a sentence, salience-filter it, then keep/hold/drop
    list_held       — list observations held back by the salience filter
    review_held     — resolve a held observation (keep → persist, or drop)
    upsert_node     — create or return a node by (label, type) identity
    create_edge     — create a directed edge between two existing nodes
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from lifegraph.config import DEFAULT_DB_PATH
from lifegraph.domain import EDGE_TYPE_VALUES, NODE_TYPE_VALUES, EdgeType, NodeType
from lifegraph.factory import make_parser, make_store
from lifegraph.ollama_client import OllamaTimeoutError, OllamaUnavailableError
from lifegraph.parser import InputValidationError, InvalidTypeError, UnparseableResponse
from lifegraph.salience import SalienceDecision, classify
from lifegraph.search import filter_graph
from lifegraph.serializer import ContextSerializer
from lifegraph.store import GraphStore

mcp = FastMCP("LifeGraph")

# ---------------------------------------------------------------------------
# Lazy singletons — initialised on first tool call so import stays fast.
# ---------------------------------------------------------------------------

_store: GraphStore | None = None
_parser = None


def _get_store() -> GraphStore:
    global _store
    if _store is None:
        db_path = os.environ.get("LIFEGRAPH_DB_PATH", DEFAULT_DB_PATH)
        _store = make_store(db_path)
    return _store


def _get_parser():
    global _parser
    if _parser is None:
        _parser = make_parser()
    return _parser


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _node_dict(node) -> dict[str, Any]:
    return {
        "id": node.id,
        "type": node.type.value,
        "label": node.label,
        "attributes": node.attributes,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
        "origin": node.origin,
    }


def _edge_dict(edge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "type": edge.type.value,
        "created_at": edge.created_at,
        "updated_at": edge.updated_at,
        "origin": edge.origin,
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search_graph(q: str = "", types: list[str] | None = None) -> dict[str, Any]:
    """Search the knowledge graph by label term and/or node types.

    Args:
        q: Case-insensitive substring to match against node labels.
        types: Optional list of NodeType values to filter by,
               e.g. ["Skill", "Goal"]. Omit to search all types.

    Returns:
        {"nodes": [...], "edges": [...]} with matching nodes and their
        connecting edges.
    """
    store = _get_store()
    graph = store.get_graph()

    valid_types: set[NodeType] | None = None
    if types:
        valid_types = {NodeType(t) for t in types if t in NODE_TYPE_VALUES}
        if not valid_types:
            valid_types = None

    filtered = filter_graph(graph, types=valid_types, term=q if q else None)
    return {
        "nodes": [_node_dict(n) for n in filtered.nodes],
        "edges": [_edge_dict(e) for e in filtered.edges],
    }


@mcp.tool()
def get_context(node_id: str, max_hops: int = 2) -> str:
    """Get a plain-text context snapshot for a node and its neighbourhood.

    The output is suitable for pasting directly into an LLM prompt as
    background knowledge.

    Args:
        node_id: The unique identifier of the focal node.
        max_hops: BFS traversal depth (1–5, default 2).

    Returns:
        A plain-text context block listing the focal node, its neighbours,
        and their relationships.
    """
    store = _get_store()
    graph = store.get_graph()
    hops = max(1, min(5, max_hops))
    serializer = ContextSerializer(max_hops=hops)
    return serializer.serialize(graph, node_id)


@mcp.tool()
def add_observation(sentence: str) -> dict[str, Any]:
    """Parse a natural-language sentence and add extracted knowledge to the graph.

    Sends the sentence to Ollama and extracts proposed nodes and edges, then runs
    a salience filter before persisting so the graph stays clean during passive
    capture:

    - "kept":    a stable fact about you — persisted (with deduplication) and the
                 source sentence recorded for provenance.
    - "held":    parsed into a graph but not clearly a stable fact — stored in the
                 review queue (see list_held / review_held) instead of persisted.
    - "dropped": transient (a question, hypothetical, code snippet, command, or an
                 empty extraction) — discarded without persisting.

    Args:
        sentence: A description of something to remember, e.g.
                  "Learning Python supports my goal of building apps".

    Returns:
        A dict with a "status" of "kept" | "held" | "dropped", a "reason", and —
        for "kept" — the {"nodes": [...], "edges": [...]} that were created or
        resolved; for "held" — the "held_id".
    """
    parser = _get_parser()
    if parser is None:
        raise RuntimeError(
            "Parser unavailable: ensure Ollama is running and "
            "LIFEGRAPH_MODEL is set (or lifegraph.toml exists)."
        )
    store = _get_store()

    try:
        proposed = parser.parse(sentence)
    except (InvalidTypeError, UnparseableResponse) as exc:
        return {
            "status": "dropped",
            "reason": f"LLM produced unparseable output: {exc}",
            "signals": ["parse_error"],
            "nodes": [],
            "edges": [],
        }
    except InputValidationError as exc:
        return {
            "status": "dropped",
            "reason": f"Invalid input: {exc}",
            "signals": ["input_validation_error"],
            "nodes": [],
            "edges": [],
        }
    except OllamaUnavailableError as exc:
        return {
            "status": "error",
            "reason": f"Ollama unavailable: {exc}",
            "signals": ["ollama_unavailable"],
            "nodes": [],
            "edges": [],
        }
    except OllamaTimeoutError:
        return {
            "status": "error",
            "reason": "Ollama request timed out.",
            "signals": ["ollama_timeout"],
            "nodes": [],
            "edges": [],
        }

    verdict = classify(sentence, proposed)

    if verdict.decision is SalienceDecision.DROP:
        return {
            "status": "dropped",
            "reason": verdict.reason,
            "signals": verdict.signals,
            "nodes": [],
            "edges": [],
        }

    if verdict.decision is SalienceDecision.HOLD:
        held = store.hold_observation(
            sentence, proposed, reason=verdict.reason, signals=verdict.signals
        )
        return {
            "status": "held",
            "reason": verdict.reason,
            "signals": verdict.signals,
            "held_id": held.id,
            "nodes": [],
            "edges": [],
        }

    # KEEP — persist and record provenance.
    result = store.apply_proposal(proposed)
    try:
        store.record_capture(
            sentence,
            [n.id for n in result.nodes],
            [e.id for e in result.edges],
        )
    except Exception:
        pass
    return {
        "status": "kept",
        "reason": verdict.reason,
        "signals": verdict.signals,
        "nodes": [_node_dict(n) for n in result.nodes],
        "edges": [_edge_dict(e) for e in result.edges],
    }


@mcp.tool()
def list_held() -> dict[str, Any]:
    """List observations the salience filter held back for review.

    These were parsed successfully but not auto-persisted because they were not
    clearly stable facts about you. Review each with review_held.

    Returns:
        {"held": [{"id", "sentence", "reason", "signals",
                   "node_count", "edge_count", "held_at"}, ...]}
    """
    store = _get_store()
    held = store.list_held(status="pending")
    return {
        "held": [
            {
                "id": h.id,
                "sentence": h.sentence,
                "reason": h.reason,
                "signals": h.signals,
                "node_count": len(h.proposal.nodes),
                "edge_count": len(h.proposal.edges),
                "held_at": h.held_at,
            }
            for h in held
        ]
    }


@mcp.tool()
def review_held(held_id: str, decision: str) -> dict[str, Any]:
    """Resolve a held observation: keep it (persist) or drop it (discard).

    Args:
        held_id: The id of the held observation (from list_held).
        decision: "keep" to persist the held proposal into the graph, or
                  "drop" to discard it. Either way the item leaves the queue.

    Returns:
        For "keep": {"status": "kept", "nodes": [...], "edges": [...]}.
        For "drop": {"status": "dropped"}.
    """
    decision = (decision or "").strip().lower()
    if decision not in ("keep", "drop"):
        raise ValueError("decision must be 'keep' or 'drop'")

    store = _get_store()
    held = store.get_held(held_id)
    if held is None:
        raise ValueError(f"Held observation not found: '{held_id}'")
    if held.status != "pending":
        raise ValueError(
            f"Held observation '{held_id}' is already resolved (status={held.status})."
        )

    if decision == "drop":
        store.resolve_held(held_id, "dropped")
        return {"status": "dropped", "nodes": [], "edges": []}

    # keep — persist the stored proposal, record provenance, then resolve.
    result = store.apply_proposal(held.proposal)
    try:
        store.record_capture(
            held.sentence,
            [n.id for n in result.nodes],
            [e.id for e in result.edges],
        )
    except Exception:
        pass
    store.resolve_held(held_id, "kept")
    return {
        "status": "kept",
        "nodes": [_node_dict(n) for n in result.nodes],
        "edges": [_edge_dict(e) for e in result.edges],
    }


@mcp.tool()
def upsert_node(label: str, type: str, attributes: str = "{}") -> dict[str, Any]:
    """Create or return a node with the given identity (label + type).

    If a node with the same normalised label and type already exists it is
    returned unchanged. Otherwise a new node is created.

    Args:
        label: The node label (1–100 characters).
        type: A valid NodeType value, e.g. "Skill", "Goal", "Event", "Person".
        attributes: JSON object string of extra key-value metadata,
                    e.g. '{"date":"2026-06-01"}'. Defaults to '{}'.

    Returns:
        The created or existing node as a JSON object.
    """
    if type not in NODE_TYPE_VALUES:
        raise ValueError(
            f"Invalid node type '{type}'. Valid types: {sorted(NODE_TYPE_VALUES)}"
        )
    attrs: dict[str, str] = {}
    raw = (attributes or "{}").strip()
    if raw and raw != "{}":
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("attributes must be a JSON object")
        attrs = parsed
    store = _get_store()
    node = store.upsert_node(label, NodeType(type), attributes=attrs)
    return _node_dict(node)


@mcp.tool()
def create_edge(source_id: str, target_id: str, type: str) -> dict[str, Any]:
    """Create a directed edge between two existing nodes.

    Args:
        source_id: The unique id of the source node.
        target_id: The unique id of the target node (must differ from source_id).
        type: A valid EdgeType value, e.g. "supports", "leads_to", "uses".

    Returns:
        The created edge as a JSON object.
    """
    if type not in EDGE_TYPE_VALUES:
        raise ValueError(
            f"Invalid edge type '{type}'. Valid types: {sorted(EDGE_TYPE_VALUES)}"
        )
    store = _get_store()
    edge = store.create_edge(source_id, target_id, EdgeType(type))
    return _edge_dict(edge)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()

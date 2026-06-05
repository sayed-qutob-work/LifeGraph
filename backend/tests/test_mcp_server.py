"""Tests for the MCP server's salience-gated add_observation and review tools.

mcp_server uses lazy module-level singletons (_store, _parser). We inject a real
GraphStore on a temp DB and a fake parser returning a preset ProposedGraph, then
call the tool functions directly (FastMCP's @tool decorator leaves them callable).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lifegraph import mcp_server
from lifegraph.domain import (
    EdgeType,
    NodeType,
    ProposedEdge,
    ProposedGraph,
    ProposedNode,
)
from lifegraph.store import GraphStore


class _FakeParser:
    """Returns a fixed ProposedGraph regardless of the sentence."""

    def __init__(self, proposal: ProposedGraph) -> None:
        self._proposal = proposal

    def parse(self, sentence: str) -> ProposedGraph:
        return self._proposal


def _deterministic_id_factory():
    counter = [0]

    def factory() -> str:
        counter[0] += 1
        return f"id-{counter[0]:04d}"

    return factory


@pytest.fixture
def wired(tmp_path: Path, monkeypatch):
    """Wire mcp_server's singletons to a temp store and a configurable parser."""
    store = GraphStore(str(tmp_path / "mcp.db"), id_factory=_deterministic_id_factory())
    monkeypatch.setattr(mcp_server, "_store", store)

    def set_proposal(proposal: ProposedGraph) -> None:
        monkeypatch.setattr(mcp_server, "_parser", _FakeParser(proposal))

    # default parser yields an empty proposal
    set_proposal(ProposedGraph())
    return store, set_proposal


def _tool_proposal() -> ProposedGraph:
    return ProposedGraph(nodes=[ProposedNode(type=NodeType.TOOL, label="Ollama")])


# ---------------------------------------------------------------------------
# add_observation branches
# ---------------------------------------------------------------------------


def test_keep_persists(wired) -> None:
    store, set_proposal = wired
    set_proposal(_tool_proposal())
    result = mcp_server.add_observation("I use Ollama for local inference")
    assert result["status"] == "kept"
    assert any(n["label"] == "Ollama" for n in result["nodes"])
    assert {n.label for n in store.get_graph().nodes} == {"Ollama"}


def test_drop_does_not_persist(wired) -> None:
    store, set_proposal = wired
    set_proposal(_tool_proposal())
    result = mcp_server.add_observation("Should I use Ollama?")
    assert result["status"] == "dropped"
    assert result["nodes"] == []
    assert store.get_graph().nodes == []
    assert store.list_held() == []


def test_hold_queues_without_persisting(wired) -> None:
    store, set_proposal = wired
    set_proposal(_tool_proposal())
    # First-person reference but not a stative marker → HOLD.
    result = mcp_server.add_observation("I tried Ollama briefly")
    assert result["status"] == "held"
    assert result["held_id"]
    assert store.get_graph().nodes == []
    pending = store.list_held()
    assert len(pending) == 1
    assert pending[0].id == result["held_id"]


# ---------------------------------------------------------------------------
# list_held / review_held
# ---------------------------------------------------------------------------


def test_review_held_keep_persists_and_clears_queue(wired) -> None:
    store, set_proposal = wired
    set_proposal(_tool_proposal())
    held_id = mcp_server.add_observation("I tried Ollama briefly")["held_id"]

    listed = mcp_server.list_held()["held"]
    assert len(listed) == 1
    assert listed[0]["id"] == held_id

    result = mcp_server.review_held(held_id, "keep")
    assert result["status"] == "kept"
    assert {n.label for n in store.get_graph().nodes} == {"Ollama"}
    assert mcp_server.list_held()["held"] == []


def test_review_held_drop_discards(wired) -> None:
    store, set_proposal = wired
    set_proposal(_tool_proposal())
    held_id = mcp_server.add_observation("I tried Ollama briefly")["held_id"]

    result = mcp_server.review_held(held_id, "drop")
    assert result["status"] == "dropped"
    assert store.get_graph().nodes == []
    assert mcp_server.list_held()["held"] == []


def test_review_held_rejects_unknown_id(wired) -> None:
    with pytest.raises(ValueError):
        mcp_server.review_held("nope", "keep")


def test_review_held_rejects_bad_decision(wired) -> None:
    store, set_proposal = wired
    set_proposal(_tool_proposal())
    held_id = mcp_server.add_observation("I tried Ollama briefly")["held_id"]
    with pytest.raises(ValueError):
        mcp_server.review_held(held_id, "maybe")


def test_review_held_rejects_double_resolve(wired) -> None:
    store, set_proposal = wired
    set_proposal(_tool_proposal())
    held_id = mcp_server.add_observation("I tried Ollama briefly")["held_id"]
    mcp_server.review_held(held_id, "drop")
    with pytest.raises(ValueError):
        mcp_server.review_held(held_id, "keep")

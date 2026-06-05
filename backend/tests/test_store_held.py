"""Tests for GraphStore held-observation queue (salience review queue).

Covers hold_observation / list_held / get_held / resolve_held and the
ProposedGraph (de)serialization used to store a held proposal verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lifegraph.domain import (
    EdgeType,
    NodeType,
    ProposedEdge,
    ProposedGraph,
    ProposedNode,
    proposal_from_dict,
    proposal_to_dict,
)
from lifegraph.store import GraphStore


def _make_db_path(tmp_path: Path, name: str = "held.db") -> str:
    return str(tmp_path / name)


def _deterministic_id_factory():
    counter = [0]

    def factory() -> str:
        counter[0] += 1
        return f"id-{counter[0]:04d}"

    return factory


def _sample_proposal() -> ProposedGraph:
    return ProposedGraph(
        nodes=[
            ProposedNode(type=NodeType.TOOL, label="Ollama", attributes={"v": "1"}),
            ProposedNode(type=NodeType.MODEL, label="llama3"),
        ],
        edges=[
            ProposedEdge(
                source_label="Ollama",
                source_type=NodeType.TOOL,
                target_label="llama3",
                target_type=NodeType.MODEL,
                type=EdgeType.RUNS_MODEL,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Proposal (de)serialization round-trip
# ---------------------------------------------------------------------------


class TestProposalRoundTrip:
    def test_round_trip_preserves_proposal(self) -> None:
        original = _sample_proposal()
        restored = proposal_from_dict(proposal_to_dict(original))
        assert restored == original


# ---------------------------------------------------------------------------
# Hold / list / get / resolve
# ---------------------------------------------------------------------------


class TestHeldQueue:
    def test_hold_then_list(self, tmp_path: Path) -> None:
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        proposal = _sample_proposal()
        held = store.hold_observation(
            "Ollama runs llama3", proposal, reason="uncertain", signals=["x"]
        )
        assert held.status == "pending"
        assert held.held_at

        pending = store.list_held()
        assert len(pending) == 1
        assert pending[0].id == held.id
        assert pending[0].sentence == "Ollama runs llama3"
        assert pending[0].reason == "uncertain"
        assert pending[0].signals == ["x"]
        # Proposal stored verbatim.
        assert pending[0].proposal == proposal

    def test_hold_does_not_write_graph(self, tmp_path: Path) -> None:
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        store.hold_observation("Ollama runs llama3", _sample_proposal())
        graph = store.get_graph()
        assert graph.nodes == []
        assert graph.edges == []

    def test_get_held(self, tmp_path: Path) -> None:
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        held = store.hold_observation("s", _sample_proposal())
        fetched = store.get_held(held.id)
        assert fetched is not None
        assert fetched.id == held.id
        assert store.get_held("nope") is None

    def test_resolve_removes_from_pending(self, tmp_path: Path) -> None:
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        held = store.hold_observation("s", _sample_proposal())
        store.resolve_held(held.id, "kept")
        assert store.list_held(status="pending") == []
        kept = store.list_held(status="kept")
        assert len(kept) == 1
        assert kept[0].id == held.id

    def test_resolve_unknown_raises(self, tmp_path: Path) -> None:
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        with pytest.raises(ValueError):
            store.resolve_held("missing", "dropped")

    def test_kept_proposal_can_be_applied(self, tmp_path: Path) -> None:
        """A held proposal, once retrieved, applies into a real graph."""
        store = GraphStore(_make_db_path(tmp_path), id_factory=_deterministic_id_factory())
        held = store.hold_observation("Ollama runs llama3", _sample_proposal())
        result = store.apply_proposal(held.proposal)
        store.resolve_held(held.id, "kept")

        labels = {n.label for n in store.get_graph().nodes}
        assert {"Ollama", "llama3"} <= labels
        assert len(result.edges) == 1

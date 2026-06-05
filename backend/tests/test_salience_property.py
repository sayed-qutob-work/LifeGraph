"""Property tests for the salience filter invariants.

These assert structural guarantees that must hold for *any* input, independent
of the exact heuristic tuning:

- The verdict is always exactly one of KEEP / HOLD / DROP.
- An empty proposal is never KEPT (nothing to persist).
- A question (trailing '?') is never KEPT (it is transient).
- KEEP requires at least one node in the proposal.
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from lifegraph.domain import NodeType, ProposedGraph, ProposedNode
from lifegraph.salience import SalienceDecision, classify


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_node_type_strategy = st.sampled_from(list(NodeType))

_label_strategy = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")

_proposed_node_strategy = st.builds(
    ProposedNode, type=_node_type_strategy, label=_label_strategy
)

_proposal_strategy = st.builds(
    ProposedGraph,
    nodes=st.lists(_proposed_node_strategy, max_size=6),
    edges=st.just([]),
)

_sentence_strategy = st.text(min_size=0, max_size=200)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(sentence=_sentence_strategy, proposal=_proposal_strategy)
def test_verdict_is_always_a_valid_decision(sentence, proposal) -> None:
    verdict = classify(sentence, proposal)
    assert verdict.decision in (
        SalienceDecision.KEEP,
        SalienceDecision.HOLD,
        SalienceDecision.DROP,
    )
    assert isinstance(verdict.reason, str) and verdict.reason
    assert isinstance(verdict.signals, list)


@settings(max_examples=100)
@given(sentence=_sentence_strategy)
def test_empty_proposal_never_kept(sentence) -> None:
    verdict = classify(sentence, ProposedGraph())
    assert verdict.decision is SalienceDecision.DROP


@settings(max_examples=200)
@given(sentence=_sentence_strategy, proposal=_proposal_strategy)
def test_question_never_kept(sentence, proposal) -> None:
    question = sentence + "?"
    verdict = classify(question, proposal)
    assert verdict.decision is not SalienceDecision.KEEP


@settings(max_examples=200)
@given(sentence=_sentence_strategy, proposal=_proposal_strategy)
def test_keep_requires_nodes(sentence, proposal) -> None:
    verdict = classify(sentence, proposal)
    if verdict.decision is SalienceDecision.KEEP:
        assert len(proposal.nodes) >= 1

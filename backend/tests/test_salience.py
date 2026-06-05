"""Tests for the salience filter — the keep/hold/drop gate before persistence.

The classifier is a pure function of (sentence, ProposedGraph), so these tests
build proposals directly rather than going through Ollama.
"""

from __future__ import annotations

import pytest

from lifegraph.domain import (
    EdgeType,
    NodeType,
    ProposedEdge,
    ProposedGraph,
    ProposedNode,
)
from lifegraph.salience import SalienceDecision, classify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(label: str, type: NodeType) -> ProposedNode:
    return ProposedNode(type=type, label=label)


def _tool_proposal() -> ProposedGraph:
    """A proposal touching a user-relevant (Tool) node."""
    return ProposedGraph(nodes=[_node("Ollama", NodeType.TOOL)], edges=[])


def _person_proposal() -> ProposedGraph:
    """A proposal about a third party with no user-relevant type."""
    return ProposedGraph(nodes=[_node("Alice", NodeType.PERSON)], edges=[])


# ---------------------------------------------------------------------------
# DROP cases
# ---------------------------------------------------------------------------


class TestDrop:
    def test_empty_proposal_drops(self) -> None:
        verdict = classify("anything at all", ProposedGraph())
        assert verdict.decision is SalienceDecision.DROP
        assert "empty_proposal" in verdict.signals

    def test_trailing_question_mark_drops(self) -> None:
        # Even a tool-bearing proposal is dropped if the sentence is a question.
        verdict = classify("Should I use Ollama for this?", _tool_proposal())
        assert verdict.decision is SalienceDecision.DROP
        assert "question_mark" in verdict.signals

    def test_interrogative_opener_without_qmark_drops(self) -> None:
        verdict = classify("How do I run Ollama locally", _tool_proposal())
        assert verdict.decision is SalienceDecision.DROP
        assert "interrogative_opener" in verdict.signals

    @pytest.mark.parametrize(
        "sentence",
        [
            "What if I switched my GPU to a 4090",
            "Suppose I used a different model",
            "Imagine I ran llama3 on the laptop",
        ],
    )
    def test_hypotheticals_drop(self, sentence: str) -> None:
        verdict = classify(sentence, _tool_proposal())
        assert verdict.decision is SalienceDecision.DROP
        assert "hypothetical" in verdict.signals

    @pytest.mark.parametrize(
        "sentence",
        [
            "Can you write a script that uses Ollama",
            "Please fix the bug in my project",
            "Explain how llama3 works",
        ],
    )
    def test_assistant_commands_drop(self, sentence: str) -> None:
        verdict = classify(sentence, _tool_proposal())
        assert verdict.decision is SalienceDecision.DROP
        assert "assistant_command" in verdict.signals

    def test_code_fence_drops(self) -> None:
        sentence = "Here is the config:\n```\nmodel = llama3\n```"
        verdict = classify(sentence, _tool_proposal())
        assert verdict.decision is SalienceDecision.DROP
        assert "code_snippet" in verdict.signals

    def test_dense_code_punctuation_drops(self) -> None:
        sentence = "store.execute(sql, (a, b)); return rows[0];"
        verdict = classify(sentence, _tool_proposal())
        assert verdict.decision is SalienceDecision.DROP
        assert "code_snippet" in verdict.signals


# ---------------------------------------------------------------------------
# KEEP cases
# ---------------------------------------------------------------------------


class TestKeep:
    @pytest.mark.parametrize(
        "sentence",
        [
            "I use Ollama for local inference",
            "I'm running llama3 on my machine",
            "I switched to Ollama last week",
            "My setup uses Ollama",
        ],
    )
    def test_first_person_fact_about_tool_keeps(self, sentence: str) -> None:
        verdict = classify(sentence, _tool_proposal())
        assert verdict.decision is SalienceDecision.KEEP
        assert "first_person_stative" in verdict.signals
        assert "user_relevant_type" in verdict.signals


# ---------------------------------------------------------------------------
# HOLD cases
# ---------------------------------------------------------------------------


class TestHold:
    def test_first_person_but_no_user_relevant_type_holds(self) -> None:
        # First-person, but the only entity is a third-party Person.
        verdict = classify("I met Alice yesterday", _person_proposal())
        assert verdict.decision is SalienceDecision.HOLD

    def test_user_relevant_type_but_not_first_person_holds(self) -> None:
        # A tool is mentioned, but the sentence is not about the user's setup.
        verdict = classify("Ollama is a popular local runtime", _tool_proposal())
        assert verdict.decision is SalienceDecision.HOLD

    def test_third_party_statement_holds(self) -> None:
        verdict = classify("Alice referred Bob to the program", _person_proposal())
        assert verdict.decision is SalienceDecision.HOLD


# ---------------------------------------------------------------------------
# Verdict shape
# ---------------------------------------------------------------------------


class TestVerdictShape:
    def test_reason_always_present(self) -> None:
        verdict = classify("I use Ollama", _tool_proposal())
        assert verdict.reason
        assert isinstance(verdict.signals, list)

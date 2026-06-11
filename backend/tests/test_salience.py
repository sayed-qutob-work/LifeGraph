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
from lifegraph.salience import SalienceDecision, classify, transient_drop_signals


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

    def test_first_person_ambiguous_action_holds(self) -> None:
        # First-person reference keeps it out of DROP, but "tried" is not a
        # stative marker → not enough confidence to auto-KEEP → HOLD.
        verdict = classify("I tried Ollama briefly", _tool_proposal())
        assert verdict.decision is SalienceDecision.HOLD

    def test_user_relevant_type_but_not_first_person_drops(self) -> None:
        # A tool is mentioned, but there is no first-person reference → general
        # claim about an external entity → DROP.
        verdict = classify("Ollama is a popular local runtime", _tool_proposal())
        assert verdict.decision is SalienceDecision.DROP
        assert "no_first_person_reference" in verdict.signals

    def test_third_party_statement_drops(self) -> None:
        # No first-person reference → general third-party statement → DROP.
        verdict = classify("Alice referred Bob to the program", _person_proposal())
        assert verdict.decision is SalienceDecision.DROP
        assert "no_first_person_reference" in verdict.signals


# ---------------------------------------------------------------------------
# Verdict shape
# ---------------------------------------------------------------------------


class TestVerdictShape:
    def test_reason_always_present(self) -> None:
        verdict = classify("I use Ollama", _tool_proposal())
        assert verdict.reason
        assert isinstance(verdict.signals, list)


# ---------------------------------------------------------------------------
# First-person word boundaries (the "daisyui" bug)
# ---------------------------------------------------------------------------


class TestFirstPersonWordBoundaries:
    @pytest.mark.parametrize(
        "sentence",
        [
            "import daisyui from 'daisyui'",     # "...daisyu[i f]rom" is not "i "
            "the wifi is flaky at the office",   # "...wif[i i]s" is not "i "
            "Ollama is a popular local runtime",
        ],
    )
    def test_word_endings_in_i_are_not_first_person(self, sentence: str) -> None:
        verdict = classify(sentence, _tool_proposal())
        assert verdict.decision is SalienceDecision.DROP
        assert "no_first_person_reference" in verdict.signals

    @pytest.mark.parametrize(
        "sentence",
        [
            "that laptop belongs to me",     # "me" at sentence end (no spaces around)
            "I used Vim for a decade",       # "i use" cue must still cover "i used"
        ],
    )
    def test_genuine_first_person_still_detected(self, sentence: str) -> None:
        verdict = classify(sentence, _person_proposal())
        assert "no_first_person_reference" not in verdict.signals


# ---------------------------------------------------------------------------
# transient_drop_signals — the sentence-only pre-screen contract
# ---------------------------------------------------------------------------


class TestTransientDropSignals:
    def test_flags_transient_sentences_without_a_proposal(self) -> None:
        assert "question_mark" in transient_drop_signals("Should I use Ollama?")
        assert "no_first_person_reference" in transient_drop_signals(
            "Ollama is a popular runtime."
        )
        assert "code_snippet" in transient_drop_signals("```python")
        assert transient_drop_signals("I use Ollama for local inference") == []

    @pytest.mark.parametrize(
        "sentence",
        [
            "Should I use Ollama for this?",
            "Ollama is a popular local runtime",
            "what if I switched to vLLM",
            "can you fix the parser for me",
            "store.execute(sql, (a, b)); return rows[0];",
        ],
    )
    def test_any_flagged_sentence_is_dropped_by_classify(self, sentence: str) -> None:
        # The pre-screen guarantee: a non-empty result means classify DROPs the
        # sentence regardless of what the parser proposes.
        assert transient_drop_signals(sentence)
        verdict = classify(sentence, _tool_proposal())
        assert verdict.decision is SalienceDecision.DROP

"""Salience filter — the gate that decides whether parsed knowledge enters the graph.

LifeGraph's passive-capture path (``add_observation``) parses every sentence it is
given, but persisting *everything* fills the graph with noise — questions, code
snippets, hypotheticals, and facts about third parties that have nothing to do
with the user. A noisy graph is an untrustworthy graph, and trust is the entire
value proposition (see ``task.md`` §2.7).

This module is a pure, dependency-free classifier (no I/O, like ``serializer.py``)
that inspects the raw sentence together with the ``ProposedGraph`` the parser
produced and returns one of three verdicts:

    KEEP — a stable fact about the user (their tools/models/hardware/projects/
           skills/goals/decisions). Safe to persist automatically.
    HOLD — parsed into something, but it is not clearly a stable user fact.
           Routed to a review queue instead of being persisted (this is the
           seed of the Month-1 per-session review queue).
    DROP — transient: a question, hypothetical, code snippet, command to the
           assistant, or an empty extraction. Discarded without persisting.

v1 is deliberately cheap heuristics. The boundary is conservative: when a
sentence is ambiguous it is HELD, never auto-KEPT, because a wrong auto-keep
costs trust while a wrong hold only costs a review click. A future LLM-judge can
replace or augment ``classify`` without changing any caller — the contract is
just ``(sentence, ProposedGraph) -> SalienceVerdict``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from lifegraph.domain import NodeType, ProposedGraph


# ---------------------------------------------------------------------------
# Verdict types
# ---------------------------------------------------------------------------


class SalienceDecision(Enum):
    """The three possible outcomes of the salience gate."""

    KEEP = "keep"  # stable user fact — persist automatically
    HOLD = "hold"  # uncertain — route to review queue, do not persist
    DROP = "drop"  # transient — discard without persisting


@dataclass(frozen=True)
class SalienceVerdict:
    """The result of classifying one observation.

    Attributes
    ----------
    decision:
        KEEP, HOLD, or DROP.
    reason:
        A short human-readable justification, surfaced in the review queue and
        in the ``add_observation`` response.
    signals:
        The names of the heuristics that fired, for tuning and debugging.
    """

    decision: SalienceDecision
    reason: str
    signals: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Heuristic signal vocabulary
# ---------------------------------------------------------------------------

# Node types that describe the user's setup / commitments. A proposal touching
# any of these is, on its own, evidence of a stable fact worth keeping.
_USER_RELEVANT_TYPES: frozenset[NodeType] = frozenset({
    NodeType.TOOL,
    NodeType.MODEL,
    NodeType.HARDWARE,
    NodeType.PROJECT,
    NodeType.SKILL,
    NodeType.GOAL,
    NodeType.HABIT,
    NodeType.TECHNOLOGY,
    NodeType.PROGRAM,
})

# Markers that a sentence is a hypothetical rather than a statement of fact.
_HYPOTHETICAL_MARKERS: tuple[str, ...] = (
    "what if",
    "suppose",
    "imagine",
    "hypothetically",
    "let's say",
    "lets say",
    "what would happen",
    "pretend",
)

# Phrasings that mean the user is asking the assistant to *do* something, not
# recording a fact about themselves.
_ASSISTANT_COMMAND_MARKERS: tuple[str, ...] = (
    "can you",
    "could you",
    "would you",
    "please ",
    "write a",
    "write me",
    "fix the",
    "fix this",
    "explain ",
    "show me",
    "give me",
    "generate ",
    "implement ",
    "debug ",
    "refactor ",
    "help me",
)

# Question words that, when they *open* a sentence, signal an interrogative even
# without a trailing question mark.
_INTERROGATIVE_OPENERS: tuple[str, ...] = (
    "what",
    "why",
    "how",
    "when",
    "where",
    "who",
    "which",
    "can",
    "could",
    "should",
    "would",
    "is ",
    "are ",
    "do ",
    "does ",
    "did ",
)

# First-person stative cues: "I <verb>" / "my ..." describing the user's setup.
# Matched against the lowercased sentence start and as whole-word occurrences.
_FIRST_PERSON_STATIVE: tuple[str, ...] = (
    "i use",
    "i'm using",
    "im using",
    "i am using",
    "i run",
    "i'm running",
    "i ran",
    "i own",
    "i have",
    "i've",
    "i prefer",
    "i built",
    "i build",
    "i'm building",
    "im building",
    "i am building",
    "i switched",
    "i moved to",
    "i work with",
    "i work on",
    "i'm working on",
    "im working on",
    "i am working on",
    "i set up",
    "i installed",
    "i configured",
    "i maintain",
    "i practice",
    "i developed",
    "i develop",
    "i value",
    "i speak",
    "i am based",
    "i study",
    "my setup",
    "my machine",
    "my gpu",
    "my laptop",
    "my project",
    "my model",
    "my workflow",
    "my stack",
    "my desktop",
    "my computer",
)

# Broad first-person markers used to detect whether a sentence is about the
# user at all. Anything with none of these is a general third-party claim.
_FIRST_PERSON_ANY: tuple[str, ...] = (
    "i ",
    "i'm",
    "im ",
    "i've",
    "i'd",
    "i'll",
    "my ",
    " me ",
    " mine",
)

# Handles "my main project", "my primary active project", etc.
# The exact-substring list misses adjectives between "my" and the noun.
_MY_ADJ_NOUN = re.compile(
    r"my\s+\w+\s+(?:\w+\s+)?"
    r"(project|workflow|stack|setup|machine|gpu|laptop|model|desktop|computer)\b"
)

# A rough "this looks like code" detector: fenced blocks, or a high density of
# characters that appear far more in source than in prose.
_CODE_FENCE = re.compile(r"```|~~~")
_CODE_CHARS = re.compile(r"[{}();=<>\[\]]")


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def classify(sentence: str, proposal: ProposedGraph) -> SalienceVerdict:
    """Decide whether a parsed observation should be kept, held, or dropped.

    Parameters
    ----------
    sentence:
        The raw natural-language sentence that was parsed.
    proposal:
        The ``ProposedGraph`` the parser produced from that sentence.

    Returns
    -------
    SalienceVerdict
        The decision plus a reason and the list of signals that fired.
    """
    text = (sentence or "").strip()
    lowered = text.casefold()

    # --- DROP: nothing was extracted, so there is nothing to keep. -----------
    if not proposal.nodes and not proposal.edges:
        return SalienceVerdict(
            SalienceDecision.DROP,
            "Parser extracted no nodes or edges.",
            ["empty_proposal"],
        )

    # --- DROP: strong transient vetoes. --------------------------------------
    drop_signals: list[str] = []

    if text.endswith("?"):
        drop_signals.append("question_mark")
    elif _opens_with_interrogative(lowered):
        drop_signals.append("interrogative_opener")

    if any(marker in lowered for marker in _HYPOTHETICAL_MARKERS):
        drop_signals.append("hypothetical")

    if any(lowered.startswith(marker) for marker in _ASSISTANT_COMMAND_MARKERS) or any(
        marker in lowered for marker in _ASSISTANT_COMMAND_MARKERS
    ):
        drop_signals.append("assistant_command")

    if _looks_like_code(text):
        drop_signals.append("code_snippet")

    if not _has_any_first_person(lowered):
        drop_signals.append("no_first_person_reference")

    if drop_signals:
        return SalienceVerdict(
            SalienceDecision.DROP,
            "Sentence looks transient (" + ", ".join(drop_signals) + ").",
            drop_signals,
        )

    # --- KEEP: first-person stative fact about a user-relevant entity. -------
    keep_signals: list[str] = []

    if _has_first_person_stative(lowered):
        keep_signals.append("first_person_stative")

    if _touches_user_relevant_type(proposal):
        keep_signals.append("user_relevant_type")

    if "first_person_stative" in keep_signals and "user_relevant_type" in keep_signals:
        return SalienceVerdict(
            SalienceDecision.KEEP,
            "Stable first-person fact about the user's setup.",
            keep_signals,
        )

    # --- HOLD: parsed into something, but not clearly a stable user fact. ----
    hold_reason = (
        "Parsed into a graph but not clearly a stable fact about you "
        "— routed for review."
    )
    return SalienceVerdict(SalienceDecision.HOLD, hold_reason, keep_signals or ["uncertain"])


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------


def _opens_with_interrogative(lowered: str) -> bool:
    """True when the sentence begins with a question word."""
    return any(lowered.startswith(opener) for opener in _INTERROGATIVE_OPENERS)


def _has_first_person_stative(lowered: str) -> bool:
    """True when the sentence states something about the user's own setup."""
    if any(cue in lowered for cue in _FIRST_PERSON_STATIVE):
        return True
    # Catch "my [adjective] project/workflow/..." that exact-substring misses.
    return bool(_MY_ADJ_NOUN.search(lowered))


def _touches_user_relevant_type(proposal: ProposedGraph) -> bool:
    """True when any proposed node is a user-setup type (tool/model/hardware/...)."""
    return any(node.type in _USER_RELEVANT_TYPES for node in proposal.nodes)


def _has_any_first_person(lowered: str) -> bool:
    """True when the sentence contains any first-person reference."""
    return any(marker in lowered for marker in _FIRST_PERSON_ANY)


def _looks_like_code(text: str) -> bool:
    """Heuristic: fenced block, or a high density of code punctuation."""
    if _CODE_FENCE.search(text):
        return True
    if not text:
        return False
    code_chars = len(_CODE_CHARS.findall(text))
    # Prose rarely exceeds a few of these; >8% density is almost always code.
    return code_chars >= 4 and (code_chars / len(text)) > 0.08

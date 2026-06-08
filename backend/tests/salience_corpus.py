"""Hand-labeled ground-truth dataset for the salience filter.

Each CorpusEntry captures one labeled example:
  sentence   raw NL input
  proposal   the ProposedGraph the LLM would have returned
  expected   intended SalienceDecision (KEEP / HOLD / DROP)
  category   which rule this exercises

Labels are based on *intended* behavior, not current classifier output.
The zero-false-KEEP invariant is the hard constraint: any sentence whose
true label is HOLD or DROP must never be auto-KEEPed.
"""
from __future__ import annotations

from dataclasses import dataclass

from lifegraph.domain import NodeType, ProposedGraph, ProposedNode
from lifegraph.salience import SalienceDecision


@dataclass(frozen=True)
class CorpusEntry:
    sentence: str
    proposal: ProposedGraph
    expected: SalienceDecision
    category: str


# ---------------------------------------------------------------------------
# Proposal mini-factories (node type is all classify() inspects)
# ---------------------------------------------------------------------------


def _node(label: str, ntype: NodeType) -> ProposedNode:
    return ProposedNode(type=ntype, label=label)


def _tool(label: str = "Ollama") -> ProposedGraph:
    return ProposedGraph(nodes=[_node(label, NodeType.TOOL)], edges=[])


def _model(label: str = "llama3") -> ProposedGraph:
    return ProposedGraph(nodes=[_node(label, NodeType.MODEL)], edges=[])


def _hardware(label: str = "RTX 3090") -> ProposedGraph:
    return ProposedGraph(nodes=[_node(label, NodeType.HARDWARE)], edges=[])


def _project(label: str = "LifeGraph") -> ProposedGraph:
    return ProposedGraph(nodes=[_node(label, NodeType.PROJECT)], edges=[])


def _technology(label: str = "Python") -> ProposedGraph:
    return ProposedGraph(nodes=[_node(label, NodeType.TECHNOLOGY)], edges=[])


def _skill(label: str = "Python") -> ProposedGraph:
    return ProposedGraph(nodes=[_node(label, NodeType.SKILL)], edges=[])


def _person(label: str = "Alice") -> ProposedGraph:
    return ProposedGraph(nodes=[_node(label, NodeType.PERSON)], edges=[])


def _habit(label: str = "step-by-step review") -> ProposedGraph:
    return ProposedGraph(nodes=[_node(label, NodeType.HABIT)], edges=[])


KEEP = SalienceDecision.KEEP
HOLD = SalienceDecision.HOLD
DROP = SalienceDecision.DROP


# ---------------------------------------------------------------------------
# Corpus (54 entries)
# ---------------------------------------------------------------------------

CORPUS: list[CorpusEntry] = [
    # ── empty (2) ──────────────────────────────────────────────────────────
    # Empty proposal always drops, regardless of sentence content.
    CorpusEntry("anything at all", ProposedGraph(), DROP, "empty"),
    CorpusEntry("I use Ollama", ProposedGraph(), DROP, "empty"),

    # ── question (9) ──────────────────────────────────────────────────────
    CorpusEntry("Should I use Ollama?", _tool(), DROP, "question"),
    CorpusEntry("How do I set up llama3?", _tool(), DROP, "question"),
    CorpusEntry("What model should I use?", _model(), DROP, "question"),
    CorpusEntry("Why is my GPU not detected?", _hardware(), DROP, "question"),
    CorpusEntry("When should I upgrade my hardware?", _hardware(), DROP, "question"),
    CorpusEntry("Which framework should I choose?", _tool(), DROP, "question"),
    CorpusEntry("Is Ollama better than LMStudio?", _tool(), DROP, "question"),
    CorpusEntry("Are there better alternatives to llama3?", _model(), DROP, "question"),
    CorpusEntry("Do I need a GPU for inference?", _hardware(), DROP, "question"),

    # ── hypothetical (6) ──────────────────────────────────────────────────
    CorpusEntry("What if I switched to a 4090?", _hardware(), DROP, "hypothetical"),
    CorpusEntry("Suppose I used llama3 instead", _model(), DROP, "hypothetical"),
    CorpusEntry("Imagine I ran mistral on my laptop", _model(), DROP, "hypothetical"),
    CorpusEntry("Hypothetically, if I had a better GPU", _hardware(), DROP, "hypothetical"),
    CorpusEntry("Let's say I moved to a cloud setup", _technology(), DROP, "hypothetical"),
    CorpusEntry("What would happen if I used a smaller model?", _model(), DROP, "hypothetical"),

    # ── command (7) ───────────────────────────────────────────────────────
    CorpusEntry("Can you write a script using Ollama", _tool(), DROP, "command"),
    CorpusEntry("Please fix the bug in my project", _project(), DROP, "command"),
    CorpusEntry("Explain how llama3 works", _model(), DROP, "command"),
    CorpusEntry("Show me how to configure Ollama", _tool(), DROP, "command"),
    CorpusEntry("Help me debug this issue", _tool(), DROP, "command"),
    CorpusEntry("Generate a config file for Ollama", _tool(), DROP, "command"),
    CorpusEntry("Refactor my code to use the new API", _project(), DROP, "command"),

    # ── code (4) ──────────────────────────────────────────────────────────
    CorpusEntry("```python\nmodel = 'llama3'\n```", _tool(), DROP, "code"),
    CorpusEntry("store.execute(sql, (a, b)); return rows[0];", _tool(), DROP, "code"),
    CorpusEntry("if (x > 0) { return x; } else { return -x; }", _tool(), DROP, "code"),
    CorpusEntry("response = client.generate({'prompt': q, 'temperature': 0})", _tool(), DROP, "code"),

    # ── third_party (8) ───────────────────────────────────────────────────
    # No first-person reference → general external claim → DROP.
    CorpusEntry("Ollama is a popular local runtime", _tool(), DROP, "third_party"),
    CorpusEntry("llama3 was released by Meta", _model(), DROP, "third_party"),
    CorpusEntry("The RTX 3090 is a powerful GPU", _hardware(), DROP, "third_party"),
    CorpusEntry("Python is widely used for ML", _technology(), DROP, "third_party"),
    CorpusEntry("VS Code has great Python extensions", _tool(), DROP, "third_party"),
    # Real-world leaks caught during dogfooding (server was on old code, now regression tests).
    CorpusEntry("Llama3 performs well on extraction tasks.", _model(), DROP, "third_party"),
    CorpusEntry("Most developers prefer REST over GraphQL.", _technology(), DROP, "third_party"),
    CorpusEntry("Claude is good at coding tasks.", _tool(), DROP, "third_party"),

    # ── user_fact (26) ────────────────────────────────────────────────────
    # First-person stative + user-relevant type → stable fact → KEEP.
    CorpusEntry("I use Ollama for local inference", _tool(), KEEP, "user_fact"),
    CorpusEntry("I'm running llama3 on my machine", _model(), KEEP, "user_fact"),
    CorpusEntry("My setup uses an RTX 3090", _hardware(), KEEP, "user_fact"),
    CorpusEntry("I switched to Ollama last month", _tool(), KEEP, "user_fact"),
    CorpusEntry("My project is LifeGraph", _project(), KEEP, "user_fact"),
    CorpusEntry("I prefer llama3 for extraction tasks", _model(), KEEP, "user_fact"),
    CorpusEntry("I work on LifeGraph as my main project", _project(), KEEP, "user_fact"),
    CorpusEntry("My workflow includes Python and Ollama", _technology(), KEEP, "user_fact"),
    CorpusEntry("I installed Ollama last week", _tool(), KEEP, "user_fact"),
    CorpusEntry("I'm building a knowledge graph app", _project(), KEEP, "user_fact"),
    CorpusEntry("I run Ollama locally on my machine", _tool(), KEEP, "user_fact"),
    CorpusEntry("I've been using Python for years", _skill(), KEEP, "user_fact"),
    CorpusEntry("My GPU is an RTX 3090", _hardware(), KEEP, "user_fact"),
    CorpusEntry("I configured my Ollama to use llama3", _tool(), KEEP, "user_fact"),
    # Adjective(s) between "my" and the noun — caught by the _MY_ADJ_NOUN regex.
    CorpusEntry("My main project right now is LifeGraph", _project(), KEEP, "user_fact"),
    CorpusEntry("My current model is llama3", _model(), KEEP, "user_fact"),
    CorpusEntry("My primary active project is LifeGraph", _project(), KEEP, "user_fact"),
    CorpusEntry("My desktop PC runs Windows", _hardware(), KEEP, "user_fact"),
    # New stative verbs added from dogfooding (i am building, i maintain, i practice, etc).
    CorpusEntry("I am building LifeGraph as a knowledge graph tool", _project(), KEEP, "user_fact"),
    CorpusEntry("I maintain the Al-Salam Woodwork website", _project(), KEEP, "user_fact"),
    CorpusEntry("I practice cybersecurity on TryHackMe", _tool(), KEEP, "user_fact"),
    CorpusEntry("I developed an Arabic disinformation detector", _project(), KEEP, "user_fact"),
    CorpusEntry("I value step-by-step approval in my workflow", _habit(), KEEP, "user_fact"),
    CorpusEntry("I speak Arabic and English", _skill(), KEEP, "user_fact"),

    # ── ambiguous_first_person (7) ────────────────────────────────────────
    # Has a first-person reference and parsed into something, but the verb is
    # not a stative marker → not safe to auto-KEEP → HOLD for review.
    CorpusEntry("I tried Ollama briefly", _tool(), HOLD, "ambiguous_first_person"),
    # Regression: "i've" was too broad as a standalone stative cue — this
    # conversational aside was falsely KEEPed during the first real-backlog
    # smoke pass (2026-06-06). Must stay HOLD after the fix.
    CorpusEntry(
        "I've already done one round of product critique and landed on the following:",
        _project(),
        HOLD,
        "ambiguous_first_person",
    ),
    CorpusEntry("I met Alice yesterday", _person(), HOLD, "ambiguous_first_person"),
    CorpusEntry("I asked about llama3 earlier", _model(), HOLD, "ambiguous_first_person"),
    CorpusEntry("I recently experimented with Ollama", _tool(), HOLD, "ambiguous_first_person"),
    CorpusEntry("I mentioned Python to my colleague", _technology(), HOLD, "ambiguous_first_person"),
    CorpusEntry("I read about llama3 yesterday", _model(), HOLD, "ambiguous_first_person"),
    CorpusEntry("I thought about switching models", _model(), HOLD, "ambiguous_first_person"),
]

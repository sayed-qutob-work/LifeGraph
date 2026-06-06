"""Tests for the dry-run log ingestor (``lifegraph.ingest``).

These exercise the log-walking, candidate extraction, and report aggregation
without any network call or the real ``~/.claude`` directory: session logs are
synthesized as JSONL fixtures, and the parser is a fake whose verdict is driven
by keywords in the sentence. The contract under test is that the ingestor reuses
``salience.classify`` and never writes to a database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifegraph.domain import NodeType, ProposedGraph, ProposedNode
from lifegraph.ingest import (
    Candidate,
    IngestReport,
    classify_candidate,
    format_report,
    iter_file_candidates,
    iter_session_files,
    run_ingest,
    split_sentences,
)
from lifegraph.ollama_client import OllamaUnavailableError
from lifegraph.parser import InputValidationError, UnparseableResponse


# ---------------------------------------------------------------------------
# Fixtures: synthetic JSONL transcripts and a fake parser
# ---------------------------------------------------------------------------


def _user_record(content):
    return {"type": "user", "message": {"role": "user", "content": content}}


def _assistant_record(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": text}}


def _write_jsonl(path: Path, records) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


class FakeParser:
    """Stand-in for InputParser: keyword-driven, no LLM.

    - "boom"   -> raises OllamaUnavailableError (environmental failure)
    - "badjson"-> raises UnparseableResponse (per-sentence parse failure)
    - "i use"  -> a Tool node (user-relevant; salience KEEPs the stative form)
    - otherwise-> a Person node — non-empty but not user-relevant, so salience
                  judges on the sentence text (question / first-person / etc.)
                  rather than short-circuiting on an empty extraction.
    """

    def __init__(self):
        self.calls = []

    def parse(self, sentence: str) -> ProposedGraph:
        self.calls.append(sentence)
        low = sentence.casefold()
        if "boom" in low:
            raise OllamaUnavailableError("ollama down")
        if "badjson" in low:
            raise UnparseableResponse("not a dict")
        if "i use" in low:
            return ProposedGraph(
                nodes=[ProposedNode(type=NodeType.TOOL, label="Ollama")], edges=[]
            )
        return ProposedGraph(
            nodes=[ProposedNode(type=NodeType.PERSON, label="someone")], edges=[]
        )


# ---------------------------------------------------------------------------
# Candidate extraction
# ---------------------------------------------------------------------------


def test_iter_session_files_finds_nested_jsonl(tmp_path: Path):
    (tmp_path / "proj-a").mkdir()
    (tmp_path / "proj-b").mkdir()
    a = tmp_path / "proj-a" / "s1.jsonl"
    b = tmp_path / "proj-b" / "s2.jsonl"
    a.write_text("{}\n", encoding="utf-8")
    b.write_text("{}\n", encoding="utf-8")
    (tmp_path / "proj-a" / "notes.txt").write_text("ignore me", encoding="utf-8")

    found = list(iter_session_files(tmp_path))
    assert found == [a, b]  # sorted, only .jsonl


def test_iter_session_files_missing_root_is_empty(tmp_path: Path):
    assert list(iter_session_files(tmp_path / "nope")) == []


def test_extracts_only_user_prose(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(
        path,
        [
            _user_record("I use Ollama on my 3090."),
            _assistant_record("Sure, here is how."),
            # list content = tool result, not typed prose -> skipped
            _user_record([{"type": "tool_result", "content": "files..."}]),
            # command machinery -> skipped
            _user_record("<command-name>/clear</command-name>"),
            _user_record("<local-command-caveat>Caveat: ...</local-command-caveat>"),
            {"type": "system", "message": {"role": "system", "content": "hi"}},
        ],
    )
    sentences = [c.sentence for c in iter_file_candidates(path)]
    assert sentences == ["I use Ollama on my 3090."]


def test_malformed_lines_are_skipped(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        "not json at all\n"
        + json.dumps(_user_record("I use Mistral.")) + "\n"
        + "{ broken\n",
        encoding="utf-8",
    )
    sentences = [c.sentence for c in iter_file_candidates(path)]
    assert sentences == ["I use Mistral."]


def test_split_sentences_segments_and_trims():
    text = "I use Ollama.  My GPU is a 3090.\nDo you know why?"
    assert list(split_sentences(text)) == [
        "I use Ollama.",
        "My GPU is a 3090.",
        "Do you know why?",
    ]
    assert list(split_sentences("   \n  ")) == []


# ---------------------------------------------------------------------------
# Classification mirrors add_observation
# ---------------------------------------------------------------------------


def test_classify_candidate_keep_hold_drop():
    parser = FakeParser()
    keep = classify_candidate(Candidate("I use Ollama daily.", Path("s")), parser)
    hold = classify_candidate(Candidate("I tried something once.", Path("s")), parser)
    drop = classify_candidate(Candidate("Ollama is popular.", Path("s")), parser)

    assert keep[0] == "kept"
    assert hold[0] == "held"
    assert drop[0] == "dropped"  # no first-person reference


def test_classify_candidate_parse_error_is_dropped():
    parser = FakeParser()
    bucket, reason, signals = classify_candidate(
        Candidate("badjson here", Path("s")), parser
    )
    assert bucket == "dropped"
    assert "parse_error" in signals


def test_classify_candidate_input_error_is_dropped():
    class TooLongParser:
        def parse(self, sentence):
            raise InputValidationError("too long")

    bucket, _, signals = classify_candidate(
        Candidate("whatever", Path("s")), TooLongParser()
    )
    assert bucket == "dropped"
    assert "input_error" in signals


def test_classify_candidate_propagates_ollama_failure():
    parser = FakeParser()
    with pytest.raises(OllamaUnavailableError):
        classify_candidate(Candidate("boom goes ollama", Path("s")), parser)


# ---------------------------------------------------------------------------
# End-to-end dry run
# ---------------------------------------------------------------------------


def _seed_backlog(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    (root / "lifegraph").mkdir(parents=True)
    (root / "other").mkdir(parents=True)
    _write_jsonl(
        root / "lifegraph" / "s1.jsonl",
        [
            _user_record("I use Ollama on my 3090."),  # keep
            _user_record("I tried something once."),  # hold
            _user_record("What is the capital of France?"),  # drop (question)
            _assistant_record("answer"),
        ],
    )
    _write_jsonl(
        root / "other" / "s2.jsonl",
        [_user_record("Ollama is a popular runtime.")],  # drop (no first person)
    )
    return root


def test_run_ingest_aggregates_without_persisting(tmp_path: Path):
    root = _seed_backlog(tmp_path)
    report = run_ingest(FakeParser(), root=root)

    assert report.files_scanned == 2
    assert report.total_candidates == 4
    assert report.decisions["kept"] == 1
    assert report.decisions["held"] == 1
    assert report.decisions["dropped"] == 2
    # drop reasons came from real salience signals
    assert sum(report.drop_reasons.values()) >= 2
    assert "no_first_person_reference" in report.drop_reasons


def test_run_ingest_project_filter_scopes_sessions(tmp_path: Path):
    root = _seed_backlog(tmp_path)
    report = run_ingest(FakeParser(), root=root, projects=["lifegraph"])

    assert report.files_scanned == 1
    assert report.total_candidates == 3  # only s1's three user sentences


def test_run_ingest_limit_caps_candidates(tmp_path: Path):
    root = _seed_backlog(tmp_path)
    report = run_ingest(FakeParser(), root=root, limit=2)

    assert report.total_candidates == 2


def test_run_ingest_sample_size_bounds_samples(tmp_path: Path):
    root = _seed_backlog(tmp_path)
    report = run_ingest(FakeParser(), root=root, sample_size=1)

    for bucket in ("kept", "held", "dropped"):
        assert len(report.samples[bucket]) <= 1


def test_format_report_is_plain_text_and_mentions_dry_run():
    report = IngestReport()
    report.files_scanned = 1
    report.total_candidates = 2
    report.decisions.update({"kept": 1, "dropped": 1})
    report.drop_reasons.update(["question_mark"])
    report.samples["kept"].append(("I use Ollama.", "stable fact", "s1"))

    text = format_report(report)
    assert "DRY RUN" in text
    assert "kept" in text and "dropped" in text
    assert "question_mark" in text
    assert "I use Ollama." in text

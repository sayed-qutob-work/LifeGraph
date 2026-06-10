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
    _is_prose_sentence,
    _iter_export_from_conversations,
    classify_candidate,
    format_report,
    iter_export_candidates,
    iter_file_candidates,
    iter_session_files,
    report_from_file,
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


def test_run_ingest_writes_output_file_immediately(tmp_path: Path):
    root = _seed_backlog(tmp_path)
    out = tmp_path / "results.jsonl"
    run_ingest(FakeParser(), root=root, output_path=out)

    assert out.exists()
    lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 4  # one line per candidate
    # every line is valid JSON with the expected fields
    for line in lines:
        rec = json.loads(line)
        assert rec["bucket"] in ("kept", "held", "dropped")
        assert "sentence" in rec and "reason" in rec and "source" in rec


def test_report_from_file_rebuilds_correctly(tmp_path: Path):
    root = _seed_backlog(tmp_path)
    out = tmp_path / "results.jsonl"
    original = run_ingest(FakeParser(), root=root, output_path=out)
    rebuilt = report_from_file(out)

    assert rebuilt.total_candidates == original.total_candidates
    assert rebuilt.decisions == original.decisions
    assert rebuilt.drop_reasons == original.drop_reasons


def test_report_from_file_handles_partial_run(tmp_path: Path):
    # Simulate a run killed after 2 of 4 candidates.
    out = tmp_path / "partial.jsonl"
    out.write_text(
        json.dumps({"sentence": "I use Ollama.", "bucket": "kept",
                    "reason": "stable fact", "signals": ["first_person_stative"], "source": "s1"}) + "\n" +
        json.dumps({"sentence": "I tried it once.", "bucket": "held",
                    "reason": "ambiguous", "signals": ["uncertain"], "source": "s1"}) + "\n",
        encoding="utf-8",
    )
    report = report_from_file(out)
    assert report.total_candidates == 2
    assert report.decisions["kept"] == 1
    assert report.decisions["held"] == 1


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


# ---------------------------------------------------------------------------
# Prose filter (_is_prose_sentence)
# ---------------------------------------------------------------------------


def test_is_prose_sentence_accepts_normal_prose():
    assert _is_prose_sentence("I use Ollama for local inference.")
    assert _is_prose_sentence("My GPU is an RTX 3090.")
    assert _is_prose_sentence("I've been building LifeGraph for three months.")
    assert _is_prose_sentence("I switched from VS Code to Neovim last week.")


def test_is_prose_sentence_rejects_too_short():
    assert not _is_prose_sentence("")
    assert not _is_prose_sentence("  ")
    assert not _is_prose_sentence("1.")
    assert not _is_prose_sentence("ok")


def test_is_prose_sentence_rejects_db_dump_rows():
    # UUID-prefixed lines come from pasted SELECT * output.
    assert not _is_prose_sentence(
        "8cdaaf53-8010-4c79-bced-980546ed4893\tI use Ollama\t2026-06-05T13:31:13Z"
    )
    assert not _is_prose_sentence(
        "0c2a7e72-301f-4fed-9790-e2c088c8ddf3    My setup runs llama3 on a GPU"
    )


def test_is_prose_sentence_rejects_tab_structured_data():
    assert not _is_prose_sentence("col1\tcol2\tcol3")
    assert not _is_prose_sentence("node_id\tlabel\ttype\tcreated_at")


def test_is_prose_sentence_rejects_markdown_bullets_and_headers():
    assert not _is_prose_sentence("- I use Ollama on my machine.")
    assert not _is_prose_sentence("* My GPU is a 3090.")
    assert not _is_prose_sentence("## Setup")
    assert not _is_prose_sentence("# Project overview")


def test_is_prose_sentence_rejects_instruction_prefixes():
    assert not _is_prose_sentence("Call add_observation with the sentence: I use Ollama")
    assert not _is_prose_sentence("Capture: I run Ollama on my Windows machine")
    assert not _is_prose_sentence("Sentence: My main CS2 goal is learning Mirage smokes.")
    assert not _is_prose_sentence("Use the lifegraph add_observation tool to capture: ...")
    assert not _is_prose_sentence("You paste I use an RTX 3090 → graph captures RTX 3090")


def test_is_prose_sentence_rejects_garbled_table_rows():
    assert not _is_prose_sentence(
        'Questions are filtered as non-stable.2"I use VS Code."KEPTStable first-person fact.'
    )
    assert not _is_prose_sentence(
        'Created: Tool node (VS Code).3"I run Ollama locally."KEPTStable fact.'
    )


# ---------------------------------------------------------------------------
# iter_file_candidates respects the prose filter
# ---------------------------------------------------------------------------


def test_iter_file_candidates_rejects_non_prose(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(
        path,
        [
            _user_record("I use Ollama for local inference."),              # kept
            _user_record("8cdaaf53-8010-4c79-bced    I use Ollama\t2026"), # DB dump
            _user_record("- My GPU is a 3090."),                           # markdown bullet
            _user_record("Call add_observation with the sentence: I use VS Code"), # instruction
            _user_record("Sentence: My goal is learning Mirage smokes."),  # example prefix
        ],
    )
    sentences = [c.sentence for c in iter_file_candidates(path)]
    assert sentences == ["I use Ollama for local inference."]


# ---------------------------------------------------------------------------
# Deduplication in run_ingest
# ---------------------------------------------------------------------------


def test_run_ingest_deduplicates_across_files(tmp_path: Path):
    root = tmp_path / "projects"
    (root / "proj-a").mkdir(parents=True)
    (root / "proj-b").mkdir(parents=True)
    # Same sentence in two different session files.
    _write_jsonl(root / "proj-a" / "s1.jsonl", [_user_record("I use Ollama daily.")])
    _write_jsonl(root / "proj-b" / "s2.jsonl", [_user_record("I use Ollama daily.")])
    # Different sentence — should still be counted.
    _write_jsonl(root / "proj-b" / "s3.jsonl", [_user_record("My GPU is an RTX 3090.")])

    report = run_ingest(FakeParser(), root=root)

    assert report.total_candidates == 2        # two unique sentences
    assert report.duplicates_skipped == 1      # one duplicate suppressed


def test_run_ingest_dedup_is_case_insensitive(tmp_path: Path):
    root = tmp_path / "projects"
    (root / "proj").mkdir(parents=True)
    _write_jsonl(
        root / "proj" / "s.jsonl",
        [
            _user_record("I use Ollama daily."),
            _user_record("I Use Ollama Daily."),   # same after casefold
        ],
    )
    report = run_ingest(FakeParser(), root=root)
    assert report.total_candidates == 1
    assert report.duplicates_skipped == 1


# ---------------------------------------------------------------------------
# --exclude filter in run_ingest
# ---------------------------------------------------------------------------


def test_run_ingest_exclude_skips_matching_sessions(tmp_path: Path):
    root = _seed_backlog(tmp_path)
    # Exclude the "lifegraph" session dir; only "other" remains.
    report = run_ingest(FakeParser(), root=root, exclude=["lifegraph"])

    assert report.files_scanned == 1
    assert report.total_candidates == 1  # only the one sentence from "other"


def test_run_ingest_exclude_takes_priority_over_project(tmp_path: Path):
    root = _seed_backlog(tmp_path)
    # --project lifegraph AND --exclude lifegraph → exclude wins, nothing scanned.
    report = run_ingest(FakeParser(), root=root, projects=["lifegraph"], exclude=["lifegraph"])

    assert report.files_scanned == 0
    assert report.total_candidates == 0


def test_format_report_shows_deduped_count():
    report = IngestReport()
    report.files_scanned = 2
    report.total_candidates = 3
    report.duplicates_skipped = 5
    report.decisions.update({"kept": 3})
    text = format_report(report)
    assert "deduped" in text
    assert "5" in text


# ---------------------------------------------------------------------------
# claude.ai export reader
# ---------------------------------------------------------------------------


def _make_human_msg(text: str, uuid: str = "m1") -> dict:
    return {
        "uuid": uuid, "text": text, "content": [],
        "sender": "human", "created_at": "", "updated_at": "",
        "attachments": [], "files": [], "parent_message_uuid": None,
    }


def _make_assistant_msg(text: str) -> dict:
    return {
        "uuid": "a1", "text": text, "content": [],
        "sender": "assistant", "created_at": "", "updated_at": "",
        "attachments": [], "files": [], "parent_message_uuid": None,
    }


def _make_conv(uuid: str, messages: list) -> dict:
    return {
        "uuid": uuid, "name": "test conv", "summary": "",
        "created_at": "", "updated_at": "", "account": {},
        "chat_messages": messages,
    }


def _write_export(path: Path, conversations: list) -> None:
    path.write_text(json.dumps(conversations), encoding="utf-8")


def test_export_reader_yields_human_prose():
    convs = [
        _make_conv("conv-1", [
            _make_human_msg("I use Ollama for local inference."),
            _make_assistant_msg("Great, I can help with that."),
            _make_human_msg("My GPU is an RTX 3090."),
        ]),
    ]
    candidates = list(_iter_export_from_conversations(convs))
    sentences = [c.sentence for c in candidates]
    assert "I use Ollama for local inference." in sentences
    assert "My GPU is an RTX 3090." in sentences
    # assistant message must be excluded
    assert not any("Great" in s for s in sentences)


def test_export_reader_skips_assistant_messages():
    convs = [
        _make_conv("conv-1", [
            _make_assistant_msg("Here is some information."),
            _make_assistant_msg("Let me explain further."),
        ]),
    ]
    assert list(_iter_export_from_conversations(convs)) == []


def test_export_reader_applies_prose_filter():
    convs = [
        _make_conv("conv-1", [
            _make_human_msg("I use Ollama for local inference."),        # passes
            _make_human_msg("- some markdown bullet point"),              # rejected
            _make_human_msg("Call add_observation with the sentence: x"), # rejected
        ]),
    ]
    sentences = [c.sentence for c in _iter_export_from_conversations(convs)]
    assert sentences == ["I use Ollama for local inference."]


def test_export_reader_splits_multi_sentence_messages():
    convs = [
        _make_conv("conv-1", [
            _make_human_msg("I use Ollama daily. My GPU is an RTX 3090."),
        ]),
    ]
    sentences = [c.sentence for c in _iter_export_from_conversations(convs)]
    assert len(sentences) == 2
    assert "I use Ollama daily." in sentences
    assert "My GPU is an RTX 3090." in sentences


def test_export_reader_source_is_conversation_uuid():
    convs = [_make_conv("abc-123", [_make_human_msg("I use Ollama.")])]
    candidates = list(_iter_export_from_conversations(convs))
    assert candidates[0].source == Path("abc-123")


def test_export_reader_handles_empty_and_malformed():
    assert list(_iter_export_from_conversations([])) == []
    assert list(_iter_export_from_conversations([None, "bad", 42])) == []


def test_iter_export_candidates_reads_file(tmp_path: Path):
    export = tmp_path / "conversations.json"
    convs = [_make_conv("c1", [_make_human_msg("I use Ollama for local inference.")])]
    _write_export(export, convs)
    sentences = [c.sentence for c in iter_export_candidates(export)]
    assert sentences == ["I use Ollama for local inference."]


def test_iter_export_candidates_bad_path_is_empty(tmp_path: Path):
    assert list(iter_export_candidates(tmp_path / "missing.json")) == []


def test_iter_export_candidates_bad_json_is_empty(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")
    assert list(iter_export_candidates(bad)) == []


# ---------------------------------------------------------------------------
# run_ingest with export_path
# ---------------------------------------------------------------------------


def test_run_ingest_export_classifies_candidates(tmp_path: Path):
    export = tmp_path / "conversations.json"
    convs = [
        _make_conv("c1", [
            _make_human_msg("I use Ollama for local inference."),  # keep
            _make_human_msg("What time is it?"),                   # drop (question)
        ]),
    ]
    _write_export(export, convs)
    # Empty Claude Code root so only export data flows through.
    empty_root = tmp_path / "empty_projects"
    empty_root.mkdir()

    report = run_ingest(FakeParser(), root=empty_root, export_path=export)

    assert report.conversations_scanned == 1
    assert report.total_candidates == 2
    assert report.decisions["kept"] == 1
    assert report.decisions["dropped"] == 1


def test_run_ingest_export_dedup_spans_both_sources(tmp_path: Path):
    # Same sentence in a CC session and the export → counted only once.
    root = tmp_path / "projects"
    (root / "proj").mkdir(parents=True)
    _write_jsonl(root / "proj" / "s.jsonl", [_user_record("I use Ollama daily.")])

    export = tmp_path / "conversations.json"
    convs = [_make_conv("c1", [_make_human_msg("I use Ollama daily.")])]
    _write_export(export, convs)

    report = run_ingest(FakeParser(), root=root, export_path=export)

    assert report.total_candidates == 1
    assert report.duplicates_skipped == 1


def test_run_ingest_conversations_scanned_zero_without_export(tmp_path: Path):
    root = _seed_backlog(tmp_path)
    report = run_ingest(FakeParser(), root=root)
    assert report.conversations_scanned == 0


def test_format_report_shows_conversations_when_nonzero():
    report = IngestReport()
    report.conversations_scanned = 192
    report.total_candidates = 50
    report.decisions.update({"kept": 50})
    text = format_report(report)
    assert "conversations" in text
    assert "192" in text


def test_format_report_hides_conversations_when_zero():
    report = IngestReport()
    report.files_scanned = 5
    report.total_candidates = 10
    report.decisions.update({"kept": 10})
    text = format_report(report)
    assert "conversations" not in text

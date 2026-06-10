"""Dry-run Claude Code log ingestor — report-only, never writes to the DB.

This walks the Claude Code session logs already sitting on disk
(``~/.claude/projects/**/*.jsonl``), pulls the user-typed sentences out of each
session, and pushes every one through the *exact* same pipeline the live
passive-capture path uses — ``InputParser.parse`` then ``salience.classify`` —
then prints a KEEP / HOLD / DROP report. **Nothing is persisted.**

Why dry-run first (see ``task.md`` §7):

* It tests the salience exit criterion ("zero false auto-KEEPs on real traffic")
  against hundreds of real sentences in one pass, instead of slow hand-fed
  dogfooding through ``add_observation``.
* It settles the ingestor-vs-review-UI ordering with numbers: a trustworthy
  auto-KEEP set with a small HOLD pile means persistence can come first; a huge
  HOLD pile means the review view comes first.
* It sizes the backlog against the ~300-fact moat threshold before any
  persistence work is invested.
* The log-walking + extraction here is ~80% of the real ingestor. Persistence is
  a deliberately separate, *later* flip — this module does not write, by design.

Reuse, do not fork: the parser and salience classifier are imported and called
directly, so the dry-run verdicts match exactly what live ``add_observation``
would decide.

Requirements: 13.1 (passive capture), 2.7 (salience gate before persistence).

Privacy-scoping hook (``task.md`` §8): ``--project`` filters which session dirs
are eligible. Moot for a local dry-run, but it is the seam where per-project
opt-in/opt-out will live once persistence is flipped on — keep it.

Run (requires Ollama up, since ``parse`` calls the LLM)::

    cd backend && python -m lifegraph.ingest                 # whole backlog
    cd backend && python -m lifegraph.ingest --limit 200     # quick smoke
    cd backend && python -m lifegraph.ingest --project LifeGraph --sample 8
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Sequence, Tuple

from lifegraph.factory import make_parser
from lifegraph.ollama_client import OllamaTimeoutError, OllamaUnavailableError
from lifegraph.parser import (
    InputParser,
    InputValidationError,
    InvalidTypeError,
    UnparseableResponse,
)
from lifegraph.salience import SalienceDecision, classify

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Where Claude Code stores per-project session transcripts.
DEFAULT_PROJECTS_ROOT = Path.home() / ".claude" / "projects"

# The three live-capture verdict buckets (mirrors add_observation's statuses).
_BUCKETS: tuple[str, ...] = ("kept", "held", "dropped")

_DECISION_TO_BUCKET = {
    SalienceDecision.KEEP: "kept",
    SalienceDecision.HOLD: "held",
    SalienceDecision.DROP: "dropped",
}

# User-content strings that begin with one of these are Claude Code machinery
# (slash-command invocations, local-command wrappers), not user prose. Skipped.
_META_PREFIXES: tuple[str, ...] = (
    "<local-command-caveat>",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<system-reminder>",
)

# Break a user message into candidate sentences: on sentence-ending punctuation
# followed by whitespace, or on line breaks. Deliberately simple — a dry-run
# report tolerates the occasional bad split (e.g. "Node.js"); we sample and
# eyeball rather than depend on perfect segmentation.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# --- Prose filter: structural patterns that rule out non-prose before parsing --

# DB query output rows: lines starting with a UUID (e.g. pasted `SELECT *` results).
_UUID_PREFIX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-", re.IGNORECASE)

# Markdown list items and headings (these are doc lines, not user assertions).
_MARKDOWN_BULLET = re.compile(r"^[-*]\s+")
_MARKDOWN_HEADER = re.compile(r"^#+\s")

# Prefixes that signal the user is directing the assistant or labelling an example,
# not asserting a fact about themselves.
_INSTRUCTION_PREFIXES: tuple[str, ...] = (
    "call add_observation",
    "capture:",
    "sentence:",
    "use the lifegraph",
    "you paste",
)

# Garbled concatenated table rows (e.g. "...stable.2"I use VS Code..."KEPT...").
_GARBLED_TABLE = re.compile(r'\d["\']|\bKEPT\b|\bHELD\b|\bDROPPED\b')

DEFAULT_SAMPLE_SIZE = 5


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One user-typed sentence pulled from a session log, plus its source."""

    sentence: str
    source: Path


@dataclass
class IngestReport:
    """Aggregate verdicts from a dry-run pass — counts and samples, no rows."""

    files_scanned: int = 0
    total_candidates: int = 0
    duplicates_skipped: int = 0
    # bucket ("kept"|"held"|"dropped") -> count
    decisions: Counter = field(default_factory=Counter)
    # salience/parse signal -> count, among DROPPED candidates only
    drop_reasons: Counter = field(default_factory=Counter)
    # bucket -> list of (sentence, reason, source_stem) for eyeballing
    samples: dict[str, List[Tuple[str, str, str]]] = field(
        default_factory=lambda: {b: [] for b in _BUCKETS}
    )


# ---------------------------------------------------------------------------
# Log walking + candidate extraction
# ---------------------------------------------------------------------------


def iter_session_files(root: Path) -> Iterator[Path]:
    """Yield every ``*.jsonl`` session transcript under ``root`` (recursively)."""
    if not root.exists():
        return
    yield from sorted(root.rglob("*.jsonl"))


def _matches_project(
    path: Path,
    projects: Sequence[str],
    exclude: Sequence[str] = (),
) -> bool:
    """Privacy-scoping predicate: keep ``path`` only if it passes include/exclude filters.

    ``projects`` is a list of case-insensitive include substrings; empty = include all.
    ``exclude`` is a list of case-insensitive exclude substrings; matched paths are
    always dropped, even if they match ``projects``.
    """
    hay = str(path).casefold()
    if exclude and any(e.casefold() in hay for e in exclude):
        return False
    if not projects:
        return True
    return any(p.casefold() in hay for p in projects)


def _is_prose_sentence(sentence: str) -> bool:
    """Return True only when a sentence is plausibly user-typed natural-language prose.

    Rejects structural patterns that consistently produce false positives before
    any LLM call is made:
    - DB dump rows (UUID-prefixed lines from pasted query output)
    - Tab-delimited structured data
    - Markdown list items and headings
    - Tool-call instruction prefixes (user directing the assistant)
    - Garbled concatenated table rows
    """
    stripped = sentence.strip()
    if len(stripped) < 6:
        return False
    if _UUID_PREFIX.match(stripped):
        return False
    if "\t" in stripped:
        return False
    if _MARKDOWN_BULLET.match(stripped) or _MARKDOWN_HEADER.match(stripped):
        return False
    if _GARBLED_TABLE.search(stripped):
        return False
    lowered = stripped.casefold()
    if any(lowered.startswith(p) for p in _INSTRUCTION_PREFIXES):
        return False
    return True


def iter_file_candidates(path: Path) -> Iterator[Candidate]:
    """Yield candidate user sentences from one session transcript.

    A transcript is line-delimited JSON. We take only records that are
    user-typed prose: ``type == "user"`` with ``message.role == "user"`` and a
    **string** content (list content is tool-result feedback, not typed text),
    skipping Claude Code command/caveat machinery. Each such message is split
    into candidate sentences.

    Malformed lines are skipped rather than aborting the file.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                for text in _user_texts_from_record(record):
                    for sentence in split_sentences(text):
                        if _is_prose_sentence(sentence):
                            yield Candidate(sentence=sentence, source=path)
    except OSError:
        return


def _user_texts_from_record(record: object) -> Iterator[str]:
    """Yield user-typed prose strings from a single JSONL record, or nothing."""
    if not isinstance(record, dict):
        return
    if record.get("type") != "user":
        return
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        return
    content = message.get("content")
    # Lists are tool-result blocks fed back into the conversation, not typed text.
    if not isinstance(content, str):
        return
    text = content.strip()
    if not text or text.startswith(_META_PREFIXES):
        return
    yield text


def split_sentences(text: str) -> Iterator[str]:
    """Split a user message into non-blank candidate sentences.

    Length is intentionally *not* clamped here: an over-long run-on is fed to
    the parser as-is so it surfaces as an ``input_error`` drop in the report,
    exactly as the live path would treat it.
    """
    for raw in _SENTENCE_SPLIT.split(text):
        sentence = raw.strip()
        if sentence:
            yield sentence


# ---------------------------------------------------------------------------
# Classification (mirrors add_observation's parse + salience, minus persistence)
# ---------------------------------------------------------------------------


def classify_candidate(
    candidate: Candidate, parser: InputParser
) -> Tuple[str, str, List[str]]:
    """Run one candidate through parse + salience; return (bucket, reason, signals).

    Per-sentence failures are bucketed as ``dropped`` with a synthetic signal,
    matching how ``add_observation`` reports them. Environmental Ollama failures
    (service down / timeout) are *not* per-sentence verdicts, so they propagate
    to the caller, which aborts the whole run with a clear message.
    """
    try:
        proposed = parser.parse(candidate.sentence)
    except (InvalidTypeError, UnparseableResponse) as exc:
        return "dropped", f"LLM produced unparseable output: {exc}", ["parse_error"]
    except InputValidationError as exc:
        return "dropped", f"Invalid input: {exc}", ["input_error"]
    # OllamaUnavailableError / OllamaTimeoutError intentionally propagate.

    verdict = classify(candidate.sentence, proposed)
    return _DECISION_TO_BUCKET[verdict.decision], verdict.reason, list(verdict.signals)


# ---------------------------------------------------------------------------
# Orchestration — read-only, builds an IngestReport
# ---------------------------------------------------------------------------


def run_ingest(
    parser: InputParser,
    root: Path = DEFAULT_PROJECTS_ROOT,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    limit: int | None = None,
    projects: Sequence[str] = (),
    exclude: Sequence[str] = (),
    output_path: Path | None = None,
) -> IngestReport:
    """Walk the backlog and classify every candidate. Never writes to the DB.

    Each verdict is appended to ``output_path`` (one JSON line, flushed
    immediately) so progress survives a kill or power-off. Pass
    ``output_path=None`` to skip file output.

    Duplicate sentences (same normalised text seen in any prior file) are
    counted in ``report.duplicates_skipped`` and not sent to the LLM.

    Args:
        parser: A ready ``InputParser`` (from ``factory.make_parser``).
        root: Directory of Claude Code session logs.
        sample_size: How many example sentences to retain per verdict bucket.
        limit: Stop after this many candidates (a quick smoke cap); None = all.
        projects: Case-insensitive path substrings to scope which sessions are
            eligible (the privacy-scoping hook). Empty = every session.
        exclude: Case-insensitive path substrings; matching sessions are always
            skipped even if they also match ``projects``.
        output_path: JSONL file to append each verdict to immediately.

    Raises:
        OllamaUnavailableError / OllamaTimeoutError: if the LLM is unreachable —
            the run cannot proceed, so this surfaces rather than counting every
            sentence as an error.
    """
    report = IngestReport()
    files = [
        p for p in iter_session_files(root)
        if _matches_project(p, projects, exclude)
    ]
    report.files_scanned = len(files)
    sys.stderr.write(f"[ingest] {len(files)} session files found\n")
    if output_path:
        sys.stderr.write(f"[ingest] writing results to {output_path}\n")
    sys.stderr.flush()

    start = time.monotonic()
    seen_normalized: set[str] = set()

    out = open(output_path, "a", encoding="utf-8") if output_path else None
    try:
        for file_idx, path in enumerate(files, 1):
            for candidate in iter_file_candidates(path):
                norm = candidate.sentence.strip().casefold()
                if norm in seen_normalized:
                    report.duplicates_skipped += 1
                    continue
                seen_normalized.add(norm)
                bucket, reason, signals = classify_candidate(candidate, parser)
                report.total_candidates += 1
                report.decisions[bucket] += 1
                if bucket == "dropped":
                    report.drop_reasons.update(signals)
                bucket_samples = report.samples[bucket]
                if len(bucket_samples) < sample_size:
                    bucket_samples.append((candidate.sentence, reason, path.stem))
                if out is not None:
                    out.write(json.dumps({
                        "sentence": candidate.sentence,
                        "bucket": bucket,
                        "reason": reason,
                        "signals": signals,
                        "source": path.stem,
                    }) + "\n")
                    out.flush()
                if report.total_candidates % 10 == 0:
                    elapsed = time.monotonic() - start
                    rate = (report.total_candidates / elapsed * 60) if elapsed > 0 else 0
                    k = report.decisions.get("kept", 0)
                    h = report.decisions.get("held", 0)
                    d = report.decisions.get("dropped", 0)
                    preview = candidate.sentence[:55].replace("\n", " ")
                    sys.stderr.write(
                        f"[{report.total_candidates}] file={file_idx}/{len(files)}"
                        f"  kept={k} held={h} dropped={d}"
                        f"  {rate:.1f}/min"
                        f"  +{elapsed:.0f}s"
                        f"  | {preview}\n"
                    )
                    sys.stderr.flush()
                if limit is not None and report.total_candidates >= limit:
                    return report
    finally:
        if out is not None:
            out.close()
    return report


def report_from_file(results_path: Path, sample_size: int = DEFAULT_SAMPLE_SIZE) -> IngestReport:
    """Rebuild an IngestReport from a saved results JSONL file.

    Lets you generate (or regenerate) the summary report from a partial or
    complete run without re-running the LLM.
    """
    report = IngestReport()
    with results_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            bucket = rec.get("bucket", "dropped")
            reason = rec.get("reason", "")
            signals = rec.get("signals", [])
            sentence = rec.get("sentence", "")
            source = rec.get("source", "")
            report.total_candidates += 1
            report.decisions[bucket] += 1
            if bucket == "dropped":
                report.drop_reasons.update(signals)
            bucket_samples = report.samples.get(bucket, [])
            if len(bucket_samples) < sample_size:
                bucket_samples.append((sentence, reason, source))
                report.samples[bucket] = bucket_samples
    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _pct(part: int, whole: int) -> str:
    return f"{(100.0 * part / whole):.1f}%" if whole else "0.0%"


def _truncate(text: str, width: int = 100) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 3] + "..."


def format_report(report: IngestReport, sample_size: int = DEFAULT_SAMPLE_SIZE) -> str:
    """Render an IngestReport as a deterministic plain-text confusion report."""
    total = report.total_candidates
    lines: List[str] = []
    bar = "=" * 64
    lines.append(bar)
    lines.append("LifeGraph ingest - DRY RUN (no database writes)")
    lines.append(bar)
    lines.append(f"files scanned:  {report.files_scanned}")
    lines.append(f"candidates:     {total}")
    if report.duplicates_skipped:
        lines.append(f"deduped:        {report.duplicates_skipped}  (skipped — same sentence seen before)")
    lines.append("")

    lines.append(f"{'verdict':<10}{'count':>8}{'share':>9}")
    lines.append(f"{'-' * 10}{' ' + '-' * 7:>8}{' ' + '-' * 8:>9}")
    for bucket in _BUCKETS:
        count = report.decisions.get(bucket, 0)
        lines.append(f"{bucket:<10}{count:>8}{_pct(count, total):>9}")
    lines.append("")

    dropped = report.decisions.get("dropped", 0)
    lines.append(f"drop reasons (signals among the {dropped} dropped):")
    if report.drop_reasons:
        for signal, count in report.drop_reasons.most_common():
            lines.append(f"  {signal:<30}{count:>6}")
    else:
        lines.append("  (none)")
    lines.append("")

    for bucket in _BUCKETS:
        shown = report.samples[bucket]
        total_in_bucket = report.decisions.get(bucket, 0)
        header = f" sample: {bucket.upper()} (showing {len(shown)} of {total_in_bucket}) "
        lines.append(header.center(64, "-"))
        if not shown:
            lines.append("  (none)")
        for sentence, reason, source in shown:
            lines.append(f'  - "{_truncate(sentence)}"')
            lines.append(f"      reason: {_truncate(reason, 90)}")
            lines.append(f"      from:   {source}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lifegraph.ingest",
        description=(
            "Dry-run Claude Code log ingestor. Classifies on-disk session "
            "sentences as KEEP/HOLD/DROP and prints a report. Never writes to "
            "the database — persistence is a separate, later step."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_PROJECTS_ROOT,
        help=f"Session logs root (default: {DEFAULT_PROJECTS_ROOT}).",
    )
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        metavar="SUBSTR",
        help=(
            "Only ingest sessions whose path contains SUBSTR "
            "(repeatable; case-insensitive). Default: all sessions."
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="SUBSTR",
        help=(
            "Skip sessions whose path contains SUBSTR (repeatable; "
            "case-insensitive). Use this to omit the project you are "
            "developing in (e.g. --exclude LifeGraph)."
        ),
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help="Example sentences to show per verdict (default: %(default)s).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N candidates (quick smoke run). Default: process all.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ingest_results.jsonl"),
        metavar="PATH",
        help=(
            "Append each verdict as a JSON line to this file immediately "
            "(flushed after every write, so progress survives a kill). "
            "Default: ingest_results.jsonl"
        ),
    )
    parser.add_argument(
        "--report-only",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Skip the LLM entirely: read a previously saved results file "
            "and print the report from it. Useful after a partial run."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: build a parser from config, run a dry-run pass, print the report."""
    args = _build_arg_parser().parse_args(argv)

    # --report-only: regenerate the report from a saved results file, no LLM.
    if args.report_only is not None:
        if not args.report_only.exists():
            print(f"Results file not found: {args.report_only}")
            return 1
        report = report_from_file(args.report_only, sample_size=args.sample)
        print(format_report(report, sample_size=args.sample))
        return 0

    parser = make_parser()
    if parser is None:
        print(
            "Parser unavailable: set LIFEGRAPH_MODEL (or provide config) so a "
            "parser can be built.",
        )
        return 2

    try:
        report = run_ingest(
            parser,
            root=args.root,
            sample_size=args.sample,
            limit=args.limit,
            projects=args.project,
            exclude=args.exclude,
            output_path=args.output,
        )
    except (OllamaUnavailableError, OllamaTimeoutError) as exc:
        print(
            "Ollama is not reachable, so sentences cannot be parsed. Start it "
            f"with `ollama serve` (127.0.0.1:11434) and retry.\n  detail: {exc}",
        )
        return 3

    print(format_report(report, sample_size=args.sample))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

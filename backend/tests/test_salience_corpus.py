"""Precision/recall harness for the salience filter.

Runs ``classify`` over the hand-labeled corpus in ``salience_corpus.py`` and:

  - builds a 3×3 confusion matrix (expected rows × predicted cols);
  - computes per-class precision and recall;
  - hard-asserts zero false auto-KEEPs (the graph trust invariant);
  - soft-asserts recall floors: KEEP >= 0.80, DROP >= 0.90;
  - always prints the matrix and per-class metrics (use pytest -s to see output).

Run:
    cd backend && pytest tests/test_salience_corpus.py -s
"""
from __future__ import annotations

from typing import List, Tuple

import pytest

from lifegraph.salience import SalienceDecision, SalienceVerdict, classify
from tests.salience_corpus import CORPUS, CorpusEntry

KEEP = SalienceDecision.KEEP
HOLD = SalienceDecision.HOLD
DROP = SalienceDecision.DROP
CLASSES = [KEEP, HOLD, DROP]
_LABEL = {KEEP: "KEEP", HOLD: "HOLD", DROP: "DROP"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ConfusionMatrix = dict[SalienceDecision, dict[SalienceDecision, int]]
Misclassified = List[Tuple[str, SalienceDecision, SalienceDecision, list]]


def _run_corpus() -> Tuple[ConfusionMatrix, Misclassified]:
    """Classify every corpus entry; return the confusion matrix and mislabels."""
    confusion: ConfusionMatrix = {c: {d: 0 for d in CLASSES} for c in CLASSES}
    misclassified: Misclassified = []
    for entry in CORPUS:
        verdict: SalienceVerdict = classify(entry.sentence, entry.proposal)
        confusion[entry.expected][verdict.decision] += 1
        if verdict.decision != entry.expected:
            misclassified.append(
                (entry.sentence, entry.expected, verdict.decision, verdict.signals)
            )
    return confusion, misclassified


def _compute_metrics(confusion: ConfusionMatrix) -> dict[SalienceDecision, dict]:
    metrics: dict[SalienceDecision, dict] = {}
    for cls in CLASSES:
        tp = confusion[cls][cls]
        true_total = sum(confusion[cls][p] for p in CLASSES)
        pred_total = sum(confusion[e][cls] for e in CLASSES)
        recall = tp / true_total if true_total else 0.0
        precision = tp / pred_total if pred_total else 0.0
        metrics[cls] = {
            "tp": tp,
            "total": true_total,
            "precision": precision,
            "recall": recall,
        }
    return metrics


def _print_report(
    confusion: ConfusionMatrix,
    metrics: dict,
    misclassified: Misclassified,
) -> None:
    col_header = "            " + "  ".join(
        f"pred={_LABEL[c]:4}" for c in CLASSES
    )
    rows = [col_header]
    for exp in CLASSES:
        cells = "  ".join(f"{confusion[exp][pred]:10d}" for pred in CLASSES)
        rows.append(f"true={_LABEL[exp]:4}  {cells}")

    metric_lines = []
    for cls in CLASSES:
        m = metrics[cls]
        metric_lines.append(
            f"  {_LABEL[cls]:4}  precision={m['precision']:.2f}"
            f"  recall={m['recall']:.2f}"
            f"  (tp={m['tp']} / n={m['total']})"
        )

    lines = [
        "",
        "=" * 62,
        "Salience corpus results",
        "-" * 62,
        "Confusion matrix (rows=expected, cols=predicted):",
        *rows,
        "-" * 62,
        "Per-class metrics:",
        *metric_lines,
    ]
    if misclassified:
        lines += ["-" * 62, "Misclassified:"]
        for sentence, exp, got, signals in misclassified:
            lines.append(
                f"  [{_LABEL[exp]}->{_LABEL[got]}]  {sentence!r}"
                f"  signals={signals}"
            )
    lines.append("=" * 62)
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


def test_salience_corpus() -> None:
    confusion, misclassified = _run_corpus()
    metrics = _compute_metrics(confusion)
    _print_report(confusion, metrics, misclassified)

    # Hard invariant: zero false auto-KEEPs.
    # A HOLD/DROP sentence silently persisted to the graph has no recovery
    # path — it corrupts the data the entire tool is built on.
    false_keeps = [
        (s, exp, got, sig)
        for s, exp, got, sig in misclassified
        if got is KEEP and exp is not KEEP
    ]
    assert not false_keeps, (
        f"TRUST INVARIANT VIOLATED — {len(false_keeps)} false auto-KEEP(s):\n"
        + "\n".join(
            f"  [true={_LABEL[exp]}]  {s!r}  signals={sig}"
            for s, exp, got, sig in false_keeps
        )
    )

    # Soft recall floors (tighten as corpus grows).
    keep_recall = metrics[KEEP]["recall"]
    drop_recall = metrics[DROP]["recall"]

    assert keep_recall >= 0.80, (
        f"KEEP recall {keep_recall:.2f} < 0.80 — "
        "too many stable user facts routed to HOLD/DROP"
    )
    assert drop_recall >= 0.90, (
        f"DROP recall {drop_recall:.2f} < 0.90 — "
        "too much noise leaking into HOLD or KEEP"
    )

"""Which section of a markdown document is a claim actually *about*? (feedback-v6 §7)

An **offer**, never a warning — and that distinction is the whole design. The field measured its own
store to find a rule separating a legitimate whole-file anchor from one that should have been a
``#section``, and returned a null: every size-shaped signal overlaps almost completely (the 7–26
heading band alone holds 35 of 41 cases), the best usable headings threshold costs **15 % false
positives at 32 % recall**, and "has it actually drifted?" — the most intuitive candidate — fires on
7 of 13 *legitimate* anchors, because a living document drifts whether or not the anchor is wrong.
An unconditional warning is right about two times in three and nothing beats it at usable recall.

So the blocker is dissolved rather than solved. A warning needs a rule that separates; an offer does
not. On a claim that really is about the whole document the author reads one line, sees it is not
what they meant, and keeps the whole-file anchor — one line, no ⚠, nothing to clear later, and no
training signal to start ignoring a mark. The field's own mechanical version of exactly this named a
plausible home for **19 of 25** mis-anchored items. That is the only form the population supports.

The scorer is deliberately tiny and self-calibrating: term weights are the *file's own* inverse
section frequency, so a word in every section (``the``, and equally the document's own subject noun)
weighs zero and no stopword list is needed or maintained. Silence is still the default (design law
#4) — no clear winner, no offer.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from yigraf.astnorm import section_texts

#: Identifier-ish words. Short tokens are dropped before scoring: they carry no subject and would let
#: an accidental ``for``/``the`` collision decide which section a belief is filed under.
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MIN_TERM = 3


def _terms(text: str) -> set[str]:
    return {w.casefold() for w in _WORD.findall(text) if len(w) >= _MIN_TERM}


@dataclass(frozen=True)
class Fit:
    """What :func:`section_fit` scored, *before* the margin is applied — the row the offer ledger needs.

    ``candidate`` is ``None`` when the document has no offerable subdivision or nothing scores, and the
    two scores are then ``0.0``. Kept separate from :func:`best_section`'s verdict because the number
    that should set ``section_offer_margin`` is the accept rate of the offers it *suppressed* as much as
    the ones it let through, and a record written at the print site sees only the latter (feedback-v7
    G#4).
    """
    candidate: str | None
    top: float
    runner_up: float

    def wins_by(self, margin: float) -> bool:
        """Would this fit be offered at ``margin``? The gate itself, so the ledger and the offer cannot
        disagree about what a stored row would have done at a different threshold.

        A ``runner_up`` of zero passes at every margin, and that is the definition rather than a hole:
        the second-best *section* scored none of the claim's distinctive terms, so the ratio is
        unbounded and no finite threshold restrains it. It is also the strongest signal the scorer can
        produce. What the zero must never mean is "there was no runner-up to compare against" — that
        shape is refused structurally in :func:`section_fit`, one candidate not being a choice.
        """
        if self.candidate is None or self.top <= 0:
            return False
        return not (self.runner_up > 0 and self.top < margin * self.runner_up)


def section_fit(root: Path, relpath: str, statement: str) -> Fit:
    """Score every offerable section of ``relpath`` against ``statement``, applying no threshold.

    Two kinds of section score but are never *offered*: an ambiguous slug (``cli._anchor`` refuses a
    duplicate ``#slug`` outright, so offering one would hand over a command that cannot run) and a
    heading spanning the whole file (a document title is not a narrowing of a whole-file anchor). Both
    still count toward the term statistics, because they are genuinely part of what this document says
    where.

    **Fewer than two offerable sections is silence, and that is the structural exemption** — not the
    raw section count it used to be tested on. An offer is a *choice*: "this section, more than the
    others". Where there is exactly one candidate there is no runner-up, so ``margin`` had nothing to
    apply against and was skipped entirely — ``1e9`` offered as readily as ``2.0``, leaving the knob
    inert on that whole shape and nothing between it and off (feedback-v7 G#2). A one-subdivision
    document is also the case where narrowing buys least: "the file, minus its preamble" is not a
    narrowing worth a line of the reader's context. The exemption 1.9.0's notes claimed fell out of
    the design for ``coding-conventions.md`` (a title plus one ``##``) IS this test — it was written on
    ``len(sections)``, which counts the title too, so it never fired there.
    """
    sections = section_texts(root, relpath)
    slugs = [slug for slug, _, _ in sections]
    offerable = {slug for slug, _, spans_file in sections
                 if slugs.count(slug) == 1 and not spans_file}
    if len(offerable) < 2:
        return Fit(None, 0.0, 0.0)

    per_section = [(slug, _terms(text)) for slug, text, _ in sections]
    total = len(per_section)
    df = Counter(term for _, terms in per_section for term in terms)
    wanted = _terms(statement)

    scored = sorted(((sum(math.log(total / df[t]) for t in wanted & terms), slug)
                     for slug, terms in per_section if slug in offerable),
                    key=lambda pair: (-pair[0], pair[1]))
    if not scored or scored[0][0] <= 0:
        return Fit(None, scored[0][0] if scored else 0.0, 0.0)
    return Fit(scored[0][1], scored[0][0], scored[1][0] if len(scored) > 1 else 0.0)


def best_section(root: Path, relpath: str, statement: str, margin: float = 2.0) -> str | None:
    """The one section slug that reads like ``statement``'s subject, or ``None`` for no clear winner.

    ``margin`` is how far ahead of the runner-up the winner must be (``2.0`` = twice the score). It is
    the offer's only tuning, and it is set for *legibility*, not recall: a second section that scores
    within the margin means the document says the claim's distinctive words in two places, and an
    offer that names one of them arbitrarily teaches the reader the suggestion is noise. Nothing is
    lost by staying quiet — the whole-file anchor already captured is correct and drifts correctly.
    """
    fit = section_fit(root, relpath, statement)
    return fit.candidate if fit.wins_by(margin) else None

"""Provenance-typed revision policy — a scoped partial order over beliefs (epistemic-control-plane #6).

int:memory-maturity / mem:81edb04b2c41bdef: when two LIVE beliefs concern the same anchor and disagree,
which does the graph prefer? The answer is **provenance-typed, never a single confidence scalar** — a
belief's authority is the *kind* of thing that grounds it (a human endorsement, a normative contract, a
live observation), not a number to average. This module is the classifier + the strict order over those
kinds. It is the adopted-as-PRINCIPLE half of the JTMS/AGM reframe (mem:81edb04b2c41bdef): a lightweight
policy, **not** a label-propagation engine and **not** an auto-revision gate.

**Partial, not total — never last-writer-wins.** Two beliefs of the SAME provenance tier are deliberately
*incomparable*: :func:`dominant_id` returns ``None``, so the pair stays an open knowledge-conflict for a
human to resolve (mem:062), rather than a scalar tiebreak (or insertion order) silently killing one. The
order only *informs* a principal's resolution — the :class:`~yigraf.contradiction.Conflict` finding's
suggested-dominant side on the status surface (mem:012) — it never mutates a belief or gates a write
(design law #5; mem:058: belief revision is a later append, not a synchronous verdict here).

**Scoped.** The comparison is provenance-only; the SCOPE (the shared anchor two beliefs both concern) is
the caller's. :func:`yigraf.contradiction.detect_conflicts` only ever pairs co-anchored live beliefs, so
the order is asked only *within* a scope — beliefs about different anchors are never ranked against each
other.
"""
from __future__ import annotations

#: The provenance order, highest authority first (epistemic-control-plane #6). A belief's tier is the
#: KIND of grounding behind it; a higher tier strictly dominates a lower one. Top-down: ``human`` (a
#: principal endorsed it — the trust floor, int:memory-attestation), ``must`` (a normative SHALL/MUST
#: contract — the intent family), ``empirical`` (confirmed by a live observation — int:memory-grounding),
#: ``architectural`` (a binding design decision/constraint), ``plan-assumption`` (a plan-scoped belief),
#: ``structural`` (derived from code structure — tree-sitter), ``llm`` (an agent's unverified inference —
#: the floor; an unknown provenance lands here too, so it never silently outranks a real belief).
PROVENANCE_ORDER = (
    "human",
    "must",
    "empirical",
    "architectural",
    "plan-assumption",
    "structural",
    "llm",
)

_RANK = {tier: i for i, tier in enumerate(PROVENANCE_ORDER)}

#: Memory kinds that are binding design choices (the ``architectural`` tier). The other memory kinds
#: (rationale, learned-fact, preference, rejected-alternative), absent a stronger signal, fall to ``llm``.
_ARCHITECTURAL_KINDS = frozenset({"decision", "constraint"})


def classify(attrs: dict) -> str:
    """The provenance tier of a belief node, read from its committed epistemic axes (never a scalar).

    Checked in descending authority so the STRONGEST signal a node carries wins its tier: a human
    endorsement (``attestation``) outranks provenance-type on any family; then a normative intent; then
    — for a memory — an empirical grounding, else a design-decision ``kind``; then plan/structure by
    family. Anything with no recognized provenance (or an unknown family) lands ``llm``: the floor never
    silently outranks a real belief.
    """
    if attrs.get("attestation") == "human":
        return "human"
    family = attrs.get("family")
    if family == "intent":
        return "must"
    if family == "memory":
        if attrs.get("grounding") == "empirical":
            return "empirical"
        if attrs.get("kind") in _ARCHITECTURAL_KINDS:
            return "architectural"
        return "llm"
    if family == "plan":
        return "plan-assumption"
    if family == "structure":
        return "structural"
    return "llm"


def rank(tier: str) -> int:
    """The tier's position in :data:`PROVENANCE_ORDER` (0 = highest). An unknown tier sorts below the
    floor, so a typo can never accidentally outrank a real belief."""
    return _RANK.get(tier, len(PROVENANCE_ORDER))


def dominates(a: dict, b: dict) -> bool:
    """True iff belief ``a`` provenance-dominates ``b`` — a STRICTLY higher tier. Same tier ⇒ ``False``:
    the order is partial, so equal-provenance beliefs are incomparable (a genuine conflict a human
    resolves, never a scalar tiebreak; mem:062)."""
    return rank(classify(a)) < rank(classify(b))


def dominant_id(left_id: str, left: dict, right_id: str, right: dict) -> str | None:
    """Which of two co-anchored beliefs the provenance order prefers, or ``None`` when they are the same
    tier (incomparable — held as an open conflict). Pure guidance for a principal's resolution; it never
    supersedes a belief itself — belief revision is a later human append (mem:058/mem:062)."""
    if dominates(left, right):
        return left_id
    if dominates(right, left):
        return right_id
    return None

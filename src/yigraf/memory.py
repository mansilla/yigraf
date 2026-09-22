"""The memory node family: the authored ``.md`` truth for captured reasoning (M7).

A memory node is a durable, versioned record of a *reasoning event* — a decision, constraint,
rationale, rejected alternative, learned fact, or preference — captured at a commit boundary and
linked into the graph (``docs/memory-model.md``, ``docs/capture-flow.md``). It is the persisted
``T`` (the *why*) that chat history loses on ``/clear``.

Like intents and plans (``docs/graph-design.md`` §4), memory is one-file-per-node markdown under
``yigraf/memory/<seq>-<slug>.md`` — body authored for humans, frontmatter machine-written by the
``remember`` / ``supersede`` / ``note-constraint`` verbs. This module reads those files into a
dataclass, writes new ones, and projects them into the graph with their cross-family edges:

- ``serves`` → an intent/plan node (this decision works toward that goal),
- ``concerns`` → a structure node, carrying a **drift anchor** (this decision governs that code; edit
  the code and drift surfaces a "re-verify" reconcile — handled by :mod:`yigraf.drift`),
- ``supersedes`` → another memory node (a mind-change; the predecessor sinks in ranking but stays
  available as a rejected alternative if it was ever referenced).

An unresolved target is **not** added as a phantom edge — ``serves``/``supersedes`` stash a
``dangling_*`` marker; ``concerns`` stashes ``dangling_concerns`` so :mod:`yigraf.drift` can
rename-re-anchor or surface it as hard drift, exactly as it does for a task's ``implements``.

v0 capture is deterministic and agent-asserted (memory-model §5 option A): no embedding dedup yet
(that's M8), so write-time collision handling is the trivial "does this exact node already exist".
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from yigraf import artifacts
from yigraf.astnorm import ANCHOR_ALGO

MEMORY_FAMILY = "memory"

#: The families :func:`recompute_counters` stamps supersession counters on — the AUTHORED families,
#: which is exactly the set :mod:`yigraf.fold` creates nodes for, so the migration proof compares like
#: with like. Structure nodes stay unstamped: nothing supersedes a symbol, and retrieval reads the
#: counter with a ``0`` default (feedback-v11 §E, superseding mem:003's memory-only rule).
_COUNTED_FAMILIES = frozenset({MEMORY_FAMILY, "intent", "plan"})
CONF = "EXTRACTED"  # agent-asserted at a commit boundary, not inferred

#: Epistemic-grounding axis (int:memory-grounding, C#6): *how* a belief was arrived at — orthogonal to
#: maturity (has it survived?) and attestation (who endorsed it?). ``inferred`` is the default for an
#: agent-asserted decision (it may be a guess); ``docs`` for one distilled from committed docs/rationale;
#: ``empirical`` for one confirmed by a live observation (a spike, a test, a prod signal). It can be
#: upgraded once evidence lands (``reaffirm --grounding empirical --evidence``), and ``empirical`` is
#: *demoted* when the evidence it names drifts (:mod:`yigraf.drift`) — but a low tier is never itself a
#: nag: an ``inferred`` node is surfaced by relevance like any other and no surface asks it to re-verify.
#: That asymmetry is deliberate. Grounding records how a belief was ARRIVED at, and for a whole class —
#: a ``preference`` a human stated in conversation — there is nothing in the repo to re-derive it from,
#: so a standing "re-verify me" would be a demand no verb can satisfy. Who vouches for such a belief is
#: the *attestation* axis's question (``yigraf attest`` ⇒ ``human``), which is why the field asked for a
#: fourth "observed, but the observation was a conversation" tier and does not need one.
GROUNDINGS = ("inferred", "docs", "empirical")
DEFAULT_GROUNDING = "inferred"

#: The anchor "algorithm" of a policy concern (``--governs``, feedback-v3 #5): the belief governs how
#: a locus is USED, not what it contains — so it surfaces at the edit hook exactly like a concern but
#: carries no content hash and NEVER drifts. A whole-file hash on "status.md holds only status" drifted
#: once per commit while every one of those edits obeyed it; a recurring never-real ⚠ trains the reader
#: to clear the badge without reading it, which is the failure the reaffirm/supersede split exists to
#: prevent. drift skips anchorless edges, so this needs no special-casing there; only re-stampers must
#: leave it alone (cli._reaffirm_concerns).
GOVERNS_ALGO = "governs-v1"

#: Attestation axis (int:memory-attestation): *who endorsed* a belief — orthogonal to grounding (how)
#: and maturity (survived?). ``agent`` is the default (an agent-captured node); ``human`` marks a
#: principal-endorsed node — a trust floor that ranks it up and makes it **sticky**: an agent
#: ``supersede`` of a human-attested node is held *pending* (surfaced as a conflict), never applied
#: silently. The human-facing entry path (a verb) lands with intent-elicitation (task #4); until then
#: ``attestation: human`` is set in a node's frontmatter (files are truth, R6).
ATTESTATIONS = ("agent", "human")
DEFAULT_ATTESTATION = "agent"

#: Maturity ladder (int:memory-maturity, mem:033) — promoted behaviorally, never by commit-age:
#: ``proposed`` a candidate distilled from mining/review (int:knowledge-mining, int:review-compound):
#: near-zero retrieval weight, and it expires unless a real encounter confirms it (GC, task #7). One
#: survived encounter (an uphold) graduates it to ``working``. ``working`` the tier an agent
#: ``remember`` lands at — a live belief with no ranking bonus. ``settled`` survived ``≥ maturity_k``
#: review-encounters un-superseded (the read-time verdict). Only ``proposed``/``working`` are *landed*
#: (build-recomputable from provenance); ``settled`` is the sidecar-derived read-time verdict.
MATURITIES = ("proposed", "working", "settled")
DEFAULT_MATURITY = "working"

#: Memory-node id algorithm (memid-v1, mem:063): the id is the content-hash of the SEMANTIC payload
#: ONLY — never provenance/timestamp/causal-parents — so two agents that independently assert the same
#: decision mint the SAME id and collapse to one node on merge (int:concurrent-write-model, mem:060).
#: Versioned like :data:`yigraf.astnorm.ANCHOR_ALGO` so the recipe can evolve without silently
#: re-identifying existing nodes. Coordinator-free, so it retires the racy global :func:`next_seq` for
#: minting (its only remaining job is the legacy-id fallback for pre-memid files).
MEMORY_ID_ALGO = "memid-v1"

#: Provenance ``source`` values whose candidates LAND at ``proposed`` (they must be confirmed by a real
#: encounter before they carry weight). An agent-asserted ``remember`` (source ``cli``/``mcp``) lands
#: ``working``; a mined or review-distilled candidate lands ``proposed`` (int:knowledge-mining,
#: int:review-compound). This is the shared quarantine landing zone the miner + review bridge feed.
PROPOSED_SOURCES = frozenset({"mined", "review"})


def landing_maturity(provenance: Any) -> str:
    """The tier a memory ENTERS at, derived from its provenance (build-recomputable — provenance is
    committed truth, so the landed tier never needs a stored counter, R1).

    Mined/review candidates land ``proposed`` (near-zero weight, expiring); an agent-asserted
    ``remember`` lands ``working``. Promotion *above* the landed tier — the confirm of a proposed
    candidate, the settle of a working one — is the behavioral read-time verdict
    (:func:`yigraf.counters.apply_maturity_verdict`), never this.

    Accepts either the verb-built ``dict`` (a single landing record) or the fold's envelope ``list``
    (mem:063 — provenance rides the assertion as a list so identical-content collapse unions it): the
    landing record is the first, so a lone-record memory reads exactly as it did pre-fold.
    """
    record = provenance[0] if isinstance(provenance, list) and provenance else provenance
    source = record.get("source") if isinstance(record, dict) else None
    return "proposed" if source in PROPOSED_SOURCES else "working"


#: Memory node types (graph-design §1 / memory-model §1). ``constraint`` is the promotable one.
MEMORY_TYPES = (
    "decision",
    "constraint",
    "rationale",
    "rejected-alternative",
    "learned-fact",
    "preference",
)

#: The type a bare capture lands as. Named so ``supersede`` can tell "the caller inherited a
#: non-default type" from "nothing to report" when it echoes what carried (feedback-v4 #12).
DEFAULT_MEMORY_TYPE = "decision"

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_HEADING = re.compile(r"^##\s+(.*?)\s*$")
_WHY = re.compile(r"^\*\*Why:\*\*\s*(.*)$")
_REJECTED = re.compile(r"^\*\*Rejected:\*\*\s*(.*)$")
_SLUG_STOP = re.compile(r"[^a-z0-9]+")

#: The frontmatter keys :func:`render_memory` OWNS — recomputed from the dataclass on every write. A
#: key that is not listed here is one this version of yigraf does not recognize: it rides through a
#: re-stamp untouched on :attr:`Memory.extra_meta` instead of being dropped. The memory store is
#: committed and shared across machines, so version skew is normal, and an older engine re-stamping
#: one anchor must not silently strip a field a newer one wrote.
_MANAGED_META = frozenset({
    "id", "family", "type", "status", "maturity", "grounding", "attestation", "serves", "concerns",
    "evidence", "supersedes", "superseded_by", "pending_supersedes", "equivalent_to",
    "rejected_valid_when", "rejected_invalidated_when", "promotable", "pinned", "provenance",
})


# --------------------------------------------------------------------------------------------------
# Frontmatter helpers (mirrors artifacts.py; kept local so the modules stay decoupled)
# --------------------------------------------------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER.match(text)
    if match is None:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("memory frontmatter must be a YAML mapping")
    return meta, match.group(2)


def _compose(meta: dict, body: str) -> str:
    front = yaml.safe_dump(meta, sort_keys=True, allow_unicode=True, default_flow_style=False)
    body = body if body.endswith("\n") or not body else body + "\n"
    return f"---\n{front}---\n{body}"


# --------------------------------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------------------------------


@dataclass
class Concern:
    """A ``concerns`` edge target: the governed symbol + the drift anchor stamped at capture time."""

    sym: str
    anchor: str | None = None
    anchor_algo: str | None = None


@dataclass
class Evidence:
    """A ``grounded_by`` edge target: what *substantiates* a belief (int:memory-grounding).

    Orthogonal to :class:`Concern` (what a decision *governs*): evidence is what earned its
    ``empirical`` grounding tier — a test, a spike, a prod signal. A resolvable locus
    (``sym:``/``file:``) carries a drift anchor exactly like a Concern, so the evidence changing
    surfaces as ``grounded_by`` drift — the empirical tier is now unearned (a demotion trigger for
    int:memory-maturity). An *opaque* ref (``commit:<sha>``, a URL, free text) is recorded but never
    drifts: there is nothing in the repo to hash, and a commit sha is immutable anyway.
    """

    ref: str
    anchor: str | None = None
    anchor_algo: str | None = None


@dataclass
class Memory:
    id: str
    seq: int
    slug: str
    type: str
    statement: str
    why: str = ""
    alternatives: str | None = None
    #: Applicability premises for ``alternatives`` (task epistemic-control-plane/3, JTMS-style): graph
    #: locators (``int:``/``mem:``/``sym:``/``file:``) whose *liveness* conditions whether the rejection
    #: still applies. The rejection surfaces only while every ``rejected_valid_when`` premise holds and
    #: no ``rejected_invalidated_when`` condition holds — so a rejection whose reason lapsed stops
    #: mis-steering the agent away from a now-viable option. Evaluated at read time (never stored, R6)
    #: by :func:`yigraf.retrieval.premise_holds`; empty ⇒ an unconditioned rejection that always applies.
    rejected_valid_when: list[str] = field(default_factory=list)
    rejected_invalidated_when: list[str] = field(default_factory=list)
    serves: list[str] = field(default_factory=list)
    concerns: list[Concern] = field(default_factory=list)
    # What grounds the belief (int:memory-grounding): required to claim ``grounding: empirical``. A
    # locus (sym:/file:) carries a drift anchor and projects a ``grounded_by`` edge; an opaque ref
    # (commit:/url/text) is recorded but never drifts. Orthogonal to ``concerns`` (what it governs).
    evidence: list[Evidence] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    # A supersede *held pending* because it targets a human-attested node (int:memory-attestation):
    # projected as a supersedes edge marked ``pending`` — surfaced as a conflict, not applied (the old
    # node is NOT demoted) until a human resolves it.
    pending_supersedes: list[str] = field(default_factory=list)
    #: Memory ids a principal has reviewed as *compatible* with this one and reconciled — projected as
    #: an ``equivalent_to`` edge that :mod:`yigraf.contradiction` reads to drop the co-anchored pair
    #: from the coherence sweep (mem:062). The reconcile append for a near-dup that is a redundant/
    #: complementary restatement, not a mind-change (which is ``supersedes``).
    equivalent_to: list[str] = field(default_factory=list)
    status: str = "active"
    #: The successor's id, stamped onto THIS artifact when an applied supersede demotes it — so the
    #: artifact tells the truth on its own (feedback-v3 #8: both twins read ``active`` in the store
    #: and a retired belief got pinned). The graph's ``superseded_in`` counter stays the derived
    #: authority; this is the artifact-side mirror, written by the verb that owns the edge.
    superseded_by: str | None = None
    maturity: str = "working"  # working → settled by survived review-encounters at read time (mem:033)
    grounding: str = DEFAULT_GROUNDING  # inferred | docs | empirical (int:memory-grounding, C#6)
    attestation: str = DEFAULT_ATTESTATION  # agent | human (int:memory-attestation)
    promotable: bool = False  # a constraint flagged as a candidate enforced check (capture-flow §0a)
    #: Inject this belief IN FULL at SessionStart, regardless of what the session turns out to be about
    #: (int:session-orientation). A *routing* flag, not a claim about the belief — which is why it is
    #: deliberately outside :func:`memory_id`'s payload: pinning changes nothing about what the memory
    #: asserts, so it must not re-identify the node or fork it from a teammate's identical capture.
    #: Set it only for the handful of constraints that are load-bearing on every task; the budget
    #: (``session_start.pinned_budget``) binds, and a pin tier where everything is pinned is wallpaper.
    pinned: bool = False
    provenance: dict = field(default_factory=dict)
    #: The real "memory/<filename>.md" this node was read from (set by :func:`read_memory`). Lets a
    #: content-addressed (``<slug>-<hash>.md``) file be rewritten/projected by its true path instead of
    #: a name reconstructed from ``seq``; ``None`` on a freshly-built node → derive from seq/slug.
    source_file: str | None = None
    #: The body EXACTLY as read from disk (``None`` on a node built in memory — a fresh capture).
    #: The frontmatter is machine-written, but the body is AUTHORED, and a human extends it by hand:
    #: a second instance of the same trap, the escape that only shows up on a real input device, a
    #: caveat the canonical ``## statement`` / ``**Why:**`` / ``**Rejected:**`` shape does not model.
    #: Every metadata verb (``reaffirm``/``reanchor``/``attest``/``pin``/``supersede``/``unlink``)
    #: round-trips the artifact through :func:`render_memory`, so re-deriving the body from
    #: (statement, why, alternatives) silently DELETED everything else — a re-stamped anchor
    #: truncating the very record it was vouching for, and doing it in the one verb whose whole job is
    #: to say "still true". Kept verbatim and re-emitted instead. Deliberately outside
    #: :func:`memory_id`'s payload, for mem:7ac9f8fae656db5f's reason: prose the canonical shape does
    #: not model changes nothing about what the belief asserts, so it must never re-identify the node
    #: or fork it from a teammate's byte-identical capture.
    body: str | None = None
    #: Frontmatter keys this version does not recognize, carried through a re-stamp untouched — see
    #: :data:`_MANAGED_META`. Never read by yigraf; the point is only that a re-stamp is not a strip.
    extra_meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------------------------------
# Read / render
# --------------------------------------------------------------------------------------------------


def _read_concern(entry: Any) -> Concern:
    if isinstance(entry, str):
        return Concern(sym=entry)
    return Concern(sym=entry["sym"], anchor=entry.get("anchor"), anchor_algo=entry.get("anchor_algo"))


def _read_evidence(entry: Any) -> Evidence:
    if isinstance(entry, str):
        return Evidence(ref=entry)
    return Evidence(ref=entry["ref"], anchor=entry.get("anchor"), anchor_algo=entry.get("anchor_algo"))


def _parse_body(body: str) -> tuple[str, str, str | None]:
    """Return ``(statement, why, alternatives)`` from a memory body.

    The first ``## `` heading is the one-line statement; ``**Why:**`` and ``**Rejected:**`` lines (the
    reasoning ``T`` and the rejected alternative — the most perishable content) follow.
    """
    statement = why = ""
    alternatives: str | None = None
    for line in body.splitlines():
        heading = _HEADING.match(line)
        if heading is not None and not statement:
            statement = heading.group(1).strip()
            continue
        m = _WHY.match(line.strip())
        if m is not None:
            why = m.group(1).strip()
            continue
        m = _REJECTED.match(line.strip())
        if m is not None:
            alternatives = m.group(1).strip()
    return statement, why, alternatives


def read_memory(path: Path) -> Memory:
    """Parse a ``memory/<seq>-<slug>.md`` file into a :class:`Memory`."""
    path = Path(path)
    meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    statement, why, alternatives = _parse_body(body)
    stem = path.stem
    seq = _seq_from_stem(stem)
    slug = stem.split("-", 1)[1] if "-" in stem and stem.split("-", 1)[0].isdigit() else stem
    return Memory(
        id=meta.get("id", f"mem:{seq:03d}"),
        seq=seq,
        slug=slug,
        source_file=f"memory/{path.name}",
        type=meta.get("type", "decision"),
        statement=statement,
        why=why,
        alternatives=alternatives,
        rejected_valid_when=list(meta.get("rejected_valid_when") or []),
        rejected_invalidated_when=list(meta.get("rejected_invalidated_when") or []),
        serves=list(meta.get("serves") or []),
        concerns=[_read_concern(e) for e in (meta.get("concerns") or [])],
        evidence=[_read_evidence(e) for e in (meta.get("evidence") or [])],
        supersedes=list(meta.get("supersedes") or []),
        pending_supersedes=list(meta.get("pending_supersedes") or []),
        equivalent_to=list(meta.get("equivalent_to") or []),
        status=meta.get("status", "active"),
        superseded_by=meta.get("superseded_by"),
        maturity=meta.get("maturity", "working"),
        grounding=meta.get("grounding", DEFAULT_GROUNDING),
        attestation=meta.get("attestation", DEFAULT_ATTESTATION),
        promotable=bool(meta.get("promotable", False)),
        pinned=bool(meta.get("pinned", False)),
        provenance=dict(meta.get("provenance") or {}),
        body=body,
        extra_meta={k: v for k, v in meta.items() if k not in _MANAGED_META},
    )


def _render_body(memory: Memory) -> str:
    """The body to write: the authored one verbatim, or the canonical shape for a node with none yet.

    :func:`_parse_body` recognizes exactly ``## statement`` / ``**Why:**`` / ``**Rejected:**``, so
    anything else in the file is text this function must CARRY, never text it may re-derive. It
    re-derives only when there is nothing to carry — a fresh capture composing its first body.
    """
    if memory.body is not None:
        if _parse_body(memory.body) != (memory.statement, memory.why, memory.alternatives):
            # No verb edits a standing artifact's statement/why/rejected: a changed belief is a new
            # node that ``supersedes`` this one, never an edit (the law artifacts.py states for an
            # intent's SHALL contract, and the whole point of the reaffirm/supersede split for a
            # belief). So a caller reaching here has broken it, and both ways out lose something the
            # caller wanted — drop the authored prose, or drop the edit. Refuse both, before any
            # write_text: the artifact on disk stays intact and says why.
            raise ValueError(
                f"{memory.id}: refusing to re-render an authored body whose statement/why/rejected "
                f"changed — that would delete whatever else the body says. A changed belief is a new "
                f"node that supersedes this one, not an edit; an amend verb must splice its new lines "
                f"into Memory.body itself.")
        return memory.body
    lines = [f"## {memory.statement}"]
    if memory.why:
        lines += ["", f"**Why:** {memory.why}"]
    if memory.alternatives:
        lines += ["", f"**Rejected:** {memory.alternatives}"]
    return "\n".join(lines) + "\n"


def splice_body(body: str, *, statement: str | None = None, why: str | None = None,
                alternatives: str | None = None) -> str:
    """Replace the statement / why / rejected LINES in an authored body, carrying everything else verbatim.

    The splice :func:`_render_body` refuses to perform by re-derivation, and the reason ``amend`` is a
    verb rather than a re-capture: a body may carry hand-written prose those three markers do not
    describe, and re-rendering from the fields would delete it. Each marker occupies a single line
    (:func:`_parse_body` reads one), so a record repair is a line substitution — and a marker the body
    lacks is *inserted* in the canonical order rather than appended, so an amended body reads like a
    captured one. ``None`` means "leave this field alone", which is why a caller must distinguish an
    unpassed flag from an empty one.

    A duplicate marker is collapsed rather than replaced twice: :func:`_parse_body` reads the LAST
    ``**Why:**`` line, so leaving a later one in place would silently defeat the amend that just
    rewrote the first.
    """
    out: list[str] = []
    seen_heading = done_why = done_rejected = False
    for line in body.splitlines():
        if not seen_heading and _HEADING.match(line) is not None:
            seen_heading = True
            out.append(f"## {statement}" if statement is not None else line)
            continue
        if why is not None and _WHY.match(line.strip()) is not None:
            if not done_why:
                out.append(f"**Why:** {why}")
                done_why = True
            continue
        if alternatives is not None and _REJECTED.match(line.strip()) is not None:
            if not done_rejected:
                out.append(f"**Rejected:** {alternatives}")
                done_rejected = True
            continue
        out.append(line)

    def _after(pattern) -> int:
        """The index of the last line matching ``pattern``, or ``-1`` — the insertion anchor."""
        return max((i for i, ln in enumerate(out) if pattern.match(ln.strip()) is not None), default=-1)

    def _insert(text: str, *anchors) -> None:
        """Put ``text`` after the first anchor pattern present, or at the end if the body has none.

        A blank line rides with it so the result is the shape a fresh capture composes
        (:func:`_render_body`): heading, blank, ``**Why:**``, blank, ``**Rejected:**``.
        """
        at = next((i for i in map(_after, anchors) if i >= 0), len(out) - 1)
        out[at + 1:at + 1] = ["", text]

    # A marker can be *missing* as well as wrong, and the heading is the case that bites: a body someone
    # hand-edited the ``## `` line out of would take the new statement on the field and not in the text,
    # and `_render_body`'s guard then raises rather than silently dropping it — a raw traceback out of a
    # repair verb, which is the abandonment design law #1 exists to prevent. So all three insert.
    if statement is not None and not seen_heading:
        out[0:0] = [f"## {statement}", ""]
    if why is not None and not done_why:
        _insert(f"**Why:** {why}", _HEADING)
    if alternatives is not None and not done_rejected:
        _insert(f"**Rejected:** {alternatives}", _WHY, _HEADING)
    return "\n".join(out).rstrip("\n") + "\n"


def render_memory(memory: Memory) -> str:
    """Render the markdown for a memory artifact (frontmatter machine-written, body authored).

    Lossless by construction: unrecognized frontmatter keys ride through (:data:`_MANAGED_META`) and
    the authored body is re-emitted verbatim (:func:`_render_body`), so a verb re-stamping one field
    cannot delete anything else in the artifact.
    """
    meta: dict[str, Any] = dict(memory.extra_meta)  # unrecognized keys first; the owned ones overwrite
    meta.update({
        "id": memory.id,
        "family": MEMORY_FAMILY,
        "type": memory.type,
        "status": memory.status,
        "maturity": memory.maturity,
        "grounding": memory.grounding,
        "attestation": memory.attestation,
        "serves": list(memory.serves),
        "concerns": [
            {"sym": c.sym, "anchor": c.anchor, "anchor_algo": c.anchor_algo} for c in memory.concerns
        ],
        "supersedes": list(memory.supersedes),
    })
    if memory.superseded_by:  # stamped by the successor's applied supersede — see the field's docstring
        meta["superseded_by"] = memory.superseded_by
    if memory.evidence:  # written only when present, like pending_supersedes (keeps the artifact terse)
        meta["evidence"] = [
            {"ref": e.ref, "anchor": e.anchor, "anchor_algo": e.anchor_algo} for e in memory.evidence
        ]
    if memory.rejected_valid_when:  # applicability premises (task 3); written only when the rejection is conditioned
        meta["rejected_valid_when"] = list(memory.rejected_valid_when)
    if memory.rejected_invalidated_when:
        meta["rejected_invalidated_when"] = list(memory.rejected_invalidated_when)
    if memory.pending_supersedes:
        meta["pending_supersedes"] = list(memory.pending_supersedes)
    if memory.equivalent_to:
        meta["equivalent_to"] = list(memory.equivalent_to)
    if memory.promotable:
        meta["promotable"] = True
    if memory.pinned:  # written only when set — an unpinned memory's artifact is byte-unchanged
        meta["pinned"] = True
    if memory.provenance:
        meta["provenance"] = dict(memory.provenance)

    return _compose(meta, _render_body(memory))


# --------------------------------------------------------------------------------------------------
# Sequence allocation + slugs
# --------------------------------------------------------------------------------------------------


def _seq_from_stem(stem: str) -> int:
    head = stem.split("-", 1)[0]
    return int(head) if head.isdigit() else 0


def memory_dir(root: Path) -> Path:
    return Path(root) / "yigraf" / "memory"


def next_seq(root: Path) -> int:
    """The next memory sequence number (1-based), one past the highest already on disk."""
    d = memory_dir(root)
    if not d.is_dir():
        return 1
    highest = 0
    for path in d.glob("*.md"):
        highest = max(highest, _seq_from_stem(path.stem))
    return highest + 1


def slugify(text: str, max_words: int = 6) -> str:
    """A short, stable filename slug from a statement (lowercase, hyphenated, first few words)."""
    words = [w for w in _SLUG_STOP.split(text.lower()) if w]
    slug = "-".join(words[:max_words])
    return slug[:48].strip("-") or "memory"


def memory_path(root: Path, seq: int, slug: str) -> Path:
    return memory_dir(root) / f"{seq:03d}-{slug}.md"


def memory_id(type_: str, statement: str, why: str, alternatives: str | None,
              serves: list[str], concern_syms: list[str], evidence_refs: list[str],
              supersedes: list[str], rejected_valid_when: list[str] | None = None,
              rejected_invalidated_when: list[str] | None = None) -> str:
    """Content-address a memory by its SEMANTIC payload (``memid-v1``, mem:063).

    The id hashes *what the memory says and what it links to* — never provenance, timestamp, or causal
    position — so two agents who independently record the same decision mint the SAME id and collapse
    to one node on merge (int:concurrent-write-model, mem:060). Coordinator-free, so it replaces the
    racy global sequence counter (:func:`next_seq`). Identity spans the whole payload (incl. ``why`` /
    ``alternatives`` and its applicability premises), so collapse is conservative: only genuinely
    identical reasoning merges for free; a same-claim-different-``why`` pair diverges and is left to the
    near-duplicate / reconcile path.

    The applicability premises (task 3) join the payload ONLY when present, so a premise-less memory
    hashes to exactly its pre-task-3 blob — no existing id is re-identified, and ``memid-v1`` stands.
    """
    payload = {
        "algo": MEMORY_ID_ALGO,
        "type": type_,
        "statement": statement.strip(),
        "why": (why or "").strip(),
        "rejected": (alternatives or "").strip(),
        "serves": sorted(serves),
        "concerns": sorted(concern_syms),
        "evidence": sorted(evidence_refs),
        "supersedes": sorted(supersedes),
    }
    if rejected_valid_when:
        payload["rejected_valid_when"] = sorted(rejected_valid_when)
    if rejected_invalidated_when:
        payload["rejected_invalidated_when"] = sorted(rejected_invalidated_when)
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "mem:" + hashlib.sha256(blob).hexdigest()[:16]


def hashed_memory_path(root: Path, slug: str, mem_id: str) -> Path:
    """Path for a content-addressed memory file: ``memory/<slug>-<hash>.md`` (``memid-v1``)."""
    return memory_dir(root) / f"{slug}-{mem_id.split(':', 1)[1]}.md"


def memory_file_path(root: Path, memory: Memory) -> Path:
    """The on-disk path for an already-read memory — its real :attr:`Memory.source_file` (hash-named
    or legacy ``NNN-slug``), falling back to the seq/slug reconstruction for a node built in memory."""
    if memory.source_file:
        return Path(root) / "yigraf" / memory.source_file
    return memory_path(root, memory.seq, memory.slug)


# --------------------------------------------------------------------------------------------------
# Projection into the graph
# --------------------------------------------------------------------------------------------------


def iter_memories(root: Path) -> list[Memory]:
    d = memory_dir(root)
    return [read_memory(p) for p in sorted(d.glob("*.md"))] if d.is_dir() else []


def find_memory(root: Path, mem_id: str) -> Path | None:
    """The artifact path for a memory id (``mem:NNN``), or ``None`` if no such node exists."""
    for path in sorted(memory_dir(root).glob("*.md")) if memory_dir(root).is_dir() else []:
        meta, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
        if meta.get("id") == mem_id:
            return path
    return None


def find_archived_memory(root: Path, mem_id: str) -> Path | None:
    """The artifact path for a memory ``gc`` moved to ``memory/archive/``, or ``None``.

    Deliberately a *separate* lookup from :func:`find_memory` rather than a widened glob: the archive is
    out of the active graph by design, and a reader that silently merged the two would resurrect
    retracted beliefs into every scan. Only the by-id surfaces call this, and they say "archived" when
    they do (feedback-v5 E#1) — the promise ``gc --help`` makes is "never deleted, kept for history",
    and an id that answers "no such node" does not read like history being kept.
    """
    d = memory_dir(root) / "archive"
    if not d.is_dir():
        return None
    for path in sorted(d.glob("*.md")):
        meta, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
        if meta.get("id") == mem_id:
            return path
    return None


#: Ids a ``--why`` can name. Only ``mem:`` is followed (below): an intent states a contract, it does
#: not carry the argument for a belief, so deferring to one is not the pathology this catches.
_WHY_ID = re.compile(r"\b(?:mem|int):[A-Za-z0-9][\w.-]*")

#: Prose that says "the argument is somewhere else". A closed list on purpose — this fires a refusal,
#: so a marker that guesses is worse than one that misses.
_DEFERRAL_MARKERS = (
    "argument is", "argument lives", "argument stays", "argument sits",
    "reasoning is", "reasoning lives", "rationale is", "rationale lives",
    "the why is", "why lives", "see ", "as in ", "as per ", "same as", "same argument",
    "same reasoning", "unchanged", "no change", "locus repair", "repair only", "rename only",
    "carried over", "documented in", "recorded in", "captured in", "stated in",
)

#: Prose that points at the node THIS one supersedes without naming its id — the pointer form the
#: edge set can see and no reader ever followed. The four nodes that motivated this check are all
#: "LOCUS REPAIR ONLY — the belief is unchanged and the argument is in the node this supersedes."
_SUPERSEDES_DEFERRALS = (
    "this supersedes", "it supersedes", "the superseded", "node superseded",
    "its predecessor", "the predecessor", "the previous node", "the prior node",
    "this replaces", "it replaces",
)

#: A residue this short is a bare pointer whatever else it says (``--why "mem:abc123"``).
_BARE_POINTER_WORDS = 3


def ids_named_in(text: str) -> list[str]:
    """Every ``mem:``/``int:`` id written in prose — a reference the EDGE set cannot see.

    ``refs_in`` counts edges, so an id a caller wrote into a ``--why`` is invisible to every count that
    decides what is collectable. This is how ``gc`` sees it (feedback-v5 amendment #2).
    """
    return list(dict.fromkeys(_WHY_ID.findall(text or "")))


def deferring_why(why: str, supersedes: "list[str] | tuple[str, ...]" = (),
                  *, max_words: int = 25) -> str | None:
    """The node id a ``--why`` DEFERS its argument to, or ``None`` when it argues for itself.

    A ``--why`` is a pointer rather than an argument when it names somewhere else and has almost
    nothing left once you remove the pointer: ``"mem:abc123"``, ``"see mem:abc123"``, ``"the belief is
    unchanged and the argument is in the node this supersedes"``. The residue length is what keeps a
    real argument that happens to *cite* a node out of it — an argument is longer than its citation.

    Nothing here reads the filesystem: this is the shape test. Whether the argument is actually THERE
    is :func:`deferral_verdict`, and only that one warns.
    """
    text = (why or "").strip()
    if not text or max_words <= 0:
        return None
    named = _WHY_ID.findall(text)
    residue = _WHY_ID.sub(" ", text)
    words = residue.split()
    lowered = " " + " ".join(residue.lower().split()) + " "
    marked = any(m in lowered for m in _DEFERRAL_MARKERS)
    if named and (len(words) <= _BARE_POINTER_WORDS or (marked and len(words) <= max_words)):
        return named[0]
    if (supersedes and marked and len(words) <= max_words
            and any(p in lowered for p in _SUPERSEDES_DEFERRALS)):
        return list(supersedes)[0]
    return None


def deferral_verdict(root: Path, why: str, supersedes: "list[str] | tuple[str, ...]" = (),
                     *, max_words: int = 25) -> tuple[str, str, list[str]] | None:
    """Follow a deferring ``--why`` to where the argument is supposed to be; ``None`` if it is there.

    Returns ``(target, verdict, chain)`` — ``missing`` (no such node), ``archived`` (``gc`` moved it
    out of the active graph), ``hollow`` (it resolves and carries no ``--why`` of its own, so the
    chain bottoms out in nothing) or ``loop``. ``chain`` is what was walked, nearest first.

    Silence when the argument is real (design law #4): the whole value of the check is that it fires
    only on a pointer to nothing. Files are truth (#6) — it reads the artifacts, not the graph, so it
    works at capture time, before the node being captured exists.
    """
    target = deferring_why(why, supersedes, max_words=max_words)
    if target is None or not target.startswith("mem:"):
        return None
    chain: list[str] = []
    seen: set[str] = set()
    current = target
    while current.startswith("mem:"):
        if current in seen:
            return target, "loop", chain
        seen.add(current)
        chain.append(current)
        path = find_memory(root, current)
        if path is None:
            kind = "archived" if find_archived_memory(root, current) is not None else "missing"
            return target, kind, chain
        node = read_memory(path)
        if not (node.why or "").strip():
            return target, "hollow", chain
        onward = deferring_why(node.why, node.supersedes, max_words=max_words)
        if onward is None:
            return None  # the argument is really there
        current = onward
    return None  # the chain left the memory family — out of scope, see _WHY_ID


def project_into(graph: nx.DiGraph, root: Path) -> None:
    """Add memory nodes + their ``serves``/``concerns``/``supersedes`` edges to ``graph``.

    Run *after* structure + intent/plan projection so ``serves``/``concerns`` targets resolve, and
    *before* :func:`yigraf.drift.resolve_renames` so a renamed ``concerns`` target re-anchors. An
    unresolved target stashes a ``dangling_*`` marker rather than conjuring a phantom node.

    Two passes (mem:063): add *all* memory nodes before projecting *any* edges, so a memory→memory
    ``supersedes``/``pending_supersedes`` edge resolves even when its target sorts later on disk. Under
    the old sequential ids, filenames sorted in creation order so a predecessor was always present
    first; content-addressed (``<slug>-<hash>.md``) files sort by slug, so a one-pass loop would stash
    a forward supersede as ``dangling_supersedes`` and silently drop it (there is no re-resolution pass
    for it, unlike ``dangling_concerns`` which :mod:`yigraf.drift` re-anchors).
    """
    memories = iter_memories(root)
    _project_file_anchor_nodes(graph, root, memories)
    for memory in memories:
        graph.add_node(
            memory.id,
            family=MEMORY_FAMILY,
            kind=memory.type,
            label=memory.statement or memory.slug,
            confidence=CONF,
            status=memory.status,
            maturity=memory.maturity,
            grounding=memory.grounding,
            attestation=memory.attestation,
            statement=memory.statement,
            why=memory.why,
            alternatives=memory.alternatives,
            promotable=memory.promotable,
            pinned=memory.pinned,  # SessionStart injects these in full (retrieval._pinned_block)
            provenance=dict(memory.provenance),  # the landing tier is recomputed from this (R1)
            source_file=memory.source_file or f"memory/{memory.seq:03d}-{memory.slug}.md",
        )
        # Applicability premises (task 3) — set only when the rejection is conditioned, so the
        # projection stays terse and retrieval reads them with a ``[]`` default. Node attrs (not edges): they are
        # read-time liveness checks (:func:`yigraf.retrieval.premise_holds`), not drift-bearing anchors.
        if memory.rejected_valid_when:
            graph.nodes[memory.id]["rejected_valid_when"] = list(memory.rejected_valid_when)
        if memory.rejected_invalidated_when:
            graph.nodes[memory.id]["rejected_invalidated_when"] = list(memory.rejected_invalidated_when)
    for memory in memories:  # second pass: every memory target now exists (see two-pass note above)
        _project_memory_edges(graph, memory)


def _project_file_anchor_nodes(graph: nx.DiGraph, root: Path, memories: list[Memory]) -> None:
    """Inject a node for each ``file:`` target a memory concerns / is grounded by / is conditioned on,
    carrying its *current* hash (#12; premises reuse the node for a presence check, task 3).

    Infra/glue files (Dockerfile, buildspec, ``*.sh``) have no code symbol to anchor to, so a decision
    about them targets ``file:<path>[:L<a>-L<b>]``. The extractor never produced such a node, so we add
    one here with the file's current SHA-256 — then the ``concerns`` edge resolves and :mod:`yigraf.drift`
    soft-compares the stored anchor against it, exactly as for a symbol. A missing file is left absent →
    the edge stays dangling → hard drift, matching a gone symbol.
    """
    for memory in memories:
        # Three memory→file relations need a file-anchor node: ``concerns`` (what it governs) and
        # ``grounded_by`` (a file that is its evidence) — both drift-bearing — plus a ``file:``
        # applicability premise (task 3), whose whole point is to track whether the file EXISTS: a
        # ``file:infra/redis.tf`` invalidated-when premise withdraws the rejection the moment that file
        # appears, so it needs the node so :func:`yigraf.retrieval.premise_holds` sees its presence.
        #
        # The stored anchor rides along because :func:`yigraf.artifacts.mint_locus_node` needs it to
        # rescue a renamed heading. A premise has none — its whole question is whether the locus
        # EXISTS, and a premise on a section that was renamed is honestly not-holding.
        loci = ([(c.sym, c.anchor) for c in memory.concerns]
                + [(e.ref, e.anchor) for e in memory.evidence]
                + [(ref, None) for ref in memory.rejected_valid_when]
                + [(ref, None) for ref in memory.rejected_invalidated_when])
        for locus, anchor in loci:
            if locus.startswith("file:"):
                artifacts.mint_locus_node(graph, root, locus, anchor)


def _project_memory_edges(graph: nx.DiGraph, memory: Memory) -> None:
    for target in memory.serves:
        if target in graph:
            graph.add_edge(memory.id, target, relation="serves", confidence=CONF)
        else:
            _stash(graph, memory.id, "dangling_serves", target)

    for concern in memory.concerns:
        if concern.sym in graph:
            attrs = {"relation": "concerns", "confidence": CONF}
            if concern.anchor is not None:
                attrs["anchor"] = concern.anchor
                attrs["anchor_algo"] = concern.anchor_algo or ANCHOR_ALGO
            graph.add_edge(memory.id, concern.sym, **attrs)
        else:
            # Keep the anchor so drift.resolve_renames can re-anchor a rename by content match.
            _stash(graph, memory.id, "dangling_concerns",
                   {"sym": concern.sym, "anchor": concern.anchor, "anchor_algo": concern.anchor_algo})

    # ``grounded_by`` (int:memory-grounding): a locus (sym:/file:) evidence gets an anchored edge and
    # rides the SAME drift machinery as concerns (yigraf.drift._DRIFT_RELATIONS) — evidence changing =
    # the empirical tier is unearned. An opaque ref (commit:/url/text) has no anchor: recorded on the
    # node for rendering, never an edge, never drifts (nothing in-repo to hash).
    for ev in memory.evidence:
        if ev.anchor is None and not (ev.ref.startswith("sym:") or ev.ref.startswith("file:")):
            _stash(graph, memory.id, "opaque_evidence", ev.ref)
        elif ev.ref in graph:
            graph.add_edge(memory.id, ev.ref, relation="grounded_by", confidence=CONF,
                           anchor=ev.anchor, anchor_algo=ev.anchor_algo or ANCHOR_ALGO)
        else:
            _stash(graph, memory.id, "dangling_grounded_by",
                   {"sym": ev.ref, "anchor": ev.anchor, "anchor_algo": ev.anchor_algo})

    for old in memory.supersedes:
        if old in graph:
            graph.add_edge(memory.id, old, relation="supersedes", confidence=CONF)
        else:
            _stash(graph, memory.id, "dangling_supersedes", old)

    # A held-pending supersede (of a human-attested node): projected as a supersedes edge marked
    # ``pending`` — recompute_counters does NOT count it, so the old node stays authoritative; retrieval
    # surfaces it as a conflict until a human resolves it (int:memory-attestation).
    for old in memory.pending_supersedes:
        if old in graph:
            graph.add_edge(memory.id, old, relation="supersedes", confidence=CONF, pending=True)
        else:
            _stash(graph, memory.id, "dangling_supersedes", old)

    # A principal-attested reconciliation (mem:062): the co-anchored pair is compatible, so
    # yigraf.contradiction._reconciled drops it from the coherence sweep. Not a mind-change (no
    # demotion, no counter) — both beliefs stay live; the edge only records "reviewed, compatible".
    for peer in memory.equivalent_to:
        if peer in graph:
            graph.add_edge(memory.id, peer, relation="equivalent_to", confidence=CONF)
        else:
            _stash(graph, memory.id, "dangling_equivalent_to", peer)


def _stash(graph: nx.DiGraph, node_id: str, attr: str, value: Any) -> None:
    graph.nodes[node_id].setdefault(attr, []).append(value)


def recompute_counters(graph: nx.DiGraph) -> None:
    """Materialize the edge-derived supersession counters on memory nodes (graph-design §3).

    ``superseded_in`` / ``supersedes_out`` are recomputed on each build (self-healing) so retrieval's
    relevance prior can down-weight a superseded decision in O(1) without a traversal. A node with
    ``superseded_in > 0`` is stale: it sinks in ranking but stays available as a rejected alternative.

    **Every family, not memory alone** (feedback-v11 §E). This used to skip non-memory nodes on the
    stated ground that "only memory nodes carry ``supersedes`` edges" — true when it was written and
    falsified by ``supersede-intent``, which exists to write a real ``int→int`` supersedes edge and
    calls that the most important decision class there is. Nothing caught it because this function has
    exactly one caller left in the tree — ``tests/test_migrate.py``'s projection reference — so the
    premise rotted where only the migration proof could see it, and only against a store holding an
    ``int→int`` supersede, which the self-hosted one did not. The field's fixture supplied that shape,
    the proof failed, and the *reference* was the thing that was wrong: both the live path
    (:func:`yigraf.extract.build_graph`, which maintains these inline) and :mod:`yigraf.fold` already
    count every family. Making this agree with them keeps the proof strict over every family node
    rather than buying a passing test with a carve-out.

    A ``pending`` supersedes edge (of a human-attested node, int:memory-attestation) does NOT count:
    the target stays authoritative (not demoted) until a human resolves the conflict.
    """
    for node_id, attrs in graph.nodes(data=True):
        if attrs.get("family") not in _COUNTED_FAMILIES:
            continue
        attrs["superseded_in"] = sum(
            1 for _, _, a in graph.in_edges(node_id, data=True)
            if a.get("relation") == "supersedes" and not a.get("pending")
        )
        attrs["supersedes_out"] = sum(
            1 for _, _, a in graph.out_edges(node_id, data=True)
            if a.get("relation") == "supersedes" and not a.get("pending")
        )

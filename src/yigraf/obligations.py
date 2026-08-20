"""Unresolved graph obligations, edge-triggered for the **principal's** notice channel (int:obligation-notice).

The statusline already counts these (``⚠ 2 drift · ⚠ 1 conflict · ⚠ 1 stale``) and that count reliably
produces no action: a level-triggered warning that is present every refresh reads as furniture. This
module is the same three signals re-shaped into the thing a count can never be — a **work item with a
locator and a resolving verb**, announced *once*, on first appearance.

That distinction is the whole justification for a second human-facing surface, and it is what keeps
``mem:012`` intact rather than argued around. ``mem:012`` bans folding human-facing graph *stats* into
the agent's injection; it does not ban telling the principal what is unresolved. So:

- **counts** → statusline (level-triggered, ambient, no locator, no verb) — :mod:`yigraf.status`
- **obligations** → the Stop-hook notice (edge-triggered, names the anchor and the command) — here

Nothing here is pushed at the agent. The principal reads the notice and decides; told "go fix that",
the agent recovers the locators through ``yigraf context`` on the existing path (mem:bf00a1f5). The
agent's own doors — ``context``, ``SessionStart``, ``PostToolUse`` — are untouched by this module.

**Derived, never stored** (R6 / design-law #6): :func:`obligations` is a pure function of the graph,
recomputed on demand exactly like :mod:`yigraf.drift` and :mod:`yigraf.contradiction`, whose findings it
re-shapes without recomputing anything. The only state is the announce latch — volatile, machine-local,
gitignored ``.local/`` (mem:ea8dbd6a), never the graph.

**Online needs no separate path.** ``yigraf sync`` pulls the team's assertions into the local replica
and :func:`yigraf.extract._fold_replica` folds them onto the same base, so a teammate's arriving belief
is already in the graph this module reads — mem:059's "the only local↔online difference is a thin
substrate adapter" holding literally. What online *does* change is the right next step, so the
provenance actor (mem:063) rides the notice: superseding a belief that arrived over the log is
presumptuous, and reaffirming reasoning you never held is impossible, so a foreign operand routes to
``dispute`` (nominate, override nobody) instead. The network is never touched from here — a
"behind the remote log" probe costs a round-trip and belongs in ``yigraf sync``, not on every turn
boundary (mem:ea12f415).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from yigraf.contradiction import detect_conflicts
from yigraf.drift import compute_drift, is_surfaced, stale_completions

#: Obligation kinds, in the order they are announced — most-actionable first. ``conflict`` leads
#: because it is the only signal that structurally **requires** the principal: the agent can clear a
#: stale completion by re-linking and drift by re-verifying, but two same-tier live beliefs stay an
#: open question until a human decides (mem:95444dc — no scalar tiebreak). Ordering is load-bearing
#: against :data:`DEFAULT_MAX`: with stale first, a repo carrying 16 stale completions and one
#: conflict showed five stale lines and "… 12 more not shown", so the one item only this reader could
#: resolve was the one the notice dropped — measured on the field's own repo shape (feedback-v3 #1,
#: which reported the conflict as reaching "nothing"; it was computed, then crowded out).
KIND_ORDER = ("conflict", "stale", "drift")

#: Default cap on announced lines per turn. The host caps hook output at 10,000 chars, but the real
#: limit is attention: a notice longer than a few lines is skimmed, which is the failure this channel
#: exists to avoid. Overflow is summarized, never truncated silently (design law: no silent caps).
DEFAULT_MAX = 5


@dataclass(frozen=True)
class Obligation:
    """One unresolved item: what it is, where it is anchored, and the verb that clears it.

    ``key`` is **stable across rebuilds** — that is what makes the latch work. It is derived from the
    identity of the finding (source id + locator, or the sorted memory pair + anchor), never from a
    count, an index, or a cosine: a conflict whose similarity score drifts 0.86 → 0.87 is the *same*
    open question and must not re-announce.
    """

    kind: str  # "stale" | "conflict" | "drift"
    key: str  # stable identity — the latch is keyed on this
    subject: str  # the node whose obligation this is (task id, or the left memory id)
    locator: str  # the anchor the obligation is about (a sym:/file: locus, or the shared anchor)
    detail: str  # one clause of human-readable why
    verb: str  # the exact command that resolves it

    def render(self) -> str:
        """One notice line: ``kind  subject ← locator — detail`` then the command, indented."""
        return (f"  {self.kind:<8} {self.subject} ← {self.locator}\n"
                f"           {self.detail}\n"
                f"           → {self.verb}")


def _actors(graph: nx.DiGraph, node_id: str) -> list[str]:
    """The distinct actors that asserted ``node_id``, read from the folded provenance (mem:063).

    Empty for a locally-authored belief — a ``remember`` writes ``[{"source": "cli"}]`` with no actor,
    while :data:`~yigraf.onlinelog.REQUIRED_PROVENANCE_FIELDS` makes ``actor`` mandatory on anything
    that crossed the wire. So a non-empty result *is* the "this arrived over the shared log" signal,
    with no extra bookkeeping and no second source of truth.
    """
    attrs = graph.nodes.get(node_id) or {}
    out: list[str] = []
    for record in attrs.get("provenance") or []:
        actor = record.get("actor") if isinstance(record, dict) else None
        if actor and actor not in out:
            out.append(actor)
    return out


def _by(graph: nx.DiGraph, node_id: str) -> str:
    """`` (by alice)`` when ``node_id`` came from someone else's assertion, else ``""``."""
    actors = _actors(graph, node_id)
    return f" (by {', '.join(actors)})" if actors else ""


def _stale(item) -> Obligation:
    """A done task whose implementing symbol drifted (int:drift-as-stale).

    STALE is not *false*: the completion is re-verifiable, cleared by re-``link`` re-anchoring (or by
    reopening the task if the change regressed it) — never auto-flipped to ``todo``.
    """
    gone = item.kind == "hard"
    return Obligation(
        kind="stale", key=f"stale::{item.task_id}::{item.locator}",
        subject=item.task_id, locator=item.locator,
        detail=("implementing symbol is gone — the completion has no evidence"
                if gone else "implementing symbol changed after the task was marked done"),
        verb=(f"reopen the task, or re-link once re-verified: "
              f"yigraf link {item.task_id} <sym>" if gone
              else f"re-verify, then: yigraf link {item.task_id} {item.locator}"),
    )


def _conflict(c, graph: nx.DiGraph | None = None) -> Obligation:
    """Two live, unreconciled beliefs — nominated by a principal, or found by the cosine sweep (mem:062).

    The resolving verb is chosen by what the finding already knows, never by guessing the semantics:

    - a **pending** supersede needs a human endorsement (``attest``, mem:048). The agent cannot clear
      it, which is precisely why this channel is a notice and not a gate.
    - a **nominated** pair (a ``disputes`` verdict, :mod:`yigraf.resolution`) is already a named open
      question, so it only offers the two closing verdicts. It carries no cosine — a nomination is a
      judgment, not a measurement — and may share no anchor at all, so neither is asserted here.
    - a **swept** pair additionally offers ``dispute``: the sweep is index-derived and fails open to
      silence, so without nominating it the pair is visible only to whoever happens to hold an index.
    - a **same-tier** pair (no ``dominant``) is deliberately left open for the principal rather than
      tie-broken (mem:95444dc — no scalar tiebreak, no last-writer-wins).
    """
    close = f"yigraf reconcile {c.left} {c.right}"
    foreign = _actors(graph, c.left) or _actors(graph, c.right) if graph is not None else []
    if c.pending:
        detail = "a supersede between them is held pending a human decision"
        verb = f"yigraf attest {c.left}  (or {c.right}) — only a principal clears a pending supersede"
    else:
        if c.dominant:
            other = c.right if c.dominant == c.left else c.left
            side = f"provenance prefers {c.dominant}"
            loser = other
        else:
            side = "same provenance tier — your call"
            loser = "<loser>"
        if getattr(c, "nominated", False):
            detail = f"nominated as contradictory by a principal; {side}"
            verb = f"{close}   — or: yigraf supersede {loser} \"<the surviving claim>\""
        elif foreign:
            # One side arrived over the shared log. Superseding someone else's belief unilaterally is
            # the wrong default — `dispute` nominates the pair without overriding anyone, which is
            # exactly the "both land, a principal decides" shape int:concurrent-write-model asks for.
            detail = f"co-anchored and unreconciled (cos {c.cosine:.2f}); {side}"
            verb = (f"yigraf dispute {c.left} {c.right} --why \"…\"   — or, if it's clearly compatible: "
                    f"{close}. Don't supersede someone else's belief without asking.")
        else:
            detail = f"co-anchored and unreconciled (cos {c.cosine:.2f}); {side}"
            verb = (f"{close}   — or: yigraf supersede {loser} \"<the surviving claim>\""
                    f"   — or: yigraf dispute {c.left} {c.right} to make it durable")
    if graph is not None:
        subject = f"{c.left}{_by(graph, c.left)} ⟂ {c.right}{_by(graph, c.right)}"
    else:
        subject = f"{c.left} ⟂ {c.right}"
    # The anchor is part of the key but may be empty on a nomination (a nominated pair need share no
    # `concerns` target); left+right already make the key unique, so an empty anchor is harmless.
    # Attribution is deliberately NOT in the key: the same conflict gaining a second asserter is the
    # same open question, and must not re-announce.
    return Obligation(kind="conflict", key=f"conflict::{c.anchor}::{c.left}::{c.right}",
                      subject=subject,
                      locator=c.anchor or "(no shared anchor)", detail=detail, verb=verb)


def _drift(item, graph: nx.DiGraph | None = None) -> Obligation:
    """Surfaced re-verify drift on a live link — the signal already in the agent's channel.

    Carried here too because the principal's view should be complete: the agent is shown this at the
    edit hook, but only for the locus it happened to touch, and only if it was still in-session.

    Attribution matters most here: a teammate's decision drifting because *you* edited the code it
    governs is not yours to reaffirm or retract — you can't re-verify reasoning you never held. So a
    foreign source routes to asking rather than to ``reaffirm``.
    """
    foreign = _by(graph, item.task_id) if graph is not None else ""
    if foreign:
        verb = (f"their belief, your edit — ask before you clear it, or nominate it: "
                f"yigraf dispute {item.task_id} <yours> --why \"…\"")
    else:
        verb = {
            "implements": f"re-verify, then: yigraf link {item.task_id} {item.locator}",
            "concerns": f"yigraf reaffirm {item.task_id}   — or supersede it if your mind changed",
            "grounded_by": f"yigraf reaffirm {item.task_id} --grounding empirical   — or downgrade to inferred",
        }.get(item.relation, f"yigraf reaffirm {item.task_id}")
    return Obligation(
        kind="drift", key=f"drift::{item.relation}::{item.task_id}::{item.locator}",
        subject=f"{item.task_id}{foreign}", locator=item.locator,
        detail=(item.detail or "anchor no longer matches") + f" ({item.relation})",
        verb=verb,
    )


def obligations(graph: nx.DiGraph, root: Path, config: dict, index=None) -> list[Obligation]:
    """Every unresolved obligation in ``graph``, ordered by :data:`KIND_ORDER`.

    Pure and additive: it re-shapes what :func:`~yigraf.drift.stale_completions`,
    :func:`~yigraf.contradiction.detect_conflicts` and :func:`~yigraf.drift.compute_drift` already
    return — no new detection, no new thresholds. ``index`` is the optional pre-loaded embedding index
    (a caller holding one passes it through so the conflict sweep doesn't re-read it); absent an index
    the *cosine sweep* contributes nothing (silence over noise, design law #4) — but a nominated
    dispute still surfaces, because a nomination is an asserted verdict rather than a measurement and
    rides the log index-free (int:team-reconciliation). So "no embeddings" means no *swept* conflicts,
    never no conflicts at all.
    """
    found: list[Obligation] = [_stale(it) for it in stale_completions(graph)]
    found += [_conflict(c, graph) for c in detect_conflicts(graph, root, config, index=index)]
    found += [_drift(it, graph) for it in compute_drift(graph)
              if it.kind in ("soft", "hard") and is_surfaced(graph, it)]
    order = {k: i for i, k in enumerate(KIND_ORDER)}
    found.sort(key=lambda o: (order.get(o.kind, len(order)), o.key))
    return found


# --------------------------------------------------------------------------------------------------
# The announce latch — what makes this edge-triggered (mem:ea8dbd6a)
# --------------------------------------------------------------------------------------------------


def latch_path(root: Path) -> Path:
    """The gitignored, machine-local announce latch (``yigraf/.local/announced.json``).

    Volatile derived state, so it lives beside the telemetry sidecar and the materialized view and is
    never written into the graph — the same rule that keeps ``usage``/``last_seen``/``survival`` out of
    the projection (design-law #6).
    """
    return Path(root) / "yigraf" / ".local" / "announced.json"


def _load_latch(root: Path) -> dict[str, dict]:
    """``{session_id: {"fp": <input fingerprint>, "keys": [announced keys]}}``.

    ``{}`` when absent or corrupt — fail-open in the safe direction: at worst we re-announce an open
    obligation once (recoverable), where going silent on a real one is not. Entries of the wrong shape
    are dropped individually rather than poisoning the whole latch.
    """
    path = latch_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    clean: dict[str, dict] = {}
    for session, entry in data.items():
        if isinstance(entry, dict) and isinstance(entry.get("keys"), list):
            clean[session] = {"fp": entry.get("fp"), "keys": list(entry["keys"])}
    return clean


def is_unchanged(root: Path, session_id: str, fingerprint: str) -> bool:
    """The hook's fast path: has this session already been announced against exactly these inputs?

    Obligations are a pure function of the graph, and the graph is a pure function of the fingerprinted
    inputs — so an unchanged fingerprint means no obligation can have appeared or cleared, and the
    caller can return silence without loading the view or the embedding index. That matters because
    this runs on **every** turn: the stat-only fingerprint is cheap, a full SQLite load plus an index
    read is not. A session with no recorded fingerprint (its first turn) always falls through.
    """
    entry = _load_latch(root).get(session_id)
    return bool(entry) and entry.get("fp") == fingerprint


#: How many sessions of announce history to retain. The latch is per-session (see
#: :func:`new_obligations`), so without a bound it would grow forever on a long-lived repo.
_MAX_SESSIONS = 20


def _save_latch(root: Path, latch: dict[str, dict], session_id: str) -> None:
    """Persist the latch, keeping ``session_id`` and the most recent sessions. Best-effort: a failed
    write means one duplicate announcement later, never a crash in a hook (design law #5)."""
    if len(latch) > _MAX_SESSIONS:
        keep = [session_id] + [k for k in reversed(list(latch)) if k != session_id]
        latch = {k: latch[k] for k in keep[:_MAX_SESSIONS] if k in latch}
    try:
        path = latch_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(latch, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass


def new_obligations(root: Path, current: list[Obligation], session_id: str,
                    fingerprint: str | None = None) -> list[Obligation]:
    """The obligations in ``current`` not yet announced to ``session_id``, marking them announced.

    **Session-keyed on purpose** (mem:ea8dbd6a). A global latch would stay silent after ``/clear`` —
    but ``/clear`` wipes the *context*, not the obligation, so a still-open item is legitimately new to
    a fresh session and must be re-announced. That is the case this channel exists for.

    Resolution is **silent**: a cleared obligation simply stops appearing. Announcing "resolved!" would
    be a stat, and stats belong on the statusline (mem:012). Keys that no longer exist are dropped from
    the session's set, so an obligation that is resolved and later *recurs* announces again — a
    genuinely new event.

    ``fingerprint`` is recorded (not consulted) so the next turn's :func:`is_unchanged` fast path can
    skip the whole computation while the inputs hold still.
    """
    latch = _load_latch(root)
    announced = set(latch.get(session_id, {}).get("keys", []))
    live = {o.key for o in current}
    fresh = [o for o in current if o.key not in announced]
    latch[session_id] = {"fp": fingerprint,
                         "keys": sorted((announced & live) | {o.key for o in fresh})}
    _save_latch(root, latch, session_id)
    return fresh


def render_notice(fresh: list[Obligation], total: int, max_lines: int = DEFAULT_MAX) -> str:
    """The principal-facing notice block for ``fresh``, capped at ``max_lines`` items.

    Overflow is *stated*, never silently dropped: a notice that quietly shows 5 of 12 would read as
    "12 is all there is". The trailing count of still-open obligations gives the principal the shape of
    the backlog without turning the notice itself into the statusline's count.
    """
    shown = fresh[:max_lines]
    head = f"[yigraf] {len(fresh)} new obligation{'s' if len(fresh) != 1 else ''}"
    lines = [head] + [o.render() for o in shown]
    if len(fresh) > len(shown):
        lines.append(f"  … {len(fresh) - len(shown)} more not shown")
    if total > len(fresh):
        lines.append(f"  ({total} open in total — yigraf status)")
    return "\n".join(lines)

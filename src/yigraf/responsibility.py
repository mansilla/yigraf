"""Who owes a conflict's resolution — the git-shaped social contract, read off the log's order.

int:team-reconciliation task #6. :mod:`yigraf.contradiction` says *that* two beliefs conflict and
:mod:`yigraf.resolution` gives a principal the verbs to close it, but nothing says **whose turn it
is**. Without that a conflict is addressed to everyone, which is to say to nobody: it waits until
someone happens to run ``yigraf status``, and the person most likely to run it is the one who already
knows about it.

**The rule is git's, and it is already true — it just wasn't said out loud.** Whoever pushes second
merges. A belief's ``seq`` is the moment it became everyone's problem, so of two conflicting beliefs
the one with the higher ``seq`` was written into a world that already contained the other, and its
author owes the reconcile. That is *derived*, not stored: no assignment field, no ownership assertion,
nothing to keep in step — the log's existing order already carries it.

Note what ``seq`` deliberately measures: **push order, not authoring order.** Write a belief on Monday
offline and push it Friday and you are the later writer even though you typed first — exactly as git
makes you rebase, and for the same reason: the shared history is what everyone else built on.

**Identity is recovered, never claimed.** ``cli._for_the_wire`` refuses to set ``actor`` because a
client's claim about who it is means nothing; the server stamps it from the authenticated principal. So
this module recovers it the same way — by reading the actor back off an event whose assertion *this
workspace authors locally* (:func:`own_actor`). Nothing new crosses the wire, and a workspace that has
pushed nothing simply has no identity to match, which is correct: it cannot own a belief it never wrote.

Pure and derived, like every other finding here: it takes the conflicts, the log's events, and the
local assertion ids, and returns who owes what. It reads no files, opens no sockets, and stores nothing.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from yigraf.contradiction import Conflict

#: What an event's ``actor`` reads as when the log has none — an unsigned or pre-auth event. Named
#: rather than blank so a notice never renders an empty owner, and never invents a plausible one.
UNATTRIBUTED = "unattributed"


@dataclass(frozen=True)
class Landing:
    """When a belief entered the shared log, and who the *server* said put it there."""

    seq: int
    actor: str


def landings(events: Iterable[Any]) -> dict[str, Landing]:
    """Each assertion's FIRST landing in the log, keyed by assertion id.

    First, not latest: an identical-content re-assertion by a second writer is a new event the read path
    unions (mem:060), and someone else independently rediscovering a belief must not reset the age of the
    one that has been standing since. The landing is when the claim entered the shared history.
    """
    out: dict[str, Landing] = {}
    for event in sorted(events, key=lambda e: e.seq):
        if event.id in out:
            continue
        actor = (event.provenance or {}).get("actor") or UNATTRIBUTED
        out[event.id] = Landing(seq=event.seq, actor=str(actor))
    return out


def own_actor(events: Iterable[Any], local_ids: set[str]) -> str | None:
    """The actor the server stamps on *my* appends — learned from the log rather than claimed.

    A workspace has no trustworthy name for itself: the token names it to the server, and the server
    decides. But every assertion this workspace authored and pushed came back stamped, so the identity
    is already in the replica — recoverable by finding an event whose assertion still has a local
    artifact. The newest such event wins, so a re-issued token or a renamed account converges on the
    current name instead of pinning the first one ever seen.

    ``None`` when nothing local has been pushed yet. That is not a failure: a workspace that has written
    nothing to the shared log cannot be the later writer of anything in it, so the caller reports owners
    by name and claims none of them.
    """
    for event in sorted(events, key=lambda e: e.seq, reverse=True):
        if event.id in local_ids:
            actor = (event.provenance or {}).get("actor")
            if actor:
                return str(actor)
    return None


@dataclass(frozen=True)
class Owed:
    """One open conflict with a name on it: who wrote the later belief, and therefore owes the verdict."""

    conflict: Conflict
    owner: str  # the actor the log stamped on the later belief
    later: str  # the belief that landed second — the one that owes
    later_seq: int
    earlier: str  # the belief it landed on top of
    earlier_seq: int
    mine: bool  # whether ``owner`` is this workspace's own recovered identity

    def render(self) -> str:
        """Two lines: the pair and why it is this writer's, then the verbs that close it."""
        c = self.conflict
        where = f" ← {c.anchor}" if c.anchor else ""
        who = "you wrote" if self.mine else f"{self.owner} wrote"
        return (f"  {c.left} ⟂ {c.right}{where}\n"
                f"    {who} {self.later}, which landed on top of {self.earlier} "
                f"(log seq {self.later_seq} > {self.earlier_seq}) — the later writer resolves\n"
                f"    → yigraf reconcile {c.left} {c.right}   — or: "
                f"yigraf supersede <loser> \"<the surviving claim>\"")


def assign(conflicts: Iterable[Conflict], landed: dict[str, Landing], me: str | None) -> list[Owed]:
    """Attach responsibility to every conflict whose two beliefs the log can order.

    A conflict with an operand that is not in the log — a purely local pair, or a replica that hasn't
    pulled the other side yet — is skipped rather than guessed at. It is still an open conflict on the
    status surface; it just has no *shared* order to derive a turn from, and inventing one (by file
    mtime, by id) would be the arbitrary tiebreak mem:95444dc rules out for exactly this reason.
    """
    out: list[Owed] = []
    for conflict in conflicts:
        left, right = landed.get(conflict.left), landed.get(conflict.right)
        if left is None or right is None:
            continue
        (later_id, later), (earlier_id, earlier) = (
            ((conflict.right, right), (conflict.left, left)) if right.seq > left.seq
            else ((conflict.left, left), (conflict.right, right)))
        out.append(Owed(conflict=conflict, owner=later.actor,
                        later=later_id, later_seq=later.seq,
                        earlier=earlier_id, earlier_seq=earlier.seq,
                        mine=me is not None and later.actor == me))
    return out


#: Owed conflicts rendered in full before the rest is summarized. Same reasoning as the obligation
#: notice's cap: this fires at the end of a command the principal is already reading, and a block long
#: enough to skim past defeats the point of naming a turn at all.
DEFAULT_MAX = 3


def render_notice(owed: list[Owed], max_lines: int = DEFAULT_MAX) -> str:
    """The post-sync notice: what you now own in full, what others own as one line. ``""`` if nothing.

    Silence when you owe nothing and no one else does either (design law #4) — a sync that surfaced no
    turn should say nothing about turns. Someone *else's* conflicts get a single summary line rather
    than silence, because knowing a disagreement is live and being handled is worth one line, and
    knowing it is live and unowned is worth more: an ``unattributed`` owner reads as exactly that.
    """
    mine = [o for o in owed if o.mine]
    theirs = [o for o in owed if not o.mine]
    if not mine and not theirs:
        return ""
    lines: list[str] = []
    if mine:
        lines.append(f"⚠ You now own {len(mine)} open conflict{'s' if len(mine) != 1 else ''} — "
                     f"your belief landed later, so the resolution is yours:")
        lines += [o.render() for o in mine[:max_lines]]
        if len(mine) > max_lines:  # stated, never silently dropped
            lines.append(f"  … {len(mine) - max_lines} more — yigraf status")
    if theirs:
        who = ", ".join(f"{actor} ({n})" for actor, n in sorted(Counter(o.owner for o in theirs).items()))
        lines.append(f"{len(theirs)} other open conflict{'s' if len(theirs) != 1 else ''} — "
                     f"owed by the later writer: {who}")
    return "\n".join(lines)

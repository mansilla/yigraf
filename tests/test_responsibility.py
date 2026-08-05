"""Whose turn a conflict is — the later writer owes the resolution (int:team-reconciliation task #6).

Pure unit coverage of :mod:`yigraf.responsibility`: the rule is derived from the log's existing order,
so these tests need nothing but events and conflicts. The end-to-end proof — two workspaces, a real
sync, the notice reaching the writer who landed second — is in ``tests/test_sync_cli.py``.
"""
from types import SimpleNamespace

from yigraf.contradiction import Conflict
from yigraf.responsibility import UNATTRIBUTED, assign, landings, own_actor, render_notice

ANCHOR = "sym:app.py#greet"


def _event(seq: int, node_id: str, actor: str | None = "alice@example.com"):
    return SimpleNamespace(seq=seq, id=node_id, provenance={"actor": actor} if actor else {})


def _conflict(left: str = "mem:a", right: str = "mem:b", **kw) -> Conflict:
    return Conflict(anchor=ANCHOR, left=left, right=right, cosine=0.9, **kw)


def test_landing_is_when_the_claim_entered_the_shared_history():
    """First landing, not latest: someone else independently rediscovering a belief (mem:060) unions
    provenance onto one that has been standing, and must not reset whose turn it is."""
    landed = landings([_event(1, "mem:a"), _event(2, "mem:b", "bob@example.com"),
                       _event(3, "mem:a", "carol@example.com")])
    assert landed["mem:a"].seq == 1 and landed["mem:a"].actor == "alice@example.com"
    assert landed["mem:b"].seq == 2


def test_an_unsigned_event_has_a_named_owner_not_a_blank_one():
    assert landings([_event(1, "mem:a", None)])["mem:a"].actor == UNATTRIBUTED


def test_own_actor_is_recovered_from_the_log_never_claimed():
    """A client never sets ``actor`` (``cli._for_the_wire``) — the server stamps it. So identity is read
    back off an event whose assertion this workspace still authors locally."""
    events = [_event(1, "mem:theirs", "bob@example.com"), _event(2, "mem:mine", "alice@example.com")]
    assert own_actor(events, {"mem:mine"}) == "alice@example.com"


def test_own_actor_takes_the_newest_stamp():
    """A re-issued token or a renamed account converges on the current name, not the first ever seen."""
    events = [_event(1, "mem:mine", "alice@old.example"), _event(2, "mem:also", "alice@new.example")]
    assert own_actor(events, {"mem:mine", "mem:also"}) == "alice@new.example"


def test_a_workspace_that_pushed_nothing_has_no_identity():
    """And needs none: it cannot be the later writer of a belief it never wrote."""
    assert own_actor([_event(1, "mem:theirs", "bob@example.com")], set()) is None


def test_the_later_belief_carries_the_obligation():
    landed = landings([_event(1, "mem:a", "alice@example.com"), _event(2, "mem:b", "bob@example.com")])
    owed = assign([_conflict()], landed, me="bob@example.com")
    assert len(owed) == 1
    assert owed[0].owner == "bob@example.com" and owed[0].later == "mem:b" and owed[0].earlier == "mem:a"
    assert owed[0].mine is True


def test_operand_order_does_not_decide_the_turn():
    """The finding sorts its operands for stability; the log decides who owes. A conflict whose *left*
    landed second must still name that side's author."""
    landed = landings([_event(1, "mem:b", "bob@example.com"), _event(2, "mem:a", "alice@example.com")])
    owed = assign([_conflict()], landed, me="bob@example.com")
    assert owed[0].later == "mem:a" and owed[0].owner == "alice@example.com" and owed[0].mine is False


def test_a_pair_the_log_cannot_order_is_skipped_not_guessed():
    """A purely local pair, or a replica that hasn't pulled the other side yet, has no *shared* order.
    Inventing one (by mtime, by id) would be the arbitrary tiebreak mem:95444dc rules out."""
    landed = landings([_event(1, "mem:a")])
    assert assign([_conflict()], landed, me="alice@example.com") == []


def test_the_notice_is_silent_when_no_turn_was_surfaced():
    assert render_notice([]) == ""


def test_yours_is_named_in_full_and_theirs_summarized():
    landed = landings([_event(1, "mem:a", "alice@example.com"), _event(2, "mem:b", "bob@example.com"),
                       _event(3, "mem:c", "alice@example.com"), _event(4, "mem:d", "carol@example.com")])
    owed = assign([_conflict(), _conflict("mem:c", "mem:d")], landed, me="bob@example.com")
    notice = render_notice(owed)
    assert "You now own 1 open conflict" in notice
    assert "you wrote mem:b" in notice and "log seq 2 > 1" in notice
    assert "yigraf reconcile mem:a mem:b" in notice and ANCHOR in notice
    assert "1 other open conflict — owed by the later writer: carol@example.com (1)" in notice
    assert "mem:c ⟂ mem:d" not in notice, "someone else's conflicts cost one line, not a block"


def test_overflow_is_stated_never_silently_dropped():
    events = [_event(i, f"mem:{i}", "bob@example.com") for i in range(1, 9)]
    conflicts = [_conflict(f"mem:{i}", f"mem:{i + 1}") for i in range(1, 8, 2)]
    notice = render_notice(assign(conflicts, landings(events), me="bob@example.com"), max_lines=2)
    assert "You now own 4 open conflicts" in notice and "… 2 more — yigraf status" in notice

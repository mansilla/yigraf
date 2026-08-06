"""Client sync loop — done-tests for the online replica model (int:yigraf-online-v1).

Proven offline against :class:`~yigraf.sync.LoopbackRemote` (an in-process server-side ``OnlineLog`` —
the stand-in for the hosted API). The real HTTP client is a thin adapter over the same three-call
:class:`~yigraf.sync.RemoteClient` port, so these tests pin the client behavior the network deployment
relies on (mem:059).

The model is git-shaped and conflict-free: the remote authors ORDER (seq + Merkle chain); clients hold
a SQLite replica and reconcile by head hash; merging is a commutative set-union by ``event_key`` (the
fold re-derives belief, so no last-writer-wins). The capstone is convergence — independent writers'
replicas fold to the identical graph.
"""
import io

import pytest

from yigraf.fold import fold
from yigraf.graph import to_node_link
from yigraf.log import Assertion
from yigraf.onlinelog import (
    IngestRejected,
    OnlineLog,
    SqliteAssertionStore,
    StoredEvent,
    verify_provenance,
)
from yigraf.sync import (
    GENESIS_HASH,
    HttpRemote,
    LoopbackRemote,
    RemoteClient,
    RemoteHead,
    RemoteUnavailable,
    SyncError,
    _verify_delta,
    push_assertion,
    replica_log,
    sync,
)

SERVER_KEY = b"server-signing-key"


def _prov(actor="alice"):
    return {"actor": actor, "session": "s1", "model": "opus-4.8", "commit_sha": "abc",
            "ts": "2026-07-15T00:00:00Z", "source": "cli"}


def _mem(id_, *, actor="alice", parents=(), label=None):
    return Assertion(
        id=id_, kind="memory",
        body={"family": "memory", "attrs": {"kind": "decision", "status": "active",
                                            "label": label or id_}, "edges": []},
        parents=tuple(parents), provenance=[_prov(actor)])


def _remote(project="proj"):
    """A fresh loopback remote (server side) + its backing store."""
    server = SqliteAssertionStore()
    return LoopbackRemote(OnlineLog(server, project, signer_key=SERVER_KEY)), server


# ============================================================================================
# The port + reconcile-by-head-hash
# ============================================================================================


def test_loopback_satisfies_the_remote_port():
    remote, _ = _remote()
    assert isinstance(remote, RemoteClient)


def test_sync_is_a_noop_when_cursor_equals_head():
    remote, _ = _remote()
    client = SqliteAssertionStore()
    first = sync(client, remote, "proj")  # empty remote, empty cursor
    assert first.already_current and first.pulled == 0
    push_assertion(client, remote, "proj", _mem("mem:1"))
    sync(client, remote, "proj")
    again = sync(client, remote, "proj")  # cursor now == head ⇒ cheap no-op
    assert again.already_current and again.pulled == 0


def test_sync_pulls_the_delta_and_advances_the_cursor():
    remote, server = _remote()
    writer = LoopbackRemote(OnlineLog(server, "proj", signer_key=SERVER_KEY))
    writer.push("proj", [_mem("mem:1"), _mem("mem:2", parents=("mem:1",))])

    client = SqliteAssertionStore()
    result = sync(client, remote, "proj")
    assert result.pulled == 2 and not result.already_current
    assert client.get_cursor("proj") == (result.head.seq, result.head.head_hash)
    # A second sync after a further remote append pulls ONLY the new event (delta, not full log).
    writer.push("proj", [_mem("mem:3")])
    assert sync(client, remote, "proj").pulled == 1


def test_resync_is_idempotent():
    remote, _ = _remote()
    push_assertion_client = SqliteAssertionStore()
    push_assertion(push_assertion_client, remote, "proj", _mem("mem:1"))
    client = SqliteAssertionStore()
    sync(client, remote, "proj")
    before = to_node_link(fold(replica_log(client, "proj")))
    sync(client, remote, "proj")  # re-run
    sync(client, remote, "proj")  # and again
    assert to_node_link(fold(replica_log(client, "proj"))) == before  # no duplication, stable


# ============================================================================================
# Write-through + server-authored provenance
# ============================================================================================


def test_push_is_write_through_visible_before_sync():
    """A local authoring write appends to the remote and folds the authoritative event into the replica
    immediately — a subsequent read sees it without waiting for a pull."""
    remote, _ = _remote()
    client = SqliteAssertionStore()
    push_assertion(client, remote, "proj", _mem("mem:1"))
    ids = [a.id for a in replica_log(client, "proj").iter_assertions_in_causal_order()]
    assert ids == ["mem:1"]  # visible in the replica immediately, before any sync/pull


def test_replica_carries_server_signed_provenance():
    """The client never signs — it stores the server's authoritative signed provenance verbatim, so it
    stays verifiable against the server key (task #8 authority survives the round-trip)."""
    remote, _ = _remote()
    client = SqliteAssertionStore()
    authoritative = push_assertion(client, remote, "proj", _mem("mem:1"))
    assert verify_provenance(authoritative.provenance, SERVER_KEY)
    replica_event = next(e for e in client.iter_events("proj") if e.id == "mem:1")
    assert replica_event.provenance == authoritative.provenance
    assert verify_provenance(replica_event.provenance, SERVER_KEY)


def test_push_propagates_ingest_rejection():
    """The server's synchronous structural/causal gate rejects a bad write; the client sees it (never a
    silent drop) and the replica stays clean."""
    remote, _ = _remote()
    client = SqliteAssertionStore()
    orphan = _mem("mem:2", parents=("mem:missing",))  # dangling causal parent
    with pytest.raises(IngestRejected):
        push_assertion(client, remote, "proj", orphan)
    assert client.iter_events("proj") == []


# ============================================================================================
# Delta chain verification (the client independently re-derives the Merkle links)
# ============================================================================================


def test_verify_delta_accepts_a_wellformed_segment():
    remote, server = _remote()
    LoopbackRemote(OnlineLog(server, "proj", signer_key=SERVER_KEY)).push(
        "proj", [_mem("mem:1"), _mem("mem:2", parents=("mem:1",))])
    events = remote.pull("proj", 0)
    _verify_delta(events, GENESIS_HASH, remote.head("proj"))  # does not raise


def test_verify_delta_rejects_a_dropped_event():
    remote, server = _remote()
    LoopbackRemote(OnlineLog(server, "proj", signer_key=SERVER_KEY)).push(
        "proj", [_mem("mem:1"), _mem("mem:2", parents=("mem:1",))])
    full = remote.pull("proj", 0)
    head = remote.head("proj")
    with pytest.raises(SyncError):
        _verify_delta(full[1:], GENESIS_HASH, head)  # first event dropped ⇒ chain breaks


def test_verify_delta_rejects_head_mismatch():
    remote, server = _remote()
    LoopbackRemote(OnlineLog(server, "proj", signer_key=SERVER_KEY)).push("proj", [_mem("mem:1")])
    events = remote.pull("proj", 0)
    with pytest.raises(SyncError):
        _verify_delta(events, GENESIS_HASH, RemoteHead(seq=1, head_hash="deadbeef" * 8))


def test_empty_delta_must_match_head():
    with pytest.raises(SyncError):
        _verify_delta([], GENESIS_HASH, RemoteHead(seq=5, head_hash="abc"))


# ============================================================================================
# Capstone — independent writers' replicas converge to the identical graph
# ============================================================================================


def test_independent_writers_converge():
    """Two clients writing through the shared remote, then syncing, fold to the byte-identical graph —
    conflict-free set-union (mem:065017c0), the whole point of the content-addressed log."""
    remote, _ = _remote()
    alice, bob = SqliteAssertionStore(), SqliteAssertionStore()

    push_assertion(alice, remote, "proj", _mem("mem:1", actor="alice"))
    push_assertion(bob, remote, "proj", _mem("mem:2", actor="bob"))
    push_assertion(alice, remote, "proj", _mem("mem:3", actor="alice", parents=("mem:1",)))

    sync(alice, remote, "proj")
    sync(bob, remote, "proj")

    ga = to_node_link(fold(replica_log(alice, "proj")))
    gb = to_node_link(fold(replica_log(bob, "proj")))
    assert ga == gb
    assert {n["id"] for n in ga["nodes"]} == {"mem:1", "mem:2", "mem:3"}


def test_sync_order_is_commutative():
    """Syncing before vs after another writer's append converges identically — order-independence is
    what makes the replica model safe under concurrency (mem:98d5a556/065017c0)."""
    remote, _ = _remote()
    early, late = SqliteAssertionStore(), SqliteAssertionStore()

    push_assertion(early, remote, "proj", _mem("mem:1"))
    sync(early, remote, "proj")            # early syncs, sees 1
    push_assertion(late, remote, "proj", _mem("mem:2"))
    sync(early, remote, "proj")            # early syncs again, now sees 2
    sync(late, remote, "proj")             # late syncs once, sees both

    assert to_node_link(fold(replica_log(early, "proj"))) == \
           to_node_link(fold(replica_log(late, "proj")))


def test_replica_mirrors_the_remote_log_exactly():
    """After sync, folding the replica equals folding the server's own log — the replica is a faithful
    projection of the authority, so ``context``/``status`` over it answer as the server would."""
    remote, server = _remote()
    LoopbackRemote(OnlineLog(server, "proj", signer_key=SERVER_KEY)).push(
        "proj", [_mem("mem:1"), _mem("mem:2", parents=("mem:1",))])
    client = SqliteAssertionStore()
    sync(client, remote, "proj")
    assert to_node_link(fold(replica_log(client, "proj"))) == \
           to_node_link(fold(OnlineLog(server, "proj", signer_key=SERVER_KEY)))


# ============================================================================================
# Transport failure — the third failure mode, and the only recoverable one
# ============================================================================================


class _Urlopen:
    """A stand-in for ``urllib.request.urlopen`` that raises whatever it was handed."""

    def __init__(self, error):
        self.error = error

    def __call__(self, req, timeout=None):
        raise self.error


def _http_error(code, body=b"{}", reason="Boom"):
    import urllib.error
    return urllib.error.HTTPError("https://api.example/x", code, reason, {}, io.BytesIO(body))


def _request(monkeypatch, error):
    """Drive one ``HttpRemote`` call with ``urlopen`` raising ``error``."""
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _Urlopen(error))
    return HttpRemote("https://api.example", "tok").head("proj")


def test_an_unreachable_remote_raises_remote_unavailable(monkeypatch):
    """Offline/DNS/refused surfaces as the recoverable signal, not a raw urllib traceback — the whole
    point is that the caller can tell 'try again later' from 'this will never work'."""
    import urllib.error
    with pytest.raises(RemoteUnavailable) as exc:
        _request(monkeypatch, urllib.error.URLError("Name or service not known"))
    assert "unreachable" in str(exc.value)


def test_a_timeout_is_transport_not_a_hard_error(monkeypatch):
    with pytest.raises(RemoteUnavailable):
        _request(monkeypatch, TimeoutError("timed out"))


def test_a_5xx_is_transient_but_a_4xx_is_not(monkeypatch):
    """A server that is up but can't serve is weather; a bad token fails identically forever, so it
    must NOT read as 'retry later' (RemoteUnavailable's docstring)."""
    import urllib.error
    with pytest.raises(RemoteUnavailable):
        _request(monkeypatch, _http_error(503))
    with pytest.raises(RemoteUnavailable):  # rate-limited is the one 4xx that IS transient
        _request(monkeypatch, _http_error(429))
    with pytest.raises(urllib.error.HTTPError):
        _request(monkeypatch, _http_error(401))


def test_a_5xx_with_a_non_json_body_still_classifies(monkeypatch):
    """A gateway answering HTML must not turn into a JSONDecodeError from the detail parse."""
    with pytest.raises(RemoteUnavailable):
        _request(monkeypatch, _http_error(502, body=b"<html>bad gateway</html>"))


def test_an_ingest_rejection_still_wins_over_the_transient_classifier(monkeypatch):
    """422 + a rejection detail stays permanent (design law #1: a rejected write teaches the fix)."""
    body = b'{"detail": {"rejected": ["unknown causal parent mem:9"]}}'
    with pytest.raises(IngestRejected) as exc:
        _request(monkeypatch, _http_error(422, body=body))
    assert exc.value.problems == ["unknown causal parent mem:9"]


def test_a_string_valued_rejection_is_not_shredded_into_characters():
    """``IngestRejected`` takes a LIST (the server sends ``exc.problems``); a variant server sending a
    bare string would otherwise be iterated per-character into 'u; n; k; n; o; w; n'."""
    body = b'{"detail": {"rejected": "unknown causal parent mem:9"}}'
    with pytest.raises(IngestRejected) as exc:
        with pytest.MonkeyPatch.context() as mp:
            import urllib.request
            mp.setattr(urllib.request, "urlopen", _Urlopen(_http_error(422, body=body)))
            HttpRemote("https://api.example", "tok").head("proj")
    assert exc.value.problems == ["unknown causal parent mem:9"]


def test_an_unpushed_assertion_stays_in_the_next_runs_push_set():
    """The retry invariant behind 'no queue needed': ``yigraf sync`` derives its push set as the file
    log minus the replica's known ids, so a push that never landed is still outgoing next run — and a
    push that DID land drops out, so the retry never duplicates (push_assertion's docstring)."""
    remote, _ = _remote()
    client = SqliteAssertionStore()
    local = [_mem("mem:1"), _mem("mem:2")]  # what FileLog would yield from the committed artifacts

    push_assertion(client, remote, "proj", local[0])          # lands
    outgoing = [a for a in local if a.id not in client.known_ids("proj")]
    assert [a.id for a in outgoing] == ["mem:2"]              # the un-pushed one is still queued

    push_assertion(client, remote, "proj", local[1])          # the next run sends it
    assert [a for a in local if a.id not in client.known_ids("proj")] == []


def test_a_real_repos_revisions_survive_the_prefix_closed_ingest_check(tmp_path):
    """End-to-end over the LOOPBACK SERVER: a whole repo's assertions push, an edit re-pushes, and the
    server accepts both.

    The half of the revision change that only a server can refuse. Causal parents must name an
    *assertion*, so a memory that serves ``int:foo`` now parents on ``int:foo@<rev>`` rather than the
    bare locator — and ``validate_ingest`` demands every parent already be in the log (prefix-closed).
    If ``_resolve_parents`` failed to rewrite a locator, or causal order stopped landing a revision
    before its dependents, this is where it surfaces: as ``IngestRejected``, not a wrong graph.
    """
    from typer.testing import CliRunner

    from yigraf.cli import _for_the_wire, app
    from yigraf.filelog import FileLog

    runner = CliRunner()
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "app.py").write_text("def greet():\n    return 'hi'\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "greeting", "--statement", "yigraf SHALL greet",
                               "--repo", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["plan", "greet", "--title", "Greet", "--task", "write greet()",
                               "--repo", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["remember", "greet returns a constant", "--why", "it is a stub",
                               "--serves", "int:greeting", "--concerns", "sym:app.py#greet",
                               "--repo", str(tmp_path)]).exit_code == 0

    remote, _ = _remote()
    client = SqliteAssertionStore()

    def _push_everything_outgoing() -> list[str]:
        local = list(FileLog(tmp_path).iter_assertions_in_causal_order())
        outgoing = [a for a in local if a.id not in client.known_ids("proj")]
        for assertion in outgoing:  # in causal order, so parents land first
            # Through the same envelope-completion the CLI uses, then `actor` — which the real server
            # stamps from the authenticated principal, and LoopbackRemote (a bare OnlineLog) does not.
            # Provenance is not part of the id, so none of this changes what is pushed.
            wire = _for_the_wire(assertion, tmp_path, "sess")
            wire.provenance[0]["actor"] = "alice"
            push_assertion(client, remote, "proj", wire)
        return [a.id for a in outgoing]

    first = _push_everything_outgoing()
    assert any(i.startswith("int:greeting@") for i in first)
    assert any(i.startswith("task:greet/1@") for i in first)
    assert _push_everything_outgoing() == [], "a second run with no edits pushes nothing"

    # Two edits to mutable bodies: a task re-anchor and an intent status change.
    assert runner.invoke(app, ["link", "task:greet/1", "sym:app.py#greet",
                               "--repo", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "greeting", "--status", "satisfied",
                               "--repo", str(tmp_path)]).exit_code == 0

    second = _push_everything_outgoing()
    assert any(i.startswith("task:greet/1@") for i in second), "the re-anchor must reach the log"
    assert any(i.startswith("int:greeting@") for i in second), "the status change must reach the log"

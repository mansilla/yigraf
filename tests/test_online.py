"""The online transport — done-tests for plan tasks #7/#8/#9 (int:yigraf-online-v1).

Proven entirely offline against :class:`~yigraf.onlinelog.SqliteAssertionStore`, the stdlib reference
adapter (mem:059: the only local↔online difference is a thin substrate adapter; the fold, the
contradiction-detector, and the query layer are shared, so the sqlite store proves the whole engine
with no network). The production :class:`~yigraf.onlinelog.PostgresAssertionStore` implements the same
contract and is exercised only against a live server.

- **#7** append-only monotonic-seq project-scoped log + LISTEN/NOTIFY + SYNCHRONOUS structural/causal
  ingest that never runs the semantic (contradiction) check.
- **#8** signed provenance on every assertion + a tamper-evident Merkle/hash chain; authority rides the
  EXISTING maturity ladder (no new axis).
- **#9** CQRS read service — a materialized view queryable by ``context``/``status``, with a
  consistency/current-state signal and NOTIFY-driven convergence.

The capstone (:func:`test_online_fold_matches_local_on_self_hosted_repo`) carries task #6's "rebuilds
identically" proof to the online transport: the online log folds to the byte-identical graph the local
``FileLog`` does, over yigraf's own real assertion corpus.
"""
from pathlib import Path

import pytest

from yigraf import memory
from yigraf.config import default_config
from yigraf.filelog import assertions_from_repo
from yigraf.fold import fold
from yigraf.graph import to_node_link
from yigraf.log import Assertion, InMemoryLog, causal_order
from yigraf.onlinelog import (
    DEFAULT_NOTIFY_CHANNEL,
    GENESIS_HASH,
    AssertionStore,
    IngestRejected,
    OnlineLog,
    SqliteAssertionStore,
    chain_hash,
    sign_provenance,
    validate_ingest,
    verify_provenance,
)
from yigraf.onlineview import ReadService
from yigraf.status import compute_status

REPO = Path(__file__).resolve().parents[1]
KEY = b"test-signer-key"


def _prov(actor="alice", source="cli", **over):
    """A complete signed-ready provenance record (the attribution task #8 requires on every assertion)."""
    rec = {"actor": actor, "session": "s1", "model": "opus-4.8", "commit_sha": "deadbeef",
           "ts": "2026-07-14T00:00:00Z", "source": source}
    rec.update(over)
    return rec


def _mem(id_, statement, *, edges=(), parents=(), prov=None, source="cli"):
    """One memory-family assertion in the fold's body contract, with a one-record provenance list."""
    return Assertion(
        id=id_, kind="memory",
        body={"family": "memory", "attrs": {"kind": "decision", "status": "active",
                                            "label": statement, "statement": statement},
              "edges": list(edges)},
        parents=tuple(parents),
        provenance=[prov if prov is not None else _prov(source=source)])


def _online(store=None, project="proj", **kw):
    return OnlineLog(store or SqliteAssertionStore(), project, signer_key=KEY, **kw)


# ============================================================================================
# Task #7 — append-only log: monotonic seq, project scope, collapse, LISTEN/NOTIFY, ingest gate
# ============================================================================================


def test_sqlite_store_satisfies_the_port():
    assert isinstance(SqliteAssertionStore(), AssertionStore)


def test_append_assigns_monotonic_seq():
    log = _online()
    for i in range(3):
        log.append(_mem(f"mem:{i}", f"claim {i}"))
    seqs = [e.seq for e in log.store.iter_events("proj")]
    assert seqs == [1, 2, 3]  # BIGSERIAL/AUTOINCREMENT monotone, insertion order


def test_iter_causal_order_matches_in_memory_substrate():
    """The read path is substrate-independent (mem:059): the same content folds the same on either
    substrate. Child appended before parent — the ingest gate would reject that, so we compare the READ
    path directly by loading both substrates from the same causally-sorted set."""
    asserts = [_mem("mem:b", "after", parents=("mem:a",)), _mem("mem:a", "before")]
    ordered = causal_order(asserts)

    mem = InMemoryLog()
    for a in ordered:
        mem.append(a)
    store = SqliteAssertionStore()
    online = _online(store)
    for a in ordered:
        online.append(a)

    assert [a.id for a in online.iter_assertions_in_causal_order()] == \
           [a.id for a in mem.iter_assertions_in_causal_order()] == ["mem:a", "mem:b"]


def test_replay_is_idempotent_and_never_grows_the_chain():
    """An identical re-assertion (a replayed log) collapses on ``event_key`` — no duplicate row, no
    chain growth (append-only integrity, mem:060/task #8)."""
    log = _online()
    a = _mem("mem:1", "once")
    log.append(a)
    head_after_first = log.head_hash()
    log.append(a)  # exact replay
    assert len(log.store.iter_events("proj")) == 1
    assert log.head_hash() == head_after_first


def test_independent_rediscovery_unions_provenance_across_writers():
    """Two writers asserting the SAME claim (mem:060): one strengthened node, provenance unioned — the
    collapse that makes a log merge re-derive belief instead of forking (int:concurrent-write-model)."""
    log = _online()
    log.append(_mem("mem:1", "shared", prov=_prov(actor="alice")))
    merged = log.append(_mem("mem:1", "shared", prov=_prov(actor="bob")))
    assert len(log.store.iter_events("proj")) == 2  # two genuine events (distinct provenance)
    assert {p["actor"] for p in merged.provenance} == {"alice", "bob"}
    assert len(list(log.iter_assertions_in_causal_order())) == 1  # collapsed to one node


def test_projects_are_isolated():
    store = SqliteAssertionStore()
    a = _online(store, project="A")
    b = _online(store, project="B")
    a.append(_mem("mem:1", "in A"))
    assert b.store.known_ids("B") == set()
    assert b.head_hash() == GENESIS_HASH  # B's chain is untouched by A's append
    assert a.store.known_ids("A") == {"mem:1"}


def test_ingest_rejects_dangling_causal_parent():
    """Causal validation (task #7): the online log stays prefix-closed — a parent not yet in the log is
    rejected with guidance, never silently dropped (stricter than causal_order's replica tolerance)."""
    log = _online()
    with pytest.raises(IngestRejected) as exc:
        log.append(_mem("mem:2", "orphan", parents=("mem:missing",)))
    assert any("mem:missing" in p for p in exc.value.problems)
    assert log.store.known_ids("proj") == set()  # nothing landed


def test_ingest_rejects_malformed_body_and_leaked_derived_belief():
    """Structural validation (task #7): the body must be the fold's {family,attrs,edges} shape, and a
    source claim may not smuggle derived belief (the fold owns acceptance/supersession)."""
    log = _online()
    bad_shape = Assertion(id="mem:x", kind="memory", body={"family": "", "edges": "nope"},
                          provenance=[_prov()])
    assert validate_ingest(bad_shape, set())  # non-empty problems

    leaked = Assertion(id="mem:y", kind="memory",
                       body={"family": "memory", "attrs": {"accepted": True}, "edges": []},
                       provenance=[_prov()])
    problems = validate_ingest(leaked, set())
    assert any("derived belief" in p for p in problems)
    with pytest.raises(IngestRejected):
        log.append(leaked)


def test_ingest_is_structural_only_never_a_semantic_gate():
    """int:yigraf-online-v1: coherence is checked ASYNC, never at ingest. Two near-identical beliefs on
    the same anchor both land — flagging them is the task-#4 sweep's job, not a synchronous write gate."""
    log = _online()
    edges = ({"relation": "concerns", "target": "sym:a#b", "attrs": {}},)
    log.append(_mem("mem:1", "the timeout should be 30s", edges=edges))
    log.append(_mem("mem:2", "the timeout should be 30 seconds", edges=edges))  # near-dup, not rejected
    assert log.store.known_ids("proj") == {"mem:1", "mem:2"}  # both landed; no semantic gate


def test_notify_fires_on_new_append_only():
    log = _online()
    seen = []
    log.store.subscribe(DEFAULT_NOTIFY_CHANNEL, lambda payload: seen.append(payload))
    a = _mem("mem:1", "claim")
    log.append(a)
    log.append(a)  # replay ⇒ no new event ⇒ no notify
    assert len(seen) == 1
    assert '"seq": 1' in seen[0] and '"id": "mem:1"' in seen[0]


# ============================================================================================
# Task #8 — signed provenance + Merkle chain; authority rides the existing maturity ladder
# ============================================================================================


def test_provenance_is_signed_and_verifies():
    log = _online()
    stored = log.append(_mem("mem:1", "claim"))
    record = stored.provenance[0]
    assert "sig" in record and verify_provenance(record, KEY)
    tampered = {**record, "actor": "mallory"}
    assert not verify_provenance(tampered, KEY)  # any field edit invalidates the signature


def test_unsigned_when_no_key_but_still_ingests():
    """Fail-open (R5): a store with no signer still appends — the chain alone stays tamper-evident."""
    log = OnlineLog(SqliteAssertionStore(), "proj", signer_key=None)
    stored = log.append(_mem("mem:1", "claim"))
    assert "sig" not in stored.provenance[0]
    assert log.verify_chain()


def test_ingest_requires_provenance_online():
    log = _online()
    no_prov = Assertion(id="mem:1", kind="memory",
                        body={"family": "memory", "attrs": {"label": "x"}, "edges": []})
    with pytest.raises(IngestRejected) as exc:
        log.append(no_prov)
    assert any("provenance" in p for p in exc.value.problems)


def test_missing_attribution_field_is_rejected():
    incomplete = _prov()
    del incomplete["model"]
    problems = validate_ingest(_mem("mem:1", "x", prov=incomplete), set())
    assert any("model" in p for p in problems)


def test_authority_rides_the_existing_maturity_ladder():
    """Task #8: no new authority axis — the online provenance ``source`` feeds the SAME ladder
    (:func:`yigraf.memory.landing_maturity`) the local path uses. A ``cli`` assert lands ``working``; a
    ``mined`` candidate lands ``proposed`` — identical to the single-writer local behavior."""
    log = _online()
    agent_said = log.append(_mem("mem:1", "agent decision", prov=_prov(source="cli")))
    mined = log.append(_mem("mem:2", "mined candidate", prov=_prov(source="mined")))
    assert memory.landing_maturity(agent_said.provenance) == "working"
    assert memory.landing_maturity(mined.provenance) == "proposed"


def test_chain_links_each_entry_to_the_prior():
    log = _online()
    log.append(_mem("mem:1", "a"))
    log.append(_mem("mem:2", "b"))
    e1, e2 = log.store.iter_events("proj")
    assert e1.prev_hash == GENESIS_HASH
    assert e2.prev_hash == e1.entry_hash
    assert e2.entry_hash == chain_hash(e1.entry_hash, e2.event_key)
    assert log.verify_chain()
    assert log.head_hash() == e2.entry_hash  # a compact commitment to the whole ordered log


def test_chain_detects_tampering():
    """Drop/reorder any committed event and the chain no longer verifies (task #8 integrity): mem:2's
    stored ``prev_hash`` points at mem:1's ``entry_hash``, so removing mem:1 breaks the linkage."""
    store = SqliteAssertionStore()
    log = _online(store)
    log.append(_mem("mem:1", "a"))
    log.append(_mem("mem:2", "b"))
    assert log.verify_chain()
    store._conn.execute("DELETE FROM events WHERE id='mem:1'")
    store._conn.commit()
    assert not log.verify_chain()  # mem:2's prev_hash no longer matches the (now genesis) predecessor


def test_empty_log_head_is_genesis():
    assert _online().head_hash() == GENESIS_HASH


# ============================================================================================
# Task #9 — CQRS read service: materialized view, consistency, NOTIFY-driven convergence
# ============================================================================================


def test_view_materializes_and_round_trips_to_the_fold(tmp_path):
    """The materialized view reloads to the byte-identical graph an in-memory fold produces (mem:059:
    shared query layer). This is what lets ``context``/``status`` run over the online graph unchanged."""
    log = _online()
    log.append(_mem("mem:1", "a"))
    log.append(_mem("mem:2", "b", parents=("mem:1",), edges=(
        {"relation": "supersedes", "target": "mem:1", "attrs": {}},)))
    rs = ReadService(log)
    rs.refold()
    loaded = rs.load_graph()
    assert loaded is not None
    assert to_node_link(loaded) == to_node_link(fold(log))


def test_consistency_flips_on_append_and_heals_on_refold():
    log = _online()
    rs = ReadService(log)
    log.append(_mem("mem:1", "a"))
    rs.refold()
    assert rs.consistency().current  # view reflects the log head
    log.append(_mem("mem:2", "b"))  # a new append leaves the view stale
    c = rs.consistency()
    assert not c.current and c.view_seq == 1 and c.log_seq == 2
    rs.refold()
    assert rs.consistency().current


def test_notify_drives_the_view_to_current_state():
    """Task #7's NOTIFY drives task #9's refold: after wiring ``start``, an append converges the view
    with no explicit refold — the read service self-heals to current state."""
    log = _online()
    rs = ReadService(log)
    rs.start()  # subscribe to the log's NOTIFY channel
    log.append(_mem("mem:1", "a"))
    assert rs.consistency().current
    assert set(rs.load_graph().nodes) == {"mem:1"}
    log.append(_mem("mem:2", "b"))
    assert set(rs.load_graph().nodes) == {"mem:1", "mem:2"}  # converged via NOTIFY, no manual refold


def test_load_current_refolds_a_stale_view():
    log = _online()
    rs = ReadService(log)
    log.append(_mem("mem:1", "a"))  # no refold yet ⇒ view absent
    assert rs.load_graph() is None
    graph = rs.load_current()  # refolds because stale, then serves
    assert set(graph.nodes) == {"mem:1"}


def test_view_is_queryable_by_status(tmp_path):
    """The point of #9: the online view answers ``status`` exactly as a local graph would — the summary
    computed over the reloaded view equals the one over the in-memory fold (shared query layer)."""
    log = _online()
    log.append(_mem("mem:1", "a decision", edges=(
        {"relation": "serves", "target": "int:x", "attrs": {}},)))
    rs = ReadService(log)
    rs.refold()
    config = default_config()
    from_view = compute_status(rs.load_graph(), tmp_path, config)
    from_fold = compute_status(fold(log), tmp_path, config)
    assert from_view.decisions == from_fold.decisions == 1
    assert from_view.as_dict() == from_fold.as_dict()


# ============================================================================================
# Capstone — the online log folds IDENTICALLY to the local FileLog (task #6 discipline, online)
# ============================================================================================


def test_online_fold_matches_local_on_self_hosted_repo():
    """Over yigraf's own real assertion corpus, appending every authored assertion (in causal order) to
    the online log and folding it yields the byte-identical graph the in-memory reference substrate does
    — the "rebuilds identically" proof (task #6) carried to the online transport (mem:059).

    Also asserts the real corpus is prefix-closed: every assertion appends through the strict causal
    gate with no dangling parent, and the whole log's Merkle chain verifies."""
    ordered = causal_order(assertions_from_repo(REPO))

    reference = InMemoryLog()
    for a in ordered:
        reference.append(a)

    store = SqliteAssertionStore()
    # The authored artifacts predate signed provenance (single-writer local), so compare the read path
    # with signing off — the fold output is independent of the attribution fields task #8 adds.
    online = OnlineLog(store, "yigraf", signer_key=None, require_signed_provenance=False)
    for a in ordered:
        online.append(a)  # strict causal gate: passes iff the corpus is prefix-closed

    assert online.verify_chain()
    assert to_node_link(fold(online)) == to_node_link(fold(reference))

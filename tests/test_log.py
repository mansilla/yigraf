"""The transport-agnostic assertion log — task #2 done-test (int:concurrent-write-model).

The two prior decisions the log exists to encode, proven as executable contracts:
- mem:063 — the id content-addresses ``(kind, body)`` ONLY; ``parents``/``provenance`` never change it,
  so independent rediscoveries of the same claim collapse to one strengthened entry (mem:060).
- mem:056080f0 — causal order is its own layer: :func:`causal_order` honors the parent DAG and is
  reproducible regardless of insertion order, and fails open on dangling parents / cycles (R5).
"""
from yigraf.log import (
    Assertion,
    InMemoryLog,
    Log,
    assertion_id,
    causal_order,
    merge_assertion,
)


def _a(id_, *parents, kind="memory", body=None, prov=None):
    return Assertion(id=id_, kind=kind, body=body or {}, parents=tuple(parents),
                     provenance=list(prov or []))


# -- mem:063: content-only identity ---------------------------------------------------------------


def test_id_ignores_parents_and_provenance():
    """The id hashes (kind, body) only — differing causal parents/provenance keep the SAME id."""
    body = {"statement": "use content-addressing", "why": "collision-free merge"}
    a = assertion_id("memory", body)
    b = assertion_id("memory", body)
    assert a == b  # same content ⇒ same id
    # Parents/provenance live on the envelope, never in the hash — nothing about them can move the id.
    one = Assertion(id=a, kind="memory", body=body, parents=("x",), provenance=[{"actor": "alice"}])
    two = Assertion(id=b, kind="memory", body=body, parents=("y", "z"), provenance=[{"actor": "bob"}])
    assert one.id == two.id


def test_id_is_order_independent():
    """Payload built in a different field/collection order canonicalizes to the same id."""
    assert assertion_id("link", {"serves": ["a", "b"], "sym": "s"}) == \
           assertion_id("link", {"sym": "s", "serves": ["b", "a"]})


def test_different_content_diverges():
    assert assertion_id("memory", {"why": "x"}) != assertion_id("memory", {"why": "y"})
    assert assertion_id("memory", {"why": "x"}) != assertion_id("link", {"why": "x"})


# -- mem:060: identical-content collapse strengthens, never duplicates -----------------------------


def test_append_collapses_identical_id_and_merges_provenance():
    log = InMemoryLog()
    log.append(_a("mem:1", "p0", prov=[{"actor": "alice", "session": "1"}]))
    log.append(_a("mem:1", "p1", prov=[{"actor": "bob", "session": "2"}]))
    stored = list(log.iter_assertions_in_causal_order())
    assert len(stored) == 1  # one node, not two — collapse (mem:060)
    entry = stored[0]
    assert set(entry.parents) == {"p0", "p1"}          # causal frontier unioned
    assert len(entry.provenance) == 2                   # both rediscoveries retained
    assert {p["actor"] for p in entry.provenance} == {"alice", "bob"}


def test_merge_dedups_identical_provenance_records():
    """Re-asserting truly identical content+provenance (a replayed log) doesn't inflate provenance."""
    rec = {"actor": "alice", "commit": "abc"}
    merged = merge_assertion(_a("mem:1", "p0", prov=[rec]), _a("mem:1", "p0", prov=[rec]))
    assert merged.parents == ("p0",)
    assert merged.provenance == [rec]


# -- mem:056080f0: causal order is its own layer ---------------------------------------------------


def test_parent_precedes_child_regardless_of_insertion_order():
    """The successor inserted first (the exact shape that dropped a pending conflict) still folds after
    its parent — order comes from the DAG, never insertion/file order (mem:056080f0)."""
    child = _a("mem:zzz", "mem:aaa")   # successor, sorts LAST by id but inserted FIRST
    parent = _a("mem:aaa")
    ordered = [x.id for x in causal_order([child, parent])]
    assert ordered.index("mem:aaa") < ordered.index("mem:zzz")


def test_order_is_reproducible_across_input_orderings():
    """Same content, any input order ⇒ identical linearization (substrate independence, mem:059)."""
    root = _a("mem:m")
    x = _a("mem:x", "mem:m")
    y = _a("mem:y", "mem:m")          # x and y are concurrent — tiebroken by id
    forward = [a.id for a in causal_order([root, x, y])]
    shuffled = [a.id for a in causal_order([y, root, x])]
    assert forward == shuffled == ["mem:m", "mem:x", "mem:y"]


def test_dangling_parent_is_ignored_not_fatal():
    """A parent naming an id absent from the log (partial replica) is dropped from ordering, fail-open."""
    ordered = causal_order([_a("mem:1", "mem:missing")])
    assert [a.id for a in ordered] == ["mem:1"]


def test_cycle_does_not_hang_and_emits_all():
    """A (should-be-impossible) cycle flushes every node deterministically instead of hanging (R5)."""
    ordered = causal_order([_a("mem:a", "mem:b"), _a("mem:b", "mem:a")])
    assert sorted(a.id for a in ordered) == ["mem:a", "mem:b"]
    assert len(ordered) == 2


# -- the interface itself --------------------------------------------------------------------------


def test_in_memory_log_satisfies_the_protocol():
    assert isinstance(InMemoryLog(), Log)


def test_append_returns_stored_entry():
    log = InMemoryLog()
    first = log.append(_a("mem:1", "p0", prov=[{"actor": "a"}]))
    assert first.parents == ("p0",)
    second = log.append(_a("mem:1", "p1", prov=[{"actor": "b"}]))
    assert set(second.parents) == {"p0", "p1"}  # the merged view is returned

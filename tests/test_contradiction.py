"""The async contradiction / coherence detector — task #4 done-test (int:concurrent-write-model).

Model-free (the test_embeddings convention): a toy 2-D index is injected with controlled vectors, so
cosine is exact and the suite needs no model backend. Proves the detector surfaces two LIVE,
co-anchored, unreconciled, near-topic beliefs as a knowledge-conflict finding (mem:062), respects
liveness / anchor-scoping / reconciliation, and fails open to SILENCE with no index (design law #4).
"""
import pytest

from yigraf import embeddings
from yigraf.config import default_config
from yigraf.contradiction import Conflict, detect_conflicts, open_conflict_count
from yigraf.graph import empty_graph

np = pytest.importorskip("numpy")

ANCHOR = "sym:a.py#f"
ANCHOR2 = "sym:b.py#g"


def _cfg():
    cfg = default_config()
    cfg["embeddings"]["model"] = "test-model"  # match the model we save the toy index under
    return cfg


def _unit(x, y):
    v = np.array([x, y], dtype="float32")
    return v / np.linalg.norm(v)


# Two vectors ~11° apart ⇒ cosine ≈ 0.98 (a near-dup pair); orthogonal-ish ⇒ ≈0.32 (below the gate).
CLOSE_A = _unit(1.0, 0.0)
CLOSE_B = _unit(1.0, 0.2)
FAR = _unit(1.0, 3.0)


def _save_index(root, vectors: dict):
    ids = list(vectors)
    matrix = np.vstack([vectors[i] for i in ids]) if ids else np.zeros((0, 2), dtype="float32")
    embeddings._save_index(root, "test-model", ids, matrix, {i: "h" for i in ids})


def _graph(*mem_ids, anchors=None, live=None):
    """A graph with ``mem_ids`` memory nodes each concerning ``ANCHOR`` (override via ``anchors``)."""
    anchors = anchors or {}
    live = live or {}
    g = empty_graph()
    for a in {ANCHOR, ANCHOR2}:
        g.add_node(a, family="structure", kind="function")
    for mid in mem_ids:
        attrs = {"family": "memory", "status": "active", "superseded_in": 0, **live.get(mid, {})}
        g.add_node(mid, **attrs)
        for tgt in anchors.get(mid, [ANCHOR]):
            g.add_edge(mid, tgt, relation="concerns")
    return g


# -- surfacing --------------------------------------------------------------------------------------


def test_flags_two_close_coanchored_live_beliefs(tmp_path):
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": CLOSE_B})
    conflicts = detect_conflicts(_graph("mem:1", "mem:2"), tmp_path, _cfg())
    assert len(conflicts) == 1
    c = conflicts[0]
    assert (c.left, c.right, c.anchor) == ("mem:1", "mem:2", ANCHOR)
    assert c.cosine > 0.85 and c.pending is False


def test_below_threshold_not_flagged(tmp_path):
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": FAR})
    assert detect_conflicts(_graph("mem:1", "mem:2"), tmp_path, _cfg()) == []


def test_different_anchors_not_flagged(tmp_path):
    """Near-identical beliefs about DIFFERENT anchors aren't a conflict (mem:058: same anchor)."""
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": CLOSE_B})
    g = _graph("mem:1", "mem:2", anchors={"mem:1": [ANCHOR], "mem:2": [ANCHOR2]})
    assert detect_conflicts(g, tmp_path, _cfg()) == []


# -- liveness ---------------------------------------------------------------------------------------


def test_superseded_belief_is_not_live(tmp_path):
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": CLOSE_B})
    g = _graph("mem:1", "mem:2", live={"mem:2": {"superseded_in": 1}})
    assert detect_conflicts(g, tmp_path, _cfg()) == []


def test_inactive_status_is_not_live(tmp_path):
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": CLOSE_B})
    g = _graph("mem:1", "mem:2", live={"mem:2": {"status": "archived"}})
    assert detect_conflicts(g, tmp_path, _cfg()) == []


# -- reconciliation (mem:062) -----------------------------------------------------------------------


def test_equivalence_edge_reconciles(tmp_path):
    """A principal's equivalent_to resolution clears the conflict — reconciliation is an append (mem:062)."""
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": CLOSE_B})
    g = _graph("mem:1", "mem:2")
    g.add_edge("mem:2", "mem:1", relation="equivalent_to")
    assert detect_conflicts(g, tmp_path, _cfg()) == []


def test_pending_supersede_stays_open_and_flagged(tmp_path):
    """A held-pending supersede is an OPEN conflict awaiting a human, not a resolution (mem:062)."""
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": CLOSE_B})
    g = _graph("mem:1", "mem:2")
    g.add_edge("mem:2", "mem:1", relation="supersedes", pending=True)
    conflicts = detect_conflicts(g, tmp_path, _cfg())
    assert len(conflicts) == 1 and conflicts[0].pending is True


# -- fail-open + shape ------------------------------------------------------------------------------


def test_no_index_fails_open_to_silence(tmp_path):
    """No embedding index ⇒ [] (silence over noise), never a flood of every co-anchored pair."""
    assert detect_conflicts(_graph("mem:1", "mem:2"), tmp_path, _cfg()) == []


def test_pair_sharing_two_anchors_reported_once(tmp_path):
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": CLOSE_B})
    g = _graph("mem:1", "mem:2", anchors={"mem:1": [ANCHOR, ANCHOR2], "mem:2": [ANCHOR, ANCHOR2]})
    assert len(detect_conflicts(g, tmp_path, _cfg())) == 1  # one pair, not one-per-anchor


def test_findings_sorted_by_cosine_descending(tmp_path):
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": CLOSE_B, "mem:3": _unit(1.0, 0.1)})
    conflicts = detect_conflicts(_graph("mem:1", "mem:2", "mem:3"), tmp_path, _cfg())
    cosines = [c.cosine for c in conflicts]
    assert cosines == sorted(cosines, reverse=True)


def test_open_conflict_count_matches(tmp_path):
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": CLOSE_B})
    g = _graph("mem:1", "mem:2")
    assert open_conflict_count(g, tmp_path, _cfg()) == 1


# -- held-pending supersedes: asserted state, not a label on a measurement (feedback-v4 #3) ----------


def _pending_graph(*, close: bool, anchors=None):
    """mem:2 pending-supersedes human-attested mem:1, optionally reading nothing like it."""
    g = _graph("mem:1", "mem:2", anchors=anchors)
    g.add_edge("mem:2", "mem:1", relation="supersedes", pending=True)
    return g


def test_a_pending_supersede_surfaces_even_when_the_two_read_nothing_alike(tmp_path):
    """`pending` used to be only a LABEL applied to a pair the cosine sweep or a dispute had already
    found — and a supersede states a CHANGED belief, so normally the two sit below the gate.

    The field measured 0.6457 and 0.5583 on realistic corrections, both invisible to `status`,
    `status --json`, `conflicts`, `show` and the Stop-hook notice, while `supersede`'s own promise is
    that the predecessor "stays authoritative until a human resolves the conflict". So the
    better-written the correction, the less likely the trust floor was to be enforced.
    """
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": FAR})  # far apart — the sweep finds nothing
    conflicts = detect_conflicts(_pending_graph(close=False), tmp_path, _cfg())
    assert len(conflicts) == 1
    assert conflicts[0].pending is True and (conflicts[0].left, conflicts[0].right) == ("mem:1", "mem:2")


def test_a_pending_supersede_surfaces_with_no_index_at_all(tmp_path):
    """Asserted state must not depend on who happens to hold an index — the same reason a nomination
    doesn't. The sweep still fails open to silence (design law #4)."""
    conflicts = detect_conflicts(_pending_graph(close=False), tmp_path, _cfg())
    assert len(conflicts) == 1 and conflicts[0].pending is True


def test_a_pending_supersede_needs_no_shared_anchor(tmp_path):
    """The sweep requires co-anchoring; a held supersede is a conflict by construction, so it reports
    with an empty anchor rather than not reporting."""
    g = _pending_graph(close=False, anchors={"mem:1": [ANCHOR], "mem:2": [ANCHOR2]})
    conflicts = detect_conflicts(g, tmp_path, _cfg())
    assert len(conflicts) == 1 and conflicts[0].anchor == ""


def test_a_pending_pair_is_reported_once_not_twice(tmp_path):
    """Above the gate the sweep would also find it — the union must not double-report."""
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": CLOSE_B})
    conflicts = detect_conflicts(_pending_graph(close=True), tmp_path, _cfg())
    assert len(conflicts) == 1 and conflicts[0].pending is True


def test_pending_outranks_the_sweep_in_the_finding_order(tmp_path):
    """Pending carries no cosine, so ordering by -cosine alone sorted every one of them BELOW every
    swept pair — under a cap that then drops the item only a principal can clear. Same shape as the
    1.5.0 stale-before-conflict bug, one level down."""
    _save_index(tmp_path, {"mem:1": CLOSE_A, "mem:2": FAR, "mem:3": CLOSE_A, "mem:4": CLOSE_B})
    g = _graph("mem:1", "mem:2", "mem:3", "mem:4")
    g.add_edge("mem:2", "mem:1", relation="supersedes", pending=True)
    conflicts = detect_conflicts(g, tmp_path, _cfg())
    assert [c.pending for c in conflicts][0] is True
    assert any(not c.pending for c in conflicts), "the swept pair is still reported, just after"


def test_the_status_count_sees_a_pending_supersede(tmp_path):
    """`status` reading `no drift · fresh` above its own `⚠ Conflict (pending)` block was one render
    contradicting itself — the count came from `detect_conflicts`, the block from a different source."""
    assert open_conflict_count(_pending_graph(close=False), tmp_path, _cfg()) == 1


def test_a_reconciled_pending_pair_is_closed(tmp_path):
    """A principal's verdict closes it like any other finding — pending is not exempt from resolution."""
    g = _pending_graph(close=False)
    g.add_node("res:1", family="resolution", kind="reconcile", left="mem:1", right="mem:2")
    assert detect_conflicts(g, tmp_path, _cfg()) == []

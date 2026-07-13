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

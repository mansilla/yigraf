"""Provenance-typed revision policy (epistemic-control-plane #6) + its wiring into the conflict finding.

Concrete-example unit tests for the classifier and the strict partial order; the algebraic invariants
(irreflexive, antisymmetric, transitive, same-tier ⇒ incomparable) live in the property suite
(tests/test_invariants.py, task #7). The load-bearing behaviour under test is mem:062's guarantee: the
order *informs* a resolution, it never breaks a same-tier tie (no scalar tiebreak, no last-writer-wins).
"""
import pytest

from yigraf import revision
from yigraf.config import default_config
from yigraf.contradiction import detect_conflicts
from yigraf.graph import empty_graph
from yigraf import embeddings

np = pytest.importorskip("numpy")


# -- classify -------------------------------------------------------------------------------------


def test_human_attestation_outranks_provenance_type_on_any_family():
    """A principal endorsement is the trust floor (int:memory-attestation): it wins the ``human`` tier
    regardless of family or grounding — checked before anything else."""
    assert revision.classify({"family": "memory", "attestation": "human", "grounding": "inferred"}) == "human"
    assert revision.classify({"family": "structure", "attestation": "human"}) == "human"


def test_intent_is_a_normative_must_contract():
    assert revision.classify({"family": "intent"}) == "must"


def test_empirical_grounding_beats_a_decision_kind():
    """An empirically-grounded memory ranks by its grounding, above a merely-asserted design decision."""
    assert revision.classify({"family": "memory", "kind": "decision", "grounding": "empirical"}) == "empirical"
    assert revision.classify({"family": "memory", "kind": "decision", "grounding": "inferred"}) == "architectural"


def test_soft_memory_kinds_fall_to_llm():
    for kind in ("rationale", "learned-fact", "preference", "rejected-alternative"):
        assert revision.classify({"family": "memory", "kind": kind, "grounding": "inferred"}) == "llm"


def test_plan_and_structure_families():
    assert revision.classify({"family": "plan"}) == "plan-assumption"
    assert revision.classify({"family": "structure"}) == "structural"


def test_unknown_provenance_is_the_floor_never_silently_wins():
    """A node with no recognized provenance lands ``llm`` — it can never outrank a real belief."""
    assert revision.classify({}) == "llm"
    assert revision.classify({"family": "mystery"}) == "llm"


# -- the strict order -----------------------------------------------------------------------------


def test_order_is_strictly_descending():
    ranks = [revision.rank(t) for t in revision.PROVENANCE_ORDER]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)


def test_higher_provenance_dominates_lower():
    human = {"family": "memory", "attestation": "human"}
    llm = {"family": "memory", "kind": "preference", "grounding": "inferred"}
    assert revision.dominates(human, llm)
    assert not revision.dominates(llm, human)


def test_same_tier_is_incomparable_no_tiebreak():
    """The core mem:062 guarantee: two same-tier beliefs neither dominate — the pair is held open for a
    human, never resolved by a scalar or by insertion order (no last-writer-wins)."""
    a = {"family": "memory", "kind": "preference", "grounding": "inferred"}
    b = {"family": "memory", "kind": "learned-fact", "grounding": "inferred"}  # both classify ``llm``
    assert revision.classify(a) == revision.classify(b) == "llm"
    assert not revision.dominates(a, b) and not revision.dominates(b, a)
    assert revision.dominant_id("mem:a", a, "mem:b", b) is None


def test_dominant_id_names_the_preferred_side():
    human = {"family": "memory", "attestation": "human"}
    llm = {"family": "memory", "kind": "preference", "grounding": "inferred"}
    assert revision.dominant_id("mem:h", human, "mem:l", llm) == "mem:h"
    assert revision.dominant_id("mem:l", llm, "mem:h", human) == "mem:h"  # order-independent


# -- integration: the conflict finding carries the guidance ---------------------------------------

ANCHOR = "sym:a.py#f"


def _unit(x, y):
    v = np.array([x, y], dtype="float32")
    return v / np.linalg.norm(v)


def _cfg():
    cfg = default_config()
    cfg["embeddings"]["model"] = "test-model"
    return cfg


def _save_index(root, vectors: dict):
    ids = list(vectors)
    matrix = np.vstack([vectors[i] for i in ids])
    embeddings._save_index(root, "test-model", ids, matrix, {i: "h" for i in ids})


def _graph(attrs_by_id: dict):
    g = empty_graph()
    g.add_node(ANCHOR, family="structure", kind="function")
    for mid, extra in attrs_by_id.items():
        g.add_node(mid, family="memory", status="active", superseded_in=0, **extra)
        g.add_edge(mid, ANCHOR, relation="concerns")
    return g


def test_conflict_finding_flags_the_human_belief_as_dominant(tmp_path):
    """A human-attested belief conflicting with an agent inference: the finding names the human side as
    dominant — principal-facing guidance, not an applied supersede (mem:062, mem:012)."""
    _save_index(tmp_path, {"mem:human": _unit(1.0, 0.0), "mem:agent": _unit(1.0, 0.2)})
    g = _graph({
        "mem:human": {"attestation": "human", "kind": "decision"},
        "mem:agent": {"attestation": "agent", "kind": "preference", "grounding": "inferred"},
    })
    conflicts = detect_conflicts(g, tmp_path, _cfg())
    assert len(conflicts) == 1 and conflicts[0].dominant == "mem:human"


def test_same_tier_conflict_has_no_dominant(tmp_path):
    """Two agent inferences of the same tier: the finding surfaces (a real conflict) but names no winner —
    it stays a human's call."""
    _save_index(tmp_path, {"mem:1": _unit(1.0, 0.0), "mem:2": _unit(1.0, 0.2)})
    g = _graph({
        "mem:1": {"attestation": "agent", "kind": "preference", "grounding": "inferred"},
        "mem:2": {"attestation": "agent", "kind": "learned-fact", "grounding": "inferred"},
    })
    conflicts = detect_conflicts(g, tmp_path, _cfg())
    assert len(conflicts) == 1 and conflicts[0].dominant is None

"""Task #6 — the migration proof: folding the authored markdown as an assertion log (``FileLog``)
rebuilds the intent/plan/memory subgraph *identically* to the ``project_into`` path it replaces.

"Identically" = the same family nodes, the same edges (with the same anchors/pending/confidence), and
the same *source-claim* node attrs. The fold additionally carries **derived belief** (``accepted``,
``superseded_in``/``supersedes_out`` on every node) and the reserved ``scope`` — additive by design
(task #5, mem:065017c08f97dcbf), so those are verified for internal consistency rather than against the
old path, which never had them. Provenance rides the envelope as a list (mem:063) where project_into
stored a dict, so its *content* is compared modulo container. Run against the self-hosted repo — the
richest real corpus we have — so the proof is over yigraf's own intents, plans, and memories.

**Verdict projections are the same kind of addition** (task:team-reconciliation/1). A resolution is an
edge between two OTHER beliefs, so the fold emits it *out of a memory node* while the verdict itself
lives in a ``resolution`` family ``project_into`` has no vocabulary for — and since ``reconcile`` stopped
writing ``equivalent_to`` frontmatter (mem:66429d96), the old path cannot see it at all. So those edges
are carved out of the diff and asserted for internal consistency instead: every family edge the fold
adds must be backed by an authored verdict claiming exactly that pair and relation.
"""
from pathlib import Path

from yigraf import artifacts, memory
from yigraf.config import default_config
from yigraf.extract import build_graph
from yigraf.filelog import FileLog
from yigraf.fold import fold

REPO = Path(__file__).resolve().parents[1]
FAMILIES = {"intent", "plan", "memory"}

#: Attrs handled by a dedicated assertion below, excluded from the source-claim attr diff: derived
#: belief + reserved scope + envelope provenance (the fold's additions), and the two dangling
#: representations (typed ``dangling_*`` on the old path, one ``dangling_edges`` list on the fold).
_HANDLED = {
    "accepted", "scope", "provenance", "superseded_in", "supersedes_out", "dangling_edges",
    "dangling_serves", "dangling_concerns", "dangling_grounded_by", "dangling_supersedes",
    "dangling_equivalent_to", "dangling_tracks", "dangling_requires", "dangling_implements",
}


def _projection_reference(root: Path, config: dict):
    """Return ``(structure_base, reference_graph)``: the current project_into projection, isolated.

    Build the real graph, strip the family nodes to recover the pure structure ``base`` (file-anchor
    nodes injected during projection stay — they are structure-family targets the fold needs), then
    re-run the projection onto a copy so the reference is the *raw* projection, before the drift-rename
    and maturity overlays ``build_graph`` layers on afterward (the fold is compared at the same stage).
    """
    graph, _ = build_graph(root, config)
    base = graph.copy()
    base.remove_nodes_from([n for n, d in graph.nodes(data=True) if d.get("family") in FAMILIES])
    ref = base.copy()
    artifacts.project_into(ref, root)
    memory.project_into(ref, root)
    memory.recompute_counters(ref)
    return base, ref


def _family_nodes(graph):
    return {n for n, d in graph.nodes(data=True) if d.get("family") in FAMILIES}


def _family_edges(graph):
    """Edges out of a family node, as hashable tuples carrying every attr project_into/the fold set."""
    out = set()
    for u, v, d in graph.edges(data=True):
        if graph.nodes[u].get("family") in FAMILIES:
            out.add((u, v, d.get("relation"), d.get("confidence"),
                     d.get("anchor"), d.get("anchor_algo"), d.get("pending")))
    return out


def _ref_danglings(graph):
    """Unresolved (source, relation, target) triples from the old path's typed ``dangling_*`` keys."""
    typed_str = {"dangling_serves": "serves", "dangling_supersedes": "supersedes",
                 "dangling_equivalent_to": "equivalent_to", "dangling_tracks": "tracks",
                 "dangling_requires": "requires"}
    typed_dict = {"dangling_concerns": "concerns", "dangling_grounded_by": "grounded_by",
                  "dangling_implements": "implements"}
    out = set()
    for n, d in graph.nodes(data=True):
        for attr, rel in typed_str.items():
            out.update((n, rel, t) for t in d.get(attr, []))
        for attr, rel in typed_dict.items():
            out.update((n, rel, t["sym"]) for t in d.get(attr, []))
    return out


def _got_danglings(graph):
    return {(n, e["relation"], e["target"])
            for n, d in graph.nodes(data=True) for e in d.get("dangling_edges", [])}


def test_fold_reproduces_family_node_ids():
    base, ref = _projection_reference(REPO, default_config())
    got = fold(FileLog(REPO), base=base.copy())
    assert _family_nodes(got) == _family_nodes(ref)


def _verdict_projections(graph):
    """The ``(source, relation, target)`` triples this repo's authored verdicts claim to project.

    Claimed, not necessarily present: :func:`yigraf.fold._apply_projection` refuses to overwrite a
    differing relation on an ordered pair, so a shadowed verdict is recorded on its own node instead of
    winning the edge. The carve-out below is therefore a subset check, never an equality.
    """
    from yigraf.resolution import PROJECTED_RELATION
    return {(d["left"], PROJECTED_RELATION[d["kind"]], d["right"])
            for _, d in graph.nodes(data=True)
            if d.get("family") == "resolution" and d.get("left") and d.get("right")}


def _triples(edges):
    return {(u, rel, v) for u, v, rel, *_rest in edges}


def test_fold_reproduces_family_edges():
    """Every family edge the fold adds over project_into is an authored verdict's projection."""
    base, ref = _projection_reference(REPO, default_config())
    got = fold(FileLog(REPO), base=base.copy())
    extra = _family_edges(got) - _family_edges(ref)
    assert _triples(extra) <= _verdict_projections(got), \
        "the fold emitted a family edge project_into did not, and no authored verdict projects it"
    assert _family_edges(got) - extra == _family_edges(ref)


def test_a_verdicts_projected_edge_is_the_folds_own_addition():
    """Keeps the carve-out above from going vacuous — on an empty ``extra`` it would pass trivially.

    A verdict lands an edge between two beliefs that ``project_into`` cannot produce at all, which is
    precisely why the resolution family exists (a principal who owns neither belief can still close the
    conflict, mem:66429d96)."""
    base, ref = _projection_reference(REPO, default_config())
    got = fold(FileLog(REPO), base=base.copy())
    landed = _triples(_family_edges(got)) & _verdict_projections(got)
    assert landed, "the self-hosted repo has authored no verdicts — this proof needs at least one"
    assert not (landed & _triples(_family_edges(ref))), "project_into cannot see a projected verdict"


def test_fold_has_no_unresolved_family_edges_the_old_path_resolved():
    base, ref = _projection_reference(REPO, default_config())
    got = fold(FileLog(REPO), base=base.copy())
    assert _got_danglings(got) == _ref_danglings(ref)


def test_fold_reproduces_source_claim_attrs():
    base, ref = _projection_reference(REPO, default_config())
    got = fold(FileLog(REPO), base=base.copy())
    for n in _family_nodes(ref):
        ref_attrs = {k: v for k, v in ref.nodes[n].items() if k not in _HANDLED}
        got_attrs = {k: v for k, v in got.nodes[n].items() if k not in _HANDLED}
        assert got_attrs == ref_attrs, f"source-claim attrs diverge for {n}"


def test_fold_reproduces_provenance_content_as_a_list():
    base, ref = _projection_reference(REPO, default_config())
    got = fold(FileLog(REPO), base=base.copy())
    for n in _family_nodes(ref):
        ref_prov = ref.nodes[n].get("provenance") or {}  # dict on memory, absent elsewhere
        expected = [ref_prov] if ref_prov else []
        assert got.nodes[n]["provenance"] == expected, f"provenance diverges for {n}"


def test_fold_reproduces_supersession_counters():
    base, ref = _projection_reference(REPO, default_config())
    got = fold(FileLog(REPO), base=base.copy())
    for n in _family_nodes(ref):
        assert got.nodes[n]["superseded_in"] == ref.nodes[n].get("superseded_in", 0)
        assert got.nodes[n]["supersedes_out"] == ref.nodes[n].get("supersedes_out", 0)


def test_fold_derives_accepted_and_scope_consistently():
    """The additive derived attrs: ``accepted`` is exactly "not counted-superseded", and today every
    write carries the empty base environment, so ``scope`` is ``[]`` on every folded node."""
    base, _ = _projection_reference(REPO, default_config())
    got = fold(FileLog(REPO), base=base.copy())
    for n in _family_nodes(got):
        d = got.nodes[n]
        assert d["accepted"] is (d["superseded_in"] == 0)
        assert d["scope"] == []

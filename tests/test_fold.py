"""The fold — task #3 done-test (int:concurrent-write-model).

Proves the fold is a pure, single-pass, deterministic materialization over the causally-ordered log,
and that memory's supersedes/append discipline now generalizes to every write:
- belief revision (mem:058): a supersede marks its target but never deletes it;
- single-pass (mem:98d5a556): the counter is right even when the successor is appended FIRST — the
  exact shape mem:056080f0 dropped — because the log orders it after its parent;
- pending supersede (mem:062): recorded, not counted; the target stays authoritative;
- no phantom nodes: an unresolved edge target is stashed, matching ``memory.project_into``.
"""
from yigraf.filelog import denormalize_danglings
from yigraf.fold import fold
from yigraf.graph import empty_graph, to_node_link
from yigraf.log import Assertion, InMemoryLog


def _node(id_, family="memory", attrs=None, edges=None, parents=(), prov=None, scope=()):
    body = {"family": family, "attrs": attrs or {}, "edges": edges or []}
    return Assertion(id=id_, kind=family, body=body, parents=tuple(parents),
                     provenance=list(prov or []), scope=tuple(scope))


def _log(*assertions):
    log = InMemoryLog()
    for a in assertions:
        log.append(a)
    return log


def _supersedes(target, pending=False):
    attrs = {"pending": True} if pending else {}
    return {"relation": "supersedes", "target": target, "attrs": attrs}


# -- materialization --------------------------------------------------------------------------------


def test_fold_materializes_nodes_and_edges():
    g = fold(_log(
        _node("int:x", family="intent", attrs={"label": "goal"}),
        _node("mem:1", attrs={"statement": "do X"}, edges=[{"relation": "serves", "target": "int:x"}],
              parents=("int:x",)),
    ))
    assert g.nodes["mem:1"]["family"] == "memory"
    assert g.nodes["mem:1"]["statement"] == "do X"
    assert g.edges["mem:1", "int:x"]["relation"] == "serves"


def test_provenance_rides_onto_the_view():
    g = fold(_log(_node("mem:1", prov=[{"actor": "alice"}])))
    assert g.nodes["mem:1"]["provenance"] == [{"actor": "alice"}]


def test_fold_attaches_to_a_base_structure_graph():
    """The fold layers assertion families onto the extractor's structure graph (task #6 wiring point)."""
    base = empty_graph()
    base.add_node("sym:a.py#f", family="structure", kind="function")
    g = fold(_log(_node("mem:1", edges=[{"relation": "concerns", "target": "sym:a.py#f"}])), base=base)
    assert g.edges["mem:1", "sym:a.py#f"]["relation"] == "concerns"
    assert g is base  # mutated in place, returned as the view


# -- generalized supersedes / append discipline ----------------------------------------------------


def test_supersede_marks_target_but_keeps_it():
    """Belief revision (mem:058): the old node survives (retrievable as a rejected alternative)."""
    g = fold(_log(
        _node("mem:old", attrs={"statement": "old"}),
        _node("mem:new", attrs={"statement": "new"}, edges=[_supersedes("mem:old")],
              parents=("mem:old",)),
    ))
    assert "mem:old" in g  # NOT deleted
    assert g.nodes["mem:old"]["superseded_in"] == 1
    assert g.nodes["mem:new"]["supersedes_out"] == 1


def test_single_pass_counter_correct_when_successor_appended_first():
    """mem:056080f0's exact failure shape: the successor is appended BEFORE its target. Causal order
    (parents) still folds it after, so the inline counter is right in ONE pass — no two-pass hack."""
    successor = _node("mem:zzz", edges=[_supersedes("mem:aaa")], parents=("mem:aaa",))
    target = _node("mem:aaa")
    g = fold(_log(successor, target))  # successor appended first, and sorts last by id
    assert g.nodes["mem:aaa"]["superseded_in"] == 1
    assert g.nodes["mem:zzz"]["supersedes_out"] == 1


def test_pending_supersede_recorded_but_not_counted():
    """A supersede of a human-attested node is held pending (mem:062): edge present, target NOT demoted."""
    g = fold(_log(
        _node("mem:human", attrs={"attestation": "human"}),
        _node("mem:agent", edges=[_supersedes("mem:human", pending=True)], parents=("mem:human",)),
    ))
    assert g.edges["mem:agent", "mem:human"]["pending"] is True
    assert g.nodes["mem:human"]["superseded_in"] == 0   # stays authoritative
    assert g.nodes["mem:agent"]["supersedes_out"] == 0


def test_two_supersedes_of_one_target_accumulate():
    g = fold(_log(
        _node("mem:t"),
        _node("mem:a", edges=[_supersedes("mem:t")], parents=("mem:t",)),
        _node("mem:b", edges=[_supersedes("mem:t")], parents=("mem:t",)),
    ))
    assert g.nodes["mem:t"]["superseded_in"] == 2


# -- no phantom nodes -------------------------------------------------------------------------------


def test_unresolved_target_is_stashed_not_phantomed():
    g = fold(_log(_node("mem:1", edges=[{"relation": "serves", "target": "int:missing"}])))
    assert "int:missing" not in g               # no phantom node
    assert not g.has_edge("mem:1", "int:missing")
    assert g.nodes["mem:1"]["dangling_edges"][0]["target"] == "int:missing"


def test_denormalizing_a_dangling_contains_does_not_kill_the_fold():
    """A plan whose tasks have not arrived is the ordinary partial-replica shape, not a broken log.

    project_into never produced a dangling `contains` (a plan and its tasks come out of one file), so
    the bridge to the per-relation `dangling_*` keys had no entry for it and raised `KeyError` on the
    whole graph — turning "one edge is unresolved" into "this project has no view at all", which is
    exactly the failure stashing an unresolved edge exists to prevent.
    """
    g = fold(_log(_node("plan:a", family="plan", attrs={"kind": "plan"},
                        edges=[{"relation": "contains", "target": "task:a/1"}])))
    denormalize_danglings(g)
    assert "task:a/1" not in g                              # still no phantom task
    assert g.nodes["plan:a"]["dangling_contains"] == ["task:a/1"]


def test_an_unbridged_relation_is_stashed_rather_than_raised():
    """Fail open: a relation this module has no bridge for costs an unread attr, never the fold."""
    g = fold(_log(_node("mem:1", edges=[{"relation": "invented_later", "target": "mem:missing"}])))
    denormalize_danglings(g)
    assert g.nodes["mem:1"]["dangling_invented_later"] == ["mem:missing"]


# -- purity / determinism ---------------------------------------------------------------------------


def test_view_is_deterministic_across_append_order():
    """Same assertions, any append order ⇒ byte-identical serialized view (a pure fold, mem:059)."""
    root = _node("int:x", family="intent")
    a = _node("mem:a", edges=[{"relation": "serves", "target": "int:x"}], parents=("int:x",))
    b = _node("mem:b", edges=[_supersedes("mem:a")], parents=("mem:a",))
    forward = to_node_link(fold(_log(root, a, b)))
    shuffled = to_node_link(fold(_log(b, a, root)))
    assert forward == shuffled


def test_collapsed_provenance_reaches_the_view():
    """Independent rediscoveries collapse in the log (mem:060); the fold sees the merged provenance."""
    log = _log(
        _node("mem:1", prov=[{"actor": "alice"}]),
        _node("mem:1", prov=[{"actor": "bob"}]),
    )
    g = fold(log)
    actors = {p["actor"] for p in g.nodes["mem:1"]["provenance"]}
    assert actors == {"alice", "bob"}


# -- task #5: source claim vs. derived accepted belief ---------------------------------------------


def test_live_node_is_accepted_superseded_node_is_not():
    """`accepted` is the fold's derived verdict: live ⇒ True, counted-superseded ⇒ False (but kept)."""
    g = fold(_log(
        _node("mem:old", attrs={"statement": "old"}),
        _node("mem:new", attrs={"statement": "new"}, edges=[_supersedes("mem:old")], parents=("mem:old",)),
    ))
    assert g.nodes["mem:new"]["accepted"] is True
    assert g.nodes["mem:old"]["accepted"] is False  # retracted belief …
    assert "mem:old" in g                            # … but still present (mem:058)


def test_pending_supersede_leaves_target_accepted():
    """A pending supersede is uncounted (mem:062), so the human-attested target stays accepted."""
    g = fold(_log(
        _node("mem:human", attrs={"attestation": "human"}),
        _node("mem:agent", edges=[_supersedes("mem:human", pending=True)], parents=("mem:human",)),
    ))
    assert g.nodes["mem:human"]["accepted"] is True


def test_body_cannot_assert_its_own_belief():
    """A source claim may not smuggle derived belief: `accepted`/`superseded_in` in a body are stripped
    and the fold's own verdict wins — this is what stops a merged log from last-writer-winning belief."""
    g = fold(_log(_node("mem:1", attrs={"accepted": False, "superseded_in": 99, "statement": "x"})))
    assert g.nodes["mem:1"]["accepted"] is True      # fold's verdict, not the asserted lie
    assert g.nodes["mem:1"]["superseded_in"] == 0
    assert g.nodes["mem:1"]["statement"] == "x"      # genuine source content survives


def test_merged_logs_rederive_belief_regardless_of_merge_order():
    """Two writers' logs merged in EITHER order fold to the same view: belief is re-derived from the
    set-union of source claims, never overwritten last-writer-wins (the intent's core guarantee)."""
    # writer A introduced the claim; writer B, concurrently, superseded it.
    a = _node("mem:claim", attrs={"statement": "the claim"})
    b = _node("mem:rev", attrs={"statement": "revised"}, edges=[_supersedes("mem:claim")],
              parents=("mem:claim",))
    ab = to_node_link(fold(_log(a, b)))   # A's log merged before B's
    ba = to_node_link(fold(_log(b, a)))   # B's log merged before A's
    assert ab == ba
    g = fold(_log(b, a))
    assert g.nodes["mem:claim"]["accepted"] is False and g.nodes["mem:rev"]["accepted"] is True


# -- task #5: the reserved scope (assumption-set) rides onto the view -------------------------------


def test_scope_rides_onto_the_view_sorted():
    g = fold(_log(_node("mem:1", scope=("assume:b", "assume:a"))))
    assert g.nodes["mem:1"]["scope"] == ["assume:a", "assume:b"]


def test_collapsed_scope_reaches_the_view():
    """Same claim asserted under two environments collapses; the fold sees the unioned assumption-set."""
    g = fold(_log(
        _node("mem:1", scope=("assume:local",)),
        _node("mem:1", scope=("assume:online",)),
    ))
    assert g.nodes["mem:1"]["scope"] == ["assume:local", "assume:online"]


# --------------------------------------------------------------------------------------------------
# Revisioned families: two ids, one node — so the linearization's id tiebreak must not decide which
# --------------------------------------------------------------------------------------------------


def _revision(locator, rev, family="plan", attrs=None, actor="me@example.com"):
    """One revision of a revisioned locator: the id carries the revision, the body carries the
    locator, and ``fold._node_id`` maps every revision back onto the one node (yigraf.filelog).

    ``actor`` is load-bearing, not decoration: superseding is keyed on ``(locator, actor)``, so only a
    revision the SAME principal replaced is dropped as their own history."""
    body = {"family": family, "locator": locator, "attrs": attrs or {}, "edges": []}
    return Assertion(id=f"{locator}@{rev}", kind=family, body=body, parents=(),
                     provenance=[{"actor": actor}] if actor else [], scope=())


def test_the_newer_revision_wins_even_when_its_id_sorts_lower():
    """The regression. Two revisions of one task are causally unrelated, so the linearization called
    them concurrent and ordered them by id — a content hash. The larger hash was applied last and won,
    whatever it said. Here the NEWER revision hashes LOWER, which is the losing half of that coin flip.

    Measured live before the fix: a closed task rendered as open in exactly this case
    (``7e936ef1 < 87387891``), i.e. for about half of all closes.
    """
    graph = fold(_log(_revision("task:p/1", "ffff", attrs={"kind": "task", "state": "todo"}),
                      _revision("task:p/1", "0000", attrs={"kind": "task", "state": "done"})))
    assert graph.nodes["task:p/1"]["state"] == "done", "arrival order decides, not the id's hash"


def test_the_newer_revision_wins_when_its_id_sorts_higher_too():
    """The half that passed by luck before — it must keep passing for the same reason as the other."""
    graph = fold(_log(_revision("task:p/1", "0000", attrs={"kind": "task", "state": "todo"}),
                      _revision("task:p/1", "ffff", attrs={"kind": "task", "state": "done"})))
    assert graph.nodes["task:p/1"]["state"] == "done"


def test_a_superseded_revision_leaves_no_trace_in_the_view():
    """One locator is one node: the replaced revision is history in the log, not a second node."""
    graph = fold(_log(_revision("int:x", "aaaa", family="intent", attrs={"status": "proposed"}),
                      _revision("int:x", "bbbb", family="intent", attrs={"status": "satisfied"})))
    assert [n for n in graph.nodes if n.startswith("int:x")] == ["int:x"]
    assert graph.nodes["int:x"]["status"] == "satisfied"


def test_three_revisions_collapse_to_the_last_arrival():
    graph = fold(_log(_revision("task:p/2", "ccc", attrs={"kind": "task", "state": "todo"}),
                      _revision("task:p/2", "aaa", attrs={"kind": "task", "state": "done"}),
                      _revision("task:p/2", "bbb", attrs={"kind": "task", "state": "todo"})))
    assert graph.nodes["task:p/2"]["state"] == "todo"


def test_unrevisioned_families_still_fork_rather_than_collapse():
    """The guarantee this must not weaken: memory/resolution are content-addressed with no locator, so
    two differing bodies remain two comparable nodes for detect_conflicts (mem:c40131f8bbc3d374)."""
    graph = fold(_log(_node("mem:1", attrs={"label": "tokens never expire"}),
                      _node("mem:2", attrs={"label": "tokens expire in 30d"})))
    assert {"mem:1", "mem:2"} <= set(graph.nodes)


def test_revisions_of_different_locators_are_all_kept():
    """Only revisions of the SAME locator compete; one plan's edit never drops another's."""
    graph = fold(_log(_revision("task:p/1", "aaa", attrs={"kind": "task", "state": "todo"}),
                      _revision("task:p/2", "bbb", attrs={"kind": "task", "state": "todo"}),
                      _revision("task:p/1", "000", attrs={"kind": "task", "state": "done"})))
    assert graph.nodes["task:p/1"]["state"] == "done"
    assert graph.nodes["task:p/2"]["state"] == "todo"


def test_a_teammates_revision_is_never_dropped_by_my_later_one():
    """The guard, at the fold this time. Superseding is keyed on (locator, ACTOR), so arriving later
    than a teammate never silences them — their machine may still hold that revision, so it stays the
    open question divergence exists to raise (mem:98b78c14157ea054). Both survive the linearization;
    which one the fold then shows is the contested-revision question this fix does NOT claim to answer.
    """
    from yigraf.log import causal_order

    theirs = _revision("task:p/1", "aaa", attrs={"kind": "task", "state": "todo"},
                       actor="teammate@example.com")
    mine = _revision("task:p/1", "bbb", attrs={"kind": "task", "state": "done"})
    surviving = {a.id for a in causal_order([theirs, mine])}
    assert surviving == {theirs.id, mine.id}, "a different principal's revision is never superseded"


def test_a_revision_without_a_named_actor_is_never_dropped():
    """No actor means no way to know it is the same author's own history, so it is left alone."""
    from yigraf.log import causal_order

    a = _revision("task:p/1", "fff", attrs={"kind": "task", "state": "todo"}, actor=None)
    b = _revision("task:p/1", "000", attrs={"kind": "task", "state": "done"}, actor=None)
    assert {x.id for x in causal_order([a, b])} == {a.id, b.id}

"""Maturity, telemetry, and GC — v0 keeps graph.json recomputable (DESIGN R1/R2/R3).

Covers: maturity is **git-derived** (settled after K commits un-superseded, recomputed each build, never
a stored counter); telemetry (usage/last_seen) lives in the **gitignored sidecar**, never in
graph.json; recency + maturity lift the relevance prior; GC **archives** superseded churn (never
deletes, never gates on usage); and the union driver merges two graph.json without conflict.

The shared-committed-counter model (accumulated survival/usage in graph.json + a counter-reconciling
merge driver) is v1/Enterprise — explicitly out of scope here.
"""
import json
import re
import subprocess
from pathlib import Path

import networkx as nx
from typer.testing import CliRunner

from yigraf import counters, retrieval
from yigraf.cli import app
from yigraf.config import default_config, load_config
from yigraf.extract import build_graph
from yigraf import graphdb
from yigraf.graph import read_graph, to_node_link


def _read_with_verdict(root: Path):
    """Read-path graph: overlay the sidecar (usage/last_seen/upholds) + resolve the maturity verdict."""
    cfg = load_config(root / "yigraf" / "config.yaml")
    g, _ = build_graph(root, cfg)
    counters.apply_telemetry(g, counters.load_telemetry(root))
    counters.apply_maturity_verdict(g, cfg)
    return g

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "auth/session.py"


def _repo(tmp_path: Path) -> Path:
    """An initialized, built repo with one symbol and one active intent (mirrors test_memory)."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "session-expiry", "--repo", str(tmp_path),
                               "-s", "Sessions SHALL expire after 30m idle.",
                               "--scenario", "Given idle 30m, When a request arrives, Then 401.",
                               "--status", "active"]).exit_code == 0
    return tmp_path


def _run(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def _graph(root: Path):
    return graphdb.load_workspace(root)


def _mem_graph(**overrides) -> nx.DiGraph:
    """A tiny in-memory graph: one active memory node, attrs overridable per test."""
    g = nx.DiGraph()
    attrs = {"maturity": "working", **overrides}
    g.add_node("mem:001", family="memory", kind="decision", **attrs)
    return g


def _git_init(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)


def _commit(root: Path, msg: str) -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", msg, "--allow-empty"], check=True)


# --------------------------------------------------------------------------------------------------
# Maturity — git-derived, settles at K, self-healing (R2)
# --------------------------------------------------------------------------------------------------


def test_build_maturity_lands_working_regardless_of_git_survival(monkeypatch):
    """mem:033: promotion is no longer git-derived — build stamps survival + the landed base only.

    An agent-asserted node (no proposed-source provenance) lands ``working`` no matter its git age."""
    monkeypatch.setattr(counters, "_survival_map", lambda root, paths: {p: 99 for p in paths})
    g = _mem_graph(source_file="memory/001-x.md")
    counters.apply_maturity(g, Path("."), {"maturity_k": 3})
    assert g.nodes["mem:001"]["survival"] == 99 and g.nodes["mem:001"]["maturity"] == "working"


def test_build_maturity_lands_proposed_for_mined_provenance(monkeypatch):
    """task #1: a mined/review candidate lands ``proposed`` — derived from committed provenance (R1)."""
    monkeypatch.setattr(counters, "_survival_map", lambda root, paths: {p: 99 for p in paths})
    g = _mem_graph(source_file="memory/001-x.md", provenance={"source": "mined"})
    counters.apply_maturity(g, Path("."), {"maturity_k": 3})
    assert g.nodes["mem:001"]["maturity"] == "proposed"


def test_survival_is_not_persisted_to_the_materialized_view(tmp_path: Path):
    """mem:034 #10: git-derived ``survival`` moved every commit, churning the projection for no default
    gain (the floor defaults off). It's stripped at serialization — the persisted view carries none,
    while the in-memory build still stamps it so the optional floor + proposed-TTL clock work."""
    root = _repo(tmp_path)
    _run(["remember", "refresh returns its token unchanged", "--repo", str(root),
          "--concerns", SYM, "--new"])
    persisted = graphdb.load_workspace(root)  # the gitignored SQLite view
    assert all("survival" not in a for _, a in persisted.nodes(data=True))  # no churn source persisted
    g, _ = build_graph(root, default_config())
    mem_nodes = [n for n, a in g.nodes(data=True) if a.get("family") == "memory"]
    assert mem_nodes and all("survival" in g.nodes[n] for n in mem_nodes)  # in-memory graph still has it


def test_verdict_proposed_stays_until_confirmed():
    """task #1: an un-confirmed candidate (no uphold) stays ``proposed`` — near-zero weight."""
    g = _mem_graph(maturity="proposed", upholds=0.0)
    counters.apply_maturity_verdict(g, {"maturity_k": 3, "maturity_confirm": 1.0})
    assert g.nodes["mem:001"]["maturity"] == "proposed"


def test_verdict_first_encounter_confirms_proposed_to_working():
    """task #1: the first real encounter (uphold ≥ maturity_confirm) graduates proposed → working."""
    g = _mem_graph(maturity="proposed", upholds=1.0)
    counters.apply_maturity_verdict(g, {"maturity_k": 3, "maturity_confirm": 1.0})
    assert g.nodes["mem:001"]["maturity"] == "working"


def test_verdict_settles_from_upholds():
    """The read-time verdict: enough accumulated survived-encounter upholds ⇒ settled (mem:033)."""
    g = _mem_graph(upholds=3.0, survival=0)
    counters.apply_maturity_verdict(g, {"maturity_k": 3})
    assert g.nodes["mem:001"]["maturity"] == "settled"


def test_verdict_stays_working_below_the_uphold_threshold():
    g = _mem_graph(upholds=2.5)
    counters.apply_maturity_verdict(g, {"maturity_k": 3})
    assert g.nodes["mem:001"]["maturity"] == "working"


def test_verdict_superseded_never_settles():
    g = _mem_graph(upholds=99, superseded_in=1)
    counters.apply_maturity_verdict(g, {"maturity_k": 3})
    assert g.nodes["mem:001"]["maturity"] == "working"


def test_verdict_optional_survival_floor_gates_promotion():
    """With a floor configured, settled also requires git-durability — enough upholds isn't sufficient."""
    g = _mem_graph(upholds=99, survival=1)
    counters.apply_maturity_verdict(g, {"maturity_k": 3, "maturity_survival_floor": 5})
    assert g.nodes["mem:001"]["maturity"] == "working"  # survival 1 < floor 5
    g2 = _mem_graph(upholds=99, survival=9)
    counters.apply_maturity_verdict(g2, {"maturity_k": 3, "maturity_survival_floor": 5})
    assert g2.nodes["mem:001"]["maturity"] == "settled"


def test_decision_settles_after_enough_reaffirm_upholds(tmp_path: Path):
    """The end-to-end done-test: a decision reaffirmed K times is settled at read time (mem:033)."""
    root = _repo(tmp_path)
    out = _run(["remember", "refresh uses optimistic locking", "--concerns", SYM, "--repo", str(root)]).output
    mem = re.search(r"Captured (mem:[0-9a-f]{16})", out).group(1)
    assert _read_with_verdict(root).nodes[mem]["maturity"] == "working"  # no upholds yet

    for _ in range(3):  # each reaffirm books a strong uphold (~1.0); K=3 ⇒ settled
        _run(["reaffirm", mem, "--repo", str(root)])
    assert _read_with_verdict(root).nodes[mem]["maturity"] == "settled"


def test_survival_is_head_cached_to_skip_the_walk(tmp_path: Path, monkeypatch):
    """The perf fix (caveats.md M9): on an unchanged HEAD the git history walk is skipped entirely."""
    from yigraf.cache import StructureCache

    cache = StructureCache(algo="x", entries={})
    walks: list[int] = []
    monkeypatch.setattr(counters, "_head_sha", lambda root: "HEAD1")
    monkeypatch.setattr(counters, "_survival_map",
                        lambda root, paths: (walks.append(1), {p: 5 for p in paths})[1])
    g = _mem_graph(source_file="memory/001-x.md")

    counters.apply_maturity(g, tmp_path, {"maturity_k": 3}, cache=cache)
    counters.apply_maturity(g, tmp_path, {"maturity_k": 3}, cache=cache)  # same HEAD → served from cache

    assert len(walks) == 1                                                  # only the first build walked git
    assert g.nodes["mem:001"]["survival"] == 5
    assert cache.maturity_survival("HEAD1") == {"yigraf/memory/001-x.md": 5}


def test_survival_recomputes_when_head_moves(tmp_path: Path, monkeypatch):
    """A commit moves HEAD, invalidating the cached survival so maturity re-derives from history."""
    from yigraf.cache import StructureCache

    cache = StructureCache(algo="x", entries={})
    heads = iter(["HEAD1", "HEAD2"])
    walks: list[int] = []
    monkeypatch.setattr(counters, "_head_sha", lambda root: next(heads))
    monkeypatch.setattr(counters, "_survival_map",
                        lambda root, paths: (walks.append(1), {p: len(walks) for p in paths})[1])
    g = _mem_graph(source_file="memory/001-x.md")

    counters.apply_maturity(g, tmp_path, {"maturity_k": 9}, cache=cache)
    counters.apply_maturity(g, tmp_path, {"maturity_k": 9}, cache=cache)  # HEAD changed → re-walk

    assert len(walks) == 2


def test_structure_cache_round_trips_maturity(tmp_path: Path):
    """The HEAD-keyed survival map survives a save/load (it lives in the gitignored structure cache)."""
    from yigraf.cache import StructureCache

    cache = StructureCache.load(tmp_path / "absent.json")  # empty, but with the live algo so load accepts it back
    cache.set_maturity_survival("HEADX", {"yigraf/memory/001-x.md": 7})
    path = tmp_path / "structure.json"
    cache.save(path)
    assert StructureCache.load(path).maturity_survival("HEADX") == {"yigraf/memory/001-x.md": 7}


# --------------------------------------------------------------------------------------------------
# The shared log's clock — survival for a belief that arrived over the wire (team-reconciliation #7)
# --------------------------------------------------------------------------------------------------


def _event(seq: int, node_id: str, session: str):
    """The two fields the log clock reads off a :class:`~yigraf.onlinelog.StoredEvent`."""
    from types import SimpleNamespace

    return SimpleNamespace(seq=seq, id=node_id, provenance={"session": session, "actor": "a@b.c"})


def test_log_survival_ages_a_belief_by_later_appends():
    """The log is the history a synced belief lives in; its ``seq`` order is that belief's clock."""
    events = [_event(1, "mem:a", "s1"), _event(2, "mem:b", "s2"), _event(3, "mem:c", "s3")]
    assert counters._log_survival(events) == {"mem:a": 2, "mem:b": 1, "mem:c": 0}


def test_a_backfill_push_does_not_age_its_own_siblings():
    """One push is one authoring act, not history (task #7).

    Adopting the shared log sends the whole backlog in a single sync run. Counting raw ``head - seq``
    would hand the first of them an instant survival of N-1 — and ``proposed_ttl`` would then archive
    mined candidates that landed seconds ago. Siblings of one session do not age each other; a genuinely
    later push does."""
    backfill = [_event(i, f"mem:{i}", "sync-backfill") for i in range(1, 4)]
    assert counters._log_survival(backfill) == {"mem:1": 0, "mem:2": 0, "mem:3": 0}
    later = counters._log_survival(backfill + [_event(4, "mem:4", "sync-later")])
    assert later["mem:1"] == 1 and later["mem:4"] == 0


def test_a_sessionless_event_never_masks_another():
    """Absent ``session`` falls back to a per-event sentinel, so unattributed events still age each
    other — the conservative direction (it can only under-count, never inflate)."""
    from types import SimpleNamespace

    events = [SimpleNamespace(seq=i, id=f"mem:{i}", provenance={}) for i in (1, 2, 3)]
    assert counters._log_survival(events) == {"mem:1": 2, "mem:2": 1, "mem:3": 0}


def test_a_re_assertion_does_not_reset_a_standing_belief():
    """mem:060: an independent rediscovery unions provenance onto a belief that has been standing —
    the FIRST landing is when the claim entered the shared history, so that is what the clock counts."""
    events = [_event(1, "mem:a", "s1"), _event(2, "mem:x", "s2"), _event(3, "mem:a", "s3")]
    assert counters._log_survival(events)["mem:a"] == 2


def test_log_survival_is_silent_for_an_offline_workspace(tmp_path: Path):
    """No ``online.project`` ⇒ no I/O at all, so an offline workspace keeps the git clock exactly."""
    assert counters.log_survival(tmp_path, {}) == {}
    assert counters.log_survival(tmp_path, {"online": {"project": "p"}}) == {}  # replica absent


def test_a_corrupt_replica_degrades_to_the_git_clock(tmp_path: Path):
    """Fail-open (design law #5): a broken replica must never break the build."""
    replica = tmp_path / "yigraf" / "cache" / "replica.db"
    replica.parent.mkdir(parents=True)
    replica.write_bytes(b"not a sqlite database")
    assert counters.log_survival(tmp_path, {"online": {"project": "p"}}) == {}


def test_survival_takes_the_stronger_of_the_two_clocks(monkeypatch):
    """Each clock is blind to what the other saw, so each can only under-count: git scores a teammate's
    belief 0 (no file here), the log scores a long-committed local belief 0 (it only just arrived on the
    wire). Two lower bounds on one quantity ⇒ take the larger, so a synced belief stops reading as
    permanently immature AND adopting a shared log never resets durability already earned in git."""
    monkeypatch.setattr(counters, "_survival_map", lambda root, paths: {p: 4 for p in paths})
    monkeypatch.setattr(counters, "log_survival",
                        lambda root, config: {"mem:001": 11, "mem:003": 0})
    g = _mem_graph(source_file="memory/001-x.md")
    g.add_node("mem:002", family="memory", kind="decision", source_file="memory/002-y.md")
    g.add_node("mem:003", family="memory", kind="decision", source_file="memory/003-z.md")
    counters.apply_maturity(g, Path("."), {"maturity_k": 3})
    assert g.nodes["mem:001"]["survival"] == 11  # the log has seen more of it
    assert g.nodes["mem:002"]["survival"] == 4  # never pushed ⇒ the git clock, exactly as before
    assert g.nodes["mem:003"]["survival"] == 4  # freshly pushed, but git's durability is not undone


def test_a_teammates_belief_is_no_longer_permanently_immature(monkeypatch):
    """The bug task #7 names: with no local artifact there is no path to score, so git returns 0 forever
    however long the belief has stood in the log."""
    monkeypatch.setattr(counters, "_survival_map", lambda root, paths: {})
    monkeypatch.setattr(counters, "log_survival", lambda root, config: {"mem:001": 7})
    g = _mem_graph(source_file="memory/001-theirs.md")
    counters.apply_maturity(g, Path("."), {"maturity_k": 3})
    assert g.nodes["mem:001"]["survival"] == 7


# --------------------------------------------------------------------------------------------------
# Relevance terms — recency + maturity lift the prior
# --------------------------------------------------------------------------------------------------


def test_recency_decays_from_one():
    assert counters.recency(1000, now=1000, half_life_days=14) == 1.0
    assert counters.recency(None, now=1000, half_life_days=14) == 0.0
    week = counters.recency(1000, now=1000 + 7 * 86400, half_life_days=14)
    assert 0.6 < week < 0.8  # half a half-life → ~0.71


def test_settled_memory_outranks_a_working_twin():
    g = nx.DiGraph()
    for nid, mat in (("mem:settled", "settled"), ("mem:working", "working")):
        g.add_node(nid, family="memory", kind="decision", maturity=mat)
    cfg = default_config()
    assert retrieval._relevance(g, "mem:settled", cfg, now=1000.0) > \
           retrieval._relevance(g, "mem:working", cfg, now=1000.0)


def test_proposed_candidate_ranks_below_a_working_twin():
    """task #1: a ``proposed`` candidate carries near-zero weight — docked well under a working belief."""
    g = nx.DiGraph()
    for nid, mat in (("mem:working", "working"), ("mem:proposed", "proposed")):
        g.add_node(nid, family="memory", kind="decision", maturity=mat)
    cfg = default_config()
    assert retrieval._relevance(g, "mem:proposed", cfg, now=1000.0) < \
           retrieval._relevance(g, "mem:working", cfg, now=1000.0)


# --------------------------------------------------------------------------------------------------
# Telemetry — gitignored sidecar, never in graph.json (R1)
# --------------------------------------------------------------------------------------------------


def test_record_injection_writes_sidecar_scoped_to_memory_and_intent(tmp_path: Path):
    g = nx.DiGraph()
    g.add_node("mem:001", family="memory")
    g.add_node("int:x", family="intent")
    g.add_node("sym:a#f", family="structure")
    bumped = counters.record_injection(tmp_path, g, ["mem:001", "int:x", "sym:a#f"], now=4242)

    assert set(bumped) == {"mem:001", "int:x"}  # structure is ranked by refs_in, never recorded
    tele = counters.load_telemetry(tmp_path)
    assert tele["mem:001"] == {"usage": 1, "last_seen": 4242} and "sym:a#f" not in tele
    assert "usage" not in g.nodes["mem:001"]  # the graph itself isn't mutated — only the sidecar


def test_apply_telemetry_overlays_for_ranking():
    g = _mem_graph()
    counters.apply_telemetry(g, {"mem:001": {"usage": 3, "last_seen": 111}})
    assert g.nodes["mem:001"]["last_seen"] == 111 and g.nodes["mem:001"]["usage"] == 3


def test_context_records_telemetry_without_dirtying_graph_json(tmp_path: Path):
    root = _repo(tmp_path)
    out = _run(["remember", "refresh uses optimistic locking", "--why", "the hot path",
                "--concerns", SYM, "--repo", str(root)]).output
    mem = re.search(r"Captured (mem:[0-9a-f]{16})", out).group(1)

    _run(["context", "optimistic locking refresh", "--repo", str(root)])
    tele = counters.load_telemetry(root)
    assert tele.get(mem, {}).get("usage", 0) >= 1  # surfacing recorded in the sidecar

    # graph.json holds no runtime telemetry — it stays fully recomputable, across rebuilds.
    _run(["build", str(root)])
    for _, attrs in _graph(root).nodes(data=True):
        assert "usage" not in attrs and "last_seen" not in attrs


# --------------------------------------------------------------------------------------------------
# GC — archive churn, never delete, never gate on usage (R3)
# --------------------------------------------------------------------------------------------------


def test_classify_gc_archives_only_superseded_churn():
    g = nx.DiGraph()
    g.add_node("mem:churn", family="memory", superseded_in=1)             # superseded, unreferenced
    g.add_node("mem:ref", family="memory", superseded_in=1)               # superseded but referenced
    g.add_node("mem:active", family="memory")                             # not superseded
    g.add_node("task:p/1", family="plan")
    g.add_edge("task:p/1", "mem:ref", relation="references")
    assert counters.classify_gc(g) == {"mem:churn": "superseded-churn"}   # only churn


def test_classify_gc_expires_abandoned_proposed_past_ttl():
    """task #7: a never-confirmed proposed candidate aged past the TTL is archived — silence expires it."""
    g = nx.DiGraph()
    g.add_node("mem:old", family="memory", maturity="proposed", survival=40)   # abandoned, old
    g.add_node("mem:fresh", family="memory", maturity="proposed", survival=5)  # too young — spared
    g.add_node("mem:confirmed", family="memory", maturity="working", survival=40)  # confirmed → graduated
    cfg = {"proposed_ttl": 30}
    assert counters.classify_gc(g, cfg) == {"mem:old": "abandoned-proposed"}


def test_classify_gc_never_expires_a_working_or_settled_decision_by_silence():
    """The load-bearing guarantee (mem:033): only the quarantine tier expires by silence."""
    g = nx.DiGraph()
    for nid, mat in (("mem:w", "working"), ("mem:s", "settled")):
        g.add_node(nid, family="memory", maturity=mat, survival=9999)  # ancient, untouched
    assert counters.classify_gc(g, {"proposed_ttl": 1}) == {}


def test_classify_gc_spares_a_referenced_proposed_candidate():
    g = nx.DiGraph()
    g.add_node("mem:p", family="memory", maturity="proposed", survival=40)
    g.add_node("task:p/1", family="plan")
    g.add_edge("task:p/1", "mem:p", relation="references")  # something points at it → keep
    assert counters.classify_gc(g, {"proposed_ttl": 30}) == {}


def test_gc_archives_superseded_churn_without_deleting(tmp_path: Path):
    root = _repo(tmp_path)
    out = _run(["remember", "refresh uses optimistic locking", "--concerns", SYM, "--repo", str(root)]).output
    mem = re.search(r"Captured (mem:[0-9a-f]{16})", out).group(1)
    _run(["supersede", mem, "refresh uses pessimistic locking", "--concerns", SYM, "--repo", str(root)])

    dry = _run(["gc", str(root)])
    assert "Dry run" in dry.output and f"{mem} → archive" in dry.output

    _run(["gc", str(root), "--apply"])
    g = _graph(root)
    assert mem not in g                                                  # dropped from the active graph
    archived = list((root / "yigraf" / "memory" / "archive").glob("*.md"))
    assert len(archived) == 1 and "optimistic" in archived[0].name        # moved, not deleted


def test_gc_expires_abandoned_proposed_but_spares_a_confirmed_one(tmp_path: Path, monkeypatch):
    """task #7 done-test: the gc verb overlays the maturity verdict, so a candidate a real encounter
    confirmed (upholds ≥ maturity_confirm → working) is spared, while a never-encountered one expires."""
    monkeypatch.setattr(counters, "_survival_map", lambda root, paths: {p: 99 for p in paths})  # all old (≥ ttl 30)
    root = _repo(tmp_path)
    o1 = _run(["propose", "confirmed candidate", "--from", "mined", "--concerns", SYM, "--repo", str(root)]).output
    confirmed = re.search(r"Captured (mem:[0-9a-f]{16})", o1).group(1)   # the confirmed candidate
    o2 = _run(["propose", "abandoned candidate", "--from", "mined", "--concerns", SYM, "--repo", str(root)]).output
    abandoned = re.search(r"Captured (mem:[0-9a-f]{16})", o2).group(1)   # the abandoned candidate

    g, _ = build_graph(root, load_config(root / "yigraf" / "config.yaml"))
    counters.record_uphold(root, g, [confirmed], 1.0)  # a real encounter confirms it (≥ maturity_confirm)

    out = _run(["gc", str(root), "--apply"]).output
    assert f"{abandoned} → archive (abandoned proposed" in out and confirmed not in out  # only the abandoned one
    g2 = _graph(root)
    assert confirmed in g2 and abandoned not in g2  # confirmed spared; abandoned dropped from the active graph
    assert any("abandoned" in p.name for p in (root / "yigraf" / "memory" / "archive").glob("*.md"))


# --------------------------------------------------------------------------------------------------
# Union-merge driver — unions nodes+edges (no counter reconciliation in v0)
# --------------------------------------------------------------------------------------------------


def _nl(node_attrs: dict, edges: list[tuple] = ()) -> dict:
    g = nx.DiGraph()
    for nid, attrs in node_attrs.items():
        g.add_node(nid, **attrs)
    for s, t in edges:
        g.add_edge(s, t, relation="serves")
    return to_node_link(g)


def test_merge_unions_nodes_and_edges():
    ours = _nl({"mem:001": {"family": "memory"}, "int:x": {"family": "intent"}},
               edges=[("mem:001", "int:x")])
    theirs = _nl({"mem:002": {"family": "memory"}, "int:x": {"family": "intent"}})
    merged = counters.merge_node_link(ours, theirs)
    ids = {n["id"] for n in merged["nodes"]}
    assert {"mem:001", "mem:002", "int:x"} <= ids                         # union — never drops a node


def test_graph_merge_cli_unions_two_branches(tmp_path: Path):
    ours = _nl({"mem:001": {"family": "memory"}})
    theirs = _nl({"mem:002": {"family": "memory"}})
    paths = {}
    for name, data in (("base", {}), ("ours", ours), ("theirs", theirs)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(data) if data else "{}")
        paths[name] = p
    _run(["graph-merge", str(paths["base"]), str(paths["ours"]), str(paths["theirs"])])
    merged = read_graph(paths["ours"])  # driver writes the union back to %A (ours)
    assert "mem:001" in merged and "mem:002" in merged


def test_install_hooks_registers_no_merge_driver(tmp_path: Path):
    """The committed graph.json + its union-merge driver are retired (mem:059): the projection is a
    gitignored SQLite view, so there is nothing to merge and install-hooks registers no driver."""
    _git_init(tmp_path)
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    result = _run(["install-hooks", str(tmp_path)])
    assert "merge" not in result.output.lower()
    got = subprocess.run(["git", "-C", str(tmp_path), "config", "merge.yigraf-graph.driver"],
                         capture_output=True, text=True)
    assert got.returncode != 0 and not got.stdout.strip()  # never registered

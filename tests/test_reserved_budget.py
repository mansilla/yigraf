"""Reserved per-family budget shares + the why-injected provenance annotation (epistemic-control-plane
task 4), and the task-7 invariant it must uphold: *budget reduction never drops the sole explanation of
a shown conflict*.

These drive :func:`yigraf.retrieval._render` directly with a hand-built graph + an explicit ``ranked``
order, so the budget logic is isolated from seeding/ranking. Line costs are deliberately uniform so the
starvation the reserved share prevents is arithmetic, not incidental.
"""
from pathlib import Path

import networkx as nx
from typer.testing import CliRunner

from yigraf import retrieval
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.extract import build_graph

runner = CliRunner()


def _struct(g: nx.DiGraph, n: int) -> list[str]:
    """`n` structure symbols with uniform-length signature lines (so budgeting is arithmetic)."""
    ids = []
    for i in range(n):
        nid = f"sym:pkg/mod.py#fn{i:02d}"
        g.add_node(nid, family="structure", kind="function", signature=f"def fn{i:02d}(): pad_padding")
        ids.append(nid)
    return ids


def _render(graph, ranked, budget_tokens, **kw):
    return retrieval._render(graph, ranked, "q", [], [], budget_tokens,
                             config=default_config(), **kw)


# --- Reserved per-family shares --------------------------------------------------------------------

def test_reserved_share_keeps_a_code_flood_from_starving_the_why_family():
    """A flood of top-ranked code symbols must not crowd the one decision out of the packet: the memory
    family's reserved floor guarantees it renders even though every structure node outranks it."""
    g = nx.DiGraph()
    struct = _struct(g, 15)
    g.add_node("mem:keep", family="memory", kind="decision", statement="THE_ONE_DECISION")
    ranked = struct + ["mem:keep"]            # every code symbol ranks ahead of the decision
    result = _render(g, ranked, budget_tokens=100)  # only ~a third of the flood fits
    assert "THE_ONE_DECISION" in result.text        # the reserved memory share saved it
    assert result.nodes_rendered < result.nodes_total and "elided" in result.text  # code was truly capped


def test_unused_shares_flow_to_the_only_family_present():
    """Shares are floors, not partitions: a single-family (all-structure) slice fills the whole budget
    via the leftover pass — a family's unused reserve is never wasted (design law #2)."""
    g = nx.DiGraph()
    ranked = _struct(g, 6)
    result = _render(g, ranked, budget_tokens=4000)  # roomy
    assert result.nodes_rendered == 6  # not clamped to structure's 30% share


# --- Task-7 invariant: never drop the sole explanation of a shown conflict -------------------------

def _mem_flood(g: nx.DiGraph, n: int) -> list[str]:
    """`n` filler decisions, uniform-length lines — enough to exhaust the memory family's own share."""
    ids = []
    for i in range(n):
        nid = f"mem:m{i:02d}"
        g.add_node(nid, family="memory", kind="decision", statement="filler_decision_body")
        ids.append(nid)
    return ids


def test_budget_reduction_never_drops_the_explanation_of_a_shown_conflict():
    """The pinned-explanation guarantee (task-7 invariant): a conflict line names mem:conflicted, and it
    is the LAST-ranked memory behind a flood of its own family — so its family share alone can't save it.
    Only the pin does: its own render line (its statement) must still appear, so the agent sees *what*
    the conflicting belief says, not merely that a conflict exists."""
    g = nx.DiGraph()
    flood = _mem_flood(g, 11)
    g.add_node("mem:conflicted", family="memory", kind="decision", statement="UNIQUE_CONFLICT_BODY")
    ranked = flood + ["mem:conflicted"]  # ranked last, behind its own family → rank-order fill drops it
    conflict = ["  ⚠ mem:new pending-supersedes human-attested mem:conflicted — resolve by attesting it."]
    result = _render(g, ranked, budget_tokens=80, conflict_lines=conflict)
    assert "UNIQUE_CONFLICT_BODY" in result.text  # the node itself rendered (pinned), not just named


def test_without_the_pin_a_tail_ranked_node_is_elided_under_the_same_budget():
    """Control for the pin test: the same last-ranked memory behind the same family flood, with no
    signal line naming it, IS elided — proving the pin test passes *because* of the pin, not the share."""
    g = nx.DiGraph()
    flood = _mem_flood(g, 11)
    g.add_node("mem:tail", family="memory", kind="decision", statement="UNPINNED_BODY")
    ranked = flood + ["mem:tail"]
    # A same-length reserved line naming something else, so the budget math matches the pin test.
    other = ["  ⚠ mem:new pending-supersedes human-attested mem:elsewhere — resolve by attesting it. "]
    result = _render(g, ranked, budget_tokens=80, conflict_lines=other)
    assert "UNPINNED_BODY" not in result.text  # last behind its family flood, unpinned → dropped


# --- The why-injected provenance annotation --------------------------------------------------------

def test_provenance_names_the_justifying_edge_for_a_structure_node():
    g = nx.DiGraph()
    g.add_node("sym:a.py#f", family="structure", kind="function")
    g.add_node("task:p/1", family="plan", kind="task")
    parent = {"sym:a.py#f": ("task:p/1", "implements")}
    assert retrieval._provenance(g, "sym:a.py#f", parent, {"task:p/1"}) == "via implements task:p/1"


def test_provenance_is_silent_for_a_seed_and_for_an_off_packet_parent():
    g = nx.DiGraph()
    g.add_node("sym:a.py#f", family="structure", kind="function")
    assert retrieval._provenance(g, "sym:a.py#f", {}, set()) == ""  # no parent ⇒ a seed
    parent = {"sym:a.py#f": ("task:p/1", "implements")}
    assert retrieval._provenance(g, "sym:a.py#f", parent, set()) == ""  # parent not a render candidate


def test_provenance_is_silent_for_non_structure_families():
    """A memory/task/intent line already shows its links — a provenance clause would be redundant noise."""
    g = nx.DiGraph()
    g.add_node("mem:1", family="memory", kind="decision")
    parent = {"mem:1": ("int:x", "serves")}
    assert retrieval._provenance(g, "mem:1", parent, {"int:x"}) == ""


# --- End-to-end: the annotation reaches real `context` output --------------------------------------

SYM = "sym:auth/session.py#refresh"


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "session-expiry", "--repo", str(tmp_path),
                               "-s", "The system SHALL expire a session after 30m idle."]).exit_code == 0
    assert runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth",
                               "--task", "implement idle expiry"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", "int:session-expiry", "--repo", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)]).exit_code == 0
    return tmp_path


def test_context_annotates_a_symbol_with_why_it_surfaced(tmp_path: Path):
    """The implementing symbol carries its retrieval justification, attributed to the task that named
    it — the 'why is this in front of me' the agent otherwise has to reconstruct."""
    root = _repo(tmp_path)
    graph, _ = build_graph(root, default_config())
    # Query the intent's words, NOT the file path: "session" is in auth/session.py, which would make the
    # symbol a query seed (no parent, no provenance). "expire idle" hits the intent and reaches the
    # symbol only over int→task(tracks)→sym(implements).
    text = retrieval.context(graph, "expire idle", default_config()).text
    assert SYM in text                             # the symbol surfaced (2 hops from the intent)
    assert "via implements task:auth/1" in text    # …carrying its retrieval justification

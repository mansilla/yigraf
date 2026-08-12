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

#: Budget for the pin/control pair: tight enough that the 11-memory flood still exhausts it before the
#: 12th (so the control's unpinned tail is genuinely elided), loose enough to clear the render *frame*.
#: It was 80, from when the frame — the query line, block and family headings, the elision tail — was
#: not charged to the budget at all; 80 tokens is now less than the frame alone, so every node dropped
#: and the pair asserted nothing. The invariant under test is unchanged; only the operating point moved.
_TIGHT_BUDGET = 120

#: Body text for the flood and for the two tail nodes, held to ONE width on purpose. The module docstring
#: promises line costs are uniform "so the starvation is arithmetic, not incidental", and the control
#: silently broke that: its tail body was 7 chars shorter than the filler, so at some budgets the tail
#: squeezed into a gap no filler line could fit and the control passed or failed on alignment luck rather
#: than on the pin. Equal widths make "the flood exhausts the budget before the 12th node" monotonic.
_FILLER_BODY = "filler_decision_body"
_PINNED_BODY = "UNIQUE_CONFLICT_BODY"
_TAIL_BODY = "unpinned_decision_00"


def _mem_flood(g: nx.DiGraph, n: int) -> list[str]:
    """`n` filler decisions, uniform-length lines — enough to exhaust the memory family's own share."""
    ids = []
    for i in range(n):
        nid = f"mem:m{i:02d}"
        g.add_node(nid, family="memory", kind="decision", statement=_FILLER_BODY)
        ids.append(nid)
    return ids


def test_budget_reduction_never_drops_the_explanation_of_a_shown_conflict():
    """The pinned-explanation guarantee (task-7 invariant): a conflict line names mem:conflicted, and it
    is the LAST-ranked memory behind a flood of its own family — so its family share alone can't save it.
    Only the pin does: its own render line (its statement) must still appear, so the agent sees *what*
    the conflicting belief says, not merely that a conflict exists."""
    g = nx.DiGraph()
    flood = _mem_flood(g, 11)
    g.add_node("mem:conflicted", family="memory", kind="decision", statement=_PINNED_BODY)
    ranked = flood + ["mem:conflicted"]  # ranked last, behind its own family → rank-order fill drops it
    conflict = ["  ⚠ mem:new pending-supersedes human-attested mem:conflicted — resolve by attesting it."]
    result = _render(g, ranked, budget_tokens=_TIGHT_BUDGET, conflict_lines=conflict)
    assert _PINNED_BODY in result.text  # the node itself rendered (pinned), not just named


def test_without_the_pin_a_tail_ranked_node_is_elided_under_the_same_budget():
    """Control for the pin test: the same last-ranked memory behind the same family flood, with no
    signal line naming it, IS elided — proving the pin test passes *because* of the pin, not the share."""
    g = nx.DiGraph()
    flood = _mem_flood(g, 11)
    # id width matches the flood's too, so the whole render line is the same cost.
    g.add_node("mem:t00", family="memory", kind="decision", statement=_TAIL_BODY)
    ranked = flood + ["mem:t00"]
    # A same-length reserved line naming something else, so the budget math matches the pin test.
    other = ["  ⚠ mem:new pending-supersedes human-attested mem:elsewhere — resolve by attesting it. "]
    result = _render(g, ranked, budget_tokens=_TIGHT_BUDGET, conflict_lines=other)
    assert _TAIL_BODY not in result.text  # last behind its family flood, unpinned → dropped


# --- The signal blocks are bounded too, or they starve the nodes -----------------------------------

def _groups(n_intents: int, per_intent: int = 3) -> list[list[str]]:
    """`n_intents` governing intents, each owing `per_intent` criteria of realistic length."""
    return [[f"  ✔ int:i{i:02d}: Given a precondition {j}, When the edit lands, Then the contract holds."
             for j in range(per_intent)] for i in range(n_intents)]


def test_a_heavily_governed_locus_stays_in_budget_and_still_renders_nodes():
    """The regression this bound exists for. The ✔ obligation block was emitted in full, *outside* the
    budget: `used` started past `char_budget`, so every node then failed the fit test and the packet
    shipped anyway. Measured on yigraf's own cli.py: 3833 tokens against an 800 budget, 0 of 86 nodes —
    the more governed a file was, the less context its agent got. Both halves are asserted, because
    either alone is satisfiable by a degenerate render (emit nothing / ignore the budget)."""
    g = nx.DiGraph()
    ranked = _mem_flood(g, 8)
    result = _render(g, ranked, budget_tokens=800, obligation_groups=_groups(15))
    assert result.token_estimate <= 800     # the block can no longer overrun the packet
    assert result.nodes_rendered > 0        # and no longer starves every node out of it


def test_obligation_elision_counts_what_it_dropped_and_where_to_read_it():
    """An elided obligation is not a silently shorter list: the tail names how many criteria across how
    many intents went unsaid, so the agent knows the block is a top slice rather than the whole
    contract set — the honest-count rule the node elision line already follows."""
    result = _render(nx.DiGraph(), [], budget_tokens=200, obligation_groups=_groups(12))
    assert "more criteria across" in result.text
    assert "intent(s)" in result.text


def test_whole_intents_go_in_or_out_never_a_partial_criteria_set():
    """Truncation is at intent granularity. Half a contract's criteria reads as "these are the
    obligations" and would ship code against the criteria it didn't print — strictly worse than a
    count. So any intent that appears at all appears with every criterion it owns."""
    groups = _groups(12, per_intent=4)
    text = _render(nx.DiGraph(), [], budget_tokens=300, obligation_groups=groups).text
    fully_shown = 0
    for group in groups:
        shown = [line for line in group if line in text]
        assert len(shown) in (0, len(group)), f"partial criteria set leaked: {len(shown)}/{len(group)}"
        fully_shown += bool(shown)
    # Non-vacuity: the budget must actually have dropped some group, or "never partial" is free.
    assert 0 < fully_shown < len(groups)


def test_the_most_governing_intent_survives_a_share_too_small_to_hold_it():
    """The top-ranked group is admitted even when it alone exceeds the share. A cap that could silence
    the single most-governing contract would re-create, in miniature, the inversion this bound fixes:
    the locus with the most to preserve told the least about it."""
    huge = [[f"  ✔ int:big: {'preserve this invariant ' * 20}"] * 4]
    assert "int:big" in _render(nx.DiGraph(), [], budget_tokens=120, obligation_groups=huge).text


class _Drift:
    """Minimal stand-in for a drift item (retrieval only reads these four fields)."""

    def __init__(self, task_id: str, kind: str = "soft", relation: str = "concerns"):
        self.task_id, self.kind, self.relation = task_id, kind, relation
        self.locator = "sym:a.py#f"


def test_the_drift_block_is_capped_and_points_at_the_uncapped_report():
    """Capping obligations alone just moved the flood: drift scales with anchored belief the same way,
    and on yigraf's own retrieval.py it reached 714 tokens of an 800-token packet with 0 of 55 nodes
    left. `yigraf drift` renders from its own path and is never capped, so the cap costs no coverage."""
    lines = retrieval._drift_block([_Drift(f"mem:{i:02d}") for i in range(12)], default_config())
    assert sum(1 for line in lines if line.startswith("  ⚠")) == 4  # retrieval.max_drift_lines
    assert "+8 more drifted" in "\n".join(lines)
    assert "`yigraf drift`" in "\n".join(lines)


def test_hard_drift_outranks_soft_drift_under_the_cap():
    """A symbol that is *gone* outranks one whose body merely changed, so the cap can't spend its four
    lines on soft drift and leave a vanished anchor unmentioned. The hard item is named to sort LAST
    alphabetically — the block's previous plain `sorted(lines)` would bury it, so this bites."""
    items = [_Drift(f"mem:a{i}", kind="soft") for i in range(6)] + [_Drift("mem:zz", kind="hard")]
    lines = retrieval._drift_block(items, default_config())
    assert "mem:zz" in lines[0]


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

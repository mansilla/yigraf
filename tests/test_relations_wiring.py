"""Wiring of the typed edge algebra into yigraf's surfaces: the write-boundary type checks
(:func:`relations.well_typed_ids` in ``link``/``remember``/``artifacts``), the drift-report blast-radius
ripple, and the self-hosted invariant that the built graph has zero mistyped edges."""
from pathlib import Path

import networkx as nx
import pytest
from typer.testing import CliRunner

from yigraf import artifacts, relations
from yigraf.cli import _blast_reconcile_lines, app
from yigraf.config import load_config
from yigraf.extract import build_graph
from yigraf.relations import EXTRACTED

runner = CliRunner()


# =================================================================================================
# #1 — the edge grammar enforced from locators at the write boundary
# =================================================================================================


def test_well_typed_ids_accepts_authored_relations():
    assert relations.well_typed_ids("implements", "task:m/1", "sym:a.py#f")
    assert relations.well_typed_ids("implements", "task:m/1", "file:a.py")
    assert relations.well_typed_ids("tracks", "task:m/1", "int:goal")
    assert relations.well_typed_ids("serves", "mem:1", "int:goal")
    assert relations.well_typed_ids("serves", "mem:1", "plan:auth")   # serves an intent OR a plan
    assert relations.well_typed_ids("supersedes", "mem:2", "mem:1")


def test_well_typed_ids_rejects_mistyped_locators():
    assert not relations.well_typed_ids("implements", "task:m/1", "int:goal")  # int is tracked, not implemented
    assert not relations.well_typed_ids("tracks", "task:m/1", "sym:a.py#f")    # tracks targets an intent
    assert not relations.well_typed_ids("serves", "mem:1", "sym:a.py#f")       # a symbol is not a goal
    assert not relations.well_typed_ids("serves", "mem:1", "mem:2")            # nor is another memory
    assert not relations.well_typed_ids("serves", "mem:1", "commit:abc")       # opaque prefix ⇒ ill-typed


def test_add_edge_to_plan_raises_on_a_mistyped_edge(tmp_path: Path):
    """The artifacts write boundary refuses an ill-typed plan edge before it reaches disk (the guard
    fires ahead of the file read, so a bogus path never matters)."""
    with pytest.raises(ValueError, match="ill-typed plan edge"):
        artifacts.add_edge_to_plan(tmp_path / "nope.md", "task:m/1", "implements", "int:goal")


def test_remember_rejects_a_mistyped_serves_target(tmp_path: Path):
    """`--serves` must name a goal (intent/plan); a symbol target is guided, not silently dangled — and,
    per design law #1, that guidance exits 0 so the agent retries rather than learning the tool fails."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    result = runner.invoke(app, ["remember", "a decision", "--serves", "sym:a.py#f", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "--serves points at the goal" in result.output
    assert "Captured" not in result.output          # the ill-typed edge was NOT written


def test_remember_accepts_a_well_typed_serves_target(tmp_path: Path):
    """The valid form is captured (a not-yet-created intent soft-warns as a dangling edge, never blocks)."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    result = runner.invoke(app, ["remember", "a decision", "--serves", "int:goal", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "Captured" in result.output


# =================================================================================================
# #2 — the drift report's blast-radius ripple (typed reverse reachability)
# =================================================================================================


def _chain_graph() -> nx.DiGraph:
    """A task implements ``f``; ``f`` calls ``g``. So ``g`` is only *transitively* the task's concern."""
    g = nx.DiGraph()
    g.add_node("task:m/1", family="plan", kind="task")
    g.add_node("sym:a.py#f", family="structure", kind="function")
    g.add_node("sym:a.py#g", family="structure", kind="function")
    g.add_edge("task:m/1", "sym:a.py#f", relation="implements", confidence=EXTRACTED)
    g.add_edge("sym:a.py#f", "sym:a.py#g", relation="calls", confidence=EXTRACTED)
    return g


def test_blast_reconcile_names_a_transitive_dependent():
    """When the deep callee ``g`` drifts, the task (which only implements its caller ``f``) is surfaced
    via the composed ``depends_on`` — the ripple the direct implements/concerns anchors never name."""
    lines = _blast_reconcile_lines(_chain_graph(), {"sym:a.py#g"}, exclude=set())
    assert len(lines) == 1
    assert "task:m/1" in lines[0] and "sym:a.py#g" in lines[0] and "depends_on" in lines[0]


def test_blast_reconcile_excludes_directly_named_nodes():
    """A node a direct drift line already prints is not repeated as a transitive dependent (no double signal)."""
    assert _blast_reconcile_lines(_chain_graph(), {"sym:a.py#g"}, exclude={"task:m/1"}) == []


def test_blast_reconcile_is_silent_without_governed_dependents():
    """No plan/memory/intent reaches the drifted symbol ⇒ nothing printed (silence is a feature)."""
    g = nx.DiGraph()
    g.add_node("sym:a.py#f", family="structure", kind="function")
    assert _blast_reconcile_lines(g, {"sym:a.py#f"}, exclude=set()) == []


# =================================================================================================
# #3 — self-hosted invariant: yigraf's own built graph has no mistyped edges
# =================================================================================================


def test_self_graph_has_no_mistyped_edges():
    """The edge grammar is not just a spec — it holds over yigraf indexing itself. If a real edge ever
    violates a signature, either the extractor changed or the grammar is wrong; both must be reconciled."""
    root = Path(__file__).resolve().parents[1]
    if not (root / "src" / "yigraf").is_dir():
        pytest.skip("not running inside the yigraf source tree")
    graph, _ = build_graph(root, load_config(root / "yigraf" / "config.yaml"))
    assert relations.mistyped_edges(graph) == []

"""The hollow ``--why``: a pointer at an argument nobody ever wrote (feedback-v5 amendment).

The field filed `gc` for breaking a `Why`-chain, then retracted it: `gc` had destroyed nothing. Four
live nodes whose whole reasoning read *"LOCUS REPAIR ONLY — the belief is unchanged and the argument
is in the node this supersedes"* pointed at parents that were a single statement line each. **The
pointers were always hollow**; archiving merely made the target unresolvable and the gap visible.

So the defect is not in `gc`. It is that a `--why` may defer its argument to another node and nothing
ever checks the argument is there — the store's own supersedes trail can be load-bearing and empty at
the same time, and `--why` is the field that was supposed to prevent that. Three surfaces close it:
capture refuses the pointer at the moment it is cheap, `gc` names the in-graph prose citations
`refs_in` cannot see, and `show` reports a hollow pointer already in the store. All three name
`amend`, the verb that writes the argument down with no supersedes trail.
"""
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yigraf import memory
from yigraf.cli import app

runner = CliRunner()

#: The exact reasoning the four field nodes carried.
LOCUS_REPAIR = "LOCUS REPAIR ONLY — the belief is unchanged and the argument is in the node this supersedes."


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _remember(root: Path, statement: str, why: str, locus: str = "sym:src/m.py#alpha") -> str:
    before = {m.id for m in memory.iter_memories(root)}
    result = runner.invoke(app, ["remember", statement, "--why", why, "--concerns", locus,
                                 "--repo", str(root)])
    assert result.exit_code == 0, result.output
    minted = {m.id for m in memory.iter_memories(root)} - before
    assert len(minted) == 1, result.output
    return minted.pop()


def _ids(root: Path) -> set[str]:
    return {m.id for m in memory.iter_memories(root)}


def _guard(root: Path, on: bool) -> None:
    """Toggle the capture guard. Every store already in the field was written before it existed, so a
    test for the surfaces that FIND those nodes has to be able to write one."""
    config = root / "yigraf" / "config.yaml"
    text = "\n".join(l for l in config.read_text().splitlines() if "hollow_why_words" not in l)
    config.write_text(text + ("\n" if on else "\nhollow_why_words: 0\n"))


# ── The shape test: a pointer, not an argument ──────────────────────────────────────────────────────

@pytest.mark.parametrize("why, supersedes, expected", [
    (LOCUS_REPAIR, ["mem:parent"], "mem:parent"),
    ("mem:865c8cda5e2b672c", [], "mem:865c8cda5e2b672c"),
    ("see mem:865c8cda5e2b672c", [], "mem:865c8cda5e2b672c"),
    ("Same reasoning as mem:abc123 — it applies verbatim.", [], "mem:abc123"),
    # …and the cases that must stay silent, because a --why may cite a node freely.
    ("", ["mem:parent"], None),
    ("The public API surface is unchanged.", [], None),
    ("We cap the hook packet at 800 tokens because it fires on every write and a bigger packet "
     "crowds out the diff the agent is actually reading; mem:012 measured the crowd-out at "
     "roughly a third of the window.", [], None),
])
def test_deferring_why_separates_a_pointer_from_an_argument(why, supersedes, expected):
    """The residue — the --why with the ids it names removed — is what tells them apart: an argument
    is longer than its own citation."""
    assert memory.deferring_why(why, supersedes) == expected


def test_a_deferral_to_a_node_that_argues_its_case_is_legitimate(tmp_path: Path):
    """Silence is a feature. Only a pointer that bottoms out in nothing is a defect."""
    root = _repo(tmp_path)
    target = _remember(root, "budgets are per-hook", "each hook has a different attention cost, and a "
                                                     "shared budget lets the cheapest one starve the rest")
    assert memory.deferral_verdict(root, f"see {target}", []) is None


# ── #1: capture refuses the pointer, at the one moment it is cheap ──────────────────────────────────

def test_a_supersede_deferring_to_an_argument_free_parent_is_refused(tmp_path: Path):
    """The reported shape, reproduced: the parent is a bare statement, and the child promises the
    argument is in it. Nothing downstream would ever have checked."""
    root = _repo(tmp_path)
    parent = _remember(root, "the rule lives on alpha", why="")
    before = _ids(root)

    result = runner.invoke(app, ["supersede", parent, "the rule lives on beta now",
                                 "--why", LOCUS_REPAIR, "--concerns", "sym:src/m.py#beta",
                                 "--repo", str(root)])

    assert result.exit_code == 0                      # recoverable ⇒ guidance, never a stack trace
    assert _ids(root) == before                       # …and nothing was captured
    assert "carries no --why of its own" in result.output
    assert f"yigraf amend {parent}" in result.output


def test_that_refusal_names_reanchor_as_the_verb_the_act_actually_wanted(tmp_path: Path):
    """A supersede whose --why says the belief is UNCHANGED is not a mind-change — it is the locus
    repair `reanchor` exists for, filed under the verb that writes a false entry in the trail."""
    root = _repo(tmp_path)
    parent = _remember(root, "the rule lives on alpha", why="")
    result = runner.invoke(app, ["supersede", parent, "the rule lives on beta now",
                                 "--why", LOCUS_REPAIR, "--concerns", "sym:src/m.py#beta",
                                 "--repo", str(root)])
    assert "yigraf reanchor" in result.output
    assert "supersedes trail" in result.output


def test_a_bare_forward_reference_to_an_id_that_does_not_exist_is_refused(tmp_path: Path):
    """"The argument it defers to may not exist, and nothing ever checks." """
    root = _repo(tmp_path)
    before = _ids(root)
    result = runner.invoke(app, ["remember", "beta is the anchor now",
                                 "--why", "see mem:ffffffffffffffff",
                                 "--concerns", "sym:src/m.py#beta", "--repo", str(root)])
    assert result.exit_code == 0
    assert _ids(root) == before
    assert "no node mem:ffffffffffffffff exists" in result.output


def test_a_supersede_that_states_what_changed_is_captured_normally(tmp_path: Path):
    """The guard must not tax an honest mind-change: this is the same supersede with a real argument."""
    root = _repo(tmp_path)
    parent = _remember(root, "the rule lives on alpha", why="")
    result = runner.invoke(app, ["supersede", parent, "the rule lives on beta now",
                                 "--why", "alpha was split in two and the invariant only ever held "
                                          "over the half that became beta; anchoring on alpha was "
                                          "pinning the wrong body",
                                 "--concerns", "sym:src/m.py#beta", "--repo", str(root)])
    assert result.exit_code == 0
    assert len(_ids(root)) == 2


def test_a_deferral_chain_reports_where_it_bottoms_out(tmp_path: Path):
    """A pointer at a pointer is still a pointer; the walk names the whole path so the reader does not
    have to repeat it by hand."""
    root = _repo(tmp_path)
    empty = _remember(root, "the rule lives on alpha", why="")
    _guard(root, on=False)
    middle = _remember(root, "the rule, restated", why=f"see {empty}", locus="sym:src/m.py#beta")
    _guard(root, on=True)

    result = runner.invoke(app, ["remember", "the rule, restated again", "--why", f"as in {middle}",
                                 "--concerns", "sym:src/m.py#beta", "--repo", str(root)])
    assert result.exit_code == 0
    assert f"defers to {middle} → {empty}" in result.output
    assert f"yigraf amend {empty}" in result.output


def test_the_guard_is_switchable(tmp_path: Path):
    """A heuristic that refuses a capture needs an off switch, or a false positive is unescapable."""
    root = _repo(tmp_path)
    parent = _remember(root, "the rule lives on alpha", why="")
    _guard(root, on=False)
    result = runner.invoke(app, ["supersede", parent, "the rule lives on beta now",
                                 "--why", LOCUS_REPAIR, "--concerns", "sym:src/m.py#beta",
                                 "--repo", str(root)])
    assert result.exit_code == 0
    assert len(_ids(root)) == 2


# ── #3: amend is the repair, so it is also the back door that must be shut ──────────────────────────

def test_amend_cannot_install_a_hollow_why(tmp_path: Path):
    root = _repo(tmp_path)
    _remember(root, "the rule lives on alpha", why="")
    target = _remember(root, "beta carries the invariant",
                       why="the invariant is about the returned value, and only beta returns one",
                       locus="sym:src/m.py#beta")
    result = runner.invoke(app, ["amend", target, "--why", "see mem:ffffffffffffffff",
                                 "--repo", str(root)])
    assert result.exit_code == 0
    assert "argues nothing" in result.output
    assert target in _ids(root)  # unchanged: amend re-keys, and no re-key happened


def test_amend_writes_the_argument_where_it_is_read(tmp_path: Path):
    """The claim the amendment makes for `amend`, exercised: a hollow Why becomes a real one with no
    supersedes trail and no second live belief."""
    root = _repo(tmp_path)
    hollow = _remember(root, "beta carries the invariant", why="it is unchanged")
    result = runner.invoke(app, ["amend", hollow, "--why",
                                 "the invariant is about the returned value, and only beta returns one",
                                 "--repo", str(root)])
    assert result.exit_code == 0, result.output
    repaired = (_ids(root) - {hollow}).pop()
    node = memory.read_memory(memory.find_memory(root, repaired))
    assert "only beta returns one" in node.why
    assert node.supersedes == []


def test_amend_repairs_the_exact_shape_the_field_has(tmp_path: Path):
    """The four in the field are supersede-children with a hollow Why, and the response document tells
    them to `amend` those. Pinned end to end, because a supersedes edge is the condition `amend`
    refuses on when it points the OTHER way: the child names its predecessor (fine), the predecessor's
    `superseded_by` stamp is re-pointed for it, and no second supersedes trail is written."""
    root, parent, child = _doomed_repo(tmp_path)

    result = runner.invoke(app, ["amend", child, "--why",
                                 "alpha was split in two and the invariant only ever held over the "
                                 "half that became beta", "--repo", str(root)])

    assert result.exit_code == 0, result.output
    repaired = (_ids(root) - {parent}).pop()
    node = memory.read_memory(memory.find_memory(root, repaired))
    assert node.supersedes == [parent]                       # the trail is intact, not re-filed
    assert "only ever held over the half" in node.why
    predecessor = memory.read_memory(memory.find_memory(root, parent))
    assert predecessor.superseded_by == repaired             # …and the stamp followed the re-key
    assert runner.invoke(app, ["show", repaired, "--repo", str(root)]).output.count("Hollow Why") == 0


# ── #2: the prose citation `refs_in` cannot see, named before the target stops resolving ────────────

def _doomed_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A collectable parent (superseded, unreferenced) whose argument a live node's `why` points at.

    Captured with the guard off, because the guard is precisely what stops this store existing now —
    the ones already in the field were filed before it did.
    """
    root = _repo(tmp_path)
    parent = _remember(root, "the rule lives on alpha", why="")
    _guard(root, on=False)
    assert runner.invoke(app, ["supersede", parent, "the rule lives on beta now",
                               "--why", LOCUS_REPAIR, "--concerns", "sym:src/m.py#beta",
                               "--repo", str(root)]).exit_code == 0
    _guard(root, on=True)
    child = (_ids(root) - {parent}).pop()
    return root, parent, child


def test_gc_names_the_live_node_whose_why_points_at_what_it_archives(tmp_path: Path):
    root, parent, child = _doomed_repo(tmp_path)
    result = runner.invoke(app, ["gc", str(root)])
    assert result.exit_code == 0
    assert f"{child}'s own `why` DEFERS its argument to {parent}" in result.output
    assert "`refs_in` cannot see" in result.output


def test_gc_says_when_the_pointer_was_hollow_all_along(tmp_path: Path):
    """The correction the field sent us: archiving destroys nothing here. Saying only "this stops
    resolving" would repeat their own inference — that an argument was lost — when there was none."""
    root, parent, _child = _doomed_repo(tmp_path)
    result = runner.invoke(app, ["gc", str(root)])
    assert f"{parent} carries no `why` of its own, so that pointer was always hollow" in result.output
    assert "destroys nothing" in result.output


def test_gc_says_copy_it_across_when_the_argument_is_real(tmp_path: Path):
    """The other half: a pointer at a node that DOES argue its case is a repair with a deadline."""
    root = _repo(tmp_path)
    parent = _remember(root, "the rule lives on alpha",
                       why="alpha is the only entry point, so the check has to sit there")
    _guard(root, on=False)
    assert runner.invoke(app, ["supersede", parent, "the rule lives on beta now",
                               "--why", LOCUS_REPAIR, "--concerns", "sym:src/m.py#beta",
                               "--repo", str(root)]).exit_code == 0
    _guard(root, on=True)
    result = runner.invoke(app, ["gc", str(root)])
    assert "Copy the argument across" in result.output
    assert "always hollow" not in result.output


def test_a_plain_citation_is_reported_as_a_citation_not_a_deferral(tmp_path: Path):
    """A `why` that ARGUES and happens to name the doomed id is not a hollow pointer, and calling it
    one would be the same defect the field kept filing: a surface naming the wrong state."""
    root = _repo(tmp_path)
    parent = _remember(root, "the rule lives on alpha", why="alpha is the only entry point")
    assert runner.invoke(app, ["supersede", parent, "the rule lives on beta now",
                               "--why", "alpha was split and the invariant followed the half that "
                                        "became beta", "--concerns", "sym:src/m.py#beta",
                               "--repo", str(root)]).exit_code == 0
    _remember(root, "beta's guard is the one that matters",
              why=f"beta inherited the entry-point role when alpha was split, which is the move "
                  f"{parent} was retired for; the guard follows the role, not the name",
              locus="sym:src/m.py#beta")

    result = runner.invoke(app, ["gc", str(root)])
    assert "1 live `why` field(s) cite an id above" in result.output
    assert "DEFERS" not in result.output


def test_gc_is_silent_when_no_live_why_points_at_a_candidate(tmp_path: Path):
    """Respect the attention budget: this line appears only when there is a citation to repoint."""
    root = _repo(tmp_path)
    parent = _remember(root, "the rule lives on alpha", why="alpha is the only entry point")
    assert runner.invoke(app, ["supersede", parent, "the rule lives on beta now",
                               "--why", "alpha was split and the invariant followed the half that "
                                        "became beta", "--concerns", "sym:src/m.py#beta",
                               "--repo", str(root)]).exit_code == 0
    result = runner.invoke(app, ["gc", str(root)])
    assert "cite an id above" not in result.output and "DEFERS" not in result.output


# ── #3: the surface where the ones already in the store are found ───────────────────────────────────

def test_show_reports_a_hollow_why_and_names_amend(tmp_path: Path):
    """`show` is where anyone holding an id reads the reasoning, so it is where the four were found —
    by hand, years late. It should have said so itself."""
    root, parent, child = _doomed_repo(tmp_path)
    result = runner.invoke(app, ["show", child, "--repo", str(root)])
    assert result.exit_code == 0
    assert "⚠ Hollow Why:" in result.output
    assert f"{parent} carries no Why of its own" in result.output
    assert f"yigraf amend {child}" in result.output


def test_show_says_nothing_about_a_why_that_argues_its_case(tmp_path: Path):
    root = _repo(tmp_path)
    node = _remember(root, "beta carries the invariant",
                     why="the invariant is about the returned value, and only beta returns one")
    result = runner.invoke(app, ["show", node, "--repo", str(root)])
    assert "Hollow Why" not in result.output

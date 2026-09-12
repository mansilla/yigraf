"""The findings from the 1.11.1 field feedback (feedback-v9), each pinned by the failure it closes.

Three of the four are a *claim* the store could not retract: a marker no verb cleared, so the task went
on asserting "this shipped no symbol" after it had grown one; a success line announcing that
grounds-drift was cleared on a node that never had any; and a migrated config whose surviving prose
still introduced the key the migration had just removed. The fourth is the one the round was really
about — a byte-identity that cannot tell a deliberate pin from an init-minted copy — and its guard is
here too, frozen, because the shipped one re-mints its fixture from the running default and therefore
cannot fail. Grouped by finding, as in the v5/v6/v7 files.
"""
from pathlib import Path

from typer.testing import CliRunner

from yigraf import artifacts, retrieval
from yigraf.config import (SUPERSEDED_SESSION_PREAMBLES, commented_preamble_block,
                          default_config, preamble_behind, refresh_preamble)
from yigraf.cli import app
from yigraf.extract import build_graph

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
OTHER_SYM = "sym:auth/session.py#revoke"


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    # Both symbols exist BEFORE any link, so `link` never has to guide instead of anchoring.
    src.write_text("def refresh(token):\n    return token\n\n\ndef revoke(token):\n    return None\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _run(root: Path, *args: str):
    return runner.invoke(app, [*args, "--repo", str(root)])


def _plan_file(root: Path, slug: str = "notes") -> Path:
    return root / "yigraf" / "plans" / "active" / f"{slug}.md"


def _task(root: Path, slug: str, *descriptions: str) -> None:
    tasks = [arg for d in descriptions for arg in ("--task", d)]
    assert _run(root, "plan", slug, "-t", slug.title(), *tasks).exit_code == 0


def _marked(root: Path, slug: str, num: int = 1) -> bool:
    plan = artifacts.read_plan(_plan_file(root, slug))
    return next(t for t in plan.tasks if t.num == num).unanchored


def _gaps(root: Path) -> str:
    graph, _ = build_graph(root, default_config())
    return retrieval.session_context(graph, default_config(), root=root).text


# --- H#2: the `unanchored:` marker no verb cleared ---------------------------------------------------

def test_link_retires_the_marker_when_the_work_grows_a_symbol(tmp_path: Path):
    """`mark_task_unanchored`'s clearing branch shipped complete and unreachable: both CLI call sites
    took the default `True`, so eleven verbs — link, unlink, --reopen, build, gc, plan --append-task,
    intent --status, a post-commit hook — left the marker standing. The assertion it records is in the
    present tense ("this completion names no symbol"), and a task that now carries an implements edge
    has stopped making it."""
    root = _repo(tmp_path)
    _task(root, "notes", "write the note")
    assert _run(root, "close", "task:notes/1", "--force").exit_code == 0
    assert _marked(root, "notes") is True

    out = _run(root, "link", "task:notes/1", SYM)
    assert out.exit_code == 0, out.output
    assert _marked(root, "notes") is False
    assert "no longer recorded as unanchored" in out.output
    assert "unanchored" not in _plan_file(root, "notes").read_text()


def test_the_tools_own_suggested_next_step_is_the_one_that_clears_it(tmp_path: Path):
    """--force prints "if the work later grows one, `yigraf link` re-earns that". Following that
    literally used to mint the contradiction below, so the invitation has to be the repair."""
    root = _repo(tmp_path)
    _task(root, "notes", "write the note")
    forced = _run(root, "close", "task:notes/1", "--force")
    assert "`yigraf link` re-earns both" in forced.output
    assert _run(root, "link", "task:notes/1", SYM).exit_code == 0
    assert _marked(root, "notes") is False


def test_the_state_close_refuses_to_write_can_no_longer_be_minted(tmp_path: Path):
    """`close` only ever writes the marker under `not task.implements`, so "unanchored AND implements"
    is a state it refuses to produce — and in it the claim --force makes, that the completion can never
    go STALE, is simply false: edit the anchored symbol and the task reports STALE while the plan file
    still asserts it names none."""
    root = _repo(tmp_path)
    _task(root, "notes", "write the note")
    assert _run(root, "close", "task:notes/1", "--force").exit_code == 0
    assert _run(root, "link", "task:notes/1", SYM).exit_code == 0

    plan = artifacts.read_plan(_plan_file(root, "notes"))
    task = plan.tasks[0]
    assert task.implements, "the edge is declared"
    assert task.unanchored is False, "…so the assertion that it implements nothing is not also on disk"

    (root / "auth" / "session.py").write_text(
        "def refresh(token):\n    return token.rotate()\n\n\ndef revoke(token):\n    return None\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    stale = runner.invoke(app, ["drift", str(root), "--stale"])
    assert "task:notes/1" in stale.output, "a linked task drifts like any other"


def test_a_forced_task_that_loses_its_symbol_is_an_ordinary_capture_gap_again(tmp_path: Path):
    """`_capture_gaps` consults the marker BEFORE it looks for an implements edge, so a surviving one
    exempted a task from the detector permanently. The control is the whole finding: two tasks in
    identical end states — done, zero implements edges — and before this only the never-forced one was
    reported."""
    root = _repo(tmp_path)
    _task(root, "notes", "forced, then grows a symbol", "control: never forced")
    assert _run(root, "close", "task:notes/1", "--force").exit_code == 0
    assert _run(root, "link", "task:notes/1", SYM).exit_code == 0
    assert _run(root, "link", "task:notes/2", OTHER_SYM).exit_code == 0
    assert _run(root, "close", "task:notes/2").exit_code == 0

    assert _run(root, "unlink", "task:notes/1", SYM).exit_code == 0        # an ordinary refactor:
    assert _run(root, "unlink", "task:notes/2", OTHER_SYM).exit_code == 0  # the symbol was inlined

    gaps = _gaps(root)
    assert "task:notes/2 is done but names no implementing symbol" in gaps, "the control"
    assert "task:notes/1 is done but names no implementing symbol" in gaps, "and the once-forced task"


def test_tracking_an_intent_leaves_the_marker_alone(tmp_path: Path):
    """Confined to the sym:/file: branch on purpose. `link <task> int:<slug>` says the task TRACKS an
    intent, which asserts nothing about whether it implements a symbol — clearing there would re-open
    the nag on work that genuinely shipped none."""
    root = _repo(tmp_path)
    _task(root, "notes", "write the note")
    assert _run(root, "intent", "notes-live-in-git", "-s", "Notes SHALL live in git.").exit_code == 0
    assert _run(root, "close", "task:notes/1", "--force").exit_code == 0
    assert _run(root, "link", "task:notes/1", "int:notes-live-in-git").exit_code == 0
    assert _marked(root, "notes") is True
    assert "task:notes/1 is done but names no implementing symbol" not in _gaps(root)


def test_the_force_flag_says_it_records_rather_than_promising_no_stale(tmp_path: Path):
    """The help string is rendered verbatim into the cheatsheet, so the sentence a reader is most
    likely to meet was the one H#2(a) falsifies. It now describes what --force *does* — which is also
    the thing 1.11.1 changed and no prose surface had said."""
    _repo(tmp_path)
    force_line = next(line for line in runner.invoke(app, ["cheatsheet"]).output.splitlines()
                      if line.strip().startswith("--force") and "capture gap" in line)
    assert "records" in force_line
    assert "never go stale" not in force_line.lower()


# --- H#3: the migrated file keeps the prose that introduced the key it just removed -----------------

def test_the_installer_says_how_to_take_the_preamble_back(tmp_path: Path):
    """`refresh_preamble` splices the KEY and nothing else — the right scope for a text write into a
    committed file, and the reason a migrated ≤1.8.x config still reads "Yours to rewrite" directly
    above a commented-out block, with the word "uncomment" nowhere in it. Widening the splice would be
    a much larger unrequested write, so the transition is explained at the moment of the migration
    instead: without it a reader edits the text where they find it, leaves it commented, and commits a
    house rule every session silently ignores."""
    root = _repo(tmp_path)
    cfg = root / "yigraf" / "config.yaml"
    body = "\n".join(f"    {line}".rstrip()
                     for line in SUPERSEDED_SESSION_PREAMBLES[0].rstrip("\n").splitlines())
    cfg.write_text(cfg.read_text().replace(commented_preamble_block(), f"  preamble: |\n{body}"))
    assert preamble_behind(cfg), "the fixture must be a genuinely stale file"

    out = runner.invoke(app, ["install", str(root), "--host", "mcp"])

    assert out.exit_code == 0, out.output
    assert "retired the committed copy" in out.output
    assert "uncomment" in out.output.lower(), "the one word a migrated file never contains"


def test_the_migration_is_silent_when_there_is_nothing_to_retire(tmp_path: Path):
    """Design law #4 still governs the second line: it exists to explain a write, so it must not fire
    on the overwhelmingly common run where no write happened."""
    out = runner.invoke(app, ["install", str(_repo(tmp_path)), "--host", "mcp"])
    assert out.exit_code == 0 and "uncomment" not in out.output.lower()


# --- H#5: `--evidence` restored a dropped `concerns` anchor onto the other list ---------------------

def _doc_repo(tmp_path: Path) -> Path:
    root = _repo(tmp_path)
    doc = root / "docs" / "d.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# D\n\n## Alpha\n\nThe alpha rule.\n\n## Bravo\n\nThe bravo rule.\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    return root


def _belief(root: Path) -> str:
    out = _run(root, "remember", "Rules live in the doc", "--why", "measured it",
               "--concerns", "file:docs/d.md#alpha", "--concerns", "file:docs/d.md#bravo")
    assert out.exit_code == 0, out.output
    graph, _ = build_graph(root, default_config())
    return next(n for n, a in graph.nodes(data=True) if a.get("family") == "memory")


def test_evidence_on_a_node_with_no_grounds_does_not_claim_drift_was_cleared(tmp_path: Path):
    """"grounds-drift cleared" on a node that has no `grounded_by` list describes an event that never
    happened — and a caller who arrived from the drop ⚠ reads it as the restore the ⚠ said no verb
    performs."""
    root = _doc_repo(tmp_path)
    mem = _belief(root)
    assert _run(root, "unlink", mem, "file:docs/d.md#bravo").exit_code == 0

    out = _run(root, "reaffirm", mem, "--evidence", "file:docs/d.md#bravo")
    assert out.exit_code == 0, out.output
    assert "grounds-drift cleared" not in out.output


def test_it_says_which_list_the_locus_landed_on(tmp_path: Path):
    """The ask, in one string: the two lists mean different things, and the caller had no reason to
    look at which column `show` put it in."""
    root = _doc_repo(tmp_path)
    mem = _belief(root)
    assert _run(root, "unlink", mem, "file:docs/d.md#bravo").exit_code == 0

    out = _run(root, "reaffirm", mem, "--evidence", "file:docs/d.md#bravo").output
    assert "`grounded_by`" in out and "does not add a `concerns` anchor back" in out
    assert "--concerns file:docs/d.md#alpha" in out, "the restatement keeps the anchors it still has"
    assert "--concerns file:docs/d.md#bravo" in out, "…and names the one being restored"


def test_a_genuine_re_observation_still_reports_the_drift_it_cleared(tmp_path: Path):
    """The control. Where there WAS grounds-drift and this call cleared it, the line is unchanged —
    the fix narrows a claim, it does not retire it."""
    root = _doc_repo(tmp_path)
    mem = _belief(root)
    assert _run(root, "reaffirm", mem, "--grounding", "empirical",
                "--evidence", "file:docs/d.md#bravo").exit_code == 0
    (root / "docs" / "d.md").write_text(
        "# D\n\n## Alpha\n\nThe alpha rule.\n\n## Bravo\n\nThe bravo rule, amended.\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0

    out = _run(root, "reaffirm", mem, "--evidence", "file:docs/d.md#bravo")
    assert out.exit_code == 0, out.output
    assert "grounds-drift cleared" in out.output


def test_adding_evidence_to_a_node_with_no_concerns_is_not_narrated(tmp_path: Path):
    """Design law #4: with no `concerns` list there are not two lists to confuse, so the clause that
    distinguishes them would be pure noise."""
    root = _doc_repo(tmp_path)   # no `_belief` here: this repo holds exactly one memory, and it has
    out = _run(root, "remember", "The build is reproducible", "--why", "measured it")  # no concerns
    assert out.exit_code == 0, out.output
    graph, _ = build_graph(root, default_config())
    mems = [n for n, a in graph.nodes(data=True) if a.get("family") == "memory"]
    assert len(mems) == 1, mems
    mem = mems[0]

    added = _run(root, "reaffirm", mem, "--evidence", "file:docs/d.md#bravo")
    assert added.exit_code == 0, added.output
    assert "does not add a `concerns` anchor back" not in added.output


# --- H#1: a pin cannot be told from a mint by its bytes ---------------------------------------------
#
# This section is the field's own test (their §F), taken with one change: it asserts the marker rather
# than byte-identity, because that is the mechanism we shipped instead. Everything that matters about
# it is unchanged — PINNED_AT_1_11_1 is a LITERAL, never an import of DEFAULT_SESSION_PREAMBLE.
#
# Why that matters is the finding's strongest limb, and it was theirs:
# `test_a_current_preamble_pinned_by_hand_is_left_alone` built its fixture from the running default at
# run time, while `test_the_current_default_is_not_also_listed_as_superseded` guarantees that text is
# never in the superseded tuple. The two together made the assertion unfalsifiable — the fixture moved
# with every release, a real team's committed file does not, so it held for a pin that is always
# current and never for one that has aged by a release. A frozen literal is what makes the aging
# visible. Re-freeze it ONCE, at the release you consider "today", and then never touch it: updating
# it to match the current default turns it back into the test that cannot fail.

PINNED_AT_1_11_1 = """\
[yigraf] Standing rules for this session — instructions, not reference:
- Read yigraf's own guidance before driving the CLI: the `yigraf` skill if your host loads skills,
  otherwise the yigraf block in AGENTS.md. `yigraf cheatsheet` lists every verb and flag. Knowing
  the verbs is not the same as knowing which one resolves which signal.
- Capture as the work lands, not as a closing ritual. `--why` and `--rejected` are worth most at the
  moment of the decision; by the end of a session the reasoning that made the choice is gone.
- Before you report done, run `yigraf status`. "Up to date" means no drift, no stale AND no unsettled
  rename — settle the rename first, it is the only one that expires. Open tasks are a fourth, separate
  thing, and a quiet context packet is evidence of none of them.
- One verb per signal, and the wrong one costs you: code a decision governs changed → `reaffirm`
  (the belief is unchanged) or `supersede` (your mind changed), never re-`remember`. A done task's
  symbol changed → re-`link`, or reopen it. Two live beliefs collide → `reconcile`, `supersede`, or
  `dispute`.
"""


def _pin(root: Path, text: str, *, declared: bool) -> Path:
    cfg = root / "yigraf" / "config.yaml"
    body = "\n".join(f"    {line}".rstrip() for line in text.rstrip("\n").splitlines())
    marker = "  preamble_pinned: true\n" if declared else ""
    cfg.write_text(cfg.read_text().replace(commented_preamble_block(),
                                           f"{marker}  preamble: |\n{body}"))
    return cfg


def test_a_declared_pin_survives_an_amendment_of_the_shipped_default(tmp_path: Path):
    """A team pinned the text on the day they read the file. No later release may take it back.

    The literal is the whole point: it is what a team that ran the documented uncomment at 1.11.1 has
    sitting in its committed config.yaml, and it stays that text while the release moves on. An import
    of DEFAULT_SESSION_PREAMBLE here would re-mint the pin every release and the assertion could never
    fail."""
    root = _repo(tmp_path)
    cfg = _pin(root, PINNED_AT_1_11_1, declared=True)
    before = cfg.read_text()

    assert refresh_preamble(cfg) is False, "the remedy declines a file that declares itself pinned"
    assert not preamble_behind(cfg), "…and so does the nudge"
    assert runner.invoke(app, ["install", str(root), "--host", "mcp"]).exit_code == 0

    assert cfg.read_text() == before, (
        "an install verb rewrote a preamble the team deliberately pinned: the `preamble_pinned` marker "
        "is the one fact byte-identity cannot carry, and it must outlive every amendment of the default")


def test_the_frozen_pin_is_still_the_text_this_release_ships(tmp_path: Path):
    """A canary, not a contract. While these are equal the protection above is also being exercised by
    every other current-text test; the day they diverge is the day the frozen fixture starts testing
    something the running release no longer produces — which is exactly when it earns its place. If
    this fails, DO NOT re-freeze the literal: check that the amendment appended the outgoing text to
    SUPERSEDED_SESSION_PREAMBLES, and delete this canary."""
    from yigraf.config import DEFAULT_SESSION_PREAMBLE
    if PINNED_AT_1_11_1 != DEFAULT_SESSION_PREAMBLE:
        import pytest
        pytest.skip("the default has been amended since 1.11.1 — the frozen pin is now doing its job")


def test_an_undeclared_pin_of_the_current_text_is_retired_with_it(tmp_path: Path):
    """⚠ The accepted loss, asserted so it stays a decision rather than a regression.

    An undeclared live key is a repo `init`ed at 1.9.0-1.10.0 or a hand-pin predating the marker, and
    nothing in the file separates them. Retiring it strands no one permanently — the text is still in
    the file, commented, one uncomment from being re-pinned WITH its declaration this time — where
    honouring it would leave the 1.9.0-1.10.0 population carrying a live copy that never tracks the
    CLI again."""
    root = _repo(tmp_path)
    cfg = _pin(root, PINNED_AT_1_11_1, declared=False)

    assert runner.invoke(app, ["install", str(root), "--host", "mcp"]).exit_code == 0

    import yaml
    assert "preamble" not in yaml.safe_load(cfg.read_text())["session_start"], "the live key is gone"
    assert commented_preamble_block() in cfg.read_text(), "and the text is still there to re-pin"
    assert "preamble_pinned: true" in commented_preamble_block(), "…declaring itself this time"

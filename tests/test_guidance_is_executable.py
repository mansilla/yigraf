"""Every verb a guidance string names must actually clear the signal it is printed under.

Design law #1 stakes the whole product on this: a recoverable condition exits 0 *because* the message
teaches the retry. Nothing tested that the taught retry works, and the fourth field report found six
places where it did not — a message naming a verb that is provably refused in that state
(``reaffirm`` on hard drift, echoed to the Stop-hook notice), omitting the one that works
(``reanchor``, on all four ``grounded_by`` surfaces), describing a command the caller did not send
(the empirical guard), asserting an outcome that did not happen (``grounds-drift cleared`` on a
deleted ref; ``the rejection stays hidden`` on a premise that holds), or pointing at a verb that does
not exist at all (``reopen the task``).

Those were six symptoms of one gap, so this file tests the *invariant* rather than the six strings:
put the tool in a state, read the verbs its own output names, run them, and assert the ⚠ is gone.
A wording change is free; a wording change that names an inert verb fails here.
"""
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "def refresh(token):\n    return token\n"


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text(SRC)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "run-a.md").write_text("observed: torque saturates at 12 rad/s\n")
    (tmp_path / "results" / "run-b.md").write_text("re-run: same, 12 rad/s\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _run(root: Path, *args: str):
    return runner.invoke(app, [*args, "--repo", str(root)])


def _remember(root: Path, statement: str, *extra: str) -> str:
    result = runner.invoke(app, ["remember", statement, "--repo", str(root), *extra])
    assert result.exit_code == 0, result.output
    return re.search(r"mem:[0-9a-f]+", result.output).group(0)


def _drift(root: Path) -> str:
    return runner.invoke(app, ["drift", str(root)]).output


def _advice(root: Path) -> str:
    """`yigraf drift` output WITHOUT its trailing verb legend.

    The legend names every verb by definition ("`reaffirm` = the belief is UNCHANGED …"), so scanning
    it for advice would say every line offers every verb. What is under test is the per-item tail.
    """
    return _drift(root).split("↳ Which verb")[0]


def _named_verbs(text: str) -> set[str]:
    """The yigraf verbs a piece of output tells the reader to run.

    Read out of backticked *commands* — a snippet must carry an operand to count. A bare `` `reaffirm` ``
    is a mention, not an instruction, and the two appear in opposite senses in the same sentence: the
    hard-drift line reads "the locus is gone, so `reaffirm` can't re-anchor it — … `reanchor <id> <old>
    <new>`". Counting the bare form would read that line as offering the verb it just ruled out.
    """
    known = {"reaffirm", "reanchor", "supersede", "unlink", "link", "close", "remember", "dispute",
             "reconcile", "attest", "pin", "propose", "note-constraint", "plan", "tasks"}
    out = set()
    for snippet in re.findall(r"`([^`]+)`", text):
        tokens = snippet.replace("yigraf ", "", 1).strip().split()
        if len(tokens) > 1 and tokens[0] in known:
            out.add(tokens[0])
    return out


# --------------------------------------------------------------------------------------------------
# hard `concerns` drift — the locus died
# --------------------------------------------------------------------------------------------------

def test_every_verb_the_hard_concerns_line_names_is_one_that_reaches_it(tmp_path: Path):
    """`reanchor`, `supersede` and `unlink` are offered; `reaffirm` deliberately is not.

    `supersede` is named for a genuine mind-change, and it is the one exit that does NOT clear the ⚠
    (the successor inherits the anchor) — so it is asserted separately below rather than folded in.
    """
    root = _repo(tmp_path)
    mem = _remember(root, "refresh must not renew past the absolute cap", "--concerns", SYM)
    (root / "auth" / "session.py").write_text("def rotate(token):\n    return token + 1\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    out = _advice(root)
    assert "hard drift" in out
    named = _named_verbs(out)
    assert "reanchor" in named and "unlink" in named
    assert "reaffirm" not in named, "reaffirm cannot re-anchor a gone locus and must not be offered"
    # and the verb it names really does clear it
    assert _run(root, "reanchor", mem, SYM, "sym:auth/session.py#rotate").exit_code == 0
    assert "No drift." in _drift(root)


def test_the_unlink_exit_the_hard_line_names_also_clears_it(tmp_path: Path):
    root = _repo(tmp_path)
    mem = _remember(root, "refresh must not renew past the absolute cap", "--concerns", SYM)
    (root / "auth" / "session.py").write_text("def rotate(token):\n    return token + 1\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    assert _run(root, "unlink", mem, SYM).exit_code == 0
    assert "No drift." in _drift(root)


def test_supersede_no_longer_advises_the_verb_the_drift_surface_ruled_out(tmp_path: Path):
    """A dead inherited anchor must route to `reanchor`, not to `reaffirm` (feedback-v4 #4).

    Taking the `supersede` exit repeatedly was a closed loop: the successor inherits the dead anchor,
    the hard-drift count stays at 1 and walks to the newest node, and every pass adds a false entry to
    the supersedes chain. The inheritance is right; the advice was not.
    """
    root = _repo(tmp_path)
    mem = _remember(root, "refresh must not renew past the absolute cap", "--concerns", SYM)
    (root / "auth" / "session.py").write_text("def rotate(token):\n    return token + 1\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    out = _run(root, "supersede", mem, "refresh renews only inside the cap", "--why", "measured").output
    assert "the locus DIED" in out and "reanchor" in out
    assert "`reaffirm <mem-id>`" not in out
    assert "<mem-id>" not in out and "<this mem-id>" not in out, "an unfilled placeholder is unrunnable"


def test_a_genuine_forward_reference_still_gets_reaffirm(tmp_path: Path):
    """The same string is CORRECT for code about to be written — the fix had to stay narrow."""
    root = _repo(tmp_path)
    mem = _remember(root, "the new expiry path must be idempotent", "--concerns",
                    "sym:auth/session.py#expire")
    out = _run(root, "supersede", mem, "the new expiry path must also be total", "--why", "x").output
    assert "reaffirm" in out and "the locus DIED" not in out
    # and it works: land the code, reaffirm, drift clears
    (root / "auth" / "session.py").write_text(SRC + "\n\ndef expire(token):\n    return None\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    new_id = re.findall(r"mem:[0-9a-f]+", out)[-1]
    assert _run(root, "reaffirm", new_id).exit_code == 0
    assert "No drift." in _drift(root)


# --------------------------------------------------------------------------------------------------
# `grounded_by` drift — where none of the named exits used to work
# --------------------------------------------------------------------------------------------------

def _grounded(root: Path) -> str:
    return _remember(root, "brake torque saturates above 12 rad/s", "--why", "measured",
                     "--grounding", "empirical", "--evidence", "file:results/run-a.md")


def test_soft_grounds_drift_names_reanchor_and_reanchor_clears_it(tmp_path: Path):
    root = _repo(tmp_path)
    mem = _grounded(root)
    (root / "results" / "run-a.md").write_text("observed: torque saturates at 9 rad/s\n")
    out = _advice(root)
    assert "soft drift · grounded_by" in out
    assert "reanchor" in _named_verbs(out), "the one verb that keeps both the tier and the evidence"
    assert _run(root, "reanchor", mem, "file:results/run-a.md", "file:results/run-b.md").exit_code == 0
    assert "No drift." in _drift(root)


def test_the_re_observe_exit_names_the_locator_that_actually_clears_it(tmp_path: Path):
    """The guard accepts only the drifting locator, and the line now says so — it used to print
    `--evidence <fresh>`, which is refused for every value except that one."""
    root = _repo(tmp_path)
    mem = _grounded(root)
    (root / "results" / "run-a.md").write_text("observed: torque saturates at 9 rad/s\n")
    assert "--evidence <fresh>" not in _drift(root)
    assert _run(root, "reaffirm", mem, "--grounding", "empirical",
                "--evidence", "file:results/run-a.md").exit_code == 0
    assert "No drift." in _drift(root)


def test_the_refusal_states_its_own_condition_and_writes_nothing(tmp_path: Path):
    root = _repo(tmp_path)
    mem = _grounded(root)
    (root / "results" / "run-a.md").write_text("observed: torque saturates at 9 rad/s\n")
    out = _run(root, "reaffirm", mem, "--grounding", "empirical",
               "--evidence", "file:results/run-b.md").output
    assert "without --evidence" not in out, "it must not explain a command the caller did not send"
    assert "EVERY drifting locator" in out and "Nothing was written." in out
    assert "file:results/run-a.md" in out  # the condition names the locator it is asking for
    assert "soft drift" in _drift(root)  # atomic: nothing advanced


def test_the_honest_downgrade_is_a_real_exit(tmp_path: Path):
    """`--grounding inferred` is offered as one of two exits, so it has to clear something.

    It used to clear nothing — and the line afterwards still called the now-`inferred` node an
    "·empirical belief" and re-offered the downgrade just performed (feedback-v4 #2).
    """
    root = _repo(tmp_path)
    mem = _grounded(root)
    (root / "results" / "run-a.md").write_text("observed: torque saturates at 9 rad/s\n")
    assert "downgrade" in _drift(root)
    assert _run(root, "reaffirm", mem, "--grounding", "inferred").exit_code == 0
    assert "No drift." in _drift(root)


def test_a_deleted_evidence_ref_is_never_reported_as_cleared(tmp_path: Path):
    """The one accepted `--evidence` form used to print "grounds-drift cleared" on a path that does
    not exist, exit 0, with no warning tail — while `yigraf drift` went on reporting hard drift."""
    root = _repo(tmp_path)
    mem = _grounded(root)
    (root / "results" / "run-a.md").unlink()
    out = _run(root, "reaffirm", mem, "--evidence", "file:results/run-a.md").output
    assert "grounds-drift cleared" not in out
    assert "grounds-drift still stands" in out
    assert "hard drift" in _drift(root)
    # the exit the tail names does clear it
    assert _run(root, "reanchor", mem, "file:results/run-a.md", "file:results/run-b.md").exit_code == 0
    assert "No drift." in _drift(root)


def test_the_two_step_the_hard_line_spells_out_completes(tmp_path: Path):
    """downgrade, *then* retire — in that order, as the line states it left to right."""
    root = _repo(tmp_path)
    mem = _grounded(root)
    (root / "results" / "run-a.md").unlink()
    assert _run(root, "unlink", mem, "file:results/run-a.md").exit_code == 0
    assert "hard drift" in _drift(root), "unlink alone is refused while empirical — nothing retired"
    assert _run(root, "reaffirm", mem, "--grounding", "inferred").exit_code == 0
    assert _run(root, "unlink", mem, "file:results/run-a.md").exit_code == 0
    assert "No drift." in _drift(root)


def test_a_guard_that_refuses_names_every_ref_it_is_waiting_on(tmp_path: Path):
    """Following the message verbatim must not refuse again on the ref it did not mention."""
    root = _repo(tmp_path)
    mem = _remember(root, "brake torque saturates above 12 rad/s", "--why", "measured",
                    "--grounding", "empirical",
                    "--evidence", "file:results/run-a.md", "--evidence", "file:results/run-b.md")
    (root / "results" / "run-a.md").write_text("changed a\n")
    (root / "results" / "run-b.md").write_text("changed b\n")
    out = _run(root, "reaffirm", mem, "--grounding", "empirical",
               "--evidence", "file:results/run-a.md").output
    assert "file:results/run-a.md" in out and "file:results/run-b.md" in out
    # the command it prints, run verbatim, succeeds
    assert _run(root, "reaffirm", mem, "--grounding", "empirical",
                "--evidence", "file:results/run-a.md",
                "--evidence", "file:results/run-b.md").exit_code == 0
    assert "No drift." in _drift(root)


# --------------------------------------------------------------------------------------------------
# the task family — the verb that did not exist
# --------------------------------------------------------------------------------------------------

def _plan_with_task(root: Path) -> str:
    assert _run(root, "plan", "auth", "-t", "Auth", "--task", "harden refresh").exit_code == 0
    assert _run(root, "link", "task:auth/1", SYM).exit_code == 0
    return "task:auth/1"


def test_the_open_task_nag_names_a_verb_that_exists_and_clears_it(tmp_path: Path):
    """`retrieval` built a dedicated ⚠ for "open but its symbols are current" and then told the reader
    to "check its box" — the one instruction with no verb behind it (feedback-v4 #1)."""
    root = _repo(tmp_path)
    task = _plan_with_task(root)
    out = runner.invoke(app, ["context", "harden refresh", "--repo", str(root)]).output
    assert task in out
    assert "close" in _named_verbs(out), "the nag must name the verb that resolves it"
    assert _run(root, "close", task).exit_code == 0
    assert "☑" in _run(root, "tasks").output


def test_the_stale_notice_names_a_reopen_that_exists(tmp_path: Path):
    root = _repo(tmp_path)
    task = _plan_with_task(root)
    assert _run(root, "close", task).exit_code == 0
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token + 1\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    out = runner.invoke(app, ["drift", "--stale", str(root)]).output
    assert "--reopen" in out
    assert _run(root, "close", task, "--reopen").exit_code == 0
    assert "☐" in _run(root, "tasks").output


def test_close_refuses_an_unanchored_completion_and_names_the_fix(tmp_path: Path):
    root = _repo(tmp_path)
    assert _run(root, "plan", "auth", "-t", "Auth", "--task", "write the migration note").exit_code == 0
    out = _run(root, "close", "task:auth/1").output
    assert "implements nothing" in out and "yigraf link task:auth/1" in out
    assert "☐" in _run(root, "tasks").output  # refused, not silently closed
    assert _run(root, "close", "task:auth/1", "--force").exit_code == 0
    assert "☑" in _run(root, "tasks").output


def test_the_plan_already_exists_refusal_names_the_verbs_that_do_the_work(tmp_path: Path):
    """It said "Edit it directly" — the one instruction an agent told never to hand-edit cannot follow."""
    root = _repo(tmp_path)
    _plan_with_task(root)
    out = _run(root, "plan", "auth", "-t", "Auth", "--task", "another").output
    named = _named_verbs(out)
    assert {"plan", "close", "tasks"} <= named
    assert "Edit it directly" not in out
    assert _run(root, "plan", "auth", "--append-task", "another").exit_code == 0
    assert "task:auth/2" in _run(root, "tasks").output


def test_a_bare_reaffirm_of_a_legacy_empirical_node_re_stamps_instead_of_refusing(tmp_path: Path):
    """A node claiming ``empirical`` with no ``evidence:`` must still be reaffirmable.

    The evidence gate keyed on ``grounding if grounding is not None else node.grounding``, so a *bare*
    reaffirm of a node that predates the evidence requirement (five in yigraf's own store, all
    pre-1.5.0) was refused by a message about ``--grounding empirical`` — a flag the caller never
    passed. Both exits it named miss what was asked: ``--evidence`` wants an observation invented, and
    the downgrade discards a probably-true tier, to clear a ``concerns`` drift on a different axis. So
    the drift on such a node was unreachable. The gate now keys on the flag actually passed, matching
    its own sibling guard, and the gap is *said* rather than enforced.
    """
    root = _repo(tmp_path)
    mem = _remember(root, "the refresh path is idempotent", "--why", "measured", "--concerns", SYM)
    node = next(p for p in (root / "yigraf" / "memory").glob("*.md") if mem.split(":")[1] in p.read_text())
    node.write_text(node.read_text().replace("grounding: inferred", "grounding: empirical"))
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token + 1\n")

    out = _run(root, "reaffirm", mem).output
    assert "drift cleared" in out, out
    assert "note:" in out and "names no evidence" in out
    assert "No drift." in _drift(root), "and the ⚠ is actually gone"

    # The upgrade it was written to gate is still gated.
    refused = _run(root, "reaffirm", mem, "--grounding", "empirical").output
    assert "requires naming the observation" in refused


# --------------------------------------------------------------------------------------------------
# the guidance the installer writes, rather than the guidance a command prints
# --------------------------------------------------------------------------------------------------

def test_the_skill_install_writes_matches_the_one_this_repo_reads():
    """``hooks.SKILL_MD`` and ``.claude/skills/yigraf/SKILL.md`` are two copies of one document, and
    nothing asserted they agree.

    The consequence is one-directional and silent: this repo *reads* the checked-in file, so editing it
    is what a contributor naturally does and what self-hosting rewards — while every user who runs
    `yigraf install` gets the constant. Guidance improved here would simply never ship, and the divergence
    grows without a single failing test. Caught while adding the section-anchor guidance, which landed in
    the file and not in the constant.
    """
    from yigraf.hooks import skill_text as _skill_text
    SKILL_MD = _skill_text()

    checked_in = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "yigraf" / "SKILL.md"
    assert checked_in.is_file(), "this repo self-hosts the skill it ships"
    assert SKILL_MD == checked_in.read_text(encoding="utf-8"), (
        "hooks.SKILL_MD (what `yigraf install` writes) has drifted from the checked-in SKILL.md "
        "(what this repo reads). Whichever you edited, mirror it into the other."
    )


# --------------------------------------------------------------------------------------------------
# an unsettled rename — the graph re-anchored it, the artifact was never told
# --------------------------------------------------------------------------------------------------

def test_the_verb_the_unsettled_rename_line_names_actually_settles_it(tmp_path: Path):
    """`renamed` is the one signal whose window CLOSES: the rescue is re-derived from the body hash on
    every build, so the guidance has to name a verb that writes it down, and that verb has to work
    before the next edit to that body. Both halves are the invariant this file exists for."""
    root = _repo(tmp_path)
    mem = _remember(root, "refresh must not renew past the absolute cap", "--concerns", SYM)
    (root / "auth" / "session.py").write_text("def rotate(token):\n    return token\n")  # pure rename
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    out = _drift(root)
    assert "renamed" in out and "not yet in the artifact" in out
    assert _run(root, "reanchor", mem, SYM, "sym:auth/session.py#rotate").exit_code == 0
    assert "renamed" not in _drift(root)


def test_the_batch_verb_the_rename_block_names_settles_every_one(tmp_path: Path):
    """The packet's own footer offers `yigraf gc --apply`; a refactor renames in bulk, so the batch
    exit has to reach a task's implements edge and a memory's concerns anchor in one pass."""
    root = _repo(tmp_path)
    _remember(root, "refresh must not renew past the absolute cap", "--concerns", SYM)
    assert _run(root, "plan", "auth", "-t", "Auth", "--task", "do it").exit_code == 0
    assert _run(root, "link", "task:auth/1", SYM).exit_code == 0
    (root / "auth" / "session.py").write_text("def rotate(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    assert "renamed" in _drift(root)
    assert runner.invoke(app, ["gc", str(root), "--apply"]).exit_code == 0
    assert "No drift." in _drift(root)


def test_the_agents_block_install_writes_matches_this_repo_own():
    """The same two-copy hazard for the host-agnostic channel: ``hooks._AGENTS_BLOCK`` is what
    ``install`` writes into a repo's AGENTS.md, and this repo carries its own copy between the fences."""
    from yigraf.hooks import _AGENTS_BLOCK

    agents = Path(__file__).resolve().parent.parent / "AGENTS.md"
    assert _AGENTS_BLOCK.strip() in agents.read_text(encoding="utf-8"), (
        "hooks._AGENTS_BLOCK (what `yigraf install` writes) has drifted from this repo's own AGENTS.md "
        "block. Whichever you edited, mirror it into the other."
    )


def test_the_skill_frontmatter_install_writes_is_valid_yaml():
    """`install` emits SKILL.md; its front matter must parse by spec, not merely in one host's loader.

    The description contains ``` `yigraf status`: ``` and was an unquoted plain scalar, where ``: ``
    terminates the scalar — so `yaml.safe_load` raised "mapping values are not allowed here" at that
    column. Claude Code's own loader tolerates it, which is exactly why nothing caught it; a stricter
    host would silently drop the skill (feedback-v4).
    """
    import re as _re

    import yaml

    from yigraf.hooks import skill_text as _skill_text
    SKILL_MD = _skill_text()

    meta = _re.match(r"---\n(.*?)\n---\n", SKILL_MD, _re.DOTALL)
    assert meta, "SKILL.md must open with a front-matter block"
    loaded = yaml.safe_load(meta.group(1))
    assert loaded["name"] == "yigraf" and loaded["description"].strip()

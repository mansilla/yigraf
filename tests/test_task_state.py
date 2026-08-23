"""`close` / `close --reopen` / `tasks` / `plan --append-task` — the task family's missing verbs.

Tasks were the only authored family whose mutable state had no verb that writes it (feedback-v4 #1).
R6 says the FILE is truth — it does not say a verb may not write the file, and yigraf already shipped
exactly such a verb for the sibling authored family (`intent <slug> --status`). So an agent that had
correctly internalised "never hand-edit an artifact" was structurally unable to close a task, and the
field measured an open count that was **67% false** (8 of 12 already done, some for a day) on the very
line `yigraf status` makes the pre-done authority. The tool even shipped a dedicated ⚠ for the failure
("open but its implementing symbol(s) exist and are current — if the work is done, check its box") and
put a non-verb, "reopen the task", inside `obligations`' `verb=` field, whose whole contract is to hand
over the resolving command.
"""
from pathlib import Path

from typer.testing import CliRunner

from yigraf import artifacts
from yigraf.cli import app

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _run(root: Path, *args: str):
    return runner.invoke(app, [*args, "--repo", str(root)])


def _plan_file(root: Path, slug: str = "auth") -> Path:
    return root / "yigraf" / "plans" / "active" / f"{slug}.md"


def _linked(root: Path) -> str:
    assert _run(root, "plan", "auth", "-t", "Auth", "--task", "harden refresh").exit_code == 0
    assert _run(root, "link", "task:auth/1", SYM).exit_code == 0
    return "task:auth/1"


# -- close / reopen ----------------------------------------------------------------------------------


def test_close_writes_the_checkbox_in_the_committed_file(tmp_path: Path):
    """R6 is untouched: the file stays truth, this verb writes it. Nothing about done-ness is stored in
    the graph — `state` is still derived from the checkbox on every build."""
    root = _repo(tmp_path)
    task = _linked(root)
    assert "- [ ] {#1}" in _plan_file(root).read_text()
    out = _run(root, "close", task)
    assert out.exit_code == 0, out.output
    assert "- [x] {#1}" in _plan_file(root).read_text()
    assert artifacts.read_plan(_plan_file(root)).tasks[0].state == "done"


def test_close_touches_only_the_checkbox(tmp_path: Path):
    """A state change is not a rewrite — the same rule `memory.render_memory` follows for a body."""
    root = _repo(tmp_path)
    task = _linked(root)
    before = _plan_file(root).read_text()
    assert _run(root, "close", task).exit_code == 0
    after = _plan_file(root).read_text()
    assert after == before.replace("- [ ] {#1}", "- [x] {#1}", 1)


def test_reopen_is_the_verb_the_stale_advice_names(tmp_path: Path):
    root = _repo(tmp_path)
    task = _linked(root)
    assert _run(root, "close", task).exit_code == 0
    out = _run(root, "close", task, "--reopen")
    assert out.exit_code == 0 and "- [ ] {#1}" in _plan_file(root).read_text()
    assert "anchors are untouched" in out.output  # reopening is not unlinking


def test_close_refuses_a_task_that_implements_nothing(tmp_path: Path):
    """"Done" and "anchored" land together, so the stale mechanism works as designed: a completion
    that is never recorded against a symbol can never go STALE."""
    root = _repo(tmp_path)
    assert _run(root, "plan", "auth", "-t", "Auth", "--task", "write the note").exit_code == 0
    out = _run(root, "close", "task:auth/1")
    assert out.exit_code == 0                                  # guidance, not a crash (design law #1)
    assert "could never go STALE" in out.output
    assert "- [ ] {#1}" in _plan_file(root).read_text()        # and it really refused
    assert _run(root, "close", "task:auth/1", "--force").exit_code == 0
    assert "- [x] {#1}" in _plan_file(root).read_text()


def test_closing_a_done_task_and_reopening_an_open_one_are_guided(tmp_path: Path):
    root = _repo(tmp_path)
    task = _linked(root)
    assert "already open" in _run(root, "close", task, "--reopen").output
    assert _run(root, "close", task).exit_code == 0
    out = _run(root, "close", task)
    assert "already done" in out.output and "--reopen" in out.output


def test_an_unknown_task_names_what_exists(tmp_path: Path):
    root = _repo(tmp_path)
    _linked(root)
    assert "task:auth/1" in _run(root, "close", "task:auth/9").output
    assert "yigraf tasks" in _run(root, "close", "not-a-locator").output


def test_a_closed_task_that_drifts_becomes_a_stale_completion(tmp_path: Path):
    """The whole point of the link-then-close pairing, end to end."""
    root = _repo(tmp_path)
    task = _linked(root)
    assert _run(root, "close", task).exit_code == 0
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token + 1\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    out = runner.invoke(app, ["drift", "--stale", str(root)]).output
    assert "STALE completions" in out and task in out
    assert _run(root, "link", task, SYM).exit_code == 0  # re-link clears it once re-verified
    assert "no stale completions" in runner.invoke(app, ["drift", "--stale", str(root)]).output


# -- tasks -------------------------------------------------------------------------------------------


def test_tasks_answers_what_is_outstanding_without_a_query_matching(tmp_path: Path):
    """`context "what is outstanding" --family plan` returned 0 nodes — the seeder is semantic even
    under `--family`. `status` gave a bare count, `show plan:<slug>` listed ids without state, and
    `drift --stale` listed only done-and-drifted ones. The surface existed and could not be addressed."""
    root = _repo(tmp_path)
    _linked(root)
    assert _run(root, "plan", "auth", "--append-task", "rotate on reuse").exit_code == 0
    assert _run(root, "close", "task:auth/1").exit_code == 0

    both = _run(root, "tasks").output
    assert "☑ task:auth/1" in both and "☐ task:auth/2" in both
    assert "☐ task:auth/2" in _run(root, "tasks", "--open").output
    assert "task:auth/1" not in _run(root, "tasks", "--open").output
    assert "☑ task:auth/1" in _run(root, "tasks", "--done").output
    assert "No stale completions." in _run(root, "tasks", "--stale").output


def test_tasks_marks_a_stale_completion_distinctly(tmp_path: Path):
    root = _repo(tmp_path)
    task = _linked(root)
    assert _run(root, "close", task).exit_code == 0
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token + 1\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    out = _run(root, "tasks", "--stale").output
    assert f"⚠ {task}" in out and "--reopen" in out


def test_tasks_scopes_to_one_plan_and_guides_on_an_unknown_one(tmp_path: Path):
    root = _repo(tmp_path)
    _linked(root)
    assert _run(root, "plan", "billing", "-t", "Billing", "--task", "meter usage").exit_code == 0
    scoped = _run(root, "tasks", "auth").output
    assert "task:auth/1" in scoped and "task:billing/1" not in scoped
    assert "Known: " in _run(root, "tasks", "nope").output


def test_open_and_done_are_disjoint(tmp_path: Path):
    root = _repo(tmp_path)
    _linked(root)
    assert "disjoint" in _run(root, "tasks", "--open", "--done").output


# -- plan --append-task ------------------------------------------------------------------------------


def test_append_task_extends_a_live_plan(tmp_path: Path):
    """A campaign that ran 125 cells across four stages created ZERO tasks, partly because
    `plan <existing-slug> --task` refuses — so the graph held its decisions and none of its work."""
    root = _repo(tmp_path)
    _linked(root)
    out = _run(root, "plan", "auth", "--append-task", "rotate on reuse", "--append-task", "cap at 24h")
    assert out.exit_code == 0, out.output
    assert "task:auth/2" in out.output and "task:auth/3" in out.output
    nums = [t.num for t in artifacts.read_plan(_plan_file(root)).tasks]
    assert nums == [1, 2, 3]


def test_appended_numbers_continue_past_the_highest_and_are_never_reused(tmp_path: Path):
    """An id already recorded on a link edge or a memory must not come to mean a different task."""
    root = _repo(tmp_path)
    assert _run(root, "plan", "auth", "-t", "Auth", "--task", "a", "--task", "b").exit_code == 0
    text = _plan_file(root).read_text().replace("- [ ] {#1} a\n", "")  # task 1 deleted by hand
    _plan_file(root).write_text(text)
    assert _run(root, "plan", "auth", "--append-task", "c").exit_code == 0
    assert [t.num for t in artifacts.read_plan(_plan_file(root)).tasks] == [2, 3]


def test_append_to_a_plan_that_does_not_exist_is_guided(tmp_path: Path):
    root = _repo(tmp_path)
    out = _run(root, "plan", "nope", "--append-task", "x")
    assert out.exit_code == 0 and "Create it with" in out.output


def test_the_already_exists_refusal_stops_saying_edit_it_directly(tmp_path: Path):
    """That was the one instruction an agent told never to hand-edit an artifact cannot follow."""
    root = _repo(tmp_path)
    _linked(root)
    out = _run(root, "plan", "auth", "-t", "Auth", "--task", "another").output
    assert "Edit it directly" not in out
    assert "--append-task" in out and "yigraf close" in out and "yigraf tasks" in out


def test_creating_without_a_title_is_guided_not_a_usage_error(tmp_path: Path):
    """`--title` became optional so `--append-task` could omit it; a missing one must still guide."""
    root = _repo(tmp_path)
    out = _run(root, "plan", "fresh", "--task", "x")
    assert out.exit_code == 0 and "--title is required" in out.output

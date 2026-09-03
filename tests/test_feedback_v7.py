"""The four findings from the 1.9.1 field feedback (feedback-v7), each pinned by the failure it closes.

Two of them are about a *sentence* again — a success line that says a move happened while the anchor
count went down, and a knob whose documented effect it did not have on a whole class of document. The
third is the first data-loss path the field has reported: an unset shell variable overwriting a live
plan. Grouped by finding, as in the v5/v6 files.
"""
import json
from pathlib import Path

from typer.testing import CliRunner

from yigraf import sectionfit
from yigraf.cli import app

runner = CliRunner()

DOC = "docs/notes.md"


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    return tmp_path


def _doc(root: Path, text: str) -> Path:
    doc = root / DOC
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(text)
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    return root


def _bigger_doc(root: Path) -> Path:
    return _doc(root, "# Robot Notes\n\nGeneral reference.\n\n"
                      "## MPPI\n\nSampling params control the rollout horizon.\n\n"
                      "## Wheel Odometry\n\nA model of the wheels and their slip on gravel.\n")


def _remember(root: Path, statement: str, *args: str):
    return runner.invoke(app, ["remember", statement, "--why", "measured it",
                               *args, "--repo", str(root)])


def _only_memory_id(root: Path) -> str:
    from yigraf import memory
    nodes = list(memory.iter_memories(root))
    assert len(nodes) == 1
    return nodes[0].id


# --- G#1: an empty slug is silently destructive on a write verb -------------------------------------

def test_an_empty_plan_slug_is_refused_before_anything_is_written(tmp_path: Path):
    """`yigraf plan ""` — an unset `$SLUG` — wrote `plans/active/.md` and reported success. It passed
    the guard twice over: `not value` short-circuited out, and `_PATH_SHAPED` does not match `""`."""
    root = _repo(tmp_path)

    result = runner.invoke(app, ["plan", "", "-t", "FIRST", "--task", "a", "--repo", str(root)])

    assert result.exit_code == 0  # design law #1: guidance, never a stack trace
    assert "empty slug" in result.output.lower()
    assert not (root / "yigraf" / "plans" / "active" / ".md").exists()
    assert list((root / "yigraf" / "plans" / "active").glob("*")) == []


def test_an_empty_slug_is_refused_on_every_verb_that_composes_one_into_a_path(tmp_path: Path):
    """`intent` and `supersede-intent` wrote the same dotfile; only `plan` lost data, but the bypass
    was general, and `intent`'s own refusal then handed over a command with a blank where the slug
    goes."""
    root = _repo(tmp_path)

    for args in (["intent", "", "-s", "x SHALL y"],
                 ["supersede-intent", "old", "", "-s", "x SHALL z"]):
        result = runner.invoke(app, args + ["--repo", str(root)])
        assert result.exit_code == 0
        assert "empty slug" in result.output.lower()
    assert list((root / "yigraf" / "intents").glob("*")) == []


def test_tasks_with_no_argument_still_means_every_plan(tmp_path: Path):
    """The regression the obvious one-liner causes: `_require_slug` is also called from `tasks` with
    `None`, where `None` means *every plan*, so refusing falsy values breaks the one surface an agent
    asks what is left."""
    root = _repo(tmp_path)
    assert runner.invoke(app, ["plan", "real", "-t", "R", "--task", "a",
                               "--repo", str(root)]).exit_code == 0

    result = runner.invoke(app, ["tasks", "--repo", str(root)])

    assert result.exit_code == 0 and "task:real/1" in result.output


def test_a_plan_is_not_clobbered_when_the_glob_stem_and_the_resolved_path_disagree(tmp_path: Path):
    """The seatbelt under the guard, and the half that actually stops the loss: `_find_plan_file`
    compares a glob's `path.stem`, and `Path(".md").stem` is `".md"` — so the empty-slug plan failed
    to find itself and the second call replaced its title, tasks and stamped `implements` anchor while
    printing "Created". Keyed on the resolved path, the file is found whatever its name."""
    root = _repo(tmp_path)
    active = root / "yigraf" / "plans" / "active"
    active.mkdir(parents=True, exist_ok=True)
    # Written directly, because the guard now makes this unreachable through the CLI — the point is
    # that the anti-clobber check no longer *depends* on the guard catching every such shape.
    (active / ".md").write_text("---\nid: 'plan:'\ntitle: FIRST\n---\n\n- [ ] task:/1 first task\n")

    result = runner.invoke(app, ["plan", ".md", "-t", "SECOND", "--task", "b", "--repo", str(root)])

    assert result.exit_code == 0
    assert "already exists" in result.output
    assert "FIRST" in (active / ".md").read_text()


# --- G#2: the margin was inert when only one section was offerable ----------------------------------

def _one_subdivision(root: Path) -> Path:
    """Their `coding-conventions.md` shape: a document-spanning title plus exactly one `##`. The title
    is excluded as a narrowing, leaving one offerable section and therefore no runner-up."""
    return _doc(root, "# Widget notes\n\nProse under the title, no heading of its own.\n\n"
                      "## Applying these\n\nThe threshold is applied per widget, and a violation is a "
                      "finding rather than a licence.\n")


CLAIM = "A violation is a finding rather than a licence."


def test_one_offerable_section_is_not_a_choice_and_is_never_offered(tmp_path: Path):
    """1.9.0's notes said this exemption fell out of the design. It did not: the test was written on
    the raw section count, which counts the title too, so `len(sections) < 2` was False and the file
    was offered `#applying-these` after all."""
    root = _one_subdivision(_repo(tmp_path))

    out = _remember(root, CLAIM, "--concerns", f"file:{DOC}").output

    assert "Offer" not in out


def test_the_margin_is_live_wherever_the_offer_can_fire(tmp_path: Path):
    """The knob did nothing on that whole shape — `1e9` offered as readily as `2.0`, because the
    comparison is against a runner-up that does not exist. There was nothing between inert and off."""
    root = _one_subdivision(_repo(tmp_path))

    assert all(sectionfit.best_section(root, DOC, CLAIM, m) is None for m in (0.5, 2.0, 1e9))


def test_two_offerable_sections_still_answer_to_the_margin(tmp_path: Path):
    """The fix narrows what is *exempt*, not what is offered: a real subdivision is unaffected, and a
    claim the document says in two places moves in and out with the margin — which is what makes the
    knob re-fittable from a store's own history."""
    root = _bigger_doc(_repo(tmp_path))

    assert sectionfit.best_section(root, DOC, "MPPI rollout horizon tunings are relative.", 2.0) == "mppi"
    shared = "The rollout horizon and the wheel slip interact."
    assert sectionfit.best_section(root, DOC, shared, 2.0) is None
    assert sectionfit.best_section(root, DOC, shared, 1.0) is not None


def test_a_runner_up_that_scores_nothing_is_an_unbounded_ratio_not_an_inert_margin(tmp_path: Path):
    """The distinction the fix turns on. A second section scoring zero passes at every margin because
    the ratio is unbounded — that is the definition and the strongest signal the scorer has. What the
    zero must not mean is "no runner-up existed", which is the shape now refused structurally."""
    root = _bigger_doc(_repo(tmp_path))

    fit = sectionfit.section_fit(root, DOC, "MPPI rollout horizon tunings are relative.")
    assert fit.candidate == "mppi" and fit.runner_up == 0.0 and fit.wins_by(1e9)

    inert = sectionfit.section_fit(_one_subdivision(_repo(tmp_path / "other")), DOC, CLAIM)
    assert inert.candidate is None and not inert.wins_by(0.5)


# --- G#3: reanchor reported a removal as a move -----------------------------------------------------

def _both_anchors(tmp_path: Path) -> tuple[Path, str]:
    root = _bigger_doc(_repo(tmp_path))
    assert _remember(root, "MPPI rollout horizon tunings are relative.",
                     "--concerns", f"file:{DOC}",
                     "--concerns", f"file:{DOC}#mppi").exit_code == 0
    return root, _only_memory_id(root)


def test_reanchoring_onto_an_anchor_the_node_already_carries_says_it_removed_one(tmp_path: Path):
    """It cannot move anything, so it drops the old anchor — 2 → 1 — and printed `old ⇒ new`. The
    removal is defensible; the report of it was not, on a node no verb can add a `concerns` anchor
    back to."""
    root, mem_id = _both_anchors(tmp_path)

    result = runner.invoke(app, ["reanchor", mem_id, f"file:{DOC}", f"file:{DOC}#mppi",
                                 "--repo", str(root)])

    assert result.exit_code == 0
    assert "⇒" not in result.output
    assert "Dropped" in result.output and "REMOVED an anchor rather than moving one" in result.output
    assert f"yigraf unlink {mem_id} file:{DOC}" in result.output
    shown = runner.invoke(app, ["show", mem_id, "--repo", str(root)]).output
    assert f"file:{DOC}#mppi" in shown and f"concerns      file:{DOC}\n" not in shown


def test_a_genuine_move_still_reads_as_a_move(tmp_path: Path):
    """The other branch, unchanged — the honest wording must not leak onto the case it is not about."""
    root, mem_id = _both_anchors(tmp_path)

    out = runner.invoke(app, ["reanchor", mem_id, f"file:{DOC}#mppi", f"file:{DOC}#wheel-odometry",
                              "--repo", str(root)]).output

    assert f"file:{DOC}#mppi ⇒ file:{DOC}#wheel-odometry" in out
    assert "Dropped" not in out
    assert "The claim and its history are unchanged" in out


def test_the_offer_does_not_route_into_the_removal(tmp_path: Path):
    """The fifth exemption, and the one that was missing: the `reanchor` the offer hands over is
    exactly the command that hits that branch, so a node already carrying the section is offered
    nothing."""
    root, _ = _both_anchors(tmp_path)

    out = _remember(root, "MPPI rollout horizon sampling is relative to the params.",
                    "--concerns", f"file:{DOC}",
                    "--concerns", f"file:{DOC}#mppi").output

    assert "Offer" not in out
    # And nothing is logged either: this is not a candidate the margin could ever be right about, so a
    # row saying `offered: false` beside scores that clear the threshold would poison the re-fit.
    assert not (root / "yigraf" / ".local" / "section-offers.json").exists()


# --- G#4: the offer recorded nothing ----------------------------------------------------------------

def _ledger(root: Path) -> list[dict]:
    return json.loads((root / "yigraf" / ".local" / "section-offers.json").read_text())


def test_every_considered_anchor_is_recorded_with_both_scores(tmp_path: Path):
    """The accept rate that should set `section_offer_margin` was uncollectable by anyone: nothing
    distinguishes a section anchor its author chose from one they took because yigraf offered it, and
    `reanchor` writes no supersedes edge while a `concerns` entry carries no timestamp."""
    root = _bigger_doc(_repo(tmp_path))

    _remember(root, "MPPI rollout horizon tunings are relative.", "--concerns", f"file:{DOC}")

    row, = _ledger(root)
    assert row["ref"] == f"file:{DOC}" and row["candidate"] == "mppi" and row["offered"] is True
    assert row["top"] > row["runner_up"] >= 0.0
    assert row["mem"].startswith("mem:") and isinstance(row["at"], float)


def test_a_suppressed_offer_is_recorded_too(tmp_path: Path):
    """The half a row written at the print site cannot see — and the only half that can re-fit the
    threshold, since the margin's whole effect is which of these it lets through."""
    root = _bigger_doc(_repo(tmp_path))

    out = _remember(root, "The rollout horizon and the wheel slip interact.",
                    "--concerns", f"file:{DOC}").output

    assert "Offer" not in out
    row, = _ledger(root)
    assert row["offered"] is False and row["candidate"] is not None
    assert row["top"] < 2.0 * row["runner_up"]  # blocked by the margin, not by scoring nothing


def test_a_stored_row_re_fits_the_threshold_it_was_written_under(tmp_path: Path):
    """The point of storing both scores rather than the verdict: one window re-scores offline at every
    candidate margin, through the same gate the offer itself uses."""
    root = _bigger_doc(_repo(tmp_path))
    _remember(root, "The rollout horizon and the wheel slip interact.", "--concerns", f"file:{DOC}")

    row, = _ledger(root)
    fit = sectionfit.Fit(row["candidate"], row["top"], row["runner_up"])

    assert fit.wins_by(2.0) is False and fit.wins_by(1.0) is True


def test_the_ledger_is_machine_local_and_never_committed(tmp_path: Path):
    """Volatile, gitignored, never the graph — the rule that keeps usage/last_seen out of the
    projection (design law #6), and the shape `reaffirms.json` already has."""
    root = _bigger_doc(_repo(tmp_path))
    _remember(root, "MPPI rollout horizon tunings are relative.", "--concerns", f"file:{DOC}")

    assert (root / "yigraf" / ".local" / "section-offers.json").exists()
    assert ".local/" in (root / "yigraf" / ".gitignore").read_text()

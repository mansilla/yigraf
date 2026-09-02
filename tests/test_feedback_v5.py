"""The eight fixes from the 1.7.1 field feedback (feedback-v5), each pinned by the failure it closes.

Grouped by finding rather than by module, because that is the unit each one was reported and argued as
— a reader who comes back to one of these wants the whole story of that finding in one place, and
several of them span drift/status/obligations/retrieval at once.
"""
from pathlib import Path

from typer.testing import CliRunner

from yigraf import obligations, retrieval, status
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.drift import compute_drift, is_stale_completion, is_surfaced, pending_renames
from yigraf.extract import build_graph
from yigraf.status import compute_status

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "auth/session.py"


def _linked_repo(tmp_path: Path) -> Path:
    """A repo with one task linked (``implements``) to ``refresh``, anchored."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / SRC
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth",
                               "--task", "do it"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)]).exit_code == 0
    return tmp_path


def _mark_done(root: Path) -> None:
    plan = root / "yigraf" / "plans" / "active" / "auth.md"
    plan.write_text(plan.read_text().replace("- [ ] {#1}", "- [x] {#1}"))


def _rename_the_symbol(root: Path) -> None:
    """Rename ``refresh`` → ``renew`` with the body byte-identical: a content-hash match, so the graph
    re-anchors it and the artifact is left naming the locator the subject left."""
    (root / SRC).write_text("def renew(token):\n    return token\n")


def _graph(root: Path):
    return build_graph(root, default_config())[0]


# ── D#1: a rename is not a re-verify prompt, so the done-task suppression must not eat it ───────────

def test_a_rename_on_a_done_task_is_surfaced(tmp_path: Path):
    """The reported failure: `drift` said "No drift." while a rename was pending, because the task was
    closed. The done-task rule withholds a *re-verification prompt*; a rename is not one — the content
    hash MATCHED, so there is nothing to re-verify and nothing to rubber-stamp."""
    root = _linked_repo(tmp_path)
    _mark_done(root)
    _rename_the_symbol(root)
    graph = _graph(root)
    renamed = [i for i in compute_drift(graph) if i.kind == "renamed"]
    assert len(renamed) == 1
    assert is_surfaced(graph, renamed[0]) is True


def test_a_soft_drift_on_a_done_task_is_still_suppressed(tmp_path: Path):
    """The other half, and the one that must not regress: int:drift-done-suppression is untouched for
    the kinds it was written about. Only ``renamed`` is exempt."""
    root = _linked_repo(tmp_path)
    _mark_done(root)
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")
    graph = _graph(root)
    soft = [i for i in compute_drift(graph) if i.kind == "soft"]
    assert len(soft) == 1 and is_surfaced(graph, soft[0]) is False


def test_a_rename_is_never_counted_as_a_stale_completion(tmp_path: Path):
    """Exempting it from one predicate must not enrol it in the other: ``stale`` means the evidence for
    a completion CHANGED, and a rename is proof it did not (mem:e5678245348632a7 — two suppression
    rules can share a gate, never an inverse)."""
    root = _linked_repo(tmp_path)
    _mark_done(root)
    _rename_the_symbol(root)
    graph = _graph(root)
    assert [i for i in compute_drift(graph) if is_stale_completion(graph, i)] == []


def test_drift_cli_reports_a_rename_on_a_closed_task(tmp_path: Path):
    root = _linked_repo(tmp_path)
    _mark_done(root)
    _rename_the_symbol(root)
    result = runner.invoke(app, ["drift", str(root)])
    assert result.exit_code == 0
    assert "renamed" in result.output and "gc --apply" in result.output


def test_status_counts_a_pending_rename(tmp_path: Path):
    """The ask itself: the expiring signal on the surface every agent already checks before handing off."""
    root = _linked_repo(tmp_path)
    _rename_the_symbol(root)
    summary = compute_status(_graph(root), root, default_config())
    assert summary.renames == 1
    assert "⚠ 1 rename" in summary.render_line()
    assert summary.as_dict()["renames"] == 1


def test_a_clean_repo_renders_no_rename_segment(tmp_path: Path):
    """Silence is a feature (design law #4): the segment exists only when there is something to settle."""
    summary = compute_status(_graph(_linked_repo(tmp_path)), tmp_path, default_config())
    assert summary.renames == 0 and "rename" not in summary.render_line()


def test_a_pending_rename_is_an_obligation_at_the_turn_boundary(tmp_path: Path):
    """The Stop hook's channel. It ranks above stale/drift because it is the only one with a deadline."""
    root = _linked_repo(tmp_path)
    _rename_the_symbol(root)
    found = obligations.obligations(_graph(root), root, default_config())
    renames = [o for o in found if o.kind == "rename"]
    assert len(renames) == 1
    assert "gc --apply" in renames[0].verb
    assert obligations.KIND_ORDER.index("rename") < obligations.KIND_ORDER.index("stale")


def test_session_start_re_injects_an_unsettled_rename(tmp_path: Path):
    """A `/clear` is exactly when the agent forgets it renamed anything, so the orientation packet is
    where the reminder has to survive."""
    root = _linked_repo(tmp_path)
    _rename_the_symbol(root)
    result = retrieval.session_context(_graph(root), default_config(), root=root)
    assert result is not None and "rename" in result.text.lower()


def test_pending_renames_and_stale_completions_are_disjoint(tmp_path: Path):
    root = _linked_repo(tmp_path)
    _mark_done(root)
    _rename_the_symbol(root)
    graph = _graph(root)
    assert len(pending_renames(graph)) == 1
    assert [i.task_id for i in pending_renames(graph)] == ["task:auth/1"]


# ── A: a schema decline is not an absence ───────────────────────────────────────────────────────────

def _downgrade_view(root: Path) -> None:
    import sqlite3

    from yigraf import graphdb
    conn = sqlite3.connect(graphdb.db_path(root))
    conn.execute("UPDATE meta SET value='1' WHERE key='db_schema_version'")
    conn.commit()
    conn.close()


def test_an_upgraded_schema_reads_as_old_schema_not_absent(tmp_path: Path):
    """What an upgrade actually produces. Reported as ``absent``, it was diagnosed as a lost graph."""
    from yigraf import graphdb
    root = _linked_repo(tmp_path)
    graphdb.load_or_build(root, default_config())  # materialize, then age it
    _downgrade_view(root)
    summary = compute_status(_graph(root), root, default_config())
    assert summary.freshness == "old-schema"
    assert "rebuilds on next read" in summary.render_line()
    assert summary.freshness_note() is not None


def test_a_missing_view_still_reads_as_absent(tmp_path: Path):
    """The token stays meaningful by staying narrow: ``absent`` now means only "there is no view"."""
    from yigraf import graphdb
    root = _linked_repo(tmp_path)
    graphdb.db_path(root).unlink(missing_ok=True)
    summary = compute_status(_graph(root), root, default_config())
    assert summary.freshness == "absent"


def test_view_state_names_each_condition(tmp_path: Path):
    from yigraf import graphdb
    root = _linked_repo(tmp_path)
    path = graphdb.db_path(root)
    path.unlink(missing_ok=True)
    assert graphdb.view_state(path) == "missing"
    graphdb.load_or_build(root, default_config())
    assert graphdb.view_state(path) == "present"
    _downgrade_view(root)
    assert graphdb.view_state(path) == "old-schema"


def test_a_read_path_still_heals_a_declined_view(tmp_path: Path):
    """The withdrawn ask, pinned so it stays true: the decline is self-healing on the first real read."""
    from yigraf import graphdb
    root = _linked_repo(tmp_path)
    graphdb.load_or_build(root, default_config())
    _downgrade_view(root)
    graphdb.load_or_build(root, default_config())
    assert graphdb.view_state(graphdb.db_path(root)) == "present"


# ── B: a typed heading resolves, and the reanchor refusal keeps its "did you mean" ───────────────────

DOC = "docs/design.md"


def _doc_repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    doc = tmp_path / DOC
    doc.parent.mkdir(parents=True)
    doc.write_text("# Design\n\n## Planning index\n\nIndex prose.\n\n## Rules\n\nThe rules body.\n\n"
                   "## Turning Radius\n\nThe vehicle turns.\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _capture(root: Path, locus: str):
    return runner.invoke(app, ["remember", "rules are normative", "--why", "t",
                               "--concerns", locus, "--repo", str(root)])


def test_a_heading_typed_with_its_own_capitalisation_is_canonicalized(tmp_path: Path):
    root = _doc_repo(tmp_path)
    result = _capture(root, f"file:{DOC}#Rules")
    assert result.exit_code == 0
    assert f"concerns file:{DOC}#rules" in result.output


def test_a_heading_typed_with_spaces_is_canonicalized(tmp_path: Path):
    """Case-insensitivity alone would not have reached this one — the space fails too."""
    root = _doc_repo(tmp_path)
    result = _capture(root, f"file:{DOC}#Turning Radius")
    assert result.exit_code == 0
    assert f"concerns file:{DOC}#turning-radius" in result.output


def test_a_slug_that_already_resolves_is_left_exactly_as_typed(tmp_path: Path):
    root = _doc_repo(tmp_path)
    assert f"concerns file:{DOC}#rules" in _capture(root, f"file:{DOC}#rules").output


def test_a_heading_in_neither_spelling_still_gets_the_normal_guidance(tmp_path: Path):
    """The canonicalizer must not swallow a real miss: it corrects a spelling, it does not invent one."""
    root = _doc_repo(tmp_path)
    result = _capture(root, f"file:{DOC}#Nonexistent Heading")
    assert "Did you mean" in result.output or "Headings in" in result.output


def test_the_reanchor_refusal_carries_the_section_suggestion(tmp_path: Path):
    """`cli.py`'s reanchor refusal was the one call site that dropped ``repo``, so the tail that turns a
    missed guess into a single retry never fired on the newest anchor kind."""
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}#rules").exit_code == 0
    mem_id = _only_memory_id(root)
    result = runner.invoke(app, ["reanchor", mem_id, f"file:{DOC}#rules", f"file:{DOC}#Ruls",
                                 "--repo", str(root)])
    assert result.exit_code == 0 and "Did you mean" in result.output
    assert f"file:{DOC}#rules" in result.output


def test_reanchor_accepts_a_heading_typed_as_written(tmp_path: Path):
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}#rules").exit_code == 0
    mem_id = _only_memory_id(root)
    result = runner.invoke(app, ["reanchor", mem_id, f"file:{DOC}#Rules",
                                 f"file:{DOC}#Turning Radius", "--repo", str(root)])
    assert result.exit_code == 0 and "Reanchored" in result.output
    assert f"file:{DOC}#turning-radius" in result.output


def _only_memory_id(root: Path) -> str:
    from yigraf import memory
    nodes = memory.iter_memories(root)
    assert len(nodes) == 1
    return nodes[0].id


# ── D#4: the locus form of reaffirm reaches the section anchors inside a file ────────────────────────

def test_a_whole_file_reaffirm_reaches_a_section_anchor(tmp_path: Path):
    """Section anchors are the recommended cure for a prose doc's false drift, so the cure and the
    batch-clear have to compose."""
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}#turning-radius").exit_code == 0
    doc = root / DOC
    doc.write_text(doc.read_text().replace("The vehicle turns.", "The vehicle turns on a dime."))
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    result = runner.invoke(app, ["reaffirm", f"file:{DOC}", "--repo", str(root)])
    assert result.exit_code == 0
    assert "reached 1 section anchor" in result.output and "drift cleared" in result.output
    assert runner.invoke(app, ["drift", str(root)]).output.strip().startswith("No drift")


def test_naming_a_section_never_reaches_the_whole_file(tmp_path: Path):
    """Containment is one-way. Reaching upward would assert a re-verification the caller did not make."""
    from yigraf.cli import _covered_loci
    assert _covered_loci(f"file:{DOC}#rules", {f"file:{DOC}"}) == set()
    assert _covered_loci(f"file:{DOC}", {f"file:{DOC}#rules"}) == {f"file:{DOC}#rules"}


def test_a_line_range_is_not_covered_by_its_file(tmp_path: Path):
    """A positional pin is not a named part of the document: an edit above it moves what it points at
    without the file-level reader ever seeing a difference."""
    from yigraf.cli import _covered_loci
    assert _covered_loci(f"file:{DOC}", {f"file:{DOC}:L1-L5"}) == set()


# ── E: gc says what it is about to cost, and show can still read what it archived ────────────────────

def _churn_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A repo holding one superseded memory (collectable churn) whose anchor is a live glue file."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "Dockerfile").write_text("FROM scratch\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text("def beta():\n    return 2\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["remember", "dockerfile stays minimal", "--why", "t",
                               "--concerns", "file:Dockerfile", "--repo", str(tmp_path)]).exit_code == 0
    old_id = _only_memory_id(tmp_path)
    assert runner.invoke(app, ["supersede", old_id, "the rule lives on beta now", "--why", "moved",
                               "--concerns", "sym:src/m.py#beta",
                               "--repo", str(tmp_path)]).exit_code == 0
    from yigraf import memory
    new_id = next(m.id for m in memory.iter_memories(tmp_path) if m.id != old_id)
    return tmp_path, old_id, new_id


def test_the_gc_dry_run_says_the_ids_stop_resolving(tmp_path: Path):
    """"Never delete, kept for history" was true of the FILE and not of the ID, and the difference is
    invisible until prose outside the graph cites one."""
    root, _old, _new = _churn_repo(tmp_path)
    result = runner.invoke(app, ["gc", str(root)])
    assert result.exit_code == 0
    assert "stop resolving" in result.output and "repoint" in result.output


def test_show_reads_an_archived_memory_and_names_its_successor(tmp_path: Path):
    root, old_id, new_id = _churn_repo(tmp_path)
    assert runner.invoke(app, ["gc", str(root), "--apply"]).exit_code == 0
    result = runner.invoke(app, ["show", old_id, "--repo", str(root)])
    assert result.exit_code == 0
    assert "ARCHIVED" in result.output and new_id in result.output


def test_an_id_that_never_existed_is_still_an_unknown_node(tmp_path: Path):
    """The archive fallback must not turn every typo into a confident answer."""
    root, _old, _new = _churn_repo(tmp_path)
    result = runner.invoke(app, ["show", "mem:ffffffffffffffff", "--repo", str(root)])
    assert "No node" in result.output


def test_gc_reports_the_placeholder_symbols_it_released(tmp_path: Path):
    """A symbol count DROPPING after a garbage collection is alarming, and the cause is benign — a
    retired memory's anchor projected the placeholder, so collecting the memory collects it."""
    root, _old, _new = _churn_repo(tmp_path)
    before = compute_status(_graph(root), root, default_config()).symbols
    result = runner.invoke(app, ["gc", str(root), "--apply"])
    assert result.exit_code == 0 and "placeholder anchor node" in result.output
    after = compute_status(_graph(root), root, default_config()).symbols
    assert after < before


def test_the_placeholder_line_is_silent_when_nothing_was_released(tmp_path: Path):
    root = _linked_repo(tmp_path)
    assert "placeholder anchor node" not in runner.invoke(app, ["gc", str(root)]).output


# ── D: the generated skill carries the version that wrote it ─────────────────────────────────────────

def test_the_generated_skill_is_version_stamped(tmp_path: Path):
    from yigraf import __version__
    from yigraf.hooks import SKILL_STAMP, skill_text
    assert f"{SKILL_STAMP}{__version__} -->" in skill_text()


def test_a_stale_skill_stamp_is_reported_on_status(tmp_path: Path):
    """An upgrade replaces the CLI and leaves the skill untouched, so the doc can name verbs that are
    gone — the tool telling the agent the wrong thing about itself."""
    from yigraf.hooks import SKILL_STAMP, installed_skill_version, skill_text
    root = _linked_repo(tmp_path)
    skill = root / ".claude" / "skills" / "yigraf" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(skill_text().replace(f"{SKILL_STAMP}", f"{SKILL_STAMP}0.9.0 -->\n<!-- x: ", 1))
    assert installed_skill_version(root) == "0.9.0"
    summary = compute_status(_graph(root), root, default_config())
    assert summary.skill_behind == "0.9.0" and "⬆ skill 0.9.0" in summary.render_line()


def test_a_current_skill_says_nothing(tmp_path: Path):
    from yigraf.hooks import skill_text
    root = _linked_repo(tmp_path)
    skill = root / ".claude" / "skills" / "yigraf" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(skill_text())
    summary = compute_status(_graph(root), root, default_config())
    assert summary.skill_behind is None and "skill" not in summary.render_line()


def test_an_unstamped_or_missing_skill_says_nothing(tmp_path: Path):
    """"I cannot tell" is not "you are behind" — guessing would fire once for every user on the release
    that introduces stamping, which is how a real alarm gets trained away."""
    from yigraf.hooks import installed_skill_version
    root = _linked_repo(tmp_path)
    assert installed_skill_version(root) is None
    skill = root / ".claude" / "skills" / "yigraf" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("---\nname: yigraf\n---\n\nan old, unstamped skill\n")
    assert installed_skill_version(root) is None


# ── C: the changelog ships with the tool ─────────────────────────────────────────────────────────────

def test_changelog_prints_releases(tmp_path: Path):
    result = runner.invoke(app, ["changelog", "--limit", "1"])
    assert result.exit_code == 0 and result.output.lstrip().startswith("## [")


def test_changelog_since_reports_how_many_releases_arrive_at_once(tmp_path: Path):
    """The specific thing that made this ask: releases that never reached PyPI arrive folded into a
    later one, and nothing installed could say so."""
    result = runner.invoke(app, ["changelog", "--since", "1.0.0"])
    assert result.exit_code == 0 and "releases are between" in result.output


def test_changelog_since_the_newest_version_is_a_clean_refusal(tmp_path: Path):
    result = runner.invoke(app, ["changelog", "--since", "99.0.0"])
    assert result.exit_code == 0 and "Nothing newer" in result.output


def test_the_wheel_config_ships_the_changelog(tmp_path: Path):
    """Pinned in config rather than by building a wheel: the build is slow, and the thing that broke
    three upgrades in a row was the absence of exactly this line."""
    import tomllib
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    include = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert include["CHANGELOG.md"] == "yigraf/CHANGELOG.md"


# ── Still-open #1: the reaffirm burst guard ──────────────────────────────────────────────────────────

def _drifted_memories(tmp_path: Path, count: int) -> tuple[Path, list[str]]:
    """A repo with ``count`` memories, each concerning its own symbol, all soft-drifted."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    names = [chr(ord("a") + i) for i in range(count)]
    src = tmp_path / "src"
    src.mkdir()
    (src / "m.py").write_text("".join(f"def {n}():\n    return 1\n" for n in names))
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    for n in names:
        assert runner.invoke(app, ["remember", f"rule about {n}", "--why", "t",
                                   "--concerns", f"sym:src/m.py#{n}",
                                   "--repo", str(tmp_path)]).exit_code == 0
    (src / "m.py").write_text("".join(f"def {n}():\n    return 2\n" for n in names))
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    from yigraf import memory
    return tmp_path, [m.id for m in memory.iter_memories(tmp_path)]


def test_a_per_id_reaffirm_loop_is_stopped_after_the_burst(tmp_path: Path):
    """Five ids in a `for` loop took a drift count from 5 to 0 with five success lines and no refusal."""
    root, ids = _drifted_memories(tmp_path, 5)
    outcomes = [runner.invoke(app, ["reaffirm", i, "--repo", str(root)]).output for i in ids]
    assert sum("Reaffirmed" in o for o in outcomes[:3]) == 3       # the first few are free
    assert all("--verified" in o for o in outcomes[3:])            # the rest must say what was checked
    assert all("Reaffirmed" not in o for o in outcomes[3:])


def test_the_guard_exits_zero_and_teaches_the_retry(tmp_path: Path):
    """Design law #1: a recoverable refusal exits 0 and prints the command that works."""
    root, ids = _drifted_memories(tmp_path, 4)
    for i in ids[:3]:
        runner.invoke(app, ["reaffirm", i, "--repo", str(root)])
    result = runner.invoke(app, ["reaffirm", ids[3], "--repo", str(root)])
    assert result.exit_code == 0
    assert f"yigraf show {ids[3]}" in result.output and "yigraf supersede" in result.output


def test_verified_lets_an_honest_caller_through_and_is_recorded(tmp_path: Path):
    root, ids = _drifted_memories(tmp_path, 4)
    for i in ids[:3]:
        runner.invoke(app, ["reaffirm", i, "--repo", str(root)])
    claim = "re-read the retry policy; the 3-attempt cap is still what the code does"
    result = runner.invoke(app, ["reaffirm", ids[3], "--verified", claim, "--repo", str(root)])
    assert result.exit_code == 0 and "Reaffirmed" in result.output and claim in result.output
    import json
    ledger = json.loads((root / "yigraf" / ".local" / "reaffirms.json").read_text())
    assert ledger[-1]["verified"] == claim


def test_the_locus_form_is_not_rate_limited(tmp_path: Path):
    """It is already bounded by an act — you re-verified one locus — so rate-limiting it would punish
    the honest batch to catch the dishonest loop."""
    root, ids = _drifted_memories(tmp_path, 4)
    for i in ids[:3]:
        runner.invoke(app, ["reaffirm", i, "--repo", str(root)])
    result = runner.invoke(app, ["reaffirm", "sym:src/m.py#d", "--repo", str(root)])
    assert result.exit_code == 0 and "Reaffirmed" in result.output


def test_the_guard_can_be_switched_off(tmp_path: Path):
    root, ids = _drifted_memories(tmp_path, 5)
    cfg = root / "yigraf" / "config.yaml"
    cfg.write_text(cfg.read_text() + "\nreaffirm_burst: 0\n")
    outcomes = [runner.invoke(app, ["reaffirm", i, "--repo", str(root)]).output for i in ids]
    assert all("Reaffirmed" in o for o in outcomes)

"""Drift detection + rename auto-re-anchor — the M3 done-test (docs/m3-notes.md)."""
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import default_config
from yigraf import retrieval
from yigraf.drift import compute_drift, is_surfaced
from yigraf.extract import build_graph
from yigraf.status import compute_status

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "auth/session.py"


def _linked_repo(tmp_path: Path) -> Path:
    """An initialized repo with one task linked (implements) to ``refresh``, anchored."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth",
                               "--task", "do it"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)]).exit_code == 0
    return tmp_path


def _drift(root: Path):
    graph, _ = build_graph(root, default_config())  # build re-anchors renames in-memory first
    return compute_drift(graph)


def test_freshly_linked_repo_has_no_drift(tmp_path: Path):
    assert _drift(_linked_repo(tmp_path)) == []


def test_editing_the_body_surfaces_soft_drift(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")
    items = _drift(root)
    assert [i.kind for i in items] == ["soft"]
    assert items[0].task_id == "task:auth/1" and items[0].locator == SYM


def test_renaming_auto_reanchors_with_no_drift(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token\n")  # pure rename, body identical
    items = _drift(root)
    assert [i.kind for i in items] == ["renamed"]
    assert items[0].locator == SYM
    assert items[0].new_locator == "sym:auth/session.py#renew"


def test_renamed_edge_carries_into_the_graph(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token\n")
    graph, _ = build_graph(root, default_config())
    new = "sym:auth/session.py#renew"
    assert graph.has_edge("task:auth/1", new)
    assert graph["task:auth/1"][new]["renamed_from"] == SYM
    assert graph["task:auth/1"][new]["anchor"] == graph.nodes[new]["content_hash"]  # no drift


def test_deleting_the_symbol_surfaces_hard_drift(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def unrelated():\n    return 0\n")
    items = _drift(root)
    assert [i.kind for i in items] == ["hard"]
    assert items[0].locator == SYM


def test_rename_plus_body_edit_is_honest_hard_drift(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token + 1\n")  # renamed AND edited
    assert [i.kind for i in _drift(root)] == ["hard"]  # body-hash no longer matches → can't re-anchor


def test_drift_cli_clean_exits_zero(tmp_path: Path):
    result = runner.invoke(app, ["drift", str(_linked_repo(tmp_path))])
    assert result.exit_code == 0 and "No drift" in result.output


def test_drift_cli_soft_exits_nonzero(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def refresh(token):\n    return token + 9\n")
    result = runner.invoke(app, ["drift", str(root)])
    assert result.exit_code == 1 and "soft drift" in result.output


def test_drift_cli_carries_the_verb_fork_only_for_a_drifted_decision(tmp_path: Path):
    """`yigraf drift` is a drift moment too, and named no verb at all before this. Same wording as the
    edit hook (one `retrieval.VERB_FORK`), and silent when only an implements edge drifted — that one
    wants re-`link`, so the reaffirm/supersede fork would be misdirection."""
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def refresh(token):\n    return token + 9\n")
    implements_only = runner.invoke(app, ["drift", str(root)])
    assert "soft drift" in implements_only.output and "Which verb" not in implements_only.output

    assert runner.invoke(app, ["remember", "refresh must stay pure", "--repo", str(root),
                               "--new", "--concerns", SYM]).exit_code == 0
    (root / SRC).write_text("def refresh(token):\n    return token + 10\n")
    result = runner.invoke(app, ["drift", str(root)])
    assert result.exit_code == 1 and retrieval.VERB_FORK in result.output


def test_drift_cli_rename_is_surfaced_but_not_a_failure(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token\n")
    result = runner.invoke(app, ["drift", str(root)])
    assert result.exit_code == 0 and "renamed" in result.output


# --- int:drift-done-suppression: a done task's implements drift is provenance, not a re-verify nag --

def _mark_task_done(root: Path) -> None:
    plan = root / "yigraf" / "plans" / "active" / "auth.md"
    plan.write_text(plan.read_text().replace("- [ ] {#1}", "- [x] {#1}"))


def _drift_the_body(root: Path) -> None:
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")


def test_done_task_drift_is_computed_but_not_surfaced(tmp_path: Path):
    """compute_drift still emits it (the internal set _verified_reconcile relies on), but is_surfaced
    withholds it from what the agent sees."""
    root = _linked_repo(tmp_path)
    _mark_task_done(root)
    _drift_the_body(root)
    graph, _ = build_graph(root, default_config())
    items = compute_drift(graph)
    assert [i.kind for i in items] == ["soft"]           # still in the full set
    assert items[0].task_id == "task:auth/1"
    assert is_surfaced(graph, items[0]) is False          # but not surfaced


def test_open_task_drift_stays_surfaced(tmp_path: Path):
    """The other side: an OPEN task's implements drift is mid-change work — still worth seeing."""
    root = _linked_repo(tmp_path)  # task left todo
    _drift_the_body(root)
    graph, _ = build_graph(root, default_config())
    assert is_surfaced(graph, compute_drift(graph)[0]) is True


def test_drift_cli_hides_done_task_drift(tmp_path: Path):
    """A done task's soft drift must not print, and must not trip the exit-1 nag gate."""
    root = _linked_repo(tmp_path)
    _mark_task_done(root)
    _drift_the_body(root)
    result = runner.invoke(app, ["drift", str(root)])
    assert result.exit_code == 0 and "No drift" in result.output


# --- The two drift surfaces now agree, and the count has something that can print it ----------------


def test_no_drift_says_so_but_owns_up_to_the_stale_it_is_withholding(tmp_path: Path):
    """`drift` printing "No drift." while `status` says `⚠ 2 stale` reads as a contradiction.

    It is not one — stale is deliberately withheld from the agent-facing drift signal, because a closed
    task must not nag mid-edit. But a count that no command can print is a dead end: the field had to
    call `drift.compute_drift` from Python to find out what the number counted.
    """
    root = _linked_repo(tmp_path)
    _mark_task_done(root)
    _drift_the_body(root)
    result = runner.invoke(app, ["drift", str(root)])
    assert "No drift." in result.output
    assert "1 stale completion(s) not shown" in result.output and "`yigraf drift --stale`" in result.output


def test_drift_stale_lists_what_the_count_counts(tmp_path: Path):
    root = _linked_repo(tmp_path)
    _mark_task_done(root)
    _drift_the_body(root)
    result = runner.invoke(app, ["drift", "--stale", str(root)])
    assert result.exit_code == 0  # a stale completion is not the CI gate; only live drift is
    assert "STALE completions" in result.output and "task:auth/1" in result.output
    assert "`close task:auth/1 --reopen` if the change undid it" in result.output


def test_the_drift_report_names_the_relation_the_claim_and_the_verb(tmp_path: Path):
    """One wording across both surfaces (`retrieval.drift_tail`), plus what the CLI can afford.

    The hook line was kind- and relation-aware while `yigraf drift` printed a bare
    `soft drift: mem:X → sym:Y (body changed since anchored)` — so the surface an agent reaches for
    once it knows the verbs was the one with no advice on it. And "something moved" never answers
    whether the belief still holds, which is what picking between `reaffirm` and `supersede` requires:
    the report is unbudgeted, so it can simply print the claim.
    """
    root = _linked_repo(tmp_path)
    assert runner.invoke(app, ["remember", "refresh must stay free of I/O", "--repo", str(root),
                               "--new", "--why", "it runs inside the request path",
                               "--concerns", SYM]).exit_code == 0
    _drift_the_body(root)
    out = runner.invoke(app, ["drift", str(root)]).output
    assert "soft drift · concerns:" in out              # WHICH anchor list drifted
    assert '"refresh must stay free of I/O"' in out     # the claim, so the fork can be decided here
    assert "`reaffirm mem:" in out and "`supersede mem:" in out  # ids pre-filled, same as the hook


def test_both_drift_surfaces_share_one_wording(tmp_path: Path):
    """The regression guard: the hook's line and the CLI's advice come from the same function."""
    root = _linked_repo(tmp_path)
    assert runner.invoke(app, ["remember", "a governed decision", "--repo", str(root), "--new",
                               "--concerns", SYM]).exit_code == 0
    _drift_the_body(root)
    graph, _ = build_graph(root, default_config())
    item = next(i for i in compute_drift(graph) if i.relation == "concerns")
    assert retrieval.drift_tail(item) in runner.invoke(app, ["drift", str(root)]).output
    assert retrieval.drift_tail(item) in retrieval._drift_line(item)


def test_status_count_excludes_done_task_drift(tmp_path: Path):
    root = _linked_repo(tmp_path)
    _mark_task_done(root)
    _drift_the_body(root)
    graph, _ = build_graph(root, default_config())
    assert compute_status(graph, root, default_config()).drifting == 0


def test_satisfied_intent_still_flagged_when_only_done_link_drifts(tmp_path: Path):
    """The load-bearing split: the done-task drift LINE is suppressed, yet the satisfied intent it
    backs is still reported unverified — because compute_drift kept the edge in the internal set."""
    root = _linked_repo(tmp_path)
    assert runner.invoke(app, ["intent", "refresh-works", "--repo", str(root),
                               "-s", "yigraf SHALL refresh tokens."]).exit_code == 0
    assert runner.invoke(app, ["intent", "refresh-works", "--repo", str(root),
                               "--status", "satisfied"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", "int:refresh-works",
                               "--repo", str(root)]).exit_code == 0
    _mark_task_done(root)
    _drift_the_body(root)
    graph, _ = build_graph(root, default_config())
    text = retrieval.context(graph, "refresh", default_config(), root=root).text
    assert "task:auth/1 → " not in text                                  # drift line suppressed
    assert "int:refresh-works is satisfied but not verified" in text     # yet the intent is flagged


# --- the "also affected" ripple must not re-surface what the direct path suppressed ---------------
#
# `_blast_reconcile_lines` walks reverse reachability from a drifted symbol to find governed nodes the
# direct drift lines did NOT name — a node correctly anchored to the same symbol, or reached over a
# derived relation. Every line it prints ends in "re-verify it still holds", so a node with no honest
# re-verification must never appear there (drift.is_reverifiable).

def _second_task_anchored_after_the_edit(root: Path) -> None:
    """A task correctly anchored to the CURRENT body — so it never drifts, but the symbol it governs
    did, which is exactly what puts it in the ripple rather than in a direct drift line."""
    plan = root / "yigraf" / "plans" / "active" / "auth.md"
    plan.write_text(plan.read_text().rstrip("\n") + "\n- [ ] {#2} verify it\n")
    assert runner.invoke(app, ["link", "task:auth/2", SYM, "--repo", str(root)]).exit_code == 0


def test_ripple_surfaces_a_live_node_governing_the_drifted_symbol(tmp_path: Path):
    """The section's reason to exist: a correctly-anchored, still-open task governing code that
    drifted for someone else is a real prompt, and must keep showing up."""
    root = _linked_repo(tmp_path)
    _drift_the_body(root)
    _second_task_anchored_after_the_edit(root)
    result = runner.invoke(app, ["drift", str(root)])
    assert "also affected" in result.output
    assert "task:auth/2" in result.output


def test_ripple_withholds_a_done_task(tmp_path: Path):
    """int:drift-done-suppression, restated for reverse reachability: is_surfaced keeps a done task's
    drift out of the report, and the ripple must not hand it straight back as a reconcile prompt."""
    root = _linked_repo(tmp_path)
    _drift_the_body(root)
    _second_task_anchored_after_the_edit(root)
    plan = root / "yigraf" / "plans" / "active" / "auth.md"
    plan.write_text(plan.read_text().replace("- [ ] {#2}", "- [x] {#2}"))
    result = runner.invoke(app, ["drift", str(root)])
    assert "soft drift" in result.output, "the direct line is unaffected"
    assert "task:auth/2" not in result.output


def test_ripple_withholds_a_superseded_memory(tmp_path: Path):
    """A retracted belief has nothing to reaffirm — its successor already withdrew the claim."""
    root = _linked_repo(tmp_path)
    _drift_the_body(root)
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    old = runner.invoke(app, ["remember", "refresh must be pure", "--concerns", SYM,
                              "--repo", str(root)])
    assert old.exit_code == 0
    mem_id = old.output.split("Captured ")[1].split(" ")[0].strip()

    assert "also affected" in runner.invoke(app, ["drift", str(root)]).output
    assert mem_id in runner.invoke(app, ["drift", str(root)]).output, "live: it belongs in the ripple"

    assert runner.invoke(app, ["supersede", mem_id, "refresh may cache", "--repo",
                               str(root)]).exit_code == 0
    assert mem_id not in runner.invoke(app, ["drift", str(root)]).output


# --- Rename PERSISTENCE: the graph re-anchors, the artifact must be told ---------------------------
# resolve_renames rescues a moved subject in the graph, which is a derived, recomputable projection —
# so the rescue is re-derived from the body hash on every build and lasts exactly as long as that body.
# test_rename_plus_body_edit_is_honest_hard_drift (above) pins the cliff; these pin the way off it.


def _plan_impls(root: Path) -> list[dict]:
    import yaml
    meta = yaml.safe_load((root / "yigraf" / "plans" / "active" / "auth.md")
                          .read_text().split("---")[1])
    return meta["edges"]["task:auth/1"]["implements"]


def test_an_unsettled_rename_reaches_the_agent_at_the_edit_hook(tmp_path: Path):
    """The limit was invisible, not honest: every agent-facing reader dropped `renamed` items, so the
    only surface that ever mentioned one was `yigraf drift`, which the working loop never runs."""
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token\n")
    graph, _ = build_graph(root, default_config())
    result = retrieval.context_for_locus(graph, SRC, default_config(), root=root)
    assert result is not None
    assert "Unsettled rename" in result.text
    assert SYM in result.text and "sym:auth/session.py#renew" in result.text
    assert "yigraf link task:auth/1 sym:auth/session.py#renew" in result.text
    assert retrieval.RENAME_CLIFF in result.text


def test_gc_reports_a_rename_dry_and_settles_it_on_apply(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token\n")

    dry = runner.invoke(app, ["gc", str(root)])
    assert dry.exit_code == 0 and "RENAMED" in dry.output and "Dry run" in dry.output
    assert [i["sym"] for i in _plan_impls(root)] == [SYM]  # dry-run wrote nothing

    applied = runner.invoke(app, ["gc", str(root), "--apply"])
    assert applied.exit_code == 0 and "Settled 1 anchor" in applied.output
    assert [i["sym"] for i in _plan_impls(root)] == ["sym:auth/session.py#renew"]
    assert _drift(root) == []  # nothing left to re-derive — the file says what the graph knew


def test_settling_preserves_the_anchor_and_the_commit_it_was_stamped_at(tmp_path: Path):
    """A rename is a content-hash MATCH, so re-hashing computes the same value and re-stamping would
    date the anchor to this commit when it was taken at an older one (feedback-v4 #14)."""
    root = _linked_repo(tmp_path)
    before = _plan_impls(root)[0]
    (root / SRC).write_text("def renew(token):\n    return token\n")
    assert runner.invoke(app, ["gc", str(root), "--apply"]).exit_code == 0
    after = _plan_impls(root)[0]
    assert after["sym"] == "sym:auth/session.py#renew"
    assert after["anchor"] == before["anchor"] and after["anchor_algo"] == before["anchor_algo"]
    assert after.get("stamped_at") == before.get("stamped_at")


def test_a_settled_rename_survives_the_body_edit_that_used_to_destroy_the_trail(tmp_path: Path):
    """The payoff. Unsettled, rename-then-edit is hard drift on a locator that will never resolve and
    no record of where the subject went; settled, the same edit is ordinary re-verifiable soft drift."""
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token\n")
    assert runner.invoke(app, ["gc", str(root), "--apply"]).exit_code == 0
    (root / SRC).write_text("def renew(token):\n    return token + 1\n")
    items = _drift(root)
    assert [i.kind for i in items] == ["soft"]
    assert items[0].locator == "sym:auth/session.py#renew"


def test_link_settles_a_proved_rename_instead_of_appending_a_second_entry(tmp_path: Path):
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def renew(token):\n    return token\n")
    result = runner.invoke(app, ["link", "task:auth/1", "sym:auth/session.py#renew",
                                 "--repo", str(root)])
    assert result.exit_code == 0 and "settled the rename from" in result.output
    assert [i["sym"] for i in _plan_impls(root)] == ["sym:auth/session.py#renew"]
    assert _drift(root) == []


def test_link_still_appends_a_genuine_second_implementer(tmp_path: Path):
    """The guard remove_edge_from_plan's docstring argues for: replacing on a GUESS would silently
    delete a real edge. Only a rename the engine proved replaces; every other link appends."""
    root = _linked_repo(tmp_path)
    (root / SRC).write_text("def refresh(token):\n    return token\n\n\ndef revoke(token):\n    return 0\n")
    assert runner.invoke(app, ["link", "task:auth/1", "sym:auth/session.py#revoke",
                               "--repo", str(root)]).exit_code == 0
    assert [i["sym"] for i in _plan_impls(root)] == [SYM, "sym:auth/session.py#revoke"]


def test_gc_settles_a_renamed_concerns_anchor_on_a_memory(tmp_path: Path):
    """Same treatment for the memory families — concerns and grounded_by reach resolve_renames through
    the identical machinery, so the settle path must not stop at plan artifacts."""
    root = _linked_repo(tmp_path)
    assert runner.invoke(app, ["remember", "refresh must stay pure", "--repo", str(root),
                               "--new", "--concerns", SYM]).exit_code == 0
    (root / SRC).write_text("def renew(token):\n    return token\n")
    assert runner.invoke(app, ["gc", str(root), "--apply"]).exit_code == 0
    bodies = "\n".join(p.read_text() for p in (root / "yigraf" / "memory").glob("*.md"))
    assert "sym:auth/session.py#renew" in bodies and SYM not in bodies
    assert _drift(root) == []

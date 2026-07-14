"""Query-driven retrieval (`yigraf context`) — the M4 done-test (docs/retrieval-design.md)."""
from pathlib import Path

from typer.testing import CliRunner

from yigraf import retrieval
from yigraf.cli import app
from yigraf.config import default_config
from yigraf.extract import build_graph

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
SRC = "auth/session.py"


def _repo(tmp_path: Path, status: str = "active") -> Path:
    """Repo with an intent (status configurable), a task tracking it, linked to a symbol."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "session-expiry", "--repo", str(tmp_path),
                               "-s", "The system SHALL expire a session after 30m idle.",
                               "--scenario", "Given idle 30m, When a request arrives, Then 401.",
                               "--status", status]).exit_code == 0
    assert runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth",
                               "--task", "implement idle expiry"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", "int:session-expiry", "--repo", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)]).exit_code == 0
    return tmp_path


def _ctx(root: Path, query: str, **kw):
    graph, _ = build_graph(root, default_config())
    return retrieval.context(graph, query, default_config(), **kw)


def test_signature_only_is_the_default_render(tmp_path: Path):
    """Default render is locator+signature — the body is NOT inlined even with a root (token-thrift)."""
    root = _repo(tmp_path)
    graph, _ = build_graph(root, default_config())
    result = retrieval.context(graph, "refresh", default_config(), root=root)
    assert "return token" not in result.text  # the body stays in the file


def test_source_for_seeds_renders_verbatim_line_numbered_source(tmp_path: Path):
    """A3: with the knob on, the top-ranked symbol's body is inlined, line-numbered (sufficiency)."""
    root = _repo(tmp_path)
    cfg = default_config()
    cfg["retrieval"]["render"] = "source_for_seeds"
    graph, _ = build_graph(root, cfg)
    result = retrieval.context(graph, "refresh", cfg, root=root)
    assert "\tdef refresh(token):" in result.text  # line-numbered source line (a tab a signature lacks)
    assert "return token" in result.text           # the body the signature render omits


def test_source_for_seeds_falls_back_to_signature_without_a_root(tmp_path: Path):
    """No root ⇒ can't read files ⇒ graceful fall back to the signature render (never a hard failure)."""
    root = _repo(tmp_path)
    cfg = default_config()
    cfg["retrieval"]["render"] = "source_for_seeds"
    graph, _ = build_graph(root, cfg)
    result = retrieval.context(graph, "refresh", cfg)  # root omitted
    assert "return token" not in result.text


def test_terms_splits_identifiers_and_paths():
    assert retrieval.terms("auth/session.py#validateToken") == [
        "auth", "session", "py", "validate", "token"]


def test_context_returns_the_requirement_and_the_symbol_signature(tmp_path: Path):
    result = _ctx(_repo(tmp_path), "session expiry")
    assert "The system SHALL expire a session" in result.text  # the requirement
    assert "def refresh(token):" in result.text                # the implementer, as a signature
    assert "return token" not in result.text                   # signature, NOT the body/source


def test_context_token_estimate_is_small(tmp_path: Path):
    result = _ctx(_repo(tmp_path), "session expiry")
    assert result.nodes_rendered > 0
    assert 0 < result.token_estimate < 500  # a tiny map, not file dumps


def test_query_matches_a_code_identifier(tmp_path: Path):
    assert SYM in _ctx(_repo(tmp_path), "refresh").text


def test_editing_a_linked_symbol_surfaces_drift_in_context(tmp_path: Path):
    root = _repo(tmp_path)
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")
    text = _ctx(root, "session expiry").text
    assert "Drift" in text and SYM in text and "re-verify or relink" in text


def test_satisfied_but_drifted_intent_emits_reconcile(tmp_path: Path):
    root = _repo(tmp_path, status="satisfied")
    (root / SRC).write_text("def refresh(token):\n    return token + 1\n")
    text = _ctx(root, "session expiry").text
    assert "satisfied but not verified" in text


def test_satisfied_and_clean_intent_does_not_reconcile(tmp_path: Path):
    text = _ctx(_repo(tmp_path, status="satisfied"), "session expiry").text
    assert "not verified" not in text  # live, undrifted link → verified


def test_family_filter_restricts_to_one_family(tmp_path: Path):
    text = _ctx(_repo(tmp_path), "session expiry", family="intent").text
    assert "int:session-expiry" in text
    assert "sym:" not in text and "plan:" not in text


def test_tight_budget_truncates_and_notes_elision(tmp_path: Path):
    result = _ctx(_repo(tmp_path), "session expiry", budget_tokens=20)
    assert result.nodes_rendered < result.nodes_total
    assert "elided" in result.text


def test_file_and_module_containers_are_suppressed_from_render(tmp_path: Path):
    # file:/module: nodes seed + bridge traversal but are render noise (they eat budget and bury intent
    # /drift). The ranking fix suppresses them from output while keeping the real symbol.
    result = _ctx(_repo(tmp_path), "refresh")
    assert "sym:auth/session.py#refresh" in result.text   # the real symbol still shows
    assert "file:auth/session.py" not in result.text      # its file container is gone
    assert "module:auth/session.py" not in result.text    # and its module container


def test_context_cli_runs_and_reports_token_count(tmp_path: Path):
    result = runner.invoke(app, ["context", "session expiry", "--repo", str(_repo(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "tokens" in result.output and "def refresh(token):" in result.output


# --- Capture-gap legibility (the push/pull asymmetry made visible) --------------------------------

def _done_unlinked_task(root: Path) -> None:
    """Add a plan whose single task is marked done but linked to no implementing symbol."""
    assert runner.invoke(app, ["plan", "cleanup", "--repo", str(root), "-t", "Cleanup",
                               "--task", "remove dead code"]).exit_code == 0
    plan_file = root / "yigraf" / "plans" / "active" / "cleanup.md"
    plan_file.write_text(plan_file.read_text().replace("- [ ] {#1}", "- [x] {#1}"))


def _session(root: Path):
    graph, _ = build_graph(root, default_config())
    return retrieval.session_context(graph, default_config(), root=root)


def test_done_task_without_link_surfaces_capture_gap_at_session_start(tmp_path: Path):
    """A completed task with no implements edge is the 'work done, graph not told' decay signal."""
    root = _repo(tmp_path)
    _done_unlinked_task(root)
    text = _session(root).text
    assert "Capture gaps" in text
    assert "task:cleanup/1 is done but names no implementing symbol" in text


def test_linking_the_done_task_closes_the_capture_gap(tmp_path: Path):
    root = _repo(tmp_path)
    _done_unlinked_task(root)
    assert runner.invoke(app, ["link", "task:cleanup/1", SYM, "--repo", str(root)]).exit_code == 0
    assert "task:cleanup/1 is done" not in _session(root).text


def test_done_task_that_is_linked_is_not_a_gap(tmp_path: Path):
    """The auth task in the base repo is linked, so even when done it must not surface as a gap."""
    root = _repo(tmp_path)
    plan_file = root / "yigraf" / "plans" / "active" / "auth.md"
    plan_file.write_text(plan_file.read_text().replace("- [ ] {#1}", "- [x] {#1}"))  # done AND linked
    assert "is done but names no implementing symbol" not in _session(root).text


def test_fully_done_plan_is_not_reinjected_as_active_at_session_start(tmp_path: Path):
    """A plan with all boxes checked is finished work — it must drop out of the SessionStart seed set
    (design law #4) rather than re-cost the agent context on every /clear."""
    root = _repo(tmp_path)
    plan = root / "yigraf" / "plans" / "active" / "auth.md"
    plan.write_text(plan.read_text().replace("- [ ] {#1}", "- [x] {#1}"))  # last (only) box checked
    text = _session(root).text
    assert "task:auth/1" not in text  # the done task no longer surfaces as active work
    # the governing intent is still seeded, so the session slice is not empty
    assert "int:session-expiry" in text


def test_plan_with_open_work_is_still_reinjected(tmp_path: Path):
    """Guard the other side: a plan still holding an open task remains an active seed."""
    root = _repo(tmp_path)  # auth/1 is left todo by _repo
    assert "task:auth/1" in _session(root).text


def test_capture_gap_is_scoped_to_the_query_in_context(tmp_path: Path):
    """`context` reports a gap only inside the query's neighborhood (like drift), not globally."""
    root = _repo(tmp_path)
    _done_unlinked_task(root)
    assert "task:cleanup/1 is done" in _ctx(root, "cleanup").text          # in scope → surfaced
    assert "task:cleanup/1 is done" not in _ctx(root, "session expiry").text  # unrelated → silent


# --------------------------------------------------------------------------------------------------
# Relevance legibility (C#8): low-confidence banner + opt-in per-node cosine.
# --------------------------------------------------------------------------------------------------


def test_relevance_note_fires_below_floor():
    """A semantic backend ran but nothing cleared the floor → a one-line honesty banner."""
    note = retrieval._relevance_note({"mem:001": 0.21}, "unrelated query", default_config())
    assert note is not None and "low confidence" in note and "unrelated query" in note


def test_relevance_note_silent_above_floor_and_without_backend():
    """Silent (None) when something matched strongly, and when there was no backend at all (design #4)."""
    assert retrieval._relevance_note({"mem:001": 0.72}, "q", default_config()) is None
    assert retrieval._relevance_note({}, "q", default_config()) is None  # no backend ⇒ can't cry wolf


def test_scores_flag_appends_cosine(tmp_path: Path):
    """`show_scores` appends the per-node cosine; off by default (token-thrift)."""
    root = _repo(tmp_path)
    graph, _ = build_graph(root, default_config())
    sem = {"int:session-expiry": 0.71}  # above the relevance floor → no banner muddying the assertion
    with_scores = retrieval.context(graph, "session expiry", default_config(),
                                    semantic_match=sem, show_scores=True)
    assert "[sim 0.71]" in with_scores.text
    without = retrieval.context(graph, "session expiry", default_config(), semantic_match=sem)
    assert "[sim" not in without.text


def _locus(root: Path, relpath: str):
    graph, _ = build_graph(root, default_config())
    return retrieval.context_for_locus(graph, relpath, default_config(), root=root)


def test_editing_a_governed_symbol_surfaces_proof_obligations(tmp_path: Path):
    """int:proof-obligations: the governing intent's acceptance criteria are injected at edit time —
    the concrete Given/When/Then the change must keep true, attributed to the intent."""
    result = _locus(_repo(tmp_path), SRC)
    assert result is not None
    assert "Proof obligations" in result.text
    assert "✔ int:session-expiry: Given idle 30m" in result.text  # the scenario, as an obligation


def test_ungoverned_edit_is_silent(tmp_path: Path):
    """Silence-unless (design law #4): an edit to code no task/intent governs injects nothing."""
    root = _repo(tmp_path)
    (root / "util").mkdir()
    (root / "util" / "misc.py").write_text("def helper():\n    return 1\n")
    assert _locus(root, "util/misc.py") is None


def test_proof_obligation_falls_back_to_statement_without_scenarios(tmp_path: Path):
    """A bare MUST contract (no Given/When/Then) still owes an obligation — its statement stands in."""
    root = _repo(tmp_path)
    assert runner.invoke(app, ["intent", "single-use", "--repo", str(root),
                               "-s", "Refresh tokens MUST be single-use."]).exit_code == 0
    assert runner.invoke(app, ["plan", "tok", "--repo", str(root), "-t", "Tok",
                               "--task", "enforce single-use"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:tok/1", "int:single-use", "--repo", str(root)]).exit_code == 0
    assert runner.invoke(app, ["link", "task:tok/1", SYM, "--repo", str(root)]).exit_code == 0
    assert "✔ int:single-use: Refresh tokens MUST be single-use." in _locus(root, SRC).text


def test_proof_obligations_exclude_the_concerns_serves_path(tmp_path: Path):
    """Anti-flood (measured 22→7 on yigraf's own retrieval.py): a memory that *concerns* the symbol and
    *serves* an intent is NOT an obligation — an obligation is what the code IMPLEMENTS via a task, not
    what a local decision merely relates to. The decision still renders in the Decisions section."""
    root = _repo(tmp_path)
    assert runner.invoke(app, ["intent", "audit-log", "--repo", str(root),
                               "-s", "All refreshes SHALL be audit-logged.",
                               "--scenario", "Given a refresh, When it completes, Then an audit row exists."]).exit_code == 0
    assert runner.invoke(app, ["remember", "refresh writes an audit row", "--repo", str(root), "--new",
                               "--serves", "int:audit-log", "--concerns", SYM]).exit_code == 0
    text = _locus(root, SRC).text
    assert "✔ int:session-expiry:" in text     # implements→tracks path still yields its obligation
    assert "audit row exists" not in text       # concerns→serves scenario must NOT leak as an obligation

"""The M2 authoring verbs end-to-end: intent/plan/link → projected graph (the M2 done-test)."""
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import default_config
from yigraf.extract import build_graph
from yigraf import graphdb, memory

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"


def _repo(tmp_path: Path) -> Path:
    """An initialized repo with one linkable symbol, already built."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _run(args: list[str]):
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def _graph(root: Path):
    return graphdb.load_workspace(root)


def test_intent_verb_projects_an_enriched_node(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["intent", "session-expiry", "--repo", str(root),
          "-s", "The system SHALL expire a session after 30m idle.",
          "--scenario", "Given idle 30m, When a request arrives, Then respond 401.",
          "--design", "Optimistic-locked refresh.", "--status", "active"])
    node = _graph(root).nodes["int:session-expiry"]
    assert node["family"] == "intent" and node["status"] == "active"
    assert node["statement"].startswith("The system SHALL expire")
    assert node["scenarios"] == ["Given idle 30m, When a request arrives, Then respond 401."]
    assert node["design"] == "Optimistic-locked refresh."


def test_plan_verb_projects_plan_and_task_nodes(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth-hardening", "--repo", str(root), "-t", "Auth hardening",
          "--task", "implement idle expiry"])
    g = _graph(root)
    assert g.nodes["plan:auth-hardening"]["kind"] == "plan"
    assert g.nodes["task:auth-hardening/1"]["state"] == "todo"
    assert g.has_edge("plan:auth-hardening", "task:auth-hardening/1")


def test_link_implements_anchors_with_no_drift(tmp_path: Path):
    """The M2 done-test: link a task to a symbol → edge carries an anchor == the symbol's hash."""
    root = _repo(tmp_path)
    _run(["plan", "auth-hardening", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth-hardening/1", SYM, "--repo", str(root)])

    g = _graph(root)
    edge = g.edges["task:auth-hardening/1", SYM]
    assert edge["relation"] == "implements" and edge["anchor_algo"] == "astnorm-v1"
    assert edge["anchor"] == g.nodes[SYM]["content_hash"]  # no drift


def test_link_tracks_an_intent(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["intent", "session-expiry", "--repo", str(root), "-s", "SHALL expire.",
          "--scenario", "Given a, When b, Then c."])
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", "int:session-expiry", "--repo", str(root)])
    assert _graph(root).edges["task:auth/1", "int:session-expiry"]["relation"] == "tracks"


def test_unlink_retires_an_implements_edge(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", SYM, "--repo", str(root)])
    assert ("task:auth/1", SYM) in _graph(root).edges

    out = _run(["unlink", "task:auth/1", SYM, "--repo", str(root)])
    assert "Unlinked task:auth/1 —implements→" in out.output
    assert ("task:auth/1", SYM) not in _graph(root).edges


def test_unlink_retires_a_tracks_edge(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["intent", "session-expiry", "--repo", str(root), "-s", "SHALL expire.",
          "--scenario", "Given a, When b, Then c."])
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", "int:session-expiry", "--repo", str(root)])
    _run(["unlink", "task:auth/1", "int:session-expiry", "--repo", str(root)])
    assert ("task:auth/1", "int:session-expiry") not in _graph(root).edges


def test_unlink_clears_hard_drift_a_file_move_left_behind(tmp_path: Path):
    """The reported trap (feedback #2): `link` keys `implements` by the exact locator, so re-linking
    after a move APPENDS and the old entry becomes drift no verb could clear — `reaffirm` re-anchors a
    *memory*, and `supersede` restates a *belief*, and a stale declaration is neither."""
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", SYM, "--repo", str(root)])

    # Move the symbol AND change its body — a pure move would auto-re-anchor by content hash.
    (root / "auth" / "session.py").unlink()
    moved = root / "auth" / "tokens.py"
    moved.write_text("def refresh(token):\n    return token + 1\n")
    new_sym = "sym:auth/tokens.py#refresh"
    _run(["build", str(root)])
    _run(["link", "task:auth/1", new_sym, "--repo", str(root)])

    both = runner.invoke(app, ["drift", str(root)])
    assert both.exit_code == 1 and SYM in both.output  # the stale edge outlives the re-link

    _run(["unlink", "task:auth/1", SYM, "--repo", str(root)])
    after = runner.invoke(app, ["drift", str(root)])
    assert after.exit_code == 0 and "No drift" in after.output
    assert ("task:auth/1", new_sym) in _graph(root).edges  # the live link is untouched


def test_unlink_names_what_the_task_actually_declares(tmp_path: Path):
    """Guidance, not a stack trace (design law #1): the usual cause is a locator that reads right but
    isn't the string on disk, so the fix is to copy one of the ones it prints."""
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", SYM, "--repo", str(root)])
    out = _run(["unlink", "task:auth/1", "sym:auth/session.py#nope", "--repo", str(root)])
    assert "doesn't declare" in out.output and SYM in out.output  # exit 0, names the real edge


def test_unlink_rejects_an_unknown_task(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    out = _run(["unlink", "task:auth/9", SYM, "--repo", str(root)])
    assert "not a task" in out.output


# --- unlink mem:<id> <ref>: retiring a dead grounded_by ref -----------------------------------------

TEST_SYM = "sym:tests/test_auth.py#test_refresh_is_single_use"


def _evidence_refs(root: Path, mem_id: str) -> list[str]:
    """The refs actually on the artifact. Read from the FILE, not a node attr: evidence projects as
    `grounded_by` EDGES, so `nodes[mem_id]["evidence"]` is always None and asserting on it is vacuous."""
    return [e.ref for e in memory.read_memory(memory.find_memory(root, mem_id)).evidence]


def _grounded(tmp_path: Path, extra_evidence: bool = False) -> tuple[Path, str]:
    """A repo with an ·empirical decision grounded by a real test symbol; returns (root, mem id)."""
    root = _repo(tmp_path)
    (root / "tests").mkdir()
    (root / "tests" / "test_auth.py").write_text(
        "def test_refresh_is_single_use():\n    assert True\n\ndef test_other():\n    assert True\n")
    _run(["build", str(root)])
    args = ["remember", "refresh tokens stay single-use", "--repo", str(root), "--new",
            "--concerns", SYM, "--grounding", "empirical", "--evidence", TEST_SYM]
    if extra_evidence:
        args += ["--evidence", "sym:tests/test_auth.py#test_other"]
    out = _run(args)
    return root, out.output.split()[1]


def test_unlink_retires_a_dead_evidence_ref_from_a_memory(tmp_path: Path):
    """The gap `reaffirm --evidence` leaves: it upserts, so a ref whose test was DELETED can neither be
    re-anchored nor replaced — naming fresh evidence adds beside the corpse and downgrading the tier
    doesn't touch it. Retiring the ref is a graph edit, not a mind-change, so it is `unlink`'s shape."""
    root, mem_id = _grounded(tmp_path, extra_evidence=True)
    out = _run(["unlink", mem_id, TEST_SYM, "--repo", str(root)])
    assert "grounded_by" in out.output and TEST_SYM in out.output
    assert TEST_SYM not in _evidence_refs(root, mem_id)


def test_unlink_refuses_to_strand_an_empirical_claim_with_no_grounding(tmp_path: Path):
    """Retiring the LAST evidence ref would leave an ·empirical belief with nothing behind it — the
    loophole the capture/reaffirm gate closes. `unlink` must not become the quiet way to keep a tier you
    can no longer justify, so it teaches both honest exits instead (design law #1: exit 0 with guidance)."""
    root, mem_id = _grounded(tmp_path)
    out = _run(["unlink", mem_id, TEST_SYM, "--repo", str(root)])
    assert "nothing grounding it" in out.output
    assert "--grounding inferred" in out.output          # the honest downgrade
    assert "--grounding empirical --evidence" in out.output  # or name the replacement
    assert TEST_SYM in _evidence_refs(root, mem_id)  # untouched


def test_downgrading_first_then_retiring_the_dead_ref_is_the_honest_path(tmp_path: Path):
    """The two-step the guidance names actually works end to end."""
    root, mem_id = _grounded(tmp_path)
    _run(["reaffirm", mem_id, "--grounding", "inferred", "--repo", str(root)])
    out = _run(["unlink", mem_id, TEST_SYM, "--repo", str(root)])
    assert "grounded_by" in out.output
    assert TEST_SYM not in _evidence_refs(root, mem_id)


def test_unlink_names_what_actually_grounds_the_memory(tmp_path: Path):
    """Same guidance shape as the task path: a ref that reads right but isn't the string on disk."""
    root, mem_id = _grounded(tmp_path, extra_evidence=True)
    out = _run(["unlink", mem_id, "sym:tests/test_auth.py#test_nope", "--repo", str(root)])
    assert "isn't grounded by" in out.output and TEST_SYM in out.output


def test_editing_a_linked_symbol_makes_the_anchor_drift(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", SYM, "--repo", str(root)])

    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token + 1\n")
    graph, _ = build_graph(root, default_config())
    edge = graph.edges["task:auth/1", SYM]
    assert edge["anchor"] != graph.nodes[SYM]["content_hash"]  # body changed → drift


def test_deleting_a_linked_symbol_dangles_without_a_phantom_node(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", SYM, "--repo", str(root)])

    (root / "auth" / "session.py").write_text("def other():\n    return 0\n")
    graph, _ = build_graph(root, default_config())
    assert SYM not in graph  # no phantom node conjured for the vanished symbol
    assert not graph.has_edge("task:auth/1", SYM)
    assert [e["sym"] for e in graph.nodes["task:auth/1"]["dangling_implements"]] == [SYM]


def test_intent_verb_refuses_to_clobber(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["intent", "x", "--repo", str(root), "-s", "SHALL x.", "--scenario", "Given a, When b, Then c."])
    result = runner.invoke(app, ["intent", "x", "--repo", str(root), "-s", "again", "--scenario", "g"])
    # Recoverable conditions return exit 0 + guidance, never a hard error (errors teach abandonment).
    assert result.exit_code == 0 and "already exists" in result.output


def test_link_rejects_an_unknown_symbol(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    result = runner.invoke(app, ["link", "task:auth/1", "sym:auth/session.py#ghost", "--repo", str(root)])
    assert result.exit_code == 0 and "Couldn't find" in result.output


def test_link_suggests_the_closest_symbol_on_a_typo(tmp_path: Path):
    """An unresolved locator that's a near-miss of a real one gets a 'did you mean' (closest-symbol)."""
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    result = runner.invoke(app, ["link", "task:auth/1", "sym:auth/session.py#refesh", "--repo", str(root)])
    assert result.exit_code == 0
    assert "Did you mean" in result.output and SYM in result.output


def test_link_rejects_an_unknown_task(tmp_path: Path):
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    result = runner.invoke(app, ["link", "task:auth/9", SYM, "--repo", str(root)])
    assert result.exit_code == 0 and "not a task" in result.output


# --------------------------------------------------------------------------------------------------
# Cluster D+E: cheatsheet, forward-ref soft-warn, note-constraint --rejected, supersede-int guidance,
# plan/task reconcile.
# --------------------------------------------------------------------------------------------------


def test_cheatsheet_lists_verbs_and_flags(tmp_path: Path):
    """D#5: an always-in-sync verb/flag map an orchestrator can paste into a subagent prompt."""
    result = runner.invoke(app, ["cheatsheet"])
    assert result.exit_code == 0
    assert "yigraf remember" in result.output and "--concerns" in result.output
    assert "yigraf context" in result.output and "yigraf reaffirm" in result.output


def test_cheatsheet_json_is_machine_readable(tmp_path: Path):
    import json
    result = runner.invoke(app, ["cheatsheet", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    verbs = {v["verb"] for v in data["verbs"]}
    assert {"remember", "context", "link", "supersede"} <= verbs
    remember = next(v for v in data["verbs"] if v["verb"] == "remember")
    assert any(o["flag"] == "--grounding" for o in remember["options"])  # introspected, not hand-listed


def test_serves_to_missing_node_soft_warns_but_captures(tmp_path: Path):
    """D#3: --serves a not-yet-existing intent is a legitimate forward-ref → warn + dangling edge."""
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "x", "--serves", "int:not-yet", "--repo", str(root)])
    assert result.exit_code == 0
    assert "no such node int:not-yet" in result.output and "dangling serves edge" in result.output
    mem = re.search(r"Captured (mem:[0-9a-f]{16})", result.output).group(1)
    assert _graph(root).nodes[mem]["dangling_serves"] == ["int:not-yet"]


def test_note_constraint_accepts_rejected(tmp_path: Path):
    """D#4: --rejected on note-constraint (parity with remember) lands as the alternative, not in --why."""
    root = _repo(tmp_path)
    out = _run(["note-constraint", "no blocking IO on the refresh path", "--concerns", SYM,
                "--rejected", "a background thread — adds a race we can't test", "--repo", str(root)]).output
    mem = re.search(r"Captured (mem:[0-9a-f]{16})", out).group(1)
    node = _graph(root).nodes[mem]
    assert "background thread" in (node.get("alternatives") or "")


def test_supersede_on_an_intent_id_hands_the_right_recipe(tmp_path: Path):
    """D#5: `supersede int:...` is the wrong verb — guide to supersede-intent, exit 0."""
    root = _repo(tmp_path)
    result = runner.invoke(app, ["supersede", "int:session-expiry", "new claim", "--repo", str(root)])
    assert result.exit_code == 0
    assert "supersede-intent" in result.output and "is an intent, not a memory" in result.output


def test_open_task_with_live_implements_surfaces_reconcile(tmp_path: Path):
    """E#14: an open task whose implementing symbols exist and are current → 'if done, check its box'."""
    from yigraf import retrieval
    root = _repo(tmp_path)
    _run(["plan", "auth", "--repo", str(root), "-t", "Auth", "--task", "do it"])
    _run(["link", "task:auth/1", SYM, "--repo", str(root)])  # linked but left open (todo)
    graph, _ = build_graph(root, default_config())
    text = retrieval.context(graph, "refresh", default_config()).text
    assert "Task reconcile:" in text and "task:auth/1 is open but its implementing symbol" in text

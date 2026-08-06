"""Case A: a teammate's assertion, arriving only over the sync log, participates in local drift.

``build_graph`` folds the synced replica onto the same structure base the authored artifacts land on,
so a belief that exists in no markdown file in this repo still anchors to *this* repo's code — and
starts drifting when you edit it. Structure never crosses the wire; only assertions do.
"""
from pathlib import Path

import pytest
from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import load_config
from yigraf.drift import compute_drift
from yigraf.extract import build_graph, symbol_content_hash
from yigraf.log import Assertion
from yigraf.onlinelog import OnlineLog, SqliteAssertionStore

runner = CliRunner()

PROJECT = "teamproj"
SYM = "sym:app.py#greet"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "app.py").write_text("def greet():\n    return 'hi'\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _config(repo: Path, online: bool = True) -> dict:
    config = load_config(repo / "yigraf" / "config.yaml")
    if online:
        config["online"]["project"] = PROJECT
    return config


def _teammate_belief(repo: Path, config: dict, anchor: str | None) -> None:
    """Append a memory to the replica as if ``yigraf sync`` had pulled it from a teammate."""
    store = SqliteAssertionStore(repo / "yigraf" / "cache" / "replica.db")
    log = OnlineLog(store, PROJECT, signer_key=None, require_signed_provenance=False)
    log.append(Assertion(
        id="mem:teammate1", kind="memory",
        body={"family": "memory",
              "attrs": {"kind": "constraint", "status": "active",
                        "statement": "greet() must stay side-effect free",
                        "source_file": "memory/theirs.md"},
              "edges": [{"relation": "concerns", "target": SYM,
                         "attrs": {"anchor": anchor, "anchor_algo": "astnorm-v1"}}]},
        provenance=[{"actor": "teammate@example.com", "source": "cli"}]))


def test_offline_workspace_is_unchanged(repo):
    """The default: no project configured ⇒ nothing folded, graph is purely local."""
    config = _config(repo, online=False)
    _teammate_belief(repo, config, symbol_content_hash(repo, SYM, config))
    graph, stats = build_graph(repo, config)
    assert stats.synced == 0
    assert "mem:teammate1" not in graph


def test_absent_replica_degrades_to_local(repo):
    config = _config(repo)
    graph, stats = build_graph(repo, config)  # configured, but nothing has ever synced
    assert stats.synced == 0
    assert graph.number_of_nodes() > 0


def test_unreadable_replica_degrades_to_local_rather_than_breaking_the_build(repo):
    """Fail-open (design law #5): a corrupt replica must never take the build down."""
    config = _config(repo)
    replica = repo / "yigraf" / "cache" / "replica.db"
    replica.parent.mkdir(parents=True, exist_ok=True)
    replica.write_bytes(b"this is not a sqlite database")
    graph, stats = build_graph(repo, config)
    assert stats.synced == 0
    assert graph.number_of_nodes() > 0


def test_teammate_belief_enters_my_graph_and_drifts_against_my_edit(repo):
    config = _config(repo)
    _teammate_belief(repo, config, symbol_content_hash(repo, SYM, config))

    graph, stats = build_graph(repo, config)
    assert stats.synced == 1
    assert "mem:teammate1" in graph, "a belief with no local artifact must still fold in"
    assert compute_drift(graph) == [], "unedited code must not drift"

    # Now I edit the code THEIR belief governs.
    (repo / "app.py").write_text("def greet():\n    print('side effect')\n    return 'hi'\n")
    graph2, _ = build_graph(repo, config)
    drift = compute_drift(graph2)
    assert [(d.kind, d.task_id, d.locator, d.relation) for d in drift] == [
        ("soft", "mem:teammate1", SYM, "concerns")]


def test_rename_re_anchors_a_teammate_belief_rather_than_drifting(repo):
    """The rename machinery is family-agnostic, so it covers synced beliefs for free."""
    config = _config(repo)
    _teammate_belief(repo, config, symbol_content_hash(repo, SYM, config))
    build_graph(repo, config)

    (repo / "app.py").write_text("def welcome():\n    return 'hi'\n")
    graph, _ = build_graph(repo, config)
    drift = compute_drift(graph)
    assert [(d.kind, d.locator, d.new_locator) for d in drift] == [
        ("renamed", SYM, "sym:app.py#welcome")]


def test_a_belief_authored_here_and_synced_collapses_to_one_node(repo):
    """Two folds over one base is safe because assertions are content-addressed (mem:060)."""
    config = _config(repo)
    out = runner.invoke(app, ["remember", "greet returns a greeting", "--why", "clarity",
                              "--concerns", SYM, "--repo", str(repo)])
    assert out.exit_code == 0, out.output

    from yigraf import filelog, memory
    mine = memory.iter_memories(repo)[0]
    assertion = filelog._memory_assertion(mine)

    store = SqliteAssertionStore(repo / "yigraf" / "cache" / "replica.db")
    OnlineLog(store, PROJECT, signer_key=None, require_signed_provenance=False).append(assertion)

    graph, stats = build_graph(repo, config)
    assert stats.synced == 1
    assert mine.id in graph
    assert len([n for n in graph.nodes if n == mine.id]) == 1
    # The round trip must not have manufactured a second, competing copy of the same belief.
    memories = [n for n, a in graph.nodes(data=True) if a.get("family") == "memory"]
    assert memories == [mine.id]


# --------------------------------------------------------------------------------------------------
# Revisioned families: an edit must PUSH, and the replica must not revert the local file (law #6)
# --------------------------------------------------------------------------------------------------
#
# Both halves of one defect. Intents and tasks used to carry a FIXED id (a slug, a positional locator)
# over a MUTABLE body, so (a) `sync`'s push set — `[a for a in local if a.id not in known_ids]` — skipped
# every edit after the first push as already-known, and (b) where a revision did reach the replica,
# `_fold_replica` running after the local fold let the teammate's older snapshot overwrite local state.
# Symptom: `yigraf link` re-anchors, `[ ]`→`[x]`, and `--status satisfied` silently never propagated,
# and completions reverted on the next build.


def _plan_repo(repo: Path) -> Path:
    assert runner.invoke(app, ["intent", "greeting-shape", "--statement",
                               "yigraf SHALL greet", "--repo", str(repo)]).exit_code == 0
    assert runner.invoke(app, ["plan", "greeting", "--title", "Greeting", "--task",
                               "make greet() work", "--repo", str(repo)]).exit_code == 0
    return repo


def _push_set(repo: Path, known: set[str]) -> list:
    """Exactly what `yigraf sync` computes as outgoing (cli.py: `a.id not in known_ids`)."""
    from yigraf.filelog import FileLog

    return [a for a in FileLog(repo).iter_assertions_in_causal_order() if a.id not in known]


def _ids(repo: Path) -> set[str]:
    from yigraf.filelog import FileLog

    return {a.id for a in FileLog(repo).iter_assertions_in_causal_order()}


def test_editing_a_task_puts_it_back_in_the_push_set(repo):
    """The stale-completions bug: once pushed, a fixed id made every later edit invisible to sync."""
    _plan_repo(repo)
    known = _ids(repo)  # as if every current assertion had already been pushed
    assert _push_set(repo, known) == [], "a repo with no edits has nothing to push"

    # Re-anchor the task onto a symbol — `yigraf link` rewrites the task's implements edge + anchor.
    assert runner.invoke(app, ["link", "task:greeting/1", SYM, "--repo", str(repo)]).exit_code == 0

    outgoing = _push_set(repo, known)
    tasks = [a for a in outgoing if a.body.get("locator") == "task:greeting/1"]
    assert len(tasks) == 1, "the re-anchored task must be seen as new content, not skipped as known"
    assert any(e["relation"] == "implements" and e["target"] == SYM
               for e in tasks[0].body["edges"])


def test_editing_an_intent_status_puts_it_back_in_the_push_set(repo):
    _plan_repo(repo)
    known = _ids(repo)
    assert runner.invoke(app, ["intent", "greeting-shape", "--status", "satisfied",
                               "--repo", str(repo)]).exit_code == 0

    outgoing = _push_set(repo, known)
    intents = [a for a in outgoing if a.body.get("locator") == "int:greeting-shape"]
    assert len(intents) == 1
    assert intents[0].body["attrs"]["status"] == "satisfied"


def test_a_revision_keeps_the_locator_as_its_node_id(repo):
    """The id carries the revision; the NODE stays the locator, so every cross-family edge still lands."""
    _plan_repo(repo)
    config = _config(repo, online=False)
    graph, _ = build_graph(repo, config)
    assert "task:greeting/1" in graph and "int:greeting-shape" in graph
    assert not [n for n in graph.nodes if "@" in str(n)], "a revision id must never reach the graph"


def test_the_replica_may_not_revert_a_locally_completed_task(repo):
    """Design law #6 for the two file-truth families: the working tree wins over the replica."""
    _plan_repo(repo)
    config = _config(repo)

    from yigraf import filelog

    # The state the teammate last saw and pushed: the task still open.
    stale = [a for a in filelog.assertions_from_repo(repo)
             if a.body.get("locator") == "task:greeting/1"][0]
    assert stale.body["attrs"]["state"] == "todo"

    # Locally, the task is now done.
    plan_md = next((repo / "yigraf" / "plans").rglob("*.md"))  # plans/<phase>/<slug>.md
    plan_md.write_text(plan_md.read_text().replace("- [ ]", "- [x]", 1))
    local = [a for a in filelog.assertions_from_repo(repo)
             if a.body.get("locator") == "task:greeting/1"][0]
    assert local.body["attrs"]["state"] == "done"
    assert local.id != stale.id, "a changed body must be a changed id"

    store = SqliteAssertionStore(repo / "yigraf" / "cache" / "replica.db")
    OnlineLog(store, PROJECT, signer_key=None,
              require_signed_provenance=False).append(stale)

    graph, stats = build_graph(repo, config)
    assert stats.synced == 1, "the stale revision is still pulled and considered…"
    assert graph.nodes["task:greeting/1"]["state"] == "done", "…but must not overwrite the local file"


def test_a_teammate_only_intent_still_arrives_over_the_log(repo):
    """Deferring to the local file must not become 'ignore the replica' — a locator this workspace
    does NOT have still folds in, or int:team-reconciliation's first scenario breaks."""
    config = _config(repo)
    store = SqliteAssertionStore(repo / "yigraf" / "cache" / "replica.db")
    OnlineLog(store, PROJECT, signer_key=None, require_signed_provenance=False).append(Assertion(
        id="int:theirs@abc123", kind="intent",
        body={"family": "intent", "locator": "int:theirs",
              "attrs": {"kind": "requirement", "status": "proposed",
                        "statement": "yigraf SHALL do their thing",
                        "source_file": "intents/theirs.md"},
              "edges": []},
        provenance=[{"actor": "teammate@example.com", "source": "cli"}]))

    graph, stats = build_graph(repo, config)
    assert stats.synced == 1
    assert "int:theirs" in graph
    assert graph.nodes["int:theirs"]["statement"] == "yigraf SHALL do their thing"


def test_the_replica_may_not_revert_a_locally_reaffirmed_anchor(repo):
    """The memory family needs design law #6 too — for a reason revisioning does not cover.

    ``memory_id`` hashes what a memory *claims* and deliberately not its drift anchors, so re-anchoring
    yields the SAME id with a DIFFERENT body. That is the one case content-addressing does not protect:
    the replica's pushed copy folded after the local file and silently restored the anchor ``reaffirm``
    had just cleared, so drift came back and no amount of reaffirming could clear it.
    """
    config = _config(repo)
    from yigraf import filelog

    assert runner.invoke(app, ["remember", "greet must stay pure", "--concerns", SYM,
                               "--repo", str(repo)]).exit_code == 0
    pushed = [a for a in filelog.assertions_from_repo(repo) if a.kind == "memory"][0]
    stale_anchor = pushed.body["edges"][0]["attrs"]["anchor"]

    # The symbol changes, so the pushed anchor is now stale and drift fires.
    (repo / "app.py").write_text("def greet():\n    return 'hello there'\n")
    assert runner.invoke(app, ["build", str(repo)]).exit_code == 0
    assert compute_drift(build_graph(repo, _config(repo, online=False))[0]), "precondition: drift fires"

    # The principal re-verifies and re-anchors. Locally the drift is gone.
    assert runner.invoke(app, ["reaffirm", pushed.id, "--repo", str(repo)]).exit_code == 0
    local = [a for a in filelog.assertions_from_repo(repo) if a.kind == "memory"][0]
    assert local.body["edges"][0]["attrs"]["anchor"] != stale_anchor
    assert local.id == pushed.id, "the bug's precondition: a re-anchor is NOT a new id"
    assert not compute_drift(build_graph(repo, _config(repo, online=False))[0])

    # Now the replica hands back the copy the teammate's log still holds, carrying the old anchor.
    store = SqliteAssertionStore(repo / "yigraf" / "cache" / "replica.db")
    OnlineLog(store, PROJECT, signer_key=None, require_signed_provenance=False).append(pushed)

    graph, stats = build_graph(repo, config)
    assert stats.synced == 1, "the stale copy is still pulled and considered…"
    assert not compute_drift(graph), "…but must not resurrect the anchor the principal cleared"


# --- divergence: the case design law #6 assumed git would clean up -------------------------------
#
# "The local file wins" is a complete answer only while the losing side survives somewhere. In a repo
# that commits yigraf/ it does (git merge); in one that gitignores it, declining the replica's revision
# discards the only other copy permanently. The fold's verdict is unchanged either way — what changes
# is that the discarded locator is now named instead of vanishing.

def _diverged(repo: Path, config: dict) -> list[str]:
    graph, _ = build_graph(repo, config)
    return list(graph.graph.get("diverged") or ())


def test_an_echo_of_my_own_revision_is_not_divergence(repo):
    """The common case: my own assertion comes back over the wire. Same id ⇒ same content ⇒ nothing to
    report. Divergence must mean disagreement, or the signal is worthless."""
    _plan_repo(repo)
    config = _config(repo)
    from yigraf import filelog

    mine = [a for a in filelog.assertions_from_repo(repo) if a.body.get("locator") == "task:greeting/1"][0]
    OnlineLog(SqliteAssertionStore(repo / "yigraf" / "cache" / "replica.db"), PROJECT,
              signer_key=None, require_signed_provenance=False).append(mine)

    assert _diverged(repo, config) == []


def test_a_competing_revision_of_a_local_locator_is_reported(repo):
    """The same setup as test_the_replica_may_not_revert_a_locally_completed_task — the local file still
    wins — but the declined revision is now named rather than silently dropped."""
    _plan_repo(repo)
    config = _config(repo)
    from yigraf import filelog

    stale = [a for a in filelog.assertions_from_repo(repo)
             if a.body.get("locator") == "task:greeting/1"][0]
    plan_md = next((repo / "yigraf" / "plans").rglob("*.md"))
    plan_md.write_text(plan_md.read_text().replace("- [ ]", "- [x]", 1))
    OnlineLog(SqliteAssertionStore(repo / "yigraf" / "cache" / "replica.db"), PROJECT,
              signer_key=None, require_signed_provenance=False).append(stale)

    graph, _ = build_graph(repo, config)
    assert list(graph.graph.get("diverged")) == ["task:greeting/1"]
    assert graph.nodes["task:greeting/1"]["state"] == "done", "the verdict is unchanged"


def test_a_teammate_only_locator_is_not_divergence(repo):
    """Nothing was declined, so nothing was lost — an arriving belief is not a disagreement."""
    config = _config(repo)
    OnlineLog(SqliteAssertionStore(repo / "yigraf" / "cache" / "replica.db"), PROJECT,
              signer_key=None, require_signed_provenance=False).append(Assertion(
        id="int:theirs@abc123", kind="intent",
        body={"family": "intent", "locator": "int:theirs",
              "attrs": {"kind": "requirement", "status": "proposed",
                        "statement": "yigraf SHALL do their thing",
                        "source_file": "intents/theirs.md"},
              "edges": []},
        provenance=[{"actor": "teammate@example.com", "source": "cli"}]))

    assert _diverged(repo, config) == []


def test_an_offline_workspace_reports_no_divergence(repo):
    """Fail-open: never invent a divergence for a workspace that has no other side."""
    assert _diverged(repo, _config(repo, online=False)) == []


def test_a_memory_can_never_diverge_structurally(repo):
    """Memory keys its node on the content hash, so a differing body is a different NODE and never
    reaches the deferral — its disagreement is a knowledge conflict, which is the correct channel."""
    config = _config(repo)
    _teammate_belief(repo, config, symbol_content_hash(repo, SYM, config))
    graph, stats = build_graph(repo, config)
    assert stats.synced == 1 and "mem:teammate1" in graph
    assert list(graph.graph.get("diverged") or ()) == []


def test_divergence_is_silent_when_there_is_none(repo, capsys):
    """Design law #4: a clean sync must not grow a section explaining that nothing happened."""
    from yigraf import cli

    graph, _ = build_graph(repo, _config(repo, online=False))
    cli._report_divergence(repo, graph)
    assert capsys.readouterr().out == ""


def test_divergence_guidance_forks_on_whether_the_workspace_is_committed(repo, capsys, monkeypatch):
    """The fold's verdict never changes; only what yigraf can promise about the losing copy does. With
    the artifacts in git this is an ordinary merge. Without, yigraf is the only thing that will ever
    mention it — so it must say the divergence is permanent rather than imply git has it."""
    from yigraf import cli

    graph, _ = build_graph(repo, _config(repo, online=False))
    graph.graph["diverged"] = ["task:greeting/1"]

    monkeypatch.setattr(cli, "_artifacts_are_committed", lambda _repo: True)
    cli._report_divergence(repo, graph)
    committed = capsys.readouterr().out
    assert "task:greeting/1" in committed and "any other merge" in committed

    monkeypatch.setattr(cli, "_artifacts_are_committed", lambda _repo: False)
    cli._report_divergence(repo, graph)
    ignored = capsys.readouterr().out
    assert "no merge will ever reconcile these" in ignored


def test_artifacts_are_committed_fails_open_outside_git(tmp_path):
    """No git, no repo, a timeout ⇒ assume the safe world rather than warn about a phantom loss."""
    from yigraf import cli

    assert cli._artifacts_are_committed(tmp_path) is True


def test_artifacts_are_committed_detects_a_real_gitignored_workspace(tmp_path):
    """The case this repo is actually in: a git repo whose yigraf/ is ignored. Distinguishing it from
    'not a git repo' is the whole job — both produce empty `git ls-files` output."""
    import subprocess

    from yigraf import cli

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hi\n")
    (tmp_path / ".gitignore").write_text("/yigraf/\n")
    (tmp_path / "yigraf").mkdir()
    (tmp_path / "yigraf" / "config.yaml").write_text("{}\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    assert cli._artifacts_are_committed(tmp_path) is False

    # …and the same repo once the workspace IS tracked.
    (tmp_path / ".gitignore").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    assert cli._artifacts_are_committed(tmp_path) is True

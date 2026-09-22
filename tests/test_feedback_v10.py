"""The findings from the 1.13.1 field feedback (feedback-v10, the seventh send), each pinned by the
failure it closes.

Two of them were invisible from inside this repo by construction — an unbounded dependency that the
lockfile resolved one way for the developer and PyPI resolved another way for every user, and three hook
channels that went silent one `cd` below the root with fail-open making that read as "nothing to say".
The rest are the second half of a verb this repo said it was waiting to design with both cases in front
of it (`--governs` on the repair verbs), a manifest tail that could not be read as truncation, and three
small honesty fixes. Grouped by finding, as in the v5–v9 files.
"""
import json
import re
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from yigraf import cli, retrieval
from yigraf.cli import app
from yigraf.config import load_config
from yigraf.extract import build_graph

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "status.md").write_text("a: 1\n")
    (tmp_path / "guide.md").write_text("# Guide\n\n## Usage\n\ntext\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _run(root: Path, *args: str):
    return runner.invoke(app, [*args, "--repo", str(root)])


def _mem_id(output: str) -> str:
    m = re.search(r"mem:[0-9a-f]{16}", output)
    assert m, output
    return m.group(0)


def _memory_file(root: Path, mem_id: str) -> Path:
    files = [p for p in (root / "yigraf" / "memory").glob("*.md") if p.stem.endswith(mem_id[4:])]
    assert len(files) == 1, files
    return files[0]


# --- J#1: the MCP dependency is capped, and the help sentence is true again -----------------------

def test_the_mcp_dependency_has_an_upper_bound():
    """mcp 2.x renamed FastMCP and left a stub that raises on import; `>=1.2` alone resolved it on every
    fresh install while uv.lock kept the dev loop on 1.x. The cap is the whole fix."""
    deps = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["dependencies"]
    spec = next(d for d in deps if re.match(r"mcp\s*[><=~!]", d))
    assert "<2" in spec.replace(" ", ""), spec


def test_the_unlocked_install_job_exists_and_does_not_use_the_lockfile():
    """The check `uv sync` structurally cannot perform: install the built wheel with no lockfile."""
    yml = (REPO / ".github" / "workflows" / "unlocked-install.yml").read_text()
    assert "run: uv sync" not in yml and "uv run pytest" not in yml.split("steps:")[1]
    assert "build_server" in yml and "pip install dist/*.whl" in yml


def test_mcp_help_no_longer_promises_it_always_runs():
    out = runner.invoke(app, ["mcp", "--help"]).output
    assert "always runs" not in out
    assert "<2" in out  # it says what IS true: the SDK is pinned to 1.x


# --- J#3: hooks resolve the root when cwd is below it; the refusal names the way out ----------------

def _payload(cwd: Path) -> dict:
    return {"session_id": "probe", "hook_event_name": "SessionStart", "source": "startup", "cwd": str(cwd)}


def test_hook_root_falls_back_to_claude_project_dir_when_cwd_holds_no_store(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    sub = root / "sub" / "deeper"
    sub.mkdir(parents=True)
    monkeypatch.delenv(cli.PROJECT_DIR_ENV, raising=False)
    assert cli._hook_root(_payload(sub)) == sub  # the root rule is unchanged: no parent search, ever
    # …but the SILENCE that used to follow is gone (feedback-v11 K#3). None of the candidates holds a
    # store, so the packet is empty — and an empty packet read exactly like a store with nothing to
    # say. The rule stands; the session is now told which store it is not reading.
    orphan = cli._session_start(_payload(sub))
    assert orphan is not None
    notice = orphan["hookSpecificOutput"]["additionalContext"]
    assert str(root) in notice and "--repo" in notice
    monkeypatch.setenv(cli.PROJECT_DIR_ENV, str(root))
    assert cli._hook_root(_payload(sub)) == root
    packet = cli._session_start(_payload(sub), record=False)
    assert packet is not None and packet["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_hook_root_prefers_a_store_at_cwd_over_the_launch_root(tmp_path, monkeypatch):
    """No parent search, and no override of a nested store the agent is actually inside: cwd first."""
    root = _repo(tmp_path)
    nested = root / "pkg"
    nested.mkdir()
    assert runner.invoke(app, ["init", str(nested)]).exit_code == 0
    monkeypatch.setenv(cli.PROJECT_DIR_ENV, str(root))
    assert cli._hook_root(_payload(nested)) == nested


def test_hook_root_reads_workspace_project_dir_when_a_host_supplies_it(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    sub = root / "sub"
    sub.mkdir()
    monkeypatch.delenv(cli.PROJECT_DIR_ENV, raising=False)
    data = {**_payload(sub), "workspace": {"current_dir": str(sub), "project_dir": str(root)}}
    assert cli._hook_root(data) == root


def test_the_refusal_names_the_resolved_path_and_the_ancestor_store(tmp_path):
    root = _repo(tmp_path)
    sub = root / "sub" / "deeper"
    sub.mkdir(parents=True)
    res = _run(sub, "status")
    assert res.exit_code == 1  # a missing workspace is a genuine stop-condition
    assert str(sub.resolve() / "yigraf") in res.output  # never the bare relative `yigraf`
    assert "does not search parent directories" in res.output
    assert str(root.resolve() / "yigraf") in res.output
    assert f"--repo {root.resolve()}" in res.output


def test_the_refusal_without_an_ancestor_still_states_the_rule(tmp_path):
    res = _run(tmp_path, "status")
    assert res.exit_code == 1
    assert str(tmp_path.resolve() / "yigraf") in res.output
    assert "does not search parent directories" in res.output


def test_init_below_a_governed_root_warns_and_names_the_ancestor(tmp_path):
    root = _repo(tmp_path)
    sub = root / "sub" / "deeper"
    sub.mkdir(parents=True)
    res = runner.invoke(app, ["init", str(sub)])
    assert res.exit_code == 0 and (sub / "yigraf").is_dir()  # warn, never refuse
    assert str(sub.resolve() / "yigraf") in res.output
    assert "⚠ An ancestor already holds a yigraf workspace at" in res.output
    assert str(root.resolve() / "yigraf") in res.output


def test_a_directory_merely_named_yigraf_above_is_not_an_ancestor_store(tmp_path):
    """`~/Dev/yigraf/yigraf` is this project's own clone: the folder that CONTAINS it is called
    `yigraf`, sits above every sibling repo, and holds no config.yaml. It must not warn."""
    (tmp_path / "yigraf" / "yigraf").mkdir(parents=True)  # a clone's parent folder, not a workspace
    project = tmp_path / "arithmos"
    project.mkdir()
    assert cli._ancestor_workspace(project) is None
    res = _run(project, "status")  # no store anywhere: the plain refusal, naming nothing above
    assert res.exit_code == 1 and "one exists above you" not in res.output
    res = runner.invoke(app, ["init", str(project)])
    assert res.exit_code == 0 and "ancestor" not in res.output


def test_init_at_a_plain_root_does_not_warn(tmp_path):
    res = runner.invoke(app, ["init", str(tmp_path)])
    assert res.exit_code == 0 and "ancestor" not in res.output


# --- C.2: --governs on the repair verbs — re-kind in place, or add the policy anchor ----------------

def test_reanchor_same_locus_with_governs_rekinds_in_place_and_stops_the_drift(tmp_path):
    root = _repo(tmp_path)
    mem = _mem_id(_run(root, "remember", "status.md holds only status", "--why", "policy",
                       "--concerns", "file:status.md").output)
    res = _run(root, "reanchor", mem, "file:status.md", "file:status.md", "--governs")
    assert res.exit_code == 0
    assert "Re-kinded file:status.md" in res.output and "policy anchor" in res.output
    assert "Dropped" not in res.output  # same locus + new kind is NOT the already-carried drop branch
    text = _memory_file(root, mem).read_text()
    assert "anchor_algo: governs-v1" in text and "anchor: null" in text
    (root / "status.md").write_text("a: 2\n")  # an edit that obeys the policy
    assert "No drift" in runner.invoke(app, ["drift", str(root)]).output


def test_reanchor_to_a_new_locus_with_governs_moves_and_converts(tmp_path):
    root = _repo(tmp_path)
    mem = _mem_id(_run(root, "remember", "the guide's usage section is the only how-to", "--why", "w",
                       "--concerns", "file:status.md").output)
    res = _run(root, "reanchor", mem, "file:status.md", "file:guide.md#usage", "--governs")
    assert res.exit_code == 0
    assert "file:status.md ⇒ file:guide.md#usage" in res.output
    assert "now a policy anchor" in res.output
    text = _memory_file(root, mem).read_text()
    assert "file:guide.md#usage" in text and "governs-v1" in text and "file:status.md" not in text


def test_reanchor_governs_refuses_an_evidence_only_ref(tmp_path):
    root = _repo(tmp_path)
    mem = _mem_id(_run(root, "remember", "measured", "--why", "w", "--evidence", "file:guide.md").output)
    res = _run(root, "reanchor", mem, "file:guide.md", "file:guide.md", "--governs")
    assert res.exit_code == 0  # guidance, not a stack trace
    assert "only as evidence" in res.output and "never a policy anchor" in res.output
    assert "governs-v1" not in _memory_file(root, mem).read_text()


def test_reaffirm_governs_rekinds_a_carried_content_anchor(tmp_path):
    root = _repo(tmp_path)
    mem = _mem_id(_run(root, "remember", "status.md holds only status", "--why", "policy",
                       "--concerns", "file:status.md").output)
    res = _run(root, "reaffirm", mem, "--governs", "file:status.md")
    assert res.exit_code == 0 and "re-kinded to a policy anchor" in res.output
    assert "governs-v1" in _memory_file(root, mem).read_text()


def test_reaffirm_governs_adds_the_policy_anchor_the_node_did_not_carry(tmp_path):
    """The adds half (G#5/G#10) for the policy kind — the anchor the drop ⚠ said no verb could restore."""
    root = _repo(tmp_path)
    mem = _mem_id(_run(root, "remember", "status.md holds only status", "--why", "policy",
                       "--concerns", "file:status.md").output)
    res = _run(root, "reaffirm", mem, "--governs", "file:guide.md#usage")
    assert res.exit_code == 0 and "now governs file:guide.md#usage" in res.output
    text = _memory_file(root, mem).read_text()
    assert "sym: file:guide.md#usage" in text and "sym: file:status.md" in text  # added, not replaced
    assert "No supersede recorded" in res.output


def test_reaffirm_governs_is_validated_like_capture(tmp_path):
    root = _repo(tmp_path)
    mem = _mem_id(_run(root, "remember", "s", "--why", "w", "--concerns", "file:status.md").output)
    res = _run(root, "reaffirm", mem, "--governs", "file:guide.md:L1-L2")
    assert res.exit_code == 0 and "not a line range" in res.output
    res = _run(root, "reaffirm", mem, "--governs", "file:nope.md")
    assert res.exit_code == 0 and "no such file" in res.output
    assert "governs-v1" not in _memory_file(root, mem).read_text()  # nothing was written


def test_reaffirm_governs_needs_a_memory_id(tmp_path):
    root = _repo(tmp_path)
    res = _run(root, "reaffirm", "file:status.md", "--governs", "file:status.md")
    assert res.exit_code == 0 and "give the mem: id" in res.output


def test_the_drop_warning_names_the_governs_route(tmp_path):
    root = _repo(tmp_path)
    mem = _mem_id(_run(root, "remember", "two anchors", "--why", "w", "--concerns", "file:status.md",
                       "--concerns", "file:guide.md").output)
    res = _run(root, "reanchor", mem, "file:status.md", "file:guide.md")
    assert "⚠ Dropped file:status.md" in res.output
    assert "no verb adds" not in res.output
    assert f"yigraf reaffirm {mem} --governs file:status.md" in res.output


# --- C.1: the manifest tail names its cause; SessionStart has a budget of its own ------------------

def _many_memories(root: Path, n: int) -> None:
    for i in range(n):
        assert _run(root, "remember", f"belief number {i} about the guide and its usage {i}",
                    "--why", f"reason {i}").exit_code == 0


def test_the_manifest_tail_names_the_packet_budget_when_it_cuts(tmp_path):
    root = _repo(tmp_path)
    _many_memories(root, 20)
    config = load_config(root / "yigraf" / "config.yaml")
    config["session_start"]["preamble"] = "rule\n" * 400  # a preamble that spends the whole budget
    config["session_start"]["manifest_titles"] = 15
    config["session_start"]["token_budget"] = 400
    graph, _ = build_graph(root, config)
    text = retrieval.session_context(graph, config, root=root).text
    titles = [ln for ln in text.splitlines() if ln.startswith("  mem:")]
    assert len(titles) < 15  # the cut happened
    tail = next(ln for ln in text.splitlines() if "title(s) cut by the packet budget" in ln)
    assert "session_start.token_budget" in tail
    assert f"+{15 - len(titles)} title(s) cut" in tail
    assert "+5 more not listed" in tail  # the cap's own remainder, said apart from the cut


def test_the_manifest_tail_without_a_cut_names_only_the_cap(tmp_path):
    root = _repo(tmp_path)
    _many_memories(root, 20)
    config = load_config(root / "yigraf" / "config.yaml")
    config["session_start"]["preamble"] = ""
    config["session_start"]["token_budget"] = 20000
    graph, _ = build_graph(root, config)
    text = retrieval.session_context(graph, config, root=root).text
    assert len([ln for ln in text.splitlines() if ln.startswith("  mem:")]) == 15
    assert "cut by the packet budget" not in text and "+5 more not listed" in text


def test_session_start_token_budget_sizes_the_packet_independently_of_the_query_budget(tmp_path):
    root = _repo(tmp_path)
    _many_memories(root, 20)
    config = load_config(root / "yigraf" / "config.yaml")
    config["session_start"]["preamble"] = "rule\n" * 400
    config["retrieval"]["query_token_budget"] = 400  # would have starved the packet before
    config["session_start"]["token_budget"] = 20000
    graph, _ = build_graph(root, config)
    text = retrieval.session_context(graph, config, root=root).text
    assert len([ln for ln in text.splitlines() if ln.startswith("  mem:")]) == 15
    # …and unset, it falls back to the query budget: byte-identical to the old behaviour.
    config["session_start"]["token_budget"] = None
    graph, _ = build_graph(root, config)
    starved = retrieval.session_context(graph, config, root=root).text
    assert len([ln for ln in starved.splitlines() if ln.startswith("  mem:")]) < 15


def test_the_shipped_config_yaml_carries_the_new_key(tmp_path):
    root = _repo(tmp_path)
    assert "token_budget: 4000" in (root / "yigraf" / "config.yaml").read_text()


# --- J#4: install prints the MCP config, and now says so on every surface --------------------------

def test_install_plan_and_help_say_the_mcp_config_is_printed_not_written(tmp_path):
    root = _repo(tmp_path)
    plan = runner.invoke(app, ["install", str(root), "--plan"]).output
    assert "PRINTED for you to paste, not written" in plan
    help_out = runner.invoke(app, ["install", "--help"]).output
    assert "never written" in help_out or "not written" in help_out
    assert "wires it by default" not in (REPO / "pyproject.toml").read_text()


# --- J#5: rendering the packet is not a read-only probe unless you say so ------------------------

def test_hook_session_start_dry_run_records_no_surfacing(tmp_path):
    root = _repo(tmp_path)
    mem = _mem_id(_run(root, "remember", "hold this always", "--why", "w").output)
    assert _run(root, "pin", mem).exit_code == 0  # a pin renders in full → it is a recorded surfacing
    telemetry = root / "yigraf" / ".local" / "telemetry.json"
    before = telemetry.read_text() if telemetry.is_file() else None
    res = runner.invoke(app, ["hook", "session-start", "--dry-run"], input=json.dumps(_payload(root)))
    assert res.exit_code == 0 and "hold this always" in res.output
    assert (telemetry.read_text() if telemetry.is_file() else None) == before
    res = runner.invoke(app, ["hook", "session-start"], input=json.dumps(_payload(root)))
    assert res.exit_code == 0
    assert telemetry.is_file() and mem in json.loads(telemetry.read_text())


def test_both_hook_verbs_say_that_they_write():
    assert "record" in runner.invoke(app, ["hook", "session-start", "--help"]).output
    assert "recorded" in runner.invoke(app, ["hook", "post-tool-use", "--help"]).output


# --- J#2: the migration proof cannot pass vacuously -----------------------------------------------

def test_the_migration_proof_cannot_pass_vacuously():
    """J#2's guard, re-pointed at the durable fix it asked for (feedback-v11 §E).

    This pinned ``allow_module_level=True`` — the *interim* mechanism, a module-level skip that made a
    checkout say what was missing instead of showing seven green ticks over ``set() == set()``. The
    field then sent the committed fixture that skip was a placeholder for, so pinning it would now fail
    by construction and, worse, would pin the weaker of the two answers. What must stay true is the
    property, not the mechanism: the proof runs on a checkout with no self-hosted store, and the corpus
    it runs against cannot be thinned into vacuity without a test saying so.
    """
    src = (REPO / "tests" / "test_migrate.py").read_text()
    assert "allow_module_level=True" not in src, "the skip was replaced by the fixture — don't restore it"
    assert 'pytest.param(FIXTURE, id="fixture")' in src, "the proof must run without the self-hosted store"
    assert "def test_the_fixture_store_exercises_every_shape_this_proof_compares" in src, \
        "the fixture's own canary is what keeps a thinned fixture from passing vacuously"
    store = REPO / "tests" / "fixtures" / "migration-store"
    assert (store / "yigraf" / "config.yaml").exists() is False, \
        "the fixture carries no config.yaml — the proof builds its own (the field's call, kept)"
    assert len(list((store / "yigraf" / "memory").glob("*.md"))) >= 8


# --- 1.14.1: the two things the first field install of 1.14.0 showed ------------------------------

def test_install_auto_wires_repo_hosts_and_only_names_home_only_hosts(tmp_path, monkeypatch):
    """A HOME marker says 'installed on this machine', not 'used here'. 1.14.0 wired it anyway and the
    next agent deleted `.cursor/` and `GEMINI.md` without understanding them — twice in one day."""
    from yigraf import hooks
    root = _repo(tmp_path)
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    (home / ".gemini").mkdir()
    (root / ".claude").mkdir()
    monkeypatch.setattr(hooks.Path, "home", classmethod(lambda cls: home))
    assert hooks.detect_hosts_split(root) == (["claude"], ["cursor", "gemini"])
    assert hooks.detect_hosts(root) == ["claude", "cursor", "gemini"]  # the union is unchanged
    plan = runner.invoke(app, ["install", str(root), "--plan"]).output
    assert "• claude" in plan and "○ cursor" in plan and "NOT wired" in plan
    res = runner.invoke(app, ["install", str(root), "--host", "auto"])
    assert res.exit_code == 0, res.output
    assert "cursor, gemini: installed on this machine, never used in this repo — NOT wired" in res.output
    assert "== claude" in res.output and "== cursor" not in res.output
    assert not (root / ".cursor").exists() and not (root / "GEMINI.md").exists()


def test_install_host_all_still_wires_every_detected_host(tmp_path, monkeypatch):
    from yigraf import hooks
    root = _repo(tmp_path)
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    monkeypatch.setattr(hooks.Path, "home", classmethod(lambda cls: home))
    res = runner.invoke(app, ["install", str(root), "--host", "all"])
    assert res.exit_code == 0, res.output
    assert "== cursor" in res.output and (root / ".cursor" / "rules" / "yigraf.mdc").is_file()
    assert "NOT wired" not in res.output


def test_a_repo_marker_wires_the_host_on_its_own(tmp_path, monkeypatch):
    """The newcomer path: a host's first visit creates its repo marker, and the next install wires it."""
    from yigraf import hooks
    root = _repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(hooks.Path, "home", classmethod(lambda cls: home))
    (root / ".cursor").mkdir()
    res = runner.invoke(app, ["install", str(root)])
    assert res.exit_code == 0 and "== cursor" in res.output
    assert (root / ".cursor" / "rules" / "yigraf.mdc").is_file()


def test_the_agents_block_and_the_skill_tell_a_new_host_to_wire_itself():
    from yigraf import hooks
    assert "yigraf install --host <your-host>" in hooks._AGENTS_BLOCK
    assert "yigraf install --host <name>" in hooks.skill_text()


# --- 1.14.2: a skipped git hook must not read as degraded drift --------------------------------------

def test_install_without_git_says_drift_is_unaffected(tmp_path):
    root = _repo(tmp_path)  # tmp_path holds no .git
    res = runner.invoke(app, ["install", str(root), "--host", "mcp"])
    assert res.exit_code == 0, res.output
    assert "post-commit → skipped (not a git repository)" in res.output
    assert "Drift detection is UNAFFECTED" in res.output
    assert "degraded" not in res.output

"""The SessionStart orientation packet (int:session-orientation) — the three UNRANKED channels.

Everything else yigraf injects ranks against a topic. These tests pin the channels that deliberately
do not: the verbatim house rules, the pin tier, and the titles manifest — plus the global-obligation
rule that stopped a repo between milestones from reading as a clean dashboard while `status` said
otherwise.
"""
import json
from pathlib import Path

from typer.testing import CliRunner

from yigraf import retrieval
from yigraf.cli import app
from yigraf.config import default_config, load_config

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"


def _repo(tmp_path: Path, *, open_task: bool = True) -> Path:
    """An initialized repo: one intent, one plan whose single task tracks + implements a symbol."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "session-expiry", "--repo", str(tmp_path),
                               "-s", "The system SHALL expire a session after 30m idle."]).exit_code == 0
    assert runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth",
                               "--task", "implement idle expiry"]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", "int:session-expiry", "--repo", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)]).exit_code == 0
    if not open_task:
        _close_every_task(tmp_path)
    return tmp_path


def _close_every_task(root: Path) -> None:
    """Check every box, so no plan holds open work — the state that used to blind SessionStart."""
    for path in (root / "yigraf" / "plans").rglob("*.md"):
        path.write_text(path.read_text().replace("- [ ]", "- [x]"))
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0


def _packet(root: Path) -> str:
    """The real SessionStart hook payload, through its actual entry point."""
    out = runner.invoke(app, ["hook", "session-start"],
                        input=json.dumps({"source": "clear", "cwd": str(root)})).output
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out.strip() else ""


def _configure(root: Path, block: str) -> None:
    cfg = root / "yigraf" / "config.yaml"
    cfg.write_text(cfg.read_text() + "\n" + block)


def _edit(root: Path) -> None:
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token + 1\n")


# --- The preamble: instruction, not reference -----------------------------------------------------


def test_the_house_rules_lead_the_packet_verbatim(tmp_path: Path):
    """The rules land ahead of the `Context for` frame, unranked and unedited.

    Position is the point, not decoration. The same words inside the frame read as reference material
    about the code — which is how a whole session's worth of drift warnings got treated as an input
    rather than an instruction — so they go above it, where CLAUDE.md sits.
    """
    text = _packet(_repo(tmp_path))
    rules = default_config()["session_start"]["preamble"].strip()
    assert rules in text
    assert text.index(rules) < text.index('Context for "active plan')


def test_the_preamble_is_the_repo_s_to_rewrite(tmp_path: Path):
    """It lives in the committed config so a team's conventions ride the repo, not each agent's memory."""
    root = _repo(tmp_path)
    _configure(root, 'session_start:\n  preamble: "HOUSE RULE: never touch auth/ on a Friday."')
    text = _packet(root)
    assert "HOUSE RULE: never touch auth/ on a Friday." in text
    assert "Standing rules for this session" not in text  # replaced, not appended to


def test_an_empty_preamble_silences_the_channel(tmp_path: Path):
    """Design law #4 survives as an opt-out — the unranked channel is not mandatory."""
    root = _repo(tmp_path)
    _configure(root, "session_start:\n  preamble: ''")
    assert "Standing rules" not in _packet(root)


def test_the_rules_arrive_with_the_live_counts_attached(tmp_path: Path):
    """`append_status` ends the head with the status line: the rule and the number it applies to."""
    root = _repo(tmp_path)
    assert "yigraf" in _packet(root).split('Context for "active plan')[0]
    _configure(root, "session_start:\n  append_status: false")
    head = _packet(root).split('Context for "active plan')[0]
    assert "· fresh" not in head and "sym ·" not in head


# --- Global obligations: the coverage hole ---------------------------------------------------------


def test_drift_reaches_session_start_with_no_plan_holding_open_work(tmp_path: Path):
    """A repo between milestones must still be told what is outstanding.

    Obligations used to be gated on the seed traversal, and a plan drops out of the seed set once its
    last box is checked — so closing a milestone silently removed the only path by which drift or a
    stale completion could reach session start. It read as a clean dashboard precisely when there was
    nothing left to hang a warning on, which is when a forgotten obligation goes unnoticed longest.
    """
    root = _repo(tmp_path)
    assert runner.invoke(app, ["remember", "sessions expire on idle, not on absolute age",
                               "--repo", str(root), "--why", "renewal must be possible",
                               "--concerns", SYM]).exit_code == 0
    _close_every_task(root)
    _edit(root)
    text = _packet(root)
    assert "⚠ Drift:" in text and SYM in text
    assert "⚠ Stale (re-verify completion):" in text and "task:auth/1" in text


def test_stale_is_capped_and_names_the_command_that_lists_the_rest(tmp_path: Path):
    """Going global means going bounded — with a handle, never a silent truncation."""
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "work.py"
    src.write_text("".join(f"def step{n}():\n    return {n}\n\n" for n in range(7)))
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["plan", "work", "--repo", str(tmp_path), "-t", "Work",
                               *sum((["--task", f"step {n}"] for n in range(7)), [])]).exit_code == 0
    for n in range(7):
        assert runner.invoke(app, ["link", f"task:work/{n + 1}", f"sym:work.py#step{n}",
                                   "--repo", str(tmp_path)]).exit_code == 0
    root = tmp_path
    _close_every_task(root)
    src.write_text(src.read_text().replace("    return ", "    return 1 + "))
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0

    text = _packet(root)
    stale = [ln for ln in text.splitlines() if "completion STALE" in ln]
    assert len(stale) == load_config(root / "yigraf" / "config.yaml")["retrieval"]["max_stale_lines"]
    assert "more stale completion(s) — `yigraf drift --stale`" in text


# --- The pin tier ----------------------------------------------------------------------------------


def test_a_pinned_belief_is_injected_in_full_and_never_twice(tmp_path: Path):
    """Pinning is the escape hatch from ranking, so the pinned block carries the whole node."""
    root = _repo(tmp_path)
    out = runner.invoke(app, ["note-constraint", "runs write to results.local/, never results/",
                              "--repo", str(root), "--pin",
                              "--why", "a committed run record is a review artifact"]).output
    assert "pinned" in out
    text = _packet(root)
    assert "Pinned — these hold regardless of what you are working on:" in text
    assert "a committed run record is a review artifact" in text  # the why, not just the statement
    mem_id = out.split("Captured ")[1].split(" ")[0]
    assert text.count(mem_id) == 1  # pinned OR ranked OR listed — never paid for twice


def test_pinning_does_not_re_identify_the_belief(tmp_path: Path):
    """A pin is routing, not a claim — so it must stay outside the content-addressed id (mem:063)."""
    root = _repo(tmp_path)
    out = runner.invoke(app, ["remember", "ground truth never enters the estimator",
                              "--repo", str(root), "--why", "it would make the experiment vacuous"]).output
    mem_id = out.split("Captured ")[1].split(" ")[0]
    assert runner.invoke(app, ["pin", mem_id, "--repo", str(root)]).exit_code == 0
    assert mem_id in _packet(root).split('Context for "active plan')[0]  # same id, now pinned


def test_the_pinned_budget_binds_and_says_what_it_dropped(tmp_path: Path):
    """A pin tier where everything fits is a pin tier that will become the new wallpaper."""
    root = _repo(tmp_path)
    for n in range(4):
        assert runner.invoke(app, ["remember", f"standing rule number {n}", "--repo", str(root),
                                   "--pin", "--why", f"reason {n} " + "padding " * 40]).exit_code == 0
    _configure(root, "session_start:\n  pinned_budget: 120")
    text = _packet(root)
    assert "pinned memory(s) elided by session_start.pinned_budget" in text


def test_unpinning_returns_a_belief_to_ranked_retrieval(tmp_path: Path):
    root = _repo(tmp_path)
    out = runner.invoke(app, ["remember", "a rule that stopped being universal", "--repo", str(root),
                              "--pin", "--why", "it was"]).output
    mem_id = out.split("Captured ")[1].split(" ")[0]
    assert runner.invoke(app, ["pin", mem_id, "--off", "--repo", str(root)]).exit_code == 0
    assert "Pinned — these hold" not in _packet(root)
    # Idempotence is guidance, not an error (design law #1).
    again = runner.invoke(app, ["pin", mem_id, "--off", "--repo", str(root)])
    assert again.exit_code == 0 and "already unpinned" in again.output


# --- The titles manifest ----------------------------------------------------------------------------


def test_the_manifest_names_what_the_packet_did_not_show(tmp_path: Path):
    """Retrievable and reachable are different properties, and only the second one has value.

    An agent cannot formulate a query for knowledge whose existence it is unaware of, and a fresh
    session is by construction unaware of everything. The manifest costs ~30 tokens a belief and
    converts the store from invisible-but-present into a set of known-unknowns.
    """
    root = _repo(tmp_path)
    for n in range(12):
        assert runner.invoke(app, ["remember", f"an unrelated finding about topic {n}",
                                   "--repo", str(root), "--why", f"because {n}"]).exit_code == 0
    text = _packet(root)
    assert "Also known — titles only" in text
    assert "`yigraf show <id>` reads one in full" in text  # the manifest hands over a live handle
    listed = text.split("Also known")[1]
    assert sum(1 for ln in listed.splitlines() if ln.strip().startswith("mem:")) >= 5


def test_the_manifest_never_repeats_what_already_rendered(tmp_path: Path):
    """It exists to name what you *don't* otherwise see; repeating is pure budget waste."""
    root = _repo(tmp_path)
    for n in range(12):
        assert runner.invoke(app, ["remember", f"a finding about topic {n}", "--repo", str(root),
                                   "--why", f"because {n}", "--concerns", SYM]).exit_code == 0
    text = _packet(root)
    head, listed = text.split("Also known")
    for line in listed.splitlines():
        if line.strip().startswith("mem:"):
            assert line.split()[0] not in head


def test_the_manifest_can_be_turned_off(tmp_path: Path):
    root = _repo(tmp_path)
    assert runner.invoke(app, ["remember", "something worth listing", "--repo", str(root),
                               "--why", "y"]).exit_code == 0
    _configure(root, "session_start:\n  manifest_titles: 0")
    assert "Also known" not in _packet(root)


# --- The budget still binds over all of it ---------------------------------------------------------


def test_the_unranked_channels_are_charged_not_added(tmp_path: Path):
    """Every new channel is charged to the same budget the slice draws on.

    The 1.3.1 lesson was that a block outside the budget does not merely overrun, it starves the
    render — so a preamble, a pin block and a manifest that were simply appended would re-enter that
    failure three times over. A bloated preamble must visibly cost the ranked content it displaces.
    """
    root = _repo(tmp_path)
    for n in range(30):
        assert runner.invoke(app, ["remember", f"finding {n} " + "words " * 30, "--repo", str(root),
                                   "--why", "reason " * 60, "--concerns", SYM]).exit_code == 0
    for n in range(4):
        assert runner.invoke(app, ["remember", f"pinned rule {n} " + "words " * 20, "--pin",
                                   "--repo", str(root), "--why", "reason " * 40]).exit_code == 0
    budget = load_config(root / "yigraf" / "config.yaml")["retrieval"]["query_token_budget"]
    assert len(_packet(root)) // 3 <= budget


def test_session_context_is_silent_only_when_there_is_nothing_at_all(tmp_path: Path):
    """The `None` contract narrowed but did not go away — a graph and a config with nothing to say."""
    from yigraf.extract import build_graph

    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    config = default_config()
    config["session_start"] = {"preamble": "", "append_status": False,
                               "pinned_budget": 0, "manifest_titles": 0}
    graph, _ = build_graph(tmp_path, config)
    assert retrieval.session_context(graph, config, root=tmp_path) is None

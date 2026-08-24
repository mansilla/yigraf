"""`amend` — the record-repair verb — plus `--why-file` and a repeatable `--rejected`.

The gap `memory._render_body` had been naming inside its own refusal: a `--why` a shell rewrote
(backticks, `$`, `!`) is unrecoverable prose, and the exits were to delete the artifact by hand or to
`supersede` — filing a mind-change nobody had and leaving the mangled text standing as the superseded
belief, in the trail that is the most valuable structure in the graph.

`amend` re-keys the node, because it must: the id is a content hash over exactly the statement / why /
rejected it repairs, and `test_minted_id_matches_the_payload_hash` pins that. So these tests care most
about the two things a re-key can break — a referrer that would cascade, and an assertion already on a
shared log that cannot be retracted — and about what must survive it: the anchors, the trail, and the
telemetry a settled belief earned.
"""
import json
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf import counters, memory
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
    result = runner.invoke(app, [*args, "--repo", str(root)])
    assert result.exit_code == 0, result.output  # every guard exits 0 with guidance (design law #1)
    return result.output


def _remember(root: Path, statement: str, *extra: str) -> str:
    return re.search(r"mem:[0-9a-f]+", _run(root, "remember", statement, *extra)).group(0)


def _drift(root: Path) -> str:
    """``drift`` takes the repo as a positional PATH, not ``--repo`` — so it bypasses ``_run``."""
    result = runner.invoke(app, ["drift", str(root), "--stale"])
    assert result.exit_code == 0, result.output
    return result.output


def _the_node(root: Path) -> memory.Memory:
    paths = sorted(memory.memory_dir(root).glob("*.md"))
    assert len(paths) == 1, [p.name for p in paths]
    return memory.read_memory(paths[0])


# --- --why-file: the trap that motivated the flag ------------------------------------------------


def test_why_file_carries_shell_hostile_text_verbatim_on_one_line(tmp_path: Path):
    """The whole point: a file is not a shell word. Backticks, `$VAR` and `!` reach the artifact as
    typed, and the newlines a paragraph naturally has collapse — **Why:** is a single line."""
    root = _repo(tmp_path)
    why = tmp_path / "why.txt"
    why.write_text("Callers cache `expires_at`,\nso $HOME mutation breaks them silently!\n")
    _remember(root, "refresh keeps the token immutable", "--why-file", str(why))
    assert _the_node(root).why == (
        "Callers cache `expires_at`, so $HOME mutation breaks them silently!")


def test_why_and_why_file_together_are_refused_rather_than_ranked(tmp_path: Path):
    """Two sources for one field is a caller mistake, and picking a winner would silently discard
    reasoning. Nothing is captured."""
    root = _repo(tmp_path)
    why = tmp_path / "why.txt"
    why.write_text("from the file")
    out = _run(root, "remember", "a claim", "--why", "from the flag", "--why-file", str(why))
    assert "not both" in out
    assert not list(memory.memory_dir(root).glob("*.md"))


def test_an_unreadable_or_empty_why_file_guides_and_captures_nothing(tmp_path: Path):
    root = _repo(tmp_path)
    assert "couldn't read" in _run(root, "remember", "a claim", "--why-file", str(tmp_path / "nope"))
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n\n")
    assert "is empty" in _run(root, "remember", "a claim", "--why-file", str(empty))
    assert not list(memory.memory_dir(root).glob("*.md"))


def test_the_empirical_refusal_names_why_file_as_the_way_out(tmp_path: Path):
    """v4 #15: the ordering half was already satisfied (this refuses before any build), so what was
    left to fix is the cost of the refusal — the composed --why, re-sent in full."""
    root = _repo(tmp_path)
    out = _run(root, "remember", "a claim", "--grounding", "empirical", "--why", "x" * 400)
    assert "--why-file" in out


# --- a repeatable --rejected --------------------------------------------------------------------


def test_repeated_rejected_keeps_every_alternative(tmp_path: Path):
    """It was a single-value option, so a second `--rejected` silently won and the first ruled-out
    design was gone — unwarned, at capture time, on the most perishable content in the node."""
    root = _repo(tmp_path)
    _remember(root, "a claim", "--rejected", "mutate in place", "--rejected", "recompute per call")
    assert _the_node(root).alternatives == "mutate in place || recompute per call"


# --- amend: the repair ---------------------------------------------------------------------------


def test_amend_rewrites_the_why_and_rekeys_without_a_supersede(tmp_path: Path):
    """A repair, not a mind-change: one record on disk, no supersedes edge, and the id follows the
    text because the id IS a hash of the text."""
    root = _repo(tmp_path)
    old_id = _remember(root, "refresh keeps the token immutable", "--why", "mangled `$(date)`",
                       "--concerns", SYM)
    out = _run(root, "amend", old_id, "--why", "callers cache it, so a mutation breaks them")

    node = _the_node(root)  # asserts exactly one artifact — the old file is gone, not orphaned
    assert node.id != old_id and node.id in out
    assert node.why == "callers cache it, so a mutation breaks them"
    assert node.supersedes == [] and not node.superseded_by, "a repair files no mind-change"
    assert [c.sym for c in node.concerns] == [SYM], "the anchor is untouched"
    assert node.concerns[0].anchor is not None


def test_the_amended_record_still_satisfies_the_id_payload_invariant(tmp_path: Path):
    """The reason amend cannot keep the old id: `test_minted_id_matches_the_payload_hash` pins the
    on-disk id to a hash of the payload, and statement/why/rejected are all inside it."""
    root = _repo(tmp_path)
    mem_id = _remember(root, "a claim", "--why", "first", "--concerns", SYM)
    _run(root, "amend", mem_id, "--statement", "a better claim", "--rejected", "the other way")
    node = _the_node(root)
    assert node.id == memory.memory_id(
        node.type, node.statement, node.why, node.alternatives, node.serves,
        [c.sym for c in node.concerns], [e.ref for e in node.evidence], node.supersedes)


def test_amend_carries_hand_written_prose_it_did_not_write(tmp_path: Path):
    """`_render_body` refuses to re-derive a body for exactly this reason, so amend splices lines
    instead: whatever the three markers do not describe must survive the repair."""
    root = _repo(tmp_path)
    mem_id = _remember(root, "a claim", "--why", "botched")
    path = next(memory.memory_dir(root).glob("*.md"))
    path.write_text(path.read_text() + "\n### A table someone added by hand\n\n| a | b |\n")

    _run(root, "amend", mem_id, "--why", "repaired")
    body = next(memory.memory_dir(root).glob("*.md")).read_text()
    assert "**Why:** repaired" in body
    assert "A table someone added by hand" in body and "| a | b |" in body


def test_amend_moves_the_telemetry_a_belief_already_earned(tmp_path: Path):
    """Same belief, so it keeps its upholds: telemetry is keyed by id, and silently resetting it would
    demote a settled node for a typo fix (counters.apply_maturity reads it as the maturity clock)."""
    root = _repo(tmp_path)
    mem_id = _remember(root, "a claim", "--why", "botched")
    counters.telemetry_path(root).parent.mkdir(parents=True, exist_ok=True)
    counters.telemetry_path(root).write_text(json.dumps({mem_id: {"usage": 9, "upholds": 4.5}}))

    _run(root, "amend", mem_id, "--why", "repaired")
    telemetry = json.loads(counters.telemetry_path(root).read_text())
    assert mem_id not in telemetry
    assert telemetry[_the_node(root).id] == {"usage": 9, "upholds": 4.5}


def test_amend_repairs_a_fresh_successor_and_repoints_the_back_stamp(tmp_path: Path):
    """The primary case after a `supersede`, which takes a --why of its own and is just as exposed to
    the shell. Its only referrer is the predecessor's `superseded_by` — a stamp, not an identity (it is
    absent from the id payload), so it is re-pointed rather than treated as a cascade."""
    root = _repo(tmp_path)
    old = _remember(root, "cache the token in module state", "--concerns", SYM, "--why", "cheap")
    new = re.search(r"mem:[0-9a-f]+", _run(
        root, "supersede", old, "cache the token per request", "--why", "mangled `$(x)`")).group(0)

    out = _run(root, "amend", new, "--why", "module state leaked across tenants")
    assert "Re-pointed" in out
    by_id = {m.id: m for m in (memory.read_memory(p) for p in memory.memory_dir(root).glob("*.md"))}
    amended = next(m for m in by_id.values() if m.id not in (old, new))
    assert by_id[old].superseded_by == amended.id, "the trail still leads to the live claim"
    assert amended.supersedes == [old], "and still leads back"
    assert new not in by_id, "the botched revision is not left behind as a second live node"


# --- amend: what it refuses, and why ------------------------------------------------------------


def test_amend_refuses_a_node_a_resolution_names(tmp_path: Path):
    """The cascade: `resolution_id` hashes the pair it reconciles, so re-keying one side would re-key
    the verdict about it — and a human made that verdict. Corrected additively instead."""
    root = _repo(tmp_path)
    left = _remember(root, "the refresh path is pure", "--concerns", SYM, "--why", "a")
    right = _remember(root, "the refresh path is idempotent", "--concerns", SYM, "--why", "b")
    _run(root, "reconcile", left, right, "--why", "compatible")

    out = _run(root, "amend", left, "--why", "a repair that must not happen")
    assert "can't be repaired in place" in out and "cascade" in out
    assert f"yigraf supersede {left}" in out
    assert memory.find_memory(root, left) is not None, "and nothing was written"


def test_amend_refuses_a_superseded_node_and_names_the_live_claim(tmp_path: Path):
    root = _repo(tmp_path)
    old = _remember(root, "cache in module state", "--concerns", SYM, "--why", "cheap")
    new = re.search(r"mem:[0-9a-f]+", _run(
        root, "supersede", old, "cache per request", "--why", "tenants leaked")).group(0)

    out = _run(root, "amend", old, "--why", "repairing history")
    assert "is superseded" in out and new in out


def test_amend_refuses_an_assertion_the_shared_log_already_holds(tmp_path: Path):
    """Append-only means never retractable. Re-keying locally would mint a SECOND node while teammates
    keep the one they pulled — and for a content-addressed family that arrives as a knowledge conflict
    rather than a correction (`extract._fold_replica`)."""
    import yaml

    from yigraf.log import Assertion
    from yigraf.onlinelog import OnlineLog, SqliteAssertionStore

    root = _repo(tmp_path)
    mem_id = _remember(root, "a claim", "--why", "botched")
    cfg = root / "yigraf" / "config.yaml"
    data = yaml.safe_load(cfg.read_text()) or {}
    data.setdefault("online", {})["project"] = "proj"
    cfg.write_text(yaml.safe_dump(data))
    replica = root / "yigraf" / "cache" / "replica.db"
    replica.parent.mkdir(parents=True, exist_ok=True)
    OnlineLog(SqliteAssertionStore(replica), "proj", signer_key=None,
              require_signed_provenance=False).append(Assertion(
                  id=mem_id, kind="memory", body={"family": "memory", "attrs": {}, "edges": []},
                  provenance=[{"actor": "me", "source": "cli"}]))

    out = _run(root, "amend", mem_id, "--why", "a repair teammates already hold the old text of")
    assert "already been pushed" in out and f"yigraf supersede {mem_id}" in out
    assert memory.find_memory(root, mem_id) is not None


def test_a_broken_replica_does_not_block_a_local_repair(tmp_path: Path):
    """Fail-open (design law #5): only a POSITIVELY known push refuses. An unreadable replica is "I
    cannot tell", and refusing a legitimate repair over a corrupt cache is the worse error."""
    import yaml

    root = _repo(tmp_path)
    mem_id = _remember(root, "a claim", "--why", "botched")
    cfg = root / "yigraf" / "config.yaml"
    data = yaml.safe_load(cfg.read_text()) or {}
    data.setdefault("online", {})["project"] = "proj"
    cfg.write_text(yaml.safe_dump(data))
    replica = root / "yigraf" / "cache" / "replica.db"
    replica.parent.mkdir(parents=True, exist_ok=True)
    replica.write_bytes(b"not a database")

    _run(root, "amend", mem_id, "--why", "repaired anyway")
    assert _the_node(root).why == "repaired anyway"


def test_amend_with_no_change_guides_instead_of_rewriting(tmp_path: Path):
    root = _repo(tmp_path)
    mem_id = _remember(root, "a claim", "--why", "unchanged")
    out = _run(root, "amend", mem_id)
    assert "nothing to amend" in out
    assert _the_node(root).id == mem_id, "and the record is byte-untouched"


# --- feedback-v4 #14 / #16 / #13: what the surfaces say ------------------------------------------


def test_a_stale_completion_dates_itself_by_the_anchor_not_by_git(tmp_path: Path):
    """v4 #14. The failure was not a wrong verb but correct-looking reasoning about *when*: the field
    read `git log`, found earlier commits touching the file, and concluded the staleness predated the
    session. Invalid — `link` re-stamps the anchor, so the two timelines are different. The line now
    names the commit the anchor was taken at, which both answers it and forecloses the wrong route."""
    import subprocess

    from yigraf import artifacts

    root = _repo(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init"],
                   cwd=root, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True, check=True).stdout.strip()

    _run(root, "plan", "demo", "--title", "Demo", "--task", "keep refresh pure")
    _run(root, "link", "task:demo/1", SYM)
    plan = artifacts.read_plan(next((root / "yigraf" / "plans").rglob("*.md")))
    assert plan.tasks[0].implements[0].stamped_at == head, "the stamp rides the anchor it dates"

    _run(root, "close", "task:demo/1")
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token.rotate()\n")
    out = _drift(root)
    assert "completion STALE" in out
    assert f"anchor last stamped at {head[:12]}" in out


def test_an_anchor_stamped_before_the_field_existed_says_nothing_about_when(tmp_path: Path):
    """Graceful degradation, and the honest kind: an undated stale line is exactly the one whose age is
    unknown, so it must not guess (every anchor in an existing store predates this)."""
    from yigraf import artifacts

    root = _repo(tmp_path)  # no git repo ⇒ no HEAD ⇒ nothing to stamp, the same shape as an old store
    _run(root, "plan", "demo", "--title", "Demo", "--task", "keep refresh pure")
    _run(root, "link", "task:demo/1", SYM)
    plan = artifacts.read_plan(next((root / "yigraf" / "plans").rglob("*.md")))
    assert plan.tasks[0].implements[0].stamped_at is None

    _run(root, "close", "task:demo/1")
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token.rotate()\n")
    out = _drift(root)
    assert "completion STALE" in out and "anchor last stamped" not in out


def test_commit_evidence_is_resolved_so_a_wrong_citation_is_visible(tmp_path: Path):
    """v4 #16: `commit:` is opaque evidence — immutable, so it never drifts, so nothing downstream ever
    re-examines it, which is why it was the one grounding ref accepted with no feedback at all. yigraf
    cannot date the observation (that lives in the prose), so it shows what the sha resolves to while
    the capture is still cheap to redo."""
    import subprocess

    root = _repo(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm",
                    "add the refresh path"], cwd=root, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          text=True, check=True).stdout.strip()

    out = _run(root, "remember", "refresh was verified by hand", "--grounding", "empirical",
               "--evidence", f"commit:{head}", "--why", "watched it in a live run")
    assert "add the refresh path" in out, "the subject line is what makes a mismatch obvious"
    assert re.search(r"\d{4}-\d{2}-\d{2}", out), "and the date is what a plausibility question asks"


def test_an_unresolvable_commit_citation_is_warned_not_swallowed(tmp_path: Path):
    """A sha from another clone, or a typo. Warned, never refused: evidence is captured as asserted,
    and the point is that nothing else will ever catch it."""
    root = _repo(tmp_path)
    out = _run(root, "remember", "a claim", "--grounding", "empirical",
               "--evidence", "commit:deadbeefcafe", "--why", "cited the wrong clone")
    assert "doesn't resolve to a commit in this repo" in out
    assert re.search(r"mem:[0-9a-f]+", out), "captured anyway"


def test_a_push_packet_leads_with_the_signal_and_a_query_leads_with_the_answer(tmp_path: Path):
    """v4 #13's ordering half. The edit hook speaks unbidden and only because something governs the
    locus or is wrong with it, so the signal IS the message; a topic query asked a question, and there
    the slice is the answer."""
    from yigraf import retrieval
    from yigraf.config import load_config
    from yigraf.extract import build_graph

    root = _repo(tmp_path)
    _run(root, "intent", "purity", "--statement", "refresh SHALL stay pure",
         "--scenario", "Given a token, When refreshed, Then nothing mutates")
    _run(root, "plan", "demo", "--title", "Demo", "--task", "keep refresh pure")
    _run(root, "link", "task:demo/1", "int:purity")
    _run(root, "link", "task:demo/1", SYM)
    _remember(root, "purity is what makes retries safe", "--concerns", SYM, "--why", "callers retry")
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token.rotate()\n")

    config = load_config(root / "yigraf" / "config.yaml")
    graph, _ = build_graph(root, config)

    pushed = retrieval.context_for_locus(graph, "auth/session.py", config, root=root).text
    heads = [ln for ln in pushed.splitlines() if ln and not ln.startswith(" ")]
    assert heads[1].startswith("Proof obligations"), heads[:3]

    pulled = retrieval.context(graph, "refresh token", config, root=root).text
    pulled_heads = [ln for ln in pulled.splitlines() if ln and not ln.startswith(" ")]
    assert not pulled_heads[1].startswith(("Proof obligations", "⚠")), pulled_heads[:3]


def test_amend_inserts_a_marker_the_body_is_missing_rather_than_raising(tmp_path: Path):
    """A marker can be *missing*, not just wrong — and the heading is the case that bites. On a body
    someone hand-edited the `## ` line out of, the new statement landed on the field and not in the
    text, and `_render_body`'s guard then raised: a raw traceback out of a repair verb, which is the
    abandonment design law #1 exists to prevent."""
    root = _repo(tmp_path)
    mem_id = _remember(root, "a claim", "--why", "original")
    path = next(memory.memory_dir(root).glob("*.md"))
    path.write_text(re.sub(r"^## .*\n", "", path.read_text(), count=1, flags=re.M))

    _run(root, "amend", mem_id, "--statement", "a repaired claim")  # asserts exit 0, no traceback
    node = _the_node(root)
    assert node.statement == "a repaired claim"
    assert node.body.splitlines()[0] == "## a repaired claim", "the heading leads, as a capture writes it"
    assert node.why == "original", "and the rest of the record is untouched"

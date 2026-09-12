"""The four findings from the 1.8.0 field feedback (feedback-v6), each pinned by the failure it closes.

Grouped by finding, as in ``test_feedback_v5``. Three of the four are one wrong sentence apiece — which
is exactly why they need tests: the wording moved with zero test movement last time, and a message an
agent acts on is behaviour.
"""
import json
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import DEFAULT_SESSION_PREAMBLE

runner = CliRunner()

DOC = "docs/notes.md"


def _doc_repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    doc = tmp_path / DOC
    doc.parent.mkdir(parents=True)
    doc.write_text("# Notes\n\n## MPPI\n\nSampling params.\n\n"
                   "## Wheel Odometry\n\nA model of the wheels and their slip.\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _capture(root: Path, locus: str, *extra: str):
    args = ["remember", "MPPI tunings are relative.", "--why", "sampling is scale-free",
            "--concerns", locus]
    for more in extra:
        args += ["--concerns", more]
    return runner.invoke(app, args + ["--repo", str(root)])


def _only_memory_id(root: Path) -> str:
    from yigraf import memory
    nodes = memory.iter_memories(root)
    assert len(nodes) == 1
    return nodes[0].id


# ── F#2: the locus reaffirm names the anchor that failed, not the file the caller typed ──────────────

def test_a_gone_section_is_named_instead_of_the_file_that_still_exists(tmp_path: Path):
    """The reported failure: delete a section, `reaffirm file:<doc>` said the FILE no longer resolves —
    a file still on disk, while `drift` named the real anchor in the same store in the same minute.
    D#4 widened the batch so `gone ⊆ {target}` stopped holding, and only the ids survived the loop."""
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}#mppi").exit_code == 0
    mem_id = _only_memory_id(root)
    (root / DOC).write_text("# Notes\n\n## Wheel Odometry\n\nA model of the wheels and their slip.\n")

    result = runner.invoke(app, ["reaffirm", f"file:{DOC}", "--repo", str(root)])

    assert result.exit_code == 0
    assert f"{mem_id} —concerns→ file:{DOC}#mppi" in result.output
    assert f"⚠ file:{DOC} no longer resolves" not in result.output


def test_the_reanchor_handover_is_executable_rather_than_a_placeholder(tmp_path: Path):
    """Following the old handover was refused (wrong old-locus) — one wasted round trip at best, and at
    worst it SUCCEEDED: on a node carrying both anchor forms it replaced the healthy whole-file anchor
    and left the real hard drift standing. The command must name the pair that actually failed."""
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}", f"file:{DOC}#mppi").exit_code == 0
    mem_id = _only_memory_id(root)
    (root / DOC).write_text("# Notes\n\n## Wheel Odometry\n\nA model of the wheels and their slip.\n")

    result = runner.invoke(app, ["reaffirm", f"file:{DOC}", "--repo", str(root)])

    assert f"yigraf reanchor {mem_id} file:{DOC}#mppi <new>" in result.output
    assert f"reanchor {mem_id} file:{DOC} <new>" not in result.output


def test_a_partially_repaired_memory_is_not_reported_as_both_cleared_and_drifting(tmp_path: Path):
    """A memory in both lists printed "drift cleared: mem:x" directly above "⚠ … mem:x". Both lines are
    true of a different anchor, which is precisely why neither alone is readable."""
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}", f"file:{DOC}#mppi").exit_code == 0
    mem_id = _only_memory_id(root)
    (root / DOC).write_text("# Notes\n\n## Wheel Odometry\n\nA model of the wheels and their slip.\n")

    result = runner.invoke(app, ["reaffirm", f"file:{DOC}", "--repo", str(root)])

    assert "partial" in result.output and mem_id in result.output


def test_a_rescued_rename_is_not_called_permanent_hard_drift(tmp_path: Path):
    """The severity to lead with. `drift` and `gc` both report a body-identical heading rename as a
    rescue to settle with `gc --apply`; `reaffirm <file>` called the same state hard drift on the file.
    The rescue EXPIRES — an agent told it is permanent has no reason to settle it while it still can."""
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}#wheel-odometry").exit_code == 0
    mem_id = _only_memory_id(root)
    (root / DOC).write_text("# Notes\n\n## MPPI\n\nSampling params.\n\n"
                            "## Wheel Odometry Model\n\nA model of the wheels and their slip.\n")

    result = runner.invoke(app, ["reaffirm", f"file:{DOC}", "--repo", str(root)])

    assert "RENAMED" in result.output and "gc --apply" in result.output
    assert (f"{mem_id} —concerns→ file:{DOC}#wheel-odometry ⇒ file:{DOC}#wheel-odometry-model"
            in result.output)
    assert "no longer resolve" not in result.output


def test_the_batch_and_drift_agree_about_one_rename(tmp_path: Path):
    """The invariant behind the fix: two surfaces disagreeing about one event is how an agent ends up
    distrusting both. Both must read the same rename map."""
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}#wheel-odometry").exit_code == 0
    (root / DOC).write_text("# Notes\n\n## MPPI\n\nSampling params.\n\n"
                            "## Wheel Odometry Model\n\nA model of the wheels and their slip.\n")

    batch = runner.invoke(app, ["reaffirm", f"file:{DOC}", "--repo", str(root)]).output
    reported = runner.invoke(app, ["drift", str(root)]).output

    moved = f"file:{DOC}#wheel-odometry ⇒ file:{DOC}#wheel-odometry-model"
    assert moved in batch and moved in reported


def test_a_deleted_section_is_not_echoed_as_one_the_file_covers(tmp_path: Path):
    """The echo invites the reading "here are this file's sections", so listing one just deleted
    misleads the same way. It now says what it actually reached; the failures are named below it."""
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}#mppi").exit_code == 0
    (root / DOC).write_text("# Notes\n\n## Wheel Odometry\n\nA model of the wheels and their slip.\n")

    result = runner.invoke(app, ["reaffirm", f"file:{DOC}", "--repo", str(root)])

    assert "section anchor(s) inside it" not in result.output


def test_a_genuinely_deleted_file_still_names_itself(tmp_path: Path):
    """The case the old sentence was right about must not regress: when the whole-file locus IS what is
    gone, the pair names it, because that is the anchor that failed."""
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}").exit_code == 0
    mem_id = _only_memory_id(root)
    (root / DOC).unlink()

    result = runner.invoke(app, ["reaffirm", f"file:{DOC}", "--repo", str(root)])

    assert result.exit_code == 0
    assert f"{mem_id} —concerns→ file:{DOC}" in result.output


# ── F#4: the released placeholder is an un-indexed FILE, never a missing symbol ──────────────────────

def _collectable_doc_anchor(tmp_path: Path) -> Path:
    """The narrow state that prints the line: the only reference to a `file:` locus that RESOLVES and
    that the extractor does not index is held by a memory `gc` is about to archive. The successor is
    re-aimed, because `supersede` inherits `--concerns` by default and would keep the placeholder."""
    root = _doc_repo(tmp_path)
    src = root / "app.py"
    src.write_text("def handle():\n    return 1\n")
    assert _capture(root, f"file:{DOC}").exit_code == 0
    old = _only_memory_id(root)
    assert runner.invoke(app, ["supersede", old, "MPPI tunings are absolute.", "--why", "measured",
                               "--concerns", "sym:app.py#handle", "--repo", str(root)]).exit_code == 0
    return root


def test_the_released_placeholder_is_not_described_as_a_missing_symbol(tmp_path: Path):
    """The old sentence sent the reader looking for a deleted function. Both halves were false in the
    only case that can print it: the node is a `file-anchor`, and its file is still on disk — a locus
    genuinely absent from source mints no node at all, so that case stays SILENT here."""
    root = _collectable_doc_anchor(tmp_path)

    result = runner.invoke(app, ["gc", str(root), "--apply"])

    assert result.exit_code == 0
    assert "placeholder anchor node(s) for un-indexed files" in result.output
    assert "symbols not in the current source" not in result.output


def test_the_release_line_reports_the_drop_the_status_line_will_show(tmp_path: Path):
    """`status.is_symbol` exists so this report and the status line cannot disagree about the number;
    the wording is the only thing that ever did."""
    from yigraf import status
    from yigraf.config import default_config
    from yigraf.extract import build_graph

    root = _collectable_doc_anchor(tmp_path)

    def syms() -> int:
        graph, _ = build_graph(root, default_config())
        return sum(1 for _, a in graph.nodes(data=True)
                   if a.get("family") == "structure" and status.is_symbol(a))

    before = syms()
    result = runner.invoke(app, ["gc", str(root), "--apply"])
    assert f"Also released {before - syms()} placeholder anchor node(s)" in result.output
    assert (root / DOC).exists(), "the line claims the files are untouched — they must be"


# ── F#1: "up to date" is defined identically on every prose surface ─────────────────────────────────

def _up_to_date_sentence(text: str) -> str:
    """The sentence a surface uses to define "up to date", with its wrapping newlines flattened."""
    flat = " ".join(text.split())
    lower = flat.lower()
    start = lower.index("up to date")
    return flat[start:start + 260]


def _prose_surfaces() -> dict[str, str]:
    """Every surface that TEACHES the definition — not every surface that mentions the counts.

    Six copies, and the three that were stale at 1.8.0 are exactly the ones a host with no skill
    reads: Codex gets hooks + AGENTS.md, and a hookless Tier-A host gets the ambient rule and not even
    the preamble. A user cannot repair any of them locally — all three are installer-generated, so a
    local edit forks them silently.

    The sixth is the MCP ``status`` tool description, added by feedback-v7: the field read the F#1
    enumeration, counted five, and pointed out that the docstring a host reads *to decide whether
    calling status answers its question* carries the same sentence and was outside the pin. It is the
    copy most likely to go stale next, for the same reason the other three did — nobody editing
    ``status.py`` has a reason to open it.
    """
    import asyncio

    from yigraf.config import DEFAULT_SESSION_PREAMBLE
    from yigraf.hooks import _AGENTS_BLOCK, _AMBIENT_MCP_RULE, skill_text
    from yigraf.mcp_server import build_server

    skill = skill_text()
    frontmatter, _, body = skill.partition("\n---\n")
    tools = {t.name: t.description or "" for t in asyncio.run(build_server(".").list_tools())}
    return {
        "skill frontmatter (description:)": frontmatter,
        "skill §0b": body,
        "config.DEFAULT_SESSION_PREAMBLE": DEFAULT_SESSION_PREAMBLE,
        "hooks._AGENTS_BLOCK": _AGENTS_BLOCK,
        "hooks._AMBIENT_MCP_RULE": _AMBIENT_MCP_RULE,
        "mcp_server status tool description": tools["status"],
    }


def test_up_to_date_is_defined_identically_on_every_prose_surface():
    """The cheap ask was three words in three files; the test is the actual fix. 1.8.0 shipped green
    with three of five surfaces still teaching a two-count definition, because the only test that could
    have caught it asserted `"rename" in text.lower()` — which the rename BLOCK satisfies whatever the
    preamble says. Pinned against `status.UP_TO_DATE_SIGNALS` so the next signal fails loudly here."""
    from yigraf.status import UP_TO_DATE_SIGNALS

    for name, text in _prose_surfaces().items():
        sentence = _up_to_date_sentence(text)
        missing = [s for s in UP_TO_DATE_SIGNALS if s not in sentence.lower()]
        assert not missing, (
            f'{name} defines "up to date" without {missing}: {sentence!r}. Every surface that teaches '
            f"the definition must enumerate the same signals — a host with no skill reads only these."
        )


def test_the_preamble_predicate_is_false_on_a_line_that_carries_a_rename():
    """Why it is more than a doc nit: `render_line` emits the literal `no drift` at zero and omits the
    `stale` segment entirely at zero, so the OLD two-count predicate evaluated TRUE against the very
    line printed beneath it."""
    from yigraf.config import DEFAULT_SESSION_PREAMBLE
    from yigraf.status import StatusSummary

    line = StatusSummary(symbols=1, intents=0, plans=1, tasks_total=1, tasks_open=0, decisions=0,
                         drifting=0, stale=0, renames=1, freshness="fresh", semantic=1, embedded=1,
                         head=None).render_line()

    assert "no drift" in line and "stale" not in line and "⚠ 1 rename" in line
    assert "no unsettled rename" in " ".join(DEFAULT_SESSION_PREAMBLE.split())


def _downgrade_preamble(root: Path) -> Path:
    """Make the repo's committed config.yaml look like one an `init` through 1.10.0 wrote: a LIVE
    `preamble:` block carrying the text 1.8.0 shipped.

    Since 1.11.0 a fresh `init` writes the block commented out, so the fixture has to uncomment it —
    which is exactly the byte-level round trip `commented_preamble_block` promises — and then swap the
    text for the superseded one. Uncommenting here is what makes this a faithful reproduction of a
    pre-1.11 file rather than an approximation of one.
    """
    from yigraf.config import (DEFAULT_SESSION_PREAMBLE, SUPERSEDED_SESSION_PREAMBLES,
                               commented_preamble_block)

    def spliced(text: str) -> str:
        return "\n".join(f"    {line}".rstrip() for line in text.rstrip("\n").splitlines())

    cfg = root / "yigraf" / "config.yaml"
    text = cfg.read_text()
    assert commented_preamble_block() in text, "init should ship the preamble commented out"
    text = text.replace(commented_preamble_block(),
                        f"  preamble: |\n{spliced(SUPERSEDED_SESSION_PREAMBLES[0])}")
    assert spliced(DEFAULT_SESSION_PREAMBLE) not in text
    cfg.write_text(text)
    return cfg


def test_an_already_initialized_repo_is_told_its_committed_preamble_is_stale(tmp_path: Path):
    """The hazard we would not have guessed: `init` splices the preamble into the repo's COMMITTED
    config.yaml and the file value wins, so amending the default reaches no existing repo — including
    this one. `skill_behind` exists for exactly this, one file over."""
    from yigraf.config import load_config, preamble_behind

    root = _doc_repo(tmp_path)
    cfg = _downgrade_preamble(root)
    assert preamble_behind(cfg), "the fixture must actually carry the older default"

    assert "⬆ preamble" in runner.invoke(app, ["status", "--repo", str(root)]).output


def test_a_rewritten_preamble_is_never_nudged(tmp_path: Path):
    """"Yours to rewrite" is the whole point of the file being committed. Only a byte-exact older
    default earns the nudge — the same discipline `installed_skill_version` applies to an unstamped
    skill, and for the same reason: a false alarm here teaches people to ignore the real one."""
    from yigraf.config import load_config, preamble_behind

    root = _doc_repo(tmp_path)
    cfg = _downgrade_preamble(root)
    cfg.write_text(cfg.read_text().replace("[yigraf] Standing rules for this session",
                                           "[acme] House rules for this session"))

    assert not preamble_behind(cfg)
    assert "preamble" not in runner.invoke(app, ["status", "--repo", str(root)]).output


def test_a_current_preamble_is_silent(tmp_path: Path):
    root = _doc_repo(tmp_path)
    assert "preamble" not in runner.invoke(app, ["status", "--repo", str(root)]).output


def test_the_current_preamble_is_printable_so_the_nudge_can_be_followed(tmp_path: Path):
    """Guidance that names no way to get the replacement text is guidance that cannot be followed."""
    from yigraf.config import DEFAULT_SESSION_PREAMBLE

    result = runner.invoke(app, ["cheatsheet", "--preamble"])

    assert result.exit_code == 0
    assert result.output.strip() == DEFAULT_SESSION_PREAMBLE.strip()


# ── F#3: the gate sentence says what the exit code actually covers ──────────────────────────────────

def _renamed_heading_repo(tmp_path: Path) -> Path:
    root = _doc_repo(tmp_path)
    assert _capture(root, f"file:{DOC}#wheel-odometry").exit_code == 0
    (root / DOC).write_text("# Notes\n\n## MPPI\n\nSampling params.\n\n"
                            "## Wheel Odometry Model\n\nA model of the wheels and their slip.\n")
    return root


def test_drift_exits_zero_on_a_rename_only_state(tmp_path: Path):
    """Pinned as the behaviour it is, not as a bug: settling a rename REWRITES committed artifacts, so
    gating on it would demand a mutate-restage-recommit cycle on every rename — which is how a
    pre-commit hook gets `--no-verify`d. What was missing is the sentence saying so."""
    root = _renamed_heading_repo(tmp_path)

    result = runner.invoke(app, ["drift", str(root)])

    assert result.exit_code == 0 and "⇒" in result.output


def test_the_gate_sentence_names_what_the_exit_code_lets_through():
    """`drift --help` uses "drift" in the wider sense that INCLUDES renames, so a reader who has just
    run it reads the §4 parenthetical against that sense — and the signal let through is the one §0b
    says to settle first, at the last boundary before the edit that ends the rescue."""
    from yigraf.hooks import skill_text

    gate = skill_text()[skill_text().index("exits non-zero on"):][:520]

    assert "soft/hard drift only" in gate
    assert "rename" in gate and "stale" in gate and "status --json" in gate


def test_the_status_json_gate_the_skill_hands_over_actually_refuses(tmp_path: Path):
    """The ask cost nothing because the remedy already existed — but only if it works. A gate on
    `status --json` must refuse the rename-only state and pass once it is settled."""
    import json as _json

    root = _renamed_heading_repo(tmp_path)

    def counts() -> dict:
        out = runner.invoke(app, ["status", "--repo", str(root), "--json"]).output
        return _json.loads(out)

    before = counts()
    assert before["renames"] == 1 and before["drifting"] == 0
    assert runner.invoke(app, ["gc", str(root), "--apply"]).exit_code == 0
    assert counts()["renames"] == 0


def test_the_mcp_status_docstring_enumerates_every_signal_the_line_carries():
    """That docstring is what an MCP host reads to decide whether calling `status` answers its
    question, and it went out of its way to explain `sem` — so the enumeration read as complete while
    rename, stale and conflict rode along unnamed. Read from source (`ast`), because the tool bodies
    are nested inside `build_server` and the [mcp] extra is optional."""
    import ast

    from yigraf import mcp_server, status

    tree = ast.parse(Path(mcp_server.__file__).read_text(encoding="utf-8"))
    doc = next(ast.get_docstring(n) for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "status")

    for signal in (*status.UP_TO_DATE_SIGNALS, "conflict"):
        assert signal in doc, f"the MCP status docstring does not name {signal}"


# ── §8: the two "neither a finding" items — a path where a slug belongs, and rename on `show` ────────

def test_a_path_where_a_plan_slug_belongs_is_not_answered_as_an_empty_plan(tmp_path: Path):
    """`yigraf drift .` means *this repo*; `yigraf tasks .` meant *the plan named "."* and said
    `No plan .. Known: …` at exit 0 — a plausible "nothing outstanding" on the one surface an agent
    asks what is left, where `yigraf status .` refuses at exit 2. It must name the convention."""
    root = _doc_repo(tmp_path)
    assert runner.invoke(app, ["plan", "m1", "-t", "M1", "--task", "ship it",
                               "--repo", str(root)]).exit_code == 0

    result = runner.invoke(app, ["tasks", ".", "--repo", str(root)])

    assert result.exit_code == 0  # still guidance, never a stack trace (design law #1)
    assert "is a path, not a plan slug" in result.output
    assert "--repo" in result.output
    assert "No plan" not in result.output


def test_the_path_guidance_does_not_recite_the_plan_inventory(tmp_path: Path):
    """The mistake is the calling convention, not the name, so the "Known: …" tail an unknown *slug*
    earns would spend the agent's budget answering a question it is not asking (design law #2)."""
    root = _doc_repo(tmp_path)
    assert runner.invoke(app, ["plan", "m1", "-t", "M1", "--repo", str(root)]).exit_code == 0

    assert "m1" not in runner.invoke(app, ["tasks", ".", "--repo", str(root)]).output
    assert "m1" in runner.invoke(app, ["tasks", "nope", "--repo", str(root)]).output  # the other case


def test_a_path_shaped_slug_cannot_write_outside_the_workspace(tmp_path: Path):
    """`plan <slug>` composed straight into `workspace / "plans" / "active" / f"{slug}.md"`, so a
    separator escaped the workspace entirely. Same wording as the read verb — it is one mistake."""
    root = _doc_repo(tmp_path)

    result = runner.invoke(app, ["plan", "../../escaped", "-t", "T", "--repo", str(root)])

    assert result.exit_code == 0 and "is a path, not a plan slug" in result.output
    assert not list(tmp_path.parent.glob("escaped.md")) and not (tmp_path / "escaped.md").exists()


def test_an_ordinary_slug_is_untouched_by_the_guard(tmp_path: Path):
    """The guard must cost nothing on the calling convention that was always right."""
    root = _doc_repo(tmp_path)
    assert runner.invoke(app, ["plan", "auth-rewrite", "-t", "T", "--task", "a",
                               "--repo", str(root)]).exit_code == 0
    assert runner.invoke(app, ["intent", "drift-detection", "-s", "SHALL x",
                               "--repo", str(root)]).exit_code == 0

    out = runner.invoke(app, ["tasks", "auth-rewrite", "--repo", str(root)]).output
    assert "task:auth-rewrite/1" in out and "is a path" not in out


def test_show_does_not_call_a_rescued_rename_permanent_hard_drift(tmp_path: Path):
    """`show` reads the ARTIFACT, which still names the locator the subject left — so the anchor line
    looked it up, missed, and printed "hard drift — the locus is gone" about a move `drift` called
    settleable in the same minute. The same false sentence F#2 removed from `reaffirm`, on the surface
    an agent lands on holding an id from a drift line."""
    root = _renamed_heading_repo(tmp_path)
    mem_id = _only_memory_id(root)

    result = runner.invoke(app, ["show", mem_id, "--repo", str(root)])

    assert result.exit_code == 0
    # Not a bare "hard drift" search: the cliff footer says the words, describing what happens if the
    # rename is NOT settled. What must be gone is the verdict on the anchor line.
    assert "hard drift — the locus is gone" not in result.output
    assert f"renamed ⇒ file:{DOC}#wheel-odometry-model" in result.output


def test_show_names_the_expiring_signal_and_the_verb_that_settles_it(tmp_path: Path):
    """`show.py`'s drift list excludes renames — right, since a rename is not drift — but that left
    `show` the one agent-reachable surface never mentioning the only signal with an expiry. The block
    must carry the cliff, or it reads as bookkeeping that can wait past the edit that destroys it."""
    from yigraf.retrieval import RENAME_CLIFF

    root = _renamed_heading_repo(tmp_path)
    mem_id = _only_memory_id(root)

    out = runner.invoke(app, ["show", mem_id, "--repo", str(root)]).output

    assert "⚠ Unsettled rename (1)" in out
    assert RENAME_CLIFF in out


def test_the_verb_show_hands_over_actually_settles_the_rename(tmp_path: Path):
    """Executable, not a placeholder — the F#2 lesson applied to the new surface: run exactly what the
    block printed and the node comes back clean."""
    root = _renamed_heading_repo(tmp_path)
    mem_id = _only_memory_id(root)
    handed = [line for line in
              runner.invoke(app, ["show", mem_id, "--repo", str(root)]).output.splitlines()
              if "`yigraf reanchor " in line]
    assert len(handed) == 1
    command = handed[0].split("`")[1].split()[1:]  # drop the `yigraf` the agent would type

    assert runner.invoke(app, command + ["--repo", str(root)]).exit_code == 0

    after = runner.invoke(app, ["show", mem_id, "--repo", str(root)]).output
    assert "Unsettled rename" not in after and "⚠" not in after
    status = json.loads(runner.invoke(app, ["status", "--repo", str(root), "--json"]).output)
    assert status["renames"] == 0


def test_a_renamed_implements_edge_is_settled_by_link_not_reanchor(tmp_path: Path):
    """The relation fork `_rename_line` already made, now shared with `show` through `rename_verb`:
    a task's declaration is rewritten by re-`link`ing, never by `reanchor` (which takes a memory)."""
    root = _doc_repo(tmp_path)
    (root / "app.py").write_text("def compute_score(x):\n    total = 0\n"
                                 "    for i in x:\n        total += i * 2\n    return total\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    assert runner.invoke(app, ["plan", "scoring", "-t", "S", "--task", "score",
                               "--repo", str(root)]).exit_code == 0
    assert runner.invoke(app, ["link", "task:scoring/1", "sym:app.py#compute_score",
                               "--repo", str(root)]).exit_code == 0
    (root / "app.py").write_text("def compute_rating(x):\n    total = 0\n"
                                 "    for i in x:\n        total += i * 2\n    return total\n")

    out = runner.invoke(app, ["show", "task:scoring/1", "--repo", str(root)]).output

    assert "`yigraf link task:scoring/1 sym:app.py#compute_rating`" in out
    assert "reanchor" not in out


# ── §7: the whole-file anchor OFFER — the measured null answered by dissolving the blocker ──────────

def _bigger_doc(root: Path) -> Path:
    (root / DOC).write_text(
        "# Robot Notes\n\nGeneral reference.\n\n"
        "## MPPI\n\nSampling params control the rollout horizon.\n\n"
        "## Wheel Odometry\n\nA model of the wheels and their slip on gravel.\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    return root


def _remember(root: Path, statement: str, *args: str):
    return runner.invoke(app, ["remember", statement, "--why", "measured it",
                               *args, "--repo", str(root)])


def test_a_whole_file_anchor_is_offered_the_section_that_reads_like_its_subject(tmp_path: Path):
    """§7's recommendation, and the only form their population supports: their mechanical version named
    a plausible home for 19 of 25 mis-anchored items. An offer, at the moment the anchor is chosen."""
    root = _bigger_doc(_doc_repo(tmp_path))

    result = _remember(root, "MPPI rollout horizon tunings are relative.", "--concerns", f"file:{DOC}")

    assert result.exit_code == 0
    assert "#mppi reads like this claim's subject" in result.output
    assert "yigraf reanchor mem:" in result.output and f"file:{DOC}#mppi`" in result.output


def test_the_offer_is_not_a_warning(tmp_path: Path):
    """The whole point. A warning fires on the right case too — unconditional is right two times in
    three — so it trains the reader to ignore a ⚠. An offer costs one line and leaves nothing behind:
    the anchor it names is the one already captured, and nothing is drifting or unsettled."""
    import json as _json

    root = _bigger_doc(_doc_repo(tmp_path))

    out = _remember(root, "MPPI rollout horizon tunings are relative.",
                    "--concerns", f"file:{DOC}").output

    assert "⚠" not in out
    state = _json.loads(runner.invoke(app, ["status", "--repo", str(root), "--json"]).output)
    assert state["drifting"] == 0 and state["renames"] == 0


def test_the_offered_reanchor_is_executable(tmp_path: Path):
    """Run exactly what was printed — the F#2 lesson, applied to a new handover."""
    root = _bigger_doc(_doc_repo(tmp_path))
    out = _remember(root, "MPPI rollout horizon tunings are relative.",
                    "--concerns", f"file:{DOC}").output
    printed = next(line for line in out.splitlines() if "`yigraf reanchor " in line)
    command = printed.split("`")[1].split()[1:]

    assert runner.invoke(app, command + ["--repo", str(root)]).exit_code == 0

    mem_id = _only_memory_id(root)
    shown = runner.invoke(app, ["show", mem_id, "--repo", str(root)]).output
    assert f"concerns      file:{DOC}#mppi" in shown


def test_a_claim_about_the_whole_document_is_offered_nothing(tmp_path: Path):
    """Silence is the default (design law #4). The document-spanning `# Robot Notes` heading is
    anchorable but is not a *narrowing* — offering it would hand back the same locus."""
    root = _bigger_doc(_doc_repo(tmp_path))

    out = _remember(root, "These notes are the shared reference for the team.",
                    "--concerns", f"file:{DOC}").output

    assert "Offer" not in out


def test_a_claim_the_document_says_in_two_places_is_offered_nothing(tmp_path: Path):
    """A near-tie means naming one of the two is arbitrary, and an arbitrary suggestion is the thing
    that teaches a reader to stop reading them. The margin is set for legibility, not recall."""
    root = _bigger_doc(_doc_repo(tmp_path))

    out = _remember(root, "The rollout horizon and the wheel slip interact.",
                    "--concerns", f"file:{DOC}").output

    assert "Offer" not in out


def test_a_document_with_no_addressable_subdivision_is_offered_nothing(tmp_path: Path):
    """§7's one required exemption, and it falls out rather than being special-cased: their
    `coding-conventions.md` is numbered principles under one title — a list, not headings — so
    whole-file is genuinely the only anchor it has."""
    root = _doc_repo(tmp_path)
    (root / DOC).write_text("# Conventions\n\n1. name things well\n2. keep functions small\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0

    out = _remember(root, "Naming things well is the convention that matters most.",
                    "--concerns", f"file:{DOC}").output

    assert "Offer" not in out


def test_a_policy_anchor_is_never_offered_a_section(tmp_path: Path):
    """`--governs` names the file whose USE the policy governs. Narrowing it would change what the
    policy covers — a different claim, not a better anchor for the same one."""
    root = _bigger_doc(_doc_repo(tmp_path))

    out = _remember(root, "MPPI rollout horizon notes belong in this file only.",
                    "--governs", f"file:{DOC}").output

    assert "Offer" not in out


def test_an_anchor_that_is_already_a_section_is_offered_nothing(tmp_path: Path):
    """Nor a line range — that is addressed by position, which no heading can name."""
    root = _bigger_doc(_doc_repo(tmp_path))

    assert "Offer" not in _remember(root, "MPPI rollout horizon tunings are relative.",
                                    "--concerns", f"file:{DOC}#mppi").output
    assert "Offer" not in _remember(root, "MPPI rollout horizon tunings are relative to sampling.",
                                    "--concerns", f"file:{DOC}:L5-L7").output


def test_the_offer_can_be_switched_off(tmp_path: Path):
    """A repo whose docs are deliberately anchored whole-file should be able to say so once."""
    root = _bigger_doc(_doc_repo(tmp_path))
    cfg = root / "yigraf" / "config.yaml"
    cfg.write_text(cfg.read_text().replace("section_offer_margin: 2.0", "section_offer_margin: 0"))

    out = _remember(root, "MPPI rollout horizon tunings are relative.",
                    "--concerns", f"file:{DOC}").output

    assert "Offer" not in out


def test_an_ambiguous_slug_is_never_offered(tmp_path: Path):
    """`cli._anchor` refuses a duplicate `#slug` outright, so offering one would hand over a command
    that cannot run — the placeholder-handover failure F#2 closed, re-opened on a new surface."""
    root = _doc_repo(tmp_path)
    (root / DOC).write_text("# Robot Notes\n\nGeneral.\n\n## MPPI\n\nSampling params.\n\n"
                            "## MPPI\n\nMore sampling params for the rollout horizon.\n\n"
                            "## Odometry\n\nWheels.\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0

    out = _remember(root, "MPPI sampling params control the rollout horizon.",
                    "--concerns", f"file:{DOC}").output

    assert "#mppi" not in out

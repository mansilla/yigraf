"""`yigraf show` — the unbudgeted read-by-id that closes the loop every warning opens.

Every other read surface answers "what is relevant to X?" under a budget. This one answers "what does
*this* say?". It exists because the tool kept handing the agent ids — in drift lines, conflict lines,
and now the SessionStart manifest — with no verb that took one; `context "mem:<id>"` semantic-searches
the literal hex and returns proximity noise under a banner, which is worse than a refusal.
"""
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"
LONG_WHY = ("the measured p99 was 840ms against a 200ms budget, and every cheaper remedy was ruled "
            "out by measurement: a bigger pool moved it 4ms, a read replica moved it 11ms, and "
            "raising the timeout only hid it " + "— detail " * 40)


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["intent", "session-expiry", "--repo", str(tmp_path),
                               "-s", "The system SHALL expire a session after 30m idle."]).exit_code == 0
    return tmp_path


def _remember(root: Path, statement: str, **flags) -> str:
    args = ["remember", statement, "--repo", str(root)]
    for key, values in flags.items():
        for value in (values if isinstance(values, list) else [values]):
            args += [f"--{key.replace('_', '-')}", value]
    out = runner.invoke(app, args)
    assert out.exit_code == 0, out.output
    return out.output.split("Captured ")[1].split(" ")[0]


def test_show_prints_the_whole_why_untruncated(tmp_path: Path):
    """Nothing here is budgeted: the long `--why` IS what the caller came for.

    Retrieval truncates because it is paying for a slice out of a window. A read-by-id is not a slice,
    and the reasoning is exactly the content `/clear` destroys and the node exists to survive it with.
    """
    root = _repo(tmp_path)
    mem_id = _remember(root, "cache the session lookup", why=LONG_WHY, concerns=SYM)
    out = runner.invoke(app, ["show", mem_id, "--repo", str(root)])
    assert out.exit_code == 0
    # Wrapping inserts newlines, so compare on collapsed whitespace, not the literal string.
    assert " ".join(LONG_WHY.split()) in " ".join(out.output.split())


def test_show_names_which_anchor_list_drifted(tmp_path: Path):
    """A memory can carry the same symbol under `concerns` and under `evidence`, cleared by different
    calls — so "this node is drifting" is not actionable; naming the relation is."""
    root = _repo(tmp_path)
    mem_id = _remember(root, "refresh must not renew past the absolute cap",
                       why="otherwise a stolen token lives forever", concerns=SYM,
                       grounding="empirical", evidence=SYM)
    (root / "auth" / "session.py").write_text("def refresh(token):\n    return token + 1\n")
    assert runner.invoke(app, ["build", str(root)]).exit_code == 0
    out = runner.invoke(app, ["show", mem_id, "--repo", str(root)]).output
    assert "concerns" in out and "grounded_by" in out
    assert "the evidence grounding this ·empirical belief" in out  # the grounded_by advice, verbatim
    assert "`reaffirm" in out  # ids pre-filled, same wording the hook and `yigraf drift` carry


def test_show_resolves_a_bare_hash_prefix(tmp_path: Path):
    """Ids are 16 hex characters nobody retypes correctly, and a caller may be copying a truncated one."""
    root = _repo(tmp_path)
    mem_id = _remember(root, "a decision worth finding", why="because")
    out = runner.invoke(app, ["show", mem_id[len("mem:"):][:8], "--repo", str(root)])
    assert out.exit_code == 0 and mem_id in out.output


def test_show_lists_candidates_rather_than_guessing(tmp_path: Path):
    """The never-guess rule `resolve_renames` applies to an ambiguous rename, applied to an id."""
    root = _repo(tmp_path)
    _remember(root, "first decision", why="a")
    _remember(root, "second decision", why="b")
    out = runner.invoke(app, ["show", "mem:", "--repo", str(root)])
    assert out.exit_code == 0  # guidance, never a stack trace (design law #1)
    assert "matches" in out.output and out.output.count("mem:") >= 3


def test_show_teaches_the_way_back_when_the_id_is_unknown(tmp_path: Path):
    root = _repo(tmp_path)
    out = runner.invoke(app, ["show", "mem:deadbeefdeadbeef", "--repo", str(root)])
    assert out.exit_code == 0
    assert "yigraf context" in out.output and "yigraf drift" in out.output


def test_show_reads_an_intent_and_a_symbol_too(tmp_path: Path):
    """Every family the warnings can name, `show` can read — otherwise the loop is only half closed."""
    root = _repo(tmp_path)
    _remember(root, "sessions expire on idle", why="renewal must stay possible", concerns=SYM,
              serves="int:session-expiry")
    intent = runner.invoke(app, ["show", "int:session-expiry", "--repo", str(root)]).output
    assert "SHALL expire a session" in intent
    assert "Referenced by:" in intent and "serves" in intent  # what points AT it — no frontmatter has this
    symbol = runner.invoke(app, ["show", SYM, "--repo", str(root)]).output
    assert "auth/session.py" in symbol and "concerns" in symbol  # what governs this code


def test_context_redirects_an_id_to_show(tmp_path: Path):
    """`context` searches by meaning and has no way to match an id except by accident.

    Handed one it used to return whichever nodes sat nearest in embedding space under a low-confidence
    banner — an answer-shaped non-answer. Every drift line now pre-fills an id, so this is precisely
    the query an agent makes right after being told what to act on.
    """
    root = _repo(tmp_path)
    mem_id = _remember(root, "a decision an agent will be handed by id", why="drift will name it")
    out = runner.invoke(app, ["context", mem_id, "--repo", str(root)])
    assert out.exit_code == 0  # exit 0 + guidance, so the agent retries instead of abandoning the tool
    assert f"yigraf show {mem_id}" in out.output
    assert "Context for" not in out.output  # it did not fall through to a semantic search


def test_a_topic_that_merely_starts_with_a_prefix_is_still_a_topic(tmp_path: Path):
    """`file: handling in the extractor` is a question. Whitespace is what separates the two cases."""
    root = _repo(tmp_path)
    out = runner.invoke(app, ["context", "file: anchors and how they drift", "--repo", str(root)])
    assert out.exit_code == 0 and "Context for" in out.output

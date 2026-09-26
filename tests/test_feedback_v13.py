"""The field's tenth report: the embeddings index read as half of two saves, intent case collisions, and
two strings from the fifth send.

M#1 is a concurrency defect, so — as in the v12 file — its test runs real **processes**: a writer
alternating two index sizes and a reader counting ``load_index`` misses while both files exist. The
field measured ~1 torn pair per capture, all a matrix one row ahead of its entry list, and an atomic write
of each file alone did not close it; only a lock over the pair on both sides does.

M#2 bites only on a case-sensitive volume. The tests are written so they pass on either kind but fail
the old code on one (Linux CI is case-sensitive): one file per id, and the refusal names the real file.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
from typer.testing import CliRunner

from yigraf import embeddings, memory
from yigraf.cli import app

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    return tmp_path


# --- M#1: the embeddings index is a pair --------------------------------------------------------------

_WRITER = textwrap.dedent("""
    import sys, numpy as np
    from pathlib import Path
    from yigraf import embeddings
    root, rounds = Path(sys.argv[1]), int(sys.argv[2])
    for i in range(rounds):
        n = 3 + i % 2  # alternate sizes, so any mix of two saves is a shape mismatch
        ids = [f"mem:{k:03d}" for k in range(n)]
        embeddings._save_index(root, "test-model", ids, np.ones((n, 4), dtype="float32"),
                               {x: "h" for x in ids})
    (root / "done").touch()
""")

_READER = textwrap.dedent("""
    import sys
    from pathlib import Path
    from yigraf import embeddings
    from yigraf.config import default_config
    root = Path(sys.argv[1]); cfg = default_config(); cfg["embeddings"]["model"] = "test-model"
    d = embeddings.index_dir(root); reads = torn = 0
    while not (root / "done").exists():
        reads += 1
        if embeddings.load_index(root, cfg) is None and (d / "meta.json").exists() and (d / "vectors.npy").exists():
            torn += 1
    print(reads, torn)
""")


def test_a_reader_never_sees_one_saves_matrix_with_anothers_entries(tmp_path: Path):
    """`load_index` returned None — "no index" to `status`, `context` and the near-duplicate guard —
    whenever it landed between `_save_index`'s two writes."""
    root = _repo(tmp_path)
    embeddings._save_index(root, "test-model", ["mem:000"], np.ones((1, 4), dtype="float32"), {})
    reader = subprocess.Popen([sys.executable, "-c", _READER, str(root)], stdout=subprocess.PIPE, text=True)
    subprocess.run([sys.executable, "-c", _WRITER, str(root), "400"], check=True)
    reads, torn = map(int, reader.communicate(timeout=60)[0].split())

    assert reads > 0 and torn == 0, f"{torn} torn reads of {reads}"


def test_the_index_save_leaves_no_temp_file(tmp_path: Path):
    root = _repo(tmp_path)
    embeddings._save_index(root, "test-model", ["mem:001"], np.ones((1, 4), dtype="float32"), {})
    names = {p.name for p in embeddings.index_dir(root).iterdir()}
    assert {"vectors.npy", "meta.json"} <= names and not any(".tmp" in n for n in names)


# --- M#2 (G#6): a case variant of an existing intent ------------------------------------------------

def _intent_files(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "yigraf" / "intents").glob("*.md"))


def test_a_case_variant_of_an_existing_intent_is_refused_and_names_the_real_file(tmp_path: Path):
    """On a case-sensitive volume `intent Bravo` beside bravo.md wrote a second `int:bravo`, and the
    fold kept whichever file's content hash sorted last."""
    root = _repo(tmp_path)
    assert runner.invoke(app, ["intent", "bravo", "-s", "The system SHALL bravo.", "--repo", str(root)]).exit_code == 0

    result = runner.invoke(app, ["intent", "Bravo", "-s", "The system SHALL Bravo.", "--repo", str(root)])

    assert result.exit_code == 0 and "already exists" in result.output and "bravo.md" in result.output
    assert _intent_files(root) == ["bravo.md"]


def test_a_status_update_through_a_case_variant_finds_the_intent(tmp_path: Path):
    """The loud false negative on a case-sensitive volume: "No intent int:bravo yet"."""
    root = _repo(tmp_path)
    runner.invoke(app, ["intent", "bravo", "-s", "The system SHALL bravo.", "--repo", str(root)])

    result = runner.invoke(app, ["intent", "BRAVO", "--status", "active", "--repo", str(root)])

    assert result.exit_code == 0 and "Updated intent int:bravo" in result.output
    assert "status: active" in (root / "yigraf" / "intents" / "bravo.md").read_text()


def test_two_supersedes_onto_case_variants_do_not_merge_into_one_node(tmp_path: Path):
    """`supersede-intent charlie delta` then `supersede-intent echo Delta` left two files declaring
    `int:delta`, folded into one node with one contract and BOTH `supersedes` edges."""
    root = _repo(tmp_path)
    for slug in ("charlie", "echo"):
        runner.invoke(app, ["intent", slug, "-s", f"The system SHALL {slug}.", "--repo", str(root)])
    assert runner.invoke(app, ["supersede-intent", "charlie", "delta", "-s", "The system SHALL delta.",
                               "--repo", str(root)]).exit_code == 0

    result = runner.invoke(app, ["supersede-intent", "echo", "Delta", "-s", "The system SHALL Delta.",
                                 "--repo", str(root)])

    assert result.exit_code == 0 and "already exists" in result.output and "delta.md" in result.output
    assert _intent_files(root) == ["charlie.md", "delta.md", "echo.md"]
    assert "status: proposed" in (root / "yigraf" / "intents" / "echo.md").read_text()  # not archived


def test_an_intent_cannot_supersede_its_own_case_variant(tmp_path: Path):
    root = _repo(tmp_path)
    runner.invoke(app, ["intent", "bravo", "-s", "The system SHALL bravo.", "--repo", str(root)])

    result = runner.invoke(app, ["supersede-intent", "bravo", "Bravo", "-s", "The system SHALL Bravo.",
                                 "--repo", str(root)])

    assert result.exit_code == 0 and "can't supersede itself" in result.output
    assert _intent_files(root) == ["bravo.md"]
    assert "archived" not in (root / "yigraf" / "intents" / "bravo.md").read_text()


# --- §D: G#12 and G#5 from the fifth send -----------------------------------------------------------

def test_an_empty_tasks_slug_is_named_even_outside_a_repo(tmp_path: Path):
    """The workspace error came first, so the caller never learned the slug was the mistake; and the
    message said "writes nothing" on a verb that only reads, pointing at `--repo` for the bare form."""
    result = runner.invoke(app, ["tasks", "", "--repo", str(tmp_path)])  # no workspace here

    assert result.exit_code == 0 and "An empty slug" in result.output
    assert "writes nothing" not in result.output and "bare `yigraf tasks`" in result.output


def test_reanchoring_an_anchor_onto_itself_is_refused_and_keeps_it(tmp_path: Path):
    """`reanchor X X` dropped the anchor — "already there" — and show/status/drift said nothing after."""
    root = _repo(tmp_path)
    (root / "mod.py").write_text("def widget():\n    return 1\n")
    runner.invoke(app, ["build", str(root)])
    runner.invoke(app, ["remember", "widget returns one", "--why", "measured it",
                        "--concerns", "sym:mod.py#widget", "--repo", str(root)])
    (node,) = memory.iter_memories(root)

    result = runner.invoke(app, ["reanchor", node.id, "sym:mod.py#widget", "sym:mod.py#widget",
                                 "--repo", str(root)])

    assert result.exit_code == 0 and "nothing to move" in result.output and "Dropped" not in result.output
    (after,) = memory.iter_memories(root)
    assert [c.sym for c in after.concerns] == ["sym:mod.py#widget"]

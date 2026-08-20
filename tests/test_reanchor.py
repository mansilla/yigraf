"""`reanchor` — the locus-repair verb — and `unlink` reaching a mis-declared concern (feedback-v3 #2).

Four nodes in the field's store carry a body whose entire content is "LOCUS REPAIR ONLY — see the node
this supersedes for the argument": each a false mind-change filed to fix an anchor. And retiring a
mis-captured concern required hand-editing frontmatter, because `unlink` reached only `grounded_by`
while its refusal read as "this memory has no such anchor".
"""
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf import memory
from yigraf.cli import app

runner = CliRunner()

OLD_SYM = "sym:auth/session.py#refresh"
NEW_SYM = "sym:auth/session.py#expire"


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n\n\ndef expire(token):\n    return None\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _remember(root: Path, statement: str, *extra: str) -> str:
    result = runner.invoke(app, ["remember", statement, "--repo", str(root), *extra])
    assert result.exit_code == 0, result.output
    return re.search(r"mem:[0-9a-f]+", result.output).group(0)


def _mem(root: Path, mem_id: str) -> memory.Memory:
    return memory.read_memory(memory.find_memory(root, mem_id))


def test_reanchor_moves_a_concern_with_no_supersede(tmp_path: Path):
    root = _repo(tmp_path)
    mem_id = _remember(root, "The idle bound is enforced here.", "--concerns", OLD_SYM)
    result = runner.invoke(app, ["reanchor", mem_id, OLD_SYM, NEW_SYM, "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "no supersede recorded" in result.output
    node = _mem(root, mem_id)
    assert [c.sym for c in node.concerns] == [NEW_SYM]
    assert node.concerns[0].anchor is not None            # freshly stamped at the new locus
    assert node.status == "active" and not node.supersedes  # the claim and its history untouched


def test_reanchor_moves_a_grounded_by_ref_too(tmp_path: Path):
    root = _repo(tmp_path)
    mem_id = _remember(root, "Confirmed by the refresh path.", "--grounding", "empirical",
                       "--evidence", OLD_SYM)
    result = runner.invoke(app, ["reanchor", mem_id, OLD_SYM, NEW_SYM, "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "grounded_by" in result.output
    assert [e.ref for e in _mem(root, mem_id).evidence] == [NEW_SYM]


def test_reanchor_refuses_a_locus_that_does_not_exist(tmp_path: Path):
    """A repair points at real code — a dangling 'repair' trades one hard drift for another."""
    root = _repo(tmp_path)
    mem_id = _remember(root, "The idle bound is enforced here.", "--concerns", OLD_SYM)
    result = runner.invoke(app, ["reanchor", mem_id, OLD_SYM, "sym:auth/session.py#nope",
                                 "--repo", str(root)])
    assert result.exit_code == 0
    assert "doesn't resolve" in result.output
    assert [c.sym for c in _mem(root, mem_id).concerns] == [OLD_SYM]  # nothing moved


def test_reanchor_refusal_names_the_anchors_the_node_carries(tmp_path: Path):
    root = _repo(tmp_path)
    mem_id = _remember(root, "The idle bound is enforced here.", "--concerns", OLD_SYM)
    result = runner.invoke(app, ["reanchor", mem_id, NEW_SYM, OLD_SYM, "--repo", str(root)])
    assert result.exit_code == 0
    assert "nothing to move" in result.output and OLD_SYM in result.output  # what it DOES carry


def test_unlink_retires_a_mis_declared_concern(tmp_path: Path):
    root = _repo(tmp_path)
    mem_id = _remember(root, "The idle bound is enforced here.",
                       "--concerns", OLD_SYM, "--concerns", NEW_SYM)
    result = runner.invoke(app, ["unlink", mem_id, NEW_SYM, "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert f"Unlinked {mem_id} —concerns→ {NEW_SYM}" in result.output
    assert [c.sym for c in _mem(root, mem_id).concerns] == [OLD_SYM]


def test_unlink_warns_when_the_last_concern_goes(tmp_path: Path):
    """Dropping the only anchor drops the edit-hook surfacing with it — say so, don't just succeed."""
    root = _repo(tmp_path)
    mem_id = _remember(root, "The idle bound is enforced here.", "--concerns", OLD_SYM)
    result = runner.invoke(app, ["unlink", mem_id, OLD_SYM, "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "now concerns nothing" in result.output


def test_unlink_refusal_names_both_anchor_lists(tmp_path: Path):
    """The old refusal was true of grounded_by and read as 'no such anchor' while `show` listed the
    concern two lines later — the exact transcript in feedback-v3 #2."""
    root = _repo(tmp_path)
    mem_id = _remember(root, "The idle bound is enforced here.", "--concerns", OLD_SYM)
    result = runner.invoke(app, ["unlink", mem_id, "file:docs/notes.md", "--repo", str(root)])
    assert result.exit_code == 0
    assert "any anchor list" in result.output
    assert OLD_SYM in result.output                       # the concern is named, not hidden

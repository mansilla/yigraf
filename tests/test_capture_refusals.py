"""Capture-time refusals for writes that would report success and then not do it (feedback-v3 #7).

A bare ``sym:<path>`` is never a valid locator — it can only land as a dangling edge reporting
permanent hard drift — and pinning a superseded belief injects nothing, ever. Both were accepted with
at most a scrolled-past warning; both are now errors at the moment the mistake is made, in the same
family as the near-duplicate guard (the field's words: "the two most useful things the tool has said
to us... catch a mistake *at* capture time").
"""
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf import memory
from yigraf.cli import app

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    return tmp_path


def _remember(root: Path, statement: str, *extra: str) -> str:
    result = runner.invoke(app, ["remember", statement, "--repo", str(root), *extra])
    assert result.exit_code == 0, result.output
    return re.search(r"mem:[0-9a-f]+", result.output).group(0)


def test_bare_sym_concerns_is_refused_with_the_candidates(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "Session handling is optimistic.", "--repo", str(root),
                                 "--concerns", "sym:auth/session.py"])
    assert result.exit_code == 0                             # guidance, not a crash (design law #1)
    assert "sym:<path>#<name>" in result.output              # names the correct form
    assert "sym:auth/session.py#refresh" in result.output    # offers the candidates as the error's content
    assert "Captured" not in result.output                   # and nothing was written
    assert not any(memory.iter_memories(root))


def test_bare_sym_evidence_is_refused_too(tmp_path: Path):
    root = _repo(tmp_path)
    result = runner.invoke(app, ["remember", "Confirmed by the session test.", "--repo", str(root),
                                 "--grounding", "empirical", "--evidence", "sym:auth/session.py"])
    assert result.exit_code == 0
    assert "Captured" not in result.output and "sym:<path>#<name>" in result.output


def test_pin_refuses_a_superseded_belief_and_names_the_successor(tmp_path: Path):
    """feedback-v3 #7 first half: `pin` answered "SessionStart now injects it in full" on a retired
    belief and injected nothing — the store's twin `active` statuses caused the wrong pick (#8)."""
    root = _repo(tmp_path)
    old = _remember(root, "Tokens refresh optimistically.",
                    "--concerns", "sym:auth/session.py#refresh")
    result = runner.invoke(app, ["supersede", old, "Tokens refresh pessimistically.",
                                 "--repo", str(root)])
    new_id = re.search(r"Captured (mem:[0-9a-f]+)", result.output).group(1)
    result = runner.invoke(app, ["pin", old, "--repo", str(root)])
    assert result.exit_code == 0
    assert "superseded" in result.output and new_id in result.output
    assert "now injects" not in result.output
    assert memory.read_memory(memory.find_memory(root, old)).pinned is False

    assert runner.invoke(app, ["pin", new_id, "--repo", str(root)]).exit_code == 0
    assert memory.read_memory(memory.find_memory(root, new_id)).pinned is True

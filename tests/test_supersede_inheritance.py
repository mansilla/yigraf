"""`supersede` carries the predecessor's anchors and demotes it honestly (feedback-v3 #4/#8).

The field report's single highest-ranked fix: three anchored beliefs were superseded after a box run
refuted them and all three landed with NO anchor — the correction to a drive-torque function would
never have resurfaced at the edit hook on the exact symbol it warns about. And the predecessor's
artifact still read `status: active`, which is how a retired belief got pinned.
"""
import re
from pathlib import Path

from typer.testing import CliRunner

from yigraf import memory
from yigraf.cli import app

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"


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


def test_supersede_inherits_concerns_and_serves_by_default(tmp_path: Path):
    root = _repo(tmp_path)
    old = _remember(root, "Tokens refresh optimistically.", "--concerns", SYM,
                    "--serves", "int:session-expiry")
    result = runner.invoke(app, ["supersede", old, "Tokens refresh pessimistically.",
                                 "--repo", str(root), "--why", "the box run refuted optimism"])
    assert result.exit_code == 0, result.output
    new_id = re.search(r"Captured (mem:[0-9a-f]+)", result.output).group(1)
    new = _mem(root, new_id)
    assert [c.sym for c in new.concerns] == [SYM]            # the anchor carried
    assert new.concerns[0].anchor is not None                # and was re-resolved fresh, not copied
    assert new.serves == ["int:session-expiry"]
    assert f"Carried" in result.output and old in result.output  # the output says what carried


def test_explicit_flags_re_aim_instead_of_inheriting(tmp_path: Path):
    root = _repo(tmp_path)
    old = _remember(root, "Tokens refresh optimistically.", "--concerns", SYM)
    result = runner.invoke(app, ["supersede", old, "Expiry owns the invariant now.",
                                 "--repo", str(root), "--concerns", "sym:auth/session.py#expire"])
    assert result.exit_code == 0, result.output
    new_id = re.search(r"Captured (mem:[0-9a-f]+)", result.output).group(1)
    assert [c.sym for c in _mem(root, new_id).concerns] == ["sym:auth/session.py#expire"]
    assert "Carried" not in result.output


def test_applied_supersede_stamps_the_predecessor_artifact(tmp_path: Path):
    """feedback-v3 #8: a supersede was discoverable only by walking edges — both twins read `active`
    in the store, and the retired one got pinned. The artifact now tells the truth on its own."""
    root = _repo(tmp_path)
    old = _remember(root, "Tokens refresh optimistically.", "--concerns", SYM)
    result = runner.invoke(app, ["supersede", old, "Tokens refresh pessimistically.",
                                 "--repo", str(root)])
    assert result.exit_code == 0, result.output
    new_id = re.search(r"Captured (mem:[0-9a-f]+)", result.output).group(1)
    demoted = _mem(root, old)
    assert demoted.status == "superseded" and demoted.superseded_by == new_id


def test_pending_supersede_leaves_the_attested_predecessor_active_until_attest(tmp_path: Path):
    """Sticky attestation is unchanged: HELD PENDING means the old node stays authoritative — the
    stamp lands only when a human applies the supersede via `attest`."""
    root = _repo(tmp_path)
    old = _remember(root, "Tokens refresh optimistically.", "--concerns", SYM)
    assert runner.invoke(app, ["attest", old, "--repo", str(root)]).exit_code == 0
    result = runner.invoke(app, ["supersede", old, "Tokens refresh pessimistically.",
                                 "--repo", str(root)])
    assert result.exit_code == 0, result.output
    new_id = re.search(r"Captured (mem:[0-9a-f]+)", result.output).group(1)
    assert _mem(root, old).status == "active"                # held pending — nothing demoted yet
    assert runner.invoke(app, ["attest", new_id, "--repo", str(root)]).exit_code == 0
    demoted = _mem(root, old)
    assert demoted.status == "superseded" and demoted.superseded_by == new_id

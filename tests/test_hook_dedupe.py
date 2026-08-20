"""PostToolUse dedupe (feedback-v3 Ask A): a packet byte-identical to one this session already
received injects nothing.

Measured on one field session: 23 PostToolUse packets, 15 byte-identical repeats, 3.47M tokens — 19 %
of yigraf's entire cost — for text the model could already read. The latch is digest-keyed, so
anything yigraf would say DIFFERENTLY (new drift, a new decision) re-injects.
"""
import json
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import _post_tool_use, app

runner = CliRunner()

SYM = "sym:auth/session.py#refresh"


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    assert runner.invoke(app, ["build", str(tmp_path)]).exit_code == 0
    result = runner.invoke(app, ["remember", "Refresh must stay idempotent.", "--repo", str(tmp_path),
                                 "--concerns", SYM])
    assert result.exit_code == 0, result.output
    return tmp_path


def _edit_event(root: Path, session: str = "s1") -> dict:
    return {"tool_name": "Edit", "session_id": session, "cwd": str(root),
            "tool_input": {"file_path": str(root / "auth" / "session.py")}}


def test_identical_packet_is_injected_once_per_session(tmp_path: Path):
    root = _repo(tmp_path)
    first = _post_tool_use(_edit_event(root))
    assert first is not None and "Refresh must stay idempotent" in str(first)
    assert _post_tool_use(_edit_event(root)) is None          # byte-identical repeat → silence
    assert _post_tool_use(_edit_event(root)) is None


def test_a_fresh_session_gets_the_packet_again(tmp_path: Path):
    """/clear wipes the context, not the obligation — a new session must see it once."""
    root = _repo(tmp_path)
    assert _post_tool_use(_edit_event(root, session="s1")) is not None
    assert _post_tool_use(_edit_event(root, session="s1")) is None
    assert _post_tool_use(_edit_event(root, session="s2")) is not None


def test_a_changed_packet_reinjects(tmp_path: Path):
    """The latch keys on the digest of the rendered text, not on 'same file' — new content re-injects."""
    root = _repo(tmp_path)
    assert _post_tool_use(_edit_event(root)) is not None
    assert _post_tool_use(_edit_event(root)) is None
    result = runner.invoke(app, ["remember", "Refresh must never log the token.", "--repo", str(root),
                                 "--concerns", SYM, "--new"])
    assert result.exit_code == 0, result.output
    again = _post_tool_use(_edit_event(root))
    assert again is not None and "never log the token" in str(again)


def test_latch_is_volatile_local_state(tmp_path: Path):
    root = _repo(tmp_path)
    assert _post_tool_use(_edit_event(root)) is not None
    latch = root / "yigraf" / ".local" / "emitted.json"
    assert latch.is_file()                                     # derived state lives in .local (D#6)
    data = json.loads(latch.read_text())
    assert "s1" in data and "auth/session.py" in data["s1"]

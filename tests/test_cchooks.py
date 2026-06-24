"""Claude Code hook entry points + installer (M5). The in-session behavior, driven via stdin JSON."""
import json
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.hooks import _AGENTS_START, install_claude_hooks
from yigraf.scaffold import init_workspace

runner = CliRunner()
SYM = "sym:auth/session.py#refresh"


def _governed_repo(tmp_path: Path, drift: bool = False) -> Path:
    runner.invoke(app, ["init", str(tmp_path)])
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    runner.invoke(app, ["build", str(tmp_path)])
    runner.invoke(app, ["intent", "session-expiry", "--repo", str(tmp_path), "-s", "SHALL expire.",
                        "--scenario", "Given a, When b, Then c.", "--status", "satisfied"])
    runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth", "--task", "idle expiry"])
    runner.invoke(app, ["link", "task:auth/1", "int:session-expiry", "--repo", str(tmp_path)])
    runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)])
    if drift:
        src.write_text("def refresh(token):\n    return token + 1\n")
    return tmp_path


def _post(root: Path, file_path: Path, tool: str = "Edit"):
    payload = json.dumps({"tool_name": tool, "tool_input": {"file_path": str(file_path)}, "cwd": str(root)})
    return runner.invoke(app, ["hook", "post-tool-use"], input=payload)


# --- PostToolUse ----------------------------------------------------------------------------------


def test_post_tool_use_injects_for_a_governed_drifted_file(tmp_path: Path):
    root = _governed_repo(tmp_path, drift=True)
    result = _post(root, root / "auth" / "session.py")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "Drift" in ctx and SYM in ctx and "satisfied but not verified" in ctx


def test_post_tool_use_is_silent_on_unrelated_code(tmp_path: Path):
    root = _governed_repo(tmp_path)
    (root / "other.py").write_text("def helper():\n    return 0\n")
    result = _post(root, root / "other.py")
    assert result.exit_code == 0 and result.output.strip() == ""


def test_post_tool_use_is_silent_on_non_python(tmp_path: Path):
    root = _governed_repo(tmp_path, drift=True)
    (root / "README.md").write_text("hello")
    assert _post(root, root / "README.md").output.strip() == ""


def test_post_tool_use_is_silent_without_a_workspace(tmp_path: Path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    assert _post(tmp_path, tmp_path / "a.py").output.strip() == ""


def test_post_tool_use_ignores_non_edit_tools(tmp_path: Path):
    root = _governed_repo(tmp_path, drift=True)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(root)})
    assert runner.invoke(app, ["hook", "post-tool-use"], input=payload).output.strip() == ""


def test_hook_is_fail_open_on_garbage_stdin(tmp_path: Path):
    result = runner.invoke(app, ["hook", "post-tool-use"], input="not json {{")
    assert result.exit_code == 0 and result.output.strip() == ""


# --- SessionStart ---------------------------------------------------------------------------------


def test_session_start_reinjects_the_active_plan(tmp_path: Path):
    root = _governed_repo(tmp_path)
    payload = json.dumps({"source": "clear", "cwd": str(root)})
    result = runner.invoke(app, ["hook", "session-start"], input=payload)
    out = json.loads(result.output)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "plan:auth" in out["hookSpecificOutput"]["additionalContext"]


def test_session_start_is_silent_with_no_specs(tmp_path: Path):
    init_workspace(tmp_path)
    (tmp_path / "m.py").write_text("def f():\n    return 1\n")
    result = runner.invoke(app, ["hook", "session-start"], input=json.dumps({"source": "clear", "cwd": str(tmp_path)}))
    assert result.output.strip() == ""


# --- installer ------------------------------------------------------------------------------------


def test_install_writes_settings_skill_and_agents(tmp_path: Path):
    init_workspace(tmp_path)
    result = install_claude_hooks(tmp_path)
    settings = json.loads(result.settings_path.read_text())
    assert any(e.get("matcher") == "Edit|Write" for e in settings["hooks"]["PostToolUse"])
    assert "hook post-tool-use" in json.dumps(settings)
    assert "hook session-start" in json.dumps(settings)
    assert "yigraf link" in result.skill_path.read_text()
    assert _AGENTS_START in result.agents_path.read_text()


def test_install_is_idempotent(tmp_path: Path):
    init_workspace(tmp_path)
    install_claude_hooks(tmp_path)
    install_claude_hooks(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    count = sum(1 for e in settings["hooks"]["PostToolUse"]
                for h in e.get("hooks", []) if "hook post-tool-use" in h.get("command", ""))
    assert count == 1
    assert (tmp_path / "AGENTS.md").read_text().count(_AGENTS_START) == 1


def test_install_preserves_foreign_settings_and_hooks(tmp_path: Path):
    init_workspace(tmp_path)
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps({
        "model": "some-model",
        "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]},
    }))
    install_claude_hooks(tmp_path)
    settings = json.loads((claude / "settings.json").read_text())
    assert settings["model"] == "some-model"
    commands = [h["command"] for e in settings["hooks"]["PostToolUse"] for h in e["hooks"]]
    assert "mine.sh" in commands and any("hook post-tool-use" in c for c in commands)

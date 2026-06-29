"""Multi-host wiring: the generalized edit-hook (Codex apply_patch) + the Codex/Antigravity installers.

The push-channel complements. Codex reuses the exact Claude Code handlers (its hook contract mirrors
them), so the only new logic is parsing a file path out of an ``apply_patch`` and writing Codex's config.
Antigravity has no hooks, so its "installer" writes an always-on rule + hands back the MCP wiring.
"""
import json
from pathlib import Path

from typer.testing import CliRunner

from yigraf.cli import _edited_file, _post_tool_use, app
from yigraf.hooks import _AGENTS_START, detect_hosts, install_antigravity, install_codex_hooks

runner = CliRunner()
SYM = "sym:auth/session.py#refresh"
_PATCH = "*** Begin Patch\n*** Update File: auth/session.py\n@@\n-x\n+y\n*** End Patch"


def _governed_repo(tmp_path: Path) -> Path:
    runner.invoke(app, ["init", str(tmp_path)])
    src = tmp_path / "auth" / "session.py"
    src.parent.mkdir(parents=True)
    src.write_text("def refresh(token):\n    return token\n")
    runner.invoke(app, ["build", str(tmp_path)])
    runner.invoke(app, ["plan", "auth", "--repo", str(tmp_path), "-t", "Auth", "--task", "expiry"])
    runner.invoke(app, ["link", "task:auth/1", SYM, "--repo", str(tmp_path)])
    return tmp_path


# ── edit detection across hosts ──────────────────────────────────────────────────────────────────

def test_edited_file_claude_and_codex_and_ignored():
    assert _edited_file({"tool_name": "Edit", "tool_input": {"file_path": "a.py"}}) == "a.py"
    assert _edited_file({"tool_name": "Write", "tool_input": {"path": "b.py"}}) == "b.py"
    assert _edited_file({"tool_name": "apply_patch", "tool_input": {"patch": _PATCH}}) == "auth/session.py"
    assert _edited_file({"tool_name": "Read", "tool_input": {"file_path": "a.py"}}) is None  # not an edit
    assert _edited_file({"tool_name": "apply_patch", "tool_input": {"patch": "no path here"}}) is None


def test_codex_apply_patch_event_surfaces_governing_context(tmp_path: Path):
    root = _governed_repo(tmp_path)
    payload = _post_tool_use({"tool_name": "apply_patch",
                              "tool_input": {"patch": _PATCH}, "cwd": str(root)})
    assert payload is not None
    out = payload["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse" and "auth/session.py" in out["additionalContext"]


# ── Codex installer ──────────────────────────────────────────────────────────────────────────────

def test_install_codex_hooks_writes_both_events_and_gitignore(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path)])
    res = install_codex_hooks(tmp_path)
    data = json.loads(res.hooks_path.read_text())
    assert res.hooks_path.name == "hooks.json" and res.hooks_path.parent.name == ".codex"
    assert set(data["hooks"]) == {"SessionStart", "PostToolUse"}
    cmds = [h["command"] for ev in data["hooks"].values() for e in ev for h in e["hooks"]]
    assert any("hook session-start" in c for c in cmds) and any("hook post-tool-use" in c for c in cmds)
    assert "hooks.json" in res.gitignore_path.read_text()  # machine-local abs path kept out of git
    assert _AGENTS_START in res.agents_path.read_text()


def test_install_codex_hooks_is_idempotent(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path)])
    assert install_codex_hooks(tmp_path).hooks_changed is True
    assert install_codex_hooks(tmp_path).hooks_changed is False  # second run is a no-op


# ── Antigravity installer (no hooks → an always-on rule + MCP wiring) ──────────────────────────────

def test_install_antigravity_writes_rule_and_mcp_command(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path)])
    res = install_antigravity(tmp_path)
    assert res.rule_path == tmp_path / ".agents" / "rules" / "yigraf.md"
    body = res.rule_path.read_text()
    assert "MCP" in body and "context" in body and "remember" in body
    assert _AGENTS_START in res.agents_path.read_text()
    assert "-m" in res.mcp_command and "yigraf" in res.mcp_command and "mcp" in res.mcp_command


# ── auto-host detection + `yigraf install` dispatch ───────────────────────────────────────────────

def test_detect_hosts_by_repo_and_home_markers(tmp_path: Path):
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir(); home.mkdir()
    assert detect_hosts(repo, home) == []                       # nothing installed/configured
    (repo / ".claude").mkdir(); assert detect_hosts(repo, home) == ["claude"]   # repo marker
    (home / ".codex").mkdir(); assert detect_hosts(repo, home) == ["claude", "codex"]  # home marker
    (home / ".gemini").mkdir(); assert detect_hosts(repo, home) == ["claude", "codex", "antigravity"]


def test_install_host_codex_wires_codex(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path)])
    out = runner.invoke(app, ["install", str(tmp_path), "--host", "codex"])
    assert out.exit_code == 0 and "codex" in out.stdout
    assert (tmp_path / ".codex" / "hooks.json").exists()


def test_install_mcp_and_unknown_host_fall_back_to_mcp(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path)])
    for host in ("mcp", "cursor"):  # explicit mcp, and an unsupported host name
        out = runner.invoke(app, ["install", str(tmp_path), "--host", host])
        assert out.exit_code == 0 and "mcpServers" in out.stdout and "yigraf" in out.stdout
    assert not (tmp_path / ".codex").exists()  # fallback wires nothing host-native

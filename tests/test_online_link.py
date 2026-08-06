"""Binding a workspace to a hosted project: `yigraf online`, the credential store, and the three checks.

What these tests are really pinning is the *failure* behaviour. The happy path is one paste and one
command; what makes the design worth its complexity is that every wrong paste, stale code, mismatched
repo and copied config produces a specific correction instead of a silent bad binding.
"""
import json
import os
import stat
import subprocess

import pytest
from typer.testing import CliRunner

from yigraf import online
from yigraf.cli import app
from yigraf.sync import WIRE_VERSION

runner = CliRunner()

REMOTE = "https://yigraf.test"
CODE = "ygl_abcdefghijklmnop"
ROOT = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
OTHER_ROOT = "ffffffffffffffffffffffffffffffffffffffff"


def _preflight(**over):
    return {"project": "yigraf-server", "name": "yigraf server", "actor": "prn_x",
            "email": "rick@corp", "role": "writer", "repo_fingerprint": None,
            "wire_versions": [WIRE_VERSION], "expires_at": "2030-01-01T00:00:00Z", **over}


def _redeemed(**over):
    return {"token": "ygf_secret", "actor": "prn_x", "email": "rick@corp",
            "project": "yigraf-server", "role": "writer", "repo_fingerprint": ROOT, **over}


@pytest.fixture
def creds(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("YIGRAF_TOKEN", raising=False)
    return online.credentials_path()


# ---- the credential store ---------------------------------------------------------------------


def test_the_token_is_stored_outside_the_repo_and_kept_private(creds):
    """Never config.yaml: that file is committed, and a token in git is a leaked token."""
    path = online.store_credential(REMOTE, {"token": "ygf_secret", "actor": "prn_x"})
    assert path == creds
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())[REMOTE]["token"] == "ygf_secret"


def test_credentials_are_keyed_by_host_so_a_second_server_doesnt_clobber_the_first(creds):
    online.store_credential(REMOTE, {"token": "one"})
    online.store_credential("https://other.test/", {"token": "two"})
    assert online.resolve_token(REMOTE) == "one"
    assert online.resolve_token("https://other.test") == "two"  # trailing slash normalized


def test_the_environment_wins_over_the_stored_credential(creds, monkeypatch):
    """CI and containers get their token from a secret store, with no interactive link step to have
    written a file — so the env var has to take precedence, not merely fill a gap."""
    online.store_credential(REMOTE, {"token": "from-file"})
    monkeypatch.setenv("YIGRAF_TOKEN", "from-env")
    assert online.resolve_token(REMOTE) == "from-env"


def test_a_corrupt_credentials_file_does_not_brick_the_cli(creds):
    creds.parent.mkdir(parents=True, exist_ok=True)
    creds.write_text("{not json")
    assert online.resolve_token(REMOTE) is None


# ---- repo identity ----------------------------------------------------------------------------


def _git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", "-C", str(path), *a], capture_output=True, check=True)
    run("init", "-q")
    run("config", "user.email", "t@t.test")
    run("config", "user.name", "T")
    (path / "f.txt").write_text("hello")
    run("add", ".")
    run("commit", "-qm", "first")
    return path


def test_the_fingerprint_is_the_root_commit(tmp_path):
    """Identify a repository by its root commit, not its remote URL: a URL changes on rename, re-host
    or org move, and the root commit survives all three."""
    repo = _git_repo(tmp_path / "r")
    root = subprocess.run(["git", "-C", str(repo), "rev-list", "--max-parents=0", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert online.repo_fingerprint(repo) == root

    # ...and it is stable across a fresh clone of the same history, with no coordination.
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True, capture_output=True)
    assert online.repo_fingerprint(clone) == root


def test_no_git_means_unknown_not_mismatch(tmp_path):
    assert online.repo_fingerprint(tmp_path) is None


def test_a_shallow_clone_refuses_to_fingerprint(tmp_path, monkeypatch):
    """The 'root' a shallow clone reports is the graft boundary and varies with clone depth. Sending it
    would claim a WRONG identity, which is worse than claiming none."""
    monkeypatch.setattr(online, "_git", lambda repo, *args:
                        "true" if args[:2] == ("rev-parse", "--is-shallow-repository") else ROOT)
    assert online.repo_fingerprint(tmp_path) is None


# ---- parsing what was pasted --------------------------------------------------------------------


def test_a_full_url_carries_its_host():
    assert online.parse_link(f"{REMOTE}/link/{CODE}") == (REMOTE, CODE)


def test_a_bare_code_needs_a_remote():
    assert online.parse_link(CODE, REMOTE) == (REMOTE, CODE)
    with pytest.raises(online.LinkError) as exc:
        online.parse_link(CODE)
    assert exc.value.code == "no_remote" and "--remote" in exc.value.guidance


@pytest.mark.parametrize("pasted", ["ygi_someinvitation", f"{REMOTE}/invite/ygi_someinvitation"])
def test_an_invitation_pasted_here_is_named_not_just_refused(pasted):
    """The two credentials look alike. Each surface must name the other rather than fail obscurely —
    it is a one-line check on each side, and it is the difference between a redirect and a lost hour."""
    with pytest.raises(online.LinkError) as exc:
        online.parse_link(pasted)
    assert exc.value.code == "wrong_credential_kind"
    assert "browser" in exc.value.guidance


# ---- the three checks ---------------------------------------------------------------------------


def test_a_repo_mismatch_is_refused_before_anything_is_written():
    """Why this check exists at all: the shared graph is full of implements/concerns edges anchored to
    code symbols. Bind to a project about another codebase and every one of them dangles — it folds,
    renders, and is quietly meaningless. That silence is exactly why the check belongs at bind time."""
    with pytest.raises(online.LinkError) as exc:
        online.check_compatibility(_preflight(repo_fingerprint=OTHER_ROOT), ROOT)
    assert exc.value.code == "repo_mismatch"
    assert "--force" in exc.value.guidance
    online.check_compatibility(_preflight(repo_fingerprint=OTHER_ROOT), ROOT, force=True)  # overridable


def test_an_unclaimed_or_unknown_fingerprint_is_allowed():
    online.check_compatibility(_preflight(repo_fingerprint=None), ROOT)  # trust on first use
    online.check_compatibility(_preflight(repo_fingerprint=ROOT), None)  # shallow clone / no git


def test_an_unsupported_wire_is_refused_with_no_way_to_override():
    """A repo mismatch is a judgement call a human may overrule; an unsupported wire means the events
    would not round-trip, so there is nothing to override."""
    with pytest.raises(online.LinkError) as exc:
        online.check_compatibility(_preflight(wire_versions=[WIRE_VERSION + 7]), ROOT, force=True)
    assert exc.value.code == "wire_unsupported"


def test_a_replica_bound_elsewhere_is_moved_aside_never_deleted(tmp_path):
    replica = tmp_path / "replica.db"
    replica.write_text("a verified merkle cursor")
    assert online.check_replica(replica, "same", REMOTE, "same", REMOTE) is None  # nothing to do

    with pytest.raises(online.LinkError) as exc:
        online.check_replica(replica, "old-project", REMOTE, "new-project", REMOTE)
    assert exc.value.code == "replica_bound" and replica.exists()

    moved = online.check_replica(replica, "old-project", REMOTE, "new-project", REMOTE, force=True)
    assert moved.read_text() == "a verified merkle cursor" and not replica.exists()
    assert moved.name.endswith(".bak-1")


# ---- the command ---------------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path, creds, monkeypatch):
    """A yigraf workspace whose credentials file is redirected into tmp_path (via ``creds``).

    NB: never call ``monkeypatch.undo()`` in a test using this — it would also undo that redirection
    and write a real token into the developer's own ``~/.config/yigraf``."""
    runner.invoke(app, ["init", str(tmp_path)])
    monkeypatch.setattr("yigraf.cli.sync", lambda **kw: None)  # the first sync is its own test's job
    return tmp_path


def _wire(monkeypatch, preflight=None, redeemed=None):
    monkeypatch.setattr(online, "preflight", lambda base, code: preflight or _preflight())
    monkeypatch.setattr(online, "redeem", lambda *a, **kw: redeemed or _redeemed())


def test_online_binds_the_workspace_and_keeps_the_token_out_of_git(workspace, monkeypatch, creds):
    _wire(monkeypatch)
    result = runner.invoke(app, ["online", f"{REMOTE}/link/{CODE}", "--repo", str(workspace)])
    assert result.exit_code == 0, result.output
    assert "Linked 'yigraf-server'" in result.output and "rick@corp" in result.output

    config = (workspace / "yigraf" / "config.yaml").read_text()
    assert "project: yigraf-server" in config and f"remote: {REMOTE}" in config
    assert f"repo_fingerprint: {ROOT}" in config
    assert "ygf_secret" not in config, "a token in a committed file is a leaked token"
    assert json.loads(creds.read_text())[REMOTE]["token"] == "ygf_secret"


def test_binding_preserves_the_comments_in_a_committed_config(workspace, monkeypatch):
    _wire(monkeypatch)
    before = (workspace / "yigraf" / "config.yaml").read_text()
    runner.invoke(app, ["online", f"{REMOTE}/link/{CODE}", "--repo", str(workspace)])
    after = (workspace / "yigraf" / "config.yaml").read_text()
    assert "# --- Structure extraction (M1) ---" in after
    assert before.count("#") == after.count("#"), "config.yaml is human-authored; keep its comments"


def test_the_credential_is_written_before_the_config(workspace, monkeypatch, creds):
    """A code is spent the moment it is redeemed. A token stored without config is recoverable; config
    written without a token is a dead binding AND a dead code — so the order is not arbitrary."""
    _wire(monkeypatch)
    monkeypatch.setattr("yigraf.cli._patch_online_config",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError):
        runner.invoke(app, ["online", f"{REMOTE}/link/{CODE}", "--repo", str(workspace)],
                      catch_exceptions=False)
    assert json.loads(creds.read_text())[REMOTE]["token"] == "ygf_secret"


def test_online_refuses_to_repoint_a_bound_workspace(workspace, monkeypatch):
    _wire(monkeypatch)
    runner.invoke(app, ["online", f"{REMOTE}/link/{CODE}", "--repo", str(workspace)])
    _wire(monkeypatch, preflight=_preflight(project="something-else"))
    result = runner.invoke(app, ["online", f"{REMOTE}/link/{CODE}", "--repo", str(workspace)])
    assert "already bound to 'yigraf-server'" in result.output
    assert "project: yigraf-server" in (workspace / "yigraf" / "config.yaml").read_text()


def test_a_dead_code_teaches_the_fix_rather_than_failing(workspace, monkeypatch):
    """Errors teach abandonment: every recoverable refusal exits 0 with the correction (design law #1)."""
    def expired(base, code):
        raise online.LinkError("code_expired", online._EXPLAIN["code_expired"])

    monkeypatch.setattr(online, "preflight", expired)
    result = runner.invoke(app, ["online", f"{REMOTE}/link/{CODE}", "--repo", str(workspace)])
    assert result.exit_code == 0
    assert "expired" in result.output and "Machines tab" in result.output


def test_online_with_no_code_answers_am_i_connected(workspace, monkeypatch):
    result = runner.invoke(app, ["online", "--repo", str(workspace)])
    assert "isn't online" in result.output and "Machines tab" in result.output

    _wire(monkeypatch)
    runner.invoke(app, ["online", f"{REMOTE}/link/{CODE}", "--repo", str(workspace)])
    monkeypatch.setattr(online, "whoami", lambda remote, token: {
        "actor": "prn_x", "email": "rick@corp", "project": "yigraf-server", "role": "writer",
        "label": "laptop:repo"})
    result = runner.invoke(app, ["online", "--repo", str(workspace)])
    assert "Project:  yigraf-server" in result.output
    assert "rick@corp (writer) as laptop:repo" in result.output


def test_whoami_names_the_identity_this_workspace_pushes_as(workspace, monkeypatch):
    _wire(monkeypatch)
    runner.invoke(app, ["online", f"{REMOTE}/link/{CODE}", "--repo", str(workspace)])
    monkeypatch.setattr(online, "whoami", lambda remote, token: {
        "actor": "prn_x", "email": "rick@corp", "project": "yigraf-server", "role": "writer",
        "label": "laptop:repo"})
    result = runner.invoke(app, ["whoami", "--repo", str(workspace)])
    assert "rick@corp — writer on yigraf-server" in result.output


# ---- the re-check inside sync --------------------------------------------------------------------


def test_sync_refuses_a_config_copied_into_another_repository(workspace, monkeypatch, creds):
    """The one case the bind-time check cannot catch. Nearly free, and the failure it prevents is
    silent: the assertions would push fine and anchor to code that isn't here."""
    _wire(monkeypatch)
    runner.invoke(app, ["online", f"{REMOTE}/link/{CODE}", "--repo", str(workspace)])
    assert f"repo_fingerprint: {ROOT}" in (workspace / "yigraf" / "config.yaml").read_text()

    # ...and now the same config finds itself in a repo with a different history.
    monkeypatch.setattr(online, "repo_fingerprint", lambda repo: OTHER_ROOT)
    result = runner.invoke(app, ["sync", "--repo", str(workspace)])
    assert result.exit_code == 0
    assert "bound to a different repository" in result.output
    assert "Nothing was pushed" in result.output


def test_sync_without_a_credential_points_at_the_link_flow(workspace, monkeypatch):
    _wire(monkeypatch)
    runner.invoke(app, ["online", f"{REMOTE}/link/{CODE}", "--repo", str(workspace)])
    online.credentials_path().unlink()
    result = runner.invoke(app, ["sync", "--repo", str(workspace)])
    assert "yigraf online <the URL>" in result.output
    assert os.environ.get("YIGRAF_TOKEN") is None

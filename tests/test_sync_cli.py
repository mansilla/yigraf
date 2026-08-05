"""``yigraf sync`` — the CLI wiring over :mod:`yigraf.sync`.

Drives the real pull/push/verify logic through a :class:`~yigraf.sync.LoopbackRemote` (an in-process
server-side ``OnlineLog``) substituted for ``HttpRemote``, so the transport is the only thing faked.
The genuine HTTP path is proven separately against a running yigraf-server.
"""
from pathlib import Path

import pytest
from typer.testing import CliRunner

import yigraf.sync as sync_mod
from yigraf.cli import app
from yigraf.config import TOKEN_ENV
from yigraf.onlinelog import OnlineLog, SqliteAssertionStore
from yigraf.sync import LoopbackRemote

runner = CliRunner()

PROJECT = "demo"
SYM = "sym:app.py#greet"
SERVER_KEY = b"test-server-signing-key"


class _ServerLike:
    """``LoopbackRemote`` plus the one policy the *server* owns: provenance ``actor`` is the
    authenticated principal, never the client's claim (yigraf_server.service.OnlineService). Without
    this the double would reject every push, since ``actor`` is a required provenance field the client
    deliberately never sets.

    The actor is derived from the bearer token, exactly as the real service derives it from the
    authenticated session — so two workspaces holding different tokens are two different principals,
    which is what any test about *whose* belief this is needs."""

    def __init__(self, log: OnlineLog, token: str = "tester") -> None:
        self._inner = LoopbackRemote(log)
        self._actor = f"{token}@example.com"

    def head(self, project):
        return self._inner.head(project)

    def pull(self, project, since_seq):
        return self._inner.pull(project, since_seq)

    def push(self, project, assertions):
        from dataclasses import replace
        stamped = [replace(a, provenance=[{**(a.provenance[0] if a.provenance else {}),
                                           "actor": self._actor}]) for a in assertions]
        return self._inner.push(project, stamped)


@pytest.fixture
def shared_remote(monkeypatch):
    """One in-process log every workspace talks to, standing in for the hosted server. Each client gets
    a connection authenticated as whoever ``YIGRAF_TOKEN`` says it is at the moment of the call."""
    log = OnlineLog(SqliteAssertionStore(), PROJECT, signer_key=SERVER_KEY)
    monkeypatch.setattr(sync_mod, "HttpRemote", lambda url, token, **kw: _ServerLike(log, token))
    monkeypatch.setenv(TOKEN_ENV, "test-token")
    return _ServerLike(log)


def _workspace(path: Path, *, online: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "app.py").write_text("def greet(name):\n    return 'hi ' + name\n")
    assert runner.invoke(app, ["init", str(path)]).exit_code == 0
    if online:
        cfg = path / "yigraf" / "config.yaml"
        text = cfg.read_text()
        text = text.replace("  project:  ", f"  project: {PROJECT}  ")
        text = text.replace("  remote:  ", "  remote: http://localhost:0  ")
        cfg.write_text(text)
    assert runner.invoke(app, ["build", str(path)]).exit_code == 0
    return path


def test_offline_workspace_is_told_how_to_connect(tmp_path, monkeypatch):
    """A recoverable config gap exits 0 with guidance (design law #1), never a hard error."""
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    ws = _workspace(tmp_path / "solo", online=False)
    out = runner.invoke(app, ["sync", "--repo", str(ws)])
    assert out.exit_code == 0
    assert "online.project and online.remote are" in out.output
    assert "works fully offline" in out.output


def test_missing_token_is_guidance_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    ws = _workspace(tmp_path / "a")
    out = runner.invoke(app, ["sync", "--repo", str(ws)])
    assert out.exit_code == 0 and TOKEN_ENV in out.output


def test_dry_run_reports_without_writing(tmp_path, shared_remote):
    ws = _workspace(tmp_path / "a")
    assert runner.invoke(app, ["remember", "greet must not log the name", "--why", "PII",
                               "--concerns", SYM, "--repo", str(ws)]).exit_code == 0
    out = runner.invoke(app, ["sync", "--repo", str(ws), "--dry-run"])
    assert out.exit_code == 0, out.output
    assert "1 to push" in out.output and "--dry-run" in out.output
    assert shared_remote.head(PROJECT).seq == 0, "a dry run must not write to the remote"


def test_push_then_pull_moves_a_belief_between_workspaces(tmp_path, shared_remote):
    alice = _workspace(tmp_path / "alice")
    bob = _workspace(tmp_path / "bob")

    assert runner.invoke(app, ["remember", "greet must not log the name", "--why", "PII",
                               "--concerns", SYM, "--repo", str(alice)]).exit_code == 0
    pushed = runner.invoke(app, ["sync", "--repo", str(alice)])
    assert pushed.exit_code == 0, pushed.output
    assert "pushed 1" in pushed.output

    pulled = runner.invoke(app, ["sync", "--repo", str(bob)])
    assert pulled.exit_code == 0, pulled.output
    assert "pulled 1" in pulled.output

    # Bob has no local memory artifact, yet the belief is in his graph.
    from yigraf import memory
    from yigraf.config import load_config
    from yigraf.extract import build_graph
    assert memory.iter_memories(bob) == []
    graph, stats = build_graph(bob, load_config(bob / "yigraf" / "config.yaml"))
    assert stats.synced == 1
    assert [n for n, a in graph.nodes(data=True) if a.get("family") == "memory"]


def test_teammates_belief_drifts_against_my_edit_after_sync(tmp_path, shared_remote):
    alice = _workspace(tmp_path / "alice")
    bob = _workspace(tmp_path / "bob")
    runner.invoke(app, ["remember", "greet must not log the name", "--why", "PII",
                        "--concerns", SYM, "--repo", str(alice)])
    runner.invoke(app, ["sync", "--repo", str(alice)])
    runner.invoke(app, ["sync", "--repo", str(bob)])

    assert runner.invoke(app, ["drift", str(bob)]).exit_code == 0, "no drift before the edit"
    (bob / "app.py").write_text("def greet(name):\n    print(name)\n    return 'hi ' + name\n")
    drifted = runner.invoke(app, ["drift", str(bob)])
    assert drifted.exit_code == 1, drifted.output
    assert "soft drift" in drifted.output


def test_sync_is_idempotent(tmp_path, shared_remote):
    ws = _workspace(tmp_path / "a")
    runner.invoke(app, ["remember", "a belief", "--why", "reasons",
                        "--concerns", SYM, "--repo", str(ws)])
    first = runner.invoke(app, ["sync", "--repo", str(ws)])
    second = runner.invoke(app, ["sync", "--repo", str(ws)])
    assert "pushed 1" in first.output
    assert "pulled 0, pushed 0" in second.output, second.output


def test_a_verdict_rides_the_log_to_the_other_workspace(tmp_path, shared_remote):
    """The resolution family is what makes conflict resolution a team operation rather than a local one."""
    from yigraf import memory, resolution

    alice = _workspace(tmp_path / "alice")
    bob = _workspace(tmp_path / "bob")
    runner.invoke(app, ["remember", "greet must not log the name", "--why", "PII",
                        "--concerns", SYM, "--repo", str(alice)])
    runner.invoke(app, ["sync", "--repo", str(alice)])
    runner.invoke(app, ["sync", "--repo", str(bob)])

    runner.invoke(app, ["remember", "greet should log the name", "--why", "debugging",
                        "--concerns", SYM, "--new", "--repo", str(bob)])
    alice_mem = memory.iter_memories(alice)[0].id
    bob_mem = memory.iter_memories(bob)[0].id
    disputed = runner.invoke(app, ["dispute", alice_mem, bob_mem, "--why", "cannot both hold",
                                   "--repo", str(bob)])
    assert disputed.exit_code == 0, disputed.output
    runner.invoke(app, ["sync", "--repo", str(bob)])

    # Alice pulls a nomination she never authored, over a belief pair she only half owns.
    runner.invoke(app, ["sync", "--repo", str(alice)])
    from yigraf.config import load_config
    from yigraf.contradiction import detect_conflicts
    from yigraf.extract import build_graph
    config = load_config(alice / "yigraf" / "config.yaml")
    graph, _ = build_graph(alice, config)
    conflicts = detect_conflicts(graph, alice, config, index=None)
    assert [(c.nominated, sorted((c.left, c.right))) for c in conflicts] == [
        (True, sorted((alice_mem, bob_mem)))]

    # She resolves it, and the verdict travels back.
    assert runner.invoke(app, ["reconcile", alice_mem, bob_mem, "--why", "different altitudes",
                               "--repo", str(alice)]).exit_code == 0
    runner.invoke(app, ["sync", "--repo", str(alice)])
    runner.invoke(app, ["sync", "--repo", str(bob)])

    assert len(resolution.iter_resolutions(bob)) == 1, "bob still only authored his own nomination"
    bob_config = load_config(bob / "yigraf" / "config.yaml")
    bob_graph, _ = build_graph(bob, bob_config)
    assert detect_conflicts(bob_graph, bob, bob_config, index=None) == [], \
        "alice's verdict must close the conflict on bob's machine too"


def _as(monkeypatch, who: str, *args):
    """Run a command as ``who`` — the token is what names a principal to the server."""
    monkeypatch.setenv(TOKEN_ENV, who)
    return runner.invoke(app, list(args))


def test_the_later_writer_is_told_the_conflict_is_theirs(tmp_path, shared_remote, monkeypatch):
    """Task #6: whoever pushed second owes the resolution, and hears so at the moment they pull.

    Alice's belief lands first; Bob writes an opposing one into a world that already contained hers, so
    the merge is his — git's rule, derived from the log's order rather than assigned by anyone. Alice
    nominates the pair (index-independent, so the sweep's cosine gate isn't what's under test), and the
    next sync tells each side something different: Bob that it is his, Alice that it is Bob's.
    """
    from yigraf import memory

    alice = _workspace(tmp_path / "alice")
    bob = _workspace(tmp_path / "bob")

    _as(monkeypatch, "alice", "remember", "greet must not log the name", "--why", "PII",
        "--concerns", SYM, "--repo", str(alice))
    _as(monkeypatch, "alice", "sync", "--repo", str(alice))
    _as(monkeypatch, "bob", "sync", "--repo", str(bob))
    _as(monkeypatch, "bob", "remember", "greet should log the name", "--why", "debugging",
        "--concerns", SYM, "--new", "--repo", str(bob))
    _as(monkeypatch, "bob", "sync", "--repo", str(bob))

    alice_mem = memory.iter_memories(alice)[0].id
    bob_mem = memory.iter_memories(bob)[0].id
    _as(monkeypatch, "alice", "sync", "--repo", str(alice))
    assert _as(monkeypatch, "alice", "dispute", alice_mem, bob_mem, "--why", "cannot both hold",
               "--repo", str(alice)).exit_code == 0
    alice_sees = _as(monkeypatch, "alice", "sync", "--repo", str(alice))

    assert alice_sees.exit_code == 0, alice_sees.output
    assert "You now own" not in alice_sees.output, "she wrote first — the merge is not hers"
    assert "1 other open conflict — owed by the later writer: bob@example.com (1)" in alice_sees.output

    bob_sees = _as(monkeypatch, "bob", "sync", "--repo", str(bob))
    assert bob_sees.exit_code == 0, bob_sees.output
    assert "You now own 1 open conflict" in bob_sees.output
    assert f"you wrote {bob_mem}" in bob_sees.output and "the later writer resolves" in bob_sees.output
    assert f"yigraf reconcile {min(alice_mem, bob_mem)}" in bob_sees.output

    # And it stops being anyone's the moment it is resolved — silence, not a "resolved!" stat (mem:012).
    assert _as(monkeypatch, "bob", "reconcile", alice_mem, bob_mem, "--why", "different altitudes",
               "--repo", str(bob)).exit_code == 0
    settled = _as(monkeypatch, "bob", "sync", "--repo", str(bob))
    assert "You now own" not in settled.output and "owed by the later writer" not in settled.output


def test_a_synced_belief_matures_on_the_logs_clock(tmp_path, shared_remote, monkeypatch):
    """Task #7: a teammate's belief has no file in *my* git history, so the git clock scores it 0
    forever however long it has stood. In the log it has a landing and later appends to be measured
    against, so it ages like everyone else's."""
    from yigraf.config import load_config
    from yigraf.extract import build_graph

    alice = _workspace(tmp_path / "alice")
    bob = _workspace(tmp_path / "bob")
    _as(monkeypatch, "alice", "remember", "greet must not log the name", "--why", "PII",
        "--concerns", SYM, "--repo", str(alice))
    _as(monkeypatch, "alice", "sync", "--repo", str(alice))
    _as(monkeypatch, "bob", "sync", "--repo", str(bob))

    config = load_config(bob / "yigraf" / "config.yaml")
    graph, _ = build_graph(bob, config)
    hers = [n for n, a in graph.nodes(data=True) if a.get("family") == "memory"]
    assert len(hers) == 1
    assert graph.nodes[hers[0]]["survival"] == 0, "nothing has landed after it yet"

    # Bob appends in a later push; the shared history has now moved on past her belief.
    _as(monkeypatch, "bob", "remember", "greet is called from the CLI", "--why", "call site",
        "--concerns", SYM, "--new", "--repo", str(bob))
    _as(monkeypatch, "bob", "sync", "--repo", str(bob))
    graph, _ = build_graph(bob, config)
    assert graph.nodes[hers[0]]["survival"] == 1, "her belief outlived bob's later append"


# ============================================================================================
# An unreachable remote — recoverable weather, and the file log is the retry queue
# ============================================================================================


class _DeadRemote:
    """A remote that is simply not there — every call fails at the transport."""

    def __init__(self, *a, **kw):
        pass

    def _die(self, *a, **kw):
        from yigraf.sync import RemoteUnavailable
        raise RemoteUnavailable("http://localhost:0 is unreachable (Connection refused)")

    head = pull = push = _die


class _DiesAfter:
    """A remote that accepts ``n`` pushes and then drops — the mid-push failure the retry must survive."""

    def __init__(self, inner, n: int) -> None:
        self.inner, self.left = inner, n

    def head(self, project):
        return self.inner.head(project)

    def pull(self, project, since_seq):
        return self.inner.pull(project, since_seq)

    def push(self, project, assertions):
        if self.left <= 0:
            from yigraf.sync import RemoteUnavailable
            raise RemoteUnavailable("http://localhost:0 is unreachable (Connection reset)")
        self.left -= 1
        return self.inner.push(project, assertions)


def test_an_unreachable_remote_is_guidance_not_a_traceback(tmp_path, monkeypatch):
    """Being offline is not a tool failure: exit 0 with guidance, so an agent doesn't learn to stop
    calling sync over a dropped connection (design law #1, same contract as the token/config gaps)."""
    monkeypatch.setattr(sync_mod, "HttpRemote", _DeadRemote)
    monkeypatch.setenv(TOKEN_ENV, "test-token")
    ws = _workspace(tmp_path / "a")
    out = runner.invoke(app, ["sync", "--repo", str(ws)])
    assert out.exit_code == 0, out.output
    assert "Couldn't reach" in out.output
    assert "committed file log" in out.output and "next" in out.output


def test_a_mid_push_drop_defers_the_rest_and_the_next_sync_sends_them(tmp_path, monkeypatch):
    """The retry story end-to-end: the remote dies after the first of two pushes. The run reports the
    deferral instead of crashing, keeps what landed, and a later run — deriving its push set from the
    file log, not a queue — sends exactly the remainder."""
    log = OnlineLog(SqliteAssertionStore(), PROJECT, signer_key=SERVER_KEY)
    flaky = _DiesAfter(_ServerLike(log, "test-token"), n=1)
    monkeypatch.setattr(sync_mod, "HttpRemote", lambda url, token, **kw: flaky)
    monkeypatch.setenv(TOKEN_ENV, "test-token")

    ws = _workspace(tmp_path / "a")
    for text in ("greet must not log the name", "greet must stay pure"):
        assert runner.invoke(app, ["remember", text, "--why", "PII", "--concerns", SYM,
                                   "--repo", str(ws)]).exit_code == 0

    dropped = runner.invoke(app, ["sync", "--repo", str(ws)])
    assert dropped.exit_code == 0, dropped.output
    assert "lost the remote mid-push" in dropped.output
    assert "1 pushed, 1 deferred" in dropped.output
    assert log.store.head(PROJECT).seq == 1, "only the first push landed"

    flaky.left = 5  # the remote comes back
    recovered = runner.invoke(app, ["sync", "--repo", str(ws)])
    assert recovered.exit_code == 0, recovered.output
    assert "pushed 1" in recovered.output, "the deferred assertion goes out, and only it"
    assert log.store.head(PROJECT).seq == 2

    third = runner.invoke(app, ["sync", "--repo", str(ws)])
    assert "pushed 0" in third.output, "nothing re-sends once the log has it (no duplicates)"
    assert log.store.head(PROJECT).seq == 2


class _RefusingRemote:
    """A remote that answers every call with one HTTP status — the credential/authorization refusals.

    ``HttpRemote`` re-raises a non-429 4xx as itself on purpose (it fails identically on every retry,
    so it must not read as "try again later"), which makes the *CLI* the only place that can turn it
    into something an operator can act on.
    """

    def __init__(self, code: int, reason: str = "Refused") -> None:
        self.code, self.reason = code, reason

    def _refuse(self):
        import io
        import urllib.error
        raise urllib.error.HTTPError("https://api.example/x", self.code, self.reason, {}, io.BytesIO(b""))

    def head(self, project):
        self._refuse()

    def pull(self, project, since_seq):
        self._refuse()

    def push(self, project, assertions):
        self._refuse()


@pytest.mark.parametrize("code, expected", [
    (401, "rejected your credential"),
    (403, "refused this operation"),
    (404, "no project"),
    (418, "refused the request"),  # anything else still explains itself rather than raising
])
def test_a_refused_credential_is_guidance_not_a_traceback(tmp_path, monkeypatch, code, expected):
    """A bad/expired/revoked token must not reach the operator as a Typer traceback.

    This is design law #1's sharpest case: the condition is *entirely* fixable by the caller, so a
    stack trace teaches "sync is broken, stop calling it" when the truth is "your token is stale".
    Exit 0 with the fix, exactly as the missing-token and unset-config gaps already do.
    """
    monkeypatch.setattr(sync_mod, "HttpRemote", lambda url, token, **kw: _RefusingRemote(code))
    monkeypatch.setenv(TOKEN_ENV, "stale-token")
    ws = _workspace(tmp_path / "a")

    out = runner.invoke(app, ["sync", "--repo", str(ws)])

    assert out.exit_code == 0, out.output
    assert "Traceback" not in out.output
    assert expected in out.output
    assert "nothing local was touched" in out.output


def test_a_404_does_not_guess_between_absent_and_forbidden(tmp_path, monkeypatch):
    """The server answers 404 identically for "no such project" and "not a member" so that membership
    is not an existence oracle (docs/online-access.md B4). The client's message must preserve that —
    naming either one would re-leak precisely what the route refused to say."""
    monkeypatch.setattr(sync_mod, "HttpRemote", lambda url, token, **kw: _RefusingRemote(404))
    monkeypatch.setenv(TOKEN_ENV, "some-token")
    ws = _workspace(tmp_path / "a")

    out = runner.invoke(app, ["sync", "--repo", str(ws)])

    assert "doesn't exist or your credential isn't a member" in out.output
    assert "deliberately doesn't say which" in out.output

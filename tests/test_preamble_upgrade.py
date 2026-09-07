"""The committed session preamble stops being a copy that upgrades can't reach (1.11.0).

``preamble_behind`` (feedback-v6 F#1) could *report* the two-copy hazard but not end it: the remedy it
named was a by-hand paste, which is a chore that scales with the number of users, and every release
that amended the default minted the hazard afresh in every repo initialized before it. Three changes
close it, and this module pins each to the failure it prevents:

* ``init`` writes the preamble **commented out**, so the key is absent and the shipped text flows
  through on every upgrade — no new copies are minted;
* every ``install`` verb retires an existing stale copy under the *same* byte-exact guard that raises
  the nudge, so the remedy is a command;
* the nudge names that command.

The guard is the load-bearing part, and most of what follows is about what must NOT happen: a
preamble a team wrote is theirs, and no code path here may touch it.
"""
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

from yigraf.cli import app
from yigraf.config import (DEFAULT_SESSION_PREAMBLE, SUPERSEDED_SESSION_PREAMBLES,
                           commented_preamble_block, load_config, preamble_behind,
                           refresh_preamble)

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    return tmp_path


def _config(root: Path) -> Path:
    return root / "yigraf" / "config.yaml"


class _TtyStdout:
    """The runner's captured stdout, claiming to be a terminal."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def isatty(self) -> bool:
        return True


class _TtySys:
    """``yigraf.cli.sys`` with a tty-claiming ``stdout``.

    The human-facing notes in `status` are gated on ``sys.stdout.isatty()`` so a piped statusline never
    swallows them (feedback-v5 A), and `CliRunner` is not a tty — so without this the guidance strings
    an agent and a user actually read are untestable. Resolved lazily on each access because the runner
    installs its capture *after* the patch.
    """

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    @property
    def stdout(self):
        return _TtyStdout(self._real.stdout)


def _stale(root: Path) -> Path:
    """Rewrite config.yaml the way an `init` through 1.10.0 wrote it: a LIVE key, 1.8.0's text."""
    body = "\n".join(f"    {line}".rstrip()
                     for line in SUPERSEDED_SESSION_PREAMBLES[0].rstrip("\n").splitlines())
    cfg = _config(root)
    cfg.write_text(cfg.read_text().replace(commented_preamble_block(),
                                           f"  preamble: |\n{body}"))
    assert preamble_behind(load_config(cfg)), "the fixture must reproduce a genuinely stale file"
    return cfg


# ── A: no new copies are minted ────────────────────────────────────────────────────────────────────


def test_a_fresh_repo_carries_no_preamble_copy(tmp_path: Path):
    """The root cause. A live key in a committed file is a second copy of text the CLI already owns,
    and it wins at read time — so every later release strands the repo. Absent, it cannot go stale."""
    cfg = _config(_repo(tmp_path))

    assert "preamble" not in (yaml.safe_load(cfg.read_text())["session_start"])
    assert load_config(cfg)["session_start"]["preamble"] == DEFAULT_SESSION_PREAMBLE
    assert not preamble_behind(load_config(cfg))


def test_the_absent_key_still_documents_itself_in_the_file(tmp_path: Path):
    """Absent must not mean invisible: reading the config is how a team learns the channel exists.
    The full text rides along commented, which is why this is a fix and not a feature removal."""
    text = _config(_repo(tmp_path)).read_text()

    assert commented_preamble_block() in text
    for line in DEFAULT_SESSION_PREAMBLE.strip().splitlines():
        assert line in text


def test_uncommenting_the_block_yields_exactly_the_live_key(tmp_path: Path):
    """Owning the preamble must be one editor command, not a retype — otherwise the commented form is
    a downgrade for the team the committed file exists to serve."""
    cfg = _config(_repo(tmp_path))
    uncommented = "\n".join(line.replace("# ", "", 1) if line.strip().startswith("#   ")
                            or line.strip() == "# preamble: |" else line
                            for line in cfg.read_text().splitlines())

    assert yaml.safe_load(uncommented)["session_start"]["preamble"] == DEFAULT_SESSION_PREAMBLE


# ── B: an existing stale copy is retired by a command ──────────────────────────────────────────────


def test_install_retires_a_stale_committed_preamble(tmp_path: Path):
    """The whole point: the user runs one verb they already run after upgrading, and the repo is
    current. No paste, nothing to relay to a teammate, nothing that scales with the user count."""
    root = _repo(tmp_path)
    cfg = _stale(root)

    result = runner.invoke(app, ["install", str(root), "--host", "mcp"])

    assert result.exit_code == 0
    assert "preamble" in result.output
    assert not preamble_behind(load_config(cfg))
    assert load_config(cfg)["session_start"]["preamble"] == DEFAULT_SESSION_PREAMBLE


def test_retiring_lands_the_repo_where_a_fresh_init_would_have(tmp_path: Path):
    """A migration that writes today's text back as a live key only resets the clock — the repo goes
    stale again next release. Retiring means reaching the same end state a 1.11 `init` produces."""
    stale_root, fresh_root = _repo(tmp_path / "a"), _repo(tmp_path / "b")
    _stale(stale_root)

    assert runner.invoke(app, ["install", str(stale_root), "--host", "mcp"]).exit_code == 0

    assert _config(stale_root).read_text() == _config(fresh_root).read_text()


def test_every_install_verb_retires_it_not_just_the_umbrella(tmp_path: Path):
    """`⬆ skill` tells people to run `install-claude-hooks`, so that is the verb many will reach for.
    A remedy that only one entry point carries is a remedy most users never trigger."""
    root = _repo(tmp_path)
    cfg = _stale(root)

    assert runner.invoke(app, ["install-claude-hooks", str(root)]).exit_code == 0

    assert not preamble_behind(load_config(cfg))


def test_the_nudge_names_the_command_that_clears_it(tmp_path: Path, monkeypatch):
    """Guidance whose remedy is 'edit this file yourself' is what this release exists to retire."""
    root = _repo(tmp_path)
    _stale(root)
    monkeypatch.setattr("yigraf.cli.sys", _TtySys(sys))

    output = runner.invoke(app, ["status", "--repo", str(root)]).output

    assert "⬆ preamble" in output
    assert "yigraf install" in output
    assert "cheatsheet --preamble" not in output


# ── The guard: a preamble that is theirs is never touched ──────────────────────────────────────────


def test_install_never_rewrites_a_preamble_the_team_wrote(tmp_path: Path):
    """The line that makes writing to a committed, user-owned file defensible at all. `refresh_preamble`
    acts only on a byte-exact copy of text WE shipped — proof the content is ours, not theirs."""
    root = _repo(tmp_path)
    cfg = _stale(root)
    cfg.write_text(cfg.read_text().replace("[yigraf] Standing rules for this session",
                                           "[acme] House rules for this session"))
    before = cfg.read_text()

    assert runner.invoke(app, ["install", str(root), "--host", "mcp"]).exit_code == 0

    assert cfg.read_text() == before


def test_a_current_preamble_pinned_by_hand_is_left_alone(tmp_path: Path):
    """A team that deliberately pinned today's text has made a choice — that it happens to match what
    we ship does not make it ours to delete. Only a *superseded* copy is provably abandoned."""
    root = _repo(tmp_path)
    cfg = _config(root)
    body = "\n".join(f"    {line}".rstrip()
                     for line in DEFAULT_SESSION_PREAMBLE.rstrip("\n").splitlines())
    cfg.write_text(cfg.read_text().replace(commented_preamble_block(), f"  preamble: |\n{body}"))
    before = cfg.read_text()

    assert runner.invoke(app, ["install", str(root), "--host", "mcp"]).exit_code == 0

    assert cfg.read_text() == before


def test_an_empty_preamble_is_left_alone(tmp_path: Path):
    """`preamble: ""` is the documented way to silence the channel. Retiring it would turn the rules
    back on for a repo that switched them off — the loudest possible false positive."""
    root = _repo(tmp_path)
    cfg = _config(root)
    cfg.write_text(cfg.read_text().replace(commented_preamble_block(), '  preamble: ""'))

    assert runner.invoke(app, ["install", str(root), "--host", "mcp"]).exit_code == 0

    assert load_config(cfg)["session_start"]["preamble"] == ""


def test_install_plan_writes_nothing(tmp_path: Path):
    """--plan is inspect-only, and this is the one thing `install` touches that git tracks."""
    root = _repo(tmp_path)
    cfg = _stale(root)
    before = cfg.read_text()

    assert runner.invoke(app, ["install", str(root), "--plan"]).exit_code == 0

    assert cfg.read_text() == before


def test_a_read_command_never_rewrites_the_file(tmp_path: Path):
    """`status` raises the nudge and must not act on it. An unrequested write into a committed file
    during a read is what mem:91fe59a8463b851d rejected, and that rejection still stands."""
    root = _repo(tmp_path)
    cfg = _stale(root)
    before = cfg.read_text()

    assert runner.invoke(app, ["status", "--repo", str(root)]).exit_code == 0

    assert cfg.read_text() == before


def test_an_ambiguous_file_is_declined_rather_than_guessed_at(tmp_path: Path):
    """The splice is textual (a YAML round trip would discard every comment in the file, which is
    where all the knob documentation lives). Where the text can't be placed unambiguously, leaving the
    nudge standing one more release costs far less than a wrong edit to a committed file."""
    root = _repo(tmp_path)
    cfg = _stale(root)
    cfg.write_text(cfg.read_text() + '\npreamble: "a second live key we cannot choose between"\n')

    assert refresh_preamble(cfg) is False
    assert preamble_behind(load_config(cfg)), "declining must leave the nudge in place"


# ── The maintenance invariant the whole mechanism rests on ─────────────────────────────────────────


def test_the_current_default_is_not_also_listed_as_superseded():
    """Detection is a byte-exact match against what we once shipped. If the current text ever appears
    in that tuple, every up-to-date repo is nudged forever and `install` deletes a live default — the
    two failures that would train people to ignore the signal."""
    assert DEFAULT_SESSION_PREAMBLE not in SUPERSEDED_SESSION_PREAMBLES


def test_every_superseded_preamble_is_still_detected():
    """The tuple is append-only by hand: amending the default without appending the outgoing text
    leaves every repo carrying it silently unreported, because the nudge can only fire on text we can
    prove we shipped."""
    for old in SUPERSEDED_SESSION_PREAMBLES:
        assert preamble_behind({"session_start": {"preamble": old}})

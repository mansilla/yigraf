"""Binding a workspace to a hosted project — the client half of code-based linking.

The model, in one line: **humans do all identity work in the browser; the CLI never authenticates a
human and never meets a stranger.** Accounts, projects and invitations live in the web UI. A member who
wants to bring a workspace online generates a *link code* for their own machine and pastes it into one
command, which redeems it for a per-machine token, checks that this repo and that project are about the
same codebase, and binds the two.

So the whole of this module is: find the code, ask what it points at, decide whether it fits, spend it,
and remember the credential. There is no OIDC client here, no browser, no callback port, no refresh, no
per-host registration — and a self-hoster runs the identical flow against their own server.

Three things are load-bearing:

* **The code is a redemption code, not the credential.** Redeeming returns a long-lived machine token;
  the code is spent at that moment. If the pasted string were itself the bearer token, every assertion
  authored through it would carry the same ``actor`` and the audit trail would say nothing.
* **The token never goes in ``config.yaml``.** That file is committed, and a token in git is a leaked
  token. It goes in ``~/.config/yigraf/credentials.json``, mode 0600, keyed by remote host.
* **Repo identity is the root commit, not the remote URL.** A URL changes on rename, re-host or org
  move; the root commit survives all three, and two clones of one history agree on it with no
  coordination.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from yigraf.sync import WIRE_VERSION

#: Where a machine token lives. Not the workspace: a credential is per-machine and per-remote, while
#: ``yigraf/config.yaml`` is per-repo AND committed.
CREDENTIALS_FILENAME = "credentials.json"

INVITE_PREFIX = "ygi_"
LINK_PREFIX = "ygl_"
TOKEN_PREFIX = "ygf_"


class LinkError(Exception):
    """A bind could not proceed. ``guidance`` is written for the person at the terminal: hand back the
    fix, not an error (design law #1)."""

    def __init__(self, code: str, guidance: str) -> None:
        super().__init__(guidance)
        self.code = code
        self.guidance = guidance


# ---------------------------------------------------------------------------------------------
# The credentials file
# ---------------------------------------------------------------------------------------------


def credentials_path() -> Path:
    """``$XDG_CONFIG_HOME/yigraf/credentials.json``, or ``~/.config/yigraf/…``."""
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "yigraf" / CREDENTIALS_FILENAME


def read_credentials(path: Path | None = None) -> dict[str, dict]:
    path = path or credentials_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # a corrupt file must not make the CLI unusable; re-linking rewrites it
    return loaded if isinstance(loaded, dict) else {}


def store_credential(remote: str, record: dict, path: Path | None = None) -> Path:
    """Write (or replace) the credential for one remote, leaving the others alone.

    The file is created 0600 *before* anything is written to it, and the directory 0700 — a token that
    is world-readable for even a moment is a leaked token."""
    path = path or credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    creds = read_credentials(path)
    creds[remote.rstrip("/")] = record
    path.touch(mode=0o600, exist_ok=True)
    os.chmod(path, 0o600)
    path.write_text(json.dumps(creds, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def credential_for(remote: str, path: Path | None = None) -> dict | None:
    return read_credentials(path).get((remote or "").rstrip("/"))


def resolve_token(remote: str, env_var: str = "YIGRAF_TOKEN", path: Path | None = None) -> str | None:
    """Token resolution order: the environment wins, then the credentials file.

    The env var is first for CI and containers, where the token comes from a secret store and there is
    no interactive link step to have written a file."""
    from_env = os.environ.get(env_var)
    if from_env:
        return from_env
    record = credential_for(remote, path)
    return record.get("token") if record else None


# ---------------------------------------------------------------------------------------------
# Repo identity
# ---------------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def repo_fingerprint(repo: Path) -> str | None:
    """The repository's root-commit SHA, or ``None`` when it cannot be known.

    ``None`` means *unknown*, never *mismatch* — it is allowed, and simply leaves the project's
    fingerprint unclaimed. Two cases produce it:

    * **A shallow clone.** The "root" a shallow clone reports is the graft boundary, and it varies with
      clone depth — sending it would claim a wrong identity, which is worse than claiming none.
    * **No git at all.** Nothing to fingerprint.

    More than one root (a grafted or merged history) sorts and takes the first: deterministic, and
    stable for as long as the history is."""
    if _git(repo, "rev-parse", "--is-shallow-repository") == "true":
        return None
    roots = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    if not roots:
        return None
    return sorted(roots.split())[0]


# ---------------------------------------------------------------------------------------------
# The link handshake
# ---------------------------------------------------------------------------------------------


def parse_link(argument: str, remote: str | None = None) -> tuple[str, str]:
    """``(remote, code)`` from either a full link URL or a bare code plus ``--remote``.

    The URL form is preferred because it carries the host, so the user never types the remote — and
    because a code copied without its host is ambiguous the moment someone runs a second server."""
    argument = (argument or "").strip()
    if argument.startswith(INVITE_PREFIX) or f"/invite/{INVITE_PREFIX}" in argument:
        raise LinkError(
            "wrong_credential_kind",
            "That's a human invitation, not a machine link code. Open it in a browser to join the "
            "project; then generate a link code from the project's Machines tab and paste THAT here.")
    if "://" in argument:
        base, _, code = argument.rstrip("/").rpartition("/link/")
        if not base or not code:
            raise LinkError("bad_link_url",
                            f"'{argument}' doesn't look like a link URL. It should end in "
                            f"/link/{LINK_PREFIX}… — copy it again from the project's Machines tab.")
        return base.rstrip("/"), code
    if not remote:
        raise LinkError("no_remote",
                        f"'{argument}' is a bare code with no host, so yigraf doesn't know which "
                        f"server to redeem it against. Paste the full URL you were given, or add "
                        f"--remote https://your-server.")
    return remote.rstrip("/"), argument


def _request(method: str, url: str, body: dict | None = None, timeout: float = 15.0) -> Any:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Accept", "application/json")  # a browser gets a page here; we want the contract
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read() or b"{}")
        except (OSError, ValueError):
            detail = {}
        raise LinkError(detail.get("error") or f"http_{exc.code}",
                        _explain(detail, exc.code, url, detail)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise LinkError("unreachable",
                        f"Couldn't reach {url} ({reason}). Nothing was created or spent — check the "
                        f"host and your network, then run the same command again.") from exc


#: Every way the server can refuse, said in words the person at the terminal can act on.
_EXPLAIN = {
    "unknown_code": "The server doesn't recognize that link code. Generate a fresh one from the "
                    "project's Machines tab in the console.",
    "code_expired": "That link code has expired — they last about 15 minutes on purpose. Generate a "
                    "fresh one from the project's Machines tab.",
    "code_redeemed": "That link code has already been used. Each one binds a single workspace; "
                     "generate another for this machine.",
    "code_revoked": "That link code was revoked. Ask for a new one.",
    "wrong_credential_kind": "That's a human invitation, not a machine link code — open it in a "
                             "browser to join the project, then generate a link code for this machine.",
    "not_a_member": "The account that generated this code is no longer a member of the project, so it "
                    "can't bind anything. Ask a project owner to re-invite them.",
}


def _explain(detail: dict, status: int, url: str, body: dict) -> str:
    error = detail.get("error")
    if error in _EXPLAIN:
        return _EXPLAIN[error]
    if error == "repo_mismatch":
        return _mismatch_guidance(body.get("project_fingerprint"))
    if error == "wire_unsupported":
        return (f"This yigraf speaks wire version {WIRE_VERSION}, and the server speaks "
                f"{body.get('wire_versions')}. Upgrade yigraf (or the server) — an unsupported wire "
                f"means the assertions wouldn't round-trip, so binding is refused rather than risked.")
    return f"{url} refused the request ({status}). {detail.get('detail') or ''}".strip()


def _mismatch_guidance(project_fingerprint: str | None, local: str | None = None) -> str:
    theirs = (f"it expects root commit {project_fingerprint[:12]}" if project_fingerprint
              else "it expects a different repository")
    mine = f", and this repo's is {local[:12]}" if local else ""
    return (f"This online project is about a different repository — {theirs}{mine}.\n"
            f"Binding anyway would leave every implements/concerns edge in the shared graph anchored "
            f"to code that isn't here: it would still fold, still render, and be quietly meaningless. "
            f"Check you're in the right workspace and that the code is for the right project. "
            f"If you're certain, re-run with --force.")


def preflight(remote: str, code: str) -> dict:
    """``GET /link/<code>`` — everything needed to decide, with no side effects.

    Two calls rather than one precisely so a failed compatibility check does not burn the user's
    single-use code."""
    return _request("GET", f"{remote}/link/{code}")


def redeem(remote: str, code: str, *, repo_fingerprint: str | None, label: str | None,
           engine_version: str, wire_version: int) -> dict:
    """``POST /link/<code>`` — spend the code for a machine token. The token comes back exactly once."""
    return _request("POST", f"{remote}/link/{code}", {
        "repo_fingerprint": repo_fingerprint,
        "engine_version": engine_version,
        "wire_version": wire_version,
        "label": label,
    })


def whoami(remote: str, token: str) -> dict:
    """``GET /me`` — which identity is this workspace pushing as."""
    req = urllib.request.Request(f"{remote.rstrip('/')}/me", method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise LinkError(f"http_{exc.code}",
                        f"{remote} rejected this workspace's credential ({exc.code}). It may have "
                        f"been revoked — re-run `yigraf online <url>` with a fresh link code.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LinkError("unreachable", f"Couldn't reach {remote} ({getattr(exc, 'reason', exc)}).") from exc


# ---------------------------------------------------------------------------------------------
# The three checks
# ---------------------------------------------------------------------------------------------


def check_compatibility(info: dict, local_fingerprint: str | None, *, force: bool = False) -> None:
    """Repo identity and wire version, decided from the preflight alone.

    Not checked: whether either side already holds assertions. Merging is a commutative set-union by
    ``event_key``, and a genuine disagreement surfaces later as a knowledge-conflict rather than a bind
    failure — a non-empty workspace binding to a non-empty project is normal and supported."""
    theirs = info.get("repo_fingerprint")
    if theirs and local_fingerprint and theirs != local_fingerprint and not force:
        raise LinkError("repo_mismatch", _mismatch_guidance(theirs, local_fingerprint))

    wires = info.get("wire_versions") or []
    if wires and WIRE_VERSION not in wires:
        # No --force here, deliberately: a repo mismatch is a judgement call a human can overrule,
        # while an unsupported wire means the events would not round-trip. There is nothing to override.
        raise LinkError("wire_unsupported",
                        f"This yigraf speaks wire version {WIRE_VERSION}; {info.get('project')} "
                        f"speaks {wires}. Upgrade yigraf (or the server) before binding.")


def check_replica(replica: Path, current_project: str | None, current_remote: str | None,
                  project: str, remote: str, *, force: bool = False) -> Path | None:
    """The third check: a replica already carrying a cursor for a *different* project or remote.

    Returns the path it was moved aside to, or ``None`` if nothing needed moving. The replica is never
    deleted — it holds a verified Merkle cursor, and silently discarding one to save a keystroke is how
    a person loses the only local copy of something."""
    if not replica.exists():
        return None
    same = (current_project or project) == project and (current_remote or remote).rstrip("/") == remote
    if same:
        return None
    if not force:
        raise LinkError("replica_bound",
                        f"This workspace's replica is already bound to '{current_project}' at "
                        f"{current_remote}. Binding it to '{project}' at {remote} would strand that "
                        f"one — its cursor is scoped per project.\n"
                        f"Re-run with --force to move the replica aside (it is renamed, never deleted) "
                        f"and start clean.")
    backup = _next_backup(replica)
    replica.rename(backup)
    return backup


def _next_backup(replica: Path) -> Path:
    n = 1
    while (candidate := replica.with_suffix(replica.suffix + f".bak-{n}")).exists():
        n += 1
    return candidate


def default_label(repo: Path) -> str:
    """``<hostname>:<repo-dir>`` — without it the project page's machine list reads 'machine 1..7' and
    revoking the right one becomes guesswork."""
    import socket

    host = socket.gethostname().split(".")[0]
    return f"{host}:{Path(repo).resolve().name}"

"""Client-side sync: keep a local replica of the online assertion log in step with the hosted remote,
so reads/hooks run LOCAL (fast, fail-open, design laws #3/#5) while writes append to the shared log
through the API (int:yigraf-online-v1). The client speaks only to the API — the DB is never exposed.

**git-shaped by design (mem:058/059).** The remote is the authority for ORDER (monotonic seq + the
Merkle chain, task #8); the client holds a :class:`~yigraf.onlinelog.SqliteAssertionStore` replica and
reconciles by comparing head hashes — a cheap :meth:`RemoteClient.head` tells it whether to pull. A
pull returns the delta since the replica's cursor; the client verifies that delta cryptographically
chains from the cursor it last saw to the advertised head before folding it in.

**Sync is conflict-free by construction.** Assertions are content-addressed (mem:063) and the fold
re-derives belief from the whole set (mem:065017c0), so reconciling two logs is a commutative
set-union by ``event_key`` — there is no CRDT merge to write, and no last-writer-wins. A genuine
disagreement (two live beliefs on one anchor) is NOT a sync failure; it surfaces later as an explicit
knowledge-conflict via the async contradiction sweep (task #4), exactly as int:concurrent-write-model
requires.

**Transport-agnostic (mem:059 again).** The sync logic here talks to a :class:`RemoteClient` PORT, so
it is provable offline against :class:`LoopbackRemote` (an in-process server-side
:class:`~yigraf.onlinelog.OnlineLog`, the test double for the API), and the real HTTP client
(``HttpRemote``, in the closed-source server's client SDK) is a thin adapter over the same three calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

from yigraf.log import Assertion
from yigraf.onlinelog import (
    GENESIS_HASH,
    OnlineLog,
    SqliteAssertionStore,
    StoredEvent,
    chain_hash,
    event_key,
    sign_provenance,
)


@dataclass
class RemoteHead:
    """A compact, cheap description of the remote log's tail — the reconcile-by-head-hash token."""

    seq: int
    head_hash: str


class SyncError(Exception):
    """The pulled delta did not cryptographically chain from the replica's cursor to the advertised
    head (a gap, a reorder, or a tampered/forked remote). Fail LOUD here — unlike a routine hook, a
    corrupt sync must not silently poison the replica."""


class RemoteUnavailable(Exception):
    """The remote could not be reached, or answered with a *transient* failure (5xx / 429).

    The third failure mode, and the only RECOVERABLE one — kept distinct because the three want
    opposite handling. :class:`~yigraf.onlinelog.IngestRejected` is permanent (the assertion is
    malformed; re-sending changes nothing, so the run reports it and moves on). :class:`SyncError` is
    an integrity break (a stop, loud, replica untouched). This one is just weather: nothing is wrong
    with the client, the replica, or the assertion, so the correct response is to say so plainly and
    let the *next* run carry the work — see :func:`push_assertion` on why no queue is needed.

    A 4xx that isn't 429 is deliberately NOT wrapped: a bad token or a wrong project URL fails
    identically on every retry, so it must surface as itself rather than read as "try again later".
    """


@runtime_checkable
class RemoteClient(Protocol):
    """The API the client speaks (never the DB). Three calls — the whole online transport surface.
    :class:`LoopbackRemote` realizes it in-process for offline tests; the HTTP client realizes it over
    the network. Ordering/validation/signing all happen on the far side (the server)."""

    def head(self, project: str) -> RemoteHead:
        """The remote log's current head (seq + Merkle head hash), or genesis if empty — the cheap
        poll a client compares to its cursor to decide whether to pull."""

    def pull(self, project: str, since_seq: int) -> list[StoredEvent]:
        """Every event with ``seq > since_seq``, in remote seq order, carrying the server-signed
        provenance + chain hashes so the client can verify integrity and fold them in."""

    def push(self, project: str, assertions: list[Assertion]) -> list[StoredEvent]:
        """Submit assertions for append. The server validates (structural/causal), signs provenance,
        chains, and assigns seq — returning the authoritative stored events. Idempotent by
        ``event_key`` (a re-push of identical content collapses, never duplicates)."""


@dataclass
class SyncResult:
    """What a :func:`sync` did: how many events it pulled and the head it reconciled to."""

    pulled: int
    head: RemoteHead
    already_current: bool


def sync(store: SqliteAssertionStore, remote: RemoteClient, project: str) -> SyncResult:
    """Reconcile the local replica ``store`` with ``remote`` for ``project`` (reconcile-by-head-hash).

    Cheap no-op when the replica's cursor already equals the remote head. Otherwise pull the delta,
    verify it chains from the cursor to the remote head (:class:`SyncError` on a break), fold each event
    into the replica verbatim (idempotent), and advance the cursor. Order-independent and re-runnable:
    running it twice, or racing two clients, converges to the same replica (the commutative set-union)."""
    cursor_seq, cursor_head = store.get_cursor(project)
    rhead = remote.head(project)
    if rhead.seq == cursor_seq and rhead.head_hash == cursor_head:
        return SyncResult(pulled=0, head=rhead, already_current=True)

    events = remote.pull(project, cursor_seq)
    _verify_delta(events, cursor_head, rhead)
    for event in events:
        store.upsert_event(project, event)
    store.set_cursor(project, rhead.seq, rhead.head_hash)
    return SyncResult(pulled=len(events), head=rhead, already_current=False)


def _verify_delta(events: list[StoredEvent], from_head: str, to_head: RemoteHead) -> None:
    """Confirm ``events`` form an unbroken chain segment from ``from_head`` to ``to_head`` — the client
    independently re-deriving the Merkle links, so a server that dropped/reordered/forged an event is
    caught before it reaches the replica. An empty delta must mean the heads already matched."""
    if not events:
        if to_head.head_hash != from_head:
            raise SyncError(f"remote advertised head {to_head.head_hash[:12]} but returned no delta "
                            f"from {from_head[:12]}")
        return
    prev = from_head
    for event in events:
        if event.prev_hash != prev or event.entry_hash != chain_hash(prev, event.event_key):
            raise SyncError(f"pulled delta breaks the chain at seq {event.seq} "
                            f"(id {event.id}) — expected prev {prev[:12]}")
        prev = event.entry_hash
    if prev != to_head.head_hash:
        raise SyncError(f"pulled delta ends at {prev[:12]}, not the advertised head "
                        f"{to_head.head_hash[:12]}")


def push_assertion(store: SqliteAssertionStore, remote: RemoteClient, project: str,
                   assertion: Assertion) -> StoredEvent:
    """Write-through a local authoring write: append to the remote (the authority), then fold the
    authoritative event into the replica so local reads see it immediately. A following :func:`sync`
    advances the cursor past it (idempotent).

    **A failed push needs no queue — the committed file log already is one.** The push set is not a
    buffer this function drains; ``yigraf sync`` re-derives it every run as
    ``[a for a in FileLog(repo) if a.id not in store.known_ids(project)]``. An assertion that never
    reached the remote is therefore still in the file log and still absent from the replica, so the
    next run picks it up unchanged — durably, because the file log is *git-committed* (a queue in
    ``.local/`` would not survive a fresh clone, and would be a second source of truth to reconcile).
    Idempotency makes the retry safe from the other side too: push is keyed by ``event_key``, so a
    write that landed but whose response was lost collapses on re-push rather than duplicating.

    What the caller owes this design is only to *stop* on :class:`RemoteUnavailable` rather than
    treating it as data loss: the work is already persisted, and the next ``yigraf sync`` sends it."""
    authoritative = remote.push(project, [assertion])[0]
    store.upsert_event(project, authoritative)
    # The response is also the only place this workspace is ever told its own name: the authority
    # stamps `actor` from the authenticated principal, so a client cannot derive it (see
    # `assertion_to_wire`). Remember it — `OnlineLog.pending_local_revisions` needs it to tell a
    # revision of mine that the log has not heard yet from a revision another principal still holds.
    actor = (authoritative.provenance or {}).get("actor")
    if actor:
        store.set_actor(project, actor)
    return authoritative


# --------------------------------------------------------------------------------------------------
# LoopbackRemote — the in-process API test double (a server-side OnlineLog over its own store)
# --------------------------------------------------------------------------------------------------


class LoopbackRemote:
    """A :class:`RemoteClient` backed by an in-process server-side :class:`~yigraf.onlinelog.OnlineLog`
    — the offline stand-in for the hosted API, so the whole sync loop is provable with no network. It
    validates + signs + chains exactly as the real server will (same engine), which is the point:
    ``LoopbackRemote`` and the HTTP server share ``OnlineLog``, so a test against the loopback proves
    the client behavior the network deployment relies on (mem:059)."""

    def __init__(self, log: OnlineLog) -> None:
        self.log = log
        self.store = log.store
        self.project = log.project

    def head(self, project: str) -> RemoteHead:
        h = self.store.head(project)
        return RemoteHead(seq=h.seq if h else 0, head_hash=h.entry_hash if h else GENESIS_HASH)

    def pull(self, project: str, since_seq: int) -> list[StoredEvent]:
        return [e for e in self.store.iter_events(project) if e.seq > since_seq]

    def push(self, project: str, assertions: list[Assertion]) -> list[StoredEvent]:
        out: list[StoredEvent] = []
        for assertion in assertions:
            self.log.append(assertion)  # validate → sign → chain → append (raises IngestRejected on bad)
            record = assertion.provenance[0] if assertion.provenance else {}
            signed = sign_provenance(record, self.log.signer_key) if record else {}
            ekey = event_key(assertion.id, assertion.kind, assertion.body,
                             assertion.parents, signed, assertion.scope)
            out.append(self.store.find_event(project, ekey))
        return out


# --------------------------------------------------------------------------------------------------
# Wire format — the JSON shapes the API speaks, single-sourced so client and server can never drift
# --------------------------------------------------------------------------------------------------

#: The version of the four shapes below. Bump it when a change would stop events round-tripping —
#: a new OPTIONAL field that old clients ignore is not a bump; a renamed, removed or re-meant one is.
#:
#: It exists so a bind can be refused rather than risked. A server advertises what it speaks on
#: ``/healthz`` and on the link preflight, and ``yigraf online`` compares before it writes anything:
#: a client that can't round-trip a project's events must find out at bind time, not on the first
#: sync that silently drops a field.
WIRE_VERSION = 1


def assertion_to_wire(assertion: Assertion) -> dict:
    """Serialize a client-submitted :class:`~yigraf.log.Assertion` for ``POST``. The server treats the
    provenance as advisory — it re-stamps ``actor``/``ts`` from the authenticated principal + its clock
    and signs (client-claimed identity is never trusted)."""
    return {"id": assertion.id, "kind": assertion.kind, "body": assertion.body,
            "parents": list(assertion.parents), "provenance": list(assertion.provenance),
            "scope": list(assertion.scope)}


def assertion_from_wire(data: dict) -> Assertion:
    return Assertion(id=data["id"], kind=data["kind"], body=data["body"],
                     parents=tuple(data.get("parents", ())), provenance=list(data.get("provenance", [])),
                     scope=tuple(data.get("scope", ())))


def event_to_wire(event: StoredEvent) -> dict:
    """Serialize an authoritative :class:`~yigraf.onlinelog.StoredEvent` for ``pull``/``push`` replies —
    the full row incl. server-signed provenance + chain hashes, so the client verifies + folds it in."""
    return {"seq": event.seq, "id": event.id, "kind": event.kind, "body": event.body,
            "parents": list(event.parents), "provenance": event.provenance, "scope": list(event.scope),
            "prev_hash": event.prev_hash, "entry_hash": event.entry_hash, "event_key": event.event_key}


def event_from_wire(data: dict) -> StoredEvent:
    return StoredEvent(seq=data["seq"], id=data["id"], kind=data["kind"], body=data["body"],
                       parents=tuple(data.get("parents", ())), provenance=data["provenance"],
                       scope=tuple(data.get("scope", ())), prev_hash=data["prev_hash"],
                       entry_hash=data["entry_hash"], event_key=data["event_key"])


# --------------------------------------------------------------------------------------------------
# The code-structure manifest — the one shape that is NOT an assertion
# --------------------------------------------------------------------------------------------------

#: The manifest's own version, deliberately separate from :data:`WIRE_VERSION`. The two shapes travel
#: the same transport but not the same plane: the assertion wire is the replication protocol every
#: :class:`RemoteClient` implements, while this is a derived snapshot one endpoint accepts. Versioning
#: them together would force a bind-refusing bump on every client for a change only the snapshot made.
STRUCTURE_WIRE_VERSION = 1


class StructureRefused(Exception):
    """The server refused a code-structure snapshot, and NAMED the refusal (``dirty_tree``,
    ``repo_mismatch``, ``empty_manifest``, ``manifest_too_large``, …).

    Distinct from :class:`~yigraf.onlinelog.IngestRejected`, which is about a malformed *assertion*:
    nothing here is being appended to the log, so nothing here can be rejected by ingest. Distinct from
    :class:`RemoteUnavailable` too — every one of these codes fails identically on a retry, so the
    caller has to be told the fix rather than told to wait (design law #1)."""

    def __init__(self, code: str, detail: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail or {}


def structure_manifest(graph) -> list[dict]:
    """Every structure node the local view holds, as four fields: locator, body hash, algo, kind.

    **No source, no bodies, no docstrings** — the locators are already what the anchors in the log
    contain, so nothing crosses the wire that was not crossing it already. That is the whole reason a
    server which has never held source can compute drift: drift compares a stamped anchor against a
    symbol's *current* hash, and the hash is the only half it was missing.

    The full set, deliberately — not just the anchored ones. Rename re-anchoring works by looking an
    anchor up among *all* body hashes, so a filtered manifest would turn every renamed or moved symbol
    into a false "symbol not found".

    ``hash_algo`` is passed through as-is, ``None`` included. An undeclared algo is not a gap to fill
    in here: the extractor's ``file:`` nodes carry an astnorm module hash and declare nothing, while a
    minted ``file:``-anchor node carries a raw SHA and says so, so inferring the algo from the
    locator's scheme would compare an astnorm hash against a raw-SHA anchor and report every file
    anchor in the project as drift. The server applies the same default ``compute_drift`` does.
    """
    return [{"id": node_id, "content_hash": attrs["content_hash"],
             "hash_algo": attrs.get("hash_algo"), "kind": attrs.get("kind")}
            for node_id, attrs in graph.nodes(data=True)
            if attrs.get("family") == "structure" and attrs.get("content_hash")]


def replica_log(store: SqliteAssertionStore, project: str) -> OnlineLog:
    """Wrap a synced replica as a read :class:`~yigraf.onlinelog.OnlineLog` for the fold/read path — the
    seam ``context``/``status`` fold onto local structure in online mode. Writes still go through
    :func:`push_assertion` to the remote, so ``require_signed_provenance`` is irrelevant on this read
    wrapper.

    Note the replica's rows are not in the remote's chain order (write-through inserts a local write
    before its pull re-fetches it), so :meth:`OnlineLog.verify_chain` is NOT meaningful here — that is an
    authority-side property. Replica integrity is enforced at *pull* time by :func:`_verify_delta`, which
    re-derives the Merkle links over the delta before folding it in. The fold itself is order-independent
    (it uses causal parents, mem:98d5a556), so local row order never affects the graph."""
    return OnlineLog(store, project, signer_key=None, require_signed_provenance=False)


# --------------------------------------------------------------------------------------------------
# HttpRemote — the real client transport (stdlib urllib; the CLI's link to a hosted yigraf-server)
# --------------------------------------------------------------------------------------------------


class HttpRemote:
    """A :class:`RemoteClient` that talks to a hosted yigraf-server over HTTP. Uses only stdlib
    ``urllib`` so the public client stays dependency-free (the wire format is single-sourced in this
    module, so client and server can't drift). Interchangeable with :class:`LoopbackRemote` — the CLI's
    sync path never knows which it holds (mem:059). The API wire protocol is open even though the server
    implementation is closed, so any compatible server works."""

    def __init__(self, base_url: str, token: str, *, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def head(self, project: str) -> RemoteHead:
        data = self._request("GET", f"/projects/{project}/head")
        return RemoteHead(seq=data["seq"], head_hash=data["head_hash"])

    def pull(self, project: str, since_seq: int) -> list[StoredEvent]:
        data = self._request("GET", f"/projects/{project}/assertions?since={int(since_seq)}")
        return [event_from_wire(e) for e in data["events"]]

    def push(self, project: str, assertions: list[Assertion]) -> list[StoredEvent]:
        body = {"assertions": [assertion_to_wire(a) for a in assertions]}
        data = self._request("POST", f"/projects/{project}/assertions", body)
        return [event_from_wire(e) for e in data["events"]]

    def put_structure(self, project: str, payload: dict) -> dict:
        """``PUT /projects/{p}/structure`` — the one call outside the :class:`RemoteClient` port.

        It is deliberately not on the Protocol: the port speaks *assertions*, and a derived code-
        structure manifest is not one — it rides no log, takes no chain link, and a
        :class:`LoopbackRemote` folding one in would be modelling something the server does elsewhere.
        So this lives on the concrete transport, where the port's shape is unaffected and any other
        :class:`RemoteClient` stays free of it.

        A refusal comes back named, and is raised as :class:`StructureRefused` rather than the bare
        ``HTTPError`` ``_request`` re-raises, because every one of these codes has a specific fix.
        """
        import urllib.error

        try:
            return self._request("PUT", f"/projects/{project}/structure", payload)
        except urllib.error.HTTPError as exc:
            detail = getattr(exc, "body_json", None) or {}
            raise StructureRefused(detail.get("error") or f"http_{exc.code}", detail) from exc

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        import json as _json
        import urllib.error
        import urllib.request

        payload = _json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=payload, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if payload is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return _json.loads(resp.read())
        except urllib.error.HTTPError as exc:  # a rejected write teaches the fix (design law #1)
            try:  # a 5xx often answers in HTML, so the detail parse must not become the error
                body_json = _json.loads(exc.read() or b"{}")
            except (OSError, ValueError):
                body_json = {}
            # An HTTPError's body is a stream: the read above consumes it, so a caller that re-raises
            # and wants the server's named refusal cannot go back for it. Hand the decoded body along
            # on the exception instead (``put_structure`` reads it) — the alternative is a second
            # request plumbing of its own, for a body this handler has already parsed.
            exc.body_json = body_json
            detail = body_json.get("detail") if isinstance(body_json, dict) else None
            if exc.code == 422 and isinstance(detail, dict) and "rejected" in detail:
                from yigraf.onlinelog import IngestRejected
                # IngestRejected takes a LIST of problems and "; "-joins it; the server sends exactly
                # that (``exc.problems``). Wrap a bare string rather than let it iterate per-character.
                rejected = detail["rejected"]
                raise IngestRejected([rejected] if isinstance(rejected, str) else list(rejected)) from exc
            if exc.code == 429 or exc.code >= 500:  # transient: the server is up but can't serve now
                raise RemoteUnavailable(f"{self.base_url} answered {exc.code} {exc.reason}") from exc
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # No answer at all — offline, DNS, refused, TLS, or timed out. HTTPError is a URLError
            # subclass and URLError an OSError subclass, so this clause is reached only for failures
            # the handler above did not already classify.
            reason = getattr(exc, "reason", exc)
            raise RemoteUnavailable(f"{self.base_url} is unreachable ({reason})") from exc

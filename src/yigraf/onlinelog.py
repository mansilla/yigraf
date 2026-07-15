"""The online :class:`~yigraf.log.Log` substrate: an append-only, monotonic-seq, project-scoped event
log with signed provenance + a tamper-evident hash chain (plan tasks #7/#8, int:yigraf-online-v1).

mem:059 settled the shape of this file before it existed: the *only* local↔online difference is a thin
substrate adapter behind the :class:`~yigraf.log.Log` protocol — the fold, the contradiction-detector,
and the query layer are all shared. mem:058 settled *why* it is boring: multi-writer coordination is
"append to an ordered log" (a transactional/pub-sub store does it correctly at throughput), never a
lease over the derived projection. So this module is small on purpose.

**Written against a PORT, not a driver — so it is provable offline (R5, "fast, no network").** The
DB operations live behind :class:`AssertionStore`; the reference adapter is :class:`SqliteAssertionStore`
(stdlib, durable, ordered, replayable — a genuine single-host online substrate, exactly as
:class:`~yigraf.log.InMemoryLog` is the reference for the spine), and :class:`PostgresAssertionStore`
is the production shim behind the ``[postgres]`` extra (psycopg, lazily imported). :class:`OnlineLog`
folds through the SAME :func:`yigraf.log.causal_order` contract as :class:`~yigraf.filelog.FileLog`, so
the online graph is byte-identical to the local one for identical content — the task-#6 "rebuilds
identically" proof carried to the online transport (``tests/test_online.py``).

**The table is an immutable EVENT log, collapse is a read-time fold (the crux).** Each ``append`` is
one physical, never-mutated row (monotonic ``seq``); an identical-content re-assertion by a second
writer (mem:060) is a *new event* the read path collapses (:func:`yigraf.log.merge_assertion`) when it
groups events by id. This is what lets task #8's hash chain hold: rows are append-only, so no collapse
ever rewrites an ``entry_hash``. Contrast the local SQLite view (``graphdb.py``), which is the DERIVED
projection and *is* rebuilt — that view is task #9's read side, never this log.

**Task #7 — ingest is SYNCHRONOUS but STRUCTURAL/CAUSAL ONLY** (:func:`validate_ingest`): the body has
the fold's ``{family, attrs, edges}`` shape, a source claim may not smuggle derived belief
(``_DERIVED_KEYS``), and every causal parent is already in the log (the online log stays prefix-closed,
stricter than :func:`causal_order`'s fail-open replica tolerance). Semantic coherence is NEVER checked
here — that is the async task-#4 sweep (int:yigraf-online-v1: "never a synchronous write gate").

**Task #8 — signed provenance on every assertion + a Merkle/hash chain.** Every online assertion
carries a provenance record ``{actor, session, model, commit_sha, ts, source, sig}``; ``sig`` is an
HMAC over the canonical record so a reader can verify who asserted it (:func:`verify_provenance`). The
seq-ordered log is chained (``entry_hash = H(prev_hash ‖ event_key)``) so any edit/reorder/drop breaks
every later hash (:func:`verify_chain`), and the ``head`` hash is a compact commitment to the whole
log. **Authority rides the EXISTING maturity ladder** (mem:033) — ``source`` is the field
:func:`yigraf.memory.landing_maturity` already reads; online adds signed attribution *around* it, never
a new authority axis.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterable, Protocol, runtime_checkable

from yigraf.fold import _DERIVED_KEYS
from yigraf.log import Assertion, _canonical, causal_order, merge_assertion

#: The genesis ``prev_hash`` every project's chain starts from (mem:058: git's data model, not crypto —
#: a linear Merkle chain, so the head hash commits to the entire ordered log).
GENESIS_HASH = "0" * 64

#: Attribution a signed online provenance record MUST carry (task #8). ``source`` is the one the
#: existing maturity ladder reads (:func:`yigraf.memory.landing_maturity`) — the rest is the signer
#: identity + integrity metadata the local single-writer path never needed.
REQUIRED_PROVENANCE_FIELDS = ("actor", "session", "model", "commit_sha", "ts", "source")

#: The pub/sub channel a writer NOTIFYs on append and the read service (task #9) LISTENs on, so the
#: materialized view converges to current state without polling.
DEFAULT_NOTIFY_CHANNEL = "yigraf_assertions"


class IngestRejected(Exception):
    """A synchronous ingest rejection (structural/causal only — never semantic). Carries the concrete
    problems so the service edge can turn them into agent-facing guidance (design law #1: teach the
    fix, don't just fail). Raised by :meth:`OnlineLog.append`; :func:`validate_ingest` is the pre-flight
    that returns the same list without raising."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


# --------------------------------------------------------------------------------------------------
# Signed provenance + hash chain (task #8) — pure, substrate-independent, so both adapters agree
# --------------------------------------------------------------------------------------------------


def _canonical_blob(value: Any) -> bytes:
    return json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False).encode("utf-8")


def sign_provenance(record: dict, key: bytes | None) -> dict:
    """Return ``record`` with an HMAC ``sig`` over its canonical form (task #8). ``key`` ``None`` ⇒
    return it unchanged (fail-open, R5: a store with no signer configured still ingests — the chain
    alone remains tamper-evident). ``sig`` is excluded from the signed payload so re-signing under a
    rotated key is idempotent w.r.t. :func:`event_key`."""
    if key is None:
        return dict(record)
    payload = {k: v for k, v in record.items() if k != "sig"}
    sig = hmac.new(key, _canonical_blob(payload), hashlib.sha256).hexdigest()
    return {**payload, "sig": sig}


def verify_provenance(record: dict, key: bytes) -> bool:
    """True iff ``record``'s ``sig`` is a valid HMAC of its canonical form under ``key`` (constant-time)."""
    expected = sign_provenance(record, key).get("sig")
    got = record.get("sig")
    return isinstance(got, str) and isinstance(expected, str) and hmac.compare_digest(got, expected)


def event_key(assertion_id: str, kind: str, body: dict, parents: tuple[str, ...],
              record: dict, scope: tuple[str, ...]) -> str:
    """Content-hash of one physical event — its replay-idempotency key. Excludes ``sig`` (so a key
    rotation doesn't mint a spurious event) and ``seq``/chain hashes (assigned by the log). An identical
    re-assertion by the same actor collapses to this same key (skipped on insert); a NEW provenance
    record (an independent rediscovery, mem:060) yields a new key ⇒ a new event the read path unions."""
    unsigned = {k: v for k, v in record.items() if k != "sig"}
    return hashlib.sha256(_canonical_blob({
        "id": assertion_id, "kind": kind, "body": body,
        "parents": sorted(parents), "provenance": unsigned, "scope": sorted(scope),
    })).hexdigest()[:32]


def chain_hash(prev_hash: str, ekey: str) -> str:
    """One link of the tamper-evident chain: ``H(prev_hash ‖ event_key)``. Linear over the seq order,
    so any edit/reorder/drop of an earlier event changes every subsequent ``entry_hash`` (task #8)."""
    return hashlib.sha256(f"{prev_hash}\0{ekey}".encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------------
# Ingest validation (task #7) — synchronous, STRUCTURAL/CAUSAL only (never semantic)
# --------------------------------------------------------------------------------------------------


def validate_ingest(assertion: Assertion, known_ids: set[str],
                    *, require_signed_provenance: bool = True) -> list[str]:
    """Return the structural/causal problems with ``assertion`` (``[]`` ⇒ acceptable). SYNCHRONOUS and
    NON-SEMANTIC by contract (int:yigraf-online-v1): validates the fold's body shape, that a source
    claim doesn't assert its own belief, that every causal parent is already in the log (prefix-closed),
    and — online — that a signed provenance record is present. It NEVER runs the contradiction /
    near-dup check (that is the async task-#4 sweep)."""
    problems: list[str] = []
    body = assertion.body
    if not isinstance(body, dict):
        return ["body must be a mapping of {family, attrs, edges}"]

    family = body.get("family")
    if not isinstance(family, str) or not family:
        problems.append("body.family must be a non-empty string")

    attrs = body.get("attrs", {})
    if not isinstance(attrs, dict):
        problems.append("body.attrs must be a mapping")
    else:
        leaked = _DERIVED_KEYS & set(attrs)
        if leaked:
            problems.append(f"body.attrs may not assert derived belief {sorted(leaked)} — the fold "
                            "derives acceptance/supersession from the whole log (mem:065017c0)")

    edges = body.get("edges", [])
    if not isinstance(edges, list):
        problems.append("body.edges must be a list")
    else:
        for i, edge in enumerate(edges):
            if (not isinstance(edge, dict) or not isinstance(edge.get("relation"), str)
                    or not isinstance(edge.get("target"), str)):
                problems.append(f"body.edges[{i}] must carry string 'relation' and 'target'")

    for parent in assertion.parents:
        if parent not in known_ids:
            problems.append(f"causal parent {parent!r} is not yet in the log — append it first so the "
                            "log stays prefix-closed (mem:98d5a556)")

    if require_signed_provenance:
        if not assertion.provenance:
            problems.append("online assertion requires a provenance record "
                            f"({'/'.join(REQUIRED_PROVENANCE_FIELDS)}) — task #8")
        else:
            record = assertion.provenance[0]
            missing = [f for f in REQUIRED_PROVENANCE_FIELDS
                       if not isinstance(record, dict) or not record.get(f)]
            if missing:
                problems.append(f"provenance record missing required fields: {missing}")
    return problems


# --------------------------------------------------------------------------------------------------
# The store port + its stored-row shape
# --------------------------------------------------------------------------------------------------


@dataclass
class StoredEvent:
    """One immutable row of the append-only event log (task #7). ``provenance`` is the SINGLE record
    for this physical event; the read path unions same-id events' records (mem:060)."""

    seq: int
    id: str
    kind: str
    body: dict
    parents: tuple[str, ...]
    provenance: dict
    scope: tuple[str, ...]
    prev_hash: str
    entry_hash: str
    event_key: str


@dataclass
class ViewRow:
    """The materialized CQRS view for a project (task #9): the folded graph as node-link JSON, stamped
    with the log head it was folded from so a reader can check consistency / current-state."""

    node_link: dict
    head_seq: int
    head_hash: str


@runtime_checkable
class AssertionStore(Protocol):
    """The substrate port: the boring transactional/pub-sub store mem:058 says does coordination
    correctly. :class:`SqliteAssertionStore` is the offline reference; :class:`PostgresAssertionStore`
    is the production shim. All ordering is project-scoped."""

    def append_lock(self, project: str) -> ContextManager:
        """Serialize the head-read + insert critical section per project, so concurrent appends chain
        deterministically. This locks the LOG TAIL, not the derived projection — the coordination
        mem:058 endorses, not the whole-graph lease it retired."""

    def head(self, project: str) -> StoredEvent | None:
        """The highest-``seq`` event for ``project`` (chain head), or ``None`` if empty."""

    def known_ids(self, project: str) -> set[str]:
        """Every assertion id present in ``project`` (for the causal prefix-closed check)."""

    def find_event(self, project: str, ekey: str) -> StoredEvent | None:
        """The event with this :func:`event_key`, or ``None`` — the replay-idempotency probe."""

    def insert_event(self, project: str, event: StoredEvent) -> int:
        """Append ``event`` (assigning the monotonic ``seq``, ignoring the passed ``seq``); return the
        assigned seq. Called only inside :meth:`append_lock` after a :meth:`find_event` miss."""

    def iter_events(self, project: str) -> list[StoredEvent]:
        """Every event for ``project`` in ``seq`` order (the durable insertion order)."""

    def notify(self, channel: str, payload: str) -> None:
        """Publish ``payload`` on ``channel`` (LISTEN/NOTIFY) after a committed append."""

    def subscribe(self, channel: str, handler: Callable[[str], None]) -> None:
        """Register ``handler`` for ``channel`` payloads (drives the task-#9 refold)."""

    def write_view(self, project: str, view: ViewRow) -> None:
        """Persist the materialized CQRS view (task #9), replacing any prior one."""

    def read_view(self, project: str) -> ViewRow | None:
        """Load the materialized CQRS view, or ``None`` if not folded yet."""


# --------------------------------------------------------------------------------------------------
# The online log — one Log implementation over any store (the shared, fully-tested logic)
# --------------------------------------------------------------------------------------------------


class OnlineLog:
    """The online, multi-writer :class:`~yigraf.log.Log`: append-only over an :class:`AssertionStore`,
    with synchronous structural/causal ingest (task #7) and signed-provenance + chained integrity
    (task #8). :meth:`iter_assertions_in_causal_order` collapses the immutable events by id and routes
    them through the shared :func:`causal_order`, so the fold sees exactly what it sees on any other
    substrate (mem:059)."""

    def __init__(self, store: AssertionStore, project: str, *, signer_key: bytes | None = None,
                 channel: str = DEFAULT_NOTIFY_CHANNEL, require_signed_provenance: bool = True) -> None:
        self.store = store
        self.project = project
        self.signer_key = signer_key
        self.channel = channel
        self.require_signed_provenance = require_signed_provenance

    def append(self, assertion: Assertion) -> Assertion:
        """Validate (structural/causal), sign the provenance, chain, and durably append. Idempotent on
        the physical event (a replay collapses, never grows the chain). NOTIFYs on a genuinely new
        event. Returns the merged view of ``assertion.id`` (mem:060). Raises :class:`IngestRejected`
        (never a silent drop) on a structural/causal problem."""
        record = assertion.provenance[0] if assertion.provenance else {}
        problems = validate_ingest(assertion, self.store.known_ids(self.project),
                                   require_signed_provenance=self.require_signed_provenance)
        if problems:
            raise IngestRejected(problems)

        signed = sign_provenance(record, self.signer_key) if record else {}
        ekey = event_key(assertion.id, assertion.kind, assertion.body,
                         assertion.parents, signed, assertion.scope)
        appended: tuple[int, str] | None = None  # (seq, entry_hash) of a genuinely new event
        with self.store.append_lock(self.project):
            if self.store.find_event(self.project, ekey) is None:  # else: exact replay ⇒ idempotent
                head = self.store.head(self.project)
                prev_hash = head.entry_hash if head else GENESIS_HASH
                entry_hash = chain_hash(prev_hash, ekey)
                seq = self.store.insert_event(self.project, StoredEvent(
                    seq=0, id=assertion.id, kind=assertion.kind, body=assertion.body,
                    parents=tuple(assertion.parents), provenance=signed, scope=tuple(assertion.scope),
                    prev_hash=prev_hash, entry_hash=entry_hash, event_key=ekey))
                appended = (seq, entry_hash)
        if appended is not None:  # NOTIFY only a real append, with the seq/head captured under the lock
            self.store.notify(self.channel, json.dumps(
                {"project": self.project, "seq": appended[0], "id": assertion.id, "head": appended[1]}))
        return self._merged(assertion.id)

    def iter_assertions_in_causal_order(self) -> Iterable[Assertion]:
        """Collapse the immutable events by id (union parents/provenance/scope, mem:060) then linearize
        the causal DAG — identical to :class:`~yigraf.log.InMemoryLog`, just sourced from durable rows,
        so ``fold`` produces the same graph as the local substrate for the same content (mem:059)."""
        return causal_order(self._collapsed().values())

    # -- integrity (task #8) -----------------------------------------------------------------------

    def verify_chain(self) -> bool:
        """Recompute the hash chain over the seq-ordered events and confirm every stored ``prev_hash`` /
        ``entry_hash`` matches — the tamper-evidence check. Any edited/reordered/dropped event fails."""
        prev = GENESIS_HASH
        for event in self.store.iter_events(self.project):
            if event.prev_hash != prev or event.entry_hash != chain_hash(prev, event.event_key):
                return False
            prev = event.entry_hash
        return True

    def head_hash(self) -> str:
        """The chain head — a compact commitment to the entire ordered log (``GENESIS_HASH`` if empty)."""
        head = self.store.head(self.project)
        return head.entry_hash if head else GENESIS_HASH

    # -- internals ---------------------------------------------------------------------------------

    def _collapsed(self) -> dict[str, Assertion]:
        merged: dict[str, Assertion] = {}
        for event in self.store.iter_events(self.project):
            a = Assertion(id=event.id, kind=event.kind, body=event.body, parents=event.parents,
                          provenance=[event.provenance] if event.provenance else [], scope=event.scope)
            merged[a.id] = merge_assertion(merged[a.id], a) if a.id in merged else a
        return merged

    def _merged(self, assertion_id: str) -> Assertion:
        return self._collapsed()[assertion_id]


# --------------------------------------------------------------------------------------------------
# SqliteAssertionStore — the offline reference adapter (stdlib; durable, ordered, replayable)
# --------------------------------------------------------------------------------------------------

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  seq        INTEGER PRIMARY KEY AUTOINCREMENT,
  project    TEXT NOT NULL,
  event_key  TEXT NOT NULL,
  id         TEXT NOT NULL,
  kind       TEXT NOT NULL,
  body       TEXT NOT NULL,
  parents    TEXT NOT NULL,
  provenance TEXT NOT NULL,
  scope      TEXT NOT NULL,
  prev_hash  TEXT NOT NULL,
  entry_hash TEXT NOT NULL,
  UNIQUE (project, event_key)
);
CREATE INDEX IF NOT EXISTS events_project_seq ON events (project, seq);
CREATE TABLE IF NOT EXISTS views (
  project   TEXT PRIMARY KEY,
  node_link TEXT NOT NULL,
  head_seq  INTEGER NOT NULL,
  head_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state (
  project     TEXT PRIMARY KEY,
  remote_seq  INTEGER NOT NULL,
  remote_head TEXT NOT NULL
);
"""


def _row_to_event(row: sqlite3.Row) -> StoredEvent:
    return StoredEvent(
        seq=row["seq"], id=row["id"], kind=row["kind"], body=json.loads(row["body"]),
        parents=tuple(json.loads(row["parents"])), provenance=json.loads(row["provenance"]),
        scope=tuple(json.loads(row["scope"])), prev_hash=row["prev_hash"],
        entry_hash=row["entry_hash"], event_key=row["event_key"])


class SqliteAssertionStore:
    """The reference :class:`AssertionStore` — a stdlib SQLite append-only log + an in-process pub/sub.
    Durable, ordered (``AUTOINCREMENT`` ⇒ monotonic seq), and replayable, so it is a genuine single-host
    online substrate; the fast test suite proves the whole online engine against it with no network.
    Per-project serialization is a :class:`threading.Lock` (in-process, sufficient for one host); the
    Postgres shim swaps it for an advisory lock. ``:memory:`` is fine for tests; a path is persistent."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        # check_same_thread=False + our own lock: a single connection shared across the (single-host)
        # writer + read-service threads, serialized on the append critical section.
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SQLITE_SCHEMA)
        self._conn.commit()
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._subscribers: dict[str, list[Callable[[str], None]]] = defaultdict(list)

    def append_lock(self, project: str) -> ContextManager:
        return self._locks[project]

    def head(self, project: str) -> StoredEvent | None:
        row = self._conn.execute(
            "SELECT * FROM events WHERE project=? ORDER BY seq DESC LIMIT 1", (project,)).fetchone()
        return _row_to_event(row) if row else None

    def known_ids(self, project: str) -> set[str]:
        return {r["id"] for r in self._conn.execute(
            "SELECT DISTINCT id FROM events WHERE project=?", (project,))}

    def find_event(self, project: str, ekey: str) -> StoredEvent | None:
        row = self._conn.execute(
            "SELECT * FROM events WHERE project=? AND event_key=?", (project, ekey)).fetchone()
        return _row_to_event(row) if row else None

    def insert_event(self, project: str, event: StoredEvent) -> int:
        cur = self._conn.execute(
            "INSERT INTO events (project, event_key, id, kind, body, parents, provenance, scope, "
            "prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (project, event.event_key, event.id, event.kind, json.dumps(event.body, sort_keys=True),
             json.dumps(list(event.parents)), json.dumps(event.provenance, sort_keys=True),
             json.dumps(list(event.scope)), event.prev_hash, event.entry_hash))
        self._conn.commit()
        return int(cur.lastrowid)

    def iter_events(self, project: str) -> list[StoredEvent]:
        return [_row_to_event(r) for r in self._conn.execute(
            "SELECT * FROM events WHERE project=? ORDER BY seq", (project,))]

    def notify(self, channel: str, payload: str) -> None:
        for handler in list(self._subscribers.get(channel, ())):
            handler(payload)  # in-process, synchronous — the real store uses LISTEN/NOTIFY

    def subscribe(self, channel: str, handler: Callable[[str], None]) -> None:
        self._subscribers[channel].append(handler)

    def write_view(self, project: str, view: ViewRow) -> None:
        self._conn.execute(
            "INSERT INTO views (project, node_link, head_seq, head_hash) VALUES (?,?,?,?) "
            "ON CONFLICT(project) DO UPDATE SET node_link=excluded.node_link, "
            "head_seq=excluded.head_seq, head_hash=excluded.head_hash",
            (project, json.dumps(view.node_link, sort_keys=True), view.head_seq, view.head_hash))
        self._conn.commit()

    def read_view(self, project: str) -> ViewRow | None:
        row = self._conn.execute(
            "SELECT node_link, head_seq, head_hash FROM views WHERE project=?", (project,)).fetchone()
        if row is None:
            return None
        return ViewRow(json.loads(row["node_link"]), row["head_seq"], row["head_hash"])

    # -- replica-only ops (client sync, yigraf.sync) — not part of the AssertionStore port ---------

    def upsert_event(self, project: str, event: StoredEvent) -> None:
        """Store a remote event VERBATIM (its server-signed provenance + chain hashes preserved),
        idempotent on ``(project, event_key)`` — the replica-ingest primitive :mod:`yigraf.sync` uses to
        fold pulled deltas in. Unlike :meth:`insert_event` it never re-signs/re-chains and never raises
        on a re-pull; the local rowid ``seq`` is assigned in pull order (fold uses causal parents, not
        seq, so it does not matter — mem:98d5a556)."""
        self._conn.execute(
            "INSERT INTO events (project, event_key, id, kind, body, parents, provenance, scope, "
            "prev_hash, entry_hash) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(project, event_key) DO NOTHING",
            (project, event.event_key, event.id, event.kind, json.dumps(event.body, sort_keys=True),
             json.dumps(list(event.parents)), json.dumps(event.provenance, sort_keys=True),
             json.dumps(list(event.scope)), event.prev_hash, event.entry_hash))
        self._conn.commit()

    def get_cursor(self, project: str) -> tuple[int, str]:
        """The replica's sync cursor: ``(remote_seq, remote_head_hash)`` last reconciled, or the genesis
        ``(0, GENESIS_HASH)`` if never synced — the token :mod:`yigraf.sync` compares to the remote head."""
        row = self._conn.execute(
            "SELECT remote_seq, remote_head FROM sync_state WHERE project=?", (project,)).fetchone()
        return (row["remote_seq"], row["remote_head"]) if row else (0, GENESIS_HASH)

    def set_cursor(self, project: str, remote_seq: int, remote_head: str) -> None:
        self._conn.execute(
            "INSERT INTO sync_state (project, remote_seq, remote_head) VALUES (?,?,?) "
            "ON CONFLICT(project) DO UPDATE SET remote_seq=excluded.remote_seq, "
            "remote_head=excluded.remote_head", (project, remote_seq, remote_head))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# --------------------------------------------------------------------------------------------------
# PostgresAssertionStore — the production shim ([postgres] extra; psycopg lazily imported)
# --------------------------------------------------------------------------------------------------

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  seq        BIGSERIAL PRIMARY KEY,
  project    TEXT NOT NULL,
  event_key  TEXT NOT NULL,
  id         TEXT NOT NULL,
  kind       TEXT NOT NULL,
  body       JSONB NOT NULL,
  parents    JSONB NOT NULL,
  provenance JSONB NOT NULL,
  scope      JSONB NOT NULL,
  prev_hash  TEXT NOT NULL,
  entry_hash TEXT NOT NULL,
  UNIQUE (project, event_key)
);
CREATE INDEX IF NOT EXISTS events_project_seq ON events (project, seq);
CREATE TABLE IF NOT EXISTS views (
  project   TEXT PRIMARY KEY,
  node_link JSONB NOT NULL,
  head_seq  BIGINT NOT NULL,
  head_hash TEXT NOT NULL
);
"""


class PostgresAssertionStore:  # pragma: no cover - requires a live Postgres; contract proven via sqlite
    """The production :class:`AssertionStore`: a real Postgres append-only table (``BIGSERIAL`` monotonic
    seq, ``JSONB`` bodies) with native ``LISTEN``/``NOTIFY``. It implements exactly the same contract the
    SQLite reference adapter is tested against (mem:059), so the shared :class:`OnlineLog` needs no
    changes. psycopg is imported lazily so it stays an optional ``[postgres]`` extra (never a hard
    dependency, mirroring ``fastembed``/``embeddings-torch``). Per-project serialization is a
    transaction-scoped advisory lock over the log tail (mem:058's endorsed coordination, not the
    retired whole-graph lease). Untested in the offline suite by construction — it needs a live server."""

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "PostgresAssertionStore needs the [postgres] extra: `uv pip install 'yigraf[postgres]'`"
            ) from exc
        self._psycopg = psycopg
        self._dsn = dsn
        self._conn = psycopg.connect(dsn, autocommit=True)
        with self._conn.cursor() as cur:
            cur.execute(_PG_SCHEMA)

    @contextlib.contextmanager
    def append_lock(self, project: str):
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (project,))
            yield

    def head(self, project: str) -> StoredEvent | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT seq, id, kind, body, parents, provenance, scope, prev_hash, "
                        "entry_hash, event_key FROM events WHERE project=%s ORDER BY seq DESC LIMIT 1",
                        (project,))
            row = cur.fetchone()
        return self._to_event(row) if row else None

    def known_ids(self, project: str) -> set[str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT DISTINCT id FROM events WHERE project=%s", (project,))
            return {r[0] for r in cur.fetchall()}

    def find_event(self, project: str, ekey: str) -> StoredEvent | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT seq, id, kind, body, parents, provenance, scope, prev_hash, "
                        "entry_hash, event_key FROM events WHERE project=%s AND event_key=%s",
                        (project, ekey))
            row = cur.fetchone()
        return self._to_event(row) if row else None

    def insert_event(self, project: str, event: StoredEvent) -> int:
        Json = self._psycopg.types.json.Json
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO events (project, event_key, id, kind, body, parents, provenance, scope, "
                "prev_hash, entry_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING seq",
                (project, event.event_key, event.id, event.kind, Json(event.body),
                 Json(list(event.parents)), Json(event.provenance), Json(list(event.scope)),
                 event.prev_hash, event.entry_hash))
            return int(cur.fetchone()[0])

    def iter_events(self, project: str) -> list[StoredEvent]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT seq, id, kind, body, parents, provenance, scope, prev_hash, "
                        "entry_hash, event_key FROM events WHERE project=%s ORDER BY seq", (project,))
            return [self._to_event(r) for r in cur.fetchall()]

    def notify(self, channel: str, payload: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_notify(%s, %s)", (channel, payload))

    def subscribe(self, channel: str, handler: Callable[[str], None]) -> None:
        # A real deployment runs this on a dedicated LISTEN connection in a background thread; left to
        # the service shell (the engine's contract is proven synchronously against the sqlite adapter).
        raise NotImplementedError("drive LISTEN on a dedicated connection in the service process")

    def write_view(self, project: str, view: ViewRow) -> None:
        Json = self._psycopg.types.json.Json
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO views (project, node_link, head_seq, head_hash) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (project) DO UPDATE SET node_link=EXCLUDED.node_link, "
                "head_seq=EXCLUDED.head_seq, head_hash=EXCLUDED.head_hash",
                (project, Json(view.node_link), view.head_seq, view.head_hash))

    def read_view(self, project: str) -> ViewRow | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT node_link, head_seq, head_hash FROM views WHERE project=%s", (project,))
            row = cur.fetchone()
        return ViewRow(row[0], row[1], row[2]) if row else None

    @staticmethod
    def _to_event(row) -> StoredEvent:
        return StoredEvent(seq=row[0], id=row[1], kind=row[2], body=row[3], parents=tuple(row[4]),
                           provenance=row[5], scope=tuple(row[6]), prev_hash=row[7], entry_hash=row[8],
                           event_key=row[9])

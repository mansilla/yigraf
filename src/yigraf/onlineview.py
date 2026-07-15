"""The CQRS read service — the materialized view of the online log (plan task #9, int:yigraf-online-v1).

Command/query split (mem:058's event-sourcing carried to the read side): the **command** side is the
append-only :class:`~yigraf.onlinelog.OnlineLog` (tasks #7/#8); the **query** side is a materialized
graph that :func:`yigraf.fold.fold` produces from that log, persisted in the SAME store keyed by
project. Crucially it is stored in the SAME :func:`yigraf.graph.to_node_link` shape ``graphdb.py``
persists the *local* view in — so ``yigraf context``/``status`` read the online graph through the
existing retrieval/status code with **no changes** (mem:059: the query layer is shared; the graph a
reader gets back is a plain :class:`~networkx.DiGraph` either way).

Two properties make this a CQRS read service rather than just a cache:

- **Consistency / current-state.** The view is stamped with the log head it was folded from (``head_seq``
  + the Merkle ``head_hash``, task #8), so :meth:`ReadService.is_current` tells a reader whether the
  view reflects every committed append — the "consistency + current state" the task asks for, without
  re-folding to find out.
- **Convergence.** :meth:`ReadService.start` LISTENs on the log's NOTIFY channel (task #7) and refolds
  on each append, so the view converges to current state on its own. It is a pure projection (R6): a
  refold is idempotent and a lost NOTIFY self-heals on the next one (or an explicit :meth:`refold`).

The view is derived and recomputable — never a write target (R1/R6), exactly like the local SQLite
view. ``base`` (the tree-sitter structure graph the assertion families attach to) is supplied by a
``base_provider`` in a real deployment (a shared structure snapshot of the repo the assertions concern);
absent it, the fold materializes the assertion families alone — enough to prove the read seam offline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import networkx as nx

from yigraf.fold import fold
from yigraf.graph import from_node_link, to_node_link
from yigraf.onlinelog import GENESIS_HASH, OnlineLog, ViewRow


@dataclass
class Consistency:
    """Whether the materialized view reflects every committed append (task #9's consistency signal)."""

    current: bool  # view head_seq == log head seq
    view_seq: int  # the log seq the view was last folded from (0 ⇒ never folded)
    log_seq: int   # the log's current head seq (0 ⇒ empty log)
    head_hash: str  # the log's current Merkle head — a compact commitment to verify against


class ReadService:
    """Owns the query side of one project's online graph: folds the log into a materialized view,
    refolds on NOTIFY, and serves the view back to ``context``/``status`` as a plain
    :class:`~networkx.DiGraph`. Stateless beyond its store — every method is a pure function of the
    committed log, so a crash/restart just re-derives (R6)."""

    def __init__(self, log: OnlineLog, base_provider: Callable[[], nx.DiGraph] | None = None) -> None:
        self.log = log
        self.store = log.store
        self.project = log.project
        self._base_provider = base_provider

    def start(self) -> None:
        """Subscribe to the log's NOTIFY channel so an append triggers a refold — the view converges to
        current state without polling (task #7's LISTEN/NOTIFY, task #9's read side consuming it)."""
        self.store.subscribe(self.log.channel, self._on_notify)

    def refold(self) -> ViewRow:
        """Fold the log and materialize the view, stamped with the log head it reflects. The single
        projection step; idempotent, so re-running it (a replayed NOTIFY) is harmless (R6)."""
        base = self._base_provider() if self._base_provider is not None else None
        graph = fold(self.log, base=base)
        head = self.store.head(self.project)
        view = ViewRow(node_link=to_node_link(graph),
                       head_seq=head.seq if head else 0,
                       head_hash=head.entry_hash if head else GENESIS_HASH)
        self.store.write_view(self.project, view)
        return view

    def load_graph(self) -> nx.DiGraph | None:
        """The read seam ``context``/``status`` call: reconstruct the materialized view as an
        :class:`~networkx.DiGraph`, or ``None`` if never folded. Uses :func:`from_node_link` so the
        graph is identical to what an in-memory :func:`fold` would produce for the same log (mem:059) —
        which is what lets the shared query layer run over the online graph unchanged."""
        view = self.store.read_view(self.project)
        if view is None:
            return None
        return from_node_link(view.node_link)

    def consistency(self) -> Consistency:
        """Whether the view is current with the log (task #9's consistency + current-state signal),
        without a refold — a cheap head comparison a reader checks before trusting the view."""
        view = self.store.read_view(self.project)
        head = self.store.head(self.project)
        log_seq = head.seq if head else 0
        view_seq = view.head_seq if view else 0
        return Consistency(current=(view is not None and view_seq == log_seq),
                           view_seq=view_seq, log_seq=log_seq,
                           head_hash=head.entry_hash if head else GENESIS_HASH)

    def load_current(self) -> nx.DiGraph | None:
        """Load the view, refolding first if it is stale — the "always give the reader current state"
        convenience over :meth:`load_graph` + :meth:`consistency`, for a reader that can't wait for the
        NOTIFY-driven refold to land."""
        if not self.consistency().current:
            self.refold()
        return self.load_graph()

    def _on_notify(self, _payload: str) -> None:
        self.refold()

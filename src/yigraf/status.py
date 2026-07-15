"""Host-agnostic status surface: a compact, ambient summary of the graph (int:status-surface).

Why a *separate* surface from the hooks. yigraf's value is delivered into the **agent's** context by
the push hooks, but the **human principal** has no cheap way to see the graph's shape — how many
intents/decisions govern the repo, whether links are drifting, whether the committed projection is
stale. This module computes that summary as a pure value object so a thin per-host adapter (a Claude
Code ``statusLine`` command, another host's ambient region) can render it **without** spending the
agent's token budget — informing the user without violating "silence is a feature" on the agent's
attention. Human-facing ambient stats ride their own UI channel; they are never folded into the
hook injection.

Host-agnostic by construction: :func:`compute_status` never reads a transcript or any host API. The
one datum that *can't* be agnostic — context-window occupancy — is an **injected optional input**
(``ctx_used``/``ctx_limit``); a host that can supply it fills those, every other host omits the line.
(Mirrors ``mem:005``: a host doesn't hand a hook its token usage, so reading it can't live in the
agnostic core.) Freshness is derived by comparing the rebuilt graph to the gitignored SQLite
materialized view (R6: the view is a recomputable projection) — nothing volatile is written anywhere.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import networkx as nx

from yigraf import graphdb
from yigraf.contradiction import open_conflict_count
from yigraf.drift import compute_drift, is_surfaced, stale_completions
from yigraf.embeddings import load_index
from yigraf.graph import to_node_link

#: Structure kinds that are *containers*, not symbols — excluded from the symbol count.
_CONTAINER_KINDS = frozenset({"file", "module"})

# ── Presentation (human-facing only) ──────────────────────────────────────────────────────────────
# ANSI styling for the *human* ambient surface (statusline / TTY). Dependency-free (no rich/colorama)
# so it never adds weight. Deliberately NOT used in the hook injection: that text is the *agent's*,
# and escape codes would be wasted tokens / noise in its context (design law #2). Plain mode stays
# byte-identical to the un-styled render so pipes, --json, and tests are unaffected.
_RESET = "\x1b[0m"

#: The spinning **Y** of ``[Yigraf]``: the capital Y rotated through 0°/90°/180°/270° (fork pointing
#: up / right / down / left), so successive statusline refreshes read as the Y turning on its axis.
SPIN = "Y≻⅄≺"
#: The static Y (when not animating) — head of the ``[Yigraf]`` brand.
BRAND = "Y"
#: "igraf" in Mathematical-Monospace (U+1D68A block): a geeky, fixed-width "terminal font" tail that
#: trails the spinning Y. Pretty-render only — the plain render stays the byte-stable ASCII "yigraf".
_IGRAF = "𝚒𝚐𝚛𝚊𝚏"


def _c(text: str, code: str) -> str:
    """Wrap ``text`` in an ANSI SGR ``code`` (e.g. ``"1;36"``); the caller gates on color being on."""
    return f"\x1b[{code}m{text}{_RESET}"


def _fmt_tokens(n: int) -> str:
    """A raw token count as a compact, glanceable magnitude: ``1280 → 1.3k``, ``128000 → 128k``,
    ``1_200_000 → 1.2M``. Sub-1k stays exact. One significant fractional digit only under 10 of a
    unit (``1.3k``/``9.4M``), whole above (``128k``/``42M``) — enough to read the trend, no noise."""
    if n < 1_000:
        return str(n)
    unit, scaled = ("M", n / 1_000_000) if n >= 1_000_000 else ("k", n / 1_000)
    return (f"{scaled:.1f}{unit}" if scaled < 10 else f"{scaled:.0f}{unit}")


@dataclass
class StatusSummary:
    """A compact, host-agnostic snapshot of the graph. ``ctx_*`` are adapter-supplied and optional."""

    symbols: int
    intents: int
    plans: int
    tasks_total: int
    tasks_open: int
    decisions: int  # active (non-superseded) memory nodes
    drifting: int  # soft + hard drift items (the re-verify count); renames auto-re-anchor, so excluded
    freshness: str  # "fresh" | "stale" | "absent" — committed graph.json vs the rebuilt graph
    semantic: bool  # a non-empty embedding index is present (reflects the last build, not a live model load)
    embedded: int  # nodes in that index
    head: str | None  # short HEAD sha, informational
    update: str | None = None  # a newer yigraf version on PyPI, if the daily check found one
    ctx_used: int | None = None  # context tokens in use, if a host supplied it
    ctx_limit: int | None = None  # context window size, if a host supplied it
    ctx_soft_limit: int = 250_000  # usable-budget knee the gauge scales to (config status.ctx_soft_limit; mem:053)
    coherence: int = 0  # open knowledge-conflicts awaiting a principal (mem:062) — the coherence-dirty
    # dimension distinct from freshness; a cheap count only (the full findings go to the resolution UI)
    stale: int = 0  # done-task completions whose implementing symbol drifted (int:drift-as-stale): the
    # completion is no longer verified. Principal-facing, shown only when >0 — never at the edit hook (mem:056)

    @property
    def _ctx_effective(self) -> int | None:
        """The gauge denominator: the *usable budget*, ``min(window, ctx_soft_limit)``.

        Quality and per-turn cost track *absolute* occupancy, not fraction-of-window, so a 1M window
        clamps to the degradation knee (``ctx_soft_limit``) while a genuine ~200k window is unaffected
        (the min is the window itself — the gauge stays byte-identical for small hosts). A
        ``ctx_soft_limit`` of 0/None opts out: gauge against the raw window.
        """
        if not self.ctx_limit:
            return None
        return min(self.ctx_limit, self.ctx_soft_limit) if self.ctx_soft_limit else self.ctx_limit

    @property
    def ctx_pct(self) -> int | None:
        """Fill as a whole percent of the *usable budget* (capped 100), or ``None`` with no host datum.

        Not fraction-of-window: at 1M a 200k working set is ~"full" (≈100%), not a benign 20%, because
        degradation and token cost track absolute occupancy. Plain and gauge both read this one number,
        so digit, bar, and color agree. Raw ``ctx_used``/``ctx_limit`` stay verbatim in the dataclass
        for a JSON consumer that wants the physical fill.
        """
        eff = self._ctx_effective
        if self.ctx_used and eff:
            return min(100, round(100 * self.ctx_used / eff))
        return None

    def render_line(self, *, color: bool = False, icon: str | None = None) -> str:
        """One scannable line for an ambient surface (statusline). No trailing newline.

        ``color=False`` (the default) returns the plain, byte-stable render — what pipes, ``--json``
        consumers, and tests see. ``color=True`` returns the styled render (ANSI + shape glyphs);
        ``icon`` overrides the brand glyph (the CLI passes a :data:`SPIN` frame so it appears to spin).
        """
        return self._pretty(icon) if color else self._plain(icon or "yigraf")

    def _plain(self, brand: str) -> str:
        # Three distinct states, because "all done" and "no plans yet" both zero out `tasks_open` and
        # would otherwise render the same bare count: `/N open` (work remains) · ` ✓` (all done, total>0)
        # · plain `0 task` (empty — no plan authored). The ✓ is the "you're clear" signal.
        if not self.tasks_total:
            tasks = "0 task"
        elif self.tasks_open:
            tasks = f"{self.tasks_total} task/{self.tasks_open} open"
        else:
            tasks = f"{self.tasks_total} task ✓"
        parts = [f"{brand} {self.symbols} sym", f"{self.intents} int", tasks, f"{self.decisions} dec",
                 f"⚠ {self.drifting} drift" if self.drifting else "no drift", self.freshness]
        if self.coherence:  # only when there are open conflicts — silent when coherent (design law #4)
            parts.append(f"⚠ {self.coherence} conflict")
        if self.stale:  # done completions whose evidence drifted (int:drift-as-stale) — shown only when >0
            parts.append(f"⚠ {self.stale} stale")
        if self.semantic:
            parts.append(f"sem {self.embedded}")
        if self.ctx_pct is not None:
            parts.append(f"ctx {self.ctx_pct}%"
                         + (f" {_fmt_tokens(self.ctx_used)}" if self.ctx_used else ""))
        if self.update:
            parts.append(f"⬆ {self.update}")
        return " · ".join(parts)

    def _pretty(self, icon: str | None) -> str:
        """Styled render: bold numbers, dim labels, shape-coded drift/freshness, a context gauge."""
        spin_y = icon if icon is not None else BRAND  # the rotating (or static) head of [Yigraf]
        brand = _c(f"[{spin_y}{_IGRAF}]", "1;36")  # spinning Y + monospace "igraf", bracketed
        kv = lambda n, label: _c(str(n), "1") + _c(f" {label}", "2")  # bold number · dim label
        segs = [
            brand + " " + kv(self.symbols, "sym"),
            kv(self.intents, "int"),
            _c(str(self.tasks_total), "1") + _c(" task", "2")
            + (_c(f"/{self.tasks_open}", "33") + _c(" open", "2") if self.tasks_open
               else _c(" ✓", "32") if self.tasks_total else ""),
            kv(self.decisions, "dec"),
            _c(f"⚠ {self.drifting} drift", "1;33") if self.drifting else _c("✓ clear", "32"),
            {"fresh": _c("● fresh", "32"), "stale": _c("○ stale", "33")}.get(
                self.freshness, _c("○ none", "2")),
        ]
        if self.coherence:  # coherence-dirty (mem:062): open conflicts for a principal, shown only when >0
            segs.append(_c(f"⚠ {self.coherence} conflict", "1;33"))
        if self.stale:  # int:drift-as-stale: done completions whose evidence drifted, shown only when >0
            segs.append(_c(f"⚠ {self.stale} stale", "1;33"))
        if self.semantic:
            segs.append(_c("✦", "35") + _c(f" sem {self.embedded}", "2"))
        if self.ctx_pct is not None:
            segs.append(self._ctx_gauge())
        if self.update:  # a newer yigraf is on PyPI — gentle, brand-colored nudge
            segs.append(_c(f"⬆ {self.update}", "1;36"))
        return _c(" · ", "2").join(segs)

    def _ctx_gauge(self) -> str:
        """A tiny 4-cell bar + percent, colored green→yellow→red as the window fills, trailed by the
        raw token magnitude (``128k``) dim, so the human reads both the fill and the absolute cost."""
        pct = self.ctx_pct or 0
        code = "32" if pct < 50 else "33" if pct < 80 else "31"
        fill = max(0, min(4, round(pct / 25)))
        gauge = _c("ctx ", "2") + _c("▰" * fill + "▱" * (4 - fill) + f" {pct}%", code)
        if self.ctx_used:
            gauge += _c(f" {_fmt_tokens(self.ctx_used)}", "2")
        return gauge

    def as_dict(self) -> dict:
        """The full summary as JSON-ready data — for a host adapter that wants to render it itself."""
        return asdict(self)


def _freshness(root: Path, graph: nx.DiGraph) -> str:
    """Is the gitignored SQLite materialized view in sync with the rebuilt graph? (R6 — the view is derived.)

    :func:`yigraf.graph.to_node_link` is deterministic (sorted), so a byte-equal canonical projection of
    the persisted view and the fresh rebuild means the view reflects the current source + landed maturity
    (the volatile git-HEAD overlays are stripped from both). Absent/unreadable ⇒ no claim of freshness
    rather than a crash (fail-open). Pure read: comparing never re-materializes the view.
    """
    persisted = graphdb.load(graphdb.db_path(root))
    if persisted is None:
        return "absent"
    canon = lambda g: json.dumps(to_node_link(g), sort_keys=True)
    return "fresh" if canon(persisted) == canon(graph) else "stale"


def compute_status(graph: nx.DiGraph, root: Path, config: dict, *,
                   ctx_used: int | None = None, ctx_limit: int | None = None) -> StatusSummary:
    """Summarize ``graph`` into a :class:`StatusSummary` — pure over the graph + on-disk artifacts.

    Never loads the embedding model (a statusline may run often): ``semantic``/``embedded`` reflect the
    persisted index, not a live backend probe. ``ctx_used``/``ctx_limit`` are passed through verbatim.
    """
    symbols = intents = plans = tasks_total = tasks_open = decisions = 0
    for _, a in graph.nodes(data=True):
        family = a.get("family")
        if family == "structure":
            if a.get("kind") not in _CONTAINER_KINDS:
                symbols += 1
        elif family == "intent":
            intents += 1
        elif family == "plan":
            if a.get("kind") == "task":
                tasks_total += 1
                if a.get("state") != "done":
                    tasks_open += 1
            else:
                plans += 1
        elif family == "memory":
            if a.get("status") == "active" and not a.get("superseded_in", 0):
                decisions += 1

    # Count only surfaced re-verify drift: a done task's implements drift is provenance, not a nag
    # (int:drift-done-suppression); renames auto-re-anchor so they never count.
    drifting = sum(1 for d in compute_drift(graph)
                   if d.kind in ("soft", "hard") and is_surfaced(graph, d))
    # The complement (int:drift-as-stale): a DONE task whose implementing symbol drifted — a stale
    # completion, principal-facing here and in context/session, never at the edit hook (mem:056/mem:81edb).
    stale = len(stale_completions(graph))

    index = load_index(root, config)
    embedded = len(index.ids) if index else 0

    # Coherence-dirty (mem:062): open knowledge-conflicts awaiting a principal — a graph-health
    # dimension distinct from freshness. Reuses the index just loaded (no model, no second read); a
    # cheap count only, so a frequent statusline never pays for it and the agent's budget is untouched.
    coherence = open_conflict_count(graph, root, config, index=index)

    # Single read-only git call; counters._head_sha is the canonical HEAD probe (fail-open ⇒ None).
    from yigraf.counters import _head_sha
    head = _head_sha(root)

    # A pure read of the .local sidecar the daily check writes — no network here (a statusline runs
    # often); update.refresh() does the throttled fetch, and only the human-facing CLI surfaces call it.
    from yigraf import __version__, update
    available = update.available(root, __version__)

    # The gauge scales to a usable budget, not the raw window (int:status-surface); default 250k.
    soft_limit = config.get("status", {}).get("ctx_soft_limit", 250_000)

    return StatusSummary(
        symbols=symbols, intents=intents, plans=plans,
        tasks_total=tasks_total, tasks_open=tasks_open, decisions=decisions,
        drifting=drifting, freshness=_freshness(root, graph), coherence=coherence, stale=stale,
        semantic=embedded > 0, embedded=embedded,
        head=head[:7] if head else None, update=available,
        ctx_used=ctx_used, ctx_limit=ctx_limit, ctx_soft_limit=soft_limit,
    )

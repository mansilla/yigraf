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
from yigraf.drift import compute_drift, is_surfaced, pending_renames, stale_completions
from yigraf.embeddings import load_index
from yigraf.graph import to_node_link

#: Structure kinds that are *containers*, not symbols — excluded from the symbol count.
_CONTAINER_KINDS = frozenset({"file", "module"})

#: The signals whose zero-state IS "up to date", as the word each prose surface must use for it.
#:
#: One source, because there are SIX copies of that sentence — the skill's frontmatter and its §0b,
#: the session preamble, the AGENTS.md block, the ambient MCP rule, and the MCP ``status`` tool's own
#: description — and 1.8.0 added ``rename`` to two of them and shipped green (feedback-v6 F#1). The
#: gap is not cosmetic: ``render_line`` emits the literal ``no drift`` at zero and omits the
#: ``stale`` segment entirely at zero, so a two-count predicate evaluates TRUE against a line printed
#: directly beneath it that reads ``⚠ 1 rename``. And the hosts a stale copy reaches are the ones
#: with no skill to correct it — Codex reads hooks + AGENTS.md, and a hookless Tier-A host reads the
#: ambient rule with no preamble at all.
#:
#: ``test_up_to_date_is_defined_identically_on_every_prose_surface`` pins all six against this tuple,
#: so the NEXT signal added here fails loudly in whichever surface it did not reach. The sixth was
#: outside the pin until feedback-v7: the field read the enumeration, counted five, and named the MCP
#: docstring — which a host reads to decide whether calling ``status`` answers its question — as the
#: copy that could go stale next. An enumeration IS a claim about completeness; this one is checked.
UP_TO_DATE_SIGNALS = ("drift", "stale", "rename")


def is_symbol(attrs: dict) -> bool:
    """Whether a ``structure`` node counts toward the ``sym`` number on the status line.

    Its own function because a second reader now needs to agree with it exactly: ``cli.gc`` reports how
    far this count moved when a collection released placeholder anchors (feedback-v5 E#3), and a report
    that explains a number by recomputing it slightly differently is worse than no report. Note that a
    ``file-anchor`` placeholder *does* count — that is precisely why the number can fall after a `gc`.
    """
    return attrs.get("kind") not in _CONTAINER_KINDS


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
    unit (``1.3k``/``9.4M``), whole above (``128k``/``42M``) — enough to read the trend, no noise.
    A trailing ``.0`` is dropped (``1M``, not ``1.0M``): it carries no information, and the round
    values are exactly the common ones — a window ceiling is 200k or 1M far more often than not."""
    if n < 1_000:
        return str(n)
    unit, scaled = ("M", n / 1_000_000) if n >= 1_000_000 else ("k", n / 1_000)
    return (f"{scaled:.1f}".removesuffix(".0") if scaled < 10 else f"{scaled:.0f}") + unit


def _groups(brand: str, session: list[str], health: list[str], scale: list[str],
            *, sep: str, rule: str) -> str:
    """Join the line as three rules-separated groups, brand-first: what SESSION this is, what the
    graph's HEALTH is, and how big it is.

    One flat ``·`` list put ``169 dec`` between ``132 task ✓`` and ``no drift``, so the eye had to
    re-read the whole line to answer either "is anything wrong?" or "how big is this?" — the two
    questions an ambient surface exists to answer at a glance. Grouping costs nothing and makes
    both answerable by position: **left** is this session (brand, context gauge, update nudge),
    **middle** is every warning plus freshness, **right** is scale. Two orderings inside the groups
    are deliberate: freshness sits at the END of the health group rather than mid-list, so the ⚠
    segments stay contiguous; and the task count LEADS the scale group, because open work is the one
    stat there that is actionable — the rest are the size of the graph, read once and slow to move.

    The brand prefixes the first group with a space rather than joining as a segment — it labels
    the line, it is not a datum — and an empty group is dropped rather than rendered as an empty
    cell, so a host that supplies no context data yields ``yigraf | … | …`` and never ``yigraf |  |``.
    """
    first = brand + (" " + sep.join(session) if session else "")
    return rule.join(g for g in (first, sep.join(health), sep.join(scale)) if g)


#: The plain (uncolored) render of each non-``fresh`` freshness state. Each carries its remedy inline,
#: because the ambient line is often the *only* place the state is ever named — and a bare token that
#: names a condition without naming its exit is what sent a field session diagnosing a lost graph after
#: a routine upgrade (feedback-v5 A). ``fresh`` and ``behind`` are absent: ``fresh`` needs no remedy, and
#: ``behind`` already reads as "a read will catch it up".
_FRESHNESS_PLAIN = {
    "old-schema": "old-schema (rebuilds on next read)",
    "absent": "absent (rebuilds on next read)",
}


@dataclass
class StatusSummary:
    """A compact, host-agnostic snapshot of the graph. ``ctx_*`` are adapter-supplied and optional."""

    symbols: int
    intents: int
    plans: int
    tasks_total: int
    tasks_open: int
    decisions: int  # active (non-superseded) memory nodes
    drifting: int  # soft + hard drift items (the re-verify count); a rename is not one of them — it
    # auto-re-anchors, so it is counted separately as `renames` below, never folded in here
    freshness: str  # "fresh" | "behind" | "old-schema" | "absent" — the gitignored SQLite view vs the
    # rebuilt graph. "old-schema" is a view a previous yigraf wrote that this one declines: an upgrade
    # produced it, the next read rebuilds it, and nothing is lost — which is exactly what folding it
    # into "absent" could not say (feedback-v5 A).
    # (graph.json + its whole-graph merge lock are retired, mem:059; see _freshness below).
    # "behind", not "stale": bare "stale" is reserved for stale COMPLETIONS (the `stale` count below),
    # and one word carrying two health dimensions cost a field session six commands (feedback-v3 #13).
    semantic: bool  # a non-empty embedding index is present (reflects the last build, not a live model load)
    embedded: int  # nodes in that index
    head: str | None  # short HEAD sha, informational
    update: str | None = None  # a newer yigraf version on PyPI, if the daily check found one
    skill_behind: str | None = None  # the version stamp on an installed SKILL.md that this yigraf did
    # not write. An upgrade replaces the CLI and leaves the skill untouched, so the doc can describe a
    # yigraf that is several releases old — naming verbs that no longer exist and omitting the ones
    # that do (feedback-v5 D). Only ever set when a stamp is PRESENT and differs; an unstamped or
    # missing skill says nothing, because "I cannot tell" is not "you are behind".
    preamble_behind: bool = False  # this repo's COMMITTED yigraf/config.yaml carries a session preamble
    # yigraf shipped before this one. The same two-copy hazard as `skill_behind`, one file over: `init`
    # splices the preamble in and the file value wins at read time, so an upgrade cannot reach it — and
    # on a host with no skill the preamble is the only channel that teaches what "up to date" means
    # (feedback-v6 F#1). Byte-exact match against an older shipped default only; a preamble the team
    # rewrote is theirs and says nothing (config.preamble_behind).
    ctx_used: int | None = None  # context tokens in use, if a host supplied it
    ctx_limit: int | None = None  # context window size, if a host supplied it
    ctx_soft_limit: int = 250_000  # usable-budget knee the gauge scales to (config status.ctx_soft_limit; mem:053)
    conflicts: int = 0  # open knowledge-conflicts awaiting a principal (mem:062) — the coherence-dirty
    # dimension distinct from freshness; a cheap count only (`yigraf conflicts` lists the findings).
    # Named after what it counts so the JSON key matches the rendered "⚠ n conflict" (feedback-v3 #1).
    stale: int = 0  # done-task completions whose implementing symbol drifted (int:drift-as-stale): the
    # completion is no longer verified. Principal-facing, shown only when >0 — never at the edit hook (mem:056)
    renames: int = 0  # anchors re-anchored in the graph but not yet settled into the artifact
    # (drift.pending_renames). The one signal with an EXPIRY — the next semantic edit to that body ends
    # the content-hash match that makes the rescue possible — so it belongs on the surface every agent
    # already checks before handing off, not only in `yigraf gc` (feedback-v5 D#1). Shown only when >0.
    diverged: int = 0  # locators ANOTHER PRINCIPAL's log revision differs on (extract._fold_replica) —
    # your own replaced revisions are classified as history upstream, whether the replacement reached the
    # log (OnlineLog.superseded_revisions) or is still sitting unpushed on disk (pending_local_revisions),
    # so this never counts the previous revision of a locator you simply edited again.
    # The local file won, as design law #6 says — this counts the losing copies that no git merge will
    # ever reconcile, because the artifacts are not committed. Shown only when >0.

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

    @property
    def ctx_fill(self) -> str:
        """The *physical* occupancy as ``used/window`` (``236k/1M``) — the percent's missing denominator.

        The percent is knee-relative (see :attr:`ctx_pct`), so on a 1M host it reads 94% at 236k. Alone
        that collides with the host's own context readout ("24%") and has been acted on as *nearly out
        of room* — a wrong next action, which is the one thing the status surface must not cause
        (design law #2). Naming the window costs four characters and makes the two reconcilable on
        sight. It also carries the only signal left above the knee: ``ctx_pct`` saturates at 100 from
        ``ctx_soft_limit`` all the way to the ceiling, so past 250k the raw pair is the sole moving
        part. Empty when the host supplied no usage.
        """
        if not self.ctx_used:
            return ""
        used = _fmt_tokens(self.ctx_used)
        return f"{used}/{_fmt_tokens(self.ctx_limit)}" if self.ctx_limit else used

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

        session = []
        if self.ctx_pct is not None:
            session.append(f"ctx {self.ctx_pct}%" + (f" {self.ctx_fill}" if self.ctx_fill else ""))
        if self.update:
            session.append(f"⬆ {self.update}")
        if self.skill_behind:  # the doc the agent reads was written by a different yigraf
            session.append(f"⬆ skill {self.skill_behind}")
        if self.preamble_behind:  # the house rules injected every session were written by an older one
            session.append("⬆ preamble")

        health = [f"⚠ {self.drifting} drift" if self.drifting else "no drift"]
        if self.conflicts:  # only when there are open conflicts — silent when coherent (design law #4)
            health.append(f"⚠ {self.conflicts} conflict")
        if self.stale:  # done completions whose evidence drifted (int:drift-as-stale) — shown only when >0
            health.append(f"⚠ {self.stale} stale")
        if self.renames:  # unsettled renames — the expiring signal (feedback-v5 D#1), shown only when >0
            health.append(f"⚠ {self.renames} rename")
        if self.diverged:  # another workspace holds a different revision no git merge will reconcile
            health.append(f"⚠ {self.diverged} diverged")
        # The two non-fresh states carry their own remedy, because the surface that NAMES the state is
        # not the surface that clears it — a reader who is told only the word goes looking for damage
        # (feedback-v5 A). Kept to three words; the full sentence is `yigraf status`'s note, below.
        health.append(_FRESHNESS_PLAIN.get(self.freshness, self.freshness))

        scale = [tasks, f"{self.symbols} sym", f"{self.intents} int", f"{self.decisions} dec"]
        if self.semantic:
            scale.append(f"sem {self.embedded}")
        return _groups(brand, session, health, scale, sep=" · ", rule=" | ")

    def _pretty(self, icon: str | None) -> str:
        """Styled render: bold numbers, dim labels, shape-coded drift/freshness, a context gauge."""
        spin_y = icon if icon is not None else BRAND  # the rotating (or static) head of [Yigraf]
        brand = _c(f"[{spin_y}{_IGRAF}]", "1;36")  # spinning Y + monospace "igraf", bracketed
        kv = lambda n, label: _c(str(n), "1") + _c(f" {label}", "2")  # bold number · dim label

        session = []
        if self.ctx_pct is not None:
            session.append(self._ctx_gauge())
        if self.update:  # a newer yigraf is on PyPI — gentle, brand-colored nudge
            session.append(_c(f"⬆ {self.update}", "1;36"))
        if self.skill_behind:  # the installed skill predates this CLI (feedback-v5 D)
            session.append(_c(f"⬆ skill {self.skill_behind}", "1;36"))
        if self.preamble_behind:  # the committed house rules predate this CLI (feedback-v6 F#1)
            session.append(_c("⬆ preamble", "1;36"))

        health = [_c(f"⚠ {self.drifting} drift", "1;33") if self.drifting else _c("✓ clear", "32")]
        if self.conflicts:  # coherence-dirty (mem:062): open conflicts for a principal, shown only when >0
            health.append(_c(f"⚠ {self.conflicts} conflict", "1;33"))
        if self.stale:  # int:drift-as-stale: done completions whose evidence drifted, shown only when >0
            health.append(_c(f"⚠ {self.stale} stale", "1;33"))
        if self.renames:  # unsettled renames, the one signal with an expiry (feedback-v5 D#1)
            health.append(_c(f"⚠ {self.renames} rename", "1;33"))
        if self.diverged:  # another workspace holds a different revision no git merge will reconcile
            health.append(_c(f"⚠ {self.diverged} diverged", "1;33"))
        health.append({"fresh": _c("● fresh", "32"), "behind": _c("○ behind", "33"),
                       # Dim, not a warning color: an upgrade did this, the next read fixes it, and the
                       # graph is intact. `○ none` said "damage" for the one state that is routine.
                       "old-schema": _c("○ old-schema (rebuilds)", "2")}.get(
            self.freshness, _c("○ none", "2")))

        scale = [
            _c(str(self.tasks_total), "1") + _c(" task", "2")
            + (_c(f"/{self.tasks_open}", "33") + _c(" open", "2") if self.tasks_open
               else _c(" ✓", "32") if self.tasks_total else ""),
            kv(self.symbols, "sym"),
            kv(self.intents, "int"),
            kv(self.decisions, "dec"),
        ]
        if self.semantic:
            scale.append(_c("✦", "35") + _c(f" sem {self.embedded}", "2"))
        return _groups(brand, session, health, scale, sep=_c(" · ", "2"), rule=_c(" │ ", "2"))

    def _ctx_gauge(self) -> str:
        """A tiny 4-cell bar + percent, colored green→yellow→red as the budget fills, trailed by the
        physical occupancy (``236k/1M``) dim, so the reader gets both the fill and what it is a fill *of*.

        Bar, digit, and color all read :attr:`ctx_pct` (knee-relative); only the dim trailer is
        window-relative. Carrying the denominator is what keeps a knee-relative 94% from being read as
        a window-relative one — see :attr:`ctx_fill`."""
        pct = self.ctx_pct or 0
        code = "32" if pct < 50 else "33" if pct < 80 else "31"
        fill = max(0, min(4, round(pct / 25)))
        gauge = _c("ctx ", "2") + _c("▰" * fill + "▱" * (4 - fill) + f" {pct}%", code)
        if self.ctx_fill:
            gauge += _c(f" {self.ctx_fill}", "2")
        return gauge

    def ctx_note(self) -> str | None:
        """The knee, spelled out — or ``None`` when there is nothing to explain (design law #4).

        The ambient line can only afford the percent and the raw pair; the *reason* the two differ
        belongs somewhere with room, so ``yigraf status`` at a real terminal carries it. Silent unless
        the knee actually clamps (``_ctx_effective < ctx_limit``): on a ~200k host the budget IS the
        window, and explaining a distinction that isn't there would be pure noise.
        """
        eff = self._ctx_effective
        if self.ctx_pct is None or eff is None or eff >= self.ctx_limit:
            return None
        return (f"  ctx {self.ctx_pct}% is of the {_fmt_tokens(eff)} usable budget, not the "
                f"{_fmt_tokens(self.ctx_limit)} window ({self.ctx_fill} in use) — attention degrades "
                f"well before a long window is physically full, so the gauge tracks that knee. "
                f"Set status.ctx_soft_limit: 0 to gauge the raw window instead.")

    def freshness_note(self) -> str | None:
        """The one-sentence explanation of a non-``fresh`` view — or ``None`` when there is nothing to
        explain (design law #4).

        The ambient line can only afford three words, and three words cannot distinguish "a previous
        yigraf wrote this view" from "your graph is gone". This is where the difference is spelled out,
        for a human at a real terminal — the same split :meth:`ctx_note` makes.
        """
        if self.freshness == "old-schema":
            return ("  the materialized view was written by an older yigraf and is being declined on "
                    "its schema version — an upgrade does this. Nothing is lost: the view is a derived, "
                    "recomputable projection (files are truth), and the next `yigraf context`, `show` "
                    "or hook rebuilds it. `status` deliberately does not, because a surface that "
                    "rebuilds the view it is reporting on can only ever report `fresh`.")
        if self.freshness == "absent":
            return ("  no materialized view yet — the next `yigraf context`, `show` or hook builds it. "
                    "The graph itself is the files; the view is only a cache of them.")
        return None

    def as_dict(self) -> dict:
        """The full summary as JSON-ready data — for a host adapter that wants to render it itself."""
        return asdict(self)


def _freshness(root: Path, graph: nx.DiGraph) -> str:
    """Is the gitignored SQLite materialized view in sync with the rebuilt graph? (R6 — the view is derived.)

    :func:`yigraf.graph.to_node_link` is deterministic (sorted), so a byte-equal canonical projection of
    the persisted view and the fresh rebuild means the view reflects the current source + landed maturity
    (the volatile git-HEAD overlays are stripped from both). Absent/unreadable ⇒ no claim of freshness
    rather than a crash (fail-open). Pure read: comparing never re-materializes the view.

    **Why this stays a pure read, even though it holds a freshly built graph.** Materializing here would
    make the freshness question answer itself — every run would report ``fresh`` because the run just
    wrote what it is comparing against — so the one surface whose job is to report the view's state
    would be the one surface that could never report a stale one. The rebuild belongs on the read paths
    that actually use the view (``load_or_build``), and it is already there.

    ``old-schema`` is separated out from ``absent`` because they are different events with different
    reassurance (feedback-v5 A): ``absent`` means there is no view, while ``old-schema`` means a
    previous yigraf's view was declined by this one — the ordinary consequence of an upgrade, and self-
    healing on the next ``context``/``show``/hook. Reported as one word, ``absent``, it was diagnosed as
    a damaged graph.
    """
    state = graphdb.view_state(graphdb.db_path(root))
    if state == "old-schema":
        return "old-schema"
    persisted = graphdb.load(graphdb.db_path(root))
    if persisted is None:
        return "absent"
    canon = lambda g: json.dumps(to_node_link(g), sort_keys=True)
    # "behind", never "stale": that word belongs to stale completions, and any read that rebuilds the
    # view clears this — an unindexed-artifact marker, not a health problem (feedback-v3 #13).
    return "fresh" if canon(persisted) == canon(graph) else "behind"


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
            if is_symbol(a):
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
    # (int:drift-done-suppression). A rename auto-re-anchors, so it is never a re-verify prompt and
    # never counts HERE — it is its own count (`renames`), for its own reason (an expiry, not a doubt).
    drifting = sum(1 for d in compute_drift(graph)
                   if d.kind in ("soft", "hard") and is_surfaced(graph, d))
    # The complement (int:drift-as-stale): a DONE task whose implementing symbol drifted — a stale
    # completion, principal-facing here and in context/session, never at the edit hook (mem:056/mem:81edb).
    stale = len(stale_completions(graph))
    # Neither drift nor stale: a rename the build re-anchored in memory that the artifact still misses
    # (feedback-v5 D#1). It is counted here — on the surface the working loop checks before it reports
    # done — because it is the one condition that STOPS being repairable if it is not acted on: the next
    # semantic edit to that body breaks the content-hash match the rescue depends on.
    renames = len(pending_renames(graph))

    index = load_index(root, config)
    embedded = len(index.ids) if index else 0

    # Coherence-dirty (mem:062): open knowledge-conflicts awaiting a principal — a graph-health
    # dimension distinct from freshness. Reuses the index just loaded (no model, no second read); a
    # cheap count only, so a frequent statusline never pays for it and the agent's budget is untouched.
    conflicts = open_conflict_count(graph, root, config, index=index)

    # Single read-only git call; counters._head_sha is the canonical HEAD probe (fail-open ⇒ None).
    from yigraf.counters import _head_sha
    head = _head_sha(root)

    # A pure read of the .local sidecar the daily check writes — no network here (a statusline runs
    # often); update.refresh() does the throttled fetch, and only the human-facing CLI surfaces call it.
    from yigraf import __version__, update
    available = update.available(root, __version__)

    # Is the SKILL.md on disk the one THIS yigraf writes? A cheap 4 KB read of one file, no network.
    # It is the agent's instruction sheet, so a stale one is not cosmetic: it is the agent being told
    # the wrong verbs by the tool itself (feedback-v5 D).
    from yigraf.hooks import installed_skill_version
    stamped = installed_skill_version(root)
    skill_behind = stamped if stamped and stamped != __version__ else None

    # The same question about the OTHER file an upgrade cannot reach: the repo's committed preamble.
    from yigraf.config import preamble_behind as _preamble_behind

    # The gauge scales to a usable budget, not the raw window (int:status-surface); default 250k.
    soft_limit = config.get("status", {}).get("ctx_soft_limit", 250_000)

    return StatusSummary(
        symbols=symbols, intents=intents, plans=plans,
        tasks_total=tasks_total, tasks_open=tasks_open, decisions=decisions,
        drifting=drifting, freshness=_freshness(root, graph), conflicts=conflicts, stale=stale,
        renames=renames,
        # Computed at fold time (only the fold sees what it declined) and carried on the graph, so a
        # statusline read costs nothing extra — extract._fold_replica.
        diverged=len(graph.graph.get("diverged") or ()),
        semantic=embedded > 0, embedded=embedded,
        head=head[:7] if head else None, update=available, skill_behind=skill_behind,
        preamble_behind=_preamble_behind(config),
        ctx_used=ctx_used, ctx_limit=ctx_limit, ctx_soft_limit=soft_limit,
    )

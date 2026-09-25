"""The hook's own wall-clock budget, and the ledger a slow run leaves behind (feedback-v11 K#4).

The field measured `hook_cancelled` records in its host's transcripts against the `"timeout": 15` our
own installer writes: 19 on `PostToolUse:Edit` across 5 sessions, 3 on `Stop`, 2 on
`SessionStart:startup`, every recorded duration just past 15 000 ms. A warm render on their store is
2.6–3.0 s, so something intermittently makes it five times slower — **and neither they nor we know
what.** Reproduction failed here: on a 2404-symbol store with semantic recall on, the edit hook is
0.51–0.66 s warm, 0.50–0.68 s immediately after a source change (the content-extraction cache absorbs
the rebuild), 1.70 s for eight concurrent, and SessionStart is 0.29–0.75 s.

So this module does **not** try to make anything faster. Two hypotheses died on measurement, and a
third guess is not worth more than the two that failed. What it fixes is the part that is wrong
whatever the cause:

1. **A cancellation is fatal and silent.** The host SIGKILLs at 15 s and yigraf has emitted nothing —
   no error, no partial output, nothing in the transcript but the host's own cancellation record. A
   lost SessionStart packet leaves the session behaving as though the store did not exist, which is
   the one failure this product cannot afford, because it is *indistinguishable from the silence
   design law #4 asks for*. So yigraf takes a deadline of its own, **below** the host's, and on trip
   emits something honest instead of being killed with nothing.
2. **A slow run leaves no evidence.** There was no timing instrumentation anywhere in this codebase,
   which is why the question "what was slow?" has never had an answer on either side. A run that
   exceeds ``slow_run_ms`` now appends its phase breakdown to a gitignored ring buffer, so the *next*
   occurrence in the field answers itself (``yigraf doctor``).

**Not raising the 15 s**, which was the field's second ask. The number is ours, but a hook that blocks
an agent for fifteen seconds already violates design law #5; raising it buys a slower failure rather
than a rarer one. Our budget belongs under the host's, not above it.

**The deadline is advisory, never a correctness boundary.** It is armed with ``SIGALRM`` where the
platform has it and simply absent where it does not (Windows), because a budget that fails closed
would itself be a way to lose the packet. Everything it interrupts is either a read or the
materialized view's own write, and that write already degrades by design (R6: the view is a
recomputable projection, and `load_or_build` answers from the build when it cannot persist).
"""
from __future__ import annotations

import json
import os
import signal
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from yigraf import sidecar

#: Seconds yigraf gives itself, under the host's 15. Not a measurement — a margin: it leaves room to
#: render a fallback and be read, where a budget at the host's own number would be killed mid-write.
DEFAULT_DEADLINE_SECONDS = 10.0

#: A run at or above this many milliseconds is worth recording. Below it the ledger stays untouched,
#: so the ordinary sub-second run costs one comparison and no I/O (design law #4 applied to disk).
DEFAULT_SLOW_RUN_MS = 2000

#: Ring-buffer depth. Small on purpose: the question is "what was slow last time", not a time series.
DEFAULT_TIMINGS_KEPT = 50

LEDGER_NAME = "hook-timings.json"


class DeadlineExceeded(Exception):
    """Raised in the hook's own process when its wall-clock budget expires.

    Caught by the handler, which emits its degraded answer. Never propagated to the host: ``_run_hook``
    is fail-open and exits 0 regardless.
    """


@dataclass
class Budget:
    """A hook's wall-clock budget and phase timer, armed for the life of a ``with`` block.

    Usage is one block per hook invocation, with each expensive step named::

        with Budget(root, "SessionStart", config) as budget:
            with budget.phase("graph"):
                ...

    ``phase`` names are the vocabulary ``yigraf doctor`` reports in, so they are the coarse steps a
    reader would ask about — not every function call. An unnamed stretch is still inside the deadline;
    it just does not appear in the breakdown.
    """
    root: Path
    event: str
    config: dict = field(default_factory=dict)
    phases: list[tuple[str, int]] = field(default_factory=list)
    tripped: bool = False
    started: float = 0.0
    _armed: bool = False
    _previous: object = None

    # --- the deadline ---------------------------------------------------------------------------

    @property
    def seconds(self) -> float:
        raw = (self.config.get("hooks") or {}).get("deadline_seconds", DEFAULT_DEADLINE_SECONDS)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return DEFAULT_DEADLINE_SECONDS

    def __enter__(self) -> "Budget":
        self.started = time.perf_counter()
        seconds = self.seconds
        # `<= 0` disarms it deliberately: a store that would rather be killed by the host than serve a
        # degraded packet can say so, and the tests use it to prove the un-armed path still works.
        if seconds > 0 and hasattr(signal, "SIGALRM"):
            try:
                self._previous = signal.signal(signal.SIGALRM, self._fire)
                signal.setitimer(signal.ITIMER_REAL, seconds)
                self._armed = True
            except (ValueError, OSError):
                self._armed = False  # not the main thread, or no itimer — run unbounded, fail-open
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.disarm()
        if exc_type is DeadlineExceeded:
            self.tripped = True
        self._record()
        return False  # the handler decides what a trip means; never swallowed here

    def _fire(self, signum, frame):
        # Marked HERE, not in `__exit__`: every handler catches `DeadlineExceeded` inside its own
        # `with` block, so the exception never reaches `__exit__` and a trip recorded there would be
        # recorded only when nobody degraded gracefully — i.e. never, on exactly the runs the ledger
        # exists for.
        self.tripped = True
        raise DeadlineExceeded(f"{self.event} exceeded {self.seconds:g}s")

    def disarm(self) -> None:
        """Stop the clock. Idempotent, and safe to call from a handler that already caught the trip."""
        if not self._armed:
            return
        self._armed = False
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
            if self._previous is not None:
                signal.signal(signal.SIGALRM, self._previous)
        except (ValueError, OSError, TypeError):
            pass

    # --- the phase timer ------------------------------------------------------------------------

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    @contextmanager
    def phase(self, name: str):
        """Time one named step. Records even when the step raises — a phase that died is the one to see."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.phases.append((name, int((time.perf_counter() - start) * 1000)))

    def note(self, name: str, value: int = 0) -> None:
        """Record a non-timing fact as a ledger row (``cached=1``, ``nodes=2404``) — same vocabulary."""
        self.phases.append((name, int(value)))

    # --- the ledger -----------------------------------------------------------------------------

    def _record(self) -> None:
        """Append this run to the ring buffer if it was slow or tripped. Silent on any failure (law #5)."""
        total = self.elapsed_ms
        threshold = (self.config.get("hooks") or {}).get("slow_run_ms", DEFAULT_SLOW_RUN_MS)
        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            threshold = DEFAULT_SLOW_RUN_MS
        if not self.tripped and total < threshold:
            return
        kept = (self.config.get("hooks") or {}).get("timings_kept", DEFAULT_TIMINGS_KEPT)
        try:
            kept = max(1, int(kept))
        except (TypeError, ValueError):
            kept = DEFAULT_TIMINGS_KEPT
        row = {"at": time.time(), "event": self.event, "total_ms": total,
               "deadline_s": self.seconds, "tripped": self.tripped,
               "phases": [{"name": n, "ms": ms} for n, ms in self.phases],
               "pid": os.getpid()}
        try:
            path = ledger_path(self.root)
            # One transaction: a burst of concurrent hooks is the case this ledger exists to explain, and
            # unlocked, each read the same buffer and overwrote the others' rows (feedback-v12 L#1).
            with sidecar.locked(path):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = []
                rows = [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
                rows = rows[-(kept - 1):] if kept > 1 else []
                rows.append(row)
                sidecar.write_atomic(path, json.dumps(rows))
        except OSError:
            pass


def ledger_path(root: Path) -> Path:
    """Where slow-run rows live: gitignored machine-local state, never the graph (design law #6)."""
    from yigraf.cli import WORKSPACE_DIRNAME  # local: cli imports this module at call time, not import
    return Path(root) / WORKSPACE_DIRNAME / ".local" / LEDGER_NAME


def read_ledger(root: Path) -> list[dict]:
    """Every recorded slow run, oldest first. Empty on anything unreadable — this is a report, not a gate."""
    try:
        data = json.loads(ledger_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []

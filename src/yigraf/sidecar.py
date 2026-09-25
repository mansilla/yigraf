"""Machine-local JSON sidecars: one lock and one atomic write for every read-modify-write (feedback-v12 L#1).

Everything under ``.local/`` and ``cache/`` is derived, gitignored state (design law #6), and most of it
is written by hooks — which an agent editing several files runs **concurrently**. Every one of those
writes was ``read_text`` → ``json.loads`` → mutate → ``write_text``, and the field measured what that
costs: 8 concurrent hooks kept 6–7 slow-run rows, 4 kept 2; 16 concurrent surfacing bumps landed as
``usage=7``. Two defects, and each half below fixes a different one:

- **Lost updates** — two writers read the same buffer and the later write discards the earlier one's
  change. Only a lock held *across* the read and the write closes this; an atomic write alone does not
  (the field built that first and measured it insufficient). On ``emitted.json`` a lost update is a
  duplicate packet injected into the agent; on ``telemetry.json`` it is an undercounted ranking signal.
- **Torn reads** — ``write_text`` truncates in place, so a lock-free reader (``doctor``, another hook's
  ``load``) can parse a prefix, fall back to empty, and discard *everything*. On ``cache/structure.json``
  that empty fallback is a cold re-extract of every source file inside a hook's budget. A sibling temp
  file plus ``os.replace`` closes it.

Not a departure from int:concurrent-write-model, which resolves writes to the **graph** by log-append
precisely so that nothing committed is ever lockable. These files are neither committed nor graph: they
are per-machine caches and counters with no merge story, and a lock here is held for one small read and
one rename.

Fail-open throughout (design law #5): no ``fcntl`` (Windows), a filesystem that cannot lock, or a wait
past ``LOCK_WAIT_SECONDS`` all fall through to an unlocked — but still atomic — write. That degraded path
is the pre-1.16 behaviour minus the torn read, so it can lose one update and never more.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path

#: How long a writer waits for another's critical section before writing unlocked. Short because some
#: callers sit outside the hook deadline (``Budget.__exit__`` disarms the alarm before recording), so a
#: wait here adds to a run that may already have spent its budget. The critical section is one small read
#: and one rename; a wait this long means something is wrong, and giving up costs one update.
LOCK_WAIT_SECONDS = 0.25


@contextmanager
def locked(path: Path):
    """Hold an exclusive lock over ``path``'s read-modify-write for the body of the block. Never raises.

    The lock is a **sibling** ``<name>.lock``, not ``path`` itself: :func:`write_atomic` replaces
    ``path``'s inode, so a lock on it would be held on a file no later writer can see — each waiter would
    serialise against a different inode, which is no lock at all. The caller does not branch on whether
    the lock was taken; see the module docstring for why writing unlocked is the right degradation.
    """
    fd = _acquire(Path(path).with_name(Path(path).name + ".lock"))
    try:
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)  # closing the descriptor is what releases an flock
            except OSError:
                pass


def _acquire(lock: Path) -> int | None:
    """Open ``lock`` and take an exclusive flock on it, or return None. Never raises.

    Separate from :func:`locked` so no failure of the *caller's body* can be mistaken for a failure to
    lock — an ``except OSError`` around a ``yield`` swallows what the body raised and resumes the
    generator.
    """
    try:
        import fcntl
    except ImportError:
        return None  # Windows: no flock — write unlocked rather than not at all
    fd = None
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_WRONLY, 0o644)
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.005)
    except OSError:
        pass
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    return None


def write_atomic(path: Path, text: str) -> None:
    """Replace ``path``'s contents in one step, so no reader can observe it half-written.

    The temp file is a per-process sibling: same directory so ``os.replace`` stays on one filesystem
    (where it is atomic), per-pid so two concurrent writers never share — and clobber — one temp file.
    Raises ``OSError`` like ``write_text`` did, so every caller's existing best-effort ``except`` holds.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise

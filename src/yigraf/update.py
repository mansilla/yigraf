"""Daily-throttled "is there a newer yigraf on PyPI?" check (int:status-surface).

Surfaced as an ``⬆ <version>`` marker on the statusline so the human notices an available update on a
refresh they already pay for — it is *not* the agent's concern, so it rides the human ambient surface,
never a hook injection (design law #4: don't spend the agent's attention budget). The result is cached
in the gitignored ``.local/`` sidecar (R1 / mem:006 — volatile, machine-local, never the committed
``graph.json``) and refreshed at most once a day. The network fetch is time-boxed and fail-open, so an
offline machine or a slow PyPI never blocks or breaks the statusline; ``checked_at`` is stamped even on
a failed fetch so we don't re-hit the network on every refresh while offline.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

#: PyPI's JSON metadata endpoint; ``info.version`` is the latest released version.
PYPI_JSON_URL = "https://pypi.org/pypi/yigraf/json"
_TTL_SECONDS = 24 * 60 * 60  # check at most once per day


def _cache_path(root: Path) -> Path:
    return Path(root) / "yigraf" / ".local" / "update-check.json"


def _parse(v: str) -> tuple[int, ...]:
    """A best-effort numeric tuple for comparison (``"0.1.8"`` → ``(0, 1, 8)``); odd input → ``()``."""
    try:
        return tuple(int(p) for p in v.split("+")[0].split(".") if p.isdigit())
    except (AttributeError, ValueError):
        return ()


def _is_newer(latest: str, current: str) -> bool:
    """Is ``latest`` a higher release than ``current``? Requires a real (≥ major.minor) current."""
    lt, ct = _parse(latest), _parse(current)
    return len(ct) >= 2 and lt > ct  # guards "0+unknown" (a raw checkout) → no marker


def _fetch_latest(timeout: float = 2.0) -> str | None:
    """The latest version string from PyPI, or ``None`` on any network/parse failure (fail-open)."""
    try:
        with urllib.request.urlopen(PYPI_JSON_URL, timeout=timeout) as resp:  # noqa: S310 — fixed https URL
            return json.load(resp)["info"]["version"]
    except Exception:  # noqa: BLE001 — an ambient check must never raise (design law #5)
        return None


def refresh(root: Path, *, fetch=_fetch_latest, now: float | None = None) -> None:
    """At most once per TTL, fetch the latest PyPI version into the sidecar cache. Fail-open.

    ``fetch``/``now`` are injectable so tests drive this without touching the network or the clock.
    """
    now = time.time() if now is None else now
    path = _cache_path(root)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if now - cached.get("checked_at", 0) < _TTL_SECONDS:
            return  # checked recently — no network this refresh
    except (OSError, json.JSONDecodeError):
        cached = {}
    latest = fetch()
    # Stamp checked_at even when the fetch failed, so we don't retry every refresh while offline;
    # keep the last known latest so the marker survives a transient outage.
    record = {"checked_at": now, "latest": latest or cached.get("latest")}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
    except OSError:
        pass


def available(root: Path, current: str) -> str | None:
    """The cached latest version if it's newer than ``current``, else ``None`` (a pure file read)."""
    try:
        latest = json.loads(_cache_path(root).read_text(encoding="utf-8")).get("latest")
    except (OSError, json.JSONDecodeError):
        return None
    return latest if latest and _is_newer(latest, current) else None

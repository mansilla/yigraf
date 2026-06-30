"""Daily-throttled PyPI update check (int:status-surface) — cache logic, throttle, fail-open."""
import json
from pathlib import Path

from yigraf import update

_DAY = 24 * 60 * 60


def _write_cache(root: Path, **fields) -> Path:
    path = root / "yigraf" / ".local" / "update-check.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields))
    return path


def _cache(root: Path) -> dict:
    return json.loads((root / "yigraf" / ".local" / "update-check.json").read_text())


def test_available_reports_a_newer_version(tmp_path: Path):
    _write_cache(tmp_path, checked_at=0, latest="0.2.0")
    assert update.available(tmp_path, "0.1.8") == "0.2.0"


def test_available_is_silent_when_current_is_latest(tmp_path: Path):
    _write_cache(tmp_path, checked_at=0, latest="0.1.8")
    assert update.available(tmp_path, "0.1.8") is None


def test_available_is_silent_without_a_cache(tmp_path: Path):
    assert update.available(tmp_path, "0.1.8") is None


def test_available_is_silent_for_an_unknown_current_version(tmp_path: Path):
    _write_cache(tmp_path, checked_at=0, latest="0.2.0")
    assert update.available(tmp_path, "0+unknown") is None  # a raw checkout must not nag


def test_refresh_is_throttled_within_the_ttl(tmp_path: Path):
    _write_cache(tmp_path, checked_at=1_000.0, latest="0.1.8")
    calls = []
    update.refresh(tmp_path, fetch=lambda: calls.append(1) or "9.9.9", now=1_000.0 + 60)
    assert calls == []  # checked a minute ago ⇒ no network this refresh
    assert _cache(tmp_path)["latest"] == "0.1.8"  # cache untouched


def test_refresh_fetches_when_stale_and_writes_cache(tmp_path: Path):
    _write_cache(tmp_path, checked_at=0.0, latest="0.1.8")
    update.refresh(tmp_path, fetch=lambda: "0.3.0", now=10 * _DAY)
    assert update.available(tmp_path, "0.1.8") == "0.3.0"


def test_refresh_is_fail_open_and_keeps_last_known(tmp_path: Path):
    _write_cache(tmp_path, checked_at=0.0, latest="0.2.0")
    update.refresh(tmp_path, fetch=lambda: None, now=10 * _DAY)  # offline ⇒ fetch yields nothing
    data = _cache(tmp_path)
    assert data["checked_at"] == 10 * _DAY  # stamped, so we don't re-hit the network every refresh
    assert data["latest"] == "0.2.0"  # last known kept, marker survives the outage


def test_refresh_first_run_creates_the_cache(tmp_path: Path):
    update.refresh(tmp_path, fetch=lambda: "1.0.0", now=123.0)
    assert _cache(tmp_path) == {"checked_at": 123.0, "latest": "1.0.0"}

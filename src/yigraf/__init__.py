"""yigraf — one connected graph over code, intent, plan, and memory."""

from importlib.metadata import PackageNotFoundError, version

try:  # single source of truth is pyproject's version, read from installed metadata — never hand-synced
    __version__ = version("yigraf")
except PackageNotFoundError:  # not installed (e.g. running from a raw checkout) — unknown, not a lie
    __version__ = "0+unknown"

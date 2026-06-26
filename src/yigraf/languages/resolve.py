"""Shared import-resolution toolkit.

Import → file resolution is the one genuinely per-language part of extraction (every module system
differs), but most of it reduces to two reusable strategies, so each language's "extra layer" is just
*which* strategy + how to read its specifiers:

- :func:`resolve_relative` — a path relative to the importing file (C ``#include "x.h"``, Ruby
  ``require_relative``, Rust ``mod``, JS ``./x``): join + normalize, then try the language's
  extensions and ``index``/``mod`` package files.
- :func:`resolve_segments` — a dotted/namespaced name mapping to a path by convention (Java
  ``com.foo.Bar`` → ``com/foo/Bar.java``): match the segments against the tail of a repo file path.
"""
from __future__ import annotations

import posixpath


def resolve_relative(base_dir: str, spec: str, relset: set[str], exts: tuple[str, ...]) -> str | None:
    """A relative ``spec`` from ``base_dir`` → a repo relpath, trying extensions + ``index``/``mod``."""
    raw = posixpath.normpath(f"{base_dir}/{spec}" if base_dir not in ("", ".") else spec)
    candidates = [raw]
    candidates += [raw + ext for ext in exts]
    candidates += [f"{raw}/index{ext}" for ext in exts]  # JS/TS package entry
    candidates += [f"{raw}/mod{ext}" for ext in exts]     # Rust module folder
    for candidate in candidates:
        if candidate in relset:
            return candidate
    return None


def resolve_segments(segments: list[str], relset: set[str], exts: tuple[str, ...]) -> str | None:
    """Dotted/namespaced ``segments`` → the repo relpath whose path tail matches (e.g. Java packages)."""
    segments = [s for s in segments if s]
    if not segments:
        return None
    tail = "/".join(segments)
    for ext in exts:
        suffix = f"{tail}{ext}"
        for relpath in relset:
            if relpath == suffix or relpath.endswith("/" + suffix):
                return relpath
    return None

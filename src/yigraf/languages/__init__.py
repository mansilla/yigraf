"""Language extractor registry.

Maps file suffixes to extractors, gated by the workspace ``languages`` config. Grammars load lazily
(in each extractor's ``ts_language``), so importing this package never requires an optional grammar
to be installed; a configured language whose grammar is missing is simply skipped — the same
graceful degradation the embedding backends use.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from yigraf.languages.base import FileProjection, LanguageExtractor
from yigraf.languages.go import GoExtractor
from yigraf.languages.jsts import JsTsExtractor
from yigraf.languages.python import PythonExtractor
from yigraf.languages.tags import GENERIC_EXTRACTORS, VENDORED_EXTRACTORS

#: Implemented extractors, in suffix-resolution order (first match wins on a shared suffix). Bespoke
#: extractors come first, then tags-query extractors (grammar-shipped, then yigraf-vendored).
_ALL: tuple[LanguageExtractor, ...] = (
    PythonExtractor(), GoExtractor(), JsTsExtractor(), *GENERIC_EXTRACTORS, *VENDORED_EXTRACTORS,
)

__all__ = [
    "FileProjection",
    "LanguageExtractor",
    "all_extractors",
    "enabled_extractors",
    "available_extractors",
    "extension_map",
    "extractor_for_path",
]


def all_extractors() -> tuple[LanguageExtractor, ...]:
    """Every implemented extractor, regardless of config (used by the back-compat dispatch)."""
    return _ALL


def enabled_extractors(config: dict) -> list[LanguageExtractor]:
    """Extractors whose name (or an alias) is listed in config ``languages``, in registration order.

    An extractor that spans several config names (e.g. the JS/TS one, enabled by ``javascript`` *or*
    ``typescript``) is still returned once.
    """
    names = set(config.get("languages") or [])
    return [e for e in _ALL if names & ({e.name} | set(e.aliases))]


def available_extractors(config: dict) -> list[LanguageExtractor]:
    """Enabled extractors whose tree-sitter grammar can actually be imported (else skipped)."""
    out: list[LanguageExtractor] = []
    for extractor in enabled_extractors(config):
        try:
            extractor.ts_language()
        except Exception:
            continue  # grammar not installed → graceful skip (fail-open, never crash a build/hook)
        out.append(extractor)
    return out


def extension_map(extractors) -> dict[str, LanguageExtractor]:
    """Map each handled file suffix to its extractor (first registered wins on collision)."""
    out: dict[str, LanguageExtractor] = {}
    for extractor in extractors:
        for ext in extractor.extensions:
            out.setdefault(ext, extractor)
    return out


def extractor_for_path(relpath: str, extractors) -> LanguageExtractor | None:
    """The extractor handling ``relpath``'s suffix among ``extractors``, or ``None``."""
    return extension_map(extractors).get(PurePosixPath(relpath).suffix)
